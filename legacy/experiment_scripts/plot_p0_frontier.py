#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P0 §7 主图：CVaR^SLA × CVaR^sf 前沿散点（仅 OPTIMAL 点），颜色表示 cost。

用法：
  python plot_p0_frontier.py \\
    --csv results/p0_gamma_frontier_b4_tasks8_grid5.csv \\
    --output results/fig_p0_frontier_b4_tasks8.png \\
    --pdf results/fig_p0_frontier_b4_tasks8.pdf
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

try:
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
except ImportError as e:
    print("需要 matplotlib: pip install matplotlib", file=sys.stderr)
    raise SystemExit(1) from e


def _load_optimal_points(csv_path: Path) -> list[dict]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    points = []
    for r in rows:
        st = str(r.get("status", "")).strip().upper()
        if st not in ("OPTIMAL", "2", "OPT"):
            continue
        try:
            sla = float(r["cvar_sla"])
            sf = float(r["cvar_sf"])
            cost = float(r["cost"])
        except (KeyError, TypeError, ValueError):
            continue
        points.append({"cvar_sla": sla, "cvar_sf": sf, "cost": cost})
    return points


def _title_from_row(csv_path: Path, points: list[dict]) -> str:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        meta = next(reader, None) or {}
    eta = meta.get("eta", "1.3")
    sigma = meta.get("scenario_s1_link_sigma", "0.80")
    n_tasks = meta.get("num_tasks", "8")
    try:
        sigma_f = float(sigma)
        sigma_s = f"{sigma_f:.2f}"
    except ValueError:
        sigma_s = str(sigma)
    return (
        f"B4, |I|={n_tasks}, per-task OD, "
        f"$\\eta$={eta}, $\\sigma$={sigma_s}"
    )


def plot_frontier(
    points: list[dict],
    *,
    title: str,
    output_png: Path,
    output_pdf: Path | None,
) -> None:
    if not points:
        raise ValueError("No OPTIMAL points to plot")

    sla = [p["cvar_sla"] for p in points]
    sf = [p["cvar_sf"] for p in points]
    cost = [p["cost"] for p in points]

    fig, ax = plt.subplots(figsize=(7.0, 5.5))
    norm = mcolors.Normalize(vmin=min(cost), vmax=max(cost))
    sc = ax.scatter(
        sla,
        sf,
        c=cost,
        cmap="viridis",
        norm=norm,
        s=72,
        edgecolors="white",
        linewidths=0.6,
        zorder=3,
    )
    cbar = fig.colorbar(sc, ax=ax, pad=0.02)
    cbar.set_label("Total cost")

    ax.set_xlabel(r"CVaR$^{\mathrm{SLA}}$")
    ax.set_ylabel(r"CVaR$^{\mathrm{sf}}$")
    ax.set_title(title)
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.set_xlim(min(sla) - 0.005, max(sla) + 0.005)
    ax.set_ylim(min(sf) - 0.002, max(sf) + 0.002)

    fig.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=200, bbox_inches="tight")
    if output_pdf is not None:
        fig.savefig(output_pdf, bbox_inches="tight")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Plot P0 CVaR frontier (§7 main figure)")
    ap.add_argument("--csv", type=str, required=True, help="Frontier results CSV")
    ap.add_argument("--output", type=str, required=True, help="Output PNG path")
    ap.add_argument("--pdf", type=str, default=None, help="Optional output PDF path")
    ap.add_argument("--title", type=str, default=None, help="Override plot title")
    args = ap.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        return 2

    points = _load_optimal_points(csv_path)
    if not points:
        print(f"ERROR: no OPTIMAL rows in {csv_path}", file=sys.stderr)
        return 2

    title = args.title or _title_from_row(csv_path, points)
    output_png = Path(args.output)
    output_pdf = Path(args.pdf) if args.pdf else None

    plot_frontier(points, title=title, output_png=output_png, output_pdf=output_pdf)
    print(f"Wrote {output_png} ({len(points)} OPTIMAL points)")
    if output_pdf is not None:
        print(f"Wrote {output_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
