"""争用失败测：强制结与灌入并发，不得半栏双写、不得双成功。"""
import json
import threading

from app.db import 连接
from app.services import 装载, 结栏, 贯验
from app.services.写闸 import 强制结


def _装载体(序号: int) -> dict:
    return {"批次编号": f"竞-{序号}", "报文": [{
        "报文编号": f"P-race-{序号}",
        "站点键": "站-河东",
        "指标键": "PM25",
        "读数": 20.0 + (序号 % 10),
        "观测时": f"2026-11-25T{1 + (序号 % 10):02d}:00:00Z",
    }]}


def test_强制结与灌入并发不得半栏双写():
    for i in range(20):
        装载.装一批(_装载体(i))  # 水位 1，未过阈（阈值 3）
        果: dict = {}
        闸 = threading.Barrier(2)

        def 强() -> None:
            闸.wait()
            try:
                果["强"] = 结栏.结当前栏(强制结)
            except ValueError as e:
                果["强"] = e

        def 灌() -> None:
            闸.wait()
            try:
                果["灌"] = 装载.装一批(_装载体(100 + i))
            except ValueError as e:
                果["灌"] = e

        t1 = threading.Thread(target=强)
        t2 = threading.Thread(target=灌)
        t1.start(); t2.start(); t1.join(); t2.join()

        conn = 连接()
        try:
            影子 = {r["报文编号"] for r in conn.execute(
                "SELECT 报文编号 FROM 入栏缓冲 WHERE 命运='影子结栏'").fetchall()}
            在栏 = {r["报文编号"] for r in conn.execute(
                "SELECT 报文编号 FROM 入栏缓冲 WHERE 命运='在栏'").fetchall()}
            凭证行 = conn.execute(
                "SELECT 报文集合, 报文数 FROM 强制结凭证 WHERE 栏号='B-demo'"
            ).fetchall()
            正式报文 = conn.execute(
                "SELECT COALESCE(SUM(报文数),0) AS c FROM 站点汇总账").fetchone()["c"]
            封印数 = conn.execute(
                "SELECT COUNT(*) AS c FROM 栏封印 WHERE 栏号='B-demo'").fetchone()["c"]
        finally:
            conn.close()

        凭证集 = set()
        for v in 凭证行:
            集 = set(json.loads(v["报文集合"]))
            assert v["报文数"] == len(集)
            凭证集 |= 集

        # 任一回合必须收敛为：恰好一次封印、一张影子凭证
        assert 封印数 == 1
        assert len(凭证行) == 1
        # 凭证与缓冲命运同票
        assert 影子 == 凭证集
        # 不得半栏：不允许有报文既不在凭证、又以在栏残留（双写/双成功的典型形态）
        assert 在栏 == set()
        assert 影子.isdisjoint(在栏)
        # 未过阈强制结永不产生正式汇总
        assert 正式报文 == 0
        # 两报文总去向：凭证 + 封印驳回，合计 2
        灌果 = 果["灌"]
        if isinstance(灌果, dict):
            assert 灌果["入栏"] + 灌果["封印驳回"] == 1
        assert isinstance(果["强"], dict)

        snap = 贯验.只读快照()
        assert snap["是否对齐"] is True

        # 清场进入下一回合：换栏号不现实，直接重建库
        from app import seed
        conn = 连接()
        try:
            for 表 in ("入栏缓冲", "观测报文", "强制结凭证", "栏封印", "站点汇总账",
                       "栏贯验", "装载批次", "结栏批次", "坏点匣"):
                conn.execute(f"DELETE FROM {表}")
            conn.commit()
        finally:
            conn.close()
