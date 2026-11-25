#!/usr/bin/env python3
"""并发双请求脚本：同栏同时打 强制结 与 灌入，验证不半栏双写、不双成功。

用法：
  python scripts/race_double_request.py --base http://127.0.0.1:8220 --rounds 20
前置：每轮开始前库内当前栏恰有 1 笔在栏（脚本会自行灌入 1 笔未过阈报文）。
退出码 0 表示 20 轮全部收敛为“恰好一凭证、一封印、正式汇总零增长、无半栏残留”。
"""
from __future__ import annotations
import argparse
import json
import sys
import threading

import httpx


def 主() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8220")
    ap.add_argument("--rounds", type=int, default=20)
    args = ap.parse_args()
    base = args.base.rstrip("/")

    for i in range(args.rounds):
        # 每轮换新栏号开新栏，避免上一轮封印后无栏可竞（经栏规接口切栏）
        栏号 = f"B-race-{i}"
        rr = httpx.post(f"{base}/api/栏规", json={"当前栏号": 栏号}, timeout=10)
        rr.raise_for_status()
        # 起手灌 1 笔，使水位=1（未过阈，默认阈值 3）
        seed_body = {"批次编号": f"race-seed-{i}", "报文": [{
            "报文编号": f"P-race-seed-{i}", "站点键": "站-河东", "指标键": "PM25",
            "读数": 21.0, "观测时": f"2026-11-25T0{1 + (i % 9)}:00:00Z",
        }]}
        r = httpx.post(f"{base}/api/观测报文/装载", json=seed_body, timeout=10)
        r.raise_for_status()

        竞体 = {"批次编号": f"race-in-{i}", "报文": [{
            "报文编号": f"P-race-in-{i}", "站点键": "站-河东", "指标键": "PM25",
            "读数": 22.0, "观测时": f"2026-11-25T0{1 + (i % 9)}:30:00Z",
        }]}
        果: dict = {}
        闸 = threading.Barrier(2)

        def 强结() -> None:
            闸.wait()
            果["强"] = httpx.post(
                f"{base}/api/结栏/跑", json={"闸形态": "强制结"}, timeout=10
            )

        def 灌入() -> None:
            闸.wait()
            果["灌"] = httpx.post(f"{base}/api/观测报文/装载", json=竞体, timeout=10)

        t1 = threading.Thread(target=强结)
        t2 = threading.Thread(target=灌入)
        t1.start(); t2.start(); t1.join(); t2.join()

        强码 = 果["强"].status_code
        灌 = 果["灌"].json()
        凭证 = httpx.get(f"{base}/api/强制结栏/凭证", timeout=10).json()
        汇总 = httpx.get(f"{base}/api/站点汇总账", timeout=10).json()
        缓冲 = httpx.get(f"{base}/api/入栏缓冲", timeout=10).json()
        闸态 = httpx.get(f"{base}/api/强制结栏/闸态", timeout=10).json()

        影子 = {x["报文编号"] for x in 缓冲 if x["命运"] == "影子结栏"}
        在栏 = {x["报文编号"] for x in 缓冲 if x["命运"] == "在栏"}
        凭集合 = set()
        for v in 凭证:
            凭集合 |= set(json.loads(v["报文集合"]))

        ok = (
            强码 == 200
            and 灌["入栏"] + 灌["封印驳回"] == 1
            and 闸态["已封印"] is True
            and 影子 == 凭集合
            and 在栏 == set()
            and len(汇总) == 0
        )
        print(f"round {i:02d} 强结={强码} 灌入栏={灌['入栏']} 封印驳回={灌['封印驳回']} "
              f"凭证={len(凭证)} 正式汇总={len(汇总)} => {'OK' if ok else 'RED'}")
        if not ok:
            print("半栏双写/双成功！详情：", json.dumps(
                {"强": 果["强"].text, "灌": 灌, "闸态": 闸态}, ensure_ascii=False))
            return 1
    print(f"{args.rounds} 轮并发双请求全部收敛，无半栏双写。")
    return 0


if __name__ == "__main__":
    sys.exit(主())
