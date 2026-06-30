"""Tests for ToyTE dataset builder and validator."""
from __future__ import annotations

from toy_te_data import build_toy_te_dataset, ToyTEData, NODE_LABELS, K_LABELS, K
from validate_toy_te import validate_toy_te_data


def test_build_toy_te_dataset():
    data = build_toy_te_dataset()
    assert isinstance(data, ToyTEData)
    assert data.name == "ToyTE"


def test_validate_passes():
    data = build_toy_te_dataset()
    result = validate_toy_te_data(data)
    if not result["ok"]:
        print(result["summary"])
    assert result["ok"], f"Validation failed:\n{result['summary']}"


def test_validate_detailed_failures():
    """If validation fails, print every failing check + reason."""
    data = build_toy_te_dataset()
    result = validate_toy_te_data(data)
    failures = [(n, d) for n, p, d in result["checks"] if not p]
    assert len(failures) == 0, (
        f"{len(failures)} checks failed:\n" +
        "\n".join(f"  ✗ {n}: {d}" for n, d in failures)
    )


def test_toyte_node_count():
    data = build_toy_te_dataset()
    assert len(data.V) == 11, f"Expected 11 nodes, got {len(data.V)}"


def test_toyte_edge_count():
    data = build_toy_te_dataset()
    assert len(data.E) == 24, f"Expected 24 edges, got {len(data.E)}"


def test_toyte_compute_nodes():
    data = build_toy_te_dataset()
    assert len(data.M) == 3, f"Expected 3 compute nodes, got {len(data.M)}"


def test_toyte_task_count():
    data = build_toy_te_dataset()
    assert len(data.I) == 2, f"Expected 2 tasks, got {len(data.I)}"


def test_toyte_scenario_count():
    data = build_toy_te_dataset()
    assert len(data.S) == 4, f"Expected 4 scenarios, got {len(data.S)}"


def test_toyte_prob_sum_to_one():
    data = build_toy_te_dataset()
    total = sum(data.prob[s] for s in data.S)
    assert abs(total - 1.0) < 1e-12, f"Probabilities sum to {total}"


def test_toyte_each_task_has_candidates():
    data = build_toy_te_dataset()
    for i in data.I:
        candidates = [m for m in data.M if (i, m) in data.valid_assign]
        assert len(candidates) >= 1, f"Task {i} has no candidates"


def test_toyte_path_counts():
    data = build_toy_te_dataset()
    for i in data.I:
        src = data.task_src[i]
        dst = data.task_dst[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            nin = len(data.P_in.get((src, m), []))
            nout = len(data.P_out.get((m, dst), []))
            assert nin >= 2, f"P_in[src→{NODE_LABELS[m]}] has {nin} paths (need ≥2)"
            assert nout >= 2, f"P_out[{NODE_LABELS[m]}→dst] has {nout} paths (need ≥2)"


def test_toyte_path_start_end():
    data = build_toy_te_dataset()
    for i in data.I:
        src = data.task_src[i]
        dst = data.task_dst[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            for path in data.P_in.get((src, m), []):
                assert path[0][0] == src, f"Ingress path to {NODE_LABELS[m]} doesn't start at src"
                assert path[-1][1] == m, f"Ingress path to {NODE_LABELS[m]} doesn't end at compute"
            for path in data.P_out.get((m, dst), []):
                assert path[0][0] == m, f"Egress path from {NODE_LABELS[m]} doesn't start at compute"
                assert path[-1][1] == dst, f"Egress path from {NODE_LABELS[m]} doesn't end at dst"


def test_toyte_edges_exist():
    data = build_toy_te_dataset()
    edge_set = set(data.E)
    for i in data.I:
        src = data.task_src[i]
        dst = data.task_dst[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            for path in data.P_in.get((src, m), []):
                for e in path:
                    assert e in edge_set, f"Edge {e} in ingress path not in E"
            for path in data.P_out.get((m, dst), []):
                for e in path:
                    assert e in edge_set, f"Edge {e} in egress path not in E"


def test_toyte_positive_bandwidth():
    data = build_toy_te_dataset()
    for e in data.E:
        assert data.B.get(e, 0.0) > 0, f"B[{e}] is not positive"


def test_toyte_positive_w():
    data = build_toy_te_dataset()
    for i in data.I:
        for k in data.K:
            assert data.w[i][k] >= 0, f"w[{i}][{K_LABELS[k]}] < 0"


def test_toyte_positive_b_in_out():
    data = build_toy_te_dataset()
    for i in data.I:
        assert data.b_in[i] > 0, f"b_in[{i}] <= 0"
        assert data.b_out[i] > 0, f"b_out[{i}] <= 0"


def test_toyte_scenario_sigma():
    """Check that the failure scenarios actually disable something."""
    data = build_toy_te_dataset()
    # s1: node A failure — at least one edge incident to A should have sigma=0
    a_incident = [(u, v) for (u, v) in data.E if u == 2 or v == 2]
    any_a_fail = any(data.sigma.get(e, {}).get(1, 1.0) == 0.0 for e in a_incident)
    assert any_a_fail, "No A-incident edge has sigma=0 in s1"

    # s2: mA compute failure
    assert data.C_s[6][0][2] == 0.0, "mA CPU not zero in s2"

    # s3: a→c derated
    assert data.sigma.get((2, 3), {}).get(3, 1.0) < 1.0, "a→c not derated in s3"


def test_toyte_heterogeneous_compute():
    """Compute nodes should have different capacity profiles."""
    data = build_toy_te_dataset()
    # mA: CPU-rich, GPU-poor
    assert data.C_normal[6][0] > data.C_normal[6][1], "mA CPU should be > GPU"
    # mB: CPU-poor, GPU-rich
    assert data.C_normal[7][0] < data.C_normal[7][1], "mB CPU should be < GPU"
    # mC: balanced
    assert data.C_normal[8][0] == data.C_normal[8][1], "mC should be balanced"
    assert data.C_normal[8][0] == data.C_normal[8][2], "mC should be balanced"


def test_toyte_compute_bottleneck_exists():
    """Colocating both tasks on one node must overflow at least one resource."""
    data = build_toy_te_dataset()
    total_demand = {k: sum(data.w[i][k] for i in data.I) for k in data.K}
    has_bottleneck = False
    for m in data.M:
        for k in data.K:
            if total_demand[k] > data.C_normal[m][k]:
                has_bottleneck = True
                break
    assert has_bottleneck, "No compute bottleneck — all nodes can serve both tasks"


def test_toyte_not_knapsack():
    """Verify toy is not a degenerate knapsack."""
    data = build_toy_te_dataset()
    # Multiple sources
    srcs = set(data.task_src[i] for i in data.I)
    assert len(srcs) >= 2, "Only one source — knapsack risk"
    # Multiple destinations
    dsts = set(data.task_dst[i] for i in data.I)
    assert len(dsts) >= 2, "Only one destination — knapsack risk"
    # Multi-path everywhere
    for i in data.I:
        src = data.task_src[i]
        dst = data.task_dst[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            assert len(data.P_in[(src, m)]) >= 2, f"No multi-path ingress for task {i}→{NODE_LABELS[m]}"
            assert len(data.P_out[(m, dst)]) >= 2, f"No multi-path egress for task {i}←{NODE_LABELS[m]}"
    # Shared links exist
    all_paths = []
    for i in data.I:
        src = data.task_src[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            for path in data.P_in.get((src, m), []):
                all_paths.extend(path)
    edge_counts = {}
    for e in all_paths:
        edge_counts[e] = edge_counts.get(e, 0) + 1
    shared = {e: c for e, c in edge_counts.items() if c >= 3}  # used by ≥3 paths
    assert len(shared) >= 1, f"No links shared by multiple paths: {edge_counts}"
