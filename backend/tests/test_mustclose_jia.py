"""失败测甲：未过阈时正式汇总行不得增加；未过阈强制结只进影子凭证。"""
import json
import pytest

from app.db import 连接
from app.services import 装载, 结栏, 目录, 统计, 贯验, 夹具
from app.services.写闸 import 正式结, 强制结


def _正式汇总行数() -> int:
    conn = 连接()
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM 站点汇总账").fetchone()["c"]
    finally:
        conn.close()


def test_未过阈正式结被写闸拒绝():
    装载.装一批(夹具.读取("未过阈样例"))
    assert 结栏.预览结栏()["在栏"] == 2
    with pytest.raises(ValueError):
        结栏.结当前栏(正式结)
    assert _正式汇总行数() == 0


@pytest.mark.asyncio
async def test_无闸或野闸接口拒绝回刷():
    装载.装一批(夹具.读取("未过阈样例"))
    from app.main import app
    async with app.test_client() as c:
        r1 = await c.post("/api/结栏/跑", json={})
        assert r1.status_code == 400
        r2 = await c.post("/api/结栏/跑", json={"闸形态": "野闸"})
        assert r2.status_code == 400
    assert _正式汇总行数() == 0


def test_未过阈强制结只入影子凭证正式汇总不增加():
    装载.装一批(夹具.读取("未过阈样例"))
    before = _正式汇总行数()
    rep = 结栏.结当前栏(强制结)

    # 结栏批次与在栏水位同票：报告钉指纹与水位
    assert rep["闸形态"] == 强制结
    assert rep["影子"] is True
    assert rep["汇总数"] == 0
    assert rep["水位"] == 2
    assert rep["指纹"]
    assert rep["凭证编号"]

    # 失败测甲红线：正式汇总行不得增加
    assert _正式汇总行数() == before

    凭证 = 目录.强制结凭证列表()
    assert len(凭证) == 1
    v = 凭证[0]
    assert v["栏号"] == "B-demo"
    assert v["报文数"] == 2
    assert v["指纹"] == rep["指纹"]
    assert set(json.loads(v["报文集合"])) == {"P-low-1", "P-low-2"}

    # 缓冲命运为影子结栏，不得冒充已汇总
    for r in 目录.缓冲列表():
        assert r["命运"] == "影子结栏"

    # 贯验读引用不同：影子凭证不进正式汇总报文数
    snap = 贯验.只读快照()
    assert snap["汇总报文"] == 0
    assert snap["影子报文数"] == 2
    assert snap["影子指纹合法"] is True
    assert snap["是否对齐"] is True

    # 统计服务两轨可区分：正式指标统计仍为空，影子走凭证摘要
    assert 统计.按指标汇总() == {}
    档 = 统计.强制结凭证摘要()
    assert len(档) == 1 and 档[0]["报文数"] == 2


def test_过阈正式结成片物化():
    装载.装一批(夹具.读取("过阈结栏样例"))
    rep = 结栏.结当前栏(正式结)
    assert rep["影子"] is False
    assert rep["闸形态"] == 正式结
    assert rep["汇总数"] == 2
    assert _正式汇总行数() == 2
    assert 目录.强制结凭证列表() == []
    assert 贯验.跑一次()["是否对齐"] is True


def test_过阈不得走强制结空栏无可选闸():
    装载.装一批(夹具.读取("过阈结栏样例"))
    with pytest.raises(ValueError):
        结栏.结当前栏(强制结)
    # 拒绝后正式汇总仍不得被影子票污染
    assert _正式汇总行数() == 0
    assert 目录.强制结凭证列表() == []

    # 空栏预览不给任何可选闸形态
    from app import seed as _seed
    conn = 连接()
    try:
        conn.execute("DELETE FROM 入栏缓冲")
        conn.commit()
    finally:
        conn.close()
    assert 结栏.预览结栏()["可选闸形态"] == []
    with pytest.raises(ValueError):
        结栏.结当前栏(强制结)
