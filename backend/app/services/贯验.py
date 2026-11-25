"""栏贯验：已汇总缓冲报文数 == 汇总账报文数之和。

双轨：
- 正式轨：入栏缓冲“已汇总”笔数 == 站点汇总账报文数之和。
- 影子轨：未过阈强制结的“影子结栏”笔数 == 强制结凭证报文数之和，
  且凭证指纹可由缓冲侧重算复核（篡改即红）；封印水位与凭证同票复核。
贯验服务独立重算，不采信结栏服务自报，结栏假绿与统计假绿在此分治。
"""
from __future__ import annotations
from app.db import 连接
from app.seed import 此刻
from app.services.结栏 import 指纹计算


def _影子对账(conn) -> dict:
    影子行 = conn.execute(
        "SELECT 报文编号, 栏号 FROM 入栏缓冲 WHERE 命运='影子结栏'"
    ).fetchall()
    影子按栏: dict[str, list[str]] = {}
    for r in 影子行:
        影子按栏.setdefault(r["栏号"], []).append(r["报文编号"])
    凭证 = conn.execute("SELECT * FROM 强制结凭证").fetchall()

    指纹合法 = True
    毛病: list[str] = []
    凭证按栏: dict[str, int] = {}
    for v in 凭证:
        凭证按栏[v["栏号"]] = 凭证按栏.get(v["栏号"], 0) + int(v["报文数"])
        期望 = 指纹计算(v["栏号"], 影子按栏.get(v["栏号"], []), len(影子按栏.get(v["栏号"], [])))
        if v["指纹"] != 期望:
            指纹合法 = False
            毛病.append(f"凭证{v['凭证编号']}指纹对不上缓冲重算")
        # 水位与指纹同票：凭证记录的水位必须等于其报文集合大小
        if int(v["水位"]) != int(v["报文数"]):
            指纹合法 = False
            毛病.append(f"凭证{v['凭证编号']}水位{ v['水位']}≠报文数{v['报文数']}")

    影子报文 = len(影子行)
    凭证报文 = sum(int(v["报文数"]) for v in 凭证)
    if 影子报文 != 凭证报文:
        指纹合法 = False
        毛病.append(f"影子缓冲={影子报文} 凭证报文={凭证报文} 两轨撕裂")
    if set(影子按栏) != set(凭证按栏):
        指纹合法 = False
        毛病.append("影子缓冲栏号集合与凭证栏号集合不一致")

    # 水位对账：封印必须钉到一张同指纹票（未过阈强制结的凭证）
    水位毛病: list[str] = []
    封印 = conn.execute("SELECT * FROM 栏封印").fetchall()
    在栏未结 = conn.execute(
        "SELECT 栏号, COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='在栏' GROUP BY 栏号"
    ).fetchall()
    规行 = {r["键"]: r["值"] for r in conn.execute("SELECT 键,值 FROM 栏规").fetchall()}
    try:
        阈 = max(1, int(float(规行.get("结栏水位阈", "3"))))
    except (TypeError, ValueError):
        阈 = 3
    封印栏 = {s["栏号"] for s in 封印}
    for r in 在栏未结:
        if r["栏号"] not in 封印栏:
            水位毛病.append(
                f"栏{r['栏号']}在栏{ r['c']}笔未过阈({阈})且未结栏，不得标合法绿"
            )
    for s in 封印:
        if s["闸形态"] == "强制结":
            v = conn.execute(
                "SELECT * FROM 强制结凭证 WHERE 栏号=? ORDER BY 时刻 DESC LIMIT 1",
                (s["栏号"],),
            ).fetchone()
            if v is None:
                水位毛病.append(f"栏{s['栏号']}强制结封印缺只读凭证")
            elif s["指纹"] != v["指纹"] or int(s["水位"]) != int(v["报文数"]):
                水位毛病.append(f"栏{s['栏号']}封印指纹/水位与凭证不同票")
        if int(s["水位"]) < 1:
            水位毛病.append(f"栏{s['栏号']}空水位封印非法")
    水位合法 = not 水位毛病 and (not 凭证 or 指纹合法)

    return {
        "影子报文数": 影子报文,
        "凭证报文数": 凭证报文,
        "影子指纹合法": 指纹合法,
        "水位对账": {"合法": 水位合法, "毛病": 毛病 + 水位毛病},
    }


def 跑一次() -> dict:
    conn = 连接()
    try:
        在栏 = conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='在栏'"
        ).fetchone()["c"]
        已汇总缓冲 = conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='已汇总'"
        ).fetchone()["c"]
        汇总报文 = conn.execute(
            "SELECT COALESCE(SUM(报文数),0) AS c FROM 站点汇总账"
        ).fetchone()["c"]
        坏点 = conn.execute("SELECT COUNT(*) AS c FROM 坏点匣").fetchone()["c"]
        影 = _影子对账(conn)
        正式对齐 = int(已汇总缓冲) == int(汇总报文)
        对齐 = 1 if (正式对齐 and 影["影子指纹合法"] and 影["水位对账"]["合法"]) else 0
        毛病 = []
        if not 正式对齐:
            毛病.append(f"撕裂：已汇总缓冲={已汇总缓冲} 汇总报文={汇总报文}")
        毛病.extend(影["水位对账"]["毛病"])
        if 在栏 and not conn.execute("SELECT 1 FROM 栏封印").fetchone():
            毛病.append(f"在栏{在栏}笔未过阈且未结栏，水位对账不得标绿")
        说明 = "入栏已汇总与站点汇总报文数一致，影子凭证指纹复核通过" if 对齐 else "; ".join(毛病) or "对账未过"
        时刻 = 此刻()
        conn.execute(
            """INSERT INTO 栏贯验(时刻,在栏笔数,汇总报文数,坏点笔数,是否对齐,说明)
               VALUES (?,?,?,?,?,?)""",
            (时刻, 在栏, int(汇总报文), 坏点, 对齐, 说明),
        )
        conn.commit()
        return {
            "时刻": 时刻,
            "在栏": 在栏,
            "已汇总缓冲": int(已汇总缓冲),
            "汇总报文": int(汇总报文),
            "坏点": 坏点,
            "影子报文数": 影["影子报文数"],
            "凭证报文数": 影["凭证报文数"],
            "影子指纹合法": 影["影子指纹合法"],
            "水位对账": 影["水位对账"],
            "是否对齐": bool(对齐),
            "说明": 说明,
        }
    finally:
        conn.close()


def 只读快照() -> dict:
    """不落库的贯验快照，供页面预览。双轨独立重算。"""
    conn = 连接()
    try:
        在栏 = conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='在栏'"
        ).fetchone()["c"]
        已汇总缓冲 = conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='已汇总'"
        ).fetchone()["c"]
        汇总报文 = conn.execute(
            "SELECT COALESCE(SUM(报文数),0) AS c FROM 站点汇总账"
        ).fetchone()["c"]
        坏点 = conn.execute("SELECT COUNT(*) AS c FROM 坏点匣").fetchone()["c"]
        影 = _影子对账(conn)
        正式对齐 = int(已汇总缓冲) == int(汇总报文)
        有在栏未结 = bool(在栏) and conn.execute(
            "SELECT 1 FROM 栏封印"
        ).fetchone() is None
        对齐 = (
            正式对齐 and 影["影子指纹合法"] and 影["水位对账"]["合法"]
            and not 有在栏未结
        )
        return {
            "在栏": 在栏,
            "已汇总缓冲": int(已汇总缓冲),
            "汇总报文": int(汇总报文),
            "坏点": 坏点,
            "影子报文数": 影["影子报文数"],
            "凭证报文数": 影["凭证报文数"],
            "影子指纹合法": 影["影子指纹合法"],
            "水位对账": 影["水位对账"],
            "是否对齐": 对齐,
        }
    finally:
        conn.close()
