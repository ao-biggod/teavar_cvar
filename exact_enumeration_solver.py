# -*- coding: utf-8 -*-
"""
Exact enumeration benchmark for TEAVAR Model A / Model C (independent of Gurobi).

Does NOT call build_teavar_model_a/c or Gurobi for the benchmark itself.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any, Iterator

from duibi_metrics import (
    path_up,
    placement_bandwidth_cost_value,
    teavar_flow_anchors,
)


@dataclass
class RouteChoice:
    """Per-task ingress/egress path indices on the placed compute node."""

    in_path: dict[int, int] = field(default_factory=dict)
    out_path: dict[int, int] = field(default_factory=dict)


@dataclass
class EvaluatedSolution:
    placement: dict[int, int]
    routes: RouteChoice
    cost: float
    scenario_sla_loss: dict[int, float]
    scenario_sf_loss: dict[int, float]
    cvar_sla: float
    cvar_sf: float
    expected_delivery: float
    model_a_objective: float
    model_c_feasible: bool
    model_c_objective: float | None


@dataclass
class ExactSolveResult:
    status: str
    best: EvaluatedSolution | None
    feasible_count: int
    evaluated_count: int
    all_feasible: list[EvaluatedSolution] = field(default_factory=list)


def compute_cvar(
    losses: dict[int, float],
    probs: dict[int, float],
    beta: float,
) -> float:
    """
    Rockafellar-Uryasev discrete CVaR:
      min_z z + 1/(1-beta) * sum_s p_s * max(loss_s - z, 0)
    """
    if not losses:
        return 0.0
    if not (0.0 < beta < 1.0):
        raise ValueError(f"beta must be in (0, 1), got {beta}")

    scenarios = list(losses.keys())
    total_p = sum(float(probs.get(s, 0.0)) for s in scenarios)
    if total_p <= 0.0:
        raise ValueError("probabilities must sum to a positive value")
    p = {s: float(probs.get(s, 0.0)) / total_p for s in scenarios}

    vals = {s: max(0.0, float(losses[s])) for s in scenarios}
    zeta_candidates = {0.0, *vals.values()}
    inv = 1.0 / (1.0 - beta)
    best = float("inf")
    for zeta in zeta_candidates:
        cvar = zeta + inv * sum(p[s] * max(0.0, vals[s] - zeta) for s in scenarios)
        if cvar < best - 1e-15:
            best = cvar
    return best


def _sf_d_ref_by_resource(data) -> dict[int, float]:
    """Independent per-resource D_ref[k] = max(sum_i w[i,k], 1.0) — not from Gurobi."""
    refs: dict[int, float] = {}
    for k in data.K:
        total = sum(float(data.w[i][k]) for i in data.I)
        refs[k] = max(total, 1.0)
    return refs


def _placement_capacity_ok(data, placement: dict[int, int]) -> bool:
    for node in data.M:
        for k in data.K:
            load = sum(
                float(data.w[i][k])
                for i in data.I
                if placement.get(i) == node
            )
            cap = float(data.C_normal.get(node, {}).get(k, 0.0))
            if load > cap + 1e-9:
                return False
    return True


def enumerate_placements(data) -> Iterator[dict[int, int]]:
    """Enumerate Cartesian product of valid compute nodes per task."""
    choices_per_task: list[list[tuple[int, int]]] = []
    for i in data.I:
        opts = [m for m in data.M if (i, m) in data.valid_assign]
        if not opts:
            return
        choices_per_task.append([(i, m) for m in opts])

    for combo in itertools.product(*choices_per_task):
        placement = {i: m for i, m in combo}
        if _placement_capacity_ok(data, placement):
            yield placement


def enumerate_routes(data, placement: dict[int, int]) -> Iterator[RouteChoice]:
    """Enumerate ingress/egress path choices (toy instances: one path each)."""
    in_ranges: list[list[int]] = []
    out_ranges: list[list[int]] = []
    for i in data.I:
        m = placement[i]
        iu, ov = teavar_flow_anchors(data, i)
        in_ranges.append(list(range(len(data.P_cand[iu, m]))))
        out_ranges.append(list(range(len(data.P_cand[m, ov]))))
        if not in_ranges[-1] or not out_ranges[-1]:
            return

    for in_combo in itertools.product(*in_ranges):
        for out_combo in itertools.product(*out_ranges):
            rc = RouteChoice(
                in_path={data.I[j]: in_combo[j] for j in range(len(data.I))},
                out_path={data.I[j]: out_combo[j] for j in range(len(data.I))},
            )
            yield rc


def _flow_values(data, placement: dict[int, int]) -> tuple[dict[int, float], dict[int, float]]:
    """Full-demand flow on placed node (zero bandwidth cost in toys)."""
    xin = {}
    xout = {}
    for i in data.I:
        m = placement[i]
        xin[i] = float(data.b_in[i])
        xout[i] = float(data.b_out[i])
    return xin, xout


def _scenario_delivery(
    data,
    placement: dict[int, int],
    routes: RouteChoice,
    s: int,
) -> tuple[dict[int, float], dict[int, float]]:
    rin: dict[int, float] = {}
    rout: dict[int, float] = {}
    for i in data.I:
        m = placement[i]
        iu, ov = teavar_flow_anchors(data, i)
        p_idx = routes.in_path[i]
        q_idx = routes.out_path[i]
        x_in = float(data.b_in[i])
        x_out = float(data.b_out[i])
        if path_up(data, iu, m, p_idx, s):
            rin[i] = x_in
        else:
            rin[i] = 0.0
        if path_up(data, m, ov, q_idx, s):
            rout[i] = x_out
        else:
            rout[i] = 0.0
    return rin, rout


def _sla_loss_per_scenario(data, rin: dict[int, float], rout: dict[int, float]) -> float:
    worst = 0.0
    for i in data.I:
        li = 0.0
        if data.b_in[i] > 0:
            li = max(li, 1.0 - rin[i] / float(data.b_in[i]))
        if data.b_out[i] > 0:
            li = max(li, 1.0 - rout[i] / float(data.b_out[i]))
        worst = max(worst, li)
    return max(0.0, worst)


def _sf_loss_per_scenario(data, placement: dict[int, int], s: int, d_ref_by_k: dict[int, float]) -> float:
    worst = 0.0
    for node in data.M:
        if node not in getattr(data, "C_s", {}) or not data.C_s[node]:
            continue
        for k in data.K:
            if k not in data.C_s[node]:
                continue
            load = sum(
                float(data.w[i][k])
                for i in data.I
                if placement.get(i) == node
            )
            cap = float(data.C_s[node][k][s])
            d_ref_k = float(d_ref_by_k[k])
            raw = max(0.0, load - cap) / d_ref_k
            worst = max(worst, raw)
    return max(0.0, worst)


def _compute_cost(data, placement: dict[int, int]) -> float:
    total = 0.0
    for i in data.I:
        m = placement[i]
        for k in data.K:
            total += float(data.w[i][k]) * float(data.p_price[m][k])
    total += placement_bandwidth_cost_value(data, placement)
    return total


def evaluate_solution(
    data,
    placement: dict[int, int],
    routes: RouteChoice,
    *,
    lambda_sla: float = 0.0,
    lambda_sf: float = 0.0,
    omega_deliver: float = 0.0,
    beta_sla: float | None = None,
    beta_sf: float | None = None,
    gamma_sla: float | None = None,
    gamma_sf: float | None = None,
) -> EvaluatedSolution:
    b_sla = float(beta_sla if beta_sla is not None else data.beta_N)
    b_sf = float(beta_sf if beta_sf is not None else data.beta_N)
    d_ref_by_k = _sf_d_ref_by_resource(data)

    sla: dict[int, float] = {}
    sf: dict[int, float] = {}
    exp_del = 0.0
    for s in data.S:
        rin, rout = _scenario_delivery(data, placement, routes, s)
        sla[s] = _sla_loss_per_scenario(data, rin, rout)
        sf[s] = _sf_loss_per_scenario(data, placement, s, d_ref_by_k)
        exp_del += float(data.prob[s]) * sum(rin[i] + rout[i] for i in data.I)

    cvar_sla = compute_cvar(sla, data.prob, b_sla)
    cvar_sf = compute_cvar(sf, data.prob, b_sf)

    cost = _compute_cost(data, placement)
    obj_a = cost + lambda_sla * cvar_sla + lambda_sf * cvar_sf - omega_deliver * exp_del

    feasible_c = True
    if gamma_sla is not None and cvar_sla > float(gamma_sla) + 1e-9:
        feasible_c = False
    if gamma_sf is not None and cvar_sf > float(gamma_sf) + 1e-9:
        feasible_c = False

    obj_c = (cost - omega_deliver * exp_del) if feasible_c else None

    return EvaluatedSolution(
        placement=dict(placement),
        routes=routes,
        cost=cost,
        scenario_sla_loss=sla,
        scenario_sf_loss=sf,
        cvar_sla=cvar_sla,
        cvar_sf=cvar_sf,
        expected_delivery=exp_del,
        model_a_objective=obj_a,
        model_c_feasible=feasible_c,
        model_c_objective=obj_c,
    )


def _enumerate_all(data) -> list[EvaluatedSolution]:
    out: list[EvaluatedSolution] = []
    for placement in enumerate_placements(data):
        for routes in enumerate_routes(data, placement):
            out.append(evaluate_solution(data, placement, routes))
    return out


def solve_exact_model_a(
    data,
    lambda_sla: float,
    lambda_sf: float,
    beta_sla: float | None = None,
    beta_sf: float | None = None,
    omega_deliver: float = 0.0,
) -> ExactSolveResult:
    best: EvaluatedSolution | None = None
    evaluated = 0
    for placement in enumerate_placements(data):
        for routes in enumerate_routes(data, placement):
            ev = evaluate_solution(
                data,
                placement,
                routes,
                lambda_sla=lambda_sla,
                lambda_sf=lambda_sf,
                omega_deliver=omega_deliver,
                beta_sla=beta_sla,
                beta_sf=beta_sf,
            )
            evaluated += 1
            if best is None or ev.model_a_objective < best.model_a_objective - 1e-12 or (
                abs(ev.model_a_objective - best.model_a_objective) <= 1e-12 and ev.cost < best.cost - 1e-12
            ):
                best = ev
    return ExactSolveResult(
        status="optimal" if best is not None else "empty",
        best=best,
        feasible_count=evaluated,
        evaluated_count=evaluated,
    )


def solve_exact_model_c(
    data,
    gamma_sla: float,
    gamma_sf: float | None,
    beta_sla: float | None = None,
    beta_sf: float | None = None,
    omega_deliver: float = 0.0,
) -> ExactSolveResult:
    best: EvaluatedSolution | None = None
    feasible: list[EvaluatedSolution] = []
    evaluated = 0
    for placement in enumerate_placements(data):
        for routes in enumerate_routes(data, placement):
            ev = evaluate_solution(
                data,
                placement,
                routes,
                omega_deliver=omega_deliver,
                beta_sla=beta_sla,
                beta_sf=beta_sf,
                gamma_sla=gamma_sla,
                gamma_sf=gamma_sf,
            )
            evaluated += 1
            if ev.model_c_feasible:
                feasible.append(ev)
                obj = ev.model_c_objective
                assert obj is not None
                if best is None or obj < best.model_c_objective - 1e-12 or (
                    abs(obj - best.model_c_objective) <= 1e-12 and ev.cost < best.cost - 1e-12
                ):
                    best = ev
    return ExactSolveResult(
        status="optimal" if best is not None else "infeasible",
        best=best,
        feasible_count=len(feasible),
        evaluated_count=evaluated,
        all_feasible=feasible,
    )


def count_feasible_solutions(data) -> int:
    n = 0
    for _placement in enumerate_placements(data):
        for _routes in enumerate_routes(data, _placement):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Gurobi result extraction (read-only; for test comparison only)
# ---------------------------------------------------------------------------

@dataclass
class GurobiModelResult:
    status: int
    status_name: str
    objective: float | None
    cost: float | None
    cvar_sla: float | None
    cvar_sf: float | None
    placement: dict[int, int]
    expected_delivery: float | None
    cvar_sla_active: bool = True
    cvar_sf_active: bool = True


def extract_model_a_result(
    m,
    cost,
    cvar_sla,
    cvar_sf,
    y,
    xin,
    xout,
    del_in,
    del_out,
    data,
    *,
    lambda_sla: float = 0.0,
    lambda_sf: float = 0.0,
) -> GurobiModelResult:
    from gurobipy import GRB

    from metrics_posthoc import (
        compute_discrete_cvar,
        compute_sla_loss_by_scenario,
        compute_sf_loss_by_scenario,
    )

    status = int(m.status)
    if status != GRB.OPTIMAL or cost is None:
        return GurobiModelResult(status, m.Status, None, None, None, None, {}, None)

    placement = {i: node for i in data.I for node in data.M if (i, node) in y and y[i, node].X > 0.5}
    beta = float(data.beta_N)
    loss_sla = compute_sla_loss_by_scenario(data, del_in, del_out)
    loss_sf = compute_sf_loss_by_scenario(data, y)
    posthoc_sla = compute_discrete_cvar(loss_sla, data.prob, beta).cvar
    posthoc_sf = compute_discrete_cvar(loss_sf, data.prob, beta).cvar

    exp_del = 0.0
    for s in data.S:
        for i in data.I:
            iu, ov = teavar_flow_anchors(data, i)
            for node in data.M:
                for p in range(len(data.P_cand[iu, node])):
                    if (i, node, p, s) in del_in:
                        exp_del += float(data.prob[s]) * del_in[i, node, p, s].X
                for q in range(len(data.P_cand[node, ov])):
                    if (i, node, q, s) in del_out:
                        exp_del += float(data.prob[s]) * del_out[i, node, q, s].X

    return GurobiModelResult(
        status=status,
        status_name=str(m.Status),
        objective=float(m.ObjVal),
        cost=float(cost),
        cvar_sla=posthoc_sla if lambda_sla > 1e-12 else None,
        cvar_sf=posthoc_sf if lambda_sf > 1e-12 else None,
        placement=placement,
        expected_delivery=exp_del,
        cvar_sla_active=lambda_sla > 1e-12,
        cvar_sf_active=lambda_sf > 1e-12,
    )


def extract_model_c_result(
    m,
    cost,
    cvar_sla,
    cvar_sf,
    y,
    xin,
    xout,
    del_in,
    del_out,
    data,
    *,
    gamma_sf: float | None = None,
) -> GurobiModelResult:
    include_sf = gamma_sf is not None
    result = extract_model_a_result(
        m, cost, cvar_sla, cvar_sf, y, xin, xout, del_in, del_out, data,
        lambda_sla=1.0,
        lambda_sf=1.0 if include_sf else 0.0,
    )
    return GurobiModelResult(
        status=result.status,
        status_name=result.status_name,
        objective=result.objective,
        cost=result.cost,
        cvar_sla=result.cvar_sla,
        cvar_sf=result.cvar_sf if include_sf else None,
        placement=result.placement,
        expected_delivery=result.expected_delivery,
        cvar_sla_active=True,
        cvar_sf_active=include_sf,
    )


def placements_match(
    a: dict[int, int],
    b: dict[int, int],
    *,
    data=None,
) -> bool:
    if a == b:
        return True
    # Symmetric two-task toys: AB and BA are equally optimal (same w, same B pricing).
    if data is not None and len(getattr(data, "I", [])) == 2:
        if len(a) == 2 and len(b) == 2 and a[0] != a[1] and b[0] != b[1]:
            return set(a.values()) == set(b.values())
    return False


def assert_close(a: float | None, b: float | None, tol: float = 1e-5, label: str = "") -> None:
    if a is None or b is None:
        raise AssertionError(f"{label}: expected numeric values, got {a!r} vs {b!r}")
    if not math.isclose(a, b, rel_tol=0.0, abs_tol=tol):
        raise AssertionError(f"{label}: {a} != {b} (tol={tol})")
