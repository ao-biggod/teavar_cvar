import gurobipy as gp
from gurobipy import GRB

def TEAVAR(edges, capacity, flows, demand, beta, T, Tf, scenarios, scenario_probs, average=False):
    """
    这段代码的逻辑可以概括为：
      1. 先遍历所有给定的故障场景
      2. 对每个 tunnel，判断在每个场景 s 下还能不能用，得到 X
      3. 对每个 tunnel，记录它用了哪些边，得到 L
      4. 决定每个 flow 在各 tunnel 上分多少流量，变量是 a
      5. 保证任意边上的总流量不超过容量
      6. 在每个故障场景下，根据哪些 tunnel 挂了，计算每个 flow 还能满足多少需求
      7. 把“未满足比例”视为损失
      8. 用 CVaR 风格目标函数最小化尾部风险
      9. 输出最优分流方案
    """

    nedges = len(edges)
    nflows = len(flows)
    ntunnels = len(T)
    nscenarios = len(scenarios)
    p = scenario_probs

    # --- CREATE TUNNEL SCENARIO MATRIX ---
    # 定义常量 X[s,t]
    # X[s,t] 是一个二值可用性矩阵，表示场景 s 下 tunnel t 是否可用
    # X[s,t] = 1 表示可用，0 表示不可用
    # 判定标准：(1) tunnel 边列表为空则不可用；(2) 场景中某条失效边 e 或其反向边出现在 tunnel 中则不可用
    X = [[1 for _ in range(ntunnels)] for _ in range(nscenarios)]

    # 为了加速反向边查找，先建立边到索引的映射
    edge_to_idx = {edge: i for i, edge in enumerate(edges)}

    for s in range(nscenarios):
        for t in range(ntunnels):
            if len(T[t]) == 0:
                X[s][t] = 0  # 认定该场景 s 下，tunnel t 失效
            else:
                for e_idx in T[t]:
                    # 遍历 tunnel 中的边，如果在场景 s 中该边挂掉
                    if scenarios[s][e_idx] == 0:
                        X[s][t] = 0
                        break

                    # 查找反向边 (u,v) -> (v,u)
                    u, v = edges[e_idx]
                    back_edge = (v, u)
                    if back_edge in edge_to_idx:
                        back_idx = edge_to_idx[back_edge]
                        if scenarios[s][back_idx] == 0:
                            X[s][t] = 0  # 认定该场景 s 下，tunnel t 失效
                            break

    # --- CREATE TUNNEL EDGE MATRIX ---
    # 定义常量 L[t,e]
    # L[t,e] = 1 表示 tunnel t 包含了边 e
    # 用于链路容量约束：所有经过边 e 的 tunnel 的流量总和不能超过其容量
    L = [[0 for _ in range(nedges)] for _ in range(ntunnels)]
    for t in range(ntunnels):
        for e_idx in T[t]:
            L[t][e_idx] = 1

    # --- 建立 Gurobi 优化模型 ---
    model = gp.Model("TEAVAR_Optimization")
    model.setParam('OutputFlag', 0)  # 不打印 Gurobi 日志

    # --- 定义决策变量 ---

    # 主决策变量 a[f, t_idx]：第 f 条 flow 在其第 t_idx 条候选 tunnel 上的带宽分配
    a = {}
    for f in range(nflows):
        for t_idx in range(len(Tf[f])):
            a[f, t_idx] = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name=f"a_{f}_{t_idx}")

    # 决策变量：alpha 风险模型中核心辅助变量（VaR 阈值）
    alpha = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="alpha")

    # 决策变量：u[s,f] 表示在场景 s 下，flow f 的损失比例
    u = model.addVars(nscenarios, nflows, lb=0, vtype=GRB.CONTINUOUS, name="u")

    # 决策变量：umax[s] 场景 s 下损失比例超过 alpha 的超额损失
    umax = model.addVars(nscenarios, lb=0, vtype=GRB.CONTINUOUS, name="umax")

    # --- 添加约束条件 ---

    # 1. 链路容量约束
    for e in range(nedges):
        flow_on_link = gp.quicksum(a[f, t_idx] * L[Tf[f][t_idx]][e]
                                   for f in range(nflows)
                                   for t_idx in range(len(Tf[f])))
        model.addConstr(flow_on_link <= capacity[e], name=f"Capacity_e{e}")

    # 2. FLOW LEVEL LOSS (流量满足比例)
    for s in range(nscenarios):
        for f in range(nflows):
            # 防止除以 0
            if demand[f] == 0:
                model.addConstr(u[s, f] == 0)
                continue
                
            satisfied_sf = gp.quicksum(a[f, t_idx] * X[s][Tf[f][t_idx]]
                                       for t_idx in range(len(Tf[f]))) / demand[f]

            model.addConstr(u[s, f] >= 1 - satisfied_sf, name=f"Loss_s{s}_f{f}")

    # 3. SCENARIO LEVEL LOSS (场景级风险线性化)
    for s in range(nscenarios):
        if average:
            avg_loss = gp.quicksum(u[s, f] for f in range(nflows)) / nflows
            model.addConstr(umax[s] + alpha >= avg_loss, name=f"AvgRisk_s{s}")
        else:
            for f in range(nflows):
                model.addConstr(umax[s] + alpha >= u[s, f], name=f"WorstRisk_s{s}_f{f}")

    # --- 目标函数 ---
    tail_penalty = gp.quicksum(p[s] * umax[s] for s in range(nscenarios))
    model.setObjective(alpha + (1 / (1 - beta)) * tail_penalty, GRB.MINIMIZE)

    # 执行求解
    model.optimize()

    # --- 输出结果 ---
    if model.status == GRB.OPTIMAL:
        allocations = []
        for f in range(nflows):
            allocations.append([a[f, t_idx].X for t_idx in range(len(Tf[f]))])

        return {
            'alpha': alpha.X,
            'obj': model.ObjVal,
            'allocations': allocations,
            'umax': [umax[s].X for s in range(nscenarios)]
        }
    else:
        return None