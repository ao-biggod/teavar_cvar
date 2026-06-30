# -*- coding: utf-8 -*-
"""Smoke: Strict risk-first lexicographic bilevel TEAVAR (ComponentRisk flow variant)."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilevel_teavar_models import (
    DEFAULT_LEX_PRIORITY,
    lex_resolved_config,
    solve_bilevel_lexicographic,
)
from toy_instances import CR_A, CR_B, CR_C, build_toy_combined_component_risk

CSV_COLUMNS = [
    "placement_code",
    "cost_deploy",
    "cost_bw",
    "cost_total",
    "r_sla",
    "r_sf",
    "e_del",
    "x_sum",
    "in_Y1",
    "in_Y2",
    "is_best",
]


def _row_dict(row) -> dict:
    return {
        "placement_code": row.placement_code,
        "cost_deploy": row.cost_deploy,
        "cost_bw": row.cost_bw,
        "cost_total": row.cost_total,
        "r_sla": row.r_sla,
        "r_sf": row.r_sf,
        "e_del": row.e_del,
        "x_sum": row.x_sum,
        "in_Y1": int(row.in_Y1),
        "in_Y2": int(row.in_Y2),
        "is_best": int(row.is_best),
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Strict lexicographic bilevel smoke (ComponentRisk, flow bandwidth)"
    )
    p.add_argument(
        "--output",
        type=str,
        default=str(ROOT / "results" / "bilevel_lex_cr_flow.csv"),
    )
    p.add_argument(
        "--config-json",
        type=str,
        default=str(ROOT / "results" / "bilevel_lex_cr_flow.resolved_config.json"),
    )
    args = p.parse_args()

    data = build_toy_combined_component_risk(bandwidth_mode="flow")
    data.placement_node_labels = {"A": CR_A, "B": CR_B, "C": CR_C}
    data.instance_name = "Toy-Combined-ComponentRisk"

    priority = DEFAULT_LEX_PRIORITY
    fast_objective = "lex_sla_delivery_cost"
    config = lex_resolved_config(data, priority=priority, fast_objective=fast_objective)

    result = solve_bilevel_lexicographic(
        data,
        priority=priority,
        fast_objective=fast_objective,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for row in sorted(result.all_rows, key=lambda r: r.placement_code):
            w.writerow(_row_dict(row))

    config_path = Path(args.config_json)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        **config,
        "status": result.status,
        "R_sf_star": result.R_sf_star,
        "R_sla_star": result.R_sla_star,
        "cost_star": result.cost_star,
        "Y1_count": result.Y1_count,
        "Y2_count": result.Y2_count,
        "best_count": result.best_count,
        "best_placement": result.best.placement_code if result.best else None,
        "wall_time_sec": result.wall_time_sec,
    }
    config_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("=== Resolved config ===")
    print(json.dumps(config, indent=2))
    print("\n=== Summary ===")
    print(f"priority={' -> '.join(priority)}")
    print(f"fast_objective={fast_objective}")
    print(f"status={result.status}")
    print(f"R_sf_star={result.R_sf_star}")
    print(f"R_sla_star={result.R_sla_star}")
    print(f"cost_star={result.cost_star}")
    print(f"Y1_count={result.Y1_count}")
    print(f"Y2_count={result.Y2_count}")
    print(f"best_count={result.best_count}")
    if result.best:
        b = result.best
        print(
            f"best placement={b.placement_code}  cost_total={b.cost_total:.6f}  "
            f"r_sf={b.r_sf:.6f}  r_sla={b.r_sla:.6f}  e_del={b.e_del:.6f}"
        )
    print(f"\nCSV: {out_path}")
    print(f"Config+summary JSON: {config_path}")
    print(f"wall_time_sec={result.wall_time_sec:.3f}")


if __name__ == "__main__":
    main()
