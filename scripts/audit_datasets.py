#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审计 9 拓扑数据集：价格比、demand 行数、场景 YAML、拓扑容量异质性、loader 就绪性。"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

TOPOS = ["B4", "ATT", "Abilene", "IBM", "Sprint", "XNet", "Nextgen", "Custom", "Custom2"]


def count_demand_rows(path: Path) -> int | None:
    if not path.exists():
        return None
    n = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def price_ratio_cpu(csv_path: Path) -> dict | None:
    if not csv_path.exists():
        return None
    rows = []
    with csv_path.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if not rows:
        return None
    by_role: dict[str, list[float]] = {}
    for r in rows:
        role = r.get("role", "?")
        try:
            p = float(r.get("price_cpu") or r.get("price_CPU") or 0)
        except ValueError:
            p = 0.0
        by_role.setdefault(role, []).append(p)
    core_p = min(by_role.get("core", [999]))
    edge_p = max(by_role.get("edge_pop", [0]))
    agg_p = sum(by_role.get("aggregation", [0])) / max(len(by_role.get("aggregation", [])), 1)
    ratio = edge_p / core_p if core_p > 0 else 0
    return {"core_min": core_p, "edge_max": edge_p, "agg_avg": agg_p, "ratio_edge_core": ratio, "n_nodes": len(rows)}


def capacity_heterogeneity(topo_path: Path) -> dict | None:
    if not topo_path.exists():
        return None
    caps = []
    has_pf = True
    with topo_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0] == "to_node" or line.startswith("#"):
                continue
            try:
                caps.append(float(parts[2]))
                if len(parts) < 4:
                    has_pf = False
            except (ValueError, IndexError):
                continue
    if not caps:
        return None
    mn, mx = min(caps), max(caps)
    return {
        "n_edges": len(caps),
        "cap_min": mn,
        "cap_max": mx,
        "cap_ratio": mx / mn if mn > 0 else 0,
        "uniform_cap": abs(mx - mn) < 1e-6 * mx,
        "has_prob_failure": has_pf,
    }


def yaml_exists(path: Path) -> bool:
    return path.exists()


def loader_ready(name: str) -> tuple[bool, str]:
    from b4_joint_data import assess_topology_readiness

    r = assess_topology_readiness(name, str(ROOT / "data"), num_tasks=4)
    msg = "; ".join(r["issues"] + r["warnings"]) or "OK"
    return r["ready"], msg


def main():
    print(f"{'Topo':>10} | {'YAML':>4} | {'demand':>8} | {'CSV比':>6} | {'cap异质':>8} | {'pf列':>4} | {'loader':>6}")
    print("-" * 78)
    for name in TOPOS:
        d = ROOT / "data" / name
        dem = count_demand_rows(d / "demand.txt")
        pr = price_ratio_cpu(d / "node_compute_resources.csv")
        cap = capacity_heterogeneity(d / "topology.txt")
        yml = yaml_exists(d / "scenarios.yaml")
        ready, msg = loader_ready(name)

        dem_s = f"{dem}行" if dem else "合成"
        ratio_s = f"{pr['ratio_edge_core']:.1f}x" if pr else "—"
        cap_s = f"{cap['cap_ratio']:.2f}x" if cap and not cap["uniform_cap"] else ("统一" if cap else "—")
        pf_s = "Y" if cap and cap["has_prob_failure"] else ("N" if cap else "—")
        print(
            f"{name:>10} | {'Y' if yml else 'N':>4} | {dem_s:>8} | {ratio_s:>6} | {cap_s:>8} | {pf_s:>4} | "
            f"{'OK' if ready else 'FAIL':>6}"
        )
        if not ready:
            print(f"           └ {msg}")

    # spot-check B4 CSV columns
    print("\n--- B4 CSV 列名抽样 ---")
    with (ROOT / "data" / "B4" / "node_compute_resources.csv").open(encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        print("columns:", r.fieldnames)
        rows = list(r)
    roles = {}
    for row in rows:
        roles.setdefault(row["role"], []).append(float(row["price_cpu"]))
    for role, ps in sorted(roles.items()):
        print(f"  {role}: price_CPU min={min(ps):.3f} max={max(ps):.3f}")

    print("\n--- 代码是否读取 scenarios.yaml ---")
    import b4_joint_data as bjd
    src = Path(bjd.__file__).read_text(encoding="utf-8")
    wired = "scenarios.yaml" in src or "yaml" in src.lower()
    print(f"  b4_joint_data.py 引用 scenarios.yaml: {'是' if wired else '否（仅文档/硬编码）'}")


if __name__ == "__main__":
    main()
