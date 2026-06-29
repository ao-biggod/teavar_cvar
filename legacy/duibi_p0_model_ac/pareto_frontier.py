# -*- coding: utf-8 -*-
"""Pareto dominance filtering for frontier CSV rows (reporting only)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _parse_float(val, default=None):
    if val is None or str(val).strip() == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _is_optimal(status: Any) -> bool:
    st = str(status or "").strip().upper()
    return st in ("2", "OPTIMAL", "OPT")


def triple_key(cost: float, sla: float, sf: float, *, ndigits: tuple[int, int, int] = (2, 4, 4)) -> tuple:
    return (
        round(float(cost), ndigits[0]),
        round(float(sla), ndigits[1]),
        round(float(sf), ndigits[2]),
    )


def dominates(
    a: dict,
    b: dict,
    *,
    cost_key: str = "monetary_cost",
    sla_key: str = "posthoc_cvar_sla",
    sf_key: str = "posthoc_cvar_sf",
    tol: float = 1e-9,
) -> bool:
    """True if ``a`` dominates ``b`` (minimize all three)."""
    ca, sa, fa = float(a[cost_key]), float(a[sla_key]), float(a[sf_key])
    cb, sb, fb = float(b[cost_key]), float(b[sla_key]), float(b[sf_key])
    le = ca <= cb + tol and sa <= sb + tol and fa <= fb + tol
    strict = ca < cb - tol or sa < sb - tol or fa < fb - tol
    return le and strict


def _grid_label(row: dict) -> str:
    gs = row.get("gamma_sla", "")
    gf = row.get("gamma_sf", "")
    return f"gamma_sla={gs};gamma_sf={gf}"


@dataclass
class ParetoAnalysis:
    distinct_triples_count: int = 0
    non_dominated_distinct_triples_count: int = 0
    dominated_grid_points_count: int = 0
    non_dominated_grid_points_count: int = 0
    dominated_entries: list[dict] = field(default_factory=list)
    non_dominated_triples: set[tuple] = field(default_factory=set)
    all_triples: set[tuple] = field(default_factory=set)


def analyze_pareto_rows(
    rows: list[dict],
    *,
    cost_key: str = "monetary_cost",
    sla_key: str = "posthoc_cvar_sla",
    sf_key: str = "posthoc_cvar_sf",
    status_key: str = "status",
    annotate: bool = True,
) -> tuple[ParetoAnalysis, list[dict]]:
    """
    Filter optimal rows; annotate ``is_pareto_nondominated`` and ``dominated_by``.
    Dominated rows remain in output when ``annotate=True``.
    """
    valid: list[dict] = []
    for r in rows:
        if not _is_optimal(r.get(status_key)):
            if annotate:
                r = dict(r)
                r["is_pareto_nondominated"] = False
                r["dominated_by"] = ""
            continue
        c = _parse_float(r.get(cost_key))
        sla = _parse_float(r.get(sla_key))
        sf = _parse_float(r.get(sf_key))
        if c is None or sla is None or sf is None:
            if annotate:
                r = dict(r)
                r["is_pareto_nondominated"] = False
                r["dominated_by"] = "missing_metrics"
            continue
        pt = dict(r)
        pt[cost_key] = c
        pt[sla_key] = sla
        pt[sf_key] = sf
        valid.append(pt)

    analysis = ParetoAnalysis()
    if not valid:
        return analysis, list(rows)

    analysis.all_triples = {
        triple_key(p[cost_key], p[sla_key], p[sf_key]) for p in valid
    }
    analysis.distinct_triples_count = len(analysis.all_triples)

    nd_points: list[dict] = []
    dominated_entries: list[dict] = []
    for p in valid:
        dom_by = [q for q in valid if q is not p and dominates(q, p)]
        if dom_by:
            dominated_entries.append(
                {
                    "point": p,
                    "dominator": dom_by[0],
                    "triple": triple_key(p[cost_key], p[sla_key], p[sf_key]),
                    "dominator_triple": triple_key(
                        dom_by[0][cost_key], dom_by[0][sla_key], dom_by[0][sf_key]
                    ),
                    "dominator_label": _grid_label(dom_by[0]),
                }
            )
        else:
            nd_points.append(p)

    analysis.dominated_grid_points_count = len(dominated_entries)
    analysis.non_dominated_grid_points_count = len(nd_points)
    analysis.non_dominated_triples = {
        triple_key(p[cost_key], p[sla_key], p[sf_key]) for p in nd_points
    }
    analysis.non_dominated_distinct_triples_count = len(analysis.non_dominated_triples)
    analysis.dominated_entries = dominated_entries

    if not annotate:
        return analysis, valid

    dom_map = {id(e["point"]): e for e in dominated_entries}
    out_rows: list[dict] = []
    for r in rows:
        row = dict(r)
        if not _is_optimal(row.get(status_key)):
            row["is_pareto_nondominated"] = False
            row["dominated_by"] = ""
            out_rows.append(row)
            continue
        c = _parse_float(row.get(cost_key))
        sla = _parse_float(row.get(sla_key))
        sf = _parse_float(row.get(sf_key))
        if c is None or sla is None or sf is None:
            row["is_pareto_nondominated"] = False
            row["dominated_by"] = "missing_metrics"
            out_rows.append(row)
            continue
        match = None
        for p in valid:
            if (
                _parse_float(p.get("gamma_sla")) == _parse_float(row.get("gamma_sla"))
                and _parse_float(p.get("gamma_sf")) == _parse_float(row.get("gamma_sf"))
            ):
                match = p
                break
        if match is None:
            row["is_pareto_nondominated"] = False
            row["dominated_by"] = ""
            out_rows.append(row)
            continue
        entry = dom_map.get(id(match))
        if entry:
            row["is_pareto_nondominated"] = False
            row["dominated_by"] = entry["dominator_label"]
        else:
            row["is_pareto_nondominated"] = True
            row["dominated_by"] = ""
        out_rows.append(row)

    return analysis, out_rows


def has_tradeoff(
    points: list[dict],
    key_a: str,
    key_b: str,
    *,
    lower_a_better: bool = True,
    lower_b_better: bool = True,
) -> bool:
    """Exist pair where improving A worsens B."""
    for i, a in enumerate(points):
        va = _parse_float(a.get(key_a))
        vb_a = _parse_float(a.get(key_b))
        if va is None or vb_a is None:
            continue
        for j in range(i + 1, len(points)):
            b = points[j]
            vb = _parse_float(b.get(key_a))
            vb_b = _parse_float(b.get(key_b))
            if vb is None or vb_b is None:
                continue
            da = vb - va
            db = vb_b - vb_a
            if abs(da) <= 1e-9 or abs(db) <= 1e-9:
                continue
            if lower_a_better and lower_b_better and da * db < 0:
                return True
    return False
