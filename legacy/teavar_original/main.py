import argparse
import time
import numpy as np
from gurobipy import GRB

# 数据路径
BASE_DATA_PATH = "./data"


def _run_teavar_paper(args):
    import parsers
    import util
    from TEAVAR_Gurobi import TEAVAR

    edges, capacity, _, nodes = parsers.read_topology(args.topology, BASE_DATA_PATH, downscale=1.0)

    link_probs = util.weibull_probs(len(edges), shape=0.8, scale=0.00001)
    scenarios, scenario_probs = util.sub_scenarios(link_probs, 1e-5)

    print(f"--- [teavar] 拓扑: {args.topology} | Beta: {args.beta} | 场景数: {len(scenarios)} ---")

    results = []
    for i in range(args.iterations):
        demands, flows = parsers.read_demand(
            args.topology,
            len(nodes),
            BASE_DATA_PATH,
            num_demand=i,
            scale=args.scale,
            downscale=2.0,
        )

        T, Tf, _ = parsers.get_tunnels(nodes, edges, flows, k=args.k)

        start_t = time.time()
        res = TEAVAR(edges, capacity, flows, demands, args.beta, T, Tf, scenarios, scenario_probs)

        if res:
            avail = (1.0 - res["alpha"]) * 100
            print(f"迭代 {i}: VaR(alpha) = {res['alpha']:.6f} | 可用性 = {avail:.4f}% | 耗时 {time.time() - start_t:.2f}s")
            results.append(avail)

    if results:
        print(f"\n平均保障吞吐率 (1-alpha): {np.mean(results):.4f}%")


def _load_joint_data_from_args(args):
    from b4_joint_data import load_joint_data

    if getattr(args, "eta", None) is not None:
        demand_scale = 1.0
        eta = float(args.eta)
        demand_scale_explicit = False
    elif getattr(args, "joint_demand_scale", None) is not None:
        demand_scale = float(args.joint_demand_scale)
        eta = None
        demand_scale_explicit = True
    else:
        demand_scale = 25.0
        eta = None
        demand_scale_explicit = True

    return load_joint_data(
        base_path=BASE_DATA_PATH,
        topology_name=args.topology,
        hub_index=args.hub,
        num_tasks=args.joint_num_tasks,
        demand_row=args.joint_demand_row,
        demand_downscale=args.demand_downscale,
        demand_scale=demand_scale,
        k_paths=args.joint_k_paths,
        stress_zero_s1=args.joint_stress_zero_s1,
        virtual_source=args.joint_virtual_source and not args.joint_umcf_teavar,
        virtual_source_sigma=args.joint_virtual_sigma,
        virtual_sink_sigma=args.joint_virtual_sink_sigma,
        umcf_virtual_nodes=_joint_umcf_virtual_nodes(args, _joint_routing_mode(args)),
        umcf_access_sigma=args.joint_umcf_sigma,
        umcf_sink_access_sigma=args.joint_umcf_sink_sigma,
        scenario_s2_derate=args.joint_scenario_s2_derate,
        scenario_s1_link_k=getattr(args, "joint_s1_link_k", 4),
        scenario_s1_link_sigma=getattr(args, "joint_s1_sigma", 0.80),
        routing_mode=_joint_routing_mode(args),
        eta=eta,
        demand_scale_explicit=demand_scale_explicit,
    )


def _joint_routing_mode(args) -> str:
    if getattr(args, "joint_umcf_per_task", False):
        return "umcf_per_task"
    if getattr(args, "joint_per_task_od", False):
        return "per_task_od"
    rm = getattr(args, "routing_mode", "hub") or "hub"
    if rm == "hub" and getattr(args, "joint_umcf_teavar", False):
        return "umcf_global"
    return rm


def _joint_umcf_virtual_nodes(args, routing_mode: str) -> bool:
    if routing_mode == "umcf_global":
        return True
    if routing_mode == "umcf_per_task":
        return False
    return bool(getattr(args, "joint_umcf_teavar", False))


def _run_joint_model_c(args, data):
    """Model A 标定 Γ → Model C（ε-约束部署，论文主表推荐路径）。"""
    from gurobipy import GRB
    from duibi_metrics import expected_total_delivered_volume
    from teavar_framework_models import build_teavar_model_a, build_teavar_model_c

    lam = args.joint_calib_lambda
    lam_sf = args.joint_lambda_compute_sf
    print(
        f"\n--- [Model C] 标定 λ={lam}, λ_sf={lam_sf} → Γ_sla/Γ_sf → min cost ---"
    )

    ma, ca, lva, sva, ya, *_ = build_teavar_model_a(
        data,
        lambda_sla=lam,
        lambda_sf=lam_sf,
        omega_deliver=args.joint_omega,
        beta_loss=args.joint_beta_loss,
        beta_sf=args.joint_beta_compute_sf,
        min_tasks_off_hub=args.joint_min_off_hub,
    )
    if ma.status != GRB.OPTIMAL or lva is None:
        print(f"  Model A 标定失败 | status={ma.status}")
        return

    if args.joint_gamma_sla is not None:
        g_sla = float(args.joint_gamma_sla)
    else:
        g_sla = max(float(lva) * args.joint_gamma_sla_slack, 1e-9)

    include_sf = lam_sf > 0
    if args.joint_gamma_sf is not None:
        g_sf = float(args.joint_gamma_sf)
    elif include_sf and (sva or 0) > 1e-12:
        g_sf = max(float(sva) * args.joint_gamma_sf_slack + 0.01, 1e-9)
    else:
        g_sf = None
        include_sf = False

    print(
        f"  Model A 标定 | cost={ca:.3f} | SLA_CVaR={lva:.4f} | sf_CVaR={sva or 0.0:.4f}"
    )
    print(
        f"  Model C 预算 | Γ_sla={g_sla:.4f}"
        + (f" | Γ_sf={g_sf:.4f}" if include_sf else " | (无 sf 预算)")
    )

    mc, cc, lvc, svc, yc, xin_c, xout_c, din_c, dout_c = build_teavar_model_c(
        data,
        gamma_sla=g_sla,
        gamma_sf=g_sf,
        omega_deliver=args.joint_omega,
        beta_loss=args.joint_beta_loss,
        beta_sf=args.joint_beta_compute_sf,
        min_tasks_off_hub=args.joint_min_off_hub,
        include_sf_budget=include_sf,
    )
    if mc.status == GRB.OPTIMAL and cc is not None:
        ev = expected_total_delivered_volume(data, mc, din_c, dout_c) or 0.0
        print(
            f"  Model C      | cost={cc:.3f} | SLA_CVaR={lvc:.4f} | sf_CVaR={svc or 0.0:.4f} | "
            f"E[del_vol]={ev:.3f}"
        )
    else:
        print(f"  Model C      | status={mc.status}")


def _run_joint(args):
    from duibi import build_single_layer_model
    from cvar_compare import build_teavar_sla_cvar_model

    lambdas = [float(x.strip()) for x in args.joint_lambdas.split(",") if x.strip()]

    data = _load_joint_data_from_args(args)

    print(
        f"--- [joint] {args.topology} 联合放置 + CVaR | hub={args.hub} | 任务数={len(data.I)} | "
        f"joint_k_paths={args.joint_k_paths} | demand_scale={args.joint_demand_scale} | "
        f"stress_s1_hub_out={args.joint_stress_zero_s1} | umcf_teavar_sla={args.joint_umcf_teavar}"
        + (
            f" | V_s={getattr(data, 'umcf_vs', '')}, V_t={getattr(data, 'umcf_vt', '')} | σ_umcf={args.joint_umcf_sigma}"
            + (
                f", σ_umcf_sink={args.joint_umcf_sink_sigma}"
                if args.joint_umcf_sink_sigma is not None
                else ""
            )
            if args.joint_umcf_teavar
            else (
                f" | virtual_source={args.joint_virtual_source}"
                + (
                    f" (σ_vs={args.joint_virtual_sigma}"
                    + (
                        f", σ_vt={args.joint_virtual_sink_sigma})"
                        if args.joint_virtual_sink_sigma is not None
                        else ")"
                    )
                    if args.joint_virtual_source
                    else ""
                )
            )
        )
        + " ---"
    )
    print(
        f"--- lambdas = {lambdas} | omega(teavar_sla) = {args.joint_omega} | min_off_hub = {args.joint_min_off_hub} | "
        f"lambda_node(teavar) = {args.joint_lambda_node} | lambda_compute_sf = {args.joint_lambda_compute_sf} ---"
    )
    if args.joint_lambda_node and args.joint_lambda_node > 0:
        print(
            "说明：obj_full = cost + λ·SLA_CVaR + λn·nodeUtil_CVaR + λsf·computeSf_CVaR - ω·E[del]；"
            "λ 只作用于 SLA，λn=--joint-lambda-node，λsf=--joint-lambda-compute-sf。"
        )
    elif args.joint_lambda_compute_sf and args.joint_lambda_compute_sf > 0:
        print(
            "说明：obj_full = cost + λ·SLA_CVaR + λsf·computeSf_CVaR - ω·E[del]（λn=0 时无利用率 CVaR 项）。"
        )
    print(
        "提示：若 teavar_sla 在各 λ 下仍相同，可试增大 --joint-lambda-node、--joint-demand-scale，或提高 --joint-k-paths / --joint-num-tasks。"
    )
    for lam in lambdas:
        print(f"\n# lambda = {lam}")
        mp, cp, ncv, lcv, yp, xin_p, xout_p = build_single_layer_model(data, lambda_val=lam)
        if mp.status == GRB.OPTIMAL:
            phys_risk = ncv + lcv
            print(
                f"  physical     | cost={cp:.3f} | node+link CVaR={phys_risk:.4f} | "
                f"obj_full={cp + lam * phys_risk:.3f}"
            )
        else:
            print(f"  physical     | status={mp.status}")

        mt, ct, ltv, ntv, sfv, yt, xin_t, xout_t, din_t, dout_t = build_teavar_sla_cvar_model(
            data,
            lambda_cvar=lam,
            omega_deliver=args.joint_omega,
            beta_loss=args.joint_beta_loss,
            min_tasks_off_node0=args.joint_min_off_hub,
            lambda_node_cvar=args.joint_lambda_node,
            beta_node=args.joint_beta_node,
            lambda_compute_sf_cvar=args.joint_lambda_compute_sf,
            beta_compute_sf=args.joint_beta_compute_sf,
        )
        if mt.status == GRB.OPTIMAL and ct is not None and ltv is not None:
            from duibi_metrics import expected_total_delivered_volume

            ev = expected_total_delivered_volume(data, mt, din_t, dout_t) or 0.0
            lam_n = args.joint_lambda_node
            lam_sf = args.joint_lambda_compute_sf
            obj_full = ct + lam * ltv + lam_n * (ntv or 0.0) + lam_sf * (sfv or 0.0) - args.joint_omega * ev
            print(
                f"  teavar_sla   | cost={ct:.3f} | SLA_CVaR={ltv:.4f} | nodeUtil_CVaR={ntv or 0.0:.4f} | "
                f"computeSf_CVaR={sfv or 0.0:.4f} | obj_full={obj_full:.3f} | E[del_vol]={ev:.3f}"
            )
        else:
            print(f"  teavar_sla   | status={mt.status}")

    if args.joint_run_model_c:
        _run_joint_model_c(args, data)


def _run_monetary(args):
    from monetary_cvar import (
        build_monetary_cvar_model,
        build_monetary_cvar_model_c,
        compare_with_model_a,
        print_monetary_result,
        print_scenario_breakdown,
    )

    data = _load_joint_data_from_args(args)
    print(
        f"--- [monetary] {args.topology} | |I|={len(data.I)} | kappa={args.monetary_kappa} | "
        f"min_off_hub={args.joint_min_off_hub} | stress_s1={args.joint_stress_zero_s1} ---"
    )

    if args.monetary_compare_a:
        compare_with_model_a(
            data,
            kappa_sum=args.monetary_kappa,
            kappa_max=args.monetary_kappa_max,
            kappa_sf=args.monetary_kappa_sf,
            lambda_sla=args.monetary_lambda_sla,
            omega=args.joint_omega,
            beta=args.monetary_beta,
            min_tasks_off_hub=args.joint_min_off_hub,
            show_scenarios=args.monetary_scenario,
            mip_gap=args.monetary_mip_gap,
        )
        return

    if args.monetary_gamma is not None:
        r = build_monetary_cvar_model_c(
            data,
            args.monetary_gamma,
            kappa_sum=args.monetary_kappa,
            kappa_max=args.monetary_kappa_max,
            kappa_sf=args.monetary_kappa_sf,
            beta=args.monetary_beta,
            min_tasks_off_hub=args.joint_min_off_hub,
            mip_gap=args.monetary_mip_gap,
        )
        print_monetary_result("Model M-C", r)
    else:
        r = build_monetary_cvar_model(
            data,
            kappa_sum=args.monetary_kappa,
            kappa_max=args.monetary_kappa_max,
            kappa_sf=args.monetary_kappa_sf,
            beta=args.monetary_beta,
            min_tasks_off_hub=args.joint_min_off_hub,
            mip_gap=args.monetary_mip_gap,
        )
        print_monetary_result("Model M", r)

    if args.monetary_scenario and r.status == GRB.OPTIMAL:
        print_scenario_breakdown("Model M/M-C", r, data, kappa_sum=args.monetary_kappa)


def main():
    parser = argparse.ArgumentParser(
        description="TEAVAR 复现 (teavar) | 联合 CVaR 扫描 (joint) | 货币化 M/M-C (monetary)"
    )
    parser.add_argument("--topology", type=str, default="B4")
    parser.add_argument("--mode", type=str, default="teavar", choices=("teavar", "joint", "monetary"))
    parser.add_argument("--beta", type=float, default=0.999)
    parser.add_argument("--k", type=int, default=12)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--demand_downscale", type=float, default=2.0)
    parser.add_argument("--topo_downscale", type=float, default=1.0)

    parser.add_argument("--hub", type=int, default=0, help="joint：作为流量中心的节点下标（0=s1）")
    parser.add_argument("--joint-num-tasks", type=int, default=10)
    parser.add_argument("--joint-demand-row", type=int, default=0)
    parser.add_argument(
        "--joint-demand-scale",
        type=float,
        default=None,
        help="joint：显式 b_in/b_out 缩放（覆盖 --eta）；未指定且未指定 --eta 时默认 25",
    )
    parser.add_argument(
        "--joint-k-paths",
        type=int,
        default=4,
        help="joint：hub↔节点 候选最短路条数（B4 建议 ≥4 以增加绕路）",
    )
    parser.add_argument("--joint-lambdas", type=str, default="0.5,5,50")
    parser.add_argument("--joint-omega", type=float, default=1.0)
    parser.add_argument("--joint-beta-loss", type=float, default=None)
    parser.add_argument("--joint-min-off-hub", type=int, default=0)
    parser.add_argument(
        "--joint-stress-zero-s1",
        action="store_true",
        help="joint：场景1 切断 hub 的所有出边（与 cvar_compare 玩具 stress 同构）",
    )
    parser.add_argument(
        "--joint-virtual-source",
        action="store_true",
        help="joint：为数据设置 sigma_vs/sigma_vt，在 teavar_sla 等模型中加虚拟接入瓶颈（缓解 hub 空路径退化）",
    )
    parser.add_argument(
        "--joint-virtual-sigma",
        type=float,
        default=0.99,
        help="joint：虚拟源边 (V_s,m) 可用率 sigma_vs[m,s] 常数（建议略小于 1）",
    )
    parser.add_argument(
        "--joint-virtual-sink-sigma",
        type=float,
        default=None,
        help="joint：虚拟汇边可用率；默认与 --joint-virtual-sigma 相同",
    )
    parser.add_argument(
        "--joint-umcf-teavar",
        action="store_true",
        help="joint：扩展显式 V_s,V_t 与 (V_s,m)/(m,V_t) 边，仅 teavar_sla 用 UMCF 锚点；与 --joint-virtual-source 互斥（本开关优先，不传则 sigma_vs 瓶颈）",
    )
    parser.add_argument(
        "--joint-umcf-sigma",
        type=float,
        default=0.99,
        help="joint：UMCF 边 (V_s,m) 在各场景下的可用率 σ",
    )
    parser.add_argument(
        "--joint-umcf-sink-sigma",
        type=float,
        default=None,
        help="joint：UMCF 边 (m,V_t) 的可用率；默认与 --joint-umcf-sigma 相同",
    )
    parser.add_argument(
        "--joint-lambda-node",
        type=float,
        default=0.5,
        help="teavar_sla：算力利用率 CVaR 权重（0=仅 SLA CVaR，与原版一致）",
    )
    parser.add_argument(
        "--joint-beta-node",
        type=float,
        default=None,
        help="teavar_sla 算力利用率 CVaR 的 β",
    )
    parser.add_argument(
        "--joint-lambda-compute-sf",
        type=float,
        default=1.0,
        help="teavar_sla：算力未满足 CVaR 权重（Method 主实验建议 >0；0=仅链路 SLA 消融）",
    )
    parser.add_argument(
        "--joint-ablation-no-compute-sf",
        action="store_true",
        help="joint：等价于 --joint-lambda-compute-sf 0（消融）",
    )
    parser.add_argument(
        "--joint-beta-compute-sf",
        type=float,
        default=None,
        help="算力未满足 CVaR 的 β",
    )
    parser.add_argument(
        "--joint-run-model-c",
        action="store_true",
        help="joint：λ 扫描结束后，用 Model A 标定 Γ 并求解 Model C（论文主表路径）",
    )
    parser.add_argument(
        "--joint-calib-lambda",
        type=float,
        default=50.0,
        help="Model C 标定时 Model A 的 λ_sla",
    )
    parser.add_argument(
        "--joint-gamma-sla",
        type=float,
        default=None,
        help="Model C 的 Γ_sla；缺省 = A 的 SLA_CVaR × --joint-gamma-sla-slack",
    )
    parser.add_argument(
        "--joint-gamma-sf",
        type=float,
        default=None,
        help="Model C 的 Γ_sf；缺省 = A 的 sf_CVaR × --joint-gamma-sf-slack + 0.01",
    )
    parser.add_argument(
        "--joint-gamma-sla-slack",
        type=float,
        default=1.5,
        help="Model C：Γ_sla = SLA_CVaR(A) × 该系数（与 progressive_pipeline 一致）",
    )
    parser.add_argument(
        "--joint-gamma-sf-slack",
        type=float,
        default=2.0,
        help="Model C：Γ_sf = sf_CVaR(A) × 该系数 + 0.01",
    )
    parser.add_argument(
        "--joint-scenario-s2-derate",
        type=float,
        default=0.60,
        help="场景 s=2 下 aggregation 节点容量乘数（默认 0.60）",
    )
    parser.add_argument(
        "--joint-s1-sigma",
        type=float,
        default=0.80,
        dest="joint_s1_sigma",
        help="场景 s=1 top-k 链路部分降级 σ（默认 0.80；stress 时仍为 0）",
    )
    parser.add_argument(
        "--joint-s1-link-k",
        type=int,
        default=4,
        help="场景 s=1 按 prob_failure 降序影响的链数 k（默认 4）",
    )
    parser.add_argument(
        "--eta",
        type=float,
        default=None,
        help="joint：η 标定总 demand≈η·C_surv；指定后忽略默认 demand_scale=25",
    )
    parser.add_argument(
        "--routing-mode",
        choices=["hub", "per_task_od", "umcf_global", "umcf_per_task"],
        default="hub",
        help="任务路由：hub | per_task_od | umcf_global | umcf_per_task",
    )
    parser.add_argument(
        "--joint-per-task-od",
        action="store_true",
        help="joint：等价于 --routing-mode per_task_od",
    )
    parser.add_argument(
        "--joint-umcf-per-task",
        action="store_true",
        help="joint：等价于 --routing-mode umcf_per_task（每任务独立 V_s^(i), V_t^(i)）",
    )

    parser.add_argument("--monetary-kappa", type=float, default=5.0, help="monetary：kappa_sum")
    parser.add_argument("--monetary-kappa-max", type=float, default=0.0)
    parser.add_argument("--monetary-kappa-sf", type=float, default=0.0)
    parser.add_argument("--monetary-beta", type=float, default=None)
    parser.add_argument("--monetary-gamma", type=float, default=None, help="monetary：Model M-C 的 Gamma_money")
    parser.add_argument(
        "--monetary-compare-a",
        action="store_true",
        help="monetary：Model A vs M vs M-C 统一 κ 对比（默认仅解 Model M）",
    )
    parser.add_argument("--monetary-scenario", action="store_true", help="monetary：逐场景 L_s 分解")
    parser.add_argument("--monetary-mip-gap", type=float, default=0.01)
    parser.add_argument(
        "--monetary-lambda-sla",
        type=float,
        default=5.0,
        help="monetary --compare-a 时 Model A 的 lambda_sla",
    )

    args = parser.parse_args()

    if args.joint_ablation_no_compute_sf:
        args.joint_lambda_compute_sf = 0.0

    if args.joint_umcf_per_task and args.joint_per_task_od:
        parser.error("--joint-umcf-per-task 与 --joint-per-task-od 互斥")
    if args.joint_umcf_per_task and args.joint_umcf_teavar:
        parser.error("--joint-umcf-per-task 与 --joint-umcf-teavar（global UMCF）互斥")

    if args.joint_per_task_od:
        args.routing_mode = "per_task_od"
    if args.joint_umcf_per_task:
        args.routing_mode = "umcf_per_task"

    if args.mode == "teavar":
        _run_teavar_paper(args)
    elif args.mode == "joint":
        _run_joint(args)
    else:
        if args.monetary_beta is None:
            args.monetary_beta = 0.95
        _run_monetary(args)


if __name__ == "__main__":
    main()
