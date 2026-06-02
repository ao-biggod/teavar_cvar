#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P0 验收：读取 Γ 网格 CSV，判定 V-1~V-3（V-4 提示运行 smoke test）。

用法：
  python scripts/p0_acceptance.py --csv results/p0_gamma_frontier.csv
  python scripts/p0_acceptance.py --csv path.csv --cost-band-pct 5 --min-distinct-points 3
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


REQUIRED_COLUMNS = (
    "gamma_sla",
    "gamma_sf",
    "status",
    "cvar_sla",
    "cvar_sf",
    "cost",
)

COLUMN_ALIASES = {
    "cvar_sla": ("cvar_sla", "sla_cvar", "CVaR_SLA", "cvar_sla_value"),
    "cvar_sf": ("cvar_sf", "sf_cvar", "CVaR_sf", "compute_sf_cvar"),
    "cost": ("cost", "objective", "total_cost"),
    "status": ("status", "model_status"),
    "gamma_sla": ("gamma_sla", "Gamma_sla", "g_sla"),
    "gamma_sf": ("gamma_sf", "Gamma_sf", "g_sf"),
}


def _resolve_column(fieldnames: list[str], logical: str) -> str:
    aliases = COLUMN_ALIASES.get(logical, (logical,))
    lower_map = {f.lower(): f for f in fieldnames}
    for a in aliases:
        if a in fieldnames:
            return a
        if a.lower() in lower_map:
            return lower_map[a.lower()]
    raise KeyError(logical)


def _load_rows(csv_path: Path) -> tuple[list[dict], dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {csv_path}")
        colmap = {}
        for logical in REQUIRED_COLUMNS:
            colmap[logical] = _resolve_column(list(reader.fieldnames), logical)
        rows = list(reader)
    return rows, colmap


def _parse_float(val, default=None):
    if val is None or str(val).strip() == "":
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _optimal_rows(rows: list[dict], colmap: dict[str, str]) -> list[dict]:
    out = []
    for r in rows:
        st = str(r.get(colmap["status"], "")).strip().upper()
        if st not in ("2", "OPTIMAL", "OPT"):
            continue
        sla = _parse_float(r.get(colmap["cvar_sla"]))
        sf = _parse_float(r.get(colmap["cvar_sf"]))
        cost = _parse_float(r.get(colmap["cost"]))
        if sla is None or sf is None or cost is None:
            continue
        out.append({"cvar_sla": sla, "cvar_sf": sf, "cost": cost, "raw": r})
    return out


def check_v1(points: list[dict]) -> tuple[bool, str]:
    slas = [p["cvar_sla"] for p in points]
    in_range = [v for v in slas if 0.01 < v < 0.95]
    distinct = len(set(round(v, 6) for v in slas))
    if len(in_range) == 0:
        return False, f"V-1 FAIL: no CVaR^SLA in (0.01, 0.95); values={slas[:8]}"
    if distinct < 2:
        return False, f"V-1 FAIL: CVaR^SLA has <2 distinct values ({distinct})"
    return True, f"V-1 PASS: SLA in range, {distinct} distinct values"


def check_v2(points: list[dict]) -> tuple[bool, str]:
    sf_vals = [p["cvar_sf"] for p in points]
    if not any(v > 0.01 for v in sf_vals):
        return False, f"V-2 FAIL: no CVaR^sf > 0.01; values={sf_vals[:8]}"
    anticorr = False
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            a, b = points[i], points[j]
            ds = b["cvar_sla"] - a["cvar_sla"]
            df = b["cvar_sf"] - a["cvar_sf"]
            if abs(ds) > 1e-6 and abs(df) > 1e-6 and ds * df < 0:
                anticorr = True
                break
        if anticorr:
            break
    if not anticorr:
        return False, "V-2 FAIL: CVaR^sf>0 but SLA/sf do not move in opposite directions"
    return True, "V-2 PASS: sf>0.01 and opposite-direction pair exists"


def check_v3(
    points: list[dict],
    cost_band_pct: float,
    min_distinct_points: int,
) -> tuple[bool, str]:
    if len(points) < min_distinct_points:
        return False, f"V-3 FAIL: only {len(points)} optimal rows (need ≥{min_distinct_points})"
    costs = [p["cost"] for p in points]
    med = sorted(costs)[len(costs) // 2]
    lo = med * (1.0 - cost_band_pct / 100.0)
    hi = med * (1.0 + cost_band_pct / 100.0)
    in_band = [p for p in points if lo <= p["cost"] <= hi]
    pairs = set((round(p["cvar_sla"], 6), round(p["cvar_sf"], 6)) for p in in_band)
    if len(pairs) < min_distinct_points:
        return False, (
            f"V-3 FAIL: cost band [{lo:.2f},{hi:.2f}] has {len(pairs)} distinct "
            f"(SLA,sf) pairs (need ≥{min_distinct_points})"
        )
    return True, f"V-3 PASS: {len(pairs)} distinct (SLA,sf) in cost band"


def run_acceptance(
    csv_path: Path,
    *,
    cost_band_pct: float = 5.0,
    min_distinct_points: int = 3,
) -> int:
    rows, colmap = _load_rows(csv_path)
    points = _optimal_rows(rows, colmap)
    print(f"CSV: {csv_path} | rows={len(rows)} | optimal={len(points)}")
    print(f"Columns: {colmap}")

    results = [
        check_v1(points),
        check_v2(points),
        check_v3(points, cost_band_pct, min_distinct_points),
    ]
    all_ok = True
    for ok, msg in results:
        print(msg)
        all_ok = all_ok and ok

    print("V-4 NOTE: also run `python -m unittest tests.test_smoke tests.test_per_task_od -v`")
    if all_ok:
        print("OVERALL: PASS")
        return 0
    print("OVERALL: FAIL")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P0 acceptance (V-1~V-3) on frontier CSV")
    ap.add_argument("--csv", type=str, required=True, help="Path to frontier results CSV")
    ap.add_argument("--cost-band-pct", type=float, default=5.0)
    ap.add_argument("--min-distinct-points", type=int, default=3)
    args = ap.parse_args(argv)
    path = Path(args.csv)
    if not path.is_file():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        print(f"Required columns (or aliases): {REQUIRED_COLUMNS}", file=sys.stderr)
        return 2
    try:
        return run_acceptance(
            path,
            cost_band_pct=args.cost_band_pct,
            min_distinct_points=args.min_distinct_points,
        )
    except KeyError as e:
        print(f"ERROR: missing column for {e.args[0]!r}", file=sys.stderr)
        print(f"Required: {REQUIRED_COLUMNS}", file=sys.stderr)
        print(f"Aliases: {COLUMN_ALIASES}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
