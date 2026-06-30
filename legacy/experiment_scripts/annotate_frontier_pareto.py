#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Annotate an existing frontier CSV with Pareto columns (no re-solve)."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pareto_frontier import analyze_pareto_rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Add is_pareto_nondominated / dominated_by to frontier CSV")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args(argv)

    in_path = Path(args.input)
    out_path = Path(args.output)
    with in_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for r in rows:
        if not r.get("monetary_cost") and r.get("cost"):
            r["monetary_cost"] = r["cost"]

    analysis, annotated = analyze_pareto_rows(rows, annotate=True)
    extra = ["is_pareto_nondominated", "dominated_by"]
    out_fields = fieldnames + [c for c in extra if c not in fieldnames]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(annotated)

    print(
        f"Wrote {out_path} | distinct_triples={analysis.distinct_triples_count} | "
        f"non_dominated_distinct={analysis.non_dominated_distinct_triples_count} | "
        f"dominated_grid_points={analysis.dominated_grid_points_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
