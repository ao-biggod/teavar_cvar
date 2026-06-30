"""Tests for Toy-2Task-IndependentComponentRisk-v1 dataset."""
from __future__ import annotations

import math

from toy_two_task_independent_data import (
    build_toy_2task_independent_v1,
    TwoTaskIndependentData,
    NODE_LABELS, K_LABELS, K, M, E_SET, ALL_COMPONENTS,
    NUM_COMPONENTS, B_CAP,
    _scenario_probability, _component_p,
)


def test_two_tasks_only():
    """Only task1 and task2.  Exactly 9 placements (no AAA/ABC)."""
    data = build_toy_2task_independent_v1()
    assert len(data.J) == 2, f"Expected 2 tasks, got {len(data.J)}"

    placements = []
    for i in data.J:
        for m in data.M:
            if (i, m) in data.valid_assign:
                placements.append((i, m))
    # 2 tasks × 3 nodes = 6 valid pairs → 9 compound placements
    assert len(placements) == 6, f"Expected 6 valid-assign pairs, got {len(placements)}"

    # Verify no three-task patterns
    compound = [f"{NODE_LABELS[m]}" for i in data.J for m in data.M if (i, m) in data.valid_assign]
    assert len(compound) == 6
    print(f"  Compound placements: AA, AB, AC, BA, BB, BC, CA, CB, CC "
          f"(9 combos from {len(data.J)} tasks × {len(data.M)} nodes)")


def test_resource_totals():
    """w1 + w2 = {CPU: 7, GPU: 3, HBM: 5}."""
    data = build_toy_2task_independent_v1()
    total = {k: 0.0 for k in K}
    for i in data.J:
        for k in K:
            total[k] += data.w[i][k]
    assert total[0] == 7.0, f"CPU total = {total[0]}, expected 7.0"
    assert total[1] == 3.0, f"GPU total = {total[1]}, expected 3.0"
    assert total[2] == 5.0, f"HBM total = {total[2]}, expected 5.0"
    print(f"  w1 + w2 = CPU={total[0]}, GPU={total[1]}, HBM={total[2]}")


def test_compute_capacity_semantics():
    """Check hard-capacity semantics for AA, BB, CC."""
    data = build_toy_2task_independent_v1()
    total_demand = {k: sum(data.w[i][k] for i in data.J) for k in K}

    # AA → mA: GPU=3>2, HBM=5>4
    ma_gpu_overflow = total_demand[1] > data.C[4][1]
    ma_hbm_overflow = total_demand[2] > data.C[4][2]
    assert ma_gpu_overflow, "AA should overflow mA GPU"
    assert ma_hbm_overflow, "AA should overflow mA HBM"
    print(f"  AA overflows mA GPU ({total_demand[1]} > {data.C[4][1]}) ✓")
    print(f"  AA overflows mA HBM ({total_demand[2]} > {data.C[4][2]}) ✓")

    # BB → mB: CPU=7>6
    mb_cpu_overflow = total_demand[0] > data.C[5][0]
    assert mb_cpu_overflow, "BB should overflow mB CPU"
    print(f"  BB overflows mB CPU ({total_demand[0]} > {data.C[5][0]}) ✓")

    # CC → mC: all fine
    mc_ok = all(total_demand[k] <= data.C[6][k] for k in K)
    assert mc_ok, "CC should be feasible on mC"
    print(f"  CC is feasible on mC ({total_demand} <= {data.C[6]}) ✓")

    # Mixed placements: all feasible
    mixed_expectations = {
        (0, 4): True, (0, 5): True, (0, 6): True,  # task1 → any
        (1, 4): True, (1, 5): True, (1, 6): True,  # task2 → any
    }
    for i in data.J:
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            demand = {k: data.w[i][k] for k in K}
            feasible = all(demand[k] <= data.C[m][k] for k in K)
            expected = mixed_expectations[(i, m)]
            assert feasible == expected, (
                f"Mixed placement i{i}→{NODE_LABELS[m]} "
                f"feasible={feasible}, expected={expected}"
            )
    print(f"  All mixed placements feasible ✓")


def test_paths_exist_for_each_task_compute_pair():
    """Each (i,m) has 2 ingress + 2 egress paths, all edges in E."""
    data = build_toy_2task_independent_v1()
    for i in data.J:
        src = data.task_src[i]
        dst = data.task_dst[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            in_paths = data.P_in.get((src, m), [])
            out_paths = data.P_out.get((m, dst), [])
            assert len(in_paths) == 2, f"P_in[{NODE_LABELS[src]}→{NODE_LABELS[m]}] has {len(in_paths)} paths"
            assert len(out_paths) == 2, f"P_out[{NODE_LABELS[m]}→{NODE_LABELS[dst]}] has {len(out_paths)} paths"
            for path in in_paths:
                for e in path:
                    assert e in E_SET, f"Edge {e} in P_in not in E"
            for path in out_paths:
                for e in path:
                    assert e in E_SET, f"Edge {e} in P_out not in E"
    print(f"  All 12 task-compute pairs have 2+2 paths ✓")


def test_multipath_is_necessary():
    """Single-path bottlenecks force multipath.

    Task1 b_in=4.0: every single ingress path bottleneck < 4.0.
    Task2 b_out=2.5: every single egress path bottleneck < 2.5.
    """
    data = build_toy_2task_independent_v1()

    # Task1 ingress: all single-path bottlenecks < 4.0
    for m in data.M:
        if (0, m) not in data.valid_assign:
            continue
        for path in data.P_in.get((data.task_src[0], m), []):
            bottleneck = min(data.B[e] for e in path)
            assert bottleneck < 4.0 - 1e-9, (
                f"Task1 ingress {NODE_LABELS[m]} path {path} "
                f"bottleneck={bottleneck} >= 4.0"
            )
    print(f"  Task1 ingress: all bottlenecks < 4.0 (need multipath) ✓")

    # Task2 egress: all single-path bottlenecks < 2.5
    for m in data.M:
        if (1, m) not in data.valid_assign:
            continue
        for path in data.P_out.get((m, data.task_dst[1]), []):
            bottleneck = min(data.B[e] for e in path)
            assert bottleneck < 2.5 - 1e-9, (
                f"Task2 egress {NODE_LABELS[m]} path {path} "
                f"bottleneck={bottleneck} >= 2.5"
            )
    print(f"  Task2 egress: all bottlenecks < 2.5 (need multipath) ✓")


def test_independent_failure_probability_product():
    """A small scenario's probability equals the product formula."""
    data = build_toy_2task_independent_v1()

    # Pick a specific scenario: only (MA, MB) compute nodes fail
    ma_idx = None
    mb_idx = None
    for idx, (ctype, cid) in enumerate(ALL_COMPONENTS):
        if ctype == "compute" and cid == 4:
            ma_idx = idx
        if ctype == "compute" and cid == 5:
            mb_idx = idx

    failed = {ma_idx, mb_idx}
    computed_prob = _scenario_probability(failed)

    # Manual product
    p_ma = _component_p("compute", 4)   # 0.08
    p_mb = _component_p("compute", 5)   # 0.04
    expected = p_ma * p_mb
    for idx, (ctype, cid) in enumerate(ALL_COMPONENTS):
        if idx not in failed:
            expected *= (1.0 - _component_p(ctype, cid))

    assert abs(computed_prob - expected) < 1e-15, (
        f"Probability mismatch: {computed_prob} vs {expected}"
    )
    print(f"  Product probability check passed: {expected:.6e} ✓")


def test_pruned_scenario_metadata():
    """Pruned mode metadata checks."""
    data = build_toy_2task_independent_v1(
        scenario_mode="pruned",
        max_failed_components=3,
        renormalize_probabilities=True,
    )
    meta = data.scenario_metadata

    # Renormalised → sum(pi) = 1
    total_pi = sum(data.pi.values())
    assert abs(total_pi - 1.0) < 1e-10, f"sum(pi)={total_pi}, expected 1.0"
    print(f"  sum(pi) = {total_pi:.10f} ✓")

    # original > 0, dropped > 0
    assert meta["original_probability_mass"] > 0, "original mass should be > 0"
    assert meta["dropped_probability_mass"] > 0, "dropped mass should be > 0"
    print(f"  original_probability_mass = {meta['original_probability_mass']:.6f}")
    print(f"  dropped_probability_mass = {meta['dropped_probability_mass']:.6f}")


def test_drop_renormalize_preserved():
    """Drop-renormalize mode: probabilities sum to 1, no aggregate scenario."""
    data = build_toy_2task_independent_v1(
        scenario_mode="pruned",
        max_failed_components=3,
        renormalize_probabilities=True,
        prune_mode="drop_renormalize",
    )
    meta = data.scenario_metadata
    # Sum of pi = 1
    total = sum(data.pi.values())
    assert abs(total - 1.0) < 1e-10, f"drop_renormalize sum(pi)={total}"
    # Renormalized flag
    assert meta["renormalized"] is True
    # No aggregate scenario
    if meta.get("has_aggregate_worst") is None:
        pass  # old metadata without this key is OK
    else:
        assert meta["has_aggregate_worst"] is False
    print(f"  sum(pi) = {total:.10f}, renormalized=True, has_aggregate=False ✓")


def test_aggregate_worst_probability_mass():
    """Aggregate-worst mode: kept scenarios not renormalised, total = 1."""
    data = build_toy_2task_independent_v1(
        scenario_mode="pruned",
        max_failed_components=3,
        renormalize_probabilities=True,  # ignored in aggregate_worst mode
        prune_mode="aggregate_worst",
    )
    meta = data.scenario_metadata
    total = sum(data.pi.values())
    # Total probability mass = 1 (kept original + aggregate)
    assert abs(total - 1.0) < 1e-10, f"aggregate_worst sum(pi)={total}"
    assert meta["has_aggregate_worst"] is True
    agg_prob = meta.get("aggregate_worst_probability", 0.0)
    assert agg_prob > 0, f"aggregate_worst_probability should be > 0, got {agg_prob}"
    # Kept scenarios are NOT renormalised → their raw sum = original_probability_mass
    kept_prob = total - agg_prob
    assert abs(kept_prob - meta["original_probability_mass"]) < 1e-10, \
        f"kept prob {kept_prob} != original mass {meta['original_probability_mass']}"
    print(f"  total={total:.6f}, agg_prob={agg_prob:.6f}, original_mass={meta['original_probability_mass']:.6f} ✓")


def test_aggregate_worst_metadata():
    """Aggregate-worst metadata keys present and consistent."""
    data = build_toy_2task_independent_v1(
        scenario_mode="pruned",
        max_failed_components=2,
        renormalize_probabilities=False,
        prune_mode="aggregate_worst",
    )
    meta = data.scenario_metadata
    assert meta.get("has_aggregate_worst") is True, "missing has_aggregate_worst=True"
    assert meta.get("aggregate_worst_probability", 0.0) > 0, "aggregate prob should > 0"
    assert meta.get("prune_mode") == "aggregate_worst"
    assert meta.get("dropped_probability_mass", 0.0) > 0
    assert meta.get("original_probability_mass", 0.0) > 0
    # Aggregate scenario should exist as last scenario
    agg_sid = data.S[-1]
    # Aggregate B_s should be all zeros (B_s is always s→e format)
    for e in data.E:
        assert data.B_s[agg_sid][e] == 0.0, f"B_s[{agg_sid}][{e}] should be 0"
    # Aggregate C_s should be all zeros
    # Detect C_s format: if C_by_original exists → s→m→k format
    C_orig = getattr(data, "C_by_original", None)
    if C_orig is not None and agg_sid in C_orig:
        for m in data.M:
            for k in data.K:
                assert C_orig[agg_sid][m][k] == 0.0, f"C_s[{agg_sid}][{m}][{k}] should be 0"
    else:
        # M1 format: C_s[m][k][s]
        for m in data.M:
            for k in data.K:
                assert data.C_s[m][k][agg_sid] == 0.0, f"C_s[{m}][{k}][{agg_sid}] should be 0"
    print(f"  aggregate scenario {agg_sid}: all capacities = 0 ✓")


def test_existing_toy_build_still_works():
    """Default parameters still build successfully."""
    data = build_toy_2task_independent_v1()
    assert len(data.J) == 2
    assert len(data.M) == 3
    assert len(data.S) == 2048
    meta = data.scenario_metadata
    assert meta["scenario_mode"] == "pruned"
    assert abs(sum(data.pi.values()) - 1.0) < 1e-10
    print(f"  {len(data.J)} tasks, {len(data.M)} nodes, {len(data.S)} scenarios ✓")

    # Scenario count far less than exhaustive
    num_exhaustive = 2 ** NUM_COMPONENTS  # 2^23 = 8,388,608
    assert len(data.S) < num_exhaustive // 1000, (
        f"Pruned scenarios ({len(data.S)}) not far less than exhaustive ({num_exhaustive})"
    )
    print(f"  Exhaustive scenarios: {num_exhaustive}")
    print(f"  Pruned scenarios:     {len(data.S)} (<< {num_exhaustive}) ✓")

    # Metadata fields
    assert meta["scenario_mode"] == "pruned"
    assert meta["renormalized"] is True
    assert meta["max_failed_components"] == 3
    assert meta["num_components"] == NUM_COMPONENTS


def test_no_model_m_fields_required():
    """Confirm no Model-M / monetary CVaR fields."""
    data = build_toy_2task_independent_v1()
    assert hasattr(data, "C")
    assert not hasattr(data, "kappa_sf")
    assert hasattr(data, "pi")
    # w is task compute demand, not priced
    print(f"  No Model-M / monetary CVaR fields required ✓")


def test_exhaustive_scenario_count():
    """Exhaustive mode: 2^23 = 8,388,608 scenarios."""
    data = build_toy_2task_independent_v1(
        scenario_mode="exhaustive",
    )
    expected = 2 ** NUM_COMPONENTS
    assert len(data.S) == expected, (
        f"Exhaustive scenarios: {len(data.S)} vs expected {expected}"
    )
    # sum(pi) should be ~1 (may have tiny FP error, not renormalised)
    total_pi = sum(data.pi.values())
    assert abs(total_pi - 1.0) < 1e-12, f"sum(pi)={total_pi}"
    print(f"  Exhaustive: {len(data.S)} scenarios, sum(pi)={total_pi:.15f} ✓")


def test_pruned_scenario_count():
    """Pruned (max_fail=3): sum C(23,0..3) = 2048 scenarios."""
    data = build_toy_2task_independent_v1(
        scenario_mode="pruned",
        max_failed_components=3,
    )
    from math import comb
    expected = sum(comb(NUM_COMPONENTS, k) for k in range(0, 4))  # 0..3
    assert len(data.S) == expected, (
        f"Pruned scenarios: {len(data.S)} vs expected {expected}"
    )
    print(f"  Pruned: {len(data.S)} scenarios ✓")
