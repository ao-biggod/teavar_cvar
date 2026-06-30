# -*- coding: utf-8 -*-
"""Runner for Toy-2Task independent data tests."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_toy_two_task_independent_data import (
    test_two_tasks_only,
    test_resource_totals,
    test_compute_capacity_semantics,
    test_paths_exist_for_each_task_compute_pair,
    test_multipath_is_necessary,
    test_independent_failure_probability_product,
    test_pruned_scenario_metadata,
    test_no_model_m_fields_required,
)

from toy_two_task_independent_data import NUM_COMPONENTS, build_toy_2task_independent_v1

tests = [
    ("two_tasks_only", test_two_tasks_only),
    ("resource_totals", test_resource_totals),
    ("compute_capacity_semantics", test_compute_capacity_semantics),
    ("paths_exist", test_paths_exist_for_each_task_compute_pair),
    ("multipath_necessary", test_multipath_is_necessary),
    ("product_probability", test_independent_failure_probability_product),
    ("pruned_metadata", test_pruned_scenario_metadata),
    ("no_model_m", test_no_model_m_fields_required),
]

passed = 0
failed = 0
print("=" * 56)
print("  Toy-2Task-IndependentComponentRisk-v1 Tests")
print("=" * 56)
for name, fn in tests:
    try:
        fn()
        print(f"  ✓ {name}")
        passed += 1
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        failed += 1

print(f"\n  {passed}/{len(tests)} passed, {failed} failed")
print("=" * 56)

# Summary
data = build_toy_2task_independent_v1()
meta = data.scenario_metadata
print(f"\nDataset summary:")
print(f"  Nodes: {len(data.V)}")
print(f"  Edges: {len(data.E)}")
print(f"  Compute nodes: {len(data.M)}")
print(f"  Tasks: {len(data.J)}")
print(f"  Independent components: {NUM_COMPONENTS}")
print(f"  Exhaustive scenarios: 2^{NUM_COMPONENTS} = {2**NUM_COMPONENTS}")
print(f"  Pruned scenarios: {len(data.S)}")
print(f"  Original mass: {meta['original_probability_mass']:.6f}")
print(f"  Dropped mass: {meta['dropped_probability_mass']:.6f}")
print(f"  Renormalized: {meta['renormalized']}")
