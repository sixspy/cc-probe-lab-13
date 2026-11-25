"""结栏：入栏缓冲按站点+指标汇总物化。

写闸形态（app.services.写闸）：
- 正式结：水位过阈才放行，物化进站点汇总账（正式轨），缓冲命运置“已汇总”。
- 强制结：未过阈只写只读归档凭证（影子轨），正式汇总不增行，缓冲命运置“影子结栏”。
读水位与写汇总在同一把写锁、同一事务内，同票同成败。
"""
from __future__ import annotations
import hashlib
import json
import uuid
from collections import defaultdict
from app.db import 连接
from app.seed import 此刻
from app.services import 目录
from app.services.写闸 import 写锁, 校验闸形态, 正式结, 强制结


def 指纹计算(栏号: str, 报文集合: list[str], 水位: int) -> str:
    体 = json.dumps(
        {"栏号": 栏号, "水位": 水位, "报文": sorted(报文集合)},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(体.encode("utf-8")).hexdigest()


def _水位阈(规: dict) -> int:
    try:
        return max(1, int(float(规.get("结栏水位阈", "3"))))
    except (TypeError, ValueError):
        return 3


def _封印查(conn, 栏号: str) -> dict | None:
    r = conn.execute("SELECT * FROM 栏封印 WHERE 栏号=?", (栏号,)).fetchone()
    return dict(r) if r else None


def 结当前栏(闸形态: str | None = 正式结) -> dict:
    校验闸形态(闸形态)
    规 = 目录.栏规()
    栏号 = 规.get("当前栏号", "B-demo")
    阈 = _水位阈(规)
    批 = f"结栏-{uuid.uuid4().hex[:8]}"
    时刻 = 此刻()
    with 写锁:
        conn = 连接()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if _封印查(conn, 栏号):
                raise ValueError(f"栏 {栏号} 已封印写闸，禁止回刷再结")
            rows = conn.execute(
                "SELECT * FROM 入栏缓冲 WHERE 栏号=? AND 命运='在栏'", (栏号,)
            ).fetchall()
            水位 = len(rows)
            编号集 = [r["报文编号"] for r in rows]
            指纹 = 指纹计算(栏号, 编号集, 水位)

            if 水位 == 0:
                raise ValueError("空栏禁止结栏（空栏封印另属其桩）")

            过阈 = 水位 >= 阈
            if 闸形态 == 强制结 and 过阈:
                raise ValueError(
                    f"水位 {水位} 已过阈 {阈}：强制结仅限未满栏，过阈须走正式结"
                )

            报告 = {
                "批次编号": 批,
                "栏号": 栏号,
                "闸形态": 闸形态,
                "水位": 水位,
                "阈值": 阈,
                "指纹": 指纹,
                "空栏": False,
            }

            if 闸形态 == 强制结:
                凭证编号 = f"凭-{栏号}-{uuid.uuid4().hex[:8]}"
                conn.execute(
                    """INSERT INTO 强制结凭证
                       (凭证编号,结栏批次编号,栏号,时刻,报文数,水位,阈值,报文集合,指纹)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (凭证编号, 批, 栏号, 时刻, 水位, 水位, 阈,
                     json.dumps(编号集, ensure_ascii=False), 指纹),
                )
                for e in rows:
                    conn.execute(
                        "UPDATE 入栏缓冲 SET 命运=? WHERE 报文编号=?",
                        ("影子结栏", e["报文编号"]),
                    )
                conn.execute(
                    "INSERT INTO 栏封印(栏号,时刻,闸形态,水位,指纹) VALUES (?,?,?,?,?)",
                    (栏号, 时刻, 强制结, 水位, 指纹),
                )
                报告.update({
                    "影子": True,
                    "汇总数": 0,
                    "缓冲消耗": 0,
                    "凭证编号": 凭证编号,
                    "明细": [],
                })
            else:
                if 水位 < 阈:
                    raise ValueError(
                        f"水位 {水位} 未过阈 {阈}：正式结写闸拒绝，请显式走强制结"
                    )
                groups: dict[tuple[str, str], list] = defaultdict(list)
                for r in rows:
                    groups[(r["站点键"], r["指标键"])].append(r)
                汇总 = 0
                明细 = []
                for (站点, 指标), evs in groups.items():
                    均值 = sum(float(e["读数"]) for e in evs) / len(evs)
                    编号 = f"汇-{栏号}-{站点}-{指标}-{uuid.uuid4().hex[:6]}"
                    conn.execute(
                        """INSERT INTO 站点汇总账(汇总编号,栏号,站点键,指标键,报文数,均值,物化时,命运)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (编号, 栏号, 站点, 指标, len(evs), 均值, 时刻, "已汇总"),
                    )
                    for e in evs:
                        conn.execute(
                            "UPDATE 入栏缓冲 SET 命运=? WHERE 报文编号=?",
                            ("已汇总", e["报文编号"]),
                        )
                        conn.execute(
                            "UPDATE 观测报文 SET 命运=? WHERE 报文编号=?",
                            ("已汇总", e["报文编号"]),
                        )
                    汇总 += 1
                    明细.append({
                        "汇总编号": 编号,
                        "站点键": 站点,
                        "指标键": 指标,
                        "报文数": len(evs),
                        "均值": round(均值, 4),
                    })
                conn.execute(
                    "INSERT INTO 栏封印(栏号,时刻,闸形态,水位,指纹) VALUES (?,?,?,?,?)",
                    (栏号, 时刻, 正式结, 水位, 指纹),
                )
                报告.update({
                    "影子": False,
                    "汇总数": 汇总,
                    "缓冲消耗": 水位,
                    "明细": 明细,
                })

            conn.execute(
                """INSERT INTO 结栏批次(编号,栏号,时刻,汇总数,报告,闸形态,影子)
                   VALUES (?,?,?,?,?,?,?)""",
                (批, 栏号, 时刻, 报告["汇总数"],
                 json.dumps(报告, ensure_ascii=False), 闸形态,
                 1 if 报告["影子"] else 0),
            )
            conn.commit()
            return 报告
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def 预览结栏() -> dict:
    """只读：当前栏在栏缓冲按站点指标分组，不写库。附水位阈值与封印/闸态。"""
    规 = 目录.栏规()
    栏号 = 规.get("当前栏号", "B-demo")
    阈 = _水位阈(规)
    conn = 连接()
    try:
        rows = conn.execute(
            "SELECT * FROM 入栏缓冲 WHERE 栏号=? AND 命运='在栏'", (栏号,)
        ).fetchall()
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for r in rows:
            groups[(r["站点键"], r["指标键"])].append(dict(r))
        预览 = []
        for (站点, 指标), evs in sorted(groups.items()):
            预览.append({
                "站点键": 站点,
                "指标键": 指标,
                "报文数": len(evs),
                "均值": round(sum(float(e["读数"]) for e in evs) / len(evs), 4),
            })
        封印 = _封印查(conn, 栏号)
        水位 = len(rows)
        过阈 = 水位 >= 阈
        if 水位 == 0 or 封印:
            可选闸 = []
        elif 过阈:
            可选闸 = [正式结]
        else:
            可选闸 = [强制结]
        return {
            "栏号": 栏号,
            "在栏": 水位,
            "水位阈": 阈,
            "过阈": 过阈,
            "已封印": 封印 is not None,
            "封印": 封印,
            "可选闸形态": 可选闸,
            "将汇总组": 预览,
        }
    finally:
        conn.close()
