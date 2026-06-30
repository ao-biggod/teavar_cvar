# -*- coding: utf-8 -*-
"""
Component-level failure enumeration for toy / validation instances.

Each binary component fails independently with probability ``p_fail``.
All 2^n failure masks become scenarios; ``P(s)`` is the product of
component survival / failure probabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class FailureComponent:
    kind: str  # 'link' | 'compute_derate'
    name: str
    p_fail: float


def iter_component_failure_states(
    components: list[FailureComponent],
) -> Iterator[tuple[int, dict[str, bool], float]]:
    """Yield (scenario_id, failed_by_name, probability) for all 2^n masks."""
    n = len(components)
    for mask in range(1 << n):
        failed: dict[str, bool] = {}
        prob = 1.0
        for i, comp in enumerate(components):
            is_failed = bool(mask & (1 << i))
            failed[comp.name] = is_failed
            prob *= comp.p_fail if is_failed else (1.0 - comp.p_fail)
        yield mask, failed, prob


def build_sigma_and_capacity_from_components(
    *,
    edges: list[tuple[int, int]],
    compute_nodes: dict[str, int],
    ingress_edges: dict[str, list[tuple[int, int]]],
    egress_edges: dict[str, list[tuple[int, int]]],
    components: list[FailureComponent],
    c_normal: dict[int, dict[int, float]],
    derate_resource: int,
    derate_capacity: float = 0.0,
) -> tuple[list[int], dict[int, float], dict, dict]:
    """
    Map component failure masks to ``sigma[e][s]`` and ``C_s[node][k][s]``.

    Link components ``{X}_in`` / ``{X}_out`` gate ingress/egress edge groups.
    ``compute_derate`` on node X zeroes ``derate_resource`` capacity when failed.
    """
    scenarios: list[int] = []
    prob: dict[int, float] = {}
    sigma: dict[tuple[int, int], dict[int, float]] = {e: {} for e in edges}
    c_s: dict[int, dict[int, dict[int, float]]] = {
        node: {k: {} for k in next(iter(c_normal.values()))} for node in c_normal
    }

    for sid, failed, p in iter_component_failure_states(components):
        scenarios.append(sid)
        prob[sid] = p
        for e in edges:
            sigma[e][sid] = 1.0
        for label, node in compute_nodes.items():
            for k, cap in c_normal[node].items():
                c_s[node][k][sid] = float(cap)
            derate_key = label
            if failed.get(derate_key, False):
                c_s[node][derate_resource][sid] = float(derate_capacity)

        for label in compute_nodes:
            in_key = f"{label}_in"
            out_key = f"{label}_out"
            if failed.get(in_key, False):
                for e in ingress_edges[label]:
                    sigma[e][sid] = 0.0
            if failed.get(out_key, False):
                for e in egress_edges[label]:
                    sigma[e][sid] = 0.0

    return scenarios, prob, sigma, c_s


def attach_component_scenarios(
    data: Any,
    *,
    components: list[FailureComponent],
    compute_nodes: dict[str, int],
    ingress_edges: dict[str, list[tuple[int, int]]],
    egress_edges: dict[str, list[tuple[int, int]]],
    derate_resource: int,
    derate_capacity: float = 0.0,
) -> None:
    """Write ``data.S``, ``data.prob``, ``data.sigma``, ``data.C_s`` from components."""
    scenarios, prob, sigma, c_s = build_sigma_and_capacity_from_components(
        edges=list(data.E),
        compute_nodes=compute_nodes,
        ingress_edges=ingress_edges,
        egress_edges=egress_edges,
        components=components,
        c_normal=data.C_normal,
        derate_resource=derate_resource,
        derate_capacity=derate_capacity,
    )
    data.S = scenarios
    data.prob = prob
    data.sigma = sigma
    data.C_s = c_s
    data.component_spec = list(components)
