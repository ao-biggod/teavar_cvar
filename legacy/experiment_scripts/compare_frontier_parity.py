#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compare two frontier CSVs (+ optional resolved configs) for Phase B++++ parity."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pareto_frontier import analyze_pareto_rows, triple_key


def _load_csv(path: Path) -> tuple[list[dict], list[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        return list(reader), fields


def _f(val, default=None):
    if val is None or str(val).strip() == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _col(row: dict, *names: str):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    lower = {k.lower(): v for k, v in row.items()}
    for n in names:
        if n.lower() in lower and lower[n.lower()] not in (None, ""):
            return lower[n.lower()]
    return None


def _optimal(rows: list[dict]) -> list[dict]:
    return [r for r in rows if str(_col(r, "status", "solver_status") or "").upper() in ("OPTIMAL", "2")]


def _gamma_pairs(rows: list[dict]) -> set[tuple[float, float]]:
    out: set[tuple[float, float]] = set()
    for r in rows:
        gs, gf = _f(_col(r, "gamma_sla")), _f(_col(r, "gamma_sf"))
        if gs is not None and gf is not None:
            out.add((round(gs, 6), round(gf, 6)))
    return out


def _triples(rows: list[dict]) -> set[tuple]:
    out: set[tuple] = set()
    for r in rows:
        c = _f(_col(r, "monetary_cost", "cost"))
        sla = _f(_col(r, "posthoc_cvar_sla", "reported_cvar_sla"))
        sf = _f(_col(r, "posthoc_cvar_sf", "reported_cvar_sf"))
        if c is not None and sla is not None and sf is not None:
            out.add(triple_key(c, sla, sf))
    return out


def _unique_vals(rows: list[dict], *col_names: str) -> list[float]:
    vals = []
    for r in rows:
        v = _f(_col(r, *col_names))
        if v is not None:
            vals.append(v)
    return sorted(set(round(v, 6) for v in vals))


def _range_stat(rows: list[dict], *col_names: str) -> dict:
    vals = [_f(_col(r, *col_names)) for r in rows]
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"min": None, "max": None, "count": 0}
    return {"min": min(vals), "max": max(vals), "count": len(vals)}


def _pair_diffs(left: list[dict], right: list[dict]) -> list[dict]:
    lmap = {(round(_f(_col(r, "gamma_sla")), 6), round(_f(_col(r, "gamma_sf")), 6)): r for r in left}
    rmap = {(round(_f(_col(r, "gamma_sla")), 6), round(_f(_col(r, "gamma_sf")), 6)): r for r in right}
    keys = sorted(set(lmap) & set(rmap))
    diffs = []
    fields = [
        ("monetary_cost", "monetary_cost", "cost"),
        ("exp_deliver", "exp_deliver"),
        ("objective", "objective", "obj_val"),
        ("posthoc_cvar_sla", "posthoc_cvar_sla"),
        ("posthoc_cvar_sf", "posthoc_cvar_sf"),
        ("model_cvar_sla", "model_cvar_sla", "cvar_sla"),
        ("model_cvar_sf", "model_cvar_sf", "cvar_sf"),
    ]
    for key in keys:
        lr, rr = lmap[key], rmap[key]
        entry = {"gamma_sla": key[0], "gamma_sf": key[1]}
        any_diff = False
        for label, *cols in fields:
            lv, rv = _f(_col(lr, *cols)), _f(_col(rr, *cols))
            entry[f"left_{label}"] = lv
            entry[f"right_{label}"] = rv
            if lv is not None and rv is not None:
                d = rv - lv
                entry[f"delta_{label}"] = d
                if abs(d) > 1e-6:
                    any_diff = True
        if any_diff:
            diffs.append(entry)
    return diffs


def _load_json(path: Path | None) -> dict | None:
    if path is None or not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _config_diff(left: dict | None, right: dict | None) -> list[str]:
    if left is None and right is None:
        return []
    if left is None or right is None:
        return ["one side missing resolved config"]
    keys = [
        "topology",
        "routing_mode",
        "num_tasks",
        "omega_deliver",
        "sf_ref_mode",
        "demand_calibration",
        "scenarios",
        "link_price",
        "task_selection",
        "loader",
    ]
    lines: list[str] = []
    for k in keys:
        lv, rv = left.get(k), right.get(k)
        if lv != rv:
            lines.append(f"{k}: left={lv!r} right={rv!r}")
    return lines


def _normalize_row(r: dict) -> dict:
    nr = dict(r)
    if not nr.get("monetary_cost") and nr.get("cost") not in (None, ""):
        nr["monetary_cost"] = nr["cost"]
    if not nr.get("posthoc_cvar_sla") and nr.get("reported_cvar_sla") not in (None, ""):
        nr["posthoc_cvar_sla"] = nr["reported_cvar_sla"]
    if not nr.get("posthoc_cvar_sf") and nr.get("reported_cvar_sf") not in (None, ""):
        nr["posthoc_cvar_sf"] = nr["reported_cvar_sf"]
    return nr


def compare(
    left_csv: Path,
    right_csv: Path,
    *,
    left_config: Path | None = None,
    right_config: Path | None = None,
) -> dict:
    lrows, _ = _load_csv(left_csv)
    rrows, _ = _load_csv(right_csv)
    lrows = [_normalize_row(r) for r in lrows]
    rrows = [_normalize_row(r) for r in rrows]
    lopt, ropt = _optimal(lrows), _optimal(rrows)
    lpareto, _ = analyze_pareto_rows(lopt, annotate=False)
    rpareto, _ = analyze_pareto_rows(ropt, annotate=False)

    report = {
        "left_csv": str(left_csv),
        "right_csv": str(right_csv),
        "row_counts": {"left": len(lrows), "right": len(rrows), "left_optimal": len(lopt), "right_optimal": len(ropt)},
        "gamma_grid": {
            "left_only": sorted(_gamma_pairs(lopt) - _gamma_pairs(ropt)),
            "right_only": sorted(_gamma_pairs(ropt) - _gamma_pairs(lopt)),
            "shared": sorted(_gamma_pairs(lopt) & _gamma_pairs(ropt)),
        },
        "distinct_triples": {
            "left": sorted(_triples(lopt)),
            "right": sorted(_triples(ropt)),
            "left_only": sorted(_triples(lopt) - _triples(ropt)),
            "right_only": sorted(_triples(ropt) - _triples(lopt)),
            "shared": sorted(_triples(lopt) & _triples(ropt)),
        },
        "non_dominated_distinct_triples": {
            "left": lpareto.non_dominated_distinct_triples_count,
            "right": rpareto.non_dominated_distinct_triples_count,
        },
        "posthoc_sla_unique": {"left": _unique_vals(lopt, "posthoc_cvar_sla"), "right": _unique_vals(ropt, "posthoc_cvar_sla")},
        "posthoc_sf_unique": {"left": _unique_vals(lopt, "posthoc_cvar_sf"), "right": _unique_vals(ropt, "posthoc_cvar_sf")},
        "monetary_cost_range": {"left": _range_stat(lopt, "monetary_cost", "cost"), "right": _range_stat(ropt, "monetary_cost", "cost")},
        "exp_deliver_range": {"left": _range_stat(lopt, "exp_deliver"), "right": _range_stat(ropt, "exp_deliver")},
        "objective_range": {"left": _range_stat(lopt, "objective", "obj_val"), "right": _range_stat(ropt, "objective", "obj_val")},
        "pair_diffs": _pair_diffs(lopt, ropt),
        "config_diff_lines": _config_diff(_load_json(left_config), _load_json(right_config)),
    }
    return report


def print_report(report: dict) -> None:
    print("=== Frontier parity comparison ===")
    print(f"left:  {report['left_csv']}")
    print(f"right: {report['right_csv']}")
    rc = report["row_counts"]
    print(f"rows: left={rc['left']} right={rc['right']} | optimal left={rc['left_optimal']} right={rc['right_optimal']}")
    gg = report["gamma_grid"]
    print(f"gamma shared={len(gg['shared'])} left_only={len(gg['left_only'])} right_only={len(gg['right_only'])}")
    dt = report["distinct_triples"]
    print(f"distinct triples: left={len(dt['left'])} right={len(dt['right'])} shared={len(dt['shared'])}")
    print(f"  left_only triples: {dt['left_only'][:8]}{'...' if len(dt['left_only'])>8 else ''}")
    print(f"  right_only triples: {dt['right_only'][:8]}{'...' if len(dt['right_only'])>8 else ''}")
    nd = report["non_dominated_distinct_triples"]
    print(f"non_dominated distinct: left={nd['left']} right={nd['right']}")
    print(f"posthoc_sla unique: left={report['posthoc_sla_unique']['left']} right={report['posthoc_sla_unique']['right']}")
    print(f"posthoc_sf unique:  left={report['posthoc_sf_unique']['left']} right={report['posthoc_sf_unique']['right']}")
    print(f"monetary_cost range: left={report['monetary_cost_range']['left']} right={report['monetary_cost_range']['right']}")
    print(f"exp_deliver range:   left={report['exp_deliver_range']['left']} right={report['exp_deliver_range']['right']}")
    if report["config_diff_lines"]:
        print("resolved config diffs:")
        for line in report["config_diff_lines"]:
            print(f"  {line}")
    diffs = report["pair_diffs"]
    print(f"gamma-pair field diffs (|delta|>0): {len(diffs)}")
    for d in diffs[:12]:
        print(
            f"  ({d['gamma_sla']},{d['gamma_sf']}): "
            f"cost {d.get('left_monetary_cost')}->{d.get('right_monetary_cost')} "
            f"posthoc_sf {d.get('left_posthoc_cvar_sf')}->{d.get('right_posthoc_cvar_sf')}"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare frontier CSV parity")
    ap.add_argument("--left-csv", required=True)
    ap.add_argument("--right-csv", required=True)
    ap.add_argument("--left-config", default=None)
    ap.add_argument("--right-config", default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)
    report = compare(
        Path(args.left_csv),
        Path(args.right_csv),
        left_config=Path(args.left_config) if args.left_config else None,
        right_config=Path(args.right_config) if args.right_config else None,
    )
    print_report(report)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
            f.write("\n")
        print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
