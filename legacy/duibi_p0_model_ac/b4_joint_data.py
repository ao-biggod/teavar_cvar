# -*- coding: utf-8 -*-
"""
将 data/B4 的拓扑、需求矩阵与 node_compute_resources.csv 转为
与 duibi / cvar_compare 相同字段的「联合放置 + hub 径向流量」数据对象。

语义（与玩具 UltraComplexData 对齐，便于复用现有 MILP）：
- 默认 `hub_index` 对应 B4 的 s1（常为 0）：**当前实现**为 Hub 径向——所有任务 ingress 为 hub→m，egress 为 m→hub（建模正文标准为每任务 $s_i\to m\to t_i$，见 `建模章节_算力网络联合优化.md`）。
- 可选 `umcf_virtual_nodes=True`（建议与 `main.py --joint-umcf-teavar` 同用）：为 TEAVAR SLA 模型显式增加
  \(V_s=\texttt{len(M)}\)、\(V_t=\texttt{len(M)+1}\)，边 \((V_s,m)\)、\((m,V_t)\) 写入 `E,B,sigma`，`P_{V_s,m}\)、\(P_{m,V_t}\)
  为单跳路径；`build_teavar_sla_cvar_model` 将 ingress/egress 锚在 \(V_s,V_t\)（`physical`/duibi 仍用 hub 径向）。
  与 `virtual_source`（`sigma_vs` 瓶颈）**不宜叠用**：启用 UMCF 时不写入 `sigma_vs`/`sigma_vt`。
- 任务流量规模来自 demand.txt 指定行中 (hub, dst) 元素，取前 num_tasks 条最大需求。
- 候选路径：在真实有向图上对 (hub,m)、(m,hub) 各取至多 k 条最短简单路径（按 hop 数）。
- 链路容量 B[e]：与 parsers.read_topology 相同换算（capacity_raw/1000）。
- 场景：s0 全通；s1 将拓扑文件中 prob_failure 最高的若干条边置为断链；s2 聚合层节点算力骤降。
"""
from __future__ import annotations

import csv
import os
import numpy as np

import parsers


def _enumerate_simple_paths_edges(adj: dict[int, list], src: int, tgt: int, max_hops: int = 20) -> list[list[tuple[int, int]]]:
    """有向图上枚举 src->tgt 的简单路径（边列表）。图很小 (B4) 时足够快。"""
    if src == tgt:
        return [[]]
    res: list[list[tuple[int, int]]] = []

    def dfs(u: int, visited: set[int], edge_path: list[tuple[int, int]]) -> None:
        if u == tgt:
            res.append(list(edge_path))
            return
        if len(edge_path) >= max_hops:
            return
        for w in adj.get(u, ()):
            if w in visited:
                continue
            visited.add(w)
            edge_path.append((u, w))
            dfs(w, visited, edge_path)
            edge_path.pop()
            visited.remove(w)

    vis = {src}
    dfs(src, vis, [])
    return res


def _build_nx_graph_from_adj(adj: dict[int, list]):
    """Build a networkx DiGraph once, reuse for all K-shortest path calls."""
    import networkx as nx
    G = nx.DiGraph()
    for u, neighbors in adj.items():
        for v in neighbors:
            G.add_edge(u, v)
    return G


def _k_shortest_edge_paths(
    adj: dict[int, list],
    source: int,
    target: int,
    k: int,
    _nx_graph=None,  # pre-built networkx graph for reuse
) -> list[list[tuple[int, int]]]:
    if source == target:
        return [[]]
    # Use networkx for efficient K-shortest simple paths (Yen-like algorithm)
    try:
        import networkx as nx
        from itertools import islice
        if _nx_graph is not None:
            G = _nx_graph
        else:
            G = nx.DiGraph()
            for u, neighbors in adj.items():
                for v in neighbors:
                    G.add_edge(u, v)
        paths = []
        for node_path in islice(nx.shortest_simple_paths(G, source, target, weight=None), k):
            edge_path = [(node_path[i], node_path[i+1]) for i in range(len(node_path)-1)]
            paths.append(edge_path)
        return paths if paths else [[]]
    except ImportError:
        pass
    # Fallback: DFS enumeration (only for very small graphs)
    max_hops = min(k + 10, 15)
    allp = _enumerate_simple_paths_edges(adj, source, target, max_hops=max_hops)
    allp.sort(key=lambda p: (len(p), p))
    out: list[list[tuple[int, int]]] = []
    seen: set[tuple[tuple[int, int], ...]] = set()
    for p in allp:
        t = tuple(p)
        if t in seen:
            continue
        seen.add(t)
        out.append(p)
        if len(out) >= min(k, 4):
            break
    return out if out else [[]]


def _read_compute_csv(csv_path: str) -> dict[int, dict]:
    """node_id 为 1..N，转为 0..N-1 索引。"""
    rows: dict[int, dict] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            nid = int(row["node_id"])
            idx = nid - 1
            rows[idx] = {
                "cpu_cap": float(row["cpu_capacity_units"]),
                "gpu_cap": float(row["gpu_capacity_units"]),
                "hbm_cap": float(row["hbm_capacity_units"]),
                "price_cpu": float(row["price_cpu"]),
                "price_gpu": float(row["price_gpu"]),
                "price_hbm": float(row["price_hbm"]),
                "role": row.get("role", ""),
            }
    return rows


def _read_topology_raw(topology_path: str, num_nodes: int) -> tuple[list, list]:
    """Fallback reader for topologies without prob_failure column (e.g. XNet).
    Returns (links, capacity) with 0-based indices."""
    lnks = []
    caps = []
    with open(topology_path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts or "to_node" in parts[0].lower():
                continue
            try:
                to_n = int(parts[0])
                from_n = int(parts[1])
                c = float(parts[2])
                # Auto-detect 0/1-based from min node ID
                lnks.append((from_n, to_n))
                caps.append(c / 1000.0)  # same scaling as parsers
            except (ValueError, IndexError):
                continue
    # Fix 1-based indexing
    if lnks:
        mn = min(min(u, v) for (u, v) in lnks)
        if mn >= 1:
            lnks = [(u - 1, v - 1) for (u, v) in lnks]
    return lnks, caps


def _read_topology_probs(topology_path: str, topo_is_0based: bool = False) -> list[tuple[int, int, float]]:
    """Return (src0, dst0, prob_failure) as 0-based indices.
    If topo_is_0based, node IDs in file are already 0-based so no shift needed."""
    shift = 0 if topo_is_0based else 1
    probs = []
    with open(topology_path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0] == "to_node":
                continue
            try:
                to_n = int(parts[0]) - shift
                from_n = int(parts[1]) - shift
                pf = float(parts[3]) if len(parts) > 3 else 0.001
                probs.append((from_n, to_n, pf))
            except (ValueError, IndexError):
                continue
    return probs


def stress_hub_outgoing_s1(data, hub: int = 0) -> None:
    """场景 1：切断 hub 的所有出边（与 cvar_compare 玩具 stress 同构）。"""
    for v in data.M:
        if v == hub:
            continue
        e = (hub, v)
        if e in data.sigma and 1 in data.sigma[e]:
            data.sigma[e][1] = 0.0


def _synthetic_demand(num_nodes: int):
    """Generate a plausible demand matrix for topologies without demand data.
    Uses a gravity model: demand proportional to node degree product."""
    rng = np.random.RandomState(42)
    deg = np.ones(num_nodes)
    # Give each node a random "population" weight
    for i in range(num_nodes):
        deg[i] = rng.uniform(0.5, 2.0)
    row = np.zeros(num_nodes * num_nodes, dtype=float)
    for src in range(num_nodes):
        for dst in range(num_nodes):
            if src != dst:
                row[src * num_nodes + dst] = deg[src] * deg[dst] * rng.uniform(500, 5000)
    return row.reshape(1, -1)


class B4JointData:
    """与 UltraComplexData 同构字段，供 build_single_layer_model / build_teavar_sla_cvar_model 使用。请用 load_b4_joint_data 填充。"""

    routing_mode: str = "hub"  # hub | per_task_od | umcf_global | umcf_per_task | dag (后三者占位)


def _paths_reachable(P_cand: dict, u: int, v: int) -> bool:
    """P_cand[(u,v)] 存在至少一条非空路径（u==v 时视为可达）。"""
    if u == v:
        return True
    paths = P_cand.get((u, v), [[]])
    return bool(paths) and any(paths)


def _build_valid_assign_hub(
    I: list[int], M: list[int], hub: int, P_cand: dict
) -> dict[tuple[int, int], bool]:
    valid_assign: dict[tuple[int, int], bool] = {}
    for i in I:
        for m in M:
            if m == hub:
                valid_assign[i, m] = True
            else:
                ph = P_cand[hub, m]
                pr = P_cand[m, hub]
                ok = bool(ph) and any(ph) and bool(pr) and any(pr)
                if ok:
                    valid_assign[i, m] = True
    return valid_assign


def _build_valid_assign_per_task_od(
    I: list[int],
    M: list[int],
    task_src: dict[int, int],
    task_dst: dict[int, int],
    P_cand: dict,
) -> dict[tuple[int, int], bool]:
    valid_assign: dict[tuple[int, int], bool] = {}
    for i in I:
        src = task_src[i]
        dst = task_dst[i]
        for m in M:
            if _paths_reachable(P_cand, src, m) and _paths_reachable(P_cand, m, dst):
                valid_assign[i, m] = True
    return valid_assign


def _build_valid_assign_umcf_per_task(
    I: list[int],
    M: list[int],
    umcf_task_src: dict[int, int],
    umcf_task_dst: dict[int, int],
    P_cand: dict,
) -> dict[tuple[int, int], bool]:
    """umcf_per_task：valid_assign[i,m] 当且仅当 V_s^(i)→m 与 m→V_t^(i) 均有非空路径。"""
    valid_assign: dict[tuple[int, int], bool] = {}
    for i in I:
        vs = umcf_task_src[i]
        vt = umcf_task_dst[i]
        for m in M:
            if _paths_reachable(P_cand, vs, m) and _paths_reachable(P_cand, m, vt):
                valid_assign[i, m] = True
    return valid_assign


def _umcf_per_task_virtual_ids(n_phys: int, num_tasks: int) -> tuple[dict[int, int], dict[int, int]]:
    """
    虚拟节点编号：V_s^(i) = n + i，V_t^(i) = n + |I| + i（n 为物理节点数 len(M)）。
    """
    umcf_task_src: dict[int, int] = {}
    umcf_task_dst: dict[int, int] = {}
    for i in range(num_tasks):
        umcf_task_src[i] = n_phys + i
        umcf_task_dst[i] = n_phys + num_tasks + i
    return umcf_task_src, umcf_task_dst


def _attach_umcf_per_task_graph_dicts(
    M: list[int],
    I: list[int],
    S: list[int],
    B: dict,
    sigma: dict,
    P_cand: dict,
    E_list: list,
    access_sigma: float,
    sink_access_sigma: float | None,
) -> tuple[dict[int, int], dict[int, int]]:
    """
    为每个任务 i 附加独立 V_s^(i), V_t^(i) 及 (V_s^(i),m)、(m,V_t^(i)) 虚拟边与单跳路径。
    仅生成本模式所需 P_cand 键，避免全图笛卡尔积。
    """
    n_phys = len(M)
    umcf_task_src, umcf_task_dst = _umcf_per_task_virtual_ids(n_phys, len(I))
    sig_u = float(access_sigma)
    sig_t = float(sink_access_sigma) if sink_access_sigma is not None else sig_u
    Bcap = max(float(v) for v in B.values()) if B else 1e9
    for i in I:
        vs = umcf_task_src[i]
        vt = umcf_task_dst[i]
        P_cand[vs, vs] = [[]]
        P_cand[vt, vt] = [[]]
        for mm in M:
            evs = (vs, mm)
            evt = (mm, vt)
            B[evs] = float(Bcap)
            B[evt] = float(Bcap)
            sigma[evs] = {s: sig_u for s in S}
            sigma[evt] = {s: sig_t for s in S}
            P_cand[vs, mm] = [[(vs, mm)]]
            P_cand[mm, vt] = [[(mm, vt)]]
            E_list.append(evs)
            E_list.append(evt)
    return umcf_task_src, umcf_task_dst


def attach_umcf_per_task(
    data,
    I: list[int] | None = None,
    access_sigma: float = 1.0,
    sink_access_sigma: float | None = None,
) -> tuple[dict[int, int], dict[int, int]]:
    """
    对已有数据对象就地附加 **每任务独立** UMCF 虚拟源/汇。

    - ``data.umcf_task_src[i]`` / ``data.umcf_task_dst[i]``：流锚点（TEAVAR ingress/egress）。
    - ``data.physical_task_src/dst``：保留物理 OD（若尚未设置则从 ``task_src/dst`` 拷贝）。
    - ``data.M`` 仍为物理放置节点集合；虚拟节点仅出现在 ``P_cand``/``E``/``B``/``sigma`` 中。
    """
    if getattr(data, "umcf_per_task_nodes", False):
        return dict(data.umcf_task_src), dict(data.umcf_task_dst)

    task_ids = list(I if I is not None else data.I)
    M = list(data.M)
    S = list(data.S)
    E_list = list(data.E)

    umcf_task_src, umcf_task_dst = _attach_umcf_per_task_graph_dicts(
        M,
        task_ids,
        S,
        data.B,
        data.sigma,
        data.P_cand,
        E_list,
        access_sigma,
        sink_access_sigma,
    )
    data.E = list(data.B.keys())

    if not getattr(data, "physical_task_src", None):
        data.physical_task_src = dict(getattr(data, "task_src", {}))
        data.physical_task_dst = dict(getattr(data, "task_dst", {}))

    data.umcf_per_task_nodes = True
    data.umcf_virtual_nodes = True
    data.umcf_task_src = umcf_task_src
    data.umcf_task_dst = umcf_task_dst
    data.umcf_vs = None
    data.umcf_vt = None
    data.sigma_vs = None
    data.sigma_vt = None
    data.valid_assign = _build_valid_assign_umcf_per_task(
        task_ids, M, umcf_task_src, umcf_task_dst, data.P_cand
    )

    from duibi_metrics import ensure_link_prices

    ensure_link_prices(data)
    scale = float(getattr(data, "bandwidth_price_scale", 1.0))
    mode = str(getattr(data, "bandwidth_price_mode", "uniform"))
    for e in data.E:
        if e in data.link_price:
            continue
        if mode == "inverse_capacity":
            data.link_price[e] = scale / max(float(data.B[e]), 1.0)
        else:
            data.link_price[e] = scale
    return umcf_task_src, umcf_task_dst


def attach_umcf_graph_dicts(
    M: list,
    S: list,
    B: dict,
    sigma: dict,
    P_cand: dict,
    E_list: list,
    access_sigma: float,
    sink_access_sigma: float | None,
) -> tuple[int, int]:
    """
    就地扩展 UMCF：V_s=len(M), V_t=len(M)+1，边 (V_s,m)、(m,V_t) 写入 B/sigma，路径写入 P_cand，边追加到 E_list。
    返回 (V_s, V_t)。
    """
    n = len(M)
    Vs, Vt = n, n + 1
    sig_u = float(access_sigma)
    sig_t = float(sink_access_sigma) if sink_access_sigma is not None else sig_u
    Bcap = max(float(v) for v in B.values()) if B else 1e9
    for mm in M:
        evs = (Vs, mm)
        evt = (mm, Vt)
        B[evs] = float(Bcap)
        B[evt] = float(Bcap)
        sigma[evs] = {s: sig_u for s in S}
        sigma[evt] = {s: sig_t for s in S}
        P_cand[Vs, mm] = [[(Vs, mm)]]
        P_cand[mm, Vt] = [[(mm, Vt)]]
        E_list.append(evs)
        E_list.append(evt)
    P_cand[Vs, Vs] = [[]]
    P_cand[Vt, Vt] = [[]]
    return Vs, Vt


def attach_umcf_to_data_object(
    data,
    access_sigma: float = 0.99,
    sink_access_sigma: float | None = None,
) -> tuple[int, int]:
    """对已有 UltraComplexData / B4JointData 就地附加 UMCF 层（与 load_b4_joint_data 一致）。"""
    if getattr(data, "umcf_virtual_nodes", False):
        return int(data.umcf_vs), int(data.umcf_vt)
    Vs, Vt = attach_umcf_graph_dicts(
        list(data.M),
        list(data.S),
        data.B,
        data.sigma,
        data.P_cand,
        data.E,
        access_sigma,
        sink_access_sigma,
    )
    data.umcf_virtual_nodes = True
    data.umcf_vs = Vs
    data.umcf_vt = Vt
    data.sigma_vs = None
    data.sigma_vt = None
    return Vs, Vt


def load_b4_joint_data(
    base_path: str = "./data",
    topology_name: str = "B4",
    hub_index: int = 0,
    num_tasks: int = 10,
    demand_row: int = 0,
    demand_downscale: float = 2.0,
    demand_scale: float = 1.0,
    k_paths: int = 2,
    stress_zero_s1: bool = False,
    virtual_source: bool = False,
    virtual_source_sigma: float = 0.99,
    virtual_sink_sigma: float | None = None,
    umcf_virtual_nodes: bool = False,
    umcf_access_sigma: float = 0.99,
    umcf_sink_access_sigma: float | None = None,
    bandwidth_price_scale: float = 1.0,
    bandwidth_price_mode: str = "inverse_capacity",
    scenario_s2_derate: float = 0.60,
    scenario_s1_link_k: int = 4,
    scenario_s1_link_sigma: float = 0.80,
    routing_mode: str = "hub",
) -> B4JointData:
    """
    :param hub_index: 作为算力「源宿」中心的节点下标（默认 0 = s1）。
    :param demand_row: demand.txt 行号（0-based）。
    :param demand_downscale: 与 main.py / parsers 一致，需求除以 (demand_downscale*1000)。
    :param demand_scale: 在换算得到的任务流量上再乘该系数（>1 加压网络与算力）。
    :param virtual_source: 为 True 时设置 `sigma_vs`/`sigma_vt`（逻辑虚拟源/汇接入可用率，建议 <1 以保留接入风险上界）。
    :param virtual_source_sigma: 各 (m,s) 上 `sigma_vs[m][s]` 的常数值（默认可用率 0.99）。
    :param virtual_sink_sigma: 若给定则作为 `sigma_vt`；否则与 `virtual_source_sigma` 相同。
    :param umcf_virtual_nodes: 为 True 时为 `cvar_compare.build_teavar_sla_cvar_model` 挂载显式 \(V_s,V_t\) 与虚拟边（见模块说明）。
    :param umcf_access_sigma: 各场景下边 \((V_s,m)\) 的可用率 \(\sigma\)。
    :param umcf_sink_access_sigma: 边 \((m,V_t)\) 的可用率；缺省与 `umcf_access_sigma` 相同。
    :param bandwidth_price_scale: 链路带宽单价尺度 $\\pi_e$ 的全局系数（见 ``duibi_metrics.ensure_link_prices``）。
    :param bandwidth_price_mode: ``uniform`` 或 ``inverse_capacity``（$\\pi_e \\propto 1/B_e$）。
    :param scenario_s2_derate: 场景 $s=2$ 下 **aggregation** 节点名义容量乘数（默认 0.60）。
    :param scenario_s1_link_k: 场景 $s=1$ 按 prob_failure 降序断链条数（0=不断链；默认 4）。
    :param scenario_s1_link_sigma: 场景 $s=1$ top-k 链路 **部分降级**可用率（P0 默认 0.80）；
        ``stress_zero_s1=True`` 时 top-k 仍为 **0**（Physical foil 硬断链）。
    :param routing_mode: ``hub`` | ``per_task_od`` | ``umcf_global`` | ``umcf_per_task``（``dag`` 占位未实现）。
    """
    routing_mode = str(routing_mode or "hub")
    if routing_mode not in ("hub", "per_task_od", "umcf_global", "umcf_per_task", "dag"):
        raise ValueError(
            f"routing_mode must be hub, per_task_od, umcf_global, umcf_per_task, or dag "
            f"(got {routing_mode!r})"
        )
    if routing_mode == "dag":
        raise NotImplementedError("routing_mode='dag' is not implemented yet.")
    use_od_tasks = routing_mode in ("per_task_od", "umcf_per_task")
    if routing_mode == "umcf_global":
        umcf_virtual_nodes = True
    if routing_mode == "umcf_per_task":
        umcf_virtual_nodes = False
    dir_path = os.path.join(base_path, topology_name)
    topo_file = os.path.join(dir_path, "topology.txt")
    csv_file = os.path.join(dir_path, "node_compute_resources.csv")

    links, capacity, _, node_names = parsers.read_topology(topology_name, base_path, downscale=1.0)
    n = len(node_names)

    # Fallback: if parsers.read_topology returned 0 links (e.g. missing prob_failure column),
    # read topology directly with default prob=0.001
    if len(links) == 0:
        links, capacity = _read_topology_raw(os.path.join(dir_path, "topology.txt"), n)
        if links:
            print(f"  [fix] {topology_name}: used fallback topology reader (prob_failure column missing)")

    # Auto-detect 0-based vs 1-based node indexing in topology files.
    min_node = min(min(u, v) for (u, v) in links) if links else 0
    topo_is_0based = min_node < 0
    if topo_is_0based:
        links = [(u + 1, v + 1) for (u, v) in links]

    if hub_index < 0 or hub_index >= n:
        raise ValueError(f"hub_index must be in [0,{n-1}]")

    adj: dict[int, list[int]] = {i: [] for i in range(n)}
    B: dict[tuple[int, int], float] = {}
    for (u, v), cap in zip(links, capacity):
        if 0 <= u < n and 0 <= v < n:
            adj[u].append(v)
            B[(u, v)] = float(cap)

    E = list(B.keys())

    demand_path = os.path.join(dir_path, "demand.txt")
    row = None
    try:
        mat = np.loadtxt(demand_path)
    except (ValueError, IOError):
        # Try tab-separated
        try:
            mat = np.loadtxt(demand_path, delimiter="\t")
        except (ValueError, IOError):
            mat = None

    if mat is None or mat.ndim == 0 or mat.size == 0:
        print(f"  [warn] {topology_name}: demand.txt invalid/empty, using synthetic demand")
        mat = _synthetic_demand(n)

    if mat.ndim == 1:
        row = mat
    else:
        row = mat[demand_row] if demand_row < len(mat) else mat[-1]

    scale = 1.0 / (1000.0 * demand_downscale)

    # Auto-detect a valid hub if the requested one has no outgoing demand
    def _hub_has_demand(h_idx: int) -> bool:
        for idx in range(n * n):
            src = idx // n
            dst = idx % n
            if src == h_idx and dst != h_idx and float(row[idx]) > 0:
                return True
        return False

    effective_hub = hub_index
    if not _hub_has_demand(hub_index):
        # Find the node with the most outgoing demand as hub
        best_hub = hub_index
        best_vol = 0.0
        for candidate in range(n):
            vol = 0.0
            for idx in range(n * n):
                src = idx // n
                dst = idx % n
                if src == candidate and dst != candidate:
                    vol += float(row[idx])
            if vol > best_vol:
                best_vol = vol
                best_hub = candidate
        effective_hub = best_hub
        print(f"  [auto-hub] {topology_name}: hub_index={hub_index} has no demand, using hub={effective_hub} instead")

    hub_pairs: list[tuple[float, int]] = []
    od_pairs: list[tuple[float, int, int]] = []
    for idx in range(n * n):
        src = idx // n
        dst = idx % n
        if src == dst:
            continue
        val = float(row[idx])
        if val <= 0:
            continue
        scaled = val * scale
        od_pairs.append((scaled, src, dst))
        if routing_mode in ("hub", "umcf_global") and src == effective_hub:
            hub_pairs.append((scaled, dst))
    od_pairs.sort(key=lambda x: -x[0])
    if routing_mode in ("hub", "umcf_global"):
        hub_pairs.sort(key=lambda x: -x[0])

    if routing_mode in ("hub", "umcf_global"):
        if not hub_pairs:
            raise ValueError(
                f"No outgoing demand found from hub={effective_hub} in demand row {demand_row} of {topology_name}; "
                "try a different demand_row."
            )
        tasks_triples: list[tuple[float, int, int]] = []
        for j in range(num_tasks):
            if j < len(hub_pairs):
                vol, dst = hub_pairs[j]
                tasks_triples.append((vol, effective_hub, dst))
            else:
                v0, d0 = hub_pairs[0]
                tasks_triples.append((v0 * 0.1, effective_hub, d0))
    else:
        if not od_pairs:
            raise ValueError(
                f"No positive off-diagonal demand in row {demand_row} of {topology_name} "
                "for routing_mode='per_task_od'."
            )
        tasks_triples = []
        for j in range(num_tasks):
            if j < len(od_pairs):
                vol, src, dst = od_pairs[j]
                tasks_triples.append((vol, src, dst))
            else:
                v0, s0, d0 = od_pairs[0]
                tasks_triples.append((v0 * 0.1, s0, d0))

    T = len(tasks_triples)
    I = list(range(T))

    task_src: dict[int, int] = {}
    task_dst: dict[int, int] = {}
    b_in: dict[int, float] = {}
    b_out: dict[int, float] = {}
    for i, (vol, src, dst) in enumerate(tasks_triples):
        task_src[i] = int(src)
        task_dst[i] = int(dst)
        vol = max(1.0, min(vol, 8000.0))
        b_in[i] = float(vol) * float(demand_scale)
        b_out[i] = float(max(1.0, vol * 0.5)) * float(demand_scale)
        b_in[i] = max(1.0, min(b_in[i], 2.0e6))
        b_out[i] = max(1.0, min(b_out[i], 2.0e6))

    M = list(range(n))
    K = [0, 1, 2]
    S = [0, 1, 2]

    csv_rows = _read_compute_csv(csv_file)
    p_price: dict[int, dict[int, float]] = {}
    C_normal: dict[int, dict[int, float]] = {}
    for m in M:
        r = csv_rows[m]
        p_price[m] = {0: r["price_cpu"], 1: r["price_gpu"], 2: r["price_hbm"]}
        C_normal[m] = {0: r["cpu_cap"], 1: r["gpu_cap"], 2: r["hbm_cap"]}

    w_templates = (
        {0: 4.0, 1: 2.0, 2: 8.0},
        {0: 8.0, 1: 0.5, 2: 4.0},
        {0: 2.0, 1: 1.0, 2: 32.0},
    )
    w: dict[int, dict[int, float]] = {}
    for i in I:
        w[i] = dict(w_templates[i % len(w_templates)])

    P_cand: dict[tuple[int, int], list] = {}
    _nx_g = _build_nx_graph_from_adj(adj)
    for u in M:
        for v in M:
            if u == v:
                P_cand[u, v] = [[]]
            else:
                p1 = _k_shortest_edge_paths(adj, u, v, k_paths, _nx_graph=_nx_g)
                P_cand[u, v] = p1 if p1 else [[]]

    valid_assign: dict[tuple[int, int], bool] = {}
    if routing_mode in ("hub", "umcf_global"):
        valid_assign = _build_valid_assign_hub(I, M, effective_hub, P_cand)
    elif routing_mode == "per_task_od":
        valid_assign = _build_valid_assign_per_task_od(I, M, task_src, task_dst, P_cand)
    else:
        # umcf_per_task：先占位，attach_umcf_per_task 后重建 valid_assign
        valid_assign = { (i, m): True for i in I for m in M }

    prob = {0: 0.6, 1: 0.3, 2: 0.1}
    sigma = {e: {s: 1.0 for s in S} for e in E}
    edge_probs = _read_topology_probs(topo_file, topo_is_0based=topo_is_0based)
    edge_probs.sort(key=lambda x: -x[2])
    k_fail = max(0, int(scenario_s1_link_k))
    s1_stressed_edges: list[tuple[int, int]] = []
    s1_partial_sigma = float(scenario_s1_link_sigma)
    for (u, v, _) in edge_probs[: min(k_fail, len(edge_probs))]:
        e = (u, v)
        if e in sigma:
            if stress_zero_s1:
                sigma[u, v][1] = 0.0
            else:
                sigma[u, v][1] = s1_partial_sigma
            s1_stressed_edges.append(e)

    if umcf_virtual_nodes and routing_mode != "umcf_per_task":
        Vs, Vt = attach_umcf_graph_dicts(M, S, B, sigma, P_cand, E, umcf_access_sigma, umcf_sink_access_sigma)
        E = list(B.keys())

    C_s: dict[int, dict[int, dict[int, float]]] = {
        m: {k: {s: float(C_normal[m][k]) for s in S} for k in K} for m in M
    }
    agg_nodes = {m for m, r in csv_rows.items() if r["role"] == "aggregation"}
    derate = float(scenario_s2_derate)
    for m in agg_nodes:
        for k in K:
            C_s[m][k][2] = max(2.0, C_normal[m][k] * derate)

    obj = B4JointData()
    obj.I = I
    obj.M = M
    obj.K = K
    obj.S = S
    obj.p_price = p_price
    obj.w = w
    obj.E = E
    obj.B = B
    obj.P_cand = P_cand
    obj.prob = prob
    obj.sigma = sigma
    obj.C_s = C_s
    obj.C_normal = C_normal
    obj.b_in = b_in
    obj.b_out = b_out
    obj.beta_N = 0.95
    obj.beta_L = 0.95
    obj.valid_assign = valid_assign
    obj.hub = effective_hub
    obj.routing_mode = routing_mode
    obj.task_src = task_src
    obj.task_dst = task_dst
    if use_od_tasks:
        obj.physical_task_src = dict(task_src)
        obj.physical_task_dst = dict(task_dst)
    obj.scenario_s1_link_k = k_fail
    obj.scenario_s1_link_sigma = s1_partial_sigma
    obj.scenario_s1_stressed_edges = list(s1_stressed_edges)
    obj.scenario_s1_mode = "hub_hard_stress" if stress_zero_s1 else "partial_sigma"
    obj.bandwidth_price_scale = float(bandwidth_price_scale)
    obj.bandwidth_price_mode = str(bandwidth_price_mode)
    from duibi_metrics import ensure_link_prices

    ensure_link_prices(obj)

    if umcf_virtual_nodes and routing_mode != "umcf_per_task":
        obj.umcf_virtual_nodes = True
        obj.umcf_vs = int(Vs)
        obj.umcf_vt = int(Vt)
        obj.umcf_per_task_nodes = False
        obj.sigma_vs = None
        obj.sigma_vt = None
    elif routing_mode == "umcf_per_task":
        obj.umcf_virtual_nodes = False
        obj.umcf_per_task_nodes = False
        obj.sigma_vs = None
        obj.sigma_vt = None
    else:
        obj.umcf_virtual_nodes = False
        obj.umcf_per_task_nodes = False
        if virtual_source:
            sig = float(virtual_source_sigma)
            sig_t = float(virtual_sink_sigma) if virtual_sink_sigma is not None else sig
            obj.sigma_vs = {m: {s: sig for s in S} for m in M}
            obj.sigma_vt = {m: {s: sig_t for s in S} for m in M}
        else:
            obj.sigma_vs = None
            obj.sigma_vt = None

    if routing_mode == "umcf_per_task":
        attach_umcf_per_task(
            obj,
            I,
            access_sigma=float(umcf_access_sigma),
            sink_access_sigma=umcf_sink_access_sigma,
        )

    if stress_zero_s1:
        stress_hub_outgoing_s1(obj, effective_hub)

    if stress_zero_s1:
        print(
            f"  [s1] mode=hub_hard_stress | top-k={k_fail} σ=0 + hub outgoing cut "
            f"| n_topk_edges={len(s1_stressed_edges)}"
        )
    else:
        print(
            f"  [s1] mode=partial_sigma | top-k={k_fail} σ={s1_partial_sigma} "
            f"| n_edges={len(s1_stressed_edges)}"
        )

    va_check = obj.valid_assign if routing_mode == "umcf_per_task" else valid_assign
    for i in I:
        if not any(va_check.get((i, m), False) for m in M):
            if routing_mode in ("hub", "umcf_global"):
                raise ValueError(
                    f"Task {i} has no reachable paths from hub={effective_hub} in {topology_name}; "
                    "check topology connectivity."
                )
            if routing_mode == "umcf_per_task":
                vs = obj.umcf_task_src[i]
                vt = obj.umcf_task_dst[i]
                raise ValueError(
                    f"Task {i} (V_s={vs}, V_t={vt}) has no valid placement in {topology_name}; "
                    "check UMCF per-task virtual connectivity."
                )
            raise ValueError(
                f"Task {i} (src={task_src[i]}, dst={task_dst[i]}) has no valid placement in {topology_name}; "
                "check topology connectivity."
            )

    return obj


# ============================================================================
# Generalized loader: works with ANY topology, not just B4
# ============================================================================

def load_joint_data(
    base_path: str = "./data",
    topology_name: str = "B4",
    hub_index: int = 0,
    num_tasks: int = 10,
    demand_row: int = 0,
    demand_downscale: float = 2.0,
    demand_scale: float = 1.0,
    k_paths: int = 4,
    stress_zero_s1: bool = False,
    virtual_source: bool = False,
    virtual_source_sigma: float = 0.99,
    virtual_sink_sigma: float | None = None,
    umcf_virtual_nodes: bool = False,
    umcf_access_sigma: float = 0.99,
    umcf_sink_access_sigma: float | None = None,
    auto_generate_compute: bool = True,
    scenario_s2_derate: float = 0.60,
    scenario_s1_link_k: int = 4,
    scenario_s1_link_sigma: float = 0.80,
    routing_mode: str = "hub",
    eta: float | None = None,
    *,
    demand_scale_explicit: bool = False,
) -> B4JointData:
    """
    Generalized version of load_b4_joint_data that works with ANY topology.

    If node_compute_resources.csv is missing and auto_generate_compute=True,
    it will be auto-generated from topology structure (degree centrality ->
    role -> realistic capacity & pricing).

    Topology sizes supported:
      - Small (6-8 nodes):  Custom, Custom2
      - Medium (11-18):     B4, Sprint, Abilene, IBM, Nextgen
      - Large (25-29):      ATT, XNet

    Compute resource scaling is automatic and realistic:
      - Core nodes (high-degree):  high capacity, low unit cost (scale economics)
      - Aggregation nodes:         medium capacity, baseline pricing
      - Edge nodes (low-degree):   low capacity, premium pricing (edge scarcity)
      - GPU price ~4x CPU; HBM price ~2x CPU

    This is the recommended entry point for multi-topology experiments.

    **η 标定**：若 ``eta`` 非 None 且 ``demand_scale_explicit=False``，加载后调用
    ``p0_calibration.apply_eta_demand_calibration``（``demand_scale`` 仅作换算基数，默认 1.0）。
    显式 ``demand_scale_explicit=True`` 时 **不** 做 η 标定。
    """
    from generate_compute_resources import generate_compute_csv

    dir_path = os.path.join(base_path, topology_name)
    csv_file = os.path.join(dir_path, "node_compute_resources.csv")

    # Auto-generate compute resources if missing
    if not os.path.exists(csv_file):
        if auto_generate_compute:
            print(f"  [auto] Generating node_compute_resources.csv for {topology_name}...")
            generate_compute_csv(topology_name, base_path=base_path)
        else:
            raise FileNotFoundError(
                f"{csv_file} not found. Run generate_compute_resources.py or set auto_generate_compute=True."
            )

    # Delegate to the original loader (now topology_name-aware)
    obj = load_b4_joint_data(
        base_path=base_path,
        topology_name=topology_name,
        hub_index=hub_index,
        num_tasks=num_tasks,
        demand_row=demand_row,
        demand_downscale=demand_downscale,
        demand_scale=demand_scale,
        k_paths=k_paths,
        stress_zero_s1=stress_zero_s1,
        virtual_source=virtual_source,
        virtual_source_sigma=virtual_source_sigma,
        virtual_sink_sigma=virtual_sink_sigma,
        umcf_virtual_nodes=umcf_virtual_nodes,
        umcf_access_sigma=umcf_access_sigma,
        umcf_sink_access_sigma=umcf_sink_access_sigma,
        scenario_s2_derate=scenario_s2_derate,
        scenario_s1_link_k=scenario_s1_link_k,
        scenario_s1_link_sigma=scenario_s1_link_sigma,
        routing_mode=routing_mode,
    )

    if eta is not None and not demand_scale_explicit:
        from p0_calibration import apply_eta_demand_calibration

        apply_eta_demand_calibration(obj, eta=float(eta), scenario_id=1)
    elif demand_scale_explicit:
        obj.p0_calibration = {
            "used_eta_calibration": False,
            "demand_scale": float(demand_scale),
            "demand_scale_explicit": True,
        }
        print(
            f"  [demand] explicit demand_scale={demand_scale:.4f} "
            f"(η calibration skipped)"
        )
    else:
        obj.p0_calibration = {"used_eta_calibration": False}

    return obj


def assess_topology_readiness(
    topology_name: str,
    base_path: str = "./data",
    *,
    hub_index: int = 0,
    num_tasks: int = 4,
) -> dict:
    """
    检查拓扑是否可用于 joint/monetary 实验。
    返回 {"ready": bool, "issues": [...], "warnings": [...], "nodes": int, "edges": int}。
    """
    import os as _os

    issues: list[str] = []
    warnings: list[str] = []
    dir_path = _os.path.join(base_path, topology_name)
    topo_file = _os.path.join(dir_path, "topology.txt")
    nodes_file = _os.path.join(dir_path, "nodes.txt")
    csv_file = _os.path.join(dir_path, "node_compute_resources.csv")
    demand_file = _os.path.join(dir_path, "demand.txt")

    if not _os.path.isdir(dir_path):
        issues.append(f"目录不存在: {dir_path}")
        return {"ready": False, "issues": issues, "warnings": warnings, "nodes": 0, "edges": 0}

    if not _os.path.exists(topo_file):
        issues.append("缺少 topology.txt")
    if not _os.path.exists(nodes_file):
        issues.append("缺少 nodes.txt")

    n_nodes = n_edges = 0
    if _os.path.exists(nodes_file):
        with open(nodes_file, encoding="utf-8") as f:
            n_nodes = sum(
                1 for line in f if line.strip() and "String_node_names" not in line
            )
    if _os.path.exists(topo_file):
        with open(topo_file, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if parts and parts[0] != "to_node" and not line.startswith("#"):
                    try:
                        int(parts[0])
                        n_edges += 1
                    except ValueError:
                        pass

    prob_missing = False
    if _os.path.exists(topo_file):
        with open(topo_file, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if not parts or parts[0] == "to_node" or line.startswith("#"):
                    continue
                if len(parts) < 4:
                    prob_missing = True
                    break
    if prob_missing:
        warnings.append("topology.txt 无 prob_failure 列 → 使用默认 pf=0.001")

    if not _os.path.exists(csv_file):
        warnings.append("缺少 node_compute_resources.csv → load_joint_data 将自动生成")
    if not _os.path.exists(demand_file):
        warnings.append("缺少 demand.txt → 使用合成重力需求")

    if issues:
        return {"ready": False, "issues": issues, "warnings": warnings, "nodes": n_nodes, "edges": n_edges}

    try:
        load_joint_data(
            base_path=base_path,
            topology_name=topology_name,
            hub_index=hub_index,
            num_tasks=num_tasks,
            demand_scale=1.0,
            k_paths=2,
            auto_generate_compute=True,
        )
    except Exception as exc:
        issues.append(f"load_joint_data 失败: {exc}")
        return {"ready": False, "issues": issues, "warnings": warnings, "nodes": n_nodes, "edges": n_edges}

    return {"ready": True, "issues": issues, "warnings": warnings, "nodes": n_nodes, "edges": n_edges}


def list_available_topologies(base_path: str = "./data") -> list[str]:
    """Return sorted list of topology names that have topology.txt."""
    import os as _os
    result = []
    for d in sorted(_os.listdir(base_path)):
        full = _os.path.join(base_path, d)
        if _os.path.isdir(full) and _os.path.exists(_os.path.join(full, "topology.txt")):
            if d != "raw":
                result.append(d)
    return result


def print_topology_summary(base_path: str = "./data"):
    """Print a summary table of all available topologies."""
    import os as _os

    print(f"{'Topology':>10} | {'Nodes':>5} | {'Edges':>5} | {'Roles (C/A/E)':>16} | {'CPU range':>14} | {'Price range':>14}")
    print("-" * 90)
    for name in list_available_topologies(base_path):
        dir_path = _os.path.join(base_path, name)
        nodes_file = _os.path.join(dir_path, "nodes.txt")
        topo_file = _os.path.join(dir_path, "topology.txt")
        csv_file = _os.path.join(dir_path, "node_compute_resources.csv")

        n_nodes = 0
        with open(nodes_file) as f:
            for line in f:
                if line.strip() and "String_node_names" not in line:
                    n_nodes += 1

        n_edges = 0
        with open(topo_file) as f:
            for line in f:
                if line.strip() and not line.startswith("#") and "to_node" not in line:
                    n_edges += 1

        if _os.path.exists(csv_file):
            rows = _read_compute_csv(csv_file)
            roles = {}
            cpu_vals = []
            price_vals = []
            for r in rows.values():
                roles[r["role"]] = roles.get(r["role"], 0) + 1
                cpu_vals.append(r["cpu_cap"])
                price_vals.append(r["price_cpu"])
            role_str = f"{roles.get('core',0)}/{roles.get('aggregation',0)}/{roles.get('edge_pop',0)}"
            cpu_str = f"{min(cpu_vals):.0f}-{max(cpu_vals):.0f}"
            price_str = f"{min(price_vals):.2f}-{max(price_vals):.2f}"
        else:
            role_str = "no CSV"
            cpu_str = "N/A"
            price_str = "N/A"

        print(f"{name:>10} | {n_nodes:>5} | {n_edges:>5} | {role_str:>16} | {cpu_str:>14} | {price_str:>14}")
