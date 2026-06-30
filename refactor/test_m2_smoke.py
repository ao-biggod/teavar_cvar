# -*- coding: utf-8 -*-
"""Smoke test: M2 model (CVaR-constrained recourse) with Toy-Mesh instances."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from toy_instances_v2 import build_toy_mesh, build_toy_mesh_sf, build_toy_mesh_combined
from m2_models import build_m2_model_c, solve_m2_model_c, solve_m2_lex


def _print_result(label: str, result, data):
    """Pretty-print M2 result."""
    status_map = {2: "OPTIMAL", 3: "INFEASIBLE", 4: "INF_OR_UNBD", 9: "TIME_LIMIT"}
    status_str = status_map.get(result.status, str(result.status))
    print(f"\n--- {label} ---")
    print(f"  Status: {status_str}")
    if result.status != 2:
        return
    print(f"  Expected service: {result.expected_service:.4f}")
    print(f"  CVaR_α(L):        {result.cvar_value:.4f}  (η*={result.eta:.4f})")
    # Placement
    assigned = {}
    for (i, m), val in result.placement.items():
        if val > 0.5:
            assigned[i] = m
    node_lab = {0: "S1", 1: "A", 2: "H", 3: "T1", 4: "B", 5: "S2", 6: "T2"}
    placement_str = ", ".join(f"i{i}→{node_lab.get(m, str(m))}" for i, m in sorted(assigned.items()))
    print(f"  Placement: {placement_str}")
    # z[i,s]
    print(f"  z[i,s]:")
    for s in data.S:
        vals = "  ".join(f"i{i}:{result.z.get((i,s),0.0):.3f}" for i in data.I)
        print(f"    s{s}: {vals}")
    print(f"  L_s[E2E]: {', '.join(f's{s}:{result.L_s.get(s,0.0):.4f}' for s in data.S)}")


def test_m2_c_mesh():
    """M2-C: Toy-Mesh with gamma sweep."""
    print("=" * 60)
    print("M2-C: Toy-Mesh (gamma sweep)")
    print("=" * 60)
    data = build_toy_mesh()
    data.theta = {i: 1.0 for i in data.I}
    data.D_i = {i: 1.0 for i in data.I}
    data.alpha = 0.8

    for gamma in [0.0, 0.1, 0.3, 0.5, 1.0]:
        m = build_m2_model_c(data, gamma=gamma, alpha=data.alpha)
        r = solve_m2_model_c(m)
        _print_result(f"γ={gamma:.1f}", r, data)


def test_m2_c_mesh_sf():
    """M2-C: Toy-Mesh-SF (compute shortfall focus)."""
    print("\n" + "=" * 60)
    print("M2-C: Toy-Mesh-SF (gamma sweep)")
    print("=" * 60)
    data = build_toy_mesh_sf()
    data.theta = {i: 1.0 for i in data.I}
    data.D_i = {i: 1.0 for i in data.I}
    data.alpha = 0.8

    for gamma in [0.0, 0.2, 0.4, 0.6, 1.0]:
        m = build_m2_model_c(data, gamma=gamma, alpha=data.alpha)
        r = solve_m2_model_c(m)
        _print_result(f"γ={gamma:.1f}", r, data)


def test_m2_lex_mesh():
    """M2-Lex: Toy-Mesh."""
    print("\n" + "=" * 60)
    print("M2-Lex: Toy-Mesh")
    print("=" * 60)
    data = build_toy_mesh()
    data.theta = {i: 1.0 for i in data.I}
    data.D_i = {i: 1.0 for i in data.I}
    data.alpha = 0.8

    p1, p2 = solve_m2_lex(data, alpha=data.alpha)
    _print_result("Pass 1 (min CVaR)", p1, data)
    if p2 is not None:
        _print_result("Pass 2 (max service @ min CVaR)", p2, data)


def test_m2_lex_mesh_sf():
    """M2-Lex: Toy-Mesh-SF."""
    print("\n" + "=" * 60)
    print("M2-Lex: Toy-Mesh-SF")
    print("=" * 60)
    data = build_toy_mesh_sf()
    data.theta = {i: 1.0 for i in data.I}
    data.D_i = {i: 1.0 for i in data.I}
    data.alpha = 0.8

    p1, p2 = solve_m2_lex(data, alpha=data.alpha)
    _print_result("Pass 1 (min CVaR)", p1, data)
    if p2 is not None:
        _print_result("Pass 2 (max service @ min CVaR)", p2, data)


if __name__ == "__main__":
    test_m2_c_mesh()
    test_m2_c_mesh_sf()
    test_m2_lex_mesh()
    test_m2_lex_mesh_sf()
    print("\nAll M2 smoke tests completed.")
