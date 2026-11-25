"""空桩：强制结栏（已落地，桩位保留）

实现位置：
- app/services/写闸.py：闸形态登记（正式结/强制结）+ 结栏/灌入共享写锁
- app/services/结栏.py：结当前栏(闸形态)，未过阈强制结只写 强制结凭证 影子轨
- app/services/贯验.py：影子凭证指纹重算与水位对账
- 只读接口：GET /api/强制结栏/凭证、GET /api/强制结栏/闸态

契约：
- 水位或人工可强制结未满栏
- 不得改坏基线默认门槛 happy path（装载→入栏/坏点→结栏汇总→贯验）。
- 页面须能读到：当前策略名、命运变化、可点的下一步。
"""
NAME = "强制结栏"
CONTRACT = "水位或人工可强制结未满栏"
HOOKS = ("before_load", "after_load", "decide_gate", "before_close", "after_close", "extra_verify_checks")


def describe() -> dict:
    return {"空桩": NAME, "契约": CONTRACT, "钩子": list(HOOKS), "默认启用": False}


def before_load(batch: dict) -> dict:
    return batch


def after_load(report: dict) -> dict:
    return report


def decide_gate(event: dict, rules: dict) -> str:
    return "入栏"


def before_close(pen_id: str) -> None:
    return None


def after_close(report: dict) -> dict:
    return report


def extra_verify_checks(snapshot: dict) -> list[str]:
    return []
