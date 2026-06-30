#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase C-0: formal P0 cost-axis determinacy check (diagnostic only; no MILP changes)."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

POINTS = [(1.0, 0.03), (1.0, 0.0377), (0.9, 0.03), (0.8, 0.03)]
TOL = 1e-6


def _f(val):
    if val is None or str(val).strip() == "":
        return None
    return float(val)


def _placement(data, y) -> dict[int, int]:
    return {
        i: node
        for i in data.I
        for node in data.M
        if (i, node) in y and y[i, node].X > 0.5
    }


def audit_p_cand(data) -> list[dict]:
    from duibi_metrics import path_bandwidth_tariff

    rows: list[dict] = []
    for (u, v), paths in sorted(data.P_cand.items()):
        for p_idx, path in enumerate(paths):
            tau = path_bandwidth_tariff(data, u, v, p_idx)
            is_zero_hop = u == v
            is_empty = len(path) == 0
            is_anomaly_empty = is_empty and u != v
            is_nonempty_tau0 = (not is_empty) and tau <= TOL
            rows.append(
                {
                    "u": u,
                    "v": v,
                    "path_id": p_idx,
                    "edge_list": [list(e) for e in path],
                    "node_list": _path_nodes(path),
                    "tau_p": tau,
                    "is_zero_hop_local": is_zero_hop and is_empty,
                    "is_anomaly_empty_path": is_anomaly_empty,
                    "is_nonempty_tau_zero": is_nonempty_tau0,
                }
            )
    return rows


def _path_nodes(path) -> list:
    if not path:
        return []
    nodes = [path[0][0]]
    for e in path:
        nodes.append(e[1])
    return nodes


def diagnose_point(data, gamma_sla: float, gamma_sf: float) -> dict:
    from cvar_compare import _task_flow_anchors
    from duibi_metrics import bandwidth_cost_expr, path_bandwidth_tariff, path_up, teavar_flow_anchors
    from frontier_reporting import monetary_cost_breakdown
    from metrics_posthoc import compute_posthoc_cvar_metrics
    from run_gamma_frontier import _exp_deliver_value
    from teavar_framework_models import build_teavar_model_c

    m, cost, lvc, svc, y, xin, xout, din, dout = build_teavar_model_c(
        data,
        gamma_sla=gamma_sla,
        gamma_sf=gamma_sf,
        omega_deliver=1.0,
        include_sf_budget=True,
        min_tasks_off_hub=2,
        time_limit=120,
        mip_gap=0.02,
    )
    placement = _placement(data, y)
    cp, cb = monetary_cost_breakdown(data, y, xin, xout)
    exp_del = _exp_deliver_value(data, m, din, dout)
    ph = compute_posthoc_cvar_metrics(data, y, din, dout, model_cvar_sla=lvc, model_cvar_sf=svc)

    per_task = getattr(data, "routing_mode", "hub") in ("per_task_od", "umcf_per_task")
    in_u_g, out_v_g = (0, 0) if per_task else teavar_flow_anchors(data)

    ingress_flows = []
    egress_flows = []
    empty_path_count = 0
    zero_cost_path_count = 0
    total_x_on_zero_cost = 0.0
    total_d_on_zero_cost = 0.0

    for i in data.I:
        iu, ov = teavar_flow_anchors(data, i)
        node = placement[i]
        for p in range(len(data.P_cand[iu, node])):
            key = (i, node, p)
            if key not in xin:
                continue
            xv = float(xin[key].X)
            path = data.P_cand[iu, node][p]
            tau = path_bandwidth_tariff(data, iu, node, p)
            if len(path) == 0:
                empty_path_count += 1
            if tau <= TOL:
                zero_cost_path_count += 1
                total_x_on_zero_cost += xv
            if xv > TOL:
                ingress_flows.append(
                    {
                        "task": i,
                        "node": node,
                        "src": iu,
                        "path_id": p,
                        "path": [list(e) for e in path],
                        "tau_p": tau,
                        "x": xv,
                        "is_empty_path": len(path) == 0,
                        "is_zero_hop": iu == node,
                    }
                )
        for q in range(len(data.P_cand[node, ov])):
            key = (i, node, q)
            if key not in xout:
                continue
            xv = float(xout[key].X)
            path = data.P_cand[node, ov][q]
            tau = path_bandwidth_tariff(data, node, ov, q)
            if len(path) == 0:
                empty_path_count += 1
            if tau <= TOL:
                zero_cost_path_count += 1
                total_x_on_zero_cost += xv
            if xv > TOL:
                egress_flows.append(
                    {
                        "task": i,
                        "node": node,
                        "dst": ov,
                        "path_id": q,
                        "path": [list(e) for e in path],
                        "tau_p": tau,
                        "x": xv,
                        "is_empty_path": len(path) == 0,
                        "is_zero_hop": node == ov,
                    }
                )

    delivery_by_task_scenario = {}
    for s in data.S:
        delivery_by_task_scenario[str(s)] = {}
        for i in data.I:
            iu, ov = _task_flow_anchors(data, i, in_u_g, out_v_g)
            rin = sum(
                float(din[k].X)
                for k in din
                if k[3] == s and k[0] == i
            )
            rout = sum(
                float(dout[k].X)
                for k in dout
                if k[3] == s and k[0] == i
            )
            delivery_by_task_scenario[str(s)][str(i)] = {
                "R_in": rin,
                "R_out": rout,
                "total": rin + rout,
            }
            for side, var_dict, anchor_u, anchor_v, is_in in [
                ("in", din, iu, placement[i], True),
                ("out", dout, placement[i], ov, False),
            ]:
                for key, var in var_dict.items():
                    if key[0] != i or key[3] != s:
                        continue
                    dv = float(var.X)
                    if dv <= TOL:
                        continue
                    _, node, pidx, _ = key
                    if is_in:
                        path = data.P_cand[anchor_u, node][pidx]
                        tau = path_bandwidth_tariff(data, anchor_u, node, pidx)
                    else:
                        path = data.P_cand[anchor_v, anchor_v if False else node][pidx]
                        path = data.P_cand[node, anchor_v][pidx]
                        tau = path_bandwidth_tariff(data, node, anchor_v, pidx)
                    if tau <= TOL:
                        total_d_on_zero_cost += dv

    coupling_checks = _coupling_checks(data, y, xin, xout, din, dout, placement)
    bw_expr = float(bandwidth_cost_expr(data, xin, xout, None, None).getValue())

    return {
        "gamma_sla": gamma_sla,
        "gamma_sf": gamma_sf,
        "solver_status": int(m.status),
        "objective": float(m.ObjVal),
        "obj_val": float(m.ObjVal),
        "monetary_cost": cp + cb,
        "compute_cost": cp,
        "bandwidth_cost": cb,
        "bandwidth_cost_expr": bw_expr,
        "expected_delivery": exp_del,
        "posthoc_cvar_sla": ph.get("posthoc_cvar_sla"),
        "posthoc_cvar_sf": ph.get("posthoc_cvar_sf"),
        "placement": {str(i): placement[i] for i in sorted(placement)},
        "placement_signature": "|".join(f"{i}:{placement[i]}" for i in sorted(placement)),
        "y_assignments": {f"y_{i}_{n}": float(y[i, n].X) for i, n in y if y[i, n].X > 0.5},
        "ingress_flows_positive_x": ingress_flows,
        "egress_flows_positive_x": egress_flows,
        "delivery_by_task_scenario": delivery_by_task_scenario,
        "path_usage_summary": {
            "empty_path_entries_in_catalog": empty_path_count,
            "zero_cost_path_entries_with_positive_x": zero_cost_path_count,
            "total_x_flow_on_zero_cost_paths": total_x_on_zero_cost,
            "total_delivered_flow_on_zero_cost_paths": total_d_on_zero_cost,
        },
        "coupling_checks": coupling_checks,
    }


def _coupling_checks(data, y, xin, xout, din, dout, placement) -> dict:
    from duibi_metrics import path_bandwidth_tariff, path_up, teavar_flow_anchors

    issues: list[dict] = []
    del_positive_no_x = []
    x_positive_not_in_cost = []
    d_exceeds_x = []
    del_positive_paths = []

    charged_x_total = 0.0
    for (i, node, p), var in xin.items():
        xv = float(var.X)
        if xv <= TOL:
            continue
        iu, _ = teavar_flow_anchors(data, i)
        tau = path_bandwidth_tariff(data, iu, node, p)
        charged_x_total += xv * tau
        if tau <= TOL and xv > TOL:
            x_positive_not_in_cost.append({"side": "in", "key": [i, node, p], "x": xv, "tau": tau})

    for (i, node, q), var in xout.items():
        xv = float(var.X)
        if xv <= TOL:
            continue
        _, ov = teavar_flow_anchors(data, i)
        tau = path_bandwidth_tariff(data, node, ov, q)
        charged_x_total += xv * tau
        if tau <= TOL and xv > TOL:
            x_positive_not_in_cost.append({"side": "out", "key": [i, node, q], "x": xv, "tau": tau})

    for key, var in din.items():
        dv = float(var.X)
        if dv <= TOL:
            continue
        i, node, p, s = key
        iu, ov = teavar_flow_anchors(data, i)
        xk = (i, node, p)
        xv = float(xin[xk].X) if xk in xin else 0.0
        up = path_up(data, iu, node, p, s)
        if xv <= TOL:
            del_positive_no_x.append({"side": "in", "key": list(key), "d": dv, "x": xv, "path_up": up})
        if dv > xv + 1e-4:
            d_exceeds_x.append({"side": "in", "key": list(key), "d": dv, "x": xv})
        path = data.P_cand[iu, node][p]
        tau = path_bandwidth_tariff(data, iu, node, p)
        del_positive_paths.append(
            {"side": "in", "task": i, "s": s, "d": dv, "x": xv, "tau": tau, "path_up": up, "path_empty": len(path) == 0}
        )

    for key, var in dout.items():
        dv = float(var.X)
        if dv <= TOL:
            continue
        i, node, q, s = key
        _, ov = teavar_flow_anchors(data, i)
        xk = (i, node, q)
        xv = float(xout[xk].X) if xk in xout else 0.0
        up = path_up(data, node, ov, q, s)
        if xv <= TOL:
            del_positive_no_x.append({"side": "out", "key": list(key), "d": dv, "x": xv, "path_up": up})
        if dv > xv + 1e-4:
            d_exceeds_x.append({"side": "out", "key": list(key), "d": dv, "x": xv})
        path = data.P_cand[node, ov][q]
        tau = path_bandwidth_tariff(data, node, ov, q)
        del_positive_paths.append(
            {"side": "out", "task": i, "s": s, "d": dv, "x": xv, "tau": tau, "path_up": up, "path_empty": len(path) == 0}
        )

    return {
        "del_positive_without_positive_x_count": len(del_positive_no_x),
        "del_positive_without_positive_x_samples": del_positive_no_x[:20],
        "d_exceeds_x_count": len(d_exceeds_x),
        "d_exceeds_x_samples": d_exceeds_x[:20],
        "positive_x_zero_tau_count": len(x_positive_not_in_cost),
        "positive_x_zero_tau_samples": x_positive_not_in_cost,
        "manual_bandwidth_from_positive_x": charged_x_total,
        "del_on_zero_tau_paths_count": sum(1 for r in del_positive_paths if r["tau"] <= TOL and r["d"] > TOL),
        "del_on_zero_tau_paths_samples": [r for r in del_positive_paths if r["tau"] <= TOL and r["d"] > TOL][:20],
    }


def load_csv_row(path: Path, gs: float, gf: float) -> dict | None:
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if abs(float(r["gamma_sla"]) - gs) < 1e-9 and abs(float(r["gamma_sf"]) - gf) < 1e-9:
                return r
    return None


def compare_smoke_vs_ssot(smoke_path: Path, ssot_path: Path, point_diags: list[dict]) -> list[dict]:
    rows = []
    for pt in point_diags:
        gs, gf = pt["gamma_sla"], pt["gamma_sf"]
        smoke = load_csv_row(smoke_path, gs, gf)
        ssot = load_csv_row(ssot_path, gs, gf)
        if not smoke or not ssot:
            continue
        smoke_cost = _f(smoke.get("monetary_cost") or smoke.get("cost"))
        ssot_cost = _f(ssot.get("monetary_cost") or ssot.get("cost"))
        smoke_bw = _f(smoke.get("bandwidth_cost"))
        ssot_bw = _f(ssot.get("bandwidth_cost"))
        smoke_cp = _f(smoke.get("compute_cost"))
        ssot_cp = _f(ssot.get("compute_cost"))
        if smoke_bw is None and smoke_cost is not None and smoke_cp is not None:
            smoke_bw = smoke_cost - smoke_cp
        rows.append(
            {
                "gamma_sla": gs,
                "gamma_sf": gf,
                "placement_match": pt.get("placement_signature") == _smoke_placement_hint(smoke, pt),
                "current_placement": pt.get("placement_signature"),
                "smoke_cost": smoke_cost,
                "ssot_cost": ssot_cost,
                "cost_delta": (ssot_cost - smoke_cost) if smoke_cost and ssot_cost else None,
                "smoke_exp_deliver": _f(smoke.get("exp_deliver")),
                "ssot_exp_deliver": _f(ssot.get("exp_deliver")),
                "smoke_posthoc_sla": _f(smoke.get("posthoc_cvar_sla")),
                "ssot_posthoc_sla": _f(ssot.get("posthoc_cvar_sla")),
                "smoke_posthoc_sf": _f(smoke.get("posthoc_cvar_sf")),
                "ssot_posthoc_sf": _f(ssot.get("posthoc_cvar_sf")),
                "smoke_compute": smoke_cp,
                "ssot_compute": ssot_cp,
                "smoke_bandwidth": smoke_bw,
                "ssot_bandwidth": ssot_bw,
                "bandwidth_delta": (ssot_bw - smoke_bw) if smoke_bw is not None and ssot_bw is not None else None,
                "cost_diff_source": _cost_diff_source(smoke_cp, ssot_cp, smoke_bw, ssot_bw),
                "path_level_note": pt.get("path_usage_summary"),
            }
        )
    return rows


def _smoke_placement_hint(smoke_row, pt) -> str | None:
    # smoke CSV lacks placement; use diagnostic re-solve placement as proxy for "current"
    return pt.get("placement_signature")


def _cost_diff_source(smoke_cp, ssot_cp, smoke_bw, ssot_bw) -> str:
    parts = []
    if smoke_cp is not None and ssot_cp is not None and abs(smoke_cp - ssot_cp) > 1:
        parts.append("compute")
    if smoke_bw is not None and ssot_bw is not None and abs(smoke_bw - ssot_bw) > 1:
        parts.append("bandwidth")
    return "+".join(parts) if parts else "negligible"


def classify_recommendation(p_cand_audit: list[dict], point_diags: list[dict], comparisons: list[dict]) -> dict:
    anomaly_empty = [r for r in p_cand_audit if r["is_anomaly_empty_path"]]
    nonempty_tau0 = [r for r in p_cand_audit if r["is_nonempty_tau_zero"]]
    del_no_x = sum(pt["coupling_checks"]["del_positive_without_positive_x_count"] for pt in point_diags)
    d_gt_x = sum(pt["coupling_checks"]["d_exceeds_x_count"] for pt in point_diags)
    pos_x_tau0 = sum(pt["coupling_checks"]["positive_x_zero_tau_count"] for pt in point_diags)
    del_tau0 = sum(pt["coupling_checks"]["del_on_zero_tau_paths_count"] for pt in point_diags)

    scheme3_triggers = bool(anomaly_empty or nonempty_tau0 or del_no_x or d_gt_x)
    bandwidth_multiplex = any(
        abs(c.get("bandwidth_delta") or 0) > 100 for c in comparisons if c.get("placement_match")
    )

    if scheme3_triggers:
        scheme = 3
        reason = "path/coupling bug signals detected"
    elif pos_x_tau0 > 0 or del_tau0 > 0 or bandwidth_multiplex:
        scheme = 2
        reason = "risk/placement OK but monetary_cost non-unique via zero-cost paths"
    else:
        scheme = 1
        reason = "cost axis appears stable"

    return {
        "recommended_scheme": scheme,
        "reason": reason,
        "counts": {
            "anomaly_empty_paths_in_catalog": len(anomaly_empty),
            "nonempty_tau_zero_paths": len(nonempty_tau0),
            "del_positive_without_x": del_no_x,
            "d_exceeds_x": d_gt_x,
            "positive_x_zero_tau": pos_x_tau0,
            "del_on_zero_tau_paths": del_tau0,
        },
    }


def write_markdown(out_path: Path, report: dict) -> None:
    rec = report["recommendation"]
    scheme = rec["recommended_scheme"]
    lines = [
        "# Phase C-0: Cost-Axis Determinacy Diagnosis",
        "",
        "## Executive summary",
        "",
        f"- **Recommended scheme:** {scheme} ({rec['reason']})",
        f"- **Paper cost-risk SSOT (`p0_gamma_frontier_b4_tasks8.csv`):** {report['ssot_verdict']}",
        "",
        "## Task A: Four diagnostic points",
        "",
    ]
    for pt in report["point_diagnostics"]:
        lines += [
            f"### Γ_sla={pt['gamma_sla']}, Γ_sf={pt['gamma_sf']}",
            "",
            f"| Field | Value |",
            f"|:---|:---|",
            f"| objective | {pt['objective']:.4f} |",
            f"| monetary_cost | {pt['monetary_cost']:.4f} |",
            f"| compute_cost | {pt['compute_cost']:.4f} |",
            f"| bandwidth_cost | {pt['bandwidth_cost']:.4f} |",
            f"| expected_delivery | {pt['expected_delivery']:.4f} |",
            f"| posthoc_cvar_sla | {pt['posthoc_cvar_sla']} |",
            f"| posthoc_cvar_sf | {pt['posthoc_cvar_sf']} |",
            f"| placement | `{pt['placement_signature']}` |",
            "",
            f"- empty/zero-cost path usage: {json.dumps(pt['path_usage_summary'], ensure_ascii=False)}",
            f"- positive ingress flows: {len(pt['ingress_flows_positive_x'])}",
            f"- positive egress flows: {len(pt['egress_flows_positive_x'])}",
            "",
        ]

    lines += ["## Task B: P_cand path catalog audit", ""]
    audit = report["p_cand_audit_summary"]
    lines += [
        f"- zero-hop local paths (u==v, empty): **{audit['zero_hop_local_count']}**",
        f"- anomaly empty paths (u!=v, empty): **{audit['anomaly_empty_count']}**",
        f"- non-empty tau_p=0 paths: **{audit['nonempty_tau_zero_count']}**",
        "",
    ]
    if audit["anomaly_empty_samples"]:
        lines.append("Anomaly samples:")
        for s in audit["anomaly_empty_samples"][:10]:
            lines.append(f"- ({s['u']},{s['v']}) p={s['path_id']}")
        lines.append("")

    lines += ["## Task C: Cost–delivery coupling", ""]
    for pt in report["point_diagnostics"]:
        cc = pt["coupling_checks"]
        lines.append(
            f"- Γ=({pt['gamma_sla']},{pt['gamma_sf']}): "
            f"del w/o x={cc['del_positive_without_positive_x_count']}, "
            f"d>x={cc['d_exceeds_x_count']}, "
            f"x tau=0={cc['positive_x_zero_tau_count']}, "
            f"del on tau=0 paths={cc['del_on_zero_tau_paths_count']}"
        )
    lines += ["", "## Task D: Smoke vs SSOT candidate", "", "| Γ | placement | smoke cost | SSOT cost | Δbw | posthoc SF match |", "|:---|:---|---:|---:|---:|:---|"]
    for c in report["smoke_vs_ssot"]:
        sf_match = abs((c.get("smoke_posthoc_sf") or 0) - (c.get("ssot_posthoc_sf") or 0)) < 1e-5
        lines.append(
            f"| ({c['gamma_sla']},{c['gamma_sf']}) | current vs smoke placement see JSON | "
            f"{c.get('smoke_cost')} | {c.get('ssot_cost')} | {c.get('bandwidth_delta')} | {sf_match} |"
        )
    lines += [
        "",
        "## Task E: Recommendation",
        "",
        report["recommendation_text"],
        "",
        "## Task F: Secondary costing (design only)",
        "",
        report["secondary_costing_design"],
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase C-0 cost axis diagnosis")
    ap.add_argument("--smoke-csv", default="results/temp_smoke_posthoc_gamma/uniform_frontier_b4_tasks8_posthoc_gamma.csv")
    ap.add_argument("--ssot-csv", default="results/p0_uniform_v2/p0_gamma_frontier_b4_tasks8.csv")
    ap.add_argument("--json-out", default="results/p0_uniform_v2/cost_axis_diagnosis.json")
    ap.add_argument("--md-out", default="results/p0_uniform_v2/cost_axis_diagnosis.md")
    args = ap.parse_args(argv)

    from run_gamma_frontier import load_p0_data

    data = load_p0_data(
        base_path="./data",
        topology="B4",
        num_tasks=8,
        k_paths=4,
        eta=1.3,
        joint_demand_scale=None,
        routing_mode="per_task_od",
        s2_derate=0.4,
        s1_link_k=4,
        s1_sigma=0.8,
        link_price_mode="uniform",
        quiet=True,
    )

    p_cand_audit = audit_p_cand(data)
    point_diags = [diagnose_point(data, gs, gf) for gs, gf in POINTS]
    comparisons = compare_smoke_vs_ssot(Path(args.smoke_csv), Path(args.ssot_csv), point_diags)
    recommendation = classify_recommendation(p_cand_audit, point_diags, comparisons)

    audit_summary = {
        "zero_hop_local_count": sum(1 for r in p_cand_audit if r["is_zero_hop_local"]),
        "anomaly_empty_count": sum(1 for r in p_cand_audit if r["is_anomaly_empty_path"]),
        "nonempty_tau_zero_count": sum(1 for r in p_cand_audit if r["is_nonempty_tau_zero"]),
        "anomaly_empty_samples": [r for r in p_cand_audit if r["is_anomaly_empty_path"]][:20],
    }

    scheme = recommendation["recommended_scheme"]
    if scheme == 1:
        ssot_verdict = "cost-risk SSOT acceptable for paper figures"
        rec_text = "**Scheme 1:** Current monetary_cost is legitimate; cost axis may be used directly."
    elif scheme == 2:
        ssot_verdict = "risk SSOT yes; cost axis defer until secondary costing"
        rec_text = (
            "**Scheme 2:** Posthoc risk / placement structure is usable. "
            "Monetary_cost is non-unique due to zero-hop zero-tariff x-flow multiplexing. "
            "Defer cost-axis figures; use secondary costing (Task F) for stable C^bw."
        )
    else:
        ssot_verdict = "not SSOT — fix path/coupling bugs first"
        rec_text = "**Scheme 3:** Fix path construction or cost/delivery coupling before any paper cost figure."

    secondary_design = (
        "Fix y and delivery (or Del) from stage-1 optimum. Stage-2: min sum tau_p x subject to "
        "d<=x and d<=A_p x, same placement. This does NOT change y or CVaR if Del is fixed; "
        "only selects minimum-bandwidth x representative. Suitable for reporting axis; "
        "label as 'minimum-bandwidth cost representative' distinct from Model C obj."
    )

    report = {
        "phase": "C-0",
        "points": POINTS,
        "p_cand_audit": p_cand_audit,
        "p_cand_audit_summary": audit_summary,
        "point_diagnostics": point_diags,
        "smoke_vs_ssot": comparisons,
        "recommendation": recommendation,
        "recommended_scheme": scheme,
        "ssot_verdict": ssot_verdict,
        "recommendation_text": rec_text,
        "secondary_costing_design": secondary_design,
    }

    json_path = Path(args.json_out)
    md_path = Path(args.md_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")
    write_markdown(md_path, report)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Scheme {scheme}: {recommendation['reason']}")
    print(f"SSOT verdict: {ssot_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
