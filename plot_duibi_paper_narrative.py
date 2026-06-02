#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
论文叙事图（与 ``duibi.build_single_layer_model`` / ``load_b4_joint_data`` 同源求解，非手填数），共 **4** 张 PNG：

1. ``paper_frontier_cost_vs_compute_cvar.png`` — 散点 + 折线：X=Compute CVaR，Y=Total cost（无应力，Hub vs UMCF）；
   在 λ 最接近 ``--annotate-lambda``（默认 50）的 UMCF 点旁标注迁移提示。
2. ``paper_link_cvar_vs_lambda.png`` — log λ vs Link CVaR；默认 λ 含 5000 以展示尾部；
   UMCF 曲线首尾英文注释（``--zh`` 时改为中文）。
3. ``paper_stress_feasibility_bar.png`` — Y 轴为 **可行性得分 0/1**（非成本刻度），左柱不可行、右柱可行；
   最优 **成本** 以柱顶文字标出（避免「左柱看起来像 cost=75」的误读）。
4. ``paper_radar_comparison.png`` — 雷达图：在固定 λ 下对比 Hub radial vs UMCF（成本/链路/算力 CVaR 归一化到 0–100，
   第四轴为应力下是否可解）。

用法::

    python plot_duibi_paper_narrative.py --output-dir figures/paper
    python plot_duibi_paper_narrative.py --zh --lambdas "0.5,5,50,500,5000" --output-dir figures/paper
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

import numpy as np

try:
    import matplotlib.pyplot as plt
except ImportError as e:  # pragma: no cover
    print("需要 matplotlib", file=sys.stderr)
    raise SystemExit(1) from e

from plot_duibi_umcf_sweep import make_dataset, parse_lambdas, solve_model_a


def _finite_xy(x_arr: np.ndarray, y_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x_arr = np.asarray(x_arr, dtype=float)
    y_arr = np.asarray(y_arr, dtype=float)
    m = np.isfinite(x_arr) & np.isfinite(y_arr)
    return x_arr[m], y_arr[m]


def _sweep_line(
    *,
    use_toy: bool,
    stress: bool,
    umcf: bool,
    lambdas: list[float],
    base_path: str,
    topology: str,
    hub: int,
    num_tasks: int,
    demand_row: int,
    demand_downscale: float,
    demand_scale: float,
    k_paths: int,
    umcf_sigma: float,
    umcf_sink_sigma: float | None,
):
    data = make_dataset(
        use_toy=use_toy,
        stress=stress,
        umcf=umcf,
        base_path=base_path,
        topology=topology,
        hub=hub,
        num_tasks=num_tasks,
        demand_row=demand_row,
        demand_downscale=demand_downscale,
        demand_scale=demand_scale,
        k_paths=k_paths,
        umcf_sigma=umcf_sigma,
        umcf_sink_sigma=umcf_sink_sigma,
    )
    xs = np.array(lambdas, dtype=float)
    costs, nc, lc = [], [], []
    for lam in lambdas:
        ok, c, ncv, lcv, _ = solve_model_a(data, lam)
        if ok:
            costs.append(c)
            nc.append(ncv)
            lc.append(lcv)
        else:
            costs.append(np.nan)
            nc.append(np.nan)
            lc.append(np.nan)
    return xs, np.array(costs), np.array(nc), np.array(lc)


def _idx_nearest_lambda(lambdas: list[float], target: float) -> int:
    arr = np.array(lambdas, dtype=float)
    return int(np.argmin(np.abs(arr - target)))


def _score_lower_better(v_hub: float, v_umcf: float) -> tuple[float, float]:
    """两方案同一指标，越小越好 → 映射到 0–100 分（较优者更高）。"""
    lo = min(v_hub, v_umcf)
    hi = max(v_hub, v_umcf)
    span = hi - lo
    if span < 1e-12:
        return 50.0, 50.0
    sh = 100.0 * (hi - v_hub) / span
    su = 100.0 * (hi - v_umcf) / span
    return float(sh), float(su)


def main() -> None:
    ap = argparse.ArgumentParser(description="论文叙事四图：前沿 / 链路λ / 应力可行性 / 雷达")
    ap.add_argument("--toy", action="store_true")
    ap.add_argument("--topology", default="B4")
    ap.add_argument("--hub", type=int, default=0)
    ap.add_argument("--k-paths", type=int, default=6)
    ap.add_argument("--num-tasks", type=int, default=10)
    ap.add_argument("--demand-row", type=int, default=0)
    ap.add_argument("--demand-scale", type=float, default=1.0)
    ap.add_argument("--demand-downscale", type=float, default=2.0)
    ap.add_argument("--lambdas", type=str, default="0.5,5,50,500,5000")
    ap.add_argument("--lambda-feas", type=float, default=50.0, help="图3、图4 所用固定 λ")
    ap.add_argument("--annotate-lambda", type=float, default=50.0, help="图1 前沿上标注「迁移」所参照的 λ")
    ap.add_argument("--umcf-sigma", type=float, default=0.99)
    ap.add_argument("--umcf-sink-sigma", type=float, default=None)
    ap.add_argument("--output-dir", type=str, default="figures/paper")
    ap.add_argument("--zh", action="store_true", help="图2 端点注释使用中文（需系统有中文字体）")
    ap.add_argument("--export-csv", action="store_true", help="将扫参结果写入 output-dir/sweep_model_a.csv")
    args = ap.parse_args()

    lambdas = parse_lambdas(args.lambdas)
    base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    out_dir = os.path.abspath(args.output_dir)
    os.makedirs(out_dir, exist_ok=True)

    common = dict(
        use_toy=args.toy,
        base_path=base_path,
        topology=args.topology,
        hub=args.hub,
        num_tasks=args.num_tasks,
        demand_row=args.demand_row,
        demand_downscale=args.demand_downscale,
        demand_scale=args.demand_scale,
        k_paths=args.k_paths,
        umcf_sigma=args.umcf_sigma,
        umcf_sink_sigma=args.umcf_sink_sigma,
    )

    x_l, c_hub, n_hub, l_hub = _sweep_line(stress=False, umcf=False, lambdas=lambdas, **common)
    _, c_um, n_um, l_um = _sweep_line(stress=False, umcf=True, lambdas=lambdas, **common)

    if args.export_csv:
        csv_path = os.path.join(out_dir, "sweep_model_a.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["lambda", "hub_cost", "hub_node_cvar", "hub_link_cvar", "umcf_cost", "umcf_node_cvar", "umcf_link_cvar"])
            for i, lam in enumerate(lambdas):
                w.writerow([lam, c_hub[i], n_hub[i], l_hub[i], c_um[i], n_um[i], l_um[i]])
        print("CSV:", csv_path)

    # ---------- 图1：前沿（Compute CVaR, Cost）----------
    fig, ax = plt.subplots(figsize=(5.0, 3.9))
    fx, fy = _finite_xy(n_hub, c_hub)
    if len(fx) > 0:
        ax.scatter(fx, fy, color="#1f77b4", s=36, zorder=3, label="Hub radial (no UMCF)")
        ax.plot(fx, fy, "-", color="#1f77b4", linewidth=1.5, zorder=2)
    fx2, fy2 = _finite_xy(n_um, c_um)
    if len(fx2) > 0:
        ax.scatter(fx2, fy2, color="#2ca02c", s=36, zorder=3, label="UMCF (virtual nodes)")
        ax.plot(fx2, fy2, "-", color="#2ca02c", linewidth=1.5, zorder=2)

    ia = _idx_nearest_lambda(lambdas, args.annotate_lambda)
    if np.isfinite(n_um[ia]) and np.isfinite(c_um[ia]):
        ax.annotate(
            f"λ≈{lambdas[ia]:g}\nplacement shift" if not args.zh else f"λ≈{lambdas[ia]:g}\n触发迁移",
            xy=(float(n_um[ia]), float(c_um[ia])),
            xytext=(18, 22),
            textcoords="offset points",
            fontsize=8,
            arrowprops=dict(arrowstyle="->", color="#333333", lw=0.9),
        )

    ax.set_xlabel(r"Compute utilization CVaR (—, $\beta_N{=}0.95$)", fontsize=9)
    ax.set_ylabel("Total cost (Model A optimal)", fontsize=9)
    ax.set_title("Pareto trace: cost vs. compute CVaR (no stress)", fontsize=10)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best", fontsize=8)
    fig.subplots_adjust(left=0.12, right=0.97, top=0.88, bottom=0.14)
    p1 = os.path.join(out_dir, "paper_frontier_cost_vs_compute_cvar.png")
    fig.savefig(p1, dpi=200, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)

    # ---------- 图2：Link CVaR vs λ ----------
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    xh, yh = _finite_xy(x_l, l_hub)
    xu, yu = _finite_xy(x_l, l_um)
    if len(xh) > 0:
        ax.plot(xh, yh, "o-", color="#1f77b4", linewidth=1.8, markersize=6, label="Hub radial (no UMCF)")
    if len(xu) > 0:
        ax.plot(xu, yu, "s-", color="#2ca02c", linewidth=1.8, markersize=6, label="UMCF (virtual nodes)")
    ax.set_xscale("log")
    ax.set_xlabel(r"Risk weight $\lambda$ (log scale)", fontsize=9)
    ax.set_ylabel(r"Link utilization CVaR (—, $\beta_L{=}0.95$)", fontsize=9)
    ax.set_title("Link CVaR sensitivity to λ (no stress)", fontsize=10)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best", fontsize=8)

    if len(xu) >= 2 and len(yu) >= 2:
        i0, i1 = 0, len(xu) - 1
        if args.zh:
            t0, t1 = "虚拟边风险基底\n(σ≈0.99)", f"λ 大时趋于稳定\n(λ={xu[i1]:g})"
        else:
            t0, t1 = "Virtual-edge\nrisk floor (σ≈0.99)", f"Tail stable\n(λ={xu[i1]:g})"
        ax.annotate(t0, xy=(xu[i0], yu[i0]), xytext=(10, 12), textcoords="offset points", fontsize=7, color="#2ca02c")
        ax.annotate(t1, xy=(xu[i1], yu[i1]), xytext=(-35, -18), textcoords="offset points", fontsize=7, color="#2ca02c")

    fig.subplots_adjust(left=0.12, right=0.97, top=0.88, bottom=0.14)
    p2 = os.path.join(out_dir, "paper_link_cvar_vs_lambda.png")
    fig.savefig(p2, dpi=200, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)

    # ---------- 图3：应力可行性（Y=得分，成本仅文字）----------
    lam = float(args.lambda_feas)
    data_st_hub = make_dataset(stress=True, umcf=False, **common)
    data_st_um = make_dataset(stress=True, umcf=True, **common)
    ok_h, c_h, _, _, st_h = solve_model_a(data_st_hub, lam)
    ok_u, c_u, _, _, st_u = solve_model_a(data_st_um, lam)

    fig, ax = plt.subplots(figsize=(4.6, 3.5))
    xpos = [0, 1]
    w = 0.55
    ax.set_xlim(-0.65, 1.65)
    ax.set_ylim(0.0, 1.15)
    ax.set_ylabel("Feasibility score (1 = optimal MILP exists)", fontsize=9)
    ax.set_xticks(xpos)
    ax.set_xticklabels(["Hub radial\n+ stress s₁\n(no UMCF)", "UMCF\n+ stress s₁"], fontsize=8)
    ax.axhline(0, color="#999", linewidth=0.8)

    if ok_h:
        ax.bar(0, 1.0, width=w, color="#1f77b4", edgecolor="black", linewidth=0.6)
        ax.text(0, 1.04, f"cost={c_h:.2f}", ha="center", va="bottom", fontsize=8)
    else:
        ax.bar(0, 0.0, width=w, color="#ffcccc", edgecolor="#b22222", linewidth=1.2, hatch="///")
        ax.plot(0, 0.52, marker="x", color="#b22222", markersize=22, markeredgewidth=2.2, linestyle="None")
        ax.text(0, 0.72, "INFEASIBLE", ha="center", fontsize=11, color="#b22222", weight="bold")
        ax.text(0, 0.58, f"(status {st_h})", ha="center", fontsize=7, color="#555")

    if ok_u:
        ax.bar(1, 1.0, width=w, color="#2ca02c", edgecolor="black", linewidth=0.6)
        ax.text(1, 1.04, f"cost={c_u:.2f}", ha="center", va="bottom", fontsize=8)
        ax.text(1, 0.88, "Survived", ha="center", fontsize=9, color="#1a5c1a", weight="bold")
    else:
        ax.bar(1, 0.0, width=w, color="#ffcccc", edgecolor="black", linewidth=0.6)
        ax.text(1, 0.72, "INFEASIBLE", ha="center", fontsize=11, color="#b22222", weight="bold")

    ax.set_title(f"Network resilience under hub outage (λ={lam:g}, Model A)", fontsize=10)
    ax.grid(True, axis="y", alpha=0.35)
    fig.subplots_adjust(left=0.14, right=0.96, top=0.86, bottom=0.28)
    p3 = os.path.join(out_dir, "paper_stress_feasibility_bar.png")
    fig.savefig(p3, dpi=200, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)

    # ---------- 图4：雷达（固定 λ，无应力 CVaR + 应力可行性）----------
    lam_r = float(args.lambda_feas)
    d_hub = make_dataset(stress=False, umcf=False, **common)
    d_um = make_dataset(stress=False, umcf=True, **common)
    ok1, ch, nh, lh, _ = solve_model_a(d_hub, lam_r)
    ok2, cu, nu, lu, _ = solve_model_a(d_um, lam_r)
    ok_h_st, _, _, _, _ = solve_model_a(data_st_hub, lam_r)
    ok_u_st, _, _, _, _ = solve_model_a(data_st_um, lam_r)

    if ok1 and ok2:
        sc, scc = _score_lower_better(ch, cu)
        sl, slc = _score_lower_better(lh, lu)
        sn, snc = _score_lower_better(nh, nu)
    else:
        sc = scc = sl = slc = sn = snc = 50.0
    surv_h = 100.0 if ok_h_st else 0.0
    surv_u = 100.0 if ok_u_st else 0.0

    cats = ["Cost\n(better ↑)", "Link CVaR\n(better ↑)", "Compute CVaR\n(better ↑)", "Stress\nsurvival"]
    N = len(cats)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False)
    angles = np.concatenate([angles, angles[:1]])
    vals_h = np.array([sc, sl, sn, surv_h], dtype=float)
    vals_u = np.array([scc, slc, snc, surv_u], dtype=float)
    vals_h = np.concatenate([vals_h, vals_h[:1]])
    vals_u = np.concatenate([vals_u, vals_u[:1]])

    fig, ax = plt.subplots(figsize=(4.8, 4.8), subplot_kw=dict(projection="polar"))
    ax.plot(angles, vals_h, "o-", color="#1f77b4", linewidth=1.6, label="Hub radial")
    ax.fill(angles, vals_h, color="#1f77b4", alpha=0.12)
    ax.plot(angles, vals_u, "s-", color="#2ca02c", linewidth=1.6, label="UMCF")
    ax.fill(angles, vals_u, color="#2ca02c", alpha=0.12)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(cats, fontsize=8)
    ax.set_ylim(0, 100)
    ax.set_title(f"Normalized scores @ λ={lam_r:g} (0–100, higher better)", fontsize=9, pad=14)
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1), fontsize=8)
    fig.subplots_adjust(left=0.05, right=0.88, top=0.9, bottom=0.05)
    p4 = os.path.join(out_dir, "paper_radar_comparison.png")
    fig.savefig(p4, dpi=200, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)

    print("已写入:")
    for p in (p1, p2, p3, p4):
        print(" ", p)
    print(f"校验: λ={lam} 应力 hub 可行={ok_h}, UMCF 可行={ok_u} | 前沿/雷达用无应力扫参")


if __name__ == "__main__":
    main()
