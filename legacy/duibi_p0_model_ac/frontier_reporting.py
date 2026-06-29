# -*- coding: utf-8 -*-
"""Frontier row enrichment: Model C objective semantics & cost breakdown (no MILP changes)."""
from __future__ import annotations

MODEL_C_OBJECTIVE_FORMULA = "monetary_cost - omega_deliver * expected_delivery"


def monetary_cost_breakdown(data, y, xin, xout) -> tuple[float, float]:
    from duibi_metrics import bandwidth_cost_expr, path_bandwidth_tariff, teavar_flow_anchors

    cost_p = sum(
        y[i, node].X * sum(data.w[i][k] * data.p_price[node][k] for k in data.K)
        for i, node in y
    )
    per_task = getattr(data, "routing_mode", "hub") in (
        "per_task_od",
        "umcf_per_task",
        "umcf_per_task_od",
    )
    if per_task:
        cost_b = 0.0
        for i in data.I:
            iu, ov = teavar_flow_anchors(data, i)
            for node in data.M:
                if (i, node) not in y:
                    continue
                for p in range(len(data.P_cand[iu, node])):
                    key = (i, node, p)
                    if key in xin:
                        cost_b += xin[key].X * float(path_bandwidth_tariff(data, iu, node, p))
                for q in range(len(data.P_cand[node, ov])):
                    key = (i, node, q)
                    if key in xout:
                        cost_b += xout[key].X * float(path_bandwidth_tariff(data, node, ov, q))
    else:
        src, dst = teavar_flow_anchors(data)
        cb = bandwidth_cost_expr(data, xin, xout, src, dst)
        cost_b = float(cb.getValue()) if hasattr(cb, "getValue") else float(cb)
    return float(cost_p), float(cost_b)


def var_value(m, name: str) -> float | None:
    try:
        v = m.getVarByName(name)
        return float(v.X) if v is not None else None
    except Exception:  # noqa: BLE001
        return None


def enrich_model_c_row(
    row: dict,
    *,
    data,
    m,
    y,
    xin,
    xout,
    din,
    dout,
    cost: float | None,
    lvc,
    svc,
    omega_deliver: float,
) -> dict:
    """Add objective decomposition and model/posthoc fields to a grid row."""
    out = dict(row)
    out["objective_formula"] = MODEL_C_OBJECTIVE_FORMULA
    out["omega_deliver"] = omega_deliver
    out["obj_val"] = out.get("objective")
    out["model_cvar_sla"] = lvc
    out["model_cvar_sf"] = svc
    out["zeta_sla"] = var_value(m, "zeta_sla")
    out["zeta_sf"] = var_value(m, "zeta_sf")
    if m is not None and getattr(m, "SolCount", 0) > 0:
        cost_p, cost_b = monetary_cost_breakdown(data, y, xin, xout)
        monetary = cost_p + cost_b
        exp_del = out.get("exp_deliver")
        out["compute_cost"] = cost_p
        out["bandwidth_cost"] = cost_b
        out["monetary_cost"] = monetary
        out["cost"] = monetary
        if exp_del is not None:
            out["obj_reconstruction_error"] = abs(
                float(out["obj_val"]) - (monetary - omega_deliver * float(exp_del))
            )
        try:
            from metrics_posthoc import compute_posthoc_cvar_metrics

            ph = compute_posthoc_cvar_metrics(
                data,
                y,
                din,
                dout,
                model_cvar_sla=lvc,
                model_cvar_sf=svc,
            )
            out.update(ph)
            out["posthoc_cvar_sla"] = ph.get("posthoc_cvar_sla")
            out["posthoc_cvar_sf"] = ph.get("posthoc_cvar_sf")
        except Exception as exc:  # noqa: BLE001
            out["posthoc_warning"] = f"posthoc_failed:{type(exc).__name__}:{exc}"
    elif cost is not None:
        out["monetary_cost"] = cost
        out["cost"] = cost
    return out
