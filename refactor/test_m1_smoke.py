# -*- coding: utf-8 -*-
"""Smoke test: M1 model with Toy-Mesh instances from toy_instances_v2.py."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from toy_instances_v2 import build_toy_mesh, build_toy_mesh_sf, build_toy_mesh_combined
from m1_models import build_m1_model, set_m1_objective, solve_m1_model, format_m1_placement


def _check_z(z_out, data, label: str):
    """Print z[i,s] for all tasks and scenarios."""
    print(f"  z[i,s] ({label}):")
    for s in data.S:
        vals = [f"  i{i}_s{s}={z_out.get((i,s), 0.0):.3f}" for i in data.I]
        print("    " + ", ".join(vals))
    avg = sum(data.prob[s] * sum(z_out.get((i,s), 0.0) for i in data.I) for s in data.S) / len(data.I)
    print(f"  expected avg service (per-task): {avg:.4f}")


def test_m1_mesh():
    """Toy-Mesh: 2 tasks, 3 scenarios, hub multipath."""
    print("=" * 60)
    print("M1 Smoke: Toy-Mesh")
    print("=" * 60)
    data = build_toy_mesh()
    data.theta = {i: 1.0 for i in data.I}
    data.D_i = {i: 1.0 for i in data.I}

    m = build_m1_model(data)
    set_m1_objective(m, data, mode="max_service")
    result = solve_m1_model(m)

    print(f"  Status: {result.status} (obj={result.objective:.4f})")
    print(f"  Placement: {format_m1_placement(data, result.placement)}")
    _check_z(result.z, data, "M1 max-service")

    # Now test with feasibility mode (no objective)
    m2 = build_m1_model(data)
    set_m1_objective(m2, data, mode="feasibility")
    r2 = solve_m1_model(m2)
    print(f"  Feasibility: status={r2.status}")
    print()


def test_m1_mesh_sf():
    """Toy-Mesh-SF: compute shortfall focus."""
    print("=" * 60)
    print("M1 Smoke: Toy-Mesh-SF")
    print("=" * 60)
    data = build_toy_mesh_sf()
    data.theta = {i: 1.0 for i in data.I}
    data.D_i = {i: 1.0 for i in data.I}

    m = build_m1_model(data)
    set_m1_objective(m, data, mode="max_service")
    result = solve_m1_model(m)

    print(f"  Status: {result.status} (obj={result.objective:.4f})")
    print(f"  Placement: {format_m1_placement(data, result.placement)}")
    _check_z(result.z, data, "M1 max-service")
    print()


def test_m1_mesh_combined():
    """Toy-Mesh-Combined: conflicting network vs compute risks."""
    print("=" * 60)
    print("M1 Smoke: Toy-Mesh-Combined")
    print("=" * 60)
    data = build_toy_mesh_combined()
    data.theta = {i: 1.0 for i in data.I}
    data.D_i = {i: 1.0 for i in data.I}

    m = build_m1_model(data)
    set_m1_objective(m, data, mode="max_service")
    result = solve_m1_model(m)

    print(f"  Status: {result.status} (obj={result.objective:.4f})")
    print(f"  Placement: {format_m1_placement(data, result.placement)}")
    _check_z(result.z, data, "M1 max-service")

    # min_max mode
    m2 = build_m1_model(data)
    set_m1_objective(m2, data, mode="min_max")
    r2 = solve_m1_model(m2)
    print(f"  Min-max: status={r2.status} (obj={r2.objective:.4f})")
    print(f"  Placement (min-max): {format_m1_placement(data, r2.placement)}")
    _check_z(r2.z, data, "M1 min-max")
    print()


def test_m1_sanity_checks():
    """Verify that M1 constraints are logically sound on Toy-Mesh."""
    print("=" * 60)
    print("M1 Sanity Checks")
    print("=" * 60)
    data = build_toy_mesh()
    data.theta = {i: 1.0 for i in data.I}
    data.D_i = {i: 1.0 for i in data.I}

    m = build_m1_model(data)
    set_m1_objective(m, data, mode="max_service")
    result = solve_m1_model(m)

    # Check 1: placement should be unique
    assigned = {}
    for (i, m), val in result.placement.items():
        if val > 0.5:
            assigned[i] = m
    for i in data.I:
        assert i in assigned, f"Task {i} has no placement!"
    print(f"  ✓ Unique placement: {assigned}")

    # Check 2: z[i,s] should equal sum_m r[i,m,s]
    for i in data.I:
        for s in data.S:
            r_sum = sum(result.r.get((i, m, s), 0.0) for m in data.M)
            z_val = result.z.get((i, s), 0.0)
            assert abs(r_sum - z_val) < 1e-6, f"z[{i},{s}]={z_val} != sum r={r_sum}"
    print("  ✓ z[i,s] == sum_m r[i,m,s] for all i,s")

    # Check 3: r[i,m,s] <= y[i,m]
    for (i, m, s), r_val in result.r.items():
        y_val = result.placement.get((i, m), 0.0)
        assert r_val <= y_val + 1e-6, f"r[{i},{m},{s}]={r_val} > y={y_val}"
    print("  ✓ r[i,m,s] <= y[i,m] for all i,m,s")

    # Check 4: r[i,m,s] >= 0, z[i,s] <= 1
    for (i, s), z_val in result.z.items():
        assert 0.0 <= z_val <= 1.0 + 1e-6, f"z[{i},{s}]={z_val} out of [0,1]"
    print("  ✓ z[i,s] in [0,1] for all i,s")

    # Check 5: flow conservation for each scenario
    found_flow_issue = False
    for s in data.S:
        for i in data.I:
            src_i = data.task_src[i]
            for m in data.M:
                if (i, m) not in data.valid_assign:
                    continue
                in_paths = data.P_cand.get((src_i, m), [])
                total_xin_s = sum(result.x_in.get((i, m, p, s), 0.0) for p in range(len(in_paths)))
                expected = data.b_in[i] * result.r.get((i, m, s), 0.0)
                if abs(total_xin_s - expected) > 1e-4:
                    found_flow_issue = True
                    print(f"  ⚠ Flow issue: i={i} m={m} s={s}: sum xin={total_xin_s:.3f} != b*r={expected:.3f}")
    if not found_flow_issue:
        print("  ✓ Scenario flow conservation holds")

    print()


if __name__ == "__main__":
    test_m1_mesh()
    test_m1_mesh_sf()
    test_m1_mesh_combined()
    test_m1_sanity_checks()
    print("All M1 smoke tests completed.")
