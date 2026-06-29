# -*- coding: utf-8 -*-
"""Resolved config snapshot for frontier runs (reporting / parity diagnosis)."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _git_snapshot() -> dict[str, str]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        return {
            "commit": commit,
            "dirty": bool(dirty),
            "dirty_summary": dirty[:4000] if dirty else "",
        }
    except Exception:  # noqa: BLE001
        return {"commit": "UNKNOWN", "dirty": False, "dirty_summary": "UNKNOWN"}


def _link_price_summary(data) -> dict[str, Any]:
    from duibi_metrics import ensure_link_prices

    ensure_link_prices(data)
    prices = [float(v) for v in data.link_price.values()] if data.link_price else []
    mode = str(getattr(data, "bandwidth_price_mode", ""))
    if not prices:
        return {"mode": mode, "min": None, "max": None, "mean": None, "is_uniform": None}
    mn, mx = min(prices), max(prices)
    mean = sum(prices) / len(prices)
    is_uniform = abs(mx - mn) < 1e-12
    return {
        "mode": mode,
        "scale": float(getattr(data, "bandwidth_price_scale", 1.0)),
        "min": mn,
        "max": mx,
        "mean": mean,
        "is_uniform": is_uniform,
        "edge_count": len(prices),
    }


def _scenario_summary(data) -> dict[str, Any]:
    scenarios = list(data.S)
    probs = {int(s): float(data.prob[s]) for s in scenarios}
    sigma_by_scenario: dict[str, dict] = {}
    for s in scenarios:
        sigmas = [float(data.sigma[e][s]) for e in data.E if e in data.sigma and s in data.sigma[e]]
        if sigmas:
            sigma_by_scenario[str(s)] = {
                "min": min(sigmas),
                "max": max(sigmas),
                "mean": sum(sigmas) / len(sigmas),
            }
    return {
        "scenario_mode": getattr(data, "scenario_mode", "macro3"),
        "scenarios": scenarios,
        "probabilities": probs,
        "sigma_summary_by_scenario": sigma_by_scenario,
        "scenario_s1_link_k": getattr(data, "scenario_s1_link_k", None),
        "scenario_s1_link_sigma": getattr(data, "scenario_s1_link_sigma", None),
        "scenario_s1_mode": getattr(data, "scenario_s1_mode", None),
        "scenario_s1_stressed_edges": getattr(data, "scenario_s1_stressed_edges", None),
        "scenario_s2_derate": getattr(data, "scenario_s2_derate", None),
    }


def _compute_capacity_summary(data) -> dict[str, Any]:
    normal: dict[str, dict] = {}
    for node in data.M:
        normal[str(node)] = {str(k): float(data.C_normal[node][k]) for k in data.K}
    by_scenario: dict[str, dict] = {}
    for s in data.S:
        by_scenario[str(s)] = {
            str(node): {str(k): float(data.C_s[node][k][s]) for k in data.K}
            for node in data.M
        }
    return {"C_normal_by_node": normal, "C_s_by_scenario": by_scenario}


def _task_selection_summary(data) -> dict[str, Any]:
    tasks = []
    for i in data.I:
        tasks.append(
            {
                "task_id": int(i),
                "src": int(data.task_src[i]),
                "dst": int(data.task_dst[i]),
                "b_in": float(data.b_in[i]),
                "b_out": float(data.b_out[i]),
                "w": {str(k): float(data.w[i][k]) for k in data.K},
            }
        )
    total_in = sum(float(data.b_in[i]) for i in data.I)
    return {
        "num_tasks": len(data.I),
        "task_selection_seed": "deterministic_sort_by_demand_desc",
        "tasks": tasks,
        "demand_total_b_in": total_in,
    }


def build_resolved_config(
    data,
    args,
    *,
    routing_mode: str,
    gamma_sla: list[float] | None = None,
    gamma_sf: list[float] | None = None,
    loader_entrypoint: str = "run_gamma_frontier.load_p0_data",
) -> dict[str, Any]:
    eta_val = args.joint_demand_scale if args.joint_demand_scale is not None else args.eta
    cfg: dict[str, Any] = {
        "snapshot_version": "phase_b_plus_plus_plus_1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "topology": args.topology,
        "routing_mode": routing_mode,
        "num_tasks": args.num_tasks,
        "k_paths": args.k_paths,
        "task_selection": _task_selection_summary(data),
        "random_seed": getattr(data, "random_seed", None),
        "link_price": _link_price_summary(data),
        "scenarios": _scenario_summary(data),
        "demand_calibration": {
            "eta": float(eta_val) if eta_val is not None else None,
            "joint_demand_scale": args.joint_demand_scale,
            "demand_scale_explicit": args.joint_demand_scale is not None,
        },
        "compute_capacity": _compute_capacity_summary(data),
        "omega_deliver": float(getattr(args, "omega_deliver", 1.0)),
        "gamma_sla_values": gamma_sla,
        "gamma_sf_values": gamma_sf,
        "min_off_hub": args.min_off_hub,
        "sf_ref_mode": "global_M_ex",
        "sf_ref_note": "Model C SF CVaR uses scalar D_ref=M_ex (Phase B+ baseline); not per_resource.",
        "loader": {
            "entrypoint": loader_entrypoint,
            "effective_arguments": {
                "base_path": args.base_path,
                "topology": args.topology,
                "num_tasks": args.num_tasks,
                "k_paths": args.k_paths,
                "eta": args.eta,
                "joint_demand_scale": args.joint_demand_scale,
                "routing_mode": routing_mode,
                "s2_derate": args.s2_derate,
                "s1_link_k": args.s1_link_k,
                "s1_sigma": args.s1_sigma,
                "umcf_access_sigma": getattr(args, "umcf_access_sigma", None),
                "umcf_sink_access_sigma": getattr(args, "umcf_sink_access_sigma", None),
                "link_price_mode": args.link_price_mode,
                "omega_deliver": getattr(args, "omega_deliver", 1.0),
                "time_limit": args.time_limit,
                "mip_gap": args.mip_gap,
            },
        },
        "git": _git_snapshot(),
        "virtual_edge_meta": getattr(data, "routing_virtual_edge_meta", {}),
    }
    return cfg


def write_resolved_config(path: Path, config: dict[str, Any]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")
    return out
