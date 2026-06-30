#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M2 L2-light smoke: embedded-y lex SF → SLA → Cost."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilevel_teavar_models import solve_bilevel_lexicographic
from l2_full_models import (
    embedded_y_variable_counts,
    solve_l2_light_lexicographic,
    summarize_dual_bounds,
)
from toy_instances import CR_A, CR_B, CR_C, build_toy_combined_component_risk


def main() -> int:
    data = build_toy_combined_component_risk(bandwidth_mode="flow")
    data.placement_node_labels = {"A": CR_A, "B": CR_B, "C": CR_C}

    from l2_full_models import build_l2_light_embedded_y

    ctx = build_l2_light_embedded_y(data)
    print("variable_counts", embedded_y_variable_counts(ctx, data))
    print("dual_bounds", summarize_dual_bounds(ctx))

    l2 = solve_l2_light_lexicographic(data, time_limit=180)
    l0 = solve_bilevel_lexicographic(data)

    print("l2_light", l2)
    print("l0_best", l0.best.placement_code if l0.best else None)
    ok = l2.status == "OPTIMAL" and l0.best and l2.placement_code == l0.best.placement_code
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
