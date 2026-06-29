#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多拓扑就绪性检查 + 可选快速 joint 冒烟。

示例：
  python run_batch_experiments.py --audit
  python run_batch_experiments.py --audit --topologies B4,ATT,Abilene
  python run_batch_experiments.py --smoke --topologies B4 --joint-num-tasks 4
"""

from __future__ import annotations

import argparse
import sys
import time

BASE_DATA_PATH = "./data"


def _parse_topologies(raw: str | None) -> list[str]:
    from b4_joint_data import list_available_topologies

    if raw:
        return [t.strip() for t in raw.split(",") if t.strip()]
    return list_available_topologies(BASE_DATA_PATH)


def run_audit(topologies: list[str], hub: int, num_tasks: int) -> int:
    from b4_joint_data import assess_topology_readiness

    print(f"{'Topology':>12} | {'Ready':>5} | {'Nodes':>5} | {'Edges':>5} | Notes")
    print("-" * 90)
    n_fail = 0
    for name in topologies:
        r = assess_topology_readiness(name, BASE_DATA_PATH, hub_index=hub, num_tasks=num_tasks)
        notes = "; ".join(r["issues"] + r["warnings"]) or "OK"
        ok = "yes" if r["ready"] else "NO"
        if not r["ready"]:
            n_fail += 1
        print(f"{name:>12} | {ok:>5} | {r['nodes']:>5} | {r['edges']:>5} | {notes}")
    print(f"\n合计: {len(topologies) - n_fail}/{len(topologies)} 就绪")
    return n_fail


def run_smoke(topologies: list[str], args) -> int:
    from gurobipy import GRB

    from b4_joint_data import load_joint_data
    from cvar_compare import build_teavar_sla_cvar_model

    n_fail = 0
    for name in topologies:
        print(f"\n=== smoke: {name} ===")
        t0 = time.time()
        try:
            data = load_joint_data(
                base_path=BASE_DATA_PATH,
                topology_name=name,
                hub_index=args.hub,
                num_tasks=args.joint_num_tasks,
                demand_scale=args.joint_demand_scale,
                k_paths=args.joint_k_paths,
                stress_zero_s1=args.joint_stress_zero_s1,
            )
            m, cost, lv, nv, sfv, *_ = build_teavar_sla_cvar_model(
                data,
                lambda_cvar=5.0,
                omega_deliver=1.0,
                min_tasks_off_node0=args.joint_min_off_hub,
                lambda_compute_sf_cvar=1.0,
            )
            dt = time.time() - t0
            if m.status == GRB.OPTIMAL:
                print(
                    f"  OK | |I|={len(data.I)} | cost={cost:.3f} | SLA_CVaR={lv:.4f} | "
                    f"sf_CVaR={sfv or 0.0:.4f} | {dt:.1f}s"
                )
            else:
                print(f"  FAIL | teavar_sla status={m.status} | {dt:.1f}s")
                n_fail += 1
        except Exception as exc:
            print(f"  FAIL | {exc}")
            n_fail += 1
    return n_fail


def main():
    parser = argparse.ArgumentParser(description="多拓扑 audit / smoke")
    parser.add_argument("--audit", action="store_true", help="仅检查数据就绪性")
    parser.add_argument("--smoke", action="store_true", help="对每个就绪拓扑解一次 teavar_sla")
    parser.add_argument("--topologies", type=str, default=None, help="逗号分隔；缺省=全部")
    parser.add_argument("--hub", type=int, default=0)
    parser.add_argument("--joint-num-tasks", type=int, default=4)
    parser.add_argument("--joint-demand-scale", type=float, default=1.0)
    parser.add_argument("--joint-k-paths", type=int, default=2)
    parser.add_argument("--joint-stress-zero-s1", action="store_true")
    parser.add_argument("--joint-min-off-hub", type=int, default=0)
    args = parser.parse_args()

    if not args.audit and not args.smoke:
        args.audit = True

    topologies = _parse_topologies(args.topologies)
    if not topologies:
        print("未找到任何拓扑（data/*/topology.txt）")
        sys.exit(1)

    fails = 0
    if args.audit:
        fails += run_audit(topologies, args.hub, args.joint_num_tasks)
    if args.smoke:
        fails += run_smoke(topologies, args)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
