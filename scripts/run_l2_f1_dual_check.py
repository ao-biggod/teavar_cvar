#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M0.5: fixed-y F1 primal / dual strong-duality check."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from l2_full_models import F1_DUAL_EPS_DEFAULT, validate_f1_strong_duality
from toy_instances import CR_A, CR_B, CR_C, build_toy_combined_component_risk


def _parse_placement(spec: str, tasks: list[int]) -> dict[int, int]:
    label_map = {"A": CR_A, "B": CR_B, "C": CR_C}
    spec = spec.strip().upper()
    if len(spec) != len(tasks):
        raise ValueError(f"placement '{spec}' length must match {len(tasks)} tasks")
    return {int(t): label_map[ch] for t, ch in zip(tasks, spec)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fixed-y F1 primal/dual validation")
    parser.add_argument("--placement", default="CCC", help="e.g. CCC, ABC, AAB")
    parser.add_argument("--eps", type=float, default=F1_DUAL_EPS_DEFAULT)
    parser.add_argument("--bandwidth-mode", default="flow", choices=("flow", "placement"))
    args = parser.parse_args()

    data = build_toy_combined_component_risk(bandwidth_mode=args.bandwidth_mode)
    data.placement_node_labels = {"A": CR_A, "B": CR_B, "C": CR_C}
    placement = _parse_placement(args.placement, list(data.I))

    result = validate_f1_strong_duality(data, placement, eps=args.eps)

    print(f"placement={args.placement} nodes={placement}")
    print(f"status={result.status}")
    print(f"primal_objective={result.primal_objective}")
    print(f"dual_objective={result.dual_objective}")
    print(f"gap={result.gap} eps={result.eps} gap_ok={result.gap_ok}")
    print(f"l0_r_sla={result.l0_r_sla} l0_match={result.l0_match}")
    print("sign_checks:", json.dumps(result.sign_checks, ensure_ascii=False))
    print("group_summaries:")
    for g in result.group_summaries:
        print(
            f"  {g.group}: count={g.count} rhs_pi_sum={g.rhs_pi_sum:.8f} "
            f"pi=[{g.pi_min:.6f}, {g.pi_max:.6f}]"
        )

    return 0 if result.gap_ok and result.l0_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
