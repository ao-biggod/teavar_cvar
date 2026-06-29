# -*- coding: utf-8 -*-
"""Post-hoc CVaR metrics for solved TEAVAR models (reporting only; no MILP changes)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class DiscreteCvarResult:
    var: float
    cvar: float
    mean_loss: float
    tail_mass: float
    worst_scenarios: list[Any]


def resolve_cvar_metric_columns(
    fieldnames: list[str],
    metric_source: str = "auto",
) -> dict:
    """Resolve which CSV columns to use for acceptance / plotting."""
    lower = {f.lower(): f for f in fieldnames}
    info: dict = {"metric_source": metric_source, "warning": ""}

    def _pick(*names: str) -> str | None:
        for n in names:
            if n in fieldnames:
                return n
            if n.lower() in lower:
                return lower[n.lower()]
        return None

    if metric_source in ("auto", "posthoc"):
        sla = _pick("posthoc_cvar_sla", "reported_cvar_sla")
        sf = _pick("posthoc_cvar_sf", "reported_cvar_sf")
        if sla and sf:
            info.update({"sla_column": sla, "sf_column": sf, "metric_source": "posthoc"})
            return info
    if metric_source in ("auto", "legacy", "model"):
        sla = _pick("cvar_sla", "model_cvar_sla")
        sf = _pick("cvar_sf", "model_cvar_sf")
        if sla and sf:
            info.update(
                {
                    "sla_column": sla,
                    "sf_column": sf,
                    "metric_source": "legacy" if metric_source == "auto" else metric_source,
                }
            )
            if metric_source == "auto":
                info["warning"] = (
                    "WARNING: posthoc_cvar_sla/posthoc_cvar_sf not found; "
                    "falling back to legacy cvar_sla/cvar_sf (model auxiliary values)."
                )
            return info
    raise KeyError("Could not resolve CVaR metric columns")


def compute_discrete_cvar(
    loss_by_scenario: Mapping[Any, float],
    prob_by_scenario: Mapping[Any, float],
    beta: float,
    *,
    prob_tol: float = 1e-6,
) -> DiscreteCvarResult:
    if not loss_by_scenario:
        return DiscreteCvarResult(0.0, 0.0, 0.0, max(0.0, 1.0 - beta), [])
    if not (0.0 < beta < 1.0):
        raise ValueError(f"beta must be in (0, 1), got {beta}")

    scenarios = list(loss_by_scenario.keys())
    probs = {s: float(prob_by_scenario.get(s, 0.0)) for s in scenarios}
    total = sum(probs.values())
    if total <= 0.0:
        raise ValueError("probabilities must sum to a positive value")
    if abs(total - 1.0) > prob_tol:
        probs = {s: p / total for s, p in probs.items()}

    losses = {s: max(0.0, float(loss_by_scenario[s])) for s in scenarios}
    mean_loss = sum(probs[s] * losses[s] for s in scenarios)
    tail_mass = 1.0 - beta
    if tail_mass <= 0.0:
        mx = max(losses.values())
        return DiscreteCvarResult(mx, mx, mean_loss, 0.0, list(scenarios))

    zeta_candidates = {0.0, *losses.values()}
    inv = 1.0 / tail_mass
    best_zeta = 0.0
    best_cvar = float("inf")
    for zeta in zeta_candidates:
        cvar = zeta + inv * sum(probs[s] * max(0.0, losses[s] - zeta) for s in scenarios)
        if cvar < best_cvar - 1e-15 or (abs(cvar - best_cvar) <= 1e-15 and zeta < best_zeta):
            best_cvar = cvar
            best_zeta = zeta

    sorted_asc = sorted(scenarios, key=lambda s: (losses[s], str(s)))
    cum = 0.0
    var = losses[sorted_asc[-1]]
    for s in sorted_asc:
        cum += probs[s]
        if cum >= beta - 1e-15:
            var = losses[s]
            break

    tail = [s for s in scenarios if losses[s] >= var - 1e-15]
    return DiscreteCvarResult(var, best_cvar, mean_loss, tail_mass, tail)


def _placement_from_y(data, y) -> dict[int, int]:
    out: dict[int, int] = {}
    for i in data.I:
        for node in data.M:
            if (i, node) in y and float(y[i, node].X) > 0.5:
                out[i] = node
                break
    return out


def compute_d_ref(data) -> float:
    if not data.I or not data.K:
        return 1.0
    d_max_any = 0.0
    for node in data.M:
        for k in data.K:
            dmax = float(sum(data.w[i][k] for i in data.I))
            d_max_any = max(d_max_any, dmax)
    if not data.M or not data.S:
        return max(d_max_any + 1.0, 1.0)
    cmax = max(
        float(data.C_s[node][k][s])
        for node in data.M
        for k in data.K
        for s in data.S
    )
    return max(d_max_any + 1.0, cmax + 1.0, 1.0)


def compute_sla_loss_by_scenario(data, del_in, del_out) -> dict[int, float]:
    from duibi_metrics import teavar_flow_anchors

    per_task = getattr(data, "routing_mode", "hub") in (
        "per_task_od",
        "umcf_per_task",
        "umcf_per_task_od",
    )
    out: dict[int, float] = {}
    for s in data.S:
        worst = 0.0
        for i in data.I:
            if per_task:
                iu, ov = teavar_flow_anchors(data, i)
            else:
                iu, ov = teavar_flow_anchors(data)
            rin = sum(
                del_in[i, node, p, s].X
                for node in data.M
                for p in range(len(data.P_cand[iu, node]))
                if (i, node, p, s) in del_in
            )
            rout = sum(
                del_out[i, node, q, s].X
                for node in data.M
                for q in range(len(data.P_cand[node, ov]))
                if (i, node, q, s) in del_out
            )
            li = 0.0
            if data.b_in[i] > 0:
                li = max(li, 1.0 - rin / data.b_in[i])
            if data.b_out[i] > 0:
                li = max(li, 1.0 - rout / data.b_out[i])
            worst = max(worst, li)
        out[s] = max(0.0, worst)
    return out


def compute_sf_loss_by_scenario(
    data,
    y,
    *,
    placement: dict[int, int] | None = None,
    sf_d_ref_by_resource: dict[int, float] | None = None,
) -> dict[int, float]:
    if sf_d_ref_by_resource is None:
        from cvar_compare import compute_sf_resource_refs

        sf_d_ref_by_resource = compute_sf_resource_refs(data)
    if placement is None:
        placement = _placement_from_y(data, y)

    d_mk: dict[tuple[int, int], float] = {}
    for node in data.M:
        for k in data.K:
            d_mk[node, k] = sum(
                float(data.w[i][k]) for i in data.I if placement.get(i) == node
            )

    out: dict[int, float] = {}
    for s in data.S:
        worst = 0.0
        for node in data.M:
            for k in data.K:
                cap = float(data.C_s[node][k][s])
                d_ref_k = float(sf_d_ref_by_resource[k])
                raw = (d_mk[node, k] - cap) / d_ref_k
                worst = max(worst, raw)
        out[s] = max(0.0, worst)
    return out


def compute_posthoc_cvar_metrics(
    data,
    y,
    del_in,
    del_out,
    *,
    model_cvar_sla=None,
    model_cvar_sf=None,
) -> dict:
    beta = float(getattr(data, "beta_N", 0.95))
    prob = {s: float(data.prob[s]) for s in data.S}
    loss_sla = compute_sla_loss_by_scenario(data, del_in, del_out)
    loss_sf = compute_sf_loss_by_scenario(data, y)
    sla = compute_discrete_cvar(loss_sla, prob, beta)
    sf = compute_discrete_cvar(loss_sf, prob, beta)
    return {
        "model_cvar_sla": model_cvar_sla,
        "model_cvar_sf": model_cvar_sf,
        "posthoc_cvar_sla": sla.cvar,
        "posthoc_cvar_sf": sf.cvar,
        "posthoc_mean_sla_loss": sla.mean_loss,
        "posthoc_mean_sf_loss": sf.mean_loss,
        "posthoc_var_sla": sla.var,
        "posthoc_var_sf": sf.var,
        "cvar_sla": model_cvar_sla,
        "cvar_sf": model_cvar_sf,
    }
