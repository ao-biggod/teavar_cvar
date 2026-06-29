import gurobipy as gp
from gurobipy import GRB


class SimpleData:
    def __init__(self):
        self.I = [0, 1, 2]
        self.M = [0, 1]
        self.E = [0]
        self.S = [0, 1]
        self.K = [0]

        self.w = {0: {0: 2}, 1: {0: 3}, 2: {0: 4}}
        self.p_price = {0: {0: 10}, 1: {0: 20}}
        self.C_normal = {0: {0: 8}, 1: {0: 6}}
        self.C_s = {
            0: {0: {0: 8, 1: 4}},
            1: {0: {0: 6, 1: 6}}
        }

        self.b_in  = {0: 5, 1: 4, 2: 6}
        self.b_out = {0: 2, 1: 1, 2: 3}

        self.delay_user_to_m = {
            0: {0: 10, 1: 50},
            1: {0: 12, 1: 45},
            2: {0: 15, 1: 40}
        }
        self.max_access_delay = {0: 30, 1: 50, 2: 40}

        self.B = {0: 100}
        self.sigma = {0: {0: 1.0, 1: 0.5}}

        self.P_in = {}
        self.P_out = {}
        for i in self.I:
            for m in self.M:
                self.P_in[(i, m)]  = [(0,)]
                self.P_out[(i, m)] = [(0,)]

        self.P_cost_in  = {(0,): 2}
        self.P_cost_out = {(0,): 1}

        self.prob = {0: 0.7, 1: 0.3}
        self.beta_N = 0.95
        self.beta_L = 0.90
        self.Gamma_N = 1.24999
        self.Gamma_L = 1.24999

        # 预处理：仅保留满足时延和容量约束的 (i,m)
        self.valid_assign = {}
        for i in self.I:
            for m in self.M:
                delay_ok = (self.delay_user_to_m[i][m] <= self.max_access_delay[i])
                cap_ok = all(self.w[i][k] <= self.C_normal[m][k] for k in self.K)
                self.valid_assign[(i, m)] = delay_ok and cap_ok


def build_cvar_risk_constrained_model(data):
    model = gp.Model("Costo_CVaR_Constraint")

    # 1. 变量：只对有效 (i,m) 创建 y
    y = model.addVars(
        ((i, m) for (i, m), ok in data.valid_assign.items() if ok),
        vtype=GRB.BINARY, name="y"
    )

    # 2. 流量变量
    x_in = {}
    x_out = {}
    for (i, m), ok in data.valid_assign.items():
        if not ok:
            continue
        x_in[i, m] = {}
        for p in data.P_in.get((i, m), []):
            x_in[i, m][p] = model.addVar(lb=0, name=f"x_in_{i}_{m}_{p[0]}")
        x_out[i, m] = {}
        for q in data.P_out.get((i, m), []):
            x_out[i, m][q] = model.addVar(lb=0, name=f"x_out_{i}_{m}_{q[0]}")

    # 3. CVaR 辅助变量
    zeta_N = model.addVar(lb=-GRB.INFINITY, name="zeta_N")
    u_s = model.addVars(data.S, lb=0, name="u_s")
    zeta_L = model.addVar(lb=-GRB.INFINITY, name="zeta_L")
    v_s = model.addVars(data.S, lb=0, name="v_s")

    # 4. 目标
    placement_cost = gp.quicksum(
        y[i, m] * sum(data.w[i][k] * data.p_price[m][k] for k in data.K)
        for (i, m) in y
    )
    bw_cost = gp.quicksum(
        x_in[i, m][p] * data.P_cost_in[p]
        for (i, m) in y for p in data.P_in.get((i, m), [])
    ) + gp.quicksum(
        x_out[i, m][q] * data.P_cost_out[q]
        for (i, m) in y for q in data.P_out.get((i, m), [])
    )
    model.setObjective(placement_cost + bw_cost, GRB.MINIMIZE)

    # 5. 约束
    # 任务唯一性
    model.addConstrs(
        (gp.quicksum(y[i, m] for m in data.M if (i, m) in y) == 1
         for i in data.I), name="Task_Unique"
    )

    # 流量守恒
    model.addConstrs(
        (gp.quicksum(x_in[i, m][p] for p in data.P_in.get((i, m), [])) == y[i, m] * data.b_in[i]
         for (i, m) in y), name="FlowCons_In")
    model.addConstrs(
        (gp.quicksum(x_out[i, m][q] for q in data.P_out.get((i, m), [])) == y[i, m] * data.b_out[i]
         for (i, m) in y), name="FlowCons_Out")

    # 节点容量
    for m in data.M:
        for k in data.K:
            model.addConstr(
                gp.quicksum(y[i, m] * data.w[i][k] for i in data.I if (i, m) in y) <= data.C_normal[m][k],
                name=f"NodeCap_{m}_{k}")

    # 链路容量（常态）
    for e in data.E:
        load_e = gp.LinExpr()
        for (i, m) in y:
            for p in data.P_in.get((i, m), []):
                if e in p:
                    load_e += x_in[i, m][p]
            for q in data.P_out.get((i, m), []):
                if e in q:
                    load_e += x_out[i, m][q]
        model.addConstr(load_e <= data.B[e], name=f"LinkCap_{e}")

    # 节点 CVaR 约束
    model.addConstr(
        zeta_N + (1 / (1 - data.beta_N)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)
        <= data.Gamma_N, name="NodeCVaR_Limit")
    for s in data.S:
        for m in data.M:
            for k in data.K:
                model.addConstr(
                    u_s[s] >= gp.quicksum(y[i, m] * data.w[i][k] for i in data.I if (i, m) in y) / data.C_s[m][k][s] - zeta_N,
                    name=f"NodeLoss_{s}_{m}_{k}")

    # 链路 CVaR 约束（修正分母）
    model.addConstr(
        zeta_L + (1 / (1 - data.beta_L)) * gp.quicksum(data.prob[s] * v_s[s] for s in data.S)
        <= data.Gamma_L, name="LinkCVaR_Limit")
    for s in data.S:
        for e in data.E:
            L_e_s = gp.LinExpr()
            for (i, m) in y:
                for p in data.P_in.get((i, m), []):
                    if e in p:
                        L_e_s += x_in[i, m][p]
                for q in data.P_out.get((i, m), []):
                    if e in q:
                        L_e_s += x_out[i, m][q]
            cap_e_s = data.B[e] * data.sigma[e][s]
            if cap_e_s > 1e-6:
                model.addConstr(v_s[s] >= L_e_s / cap_e_s - zeta_L,
                                name=f"LinkLoss_{s}_{e}")
            else:
                model.addConstr(v_s[s] >= 1 - zeta_L,
                                name=f"LinkLoss_Fail_{s}_{e}")

    model.update()

    # 将变量字典保存在模型上，方便后续快速访问
    model._y = y
    model._x_in = x_in
    model._x_out = x_out
    model._zeta_N = zeta_N
    model._zeta_L = zeta_L
    model._u = u_s
    model._v = v_s
    return model


if __name__ == "__main__":
    data = SimpleData()
    model = build_cvar_risk_constrained_model(data)

    model.setParam('OutputFlag', 1)
    model.setParam('MIPGap', 1e-4)
    model.optimize()

    if model.status == GRB.OPTIMAL:
        print("\n=== Optimal solution found ===")
        print(f"Total Cost = {model.objVal:.4f}")

        print("\nTask Placement:")
        for (i, m), var in model._y.items():
            if var.X > 0.5:
                print(f"  Task {i} -> Node {m}")

        print("\nFlow Allocation:")
        for (i, m) in model._x_in:
            for p, var in model._x_in[i, m].items():
                if var.X > 1e-6:
                    print(f"  x_in  Task{i} Node{m} Path{p} = {var.X:.2f}")
        for (i, m) in model._x_out:
            for q, var in model._x_out[i, m].items():
                if var.X > 1e-6:
                    print(f"  x_out Task{i} Node{m} Path{q} = {var.X:.2f}")

        zeta_N_val = model._zeta_N.X
        zeta_L_val = model._zeta_L.X
        u_vals = {s: model._u[s].X for s in data.S}
        v_vals = {s: model._v[s].X for s in data.S}
        node_cvar = zeta_N_val + (1/(1-data.beta_N)) * sum(data.prob[s]*u_vals[s] for s in data.S)
        link_cvar = zeta_L_val + (1/(1-data.beta_L)) * sum(data.prob[s]*v_vals[s] for s in data.S)
        print(f"\nNode CVaR: zeta_N={zeta_N_val:.4f}, u_s={u_vals}")
        print(f"  Computed Node CVaR = {node_cvar:.4f}  (limit {data.Gamma_N})")
        print(f"Link CVaR: zeta_L={zeta_L_val:.4f}, v_s={v_vals}")
        print(f"  Computed Link CVaR = {link_cvar:.4f}  (limit {data.Gamma_L})")
    else:
        print(f"No optimal solution found, status = {model.status}")