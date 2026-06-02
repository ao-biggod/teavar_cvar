#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对 duibi Model A 在不同「应力 × UMCF」组合下扫 λ，绘制成本与双 CVaR 对比图。

- 仅连接 **Gurobi 最优且数值有限** 的 (λ, 指标) 点，避免不可行系列被误画成「贴着基线的假曲线」。
- 可选 ``--paper-legend``：图例改为论文友好短名；成本子图对「应力、无 UMCF」全不可行时标注 INFEASIBLE。

默认 B4；``--toy`` 时玩具数据在应力下会调用 ``stress_hub_outgoing_s1``（与 ``duibi.py --toy`` 仅打印提示不同，见模块说明）。

用法::

    python plot_duibi_umcf_sweep.py --output figures/b4_umcf_sweep.png
    python plot_duibi_umcf_sweep.py --paper-legend --output figures/b4_umcf_sweep.png
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

try:
    import matplotlib.pyplot as plt
except ImportError as e:  # pragma: no cover
    print("需要 matplotlib：pip install matplotlib", file=sys.stderr)
    raise SystemExit(1) from e

from gurobipy import GRB


def parse_lambdas(s: str) -> list[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def make_dataset(
    *,
    use_toy: bool,
    stress: bool,
    umcf: bool,
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
    if use_toy:
        from duibi import UltraComplexData
        from b4_joint_data import attach_umcf_to_data_object, stress_hub_outgoing_s1

        data = UltraComplexData()
        if umcf:
            attach_umcf_to_data_object(data, umcf_sigma, umcf_sink_sigma)
        if stress:
            stress_hub_outgoing_s1(data, int(getattr(data, "hub", 0)))
        return data

    from b4_joint_data import load_b4_joint_data

    return load_b4_joint_data(
        base_path=base_path,
        topology_name=topology,
        hub_index=hub,
        num_tasks=num_tasks,
        demand_row=demand_row,
        demand_downscale=demand_downscale,
        demand_scale=demand_scale,
        k_paths=k_paths,
        stress_zero_s1=stress,
        virtual_source=False,
        umcf_virtual_nodes=umcf,
        umcf_access_sigma=umcf_sigma,
        umcf_sink_access_sigma=umcf_sink_sigma,
    )


def solve_model_a(data, lambda_val: float):
    from duibi import build_single_layer_model

    m, cost, n_cv, l_cv, *_ = build_single_layer_model(data, lambda_val)
    ok = m.status == GRB.OPTIMAL and cost is not None and n_cv is not None and l_cv is not None
    if not ok:
        return False, np.nan, np.nan, np.nan, int(m.status)
    return True, float(cost), float(n_cv), float(l_cv), int(m.status)


def _finite_xy(x_arr: np.ndarray, y_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """保留 (x,y) 同时有限的点，避免前沿图等场景下 x/y 错配。"""
    x_arr = np.asarray(x_arr, dtype=float)
    y_arr = np.asarray(y_arr, dtype=float)
    m = np.isfinite(x_arr) & np.isfinite(y_arr)
    return x_arr[m], y_arr[m]


def _paper_legend_entry(ci: int, technical: str) -> str:
    """与 conditions 行顺序一致：0 基线 1 应力无UMCF 2 仅UMCF 3 UMCF+应力"""
    friendly = [
        "Hub radial (no failure, no UMCF)",
        "Hub radial + stress s₁ (no UMCF)",
        "UMCF virtual ingress/egress (no failure)",
        "UMCF + stress s₁",
    ]
    return friendly[ci] if ci < len(friendly) else technical.replace("\n", " ")


def main() -> None:
    p = argparse.ArgumentParser(description="绘制 duibi Model A：UMCF × 应力 × λ 对比图")
    p.add_argument("--toy", action="store_true", help="使用 UltraComplexData（默认 B4）")
    p.add_argument("--topology", type=str, default="B4")
    p.add_argument("--hub", type=int, default=0)
    p.add_argument("--k-paths", type=int, default=6)
    p.add_argument("--num-tasks", type=int, default=10)
    p.add_argument("--demand-row", type=int, default=0)
    p.add_argument("--demand-scale", type=float, default=1.0)
    p.add_argument("--demand-downscale", type=float, default=2.0)
    p.add_argument(
        "--lambdas",
        type=str,
        default="0.5,5,50,500",
        help='逗号分隔 λ 列表，例如 "0.5,5,50,500"',
    )
    p.add_argument("--umcf-sigma", type=float, default=0.99)
    p.add_argument("--umcf-sink-sigma", type=float, default=None)
    p.add_argument(
        "--output",
        type=str,
        default="figures/duibi_umcf_sweep.png",
        help="输出 PNG 路径",
    )
    p.add_argument(
        "--paper-legend",
        action="store_true",
        help="图例改为论文友好英文短名（可配合正文自行翻译）",
    )
    args = p.parse_args()

    lambdas = parse_lambdas(args.lambdas)
    base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    conditions: list[tuple[str, bool, bool]] = [
        ("baseline\n(no stress, no UMCF)", False, False),
        ("+stress s1\n(hub out cut)", True, False),
        ("+UMCF\n(no stress)", False, True),
        ("+UMCF + stress", True, True),
    ]

    costs = np.full((len(conditions), len(lambdas)), np.nan)
    link_cv = np.full_like(costs, np.nan)
    node_cv = np.full_like(costs, np.nan)
    feasible = np.zeros((len(conditions), len(lambdas)), dtype=bool)
    status_tab = np.zeros((len(conditions), len(lambdas)), dtype=np.int32)

    for ci, (label, stress, umcf) in enumerate(conditions):
        data = make_dataset(
            use_toy=args.toy,
            stress=stress,
            umcf=umcf,
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
        for li, lam in enumerate(lambdas):
            ok, c, nc, lc, st = solve_model_a(data, lam)
            feasible[ci, li] = ok
            status_tab[ci, li] = st
            if ok:
                costs[ci, li] = c
                link_cv[ci, li] = lc
                node_cv[ci, li] = nc

    out_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    x = np.array(lambdas, dtype=float)
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 3.25), sharex=False)
    title = (
        "Model A | toy data"
        if args.toy
        else f"Model A | {args.topology} hub={args.hub} k={args.k_paths}"
    )
    fig.suptitle(title, fontsize=10, y=0.98)

    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
    stress_no_umcf_ci = 1

    for ci, (label, _, _) in enumerate(conditions):
        leg = _paper_legend_entry(ci, label) if args.paper_legend else label.replace("\n", " ")
        for axi, ymat, mk in zip(
            axes,
            (costs, link_cv, node_cv),
            ("o", "s", "^"),
        ):
            fx, fy = _finite_xy(x, ymat[ci])
            if len(fx) > 0:
                # 图例只放在第一个子图，最后统一挪到底部，避免子图内大块空白
                kw = dict(marker=mk, color=colors[ci % len(colors)], linewidth=1.6, markersize=5)
                if axi is axes[0]:
                    kw["label"] = leg
                axi.plot(fx, fy, **kw)
            # 不在无可行点时画线，避免与「全 NaN 仍画一条线」的误解

    # 成本图：应力且无 UMCF 全不可行 → 显式标注
    if not feasible[stress_no_umcf_ci].any():
        ax0 = axes[0]
        ref = np.nanmax(costs[np.setdiff1d(np.arange(len(conditions)), [stress_no_umcf_ci]), :])
        y_anno = float(ref) * 0.55 if np.isfinite(ref) else 400.0
        x_anno = float(np.sqrt(x.min() * x.max()))
        ax0.text(
            x_anno,
            y_anno,
            "INFEASIBLE\n(hub+stress)",
            fontsize=8,
            color="#b22222",
            ha="center",
            va="center",
            weight="bold",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="#b22222", linewidth=1.0),
        )

    for axi, ymat in zip(axes, (costs, link_cv, node_cv)):
        axi.set_xlabel(r"$\lambda$", fontsize=9)
        axi.set_xscale("log")
        axi.grid(True, alpha=0.35)
        axi.tick_params(labelsize=8)
        axi.margins(x=0.06, y=0.08)
        finite = ymat[np.isfinite(ymat)]
        if finite.size:
            lo, hi = float(np.min(finite)), float(np.max(finite))
            pad = max((hi - lo) * 0.08, 1e-9)
            axi.set_ylim(lo - pad, hi + pad)

    axes[0].set_title("Cost", fontsize=9)
    axes[0].set_ylabel("Total cost", fontsize=9)

    axes[1].set_title("Link CVaR", fontsize=9)
    axes[1].set_ylabel(r"Link CVaR ($\beta_L{=}0.95$)", fontsize=9)

    axes[2].set_title("Compute CVaR", fontsize=9)
    axes[2].set_ylabel(r"Compute CVaR ($\beta_N{=}0.95$)", fontsize=9)

    h, lab = axes[0].get_legend_handles_labels()
    if h:
        fig.legend(
            h,
            lab,
            loc="lower center",
            ncol=2,
            fontsize=6.5,
            frameon=True,
            bbox_to_anchor=(0.5, -0.02),
            columnspacing=0.9,
            handletextpad=0.5,
        )
    fig.subplots_adjust(left=0.07, right=0.99, wspace=0.26, top=0.86, bottom=0.34)
    fig.savefig(out_path, dpi=180, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)

    print(f"已保存: {out_path}")
    print("可行性 (行=条件, 列=λ):")
    for ci, (label, _, _) in enumerate(conditions):
        row = " | ".join(
            "OK" if feasible[ci, li] else f"X(status={status_tab[ci, li]})" for li in range(len(lambdas))
        )
        print(f"  [{ci}] {label.replace(chr(10), ' / ')} :: {row}")


if __name__ == "__main__":
    main()
