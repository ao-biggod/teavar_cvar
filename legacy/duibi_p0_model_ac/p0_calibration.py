# -*- coding: utf-8 -*-
"""
P0 实验装置：η 标定与幸存容量估计（工程近似版）。

``estimate_surv_capacity`` 为 **保守近似**，非精确 max-flow LP；
见函数 docstring。``apply_eta_demand_calibration`` 将任务 demand 总量缩放到 η·C_surv。
"""
from __future__ import annotations

from typing import Callable, Optional


def _path_bottleneck(data, path: list, scenario_id: int) -> float:
    """路径在场景 s 下的瓶颈幸存容量 min_{e∈p} σ_e·B_e。"""
    s = int(scenario_id)
    if not path:
        return 0.0
    return min(float(data.sigma[e][s]) * float(data.B[e]) for e in path)


def _task_od_endpoints(data, task_i: int) -> tuple[int, int]:
    routing_mode = getattr(data, "routing_mode", "hub")
    if routing_mode == "per_task_od":
        return int(data.task_src[task_i]), int(data.task_dst[task_i])
    h = int(getattr(data, "hub", 0))
    return h, h


def estimate_surv_capacity(data, scenario_id: int = 1) -> float:
    """
    估算场景 ``scenario_id`` 下网络「幸存承载能力」C_surv（**近似**）。

    算法（保守、可复现）：
    对每个任务 i、每个 ``valid_assign[i,m]``，遍历 ingress ``P_cand[(src_i,m)]``
    与 egress ``P_cand[(m,dst_i)]`` 的候选路径，取路径瓶颈
    ``min_{e∈p} σ_e(s)·B_e``；C_surv = 所有上述瓶颈的全局 **最大值**。

    不保证等于真实 multicommodity max-flow；P0 用于 η 标定量级。
    """
    s = int(scenario_id)
    best = 0.0
    for i in data.I:
        src_i, dst_i = _task_od_endpoints(data, i)
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            for path in data.P_cand.get((src_i, m), [[]]):
                if path:
                    best = max(best, _path_bottleneck(data, path, s))
            for path in data.P_cand.get((m, dst_i), [[]]):
                if path:
                    best = max(best, _path_bottleneck(data, path, s))
    return float(best)


def _total_task_demand(data) -> float:
    return float(sum(float(data.b_in[i]) + float(data.b_out[i]) for i in data.I))


def apply_eta_demand_calibration(
    data,
    eta: float = 1.3,
    scenario_id: int = 1,
    *,
    log: Optional[Callable[[str], None]] = print,
) -> dict:
    """
    将 ``b_in/b_out`` 缩放，使 ``Σ_i (b_in[i]+b_out[i]) ≈ η · C_surv``。

    返回摘要 dict 并写入 ``data.p0_calibration``。
    """
    eta = float(eta)
    if eta <= 0:
        raise ValueError(f"eta must be positive, got {eta}")
    c_surv = estimate_surv_capacity(data, scenario_id=scenario_id)
    if c_surv <= 0:
        raise ValueError(
            f"estimate_surv_capacity returned {c_surv} (scenario={scenario_id}); "
            "cannot apply eta calibration."
        )
    current = _total_task_demand(data)
    if current <= 0:
        raise ValueError("total task demand is zero; cannot apply eta calibration.")
    target = eta * c_surv
    factor = target / current
    for i in data.I:
        data.b_in[i] = max(1.0, min(float(data.b_in[i]) * factor, 2.0e6))
        data.b_out[i] = max(1.0, min(float(data.b_out[i]) * factor, 2.0e6))
    summary = {
        "eta": eta,
        "estimated_surv_capacity": c_surv,
        "demand_total_before": current,
        "demand_total_after": _total_task_demand(data),
        "demand_scale_factor": factor,
        "scenario_id": int(scenario_id),
        "used_eta_calibration": True,
    }
    data.p0_calibration = summary
    if log:
        log(
            f"  [eta] η={eta:.3f} | C_surv≈{c_surv:.2f} | "
            f"demand {current:.1f} → {summary['demand_total_after']:.1f} "
            f"(×{factor:.4f})"
        )
    return summary
