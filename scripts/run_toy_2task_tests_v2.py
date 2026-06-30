# -*- coding: utf-8 -*-
"""Standalone tests for Toy-2Task-IndependentComponentRisk-v1."""
import sys, os, traceback
from pathlib import Path

# Project root derived from current file location (not hardcoded)
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from toy_two_task_independent_data import (
    build_toy_2task_independent_v1,
    NODE_LABELS, K_LABELS, K, M,
    ALL_COMPONENTS, NUM_COMPONENTS,
    _scenario_probability, _component_p, _iter_combinations,
)
from math import comb

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  ✓ {name}")
        passed += 1
    except Exception as e:
        traceback.print_exc()
        print(f"  ✗ {name}: {e}")
        failed += 1

# --- test 1 ---
def _t1():
    data = build_toy_2task_independent_v1()
    assert len(data.J) == 2
    pairs = [(i,m) for i in data.J for m in data.M if (i,m) in data.valid_assign]
    assert len(pairs) == 6

# --- test 2 ---
def _t2():
    data = build_toy_2task_independent_v1()
    t = {k: sum(data.w[i][k] for i in data.J) for k in K}
    assert t[0]==7.0 and t[1]==3.0 and t[2]==5.0

# --- test 3 ---
def _t3():
    data = build_toy_2task_independent_v1()
    td = {k: sum(data.w[i][k] for i in data.J) for k in K}
    assert td[1] > data.C[4][1], "AA GPU overflow"
    assert td[2] > data.C[4][2], "AA HBM overflow"
    assert td[0] > data.C[5][0], "BB CPU overflow"
    assert all(td[k] <= data.C[6][k] for k in K), "CC OK"
    for i in data.J:
        for m in data.M:
            if (i,m) in data.valid_assign:
                d = {k: data.w[i][k] for k in K}
                assert all(d[k] <= data.C[m][k] for k in K)

# --- test 4 ---
def _t4():
    data = build_toy_2task_independent_v1()
    e_set = set(data.E)
    for i in data.J:
        src, dst = data.task_src[i], data.task_dst[i]
        for m in data.M:
            if (i,m) not in data.valid_assign:
                continue
            ip = data.P_in[(src,m)]
            op = data.P_out[(m,dst)]
            assert len(ip) == 2
            assert len(op) == 2
            for path in ip + op:
                for e in path:
                    assert e in e_set, f"Edge {e} not in E"

# --- test 5 ---
def _t5():
    data = build_toy_2task_independent_v1()
    for m in data.M:
        if (0,m) in data.valid_assign:
            for p in data.P_in[(data.task_src[0], m)]:
                assert min(data.B[e] for e in p) < 4.0
    for m in data.M:
        if (1,m) in data.valid_assign:
            for p in data.P_out[(m, data.task_dst[1])]:
                assert min(data.B[e] for e in p) < 2.5

# --- test 6 ---
def _t6():
    ma_idx = next(i for i,(ct,cid) in enumerate(ALL_COMPONENTS) if ct=='compute' and cid==4)
    mb_idx = next(i for i,(ct,cid) in enumerate(ALL_COMPONENTS) if ct=='compute' and cid==5)
    failed_set = {ma_idx, mb_idx}
    p = _scenario_probability(failed_set)
    expected = _component_p('compute',4) * _component_p('compute',5)
    for idx,(ct,cid) in enumerate(ALL_COMPONENTS):
        if idx not in failed_set:
            expected *= (1.0 - _component_p(ct,cid))
    assert abs(p - expected) < 1e-15

# --- test 7 ---
def _t7():
    data = build_toy_2task_independent_v1(scenario_mode="pruned", max_failed_components=3)
    meta = data.scenario_metadata
    assert abs(sum(data.pi.values()) - 1.0) < 1e-10
    assert meta["original_probability_mass"] > 0
    assert meta["dropped_probability_mass"] > 0
    expected = sum(comb(NUM_COMPONENTS, k) for k in range(0,4))
    assert len(data.S) == expected, f"{len(data.S)} vs {expected}"
    assert meta["scenario_mode"] == "pruned"
    assert meta["renormalized"] == True

# --- test 8 ---
def _t8():
    data = build_toy_2task_independent_v1()
    assert hasattr(data, "C")
    assert not hasattr(data, "kappa_sf")

# --- test 9 (purely math — NO 8M iteration) ---
def _t9():
    # Exhaustive formula: 2^23 = 8,388,608
    expected = 2 ** NUM_COMPONENTS
    assert expected == 8_388_608
    # Verify _iter_combinations on tiny n only (n=5, fast)
    n_small = 5
    exhaustive_count = sum(1 for _ in _iter_combinations(n_small, total_components=n_small))
    assert exhaustive_count == 2 ** n_small, f"n=5: {exhaustive_count} vs {2**n_small}"
    pruned_count = sum(1 for _ in _iter_combinations(3, total_components=n_small))
    expected_pruned = sum(comb(n_small, k) for k in range(0, 4))
    assert pruned_count == expected_pruned, f"n=5 pruned: {pruned_count} vs {expected_pruned}"
    print(f"    n=5 exhaustive:    2^{n_small} = {exhaustive_count} ✓")
    print(f"    n=5 pruned (≤3):   {pruned_count} = {expected_pruned} ✓")
    print(f"    n={NUM_COMPONENTS} formula: 2^{NUM_COMPONENTS} = {expected} ✓")

# --- test 10 ---
def _t10():
    data = build_toy_2task_independent_v1(scenario_mode="pruned", max_failed_components=2, renormalize_probabilities=True)
    meta = data.scenario_metadata
    assert len(data.S) == sum(comb(NUM_COMPONENTS, k) for k in range(0,3))
    assert abs(sum(data.pi.values()) - 1.0) < 1e-10
    assert meta["dropped_probability_mass"] > meta["original_probability_mass"] * 0.001

# Run
print("=" * 56)
print("  Toy-2Task-IndependentComponentRisk-v1 Tests")
print("=" * 56)

tests = [
    ("two_tasks_only", _t1),
    ("resource_totals", _t2),
    ("compute_capacity_semantics", _t3),
    ("paths_and_edges", _t4),
    ("multipath_necessary", _t5),
    ("product_probability", _t6),
    ("pruned_metadata", _t7),
    ("no_model_m", _t8),
    ("exhaustive_formula", _t9),
    ("pruned_maxfail2", _t10),
]
for name, fn in tests:
    test(name, fn)

print(f"\n  {passed}/{len(tests)} passed, {failed} failed")
print("=" * 56)

# Summary
data = build_toy_2task_independent_v1()
meta = data.scenario_metadata
print(f"\nDataset: {data.name}")
print(f"  Nodes: {len(data.V)} | Edges: {len(data.E)} | Compute: {len(data.M)} | Tasks: {len(data.J)}")
print(f"  Independent components: {NUM_COMPONENTS} ({len(data.M)} compute + {len(data.E)} links)")
print(f"  Exhaustive scenarios: 2^{NUM_COMPONENTS} = {2**NUM_COMPONENTS}")
print(f"  Pruned (max_fail=3): {len(data.S)} scenarios")
print(f"  Original prob mass: {meta['original_probability_mass']:.6f}")
print(f"  Dropped prob mass:  {meta['dropped_probability_mass']:.6f}")
print(f"  Renormalized: {meta['renormalized']}")
