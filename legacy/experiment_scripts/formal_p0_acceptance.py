#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Formal P0 acceptance (Phase B+++): Pareto-filtered frontier validation.

V-1: posthoc SLA >= 2 tiers AND posthoc SF >= 2 tiers (non-dominated triples).
V-2: non-dominated distinct triples >= 3.
V-3: cost vs SLA trade-off on non-dominated triples.
V-4: cost vs SF trade-off on non-dominated triples.
V-5: SLA vs SF opposite-direction pair on non-dominated triples.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pareto_frontier import analyze_pareto_rows, has_tradeoff


def _parse_float(val, default=None):
    if val is None or str(val).strip() == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _resolve_column(fieldnames: list[str], *candidates: str) -> str | None:
    lower = {f.lower(): f for f in fieldnames}
    for c in candidates:
        if c in fieldnames:
            return c
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def _prepare_rows(csv_path: Path) -> tuple[list[dict], dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {csv_path}")
        fields = list(reader.fieldnames)
        colmap = {
            "status": _resolve_column(fields, "status", "solver_status") or "status",
            "cost": _resolve_column(fields, "monetary_cost", "cost") or "cost",
            "posthoc_sla": _resolve_column(fields, "posthoc_cvar_sla", "reported_cvar_sla")
            or "posthoc_cvar_sla",
            "posthoc_sf": _resolve_column(fields, "posthoc_cvar_sf", "reported_cvar_sf")
            or "posthoc_cvar_sf",
            "gamma_sla": _resolve_column(fields, "gamma_sla") or "gamma_sla",
            "gamma_sf": _resolve_column(fields, "gamma_sf") or "gamma_sf",
        }
        rows = list(reader)

    normalized: list[dict] = []
    for r in rows:
        nr = dict(r)
        nr["status"] = r.get(colmap["status"], "")
        nr["monetary_cost"] = r.get(colmap["cost"], "")
        nr["posthoc_cvar_sla"] = r.get(colmap["posthoc_sla"], "")
        nr["posthoc_cvar_sf"] = r.get(colmap["posthoc_sf"], "")
        normalized.append(nr)
    return normalized, colmap


def check_v1_nd(nd_triples_points: list[dict]) -> tuple[bool, str]:
    slas = [_parse_float(p.get("posthoc_cvar_sla")) for p in nd_triples_points]
    sfs = [_parse_float(p.get("posthoc_cvar_sf")) for p in nd_triples_points]
    slas = [x for x in slas if x is not None]
    sfs = [x for x in sfs if x is not None]
    distinct_sla = len(set(round(v, 4) for v in slas))
    distinct_sf = len(set(round(v, 4) for v in sfs))
    if distinct_sla < 2:
        return False, f"V-1 FAIL: posthoc SLA tiers={distinct_sla} (need >=2)"
    if distinct_sf < 2:
        return False, f"V-1 FAIL: posthoc SF tiers={distinct_sf} (need >=2)"
    return True, f"V-1 PASS: posthoc SLA tiers={distinct_sla}, SF tiers={distinct_sf}"


def check_v2(analysis) -> tuple[bool, str]:
    n = analysis.non_dominated_distinct_triples_count
    if n < 3:
        return False, f"V-2 FAIL: non-dominated distinct triples={n} (need >=3)"
    return True, f"V-2 PASS: non-dominated distinct triples={n}"


def check_v3(nd_points: list[dict]) -> tuple[bool, str]:
    ok = has_tradeoff(nd_points, "monetary_cost", "posthoc_cvar_sla")
    if not ok:
        return False, "V-3 FAIL: no cost vs posthoc SLA trade-off on non-dominated triples"
    return True, "V-3 PASS: cost vs posthoc SLA trade-off exists"


def check_v4(nd_points: list[dict]) -> tuple[bool, str]:
    ok = has_tradeoff(nd_points, "monetary_cost", "posthoc_cvar_sf")
    if not ok:
        return False, "V-4 FAIL: no cost vs posthoc SF trade-off on non-dominated triples"
    return True, "V-4 PASS: cost vs posthoc SF trade-off exists"


def check_v5(nd_points: list[dict]) -> tuple[bool, str]:
    ok = has_tradeoff(nd_points, "posthoc_cvar_sla", "posthoc_cvar_sf")
    if not ok:
        return False, "V-5 FAIL: no SLA vs SF opposite-direction pair on non-dominated triples"
    return True, "V-5 PASS: SLA vs SF opposite-direction pair exists"


def run_formal_acceptance(csv_path: Path, *, print_pareto_summary: bool = True) -> int:
    rows, colmap = _prepare_rows(csv_path)
    analysis, annotated = analyze_pareto_rows(rows, annotate=True)

    nd_points = [
        r
        for r in annotated
        if str(r.get("is_pareto_nondominated", "")).lower() in ("true", "1")
        or r.get("is_pareto_nondominated") is True
    ]
    seen: set[tuple] = set()
    nd_unique: list[dict] = []
    for p in nd_points:
        key = (
            round(_parse_float(p.get("monetary_cost"), 0), 2),
            round(_parse_float(p.get("posthoc_cvar_sla"), 0), 4),
            round(_parse_float(p.get("posthoc_cvar_sf"), 0), 4),
        )
        if key in seen:
            continue
        seen.add(key)
        nd_unique.append(p)

    print(f"CSV: {csv_path} | rows={len(rows)}")
    print(f"Columns: {colmap}")
    if print_pareto_summary:
        print(
            f"Pareto: distinct_triples={analysis.distinct_triples_count} | "
            f"non_dominated_distinct={analysis.non_dominated_distinct_triples_count} | "
            f"dominated_grid_points={analysis.dominated_grid_points_count} | "
            f"non_dominated_grid_points={analysis.non_dominated_grid_points_count}"
        )
        for e in analysis.dominated_entries[:8]:
            print(
                f"  dominated {_grid_triple(e)} by {e['dominator_label']}"
            )
        if len(analysis.dominated_entries) > 8:
            print(f"  ... and {len(analysis.dominated_entries) - 8} more dominated points")

    results = [
        check_v1_nd(nd_unique if nd_unique else nd_points),
        check_v2(analysis),
        check_v3(nd_unique if nd_unique else nd_points),
        check_v4(nd_unique if nd_unique else nd_points),
        check_v5(nd_unique if nd_unique else nd_points),
    ]
    all_ok = True
    for ok, msg in results:
        print(msg)
        all_ok = all_ok and ok

    print("V-6 NOTE: also run `python -m unittest tests.test_smoke tests.test_per_task_od -v`")
    if all_ok:
        print("FORMAL OVERALL: PASS")
        return 0
    print("FORMAL OVERALL: FAIL")
    return 1


def _grid_triple(entry: dict) -> str:
    p = entry["point"]
    return (
        f"({round(float(p['monetary_cost']),2)}, "
        f"{round(float(p['posthoc_cvar_sla']),4)}, "
        f"{round(float(p['posthoc_cvar_sf']),4)})"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Formal P0 acceptance with Pareto filtering")
    ap.add_argument("--csv", type=str, required=True)
    args = ap.parse_args(argv)
    path = Path(args.csv)
    if not path.is_file():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 2
    return run_formal_acceptance(path)


if __name__ == "__main__":
    raise SystemExit(main())
