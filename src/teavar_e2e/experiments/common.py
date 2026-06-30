# -*- coding: utf-8 -*-
"""Shared helpers for E2E mainline runners — no model logic, just data load + solve wrappers."""
from __future__ import annotations

import csv
import os
import time
from datetime import datetime
from typing import Any


def parse_gamma_list(raw: str) -> list[float]:
    """Parse comma/space-separated gamma string into sorted float list."""
    raw = raw.replace(",", " ")
    vals = [float(x.strip()) for x in raw.split() if x.strip()]
    return sorted(vals)


def build_toy2task_data(
    max_failed_components: int = 2,
    renormalize_probabilities: bool = True,
) -> Any:
    """Build Toy-2Task-Independent data with pruned scenario mode."""
    from teavar_e2e.data.toy_two_task_independent_data import (
        build_toy_2task_independent_v1,
    )
    return build_toy_2task_independent_v1(
        scenario_mode="pruned",
        max_failed_components=max_failed_components,
        renormalize_probabilities=renormalize_probabilities,
    )


def solve_m2_c_cost_once(
    data: Any,
    gamma: float,
    *,
    beta_cvar: float = 0.95,
    rho_min_service: float | None = None,
    time_limit: float | None = None,
    mip_gap: float | None = None,
    quiet: bool = True,
) -> tuple[Any, dict]:
    """
    Build and solve one M2-C-Cost configuration.

    Returns (result, metrics_dict).  On infeasible / Gurobi unavailable the
    metrics dict carries ``status`` and ``NA`` values — never raises.
    """
    _ = beta_cvar  # passed via data.beta_cvar before build

    t0 = time.perf_counter()
    try:
        import gurobipy as gp  # noqa: F401
    except ImportError:
        return None, _empty_metrics(
            gamma=gamma, status="NO_GUROBI", runtime=time.perf_counter() - t0
        )

    from teavar_e2e.models.m2_cost_models import build_m2_c_cost_model, solve_m2_c_cost

    data.beta_cvar = float(beta_cvar)  # set CVaR confidence on data

    try:
        model = build_m2_c_cost_model(
            data,
            gamma=float(gamma),
            rho_min_service=rho_min_service,
            quiet=quiet,
            time_limit=time_limit,
            mip_gap=mip_gap,
        )
    except Exception as exc:
        return None, _empty_metrics(
            gamma=gamma,
            status=f"BUILD_ERROR_{exc}",
            runtime=time.perf_counter() - t0,
        )

    var_count = len(model.getVars())
    constr_count = len(model.getConstrs())

    try:
        result = solve_m2_c_cost(model)
    except Exception as exc:
        model.dispose()
        return None, _empty_metrics(
            gamma=gamma,
            status=f"SOLVE_ERROR_{exc}",
            var_count=var_count,
            constr_count=constr_count,
            runtime=time.perf_counter() - t0,
        )

    runtime = time.perf_counter() - t0
    status_str = _gurobi_status_label(int(result.status))

    # Compute min_task_service
    min_z = float("nan")
    if result.z:
        z_by_task = _task_z_aggregates(result.z, data.J)
        if z_by_task:
            min_z = min(z_by_task.values())

    metrics = {
        "gamma": gamma,
        "status": status_str,
        "objective": _safe_float(result.objective),
        "total_cost": _safe_float(result.cost_placement) + _safe_float(result.cost_bandwidth_expected),
        "placement_cost": _safe_float(result.cost_placement),
        "bandwidth_cost": _safe_float(result.cost_bandwidth_expected),
        "cvar_e2e": _safe_float(result.cvar_value),
        "eta": _safe_float(result.eta),
        "expected_service": _safe_float(result.expected_service),
        "min_task_service": min_z,
        "var_count": var_count,
        "constr_count": constr_count,
        "runtime_sec": round(runtime, 3),
    }
    model.dispose()
    return result, metrics


def _gurobi_status_label(code: int) -> str:
    mapping = {2: "OPTIMAL", 3: "INFEASIBLE", 4: "INF_OR_UNBD", 5: "UNBOUNDED", 9: "TIME_LIMIT", 11: "SUBOPTIMAL"}
    return mapping.get(code, str(code))


def _task_z_aggregates(z_vals: dict, task_ids: list[int]) -> dict[int, float]:
    """Per-task expected service from z[i,s] dict and scenario probabilities."""
    out: dict[int, float] = {}
    for (i, s), val in z_vals.items():
        out[i] = out.get(i, 0.0) + val
    return out


def _safe_float(x: float | None) -> str:
    if x is None or (isinstance(x, float) and (x != x)):  # x != x detects NaN
        return "NA"
    return f"{float(x):.6g}"


def _empty_metrics(
    gamma: float,
    status: str = "INFEASIBLE",
    var_count: int = 0,
    constr_count: int = 0,
    runtime: float = 0.0,
) -> dict:
    return {
        "gamma": gamma,
        "status": status,
        "objective": "NA",
        "total_cost": "NA",
        "placement_cost": "NA",
        "bandwidth_cost": "NA",
        "cvar_e2e": "NA",
        "eta": "NA",
        "expected_service": "NA",
        "min_task_service": "NA",
        "var_count": var_count,
        "constr_count": constr_count,
        "runtime_sec": round(runtime, 3),
    }


CSV_FIELDS = [
    "dataset",
    "beta",
    "gamma",
    "rho",
    "loss_mode",
    "max_failed_components",
    "aggregate_worst_case",
    "num_scenarios",
    "dropped_probability_mass",
    "status",
    "objective",
    "total_cost",
    "placement_cost",
    "bandwidth_cost",
    "cvar_e2e",
    "eta",
    "expected_service",
    "min_task_service",
    "var_count",
    "constr_count",
    "runtime_sec",
]


def write_csv_row(path: str, row: dict, *, mode: str = "a") -> None:
    """Append (or write) a single dict row to CSV.  Creates header on first write."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_header = not os.path.exists(path) or mode == "w"
    with open(path, mode, newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow(row)


def output_path(basename: str, output_dir: str = "new_results/e2e_mainline") -> str:
    """Timestamped output path under *output_dir*."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(output_dir, f"{basename}_{ts}.csv")
