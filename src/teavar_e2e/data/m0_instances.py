# -*- coding: utf-8 -*-
"""M0 deterministic toy instances (two-stage multi-path, no scenarios)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

K_CPU, K_GPU, K_HBM = 0, 1, 2
TOY_K = [K_CPU, K_GPU, K_HBM]

# Topology node ids
M0_SRC0, M0_SRC1 = 0, 1
M0_DST0, M0_DST1 = 2, 3
M0_RELAY = 7
M0_COMPUTE = (4, 5, 6)


@dataclass
class M0Data:
    """Minimal attribute bag for ``build_m0_model``."""

    I: list[int] = field(default_factory=list)
    M: list[int] = field(default_factory=list)
    K: list[int] = field(default_factory=lambda: list(TOY_K))
    E: list[tuple[int, int]] = field(default_factory=list)
    B: dict[tuple[int, int], float] = field(default_factory=dict)
    C_normal: dict[int, dict[int, float]] = field(default_factory=dict)
    P_cand: dict[tuple[int, int], list[list[tuple[int, int]]]] = field(default_factory=dict)
    valid_assign: set[tuple[int, int]] = field(default_factory=set)
    task_src: dict[int, int] = field(default_factory=dict)
    task_dst: dict[int, int] = field(default_factory=dict)
    b_in: dict[int, float] = field(default_factory=dict)
    b_out: dict[int, float] = field(default_factory=dict)
    w: dict[int, dict[int, float]] = field(default_factory=dict)
    routing_mode: str = "per_task_od"


def _two_paths(u: int, v: int, relay: int) -> list[list[tuple[int, int]]]:
    """Direct edge and relay detour; both paths must be edge-disjoint enough to count as 2 routes."""
    if u == v:
        return [[], []]
    direct = [(u, v)]
    if relay not in (u, v):
        detour = [(u, relay), (relay, v)]
        return [direct, detour]
    return [direct, direct]


def _add_paths(data: M0Data, u: int, v: int, relay: int) -> None:
    paths = _two_paths(u, v, relay)
    if len(paths) < 2:
        raise ValueError(f"need >=2 paths for ({u},{v})")
    data.P_cand[u, v] = paths


def _collect_edges(data: M0Data) -> None:
    edges: set[tuple[int, int]] = set()
    for paths in data.P_cand.values():
        for path in paths:
            for e in path:
                edges.add((int(e[0]), int(e[1])))
    data.E = sorted(edges)


def _default_bandwidth(data: M0Data) -> None:
    for e in data.E:
        data.B[e] = 100.0
    # Narrow edges: detour relay links (lambda_m0=1 prefers direct / balanced split).
    data.B[(M0_SRC0, M0_RELAY)] = 12.0
    data.B[(M0_SRC1, M0_RELAY)] = 12.0
    data.B[(M0_RELAY, M0_COMPUTE[0])] = 12.0
    data.B[(M0_RELAY, M0_COMPUTE[2])] = 12.0
    # Direct ingress to compute-4 is tight when used alone.
    data.B[(M0_SRC0, M0_COMPUTE[0])] = 16.0
    data.B[(M0_SRC1, M0_COMPUTE[2])] = 16.0


def build_m0_toy() -> M0Data:
    """
    Small multi-path M0 toy: 2 tasks, 3 compute nodes, shared relay.

    - Each ``(s_i, m)`` and ``(m, d_i)`` has >=2 candidate paths.
    - Nominal capacities allow feasible placement with ``U_link, U_node <= 1``.
    - ``lambda_m0=1`` vs ``0`` exposes link vs node load trade-off.
    """
    data = M0Data()
    data.routing_mode = "per_task_od"
    data.I = [0, 1]
    data.M = list(M0_COMPUTE)

    data.task_src = {0: M0_SRC0, 1: M0_SRC1}
    data.task_dst = {0: M0_DST0, 1: M0_DST1}

    data.b_in = {0: 10.0, 1: 10.0}
    data.b_out = {0: 10.0, 1: 10.0}
    data.w = {
        0: {K_CPU: 8.0, K_GPU: 1.0, K_HBM: 1.0},
        1: {K_CPU: 1.0, K_GPU: 8.0, K_HBM: 1.0},
    }

    # Heterogeneous compute: split tasks -> low U_node; colocate -> high U_node.
    data.C_normal = {
        4: {K_CPU: 10.0, K_GPU: 10.0, K_HBM: 10.0},
        5: {K_CPU: 10.0, K_GPU: 10.0, K_HBM: 10.0},
        6: {K_CPU: 10.0, K_GPU: 10.0, K_HBM: 10.0},
    }

    relay = M0_RELAY
    for m in data.M:
        for i in data.I:
            src = data.task_src[i]
            dst = data.task_dst[i]
            _add_paths(data, src, m, relay)
            _add_paths(data, m, dst, relay)

    _collect_edges(data)
    _default_bandwidth(data)

    data.valid_assign = {(i, m) for i in data.I for m in data.M}
    return data
