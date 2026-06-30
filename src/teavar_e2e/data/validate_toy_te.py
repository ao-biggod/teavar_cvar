"""Validator for ToyTEData — run before any experiment to catch design flaws."""
from __future__ import annotations

from typing import Any

from teavar_e2e.data.toy_te_data import (
    ToyTEData,
    E_SET, V, M, K, I, S,
    SHARED_INGRESS_BOTTLENECKS, SHARED_EGRESS_BOTTLENECKS,
    COMPUTE_BOTTLENECKS, NODE_LABELS, K_LABELS,
)


def validate_toy_te_data(data: ToyTEData, *, strict_forwarding_transit: bool = False) -> dict[str, Any]:
    """Run all sanity checks.  Returns a dict with check results.

    Parameters
    ----------
    strict_forwarding_transit :
        If True, intermediate nodes on every path must belong to ``R``
        (forwarding-only nodes).  Default False — compute-capable nodes
        may appear as transit nodes.

    Keys:
      ``ok`` — bool, True if every check passed
      ``summary`` — human-readable report string
      ``checks`` — list of (name, passed, detail) tuples
    """
    checks: list[tuple[str, bool, str]] = []
    ok = True

    def _check(name: str, condition: bool, detail: str = ""):
        nonlocal ok
        passed = bool(condition)
        if not passed:
            ok = False
        checks.append((name, passed, detail))

    # 0. Topology integrity
    v_set = set(data.V)
    m_set = set(data.M)
    _check("0a. M ⊆ V", m_set.issubset(v_set), f"extra nodes in M: {m_set - v_set}")

    # 0b. All task-source / task-dst nodes exist in V
    for i in data.I:
        _check(f"0b. task_src[{i}] ∈ V", data.task_src[i] in v_set,
               f"src={NODE_LABELS.get(data.task_src[i], data.task_src[i])}")
        _check(f"0b. task_dst[{i}] ∈ V", data.task_dst[i] in v_set,
               f"dst={NODE_LABELS.get(data.task_dst[i], data.task_dst[i])}")

    # 0c. valid_assign ⊆ J × M
    for (i, m) in data.valid_assign:
        _check(f"0c. valid_assign ({i},{NODE_LABELS.get(m,m)}) ∈ J × M",
               i in data.I and m in data.M, "")

    # 0d. All path nodes are in V; optionally enforce transit-only forwarding
    v_set = set(data.V)
    r_set = set(data.R)  # forwarding-only nodes
    for i in data.I:
        src = data.task_src[i]
        dst = data.task_dst[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            for path in data.P_in.get((src, m), []):
                for edge_idx, e in enumerate(path):
                    u, v = e[0], e[1]
                    _check(f"0d. path node {NODE_LABELS.get(u,u)} ∈ V",
                           u in v_set, f"missing from V: {u}")
                    _check(f"0d. path node {NODE_LABELS.get(v,v)} ∈ V",
                           v in v_set, f"missing from V: {v}")
                    if strict_forwarding_transit:
                        # Intermediate nodes (not first src or last compute)
                        is_first = (edge_idx == 0 and u == src)
                        is_last = (edge_idx == len(path) - 1 and v == m)
                        if not is_first and not is_last:
                            for n in (u, v):
                                _check(f"0d. transit node {NODE_LABELS.get(n,n)} ∈ R",
                                       n in r_set,
                                       f"compute node used as transit (strict mode)")
            for path in data.P_out.get((m, dst), []):
                for edge_idx, e in enumerate(path):
                    u, v = e[0], e[1]
                    _check(f"0d. path node {NODE_LABELS.get(u,u)} ∈ V",
                           u in v_set, f"missing from V: {u}")
                    _check(f"0d. path node {NODE_LABELS.get(v,v)} ∈ V",
                           v in v_set, f"missing from V: {v}")
                    if strict_forwarding_transit:
                        is_first = (edge_idx == 0 and u == m)
                        is_last = (edge_idx == len(path) - 1 and v == dst)
                        if not is_first and not is_last:
                            for n in (u, v):
                                _check(f"0d. transit node {NODE_LABELS.get(n,n)} ∈ R",
                                       n in r_set,
                                       f"compute node used as transit (strict mode)")

    # 1. Each task has at least one candidate execution node
    for i in data.I:
        candidates = [m for m in data.M if (i, m) in data.valid_assign]
        _check(f"1. task {i} has candidate compute nodes",
               len(candidates) >= 1,
               f"candidates={candidates}")

    # 2. Each task-compute pair has P_in and P_out
    for i in data.I:
        src = data.task_src[i]
        dst = data.task_dst[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            has_p_in = (src, m) in data.P_in
            has_p_out = (m, dst) in data.P_out
            _check(f"2. P_in/P_out for task {i} → node {NODE_LABELS[m]}",
                   has_p_in and has_p_out,
                   f"P_in={has_p_in}, P_out={has_p_out}")

    # 3-4. Each P_in / P_out has ≥ 2 paths
    for i in data.I:
        src = data.task_src[i]
        dst = data.task_dst[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            nin = len(data.P_in.get((src, m), []))
            nout = len(data.P_out.get((m, dst), []))
            _check(f"3a. P_in[{NODE_LABELS[src]}→{NODE_LABELS[m]}] ≥ 2 paths",
                   nin >= 2, f"count={nin}")
            _check(f"3b. P_out[{NODE_LABELS[m]}→{NODE_LABELS[dst]}] ≥ 2 paths",
                   nout >= 2, f"count={nout}")

    # 5. Ingress path starts at src, ends at compute node
    for i in data.I:
        src = data.task_src[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            paths = data.P_in.get((src, m), [])
            for p_idx, path in enumerate(paths):
                if not path or len(path) == 0:
                    _check(f"4. P_in[{NODE_LABELS[src]}→{NODE_LABELS[m]}][{p_idx}] non-empty",
                           False, "empty path")
                    continue
                first_edge = path[0]
                last_edge = path[-1]
                _check(f"4a. P_in[{NODE_LABELS[src]}→{NODE_LABELS[m]}][{p_idx}] starts at src",
                       isinstance(first_edge, tuple) and first_edge[0] == src,
                       f"got {first_edge}")
                _check(f"4b. P_in[{NODE_LABELS[src]}→{NODE_LABELS[m]}][{p_idx}] ends at compute",
                       isinstance(last_edge, tuple) and last_edge[1] == m,
                       f"got last edge {last_edge}")

    # 6. Egress path starts at compute, ends at dst
    for i in data.I:
        dst = data.task_dst[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            paths = data.P_out.get((m, dst), [])
            for p_idx, path in enumerate(paths):
                if not path or len(path) == 0:
                    _check(f"5. P_out[{NODE_LABELS[m]}→{NODE_LABELS[dst]}][{p_idx}] non-empty",
                           False, "empty path")
                    continue
                first_edge = path[0]
                last_edge = path[-1]
                _check(f"5a. P_out[{NODE_LABELS[m]}→{NODE_LABELS[dst]}][{p_idx}] starts at compute",
                       isinstance(first_edge, tuple) and first_edge[0] == m,
                       f"got {first_edge}")
                _check(f"5b. P_out[{NODE_LABELS[m]}→{NODE_LABELS[dst]}][{p_idx}] ends at dst",
                       isinstance(last_edge, tuple) and last_edge[1] == dst,
                       f"got last edge {last_edge}")

    # 7. Every edge in every path exists in E
    for i in data.I:
        src = data.task_src[i]
        dst = data.task_dst[i]
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            for path in data.P_in.get((src, m), []):
                for e in path:
                    _check(f"6. edge {NODE_LABELS.get(e[0],e[0])}→{NODE_LABELS.get(e[1],e[1])} in E",
                           e in E_SET,
                           f"missing edge {e}")
            for path in data.P_out.get((m, dst), []):
                for e in path:
                    _check(f"6. edge {NODE_LABELS.get(e[0],e[0])}→{NODE_LABELS.get(e[1],e[1])} in E",
                           e in E_SET,
                           f"missing edge {e}")

    # 8. All B[e] > 0
    for e in data.E:
        _check(f"7. B[{NODE_LABELS.get(e[0],e[0])}→{NODE_LABELS.get(e[1],e[1])}] > 0",
               data.B.get(e, 0.0) > 0,
               f"B={data.B.get(e, 0.0)}")

    # 9. All C_normal[m,k] ≥ 0
    for m in data.M:
        for k in data.K:
            val = data.C_normal.get(m, {}).get(k, -1.0)
            _check(f"8. C_normal[{NODE_LABELS[m]}][{K_LABELS[k]}] ≥ 0",
                   val >= 0, f"value={val}")

    # 10. All b_in, b_out, w[i,k] ≥ 0
    for i in data.I:
        _check(f"9a. b_in[{i}] ≥ 0", data.b_in.get(i, -1.0) >= 0,
               f"value={data.b_in.get(i, -1.0)}")
        _check(f"9b. b_out[{i}] ≥ 0", data.b_out.get(i, -1.0) >= 0,
               f"value={data.b_out.get(i, -1.0)}")
        for k in data.K:
            _check(f"9c. w[{i}][{K_LABELS[k]}] ≥ 0",
                   data.w.get(i, {}).get(k, -1.0) >= 0,
                   f"value={data.w.get(i, {}).get(k, -1.0)}")

    # 11. sum_s p_s = 1
    total_p = sum(data.prob.get(s, 0.0) for s in data.S)
    _check("10. sum_s prob[s] = 1",
           abs(total_p - 1.0) < 1e-10,
           f"sum={total_p}")

    # 12. All B_s[e,s] ≥ 0
    for e in data.E:
        for s in data.S:
            val = data.B_s.get(e, {}).get(s, -1.0)
            _check(f"11. B_s[{NODE_LABELS.get(e[0],e[0])}→{NODE_LABELS.get(e[1],e[1])}][s{s}] ≥ 0",
                   val >= 0, f"value={val}")

    # 13. All C_s[m,k,s] ≥ 0
    for m in data.M:
        for k in data.K:
            for s in data.S:
                val = data.C_s.get(m, {}).get(k, {}).get(s, -1.0)
                _check(f"12. C_s[{NODE_LABELS[m]}][{K_LABELS[k]}][s{s}] ≥ 0",
                       val >= 0, f"value={val}")

    # 14. At least one shared bottleneck link (ingress or egress)
    all_bottlenecks = SHARED_INGRESS_BOTTLENECKS + SHARED_EGRESS_BOTTLENECKS
    _check("13. at least one shared bottleneck link",
           len(all_bottlenecks) >= 1,
           f"bottleneck count={len(all_bottlenecks)}")

    # 15. At least one compute bottleneck (colocation overflows some resource)
    _check("14. at least one compute bottleneck",
           len(COMPUTE_BOTTLENECKS) >= 1,
           f"compute bottleneck count={len(COMPUTE_BOTTLENECKS)}")

    # 16. Not a knapsack: multiple sources, multiple destinations, multi-path, shared links
    unique_srcs = len(set(data.task_src[i] for i in data.I))
    unique_dsts = len(set(data.task_dst[i] for i in data.I))
    multi_path_ok = all(
        len(data.P_in.get((data.task_src[i], m), [])) >= 2
        and len(data.P_out.get((m, data.task_dst[i]), [])) >= 2
        for i in data.I for m in data.M if (i, m) in data.valid_assign
    )
    _check("15. multiple sources (≥2)", unique_srcs >= 2, f"src_count={unique_srcs}")
    _check("16. multiple destinations (≥2)", unique_dsts >= 2, f"dst_count={unique_dsts}")
    _check("17. multi-path for every task-compute pair", multi_path_ok, "")
    _check("18. shared bottleneck links exist", len(all_bottlenecks) > 0,
           f"bottleneck_count={len(all_bottlenecks)}")

    # Build summary
    lines = [
        "=" * 56,
        "  ToyTE Sanity Check Report",
        "=" * 56,
        f"  Total checks:    {len(checks)}",
        f"  Passed:          {sum(1 for _, p, _ in checks if p)}",
        f"  Failed:          {sum(1 for _, p, _ in checks if not p)}",
        f"  Overall:         {'✓ ALL PASSED' if ok else '✗ FAILURES DETECTED'}",
        "=" * 56,
    ]
    for name, passed, detail in checks:
        icon = "✓" if passed else "✗"
        label = name[:60]
        if detail:
            lines.append(f"  {icon} {label:<55s}  # {detail}")
        else:
            lines.append(f"  {icon} {label:<55s}")

    return {
        "ok": ok,
        "summary": "\n".join(lines),
        "checks": checks,
    }
