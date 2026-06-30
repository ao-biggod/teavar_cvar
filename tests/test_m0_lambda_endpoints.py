# -*- coding: utf-8 -*-
"""
M0 λ endpoint tests with ToyTE dataset.

Verifies:
  1. λ=0, 0.5, 1 all return OPTIMAL.
  2. λ=0 → peak_node_util is minimal (or tied for minimal).
  3. λ=1 → peak_link_util is minimal (or tied for minimal).
  4. λ=0.5 → solver epigraph ≈ posthoc peak (within tolerance).
  5. λ=0 / λ=1 → ignored epigraph may differ from posthoc peak.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from toy_te_data import build_toy_te_dataset, NODE_LABELS, K_LABELS
from refactor.m0_models import build_m0_model, solve_m0_model

TOL = 1e-4


def _build_toyte_data():
    data = build_toy_te_dataset()
    # Bridge to M0's P_cand convention: keys are (u, v)
    data.P_cand = {}
    for (u, v), paths in data.P_in.items():
        data.P_cand[u, v] = paths
    for (u, v), paths in data.P_out.items():
        data.P_cand[u, v] = paths
    return data


def test_lambda_endpoints():
    data = _build_toyte_data()

    results = {}
    for lam in [0.0, 0.5, 1.0]:
        model = build_m0_model(data, lambda_m0=lam)
        r = solve_m0_model(model)
        results[lam] = r
        print(f"\nλ={lam:.1f}:")
        print(f"  Status:       {r.status} (obj={r.objective:.6f})")
        print(f"  U_link_solver={r.U_link_solver:.6f}  U_node_solver={r.U_node_solver:.6f}")
        print(f"  peak_link_util={r.peak_link_util:.6f}  peak_node_util={r.peak_node_util:.6f}")
        if r.argmax_link:
            u, v = r.argmax_link
            print(f"  argmax_link:  {NODE_LABELS.get(u,u)}→{NODE_LABELS.get(v,v)}")
        if r.argmax_node:
            m, k = r.argmax_node
            print(f"  argmax_node:  {NODE_LABELS.get(m,m)}[{K_LABELS[k]}]")
        # Placement
        assigned = {}
        for (i, m), val in r.placement.items():
            if val > 0.5:
                assigned[i] = m
        print(f"  Placement:    {', '.join(f'i{i}→{NODE_LABELS.get(m,m)}' for i,m in sorted(assigned.items()))}")

        assert r.status == 2, f"λ={lam}: status={r.status} (not OPTIMAL)"

    r0 = results[0.0]
    r5 = results[0.5]
    r1 = results[1.0]

    # λ=0 → node utilization should be minimal
    node_utils = {lam: r.peak_node_util for lam, r in results.items()}
    print(f"\nNode peak utils: {node_utils}")
    assert r0.peak_node_util <= min(node_utils.values()) + TOL, (
        f"λ=0 node util {r0.peak_node_util:.4f} not minimal"
    )
    print("  ✓ λ=0: peak_node_util is minimal")

    # λ=1 → link utilization should be minimal
    link_utils = {lam: r.peak_link_util for lam, r in results.items()}
    print(f"Link peak utils: {link_utils}")
    assert r1.peak_link_util <= min(link_utils.values()) + TOL, (
        f"λ=1 link util {r1.peak_link_util:.4f} not minimal"
    )
    print("  ✓ λ=1: peak_link_util is minimal")

    # λ=0.5 → solver epigraph ≈ posthoc peak (both variables in objective)
    link_diff = abs(r5.U_link_solver - r5.peak_link_util)
    node_diff = abs(r5.U_node_solver - r5.peak_node_util)
    print(f"\nλ=0.5: |solver - posthoc| link={link_diff:.6f} node={node_diff:.6f}")
    assert link_diff < TOL, f"λ=0.5 link mismatch: solver={r5.U_link_solver} posthoc={r5.peak_link_util}"
    assert node_diff < TOL, f"λ=0.5 node mismatch: solver={r5.U_node_solver} posthoc={r5.peak_node_util}"
    print("  ✓ λ=0.5: solver epigraph ≈ posthoc peak")

    # λ endpoints: the ignored epigraph may differ — we just report, don't force
    link_endpoint_diff = abs(r0.U_link_solver - r0.peak_link_util)
    node_endpoint_diff = abs(r1.U_node_solver - r1.peak_node_util)
    print(f"\nλ=0: |U_link_solver - peak_link_util| = {link_endpoint_diff:.6f}  (may be large, OK)")
    print(f"λ=1: |U_node_solver - peak_node_util| = {node_endpoint_diff:.6f}  (may be large, OK)")
    print("  ✓ λ endpoint: ignored epigraph NOT forced to match (informational)")

    print("\n✓ All M0 λ endpoint tests passed.")


if __name__ == "__main__":
    test_lambda_endpoints()
