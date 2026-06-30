#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Smoke test for M2-C-Cost Adaptive on Toy-2Task-IndependentComponentRisk-v1.

Usage:
    cd TEAVAR_python
    .venv/Scripts/python scripts/run_m2_c_cost_adaptive_smoke.py

Builds and solves the M2-C-Cost model with aggregate_worst pruning,
then prints key results.
"""
from __future__ import annotations

import sys, os
_srcdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _srcdir not in sys.path:
    sys.path.insert(0, _srcdir)

from toy_two_task_independent_data import build_toy_2task_independent_v1
from refactor.m2_c_cost_models import build_m2_c_cost_adaptive, solve_m2_c_cost_adaptive


def main():
    print("=" * 60)
    print("M2-C-Cost Adaptive Smoke Test")
    print("=" * 60)

    # --- Build data with aggregate_worst pruning ---
    print("\n[1] Building Toy-2Task (max_fail=2, aggregate_worst)...")
    data = build_toy_2task_independent_v1(
        scenario_mode="pruned",
        max_failed_components=2,
        renormalize_probabilities=False,
        prune_mode="aggregate_worst",
    )
    meta = data.scenario_metadata
    print(f"    Scenarios: {len(data.S)} (kept={meta['num_scenarios_before_pruning']}, "
          f"aggregate=1)")
    print(f"    Prune mode: {meta['prune_mode']}")
    print(f"    Aggregate prob: {meta['aggregate_worst_probability']:.6f}")
    print(f"    Dropped mass: {meta['dropped_probability_mass']:.6f}")
    print(f"    Total prob: {sum(data.prob[s] for s in data.S):.10f}")

    # --- Build model ---
    print("\n[2] Building M2-C-Cost Adaptive model...")
    print(f"    gamma=0.5, beta=0.8, service_floor=0.85")
    model = build_m2_c_cost_adaptive(
        data,
        gamma=0.5,
        beta=0.8,
        loss_mode="mean",
        service_floor={0: 0.85, 1: 0.85},
        quiet=True,
    )
    print(f"    Variables: {model.NumVars} ({model.NumIntVars} integer)")
    print(f"    Constraints: {model.NumConstrs}")

    # --- Solve ---
    print("\n[3] Solving...")
    result = solve_m2_c_cost_adaptive(model)
    status_names = {1: "LOADED", 2: "OPTIMAL", 3: "INFEASIBLE",
                    4: "INF_OR_UNBD", 5: "UNBOUNDED", 6: "CUTOFF",
                    7: "ITERATION_LIMIT", 8: "NODE_LIMIT", 9: "TIME_LIMIT",
                    10: "SOLUTION_LIMIT", 11: "INTERRUPTED", 12: "NUMERIC",
                    13: "SUBOPTIMAL"}
    sname = status_names.get(result.status, f"UNKNOWN({result.status})")
    print(f"    Status: {result.status} ({sname})")

    # --- Results ---
    print("\n[4] Results:")
    print(f"    Objective:          {result.objective:.4f}")
    print(f"    Deployment cost:    {result.deployment_cost:.4f}")
    print(f"    Expected BW cost:   {result.bandwidth_cost:.4f}")
    print(f"    Expected service:   {result.expected_service:.6f}")
    print(f"    CVaR (post-hoc):    {result.cvar_value:.6f}")
    print(f"    eta (post-hoc):     {result.eta:.6f}")

    # Per-task expected service
    print("\n[5] Per-task metrics:")
    for i in data.I:
        exp_z = sum(data.prob[s] * result.z.get((i, s), 0.0) for s in data.S)
        z_nominal = result.z.get((i, 0), 0.0)
        z_agg = result.z.get((i, data.S[-1]), 0.0)
        print(f"    Task {i}: E[z]={exp_z:.6f}, z_nominal={z_nominal:.2f}, "
              f"z_aggregate={z_agg:.2f}")

    # Placement
    print("\n[6] Placement:")
    for i in data.I:
        for m in data.M:
            val = result.placement.get((i, m), 0.0)
            if val > 0.5:
                from toy_two_task_independent_data import NODE_LABELS
                print(f"    Task {i} → {NODE_LABELS[m]}")

    # L_s per scenario (high-loss only)
    print("\n[7] Loss L_s (scenarios with L > 0.5):")
    high_loss = [(s, L) for s, L in result.L_s.items() if L > 0.5]
    for s, L in sorted(high_loss, key=lambda x: -x[1]):
        print(f"    s={s}: L={L:.6f} (prob={data.prob[s]:.6f})")
    if not high_loss:
        print("    (none — all L_s <= 0.5)")

    print("\n" + "=" * 60)
    print("Smoke test complete.")

    # Validation
    checks = 0
    ok = 0
    checks += 1
    if result.status in (2, 9, 13):
        ok += 1
    else:
        print(f"  [FAIL] Status not optimal")

    if result.status in (2, 9, 13):
        checks += 1
        if abs(result.objective - (result.deployment_cost + result.bandwidth_cost)) < 1e-4:
            ok += 1
        else:
            print(f"  [FAIL] Objective != deploy + bw")

        checks += 1
        if all(result.z.get((i, 0), 0) > 0.99 for i in data.I):
            ok += 1
        else:
            print(f"  [FAIL] z_nominal != 1.0")

    print(f"  Checks: {ok}/{checks} passed")
    return 0 if ok == checks else 1


if __name__ == "__main__":
    sys.exit(main())
