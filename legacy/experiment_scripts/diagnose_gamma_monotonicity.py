#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase B++: Model C Γ-grid monotonicity & Pareto credibility diagnostics.

Re-solves each (gamma_sla, gamma_sf) point, decomposes objective vs monetary cost,
checks monotonicity and non-dominated triples. Does NOT change MILP semantics.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gurobipy import GRB

MODEL_C_OBJECTIVE_FORMULA = (
    "min  cost_p + cost_b - omega_deliver * E[Del]   "
    "(monetary cost = cost_p + cost_b; NOT equal to ObjVal when omega>0)"
)


def _has_solution(m) -> bool:
    return m.SolCount > 0


def _placement_from_y(data, y) -> dict[int, int]:
    out: dict[int, int] = {}
    for i in data.I:
        for node in data.M:
            if (i, node) in y and y[i, node].X > 0.5:
                out[i] = node
                break
    return out


def _monetary_cost_breakdown(data, y, xin, xout) -> tuple[float, float]:
    from duibi_metrics import bandwidth_cost_expr, path_bandwidth_tariff, teavar_flow_anchors

    cost_p = sum(
        y[i, node].X * sum(data.w[i][k] * data.p_price[node][k] for k in data.K)
        for i, node in y
    )
    per_task = getattr(data, "routing_mode", "hub") in (
        "per_task_od",
        "umcf_per_task",
        "umcf_per_task_od",
    )
    if per_task:
        cost_b = 0.0
        for i in data.I:
            iu, ov = teavar_flow_anchors(data, i)
            for node in data.M:
                if (i, node) not in y:
                    continue
                for p in range(len(data.P_cand[iu, node])):
                    key = (i, node, p)
                    if key in xin:
                        cost_b += xin[key].X * float(path_bandwidth_tariff(data, iu, node, p))
                for q in range(len(data.P_cand[node, ov])):
                    key = (i, node, q)
                    if key in xout:
                        cost_b += xout[key].X * float(path_bandwidth_tariff(data, node, ov, q))
    else:
        src, dst = teavar_flow_anchors(data)
        cb = bandwidth_cost_expr(data, xin, xout, src, dst)
        cost_b = float(cb.getValue()) if hasattr(cb, "getValue") else float(cb)
    return float(cost_p), float(cost_b)


def _var_value(m, name: str) -> float | None:
    try:
        v = m.getVarByName(name)
        return float(v.X) if v is not None else None
    except Exception:  # noqa: BLE001
        return None


def solve_diagnostic_point(
    data,
    gamma_sla: float,
    gamma_sf: float,
    *,
    omega_deliver: float,
    min_off_hub: int,
    time_limit: float,
    mip_gap: float,
) -> dict:
    from metrics_posthoc import compute_posthoc_cvar_metrics
    from run_gamma_frontier import _exp_deliver_value, _status_name
    from teavar_framework_models import build_teavar_model_c

    import time

    t0 = time.perf_counter()
    m, cost, lvc, svc, y, xin, xout, din, dout = build_teavar_model_c(
        data,
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        omega_deliver=omega_deliver,
        include_sf_budget=True,
        min_tasks_off_hub=min_off_hub,
        time_limit=time_limit,
        mip_gap=mip_gap,
    )
    elapsed = time.perf_counter() - t0
    row: dict = {
        "gamma_sla": gamma_sla,
        "gamma_sf": gamma_sf,
        "solver_status": _status_name(m.status),
        "omega_deliver": omega_deliver,
        "model_objective_formula": MODEL_C_OBJECTIVE_FORMULA,
    }
    if not _has_solution(m):
        row.update(
            {
                "obj_val": None,
                "reported_cost": cost,
                "compute_cost": None,
                "bandwidth_cost": None,
                "monetary_cost": None,
                "exp_deliver": None,
                "model_cvar_sla": lvc,
                "model_cvar_sf": svc,
                "posthoc_cvar_sla": None,
                "posthoc_cvar_sf": None,
                "zeta_sla": None,
                "zeta_sf": None,
                "obj_equals_monetary_cost": False,
                "solve_time": elapsed,
            }
        )
        return row

    cost_p, cost_b = _monetary_cost_breakdown(data, y, xin, xout)
    monetary = cost_p + cost_b
    obj = float(m.ObjVal)
    exp_del = _exp_deliver_value(data, m, din, dout)
    zeta_sla = _var_value(m, "zeta_sla")
    zeta_sf = _var_value(m, "zeta_sf")

    ph = compute_posthoc_cvar_metrics(
        data, y, din, dout, model_cvar_sla=lvc, model_cvar_sf=svc
    )
    placement = _placement_from_y(data, y)

    row.update(
        {
            "obj_val": obj,
            "reported_cost": cost,
            "compute_cost": cost_p,
            "bandwidth_cost": cost_b,
            "monetary_cost": monetary,
            "exp_deliver": exp_del,
            "model_cvar_sla": lvc,
            "model_cvar_sf": svc,
            "posthoc_cvar_sla": ph.get("posthoc_cvar_sla"),
            "posthoc_cvar_sf": ph.get("posthoc_cvar_sf"),
            "zeta_sla": zeta_sla,
            "zeta_sf": zeta_sf,
            "obj_minus_monetary": obj - monetary,
            "omega_times_exp_deliver": omega_deliver * float(exp_del or 0.0),
            "obj_equals_monetary_cost": abs(obj - monetary) < 1e-6,
            "obj_reconstructed": monetary - omega_deliver * float(exp_del or 0.0),
            "obj_reconstruction_error": abs(obj - (monetary - omega_deliver * float(exp_del or 0.0))),
            "placement_signature": "|".join(f"{i}:{placement.get(i)}" for i in sorted(data.I)),
            "link_price_mode": getattr(data, "bandwidth_price_mode", ""),
            "routing_mode": getattr(data, "routing_mode", ""),
            "solve_time": elapsed,
        }
    )
    return row


def _load_gamma_pairs_from_csv(path: Path) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            pairs.append((float(r["gamma_sla"]), float(r["gamma_sf"])))
    return pairs


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _pareto_non_dominated(
    points: list[dict],
    *,
    cost_key: str = "monetary_cost",
    sla_key: str = "posthoc_cvar_sla",
    sf_key: str = "posthoc_cvar_sf",
) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """Minimize cost, sla, sf. Return (non_dominated, dominated_with_dominator)."""
    valid = [
        p
        for p in points
        if p.get("solver_status") == "OPTIMAL"
        and p.get(cost_key) is not None
        and p.get(sla_key) is not None
        and p.get(sf_key) is not None
    ]

    def dominates(a: dict, b: dict) -> bool:
        ca, sa, fa = float(a[cost_key]), float(a[sla_key]), float(a[sf_key])
        cb, sb, fb = float(b[cost_key]), float(b[sla_key]), float(b[sf_key])
        le = ca <= cb + 1e-9 and sa <= sb + 1e-9 and fa <= fb + 1e-9
        strict = ca < cb - 1e-9 or sa < sb - 1e-9 or fa < fb - 1e-9
        return le and strict

    nd: list[dict] = []
    dominated: list[tuple[dict, dict]] = []
    for p in valid:
        dom_by = [q for q in valid if q is not p and dominates(q, p)]
        if dom_by:
            dominated.append((p, dom_by[0]))
        else:
            nd.append(p)
    return nd, dominated


def _triple_key(p: dict) -> tuple:
    return (
        round(float(p["monetary_cost"]), 2),
        round(float(p["posthoc_cvar_sla"]), 4),
        round(float(p["posthoc_cvar_sf"]), 4),
    )


def run_monotonicity_checks(rows: list[dict]) -> list[str]:
    lines: list[str] = []
    lines.append(f"Model C objective: {MODEL_C_OBJECTIVE_FORMULA}")

    by_sla: dict[float, list[dict]] = {}
    for r in rows:
        if r.get("solver_status") != "OPTIMAL":
            continue
        by_sla.setdefault(float(r["gamma_sla"]), []).append(r)

    for gs in sorted(by_sla):
        pts = sorted(by_sla[gs], key=lambda x: float(x["gamma_sf"]))
        lines.append(f"\n--- gamma_sla={gs:.4f} (sorted by gamma_sf) ---")
        lines.append(
            f"{'gf':>8} {'obj':>12} {'mon_cost':>12} {'exp_del':>10} "
            f"{'m_sf':>8} {'p_sf':>8} {'placement_changed':>8}"
        )
        prev_pl = None
        obj_mono_violations = []
        cost_mono_violations = []
        for i, r in enumerate(pts):
            pl = r.get("placement_signature", "")
            pl_chg = pl != prev_pl if prev_pl else False
            lines.append(
                f"{float(r['gamma_sf']):8.4f} "
                f"{float(r['obj_val']):12.2f} "
                f"{float(r['monetary_cost']):12.2f} "
                f"{float(r['exp_deliver'] or 0):10.1f} "
                f"{float(r['model_cvar_sf']):8.4f} "
                f"{float(r['posthoc_cvar_sf']):8.4f} "
                f"{'Y' if pl_chg and prev_pl else '':>8}"
            )
            if i > 0:
                prev = pts[i - 1]
                if float(r["obj_val"]) > float(prev["obj_val"]) + 1e-6:
                    obj_mono_violations.append((prev["gamma_sf"], r["gamma_sf"]))
                if float(r["monetary_cost"]) > float(prev["monetary_cost"]) + 1e-6:
                    cost_mono_violations.append((prev["gamma_sf"], r["gamma_sf"]))
            prev_pl = pl

        if obj_mono_violations:
            lines.append(
                f"  obj_val NON-MONOTONE (should non-increase as gamma_sf↑): {obj_mono_violations}"
            )
        else:
            lines.append("  obj_val: NON-INCREASING as gamma_sf widens [OK]")

        if cost_mono_violations:
            lines.append(
                f"  monetary_cost INCREASES as gamma_sf widens (expected when objective≠cost): "
                f"{cost_mono_violations}"
            )
        else:
            lines.append("  monetary_cost: non-increasing (pure-cost intuition holds)")

    return lines


def run_acceptance_on_nd(nd: list[dict], nd_triples: set[tuple]) -> list[str]:
    lines = [f"\n=== Non-dominated acceptance (distinct triples={len(nd_triples)}) ==="]
    if len(nd_triples) < 3:
        lines.append("FAIL: fewer than 3 non-dominated triples")
        return lines

    costs = [float(p["monetary_cost"]) for p in nd]
    slas = [float(p["posthoc_cvar_sla"]) for p in nd]
    sfs = [float(p["posthoc_cvar_sf"]) for p in nd]
    distinct_sla = len(set(round(x, 4) for x in slas))
    distinct_sf = len(set(round(x, 4) for x in sfs))
    distinct_cost = len(set(round(x, 2) for x in costs))

    lines.append(f"distinct cost={distinct_cost}, sla={distinct_sla}, sf={distinct_sf}")

    # cost vs SLA trade-off
    cost_sla_trade = False
    for a in nd:
        for b in nd:
            if a is b:
                continue
            if float(a["monetary_cost"]) < float(b["monetary_cost"]) and float(a["posthoc_cvar_sla"]) > float(
                b["posthoc_cvar_sla"]
            ):
                cost_sla_trade = True
    lines.append(f"cost vs SLA trade-off exists: {cost_sla_trade}")

    cost_sf_trade = False
    for a in nd:
        for b in nd:
            if a is b:
                continue
            if float(a["monetary_cost"]) < float(b["monetary_cost"]) and float(a["posthoc_cvar_sf"]) > float(
                b["posthoc_cvar_sf"]
            ):
                cost_sf_trade = True
    lines.append(f"cost vs SF trade-off exists: {cost_sf_trade}")

    sla_sf_opp = False
    for a in nd:
        for b in nd:
            if a is b:
                continue
            da = float(a["posthoc_cvar_sla"]) - float(b["posthoc_cvar_sla"])
            db = float(a["posthoc_cvar_sf"]) - float(b["posthoc_cvar_sf"])
            if da * db < -1e-12:
                sla_sf_opp = True
    lines.append(f"SLA vs SF opposite-direction pair: {sla_sf_opp}")
    lines.append(f">=3 non-dominated triples: {'PASS' if len(nd_triples) >= 3 else 'FAIL'}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Model C Γ monotonicity & Pareto diagnostics")
    ap.add_argument(
        "--input-csv",
        default="results/temp_smoke_posthoc_gamma/uniform_frontier_b4_tasks8_posthoc_gamma.csv",
        help="Existing frontier CSV (gamma pairs only)",
    )
    ap.add_argument(
        "--output-csv",
        default="results/temp_smoke_posthoc_gamma/model_c_gamma_diagnostic.csv",
    )
    ap.add_argument(
        "--report",
        default="results/temp_smoke_posthoc_gamma/model_c_gamma_diagnostic_report.txt",
    )
    ap.add_argument("--topology", default="B4")
    ap.add_argument("--num-tasks", type=int, default=8)
    ap.add_argument("--routing-mode", default="per_task_od")
    ap.add_argument("--scenario-mode", default="macro3")
    ap.add_argument("--link-price-mode", default="uniform")
    ap.add_argument("--omega-deliver", type=float, default=1.0)
    ap.add_argument("--min-off-hub", type=int, default=2)
    ap.add_argument("--time-limit", type=float, default=90.0)
    ap.add_argument("--mip-gap", type=float, default=0.03)
    args = ap.parse_args(argv)

    from run_gamma_frontier import load_p0_data

    pairs = _load_gamma_pairs_from_csv(Path(args.input_csv))
    data = load_p0_data(
        base_path="./data",
        topology=args.topology,
        num_tasks=args.num_tasks,
        k_paths=4,
        eta=1.3,
        joint_demand_scale=None,
        routing_mode=args.routing_mode,
        s2_derate=0.4,
        s1_link_k=4,
        s1_sigma=0.8,
        scenario_mode=args.scenario_mode,
        link_price_mode=args.link_price_mode,
        quiet=True,
    )

    rows: list[dict] = []
    for gs, gf in pairs:
        print(f"diagnose Γ_sla={gs} Γ_sf={gf} ...", flush=True)
        rows.append(
            solve_diagnostic_point(
                data,
                gs,
                gf,
                omega_deliver=args.omega_deliver,
                min_off_hub=args.min_off_hub,
                time_limit=args.time_limit,
                mip_gap=args.mip_gap,
            )
        )

    fieldnames = [
        "gamma_sla",
        "gamma_sf",
        "solver_status",
        "obj_val",
        "reported_cost",
        "compute_cost",
        "bandwidth_cost",
        "monetary_cost",
        "exp_deliver",
        "omega_deliver",
        "omega_times_exp_deliver",
        "obj_minus_monetary",
        "obj_reconstructed",
        "obj_reconstruction_error",
        "obj_equals_monetary_cost",
        "model_cvar_sla",
        "model_cvar_sf",
        "posthoc_cvar_sla",
        "posthoc_cvar_sf",
        "zeta_sla",
        "zeta_sf",
        "placement_signature",
        "link_price_mode",
        "routing_mode",
        "solve_time",
        "model_objective_formula",
    ]
    out_csv = Path(args.output_csv)
    _write_csv(out_csv, rows, fieldnames)

    opt_rows = [r for r in rows if r.get("solver_status") == "OPTIMAL"]
    nd, dominated = _pareto_non_dominated(opt_rows)
    all_triples = {_triple_key(r) for r in opt_rows}
    nd_triples = {_triple_key(r) for r in nd}
    nd_points = len(nd)

    report_lines = [
        "Phase B++ Model C Γ Diagnostic Report",
        f"input: {args.input_csv}",
        f"diagnostic_csv: {out_csv}",
        f"points: {len(rows)} optimal: {len(opt_rows)}",
        "",
        "=== Objective vs cost ===",
    ]
    for r in opt_rows[:3]:
        report_lines.append(
            f"  gf={r['gamma_sf']} obj={r['obj_val']:.4f} monetary={r['monetary_cost']:.4f} "
            f"exp_del={r['exp_deliver']:.2f} recon_err={r['obj_reconstruction_error']:.2e} "
            f"reported_cost==monetary: {abs(float(r['reported_cost'])-float(r['monetary_cost']))<1e-4}"
        )
    report_lines.append(
        f"obj_equals_monetary_cost (any point): {any(r.get('obj_equals_monetary_cost') for r in opt_rows)}"
    )
    report_lines.append(
        f"reported_cost matches monetary_cost (all): "
        f"{all(abs(float(r['reported_cost'])-float(r['monetary_cost']))<1e-4 for r in opt_rows)}"
    )

    report_lines.extend(run_monotonicity_checks(rows))

    report_lines.extend(
        [
            "",
            "=== Pareto (min cost, min posthoc_sla, min posthoc_sf) ===",
            f"distinct triples (all optimal): {len(all_triples)}",
            f"non-dominated triples: {len(nd_triples)} (from {nd_points} non-dominated grid points)",
            f"dominated points: {len(dominated)}",
        ]
    )
    for p, dom in dominated:
        report_lines.append(
            f"  DOMINATED gf=({p['gamma_sla']},{p['gamma_sf']}) "
            f"triple={_triple_key(p)} "
            f"by gf=({dom['gamma_sla']},{dom['gamma_sf']}) triple={_triple_key(dom)}"
        )

    # Phase B+ six triples check
    phase_b_triples = {
        (1429.16, 1.0, 0.0209),
        (1717.93, 1.0, 0.0377),
        (2316.46, 0.9, 0.0377),
        (2330.94, 0.9, 0.0209),
        (3009.99, 0.8, 0.0209),
        (3054.2, 0.8, 0.0377),
    }
    report_lines.append("\n=== Phase B+ 6 triples dominated? ===")
    for t in sorted(phase_b_triples):
        in_nd = t in nd_triples
        dom_entry = [
            (p, d)
            for p, d in dominated
            if _triple_key(p) == t
        ]
        report_lines.append(
            f"  {t} in_non_dominated={in_nd} dominated={bool(dom_entry)}"
        )

    report_lines.extend(run_acceptance_on_nd(nd, nd_triples))

    # Feasibility: tight solution feasible at loose gamma?
    report_lines.append("\n=== Feasibility cross-check (gamma_sla=1.0) ===")
    sla1 = [r for r in opt_rows if abs(float(r["gamma_sla"]) - 1.0) < 1e-6]
    tight = min(sla1, key=lambda x: float(x["gamma_sf"]))
    loose = max(sla1, key=lambda x: float(x["gamma_sf"]))
    report_lines.append(
        f"tight gf={tight['gamma_sf']} posthoc_sf={tight['posthoc_cvar_sf']} "
        f"would satisfy loose gf={loose['gamma_sf']}: "
        f"{float(tight['posthoc_cvar_sf']) <= float(loose['gamma_sf']) + 1e-9}"
    )
    report_lines.append(
        f"tight monetary={tight['monetary_cost']} vs loose monetary={loose['monetary_cost']} "
        f"(loose gamma allows higher-monetary solution because objective rewards delivery)"
    )

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_text = "\n".join(report_lines)
    report_path.write_text(report_text, encoding="utf-8")
    print(report_text)
    print(f"\nWrote {out_csv}")
    print(f"Wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
