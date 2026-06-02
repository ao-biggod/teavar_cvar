import gurobipy as gp
from gurobipy import GRB

def TEAVAR(edges, capacity, flows, demand, beta, T, Tf, scenarios, scenario_probs, average=False):
    nedges = len(edges)
    nflows = len(flows)
    ntunnels = len(T)
    nscenarios = len(scenarios)
    
    # 计算隧道可用性矩阵 X[s, t]
    X = [[1 for _ in range(ntunnels)] for _ in range(nscenarios)]
    for s in range(nscenarios):
        for t in range(ntunnels):
            for e_idx in T[t]:
                if scenarios[s][e_idx] == 0:
                    X[s][t] = 0
                    break

    # 计算链路-隧道包含矩阵 L[t, e]
    L = [[0 for _ in range(nedges)] for _ in range(ntunnels)]
    for t in range(ntunnels):
        for e_idx in T[t]:
            L[t][e_idx] = 1

    model = gp.Model("TEAVAR")
    model.setParam('OutputFlag', 0)

    # 变量 a: 流量分配比例
    a = []
    for f in range(nflows):
        f_vars = []
        for t_idx in range(len(Tf[f])):
            f_vars.append(model.addVar(lb=0, ub=1.0, vtype=GRB.CONTINUOUS))
        a.append(f_vars)
        if len(f_vars) > 0:
            model.addConstr(gp.quicksum(a[f]) <= 1.0)

    alpha = model.addVar(lb=0, ub=1.0, vtype=GRB.CONTINUOUS, name="alpha")
    u = model.addVars(nscenarios, nflows, lb=0, name="u")
    umax = model.addVars(nscenarios, lb=0, name="umax")

    # 1. 链路容量约束
    for e in range(nedges):
        usage = gp.LinExpr()
        for f in range(nflows):
            for t_in_f, global_t_idx in enumerate(Tf[f]):
                if L[global_t_idx][e] == 1:
                    usage += a[f][t_in_f] * demand[f]
        model.addConstr(usage <= capacity[e])

    # 2. 丢包损失约束
    for s in range(nscenarios):
        for f in range(nflows):
            if not Tf[f]:
                model.addConstr(u[s, f] == 1.0)
                continue
            satisfied = gp.LinExpr()
            for t_in_f, global_t_idx in enumerate(Tf[f]):
                satisfied += a[f][t_in_f] * X[s][global_t_idx]
            model.addConstr(u[s, f] >= 1.0 - satisfied)

    # 3. CVaR 风险映射
    for s in range(nscenarios):
        if average:
            avg_loss = gp.quicksum(u[s, f] for f in range(nflows)) / nflows
            model.addConstr(umax[s] >= avg_loss - alpha)
        else:
            for f in range(nflows):
                model.addConstr(umax[s] >= u[s, f] - alpha)

    # 目标函数
    tail_risk = gp.quicksum(scenario_probs[s] * umax[s] for s in range(nscenarios))
    model.setObjective(alpha + (1.0 / (1.0 - beta)) * tail_risk, GRB.MINIMIZE)
    
    model.optimize()

    if model.status == GRB.OPTIMAL:
        return {'alpha': alpha.X, 'obj': model.ObjVal}
    return None