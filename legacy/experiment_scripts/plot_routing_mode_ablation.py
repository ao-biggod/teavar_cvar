#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
routing_mode 消融对比图：CVaR^SLA × CVaR^sf，按 routing_mode 分色。

用法：
  python plot_routing_mode_ablation.py \\
    --csv results/routing_mode_ablation_tasks4_points.csv \\
    --output results/fig_routing_mode_ablation_tasks4.png \\
    --pdf results/fig_routing_mode_ablation_tasks4.pdf
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

try:
    import matplotlib.pyplot as plt
except ImportError as e:
    print("需要 matplotlib", file=sys.stderr)
    raise SystemExit(1) from e

MODE_COLORS = {
    "per_task_od": "#1f77b4",
    "umcf_global": "#ff7f0e",
    "umcf_per_task": "#2ca02c",
}
MODE_LABELS = {
    "per_task_od": "per-task OD",
    "umcf_global": "UMCF global",
    "umcf_per_task": "UMCF per-task",
}


def load_optimal_by_mode(csv_path: Path) -> dict[str, list[dict]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_mode: dict[str, list[dict]] = {}
    for r in rows:
        st = str(r.get("status", "")).strip().upper()
        if st not in ("OPTIMAL", "2", "OPT"):
            continue
        mode = r.get("routing_mode", "unknown")
        try:
            by_mode.setdefault(mode, []).append(
                {
                    "cvar_sla": float(r["cvar_sla"]),
                    "cvar_sf": float(r["cvar_sf"]),
                    "cost": float(r["cost"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return by_mode


def _title_from_csv(csv_path: Path, by_mode: dict) -> str:
    with csv_path.open(newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f), {})
    n_tasks = row.get("num_tasks", "?")
    eta = row.get("eta", "1.3")
    sigma = row.get("scenario_s1_link_sigma", "0.80")
    try:
        sigma_s = f"{float(sigma):.2f}"
    except ValueError:
        sigma_s = str(sigma)
    grid_n = max(len(v) for v in by_mode.values()) if by_mode else 0
    grid_side = int(grid_n**0.5) if grid_n else 3
    return (
        f"B4, |I|={n_tasks}, $\\Gamma$ {grid_side}$\\times${grid_side}, "
        f"$\\eta$={eta}, $\\sigma$={sigma_s}"
    )


def plot_ablation(
    by_mode: dict[str, list[dict]],
    *,
    title: str,
    output_png: Path,
    output_pdf: Path | None,
) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    for mode, points in sorted(by_mode.items()):
        if not points:
            continue
        sla = [p["cvar_sla"] for p in points]
        sf = [p["cvar_sf"] for p in points]
        ax.scatter(
            sla,
            sf,
            c=MODE_COLORS.get(mode, "#888888"),
            label=MODE_LABELS.get(mode, mode),
            s=64,
            alpha=0.85,
            edgecolors="white",
            linewidths=0.5,
        )
    ax.set_xlabel(r"CVaR$^{\mathrm{SLA}}$")
    ax.set_ylabel(r"CVaR$^{\mathrm{sf}}$")
    ax.set_title(title)
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.legend(loc="best", framealpha=0.9)
    fig.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=200, bbox_inches="tight")
    if output_pdf is not None:
        fig.savefig(output_pdf, bbox_inches="tight")
    plt.close(fig)


def resolve_points_csv(csv_arg: Path) -> Path:
    if csv_arg.is_file():
        if csv_arg.stem.endswith("_points") or "routing_mode" in csv_arg.read_text(
            encoding="utf-8", errors="ignore"
        )[:500]:
            return csv_arg
    candidate = csv_arg.with_name(csv_arg.stem + "_points.csv")
    if candidate.is_file():
        return candidate
    return csv_arg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Plot routing_mode ablation")
    ap.add_argument("--csv", required=True, help="Summary or *_points.csv")
    ap.add_argument("--output", required=True, help="Output PNG")
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--title", default=None)
    args = ap.parse_args(argv)

    csv_path = resolve_points_csv(Path(args.csv))
    if not csv_path.is_file():
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        return 2

    by_mode = load_optimal_by_mode(csv_path)
    if not any(by_mode.values()):
        print(f"ERROR: no OPTIMAL rows in {csv_path}", file=sys.stderr)
        return 2

    title = args.title or _title_from_csv(csv_path, by_mode)
    out_png = Path(args.output)
    out_pdf = Path(args.pdf) if args.pdf else None
    plot_ablation(by_mode, title=title, output_png=out_png, output_pdf=out_pdf)
    print(f"Wrote {out_png}")
    if out_pdf:
        print(f"Wrote {out_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
