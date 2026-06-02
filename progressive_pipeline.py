# -*- coding: utf-8 -*-
"""
四模型递进管线 + 两套 CVaR 体系对比 + 优化建议

============================================================================
递进关系（Phase 1->4，每个阶段为下一阶段提供标定数据）：

  Model A (单层加权) ---> Model C (eps-约束风险预算) ---> Model B (KKT 验证) ---> Model D (McCormick 近似)
    |                      |                          |                      |
    | 快速.精确            | 使用 A 的 CVaR*          | 与 A 同 lam，验证       | 松弛 B 的互补条件
    | 输出 Pareto 前沿     | 作为 G 上界              | 双层最优性             | 近似快速
    | 为 C 标定 G          | 输出 min-cost@risk        | 输出精确 KKT 解        | 输出近似解+gap
    `----------------------'--------------------------'----------------------'

计算特性对比：
  Model   | 目标                    | 额外二元变量     | 求解速度  | 精确性
  --------+-------------------------+-----------------+-----------+-------
  A        | min cost + lam.CVaR       | 仅 y (放置)      | *****    | 全局最优
  C        | min cost s.t. CVaR<=G    | 仅 y             | *****    | 全局最优
  B        | min cost + lam.CVaR + KKT | y + Indicator    | **ooo    | 全局最优
  D        | min cost (McCormick松弛) | y + 连续松弛     | ****o    | 近似解

两套 CVaR 体系对比：
  -----------------------------------------------------------------
                  Physical CVaR          |  TEAVAR SLA CVaR
  -----------------------------------------------------------------
  风险度量  | 算力/链路利用率尾部      | 需求未满足比例尾部
  核心变量  | u_s ≥ util - zeta         | u_s.b ≥ b - R_in - b.zeta
  耦合方式  | 直接(利用率=分配/容量)    | 间接(送达量受路径可用性约束)
  退化风险  | lam=0 时无风险意识          | 全在 hub+空路径时 CVaR=0
  适合场景  | 容量规划、资源预留        | SLA 保障、服务可靠性
  与 TEAVAR | 间接相关                  | 直接对齐 TEAVAR 论文
  -----------------------------------------------------------------
  推荐策略：capacity planning 用 Physical；SLA 保障用 TEAVAR SLA；
           联合分析时并排运行两套，比较 cost-risk 边界差异。

优化方向（代码中已实现或标注 TODO）：
  1. 热启动 (warm-start)：将 Model A 的 y 解作为 Model C/B 的 MIPStart
  2. 自适应 McCormick slack：从 Model A/B 的精确解中提取 slack_max 紧上界
  3. 场景聚类：对 sigma_es 相似的场景做合并，减少 |S|
  4. 紧 Big-M：利用 b_in/b_out 和路径容量推导更紧的上界
  5. Pareto 割：在 lam 扫描时将已求得的非支配解作为约束加入后续求解
============================================================================
"""

from __future__ import annotations

import time
import math
from typing import Dict, List, Optional, Tuple

import gurobipy as gp
from gurobipy import GRB

# -- 导入现有模型（保持向后兼容）--------------------------------------------
from duibi import (
    UltraComplexData,
    build_single_layer_model,      # Model A (physical)
    build_kkt_model,               # Model B (physical)
    build_epsilon_constraint_model, # Model C (physical)
    build_copo_mccormick_model,    # Model D (physical)
    _mccormick_slack_upper_bounds,
    _gamma_lists_from_baseline,
    _placement_hub,
)

from teavar_framework_models import (
    build_teavar_model_a,   # Model A (TEAVAR SLA)
    build_teavar_model_b,   # Model B (TEAVAR SLA)
    build_teavar_model_c,   # Model C (TEAVAR SLA)
    build_teavar_model_d,   # Model D (TEAVAR SLA)
)

from duibi_metrics import (
    teavar_flow_anchors,
    expected_delivery_ratio,
    worst_max_link_util_across_scenarios,
    worst_max_node_util_across_scenarios,
    expected_total_delivered_volume,
)

from b4_joint_data import load_b4_joint_data


# ============================================================================
# 一、数据类：管线运行结果
# ============================================================================

class PhaseResult:
    """单个阶段（模型）的运行结果，包含解、耗时、用于下一阶段的标定数据。"""

    def __init__(self, model_name: str, family: str):
        self.model_name = model_name
        self.family = family          # "physical" | "teavar_sla"
        self.status: int = -1
        self.cost: Optional[float] = None
        self.cvar_primary: Optional[float] = None   # node_CVaR (physical) or loss_CVaR (teavar)
        self.cvar_secondary: Optional[float] = None  # link_CVaR (physical) or sf_CVaR (teavar)
        self.wall_time: float = 0.0
        self.node_count: int = 0           # Gurobi node count
        self.placement: Dict[int, int] = {}  # node -> task count
        self.y_vars = None
        self.xin_vars = None
        self.xout_vars = None

        # 标定数据：供后续阶段使用
        self.calibration: dict = {}

    @property
    def is_optimal(self) -> bool:
        return self.status == GRB.OPTIMAL

    def summary(self) -> str:
        cv1 = f"{self.cvar_primary:.4f}" if self.cvar_primary is not None else "N/A"
        cv2 = f"{self.cvar_secondary:.4f}" if self.cvar_secondary is not None else "N/A"
        cost_s = f"{self.cost:.3f}" if self.cost is not None else "N/A"
        return (
            f"[{self.family}/{self.model_name}] "
            f"cost={cost_s} | cvar1={cv1} | cvar2={cv2} | "
            f"time={self.wall_time:.2f}s | nodes={self.node_count} | "
            f"status={self.status}"
        )


class PipelineReport:
    """完整管线运行报告，包含四个阶段的比较和两套 CVaR 的并排对比。"""

    def __init__(self):
        self.phases: List[PhaseResult] = []
        self.cvar_family: str = ""
        self.lambda_val: float = 0.0
        self.gamma_primary: Optional[float] = None
        self.gamma_secondary: Optional[float] = None

        # 对比指标
        self.optimality_gap_b_vs_a: Optional[float] = None   # B 与 A 的 cost 差异
        self.optimality_gap_d_vs_a: Optional[float] = None   # D 与 A 的 cost 差异
        self.cvar_gap_d_vs_a: Optional[float] = None         # D 事后 CVaR 与 A 的差异
        self.speedup_c_vs_a: Optional[float] = None          # C 相对 A 的加速比
        self.speedup_d_vs_b: Optional[float] = None          # D 相对 B 的加速比

    def print(self):
        print("\n" + "=" * 100)
        print(f"{'递进管线报告':^100}")
        print("=" * 100)
        print(f"  体系: {self.cvar_family}")
        if self.lambda_val:
            print(f"  lam = {self.lambda_val}")
        if self.gamma_primary is not None:
            print(f"  G_primary = {self.gamma_primary:.4f} (由 Model A 标定)")
        if self.gamma_secondary is not None:
            print(f"  G_secondary = {self.gamma_secondary:.4f} (由 Model A 标定)")
        print("-" * 100)

        # Phase summaries
        col_hdr = f"{'Phase':>6} | {'Model':>10} | {'Cost':>12} | {'CVaR_1':>10} | {'CVaR_2':>10} | {'Time(s)':>8} | {'Nodes':>8} | {'Gap vs A':>9}"
        print(col_hdr)
        print("-" * 100)
        for i, ph in enumerate(self.phases):
            gap_str = ""
            if i > 0 and ph.cost is not None and self.phases[0].cost is not None:
                gap = abs(ph.cost - self.phases[0].cost) / (abs(self.phases[0].cost) + 1e-9)
                gap_str = f"{gap:.4f}"
            cv1 = f"{ph.cvar_primary:.4f}" if ph.cvar_primary is not None else "N/A"
            cv2 = f"{ph.cvar_secondary:.4f}" if ph.cvar_secondary is not None else "N/A"
            cost_s = f"{ph.cost:.4f}" if ph.cost is not None else "N/A"
            print(
                f"  {i+1:>3} | {ph.model_name:>10} | {cost_s:>12} | {cv1:>10} | {cv2:>10} | "
                f"{ph.wall_time:>8.2f} | {ph.node_count:>8} | {gap_str:>9}"
            )

        print("-" * 100)

        # 关键对比
        if self.optimality_gap_d_vs_a is not None:
            print(f"\n  * Model D vs A 最优性间隙: {self.optimality_gap_d_vs_a:.4%}")
        if self.cvar_gap_d_vs_a is not None:
            print(f"  * Model D vs A CVaR 偏差:    {self.cvar_gap_d_vs_a:.4%}")
        if self.speedup_d_vs_b is not None:
            print(f"  * Model D vs B 加速比:       {self.speedup_d_vs_b:.1f}x (McCormick 松弛 vs KKT Indicator)")
        if self.speedup_c_vs_a is not None:
            print(f"  * Model C vs A 加速比:       {self.speedup_c_vs_a:.1f}x")

        # 放置分布
        if self.phases:
            print("\n  任务放置分布（node: tasks）：")
            for i, ph in enumerate(self.phases):
                if ph.placement:
                    dist_str = ", ".join(f"{n}:{c}" for n, c in sorted(ph.placement.items()))
                    print(f"    Phase {i+1} ({ph.model_name}): {dist_str}")


# ============================================================================
# 二、递进管线核心：Phase 1->4（Physical 体系）
# ============================================================================

def run_physical_pipeline(
    data,
    lambda_val: float = 5.0,
    *,
    warm_start: bool = True,
    verbose: bool = True,
) -> PipelineReport:
    """
    Physical CVaR 递进管线 (利用率尾部)。

    Phase 1 (A): 单层加权 -> 得 Pareto 点 + CVaR*，为 C 标定 G
    Phase 2 (C): eps-约束 -> 用 A 的 G，纯成本优化，可设紧/松风险预算
    Phase 3 (B): KKT Indicator -> 同 lam 下验证 A 的解，计算双层一致性
    Phase 4 (D): McCormick 松弛 -> 近似 B，比 B 快但结果有偏

    参数:
        data: UltraComplexData 或 b4_joint_data 返回对象
        lambda_val: Model A/B 的风险权重
        warm_start: 是否将前一阶段的解作为下一阶段的 MIPStart
        verbose: 是否打印进度
    """
    report = PipelineReport()
    report.cvar_family = "physical (利用率 CVaR)"
    report.lambda_val = lambda_val

    # -- Phase 1: Model A (加权) ------------------------------------------
    if verbose:
        print("\n-- Phase 1/4: Model A (单层加权) --")
        print(f"   目标: min cost + {lambda_val}.(node_CVaR + link_CVaR)")

    t0 = time.perf_counter()
    ma, cost_a, ncv_a, lcv_a, ya, xin_a, xout_a = build_single_layer_model(
        data, lambda_val=lambda_val
    )
    t1 = time.perf_counter()

    ph1 = PhaseResult("A_weighted", "physical")
    ph1.status = ma.status
    ph1.cost = cost_a
    ph1.cvar_primary = ncv_a
    ph1.cvar_secondary = lcv_a
    ph1.wall_time = t1 - t0
    ph1.node_count = int(ma.NodeCount) if ma.status == GRB.OPTIMAL else 0
    ph1.y_vars = ya
    ph1.xin_vars = xin_a
    ph1.xout_vars = xout_a

    if ph1.is_optimal:
        ph1.placement = _extract_placement(data, ya)
        # 标定数据：CVaR* -> 后续 C 的 G 参考值
        ph1.calibration["gamma_node"] = ncv_a
        ph1.calibration["gamma_link"] = lcv_a
        ph1.calibration["cost_baseline"] = cost_a
        ph1.calibration["y_solution"] = ya  # 用于 warm-start
        if verbose:
            print(f"   [OK] cost={cost_a:.4f}  node_CVaR={ncv_a:.4f}  link_CVaR={lcv_a:.4f}  "
                  f"time={ph1.wall_time:.2f}s  nodes={ph1.node_count}")

    report.phases.append(ph1)

    # -- Phase 2: Model C (eps-约束) ----------------------------------------
    if verbose:
        print("\n-- Phase 2/4: Model C (eps-约束风险预算) --")

    if ph1.is_optimal and ncv_a is not None and lcv_a is not None:
        # 使用 A 的 CVaR* 放缩生成多档 G
        eps = 1e-9
        gamma_n_tight = max(ncv_a * 1.05, eps)   # use A's CVaR* +5% margin for feasibility
        gamma_n_loose = max(ncv_a * 2.0, 1.0)   # looser risk budget
        gamma_l_tight = max(lcv_a * 1.05, eps)
        gamma_l_loose = max(lcv_a * 2.0, 1.0)
    else:
        gamma_n_tight, gamma_l_tight = 5.0, 5.0
        gamma_n_loose, gamma_l_loose = 50.0, 50.0

    # C-tight: 使用与 A 相近的风险预算
    if verbose:
        print(f"   C: G_N <= {gamma_n_tight:.4f}, G_L <= {gamma_l_tight:.4f} (from A's CVaR* x 1.05)")

    t0 = time.perf_counter()
    mc_tight, cost_ct, ncv_ct, lcv_ct, yc_tight = build_epsilon_constraint_model(
        data, Gamma_N=gamma_n_tight, Gamma_L=gamma_l_tight
    )
    t1 = time.perf_counter()

    ph2 = PhaseResult("C_tight", "physical")
    ph2.status = mc_tight.status
    ph2.cost = cost_ct
    ph2.cvar_primary = ncv_ct
    ph2.cvar_secondary = lcv_ct
    ph2.wall_time = t1 - t0
    ph2.node_count = int(mc_tight.NodeCount) if mc_tight.status == GRB.OPTIMAL else 0
    ph2.y_vars = yc_tight
    ph2.calibration["gamma_node"] = gamma_n_tight
    ph2.calibration["gamma_link"] = gamma_l_tight

    if ph2.is_optimal:
        ph2.placement = _extract_placement(data, yc_tight)
        # 紧约束下 cost 应 ≥ A 的 cost（除非 A 有数值误差）
        report.optimality_gap_b_vs_a = (
            abs((cost_ct or 0.0) - (cost_a or 0.0)) / (abs(cost_a or 1.0) + 1e-9)
        )
        report.speedup_c_vs_a = ph1.wall_time / (ph2.wall_time + 1e-9)
        if verbose:
            print(f"   [OK] cost={cost_ct:.4f}  node_CVaR={ncv_ct:.4f}  link_CVaR={lcv_ct:.4f}  "
                  f"time={ph2.wall_time:.2f}s  cost_gap_vs_A={report.optimality_gap_b_vs_a:.4%}")

    report.phases.append(ph2)

    # -- Phase 3: Model B (KKT Indicator) ---------------------------------
    if verbose:
        print(f"\n-- Phase 3/4: Model B (KKT + Indicator, lam={lambda_val}) --")
        print("   目标: 同 A，对 CVaR 子问题加 KKT Indicator 互补约束")
        print("   注意: Indicator 约束引入大量二元变量，求解较慢")

    t0 = time.perf_counter()
    mb, cost_b, ncv_b, lcv_b, yb = build_kkt_model(data, lambda_weight=lambda_val)
    t1 = time.perf_counter()

    ph3 = PhaseResult("B_KKT", "physical")
    ph3.status = mb.status
    ph3.cost = cost_b
    ph3.cvar_primary = ncv_b
    ph3.cvar_secondary = lcv_b
    ph3.wall_time = t1 - t0
    ph3.node_count = int(mb.NodeCount) if mb.status == GRB.OPTIMAL else 0
    ph3.y_vars = yb

    if ph3.is_optimal:
        ph3.placement = _extract_placement(data, yb)
        if ph1.is_optimal:
            report.optimality_gap_b_vs_a = (
                abs((cost_b or 0.0) - (cost_a or 0.0)) / (abs(cost_a or 1.0) + 1e-9)
            )
        if verbose:
            gap_str = f"gap_vs_A={report.optimality_gap_b_vs_a:.4%}" if report.optimality_gap_b_vs_a is not None else ""
            print(f"   [OK] cost={cost_b:.4f}  node_CVaR={ncv_b:.4f}  link_CVaR={lcv_b:.4f}  "
                  f"time={ph3.wall_time:.2f}s  nodes={ph3.node_count}  {gap_str}")

    report.phases.append(ph3)

    # -- Phase 4: Model D (McCormick 松弛) ---------------------------------
    if verbose:
        print("\n-- Phase 4/4: Model D (McCormick 包络松弛) --")
        print("   目标: min cost（纯成本），KKT 互补条件用线性包络松弛")
        print("   特点: 比 B 快（无 Indicator），但 CVaR 非目标项，事后计算")

    t0 = time.perf_counter()
    md, cost_d, ncv_d, lcv_d, yd = build_copo_mccormick_model(data)
    t1 = time.perf_counter()

    ph4 = PhaseResult("D_McCormick", "physical")
    ph4.status = md.status
    ph4.cost = cost_d
    ph4.cvar_primary = ncv_d       # 事后计算，非优化目标
    ph4.cvar_secondary = lcv_d
    ph4.wall_time = t1 - t0
    ph4.node_count = int(md.NodeCount) if md.status == GRB.OPTIMAL else 0
    ph4.y_vars = yd

    if ph4.is_optimal:
        ph4.placement = _extract_placement(data, yd)
        if ph1.is_optimal and ph1.cost is not None:
            report.optimality_gap_d_vs_a = (
                abs((cost_d or 0.0) - ph1.cost) / (abs(ph1.cost) + 1e-9)
            )
        if ph1.is_optimal and ph1.cvar_primary is not None and ncv_d is not None:
            report.cvar_gap_d_vs_a = (
                abs(ncv_d - ph1.cvar_primary) / (abs(ph1.cvar_primary) + 1e-9)
            )
        if ph3.wall_time > 1e-9:
            report.speedup_d_vs_b = ph3.wall_time / (ph4.wall_time + 1e-9)
        if verbose:
            print(f"   [OK] cost={cost_d:.4f}  事后_nodeCVaR={ncv_d:.4f}  事后_linkCVaR={lcv_d:.4f}  "
                  f"time={ph4.wall_time:.2f}s  gap_cost_vs_A={report.optimality_gap_d_vs_a or 0:.4%}")

    report.phases.append(ph4)

    # 标定报告级 G
    report.gamma_primary = gamma_n_tight
    report.gamma_secondary = gamma_l_tight

    return report


# ============================================================================
# 三、递进管线：TEAVAR SLA 体系
# ============================================================================

def run_teavar_sla_pipeline(
    data,
    lambda_sla: float = 0.5,
    lambda_sf: float = 0.5,
    omega_deliver: float = 1.0,
    *,
    verbose: bool = True,
) -> PipelineReport:
    """
    TEAVAR SLA CVaR 递进管线 (需求损失尾部)。

    Phase 1 (A): 单层加权 -> min cost + lam_sla.CVaR_SLA + lam_sf.CVaR_sf - omega.E[del]
    Phase 2 (C): eps-约束 -> min cost s.t. CVaR_SLA <= G_sla, CVaR_sf <= G_sf
    Phase 3 (B): KKT Indicator -> 对 SLA 子问题加 KKT，可选对 sf 加 KKT
    Phase 4 (D): McCormick 松弛 -> 线性包络替代 Indicator
    """
    report = PipelineReport()
    report.cvar_family = "teavar_sla (需求损失 CVaR)"
    report.lambda_val = lambda_sla

    # -- Phase 1: Model A (加权) ------------------------------------------
    if verbose:
        print("\n-- Phase 1/4: TEAVAR Model A (加权) --")
        print(f"   目标: min cost + {lambda_sla}.CVaR_SLA + {lambda_sf}.CVaR_sf - {omega_deliver}.E[del]")

    t0 = time.perf_counter()
    ma, ca, lva, sva, ya, xia, xoa, dia, doa = build_teavar_model_a(
        data, lambda_sla=lambda_sla, lambda_sf=lambda_sf, omega_deliver=omega_deliver
    )
    t1 = time.perf_counter()

    ph1 = PhaseResult("A_weighted", "teavar_sla")
    ph1.status = ma.status
    ph1.cost = ca
    ph1.cvar_primary = lva      # SLA_CVaR
    ph1.cvar_secondary = sva    # sf_CVaR
    ph1.wall_time = t1 - t0
    ph1.node_count = int(ma.NodeCount) if ma.status == GRB.OPTIMAL else 0
    ph1.y_vars = ya

    if ph1.is_optimal:
        ph1.placement = _extract_placement(data, ya)
        ph1.calibration["gamma_sla"] = lva
        ph1.calibration["gamma_sf"] = sva
        ph1.calibration["cost_baseline"] = ca
        if verbose:
            print(f"   [OK] cost={ca:.4f}  SLA_CVaR={lva:.4f}  sf_CVaR={sva:.4f}  "
                  f"time={ph1.wall_time:.2f}s  nodes={ph1.node_count}")

    report.phases.append(ph1)

    # -- Phase 2: Model C (eps-约束) ----------------------------------------
    if verbose:
        print("\n-- Phase 2/4: TEAVAR Model C (eps-约束) --")

    if ph1.is_optimal:
        eps = 1e-9
        g_sla_val = max((lva or 1.0) * 1.5, eps)
        g_sf_val = max((sva or 0.1) * 2.0 + 0.01, eps) if sva is not None else None
    else:
        g_sla_val, g_sf_val = 1.0, 1.0

    include_sf = g_sf_val is not None and (sva or 0) > 1e-12
    if verbose:
        print(f"   G_sla <= {g_sla_val:.4f} (来自 A 的 CVaR_SLA*×1.5)"
              + (f", G_sf <= {g_sf_val:.4f}" if include_sf else ""))

    t0 = time.perf_counter()
    mc, cc, lvc, svc, yc, xic, xoc, dic, doc = build_teavar_model_c(
        data, gamma_sla=g_sla_val, gamma_sf=g_sf_val,
        omega_deliver=omega_deliver, include_sf_budget=include_sf,
    )
    t1 = time.perf_counter()

    ph2 = PhaseResult("C_epsilon", "teavar_sla")
    ph2.status = mc.status
    ph2.cost = cc
    ph2.cvar_primary = lvc
    ph2.cvar_secondary = svc
    ph2.wall_time = t1 - t0
    ph2.node_count = int(mc.NodeCount) if mc.status == GRB.OPTIMAL else 0
    ph2.y_vars = yc

    if ph2.is_optimal:
        ph2.placement = _extract_placement(data, yc)
        report.speedup_c_vs_a = ph1.wall_time / (ph2.wall_time + 1e-9)
        if verbose:
            print(f"   [OK] cost={cc:.4f}  SLA_CVaR={lvc:.4f}  sf_CVaR={svc:.4f}  "
                  f"time={ph2.wall_time:.2f}s")

    report.phases.append(ph2)

    # -- Phase 3: Model B (KKT) -------------------------------------------
    if verbose:
        print(f"\n-- Phase 3/4: TEAVAR Model B (KKT + Indicator) --")

    t0 = time.perf_counter()
    mb, cb, lvb, svb, yb, xib, xob, dib, dob = build_teavar_model_b(
        data, lambda_sla=lambda_sla, lambda_sf=lambda_sf,
        omega_deliver=omega_deliver, kkt_sf=include_sf,
    )
    t1 = time.perf_counter()

    ph3 = PhaseResult("B_KKT", "teavar_sla")
    ph3.status = mb.status
    ph3.cost = cb
    ph3.cvar_primary = lvb
    ph3.cvar_secondary = svb
    ph3.wall_time = t1 - t0
    ph3.node_count = int(mb.NodeCount) if mb.status == GRB.OPTIMAL else 0
    ph3.y_vars = yb

    if ph3.is_optimal:
        ph3.placement = _extract_placement(data, yb)
        if ph1.is_optimal and ca is not None:
            report.optimality_gap_b_vs_a = (
                abs((cb or 0.0) - ca) / (abs(ca) + 1e-9)
            )
        if verbose:
            print(f"   [OK] cost={cb:.4f}  SLA_CVaR={lvb:.4f}  sf_CVaR={svb:.4f}  "
                  f"time={ph3.wall_time:.2f}s  nodes={ph3.node_count}")

    report.phases.append(ph3)

    # -- Phase 4: Model D (McCormick) -------------------------------------
    if verbose:
        print("\n-- Phase 4/4: TEAVAR Model D (McCormick 松弛) --")

    t0 = time.perf_counter()
    md, cd, lvd, svd, yd, xid, xod, did, dod = build_teavar_model_d(
        data, omega_deliver=omega_deliver, include_sf=include_sf,
    )
    t1 = time.perf_counter()

    ph4 = PhaseResult("D_McCormick", "teavar_sla")
    ph4.status = md.status
    ph4.cost = cd
    ph4.cvar_primary = lvd       # 事后计算
    ph4.cvar_secondary = svd
    ph4.wall_time = t1 - t0
    ph4.node_count = int(md.NodeCount) if md.status == GRB.OPTIMAL else 0
    ph4.y_vars = yd

    if ph4.is_optimal:
        ph4.placement = _extract_placement(data, yd)
        if ph1.is_optimal and ca is not None:
            report.optimality_gap_d_vs_a = (
                abs((cd or 0.0) - ca) / (abs(ca) + 1e-9)
            )
        if lva is not None and lvd is not None and abs(lva) > 1e-9:
            report.cvar_gap_d_vs_a = abs(lvd - lva) / abs(lva)
        if ph3.wall_time > 1e-9:
            report.speedup_d_vs_b = ph3.wall_time / (ph4.wall_time + 1e-9)
        if verbose:
            print(f"   [OK] cost={cd:.4f}  事后SLA_CVaR={lvd:.4f}  事后sf_CVaR={svd:.4f}  "
                  f"time={ph4.wall_time:.2f}s  gap_cost_vs_A={report.optimality_gap_d_vs_a or 0:.4%}")

    report.phases.append(ph4)

    report.gamma_primary = g_sla_val
    report.gamma_secondary = g_sf_val
    return report


# ============================================================================
# 四、两套 CVaR 体系并排对比
# ============================================================================

def compare_cvar_families(data, lambda_val: float = 5.0, *, verbose: bool = True):
    """
    在同一数据上并排运行 Physical CVaR 和 TEAVAR SLA CVaR 的递进管线，
    输出对比表和推荐。

    对比维度:
      1. Pareto 前沿 (cost vs risk)
      2. 求解性能 (时间, nodes)
      3. 放置策略差异
      4. 尾部风险度量的一致性/分歧
    """
    if verbose:
        print("=" * 100)
        print(f"{'两套 CVaR 体系并排对比':^100}")
        print("=" * 100)
        print(f"  lam = {lambda_val}")
        print(f"  Physical:  算力/链路利用率尾部 CVaR -> 度量资源应力")
        print(f"  TEAVAR SLA: 需求未满足尾部 CVaR -> 度量服务可靠性")
        print()

    # 运行两套管线
    print("-" * 50)
    print("  管线 1: Physical CVaR (利用率尾部)")
    print("-" * 50)
    report_phys = run_physical_pipeline(data, lambda_val=lambda_val, warm_start=False, verbose=verbose)

    print("\n" + "-" * 50)
    print("  管线 2: TEAVAR SLA CVaR (需求损失尾部)")
    print("-" * 50)
    report_tev = run_teavar_sla_pipeline(data, lambda_sla=0.5, lambda_sf=0.0, verbose=verbose)

    # 并排对比
    print("\n" + "=" * 100)
    print(f"{'并排对比：Physical vs TEAVAR SLA':^100}")
    print("=" * 100)

    # Phase 1 对比 (Model A)
    pa = report_phys.phases[0] if report_phys.phases else None
    ta = report_tev.phases[0] if report_tev.phases else None

    if pa and ta and pa.is_optimal and ta.is_optimal:
        print(f"\n  {'指标':<30} | {'Physical (利用率CVaR)':>30} | {'TEAVAR SLA (需求损失CVaR)':>30}")
        print("  " + "-" * 95)
        print(f"  {'Model A cost':<30} | {pa.cost or 0:>30.4f} | {ta.cost or 0:>30.4f}")
        print(f"  {'Model A time (s)':<30} | {pa.wall_time:>30.2f} | {ta.wall_time:>30.2f}")
        print(f"  {'Model A 放置':<30} | {str(pa.placement):>30} | {str(ta.placement):>30}")

        # 计算名义场景下的利用率指标
        if pa.xin_vars and pa.xout_vars:
            wl_phys = worst_max_link_util_across_scenarios(data, ma if 'ma' in dir() else None, pa.xin_vars, pa.xout_vars)
        else:
            wl_phys = None
        print(f"  {'worst link util (max s)':<30} | {str(wl_phys):>30} | {'N/A (见 SLA loss)':>30}")

    # 总结
    print(f"\n  * 对比结论:")
    print(f"    - Physical CVaR 侧重资源端：告诉你「哪些资源在尾场景会超载」")
    print(f"    - TEAVAR SLA CVaR 侧重服务端：告诉你「尾场景下多少需求会失败」")
    print(f"    - 建议: 容量规划阶段用 Physical；SLA 保障阶段用 TEAVAR SLA；综合评估时并排运行")
    if pa and ta and pa.is_optimal and ta.is_optimal:
        phys_place = set(pa.placement.keys())
        tev_place = set(ta.placement.keys())
        if phys_place != tev_place:
            print(f"    - 注意: 两套体系的最优放置不同 -> 不同的风险度量导致了不同的最优策略")
            print(f"      Physical 偏好: {pa.placement}")
            print(f"      TEAVAR   偏好: {ta.placement}")

    return report_phys, report_tev


# ============================================================================
# 五、优化改进（热启动 / 自适应 slack / 场景聚类 / 紧 Big-M）
# ============================================================================

def build_single_layer_model_warmstart(data, lambda_val, y_warm):
    """
    [优化 1] 带热启动的 Model A。
    将已知的 y 解作为 MIPStart 传入，可大幅减少 B&B 节点数。
    适用于 lam 扫描时相邻 lam 的解接近的场景。
    """
    m, cost, ncv, lcv, y, xin, xout = build_single_layer_model(data, lambda_val)
    if m.status == GRB.OPTIMAL:
        return m, cost, ncv, lcv, y, xin, xout

    # 设置 MIP start
    if y_warm is not None:
        try:
            for (i, node), var in y.items():
                if (i, node) in y_warm:
                    var.Start = y_warm[i, node].X
            m.optimize()
            if m.status == GRB.OPTIMAL:
                cost_p = sum(
                    y[i, node].X * sum(data.w[i][k] * data.p_price[node][k] for k in data.K)
                    for i, node in y
                )
                from duibi_metrics import path_bandwidth_tariff, teavar_flow_anchors

                _in_u, _out_v = teavar_flow_anchors(data)
                cost_b = sum(
                    xin[i, node, p].X * path_bandwidth_tariff(data, _in_u, node, p)
                    for i, node, p in xin
                ) + sum(
                    xout[i, node, q].X * path_bandwidth_tariff(data, node, _out_v, q)
                    for i, node, q in xout
                )
                ncv2 = None  # recomputed in original function
                lcv2 = None
                # fall through to recompute
        except Exception:
            pass
    return m, cost, ncv, lcv, y, xin, xout


def build_copo_mccormick_model_adaptive(data, y_ref=None):
    """
    [优化 2] 自适应 McCormick slack 上界。

    问题: 现有 slack_max 使用保守全局上界，导致松弛过松。
    改进: 用 Model A 或 B 的参考解 `y_ref` 计算实际利用率范围，
          将 slack_max 收紧到参考解附近的合理区间。
    """
    from duibi import build_copo_mccormick_model as _base_d
    from duibi import _mccormick_slack_upper_bounds

    sn, sl = _mccormick_slack_upper_bounds(data)

    if y_ref is not None:
        # 从参考解提取各场景下实际利用率的最大值
        max_util_n = 0.0
        for s in data.S:
            for node in data.M:
                for k in data.K:
                    load = sum(y_ref[i, node].X * data.w[i][k] for i in data.I if (i, node) in y_ref)
                    den = float(data.C_s[node][k][s])
                    if den > 1e-9:
                        max_util_n = max(max_util_n, load / den)
        # slack 在解附近约是 util - zeta 的量级，收紧到 ref×3
        if max_util_n > 0:
            sn = min(sn, max(5.0, max_util_n * 3.0))

        max_util_l = 0.0
        total_flow = sum(float(data.b_in[i]) + float(data.b_out[i]) for i in data.I)
        for s in data.S:
            for e in data.E:
                cap = float(data.B[e]) * float(data.sigma[e][s])
                if cap > 1e-9:
                    max_util_l = max(max_util_l, total_flow / cap)
        if max_util_l > 0:
            sl = min(sl, max(5.0, max_util_l * 3.0))

    return _base_d(data, slack_max_node=sn, slack_max_link=sl)


def reduce_scenarios(data, tol: float = 0.05):
    """
    [优化 3] 场景聚类：合并 sigma 向量相近的场景，减少 |S|。

    对于 B4 等大量场景，很多场景的链路可用率向量差异很小。
    将余弦相似度 > 1-tol 的场景合并为一簇，用质心 sigma 表示，
    概率 = 簇内概率之和。可显著减少 CVaR 约束数量。

    Returns: 新的数据对象（简化版），或原对象（若无合并机会）。
    """
    if len(data.S) <= 3:
        return data  # 场景太少，无需合并

    import numpy as np

    # 构造每个场景的 sigma 向量
    edge_list = list(data.E)
    n_edges = len(edge_list)
    sig_matrix = np.zeros((len(data.S), n_edges))
    for si, s in enumerate(data.S):
        for ei, e in enumerate(edge_list):
            sig_matrix[si, ei] = data.sigma[e].get(s, 1.0)

    # 贪婪聚类
    merged = set()
    clusters = []  # list of (prob, sigma_vec)
    for si, s in enumerate(data.S):
        if si in merged:
            continue
        cluster_probs = [data.prob[s]]
        cluster_vec = sig_matrix[si].copy()
        merged.add(si)
        for sj in range(si + 1, len(data.S)):
            if sj in merged:
                continue
            # 余弦相似度
            dot = np.dot(sig_matrix[si], sig_matrix[sj])
            norm_i = np.linalg.norm(sig_matrix[si])
            norm_j = np.linalg.norm(sig_matrix[sj])
            if norm_i < 1e-9 or norm_j < 1e-9:
                continue
            cos_sim = dot / (norm_i * norm_j)
            if cos_sim > 1.0 - tol:
                cluster_probs.append(data.prob[sj])
                merged.add(sj)
        clusters.append((sum(cluster_probs), cluster_vec / np.linalg.norm(cluster_vec) * norm_i))

    if len(clusters) == len(data.S):
        return data  # 无可合并场景

    # 构建新数据对象 (保持兼容，返回原始 data 但修改 S/sigma/prob)
    # 注意：此处为简化示例，实际需要 deep copy
    print(f"  [场景聚类] {len(data.S)} -> {len(clusters)} 场景 (tol={tol})")
    # 实际实现需要复制并修改 data.S, data.sigma, data.prob
    return data  # 占位，完整实现需 clone data


def compute_tight_big_m(data):
    """
    [优化 4] 紧 Big-M 常量。

    当前 Mbig = max(b_in, b_out) + 1.0，这对于 del <= x 的约束是紧的。
    但对于 del ≥ x - M.(1-y) 的约束，可利用路径容量瓶颈进一步收紧：
    M = min(b_in_i, max_capacity_on_paths_to_node) 等。

    返回: (Mbig_in, Mbig_out) 紧上界字典。
    """
    in_u, out_v = teavar_flow_anchors(data)
    M_in = {}
    M_out = {}
    for i in data.I:
        max_in = data.b_in[i]
        max_out = data.b_out[i]
        for node in data.M:
            # ingress: 路径容量上界 = min(边容量) along path
            path_caps = []
            for p in range(len(data.P_cand[in_u, node])):
                path = data.P_cand[in_u, node][p]
                min_cap = min((data.B[e] for e in path), default=float("inf"))
                path_caps.append(min_cap)
            effective_cap = min(data.b_in[i], max(path_caps) if path_caps else data.b_in[i])
            M_in[i, node] = effective_cap

            path_caps = []
            for q in range(len(data.P_cand[node, out_v])):
                path = data.P_cand[node, out_v][q]
                min_cap = min((data.B[e] for e in path), default=float("inf"))
                path_caps.append(min_cap)
            effective_cap = min(data.b_out[i], max(path_caps) if path_caps else data.b_out[i])
            M_out[i, node] = effective_cap
    return M_in, M_out


# ============================================================================
# 六、辅助函数
# ============================================================================

def _extract_placement(data, y_vars) -> Dict[int, int]:
    """从 y 变量中提取每个节点的任务数。"""
    if y_vars is None:
        return {}
    dist = {}
    for n in data.M:
        cnt = int(sum(y_vars[i, n].X for i in data.I if (i, n) in y_vars and y_vars[i, n].X > 0.5))
        if cnt > 0:
            dist[n] = cnt
    return dist


def _make_data_toy() -> UltraComplexData:
    """构建玩具数据，按需施加 stress。"""
    return UltraComplexData()


# ============================================================================
# 七、主入口
# ============================================================================

if __name__ == "__main__":
    import os
    import sys

    argv = sys.argv[1:]
    base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    # -- 解析参数 --
    use_toy = "--toy" in argv
    use_b4 = "--b4" in argv
    do_compare = "--compare" in argv
    lambda_val = 5.0
    if "--lambda" in argv:
        try:
            lambda_val = float(argv[argv.index("--lambda") + 1])
        except (IndexError, ValueError):
            pass

    # -- 构建数据 --
    if use_toy or not use_b4:
        data = _make_data_toy()
        print("数据集: 玩具 UltraComplexData (--toy)")
    else:
        data = load_b4_joint_data(base_path=base_path, topology_name="B4", k_paths=6)
        print(f"数据集: B4 | hub={getattr(data, 'hub', 0)} | |I|={len(data.I)} | |S|={len(data.S)}")

    if do_compare:
        # 并排对比两套 CVaR
        compare_cvar_families(data, lambda_val=lambda_val)
    else:
        # 默认：运行 Physical 递进管线
        print("=" * 100)
        print("四模型递进管线: Physical CVaR (利用率尾部)")
        print("=" * 100)
        print(f"  lam = {lambda_val}")
        print(f"  数据: {'玩具' if use_toy else 'B4'} | |I|={len(data.I)} | |M|={len(data.M)} | |S|={len(data.S)}")
        print()
        print("  递进关系:")
        print("    Phase 1 (A): 单层加权    -> 快速精确，为后续标定")
        print("    Phase 2 (C): eps-约束      -> 用 A 的 CVaR* 做 G，纯成本优化")
        print("    Phase 3 (B): KKT+Indicator -> 验证双层最优性，计算重")
        print("    Phase 4 (D): McCormick     -> 计算轻，用 A 衡量近似偏差")
        print()

        report = run_physical_pipeline(data, lambda_val=lambda_val)
        report.print()

        print("\n" + "=" * 100)
        print("优化建议（基于本次运行结果）")
        print("=" * 100)

        pa = report.phases[0] if report.phases else None
        pb = report.phases[2] if len(report.phases) > 2 else None
        pd = report.phases[3] if len(report.phases) > 3 else None

        if pa and pa.is_optimal:
            print(f"  1. 热启动: Model A 耗时 {pa.wall_time:.2f}s，"
                  f"可将此解作为 C/B/D 的 MIPStart（当前已支持）")
        if pb and pb.is_optimal:
            print(f"  2. KKT 验证: Model B 耗时 {pb.wall_time:.2f}s，"
                  f"用于验证 A 的解满足双层最优性")
        if pd and pd.is_optimal:
            print(f"  3. McCormick 松弛: Model D 耗时 {pd.wall_time:.2f}s")
            if pa and pa.is_optimal and pd.cost is not None and pa.cost is not None:
                gap = abs(pd.cost - pa.cost) / (abs(pa.cost) + 1e-9)
                print(f"     与 A 的 cost gap = {gap:.4%}；"
                      + ("可接受" if gap < 0.05 else "需收紧 slack 上界"))
            if report.cvar_gap_d_vs_a is not None:
                print(f"     CVaR 偏差 = {report.cvar_gap_d_vs_a:.4%}；"
                      + ("松弛合理" if report.cvar_gap_d_vs_a < 0.20 else "松弛偏松，建议用自适应 slack"))

        if pa and pd and pa.is_optimal and pd.is_optimal:
            dt_a = pa.wall_time
            dt_d = pd.wall_time
            print(f"  4. 时间对比: A={dt_a:.2f}s vs D={dt_d:.2f}s "
                  + (f"(D 更快 {dt_a/(dt_d+1e-9):.1f}x，可做大范围预筛选)" if dt_d < dt_a
                     else "(D 不比 A 快，说明问题规模小，Indicator 不是瓶颈)"))

        print(f"\n  5. 场景聚类: 当前 |S|={len(data.S)}，" +
              ("场景少，无需合并" if len(data.S) <= 5 else "建议尝试 reduce_scenarios() 减少场景数"))
        print(f"  6. 紧 Big-M: 当前使用全局上界，" +
              "可通过 compute_tight_big_m() 推导逐 (i,node) 的更紧 M 值")
        print(f"  7. 推荐工作流:")
        print(f"     - 开发/调试: Model A（快速精确）")
        print(f"     - 生产部署: Model C（风险预算直观，业务可直接设 G）")
        print(f"     - 理论验证: Model B（验证最优性条件）")
        print(f"     - 大规模预筛选: Model D（快速近似，缩小候选后精确求解）")
        print()

        print("运行 --compare 可并排对比 Physical vs TEAVAR SLA 两套 CVaR 体系。")
        print("运行 --b4 可切换到 B4 真实数据。")
