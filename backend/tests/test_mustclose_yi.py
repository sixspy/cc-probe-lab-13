"""失败测乙：水位对账不得把未过阈结栏错标合法绿；结栏假绿与统计假绿分属两服务。"""
from app.db import 连接
from app.services import 装载, 结栏, 目录, 统计, 贯验, 夹具
from app.services.写闸 import 正式结, 强制结


def test_未过阈未结栏水位对账不得标绿():
    装载.装一批(夹具.读取("未过阈样例"))
    snap = 贯验.只读快照()
    assert snap["是否对齐"] is False
    assert snap["水位对账"]["合法"] is False

    r = 贯验.跑一次()
    assert r["是否对齐"] is False
    assert 目录.贯验列表()[0]["是否对齐"] == 0


def test_强制结凭证指纹可重算且被篡改即红():
    装载.装一批(夹具.读取("未过阈样例"))
    rep = 结栏.结当前栏(强制结)
    vs = 目录.强制结凭证列表()
    assert len(vs) == 1
    assert vs[0]["指纹"] == rep["指纹"]

    snap = 贯验.只读快照()
    assert snap["影子指纹合法"] is True
    assert snap["水位对账"]["合法"] is True
    assert snap["是否对齐"] is True

    conn = 连接()
    try:
        conn.execute("UPDATE 强制结凭证 SET 指纹='伪造指纹' WHERE 凭证编号=?", (vs[0]["凭证编号"],))
        conn.commit()
    finally:
        conn.close()

    snap2 = 贯验.只读快照()
    assert snap2["影子指纹合法"] is False
    assert snap2["是否对齐"] is False
    assert 贯验.跑一次()["是否对齐"] is False


def test_结栏假绿与统计假绿分属两服务():
    装载.装一批(夹具.读取("未过阈样例"))
    结栏.结当前栏(强制结)

    # 统计服务只读正式账：影子凭证不得抬升正式统计
    assert 统计.按指标汇总() == {}
    assert 统计.结栏批次摘要()[0]["影子"] == 1

    # 贯验服务独立重算影子凭证与水位，不采信结栏服务自报
    snap = 贯验.只读快照()
    assert snap["汇总报文"] == 0
    assert snap["影子报文数"] == 2
    assert snap["影子指纹合法"] is True
    assert snap["是否对齐"] is True


def test_强制结后封印拒绝再灌入():
    装载.装一批(夹具.读取("未过阈样例"))
    结栏.结当前栏(强制结)
    体 = {"报文": [{
        "报文编号": "P-seal-1", "站点键": "站-河东", "指标键": "PM25",
        "读数": 20, "观测时": "2026-11-25T10:00:00Z",
    }]}
    报 = 装载.装一批(体)
    assert 报["封印驳回"] == 1
    assert 报["入栏"] == 0
    # 被拦报文不得落任何账
    conn = 连接()
    try:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM 观测报文 WHERE 报文编号='P-seal-1'"
        ).fetchone()["c"] == 0
    finally:
        conn.close()
