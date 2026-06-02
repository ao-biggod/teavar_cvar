import gurobipy as gp
from gurobipy import GRB

class SimpleData:
    def __init__(self):
        # 集合
        self.I = [0, 1, 2]           # 3个任务
        self.M = [0, 1]              # 2个节点
        self.E = [0]                 # 1条链路
        self.S = [0, 1]              # 2个场景 (0:正常, 1:极端故障)
        self.K = [0]                 # 单资源维度

        # 任务资源需求 (保持不变)
        self.w = {0: {0: 2}, 1: {0: 3}, 2: {0: 4}}

        # --- 核心改动 1: 制造剧烈的价格冲突 ---
        # Node 0 非常便宜，Node 1 极其昂贵
        self.p_price = {
            0: {0: 10}, 
            1: {0: 50}  # 价格翻10倍，增加迁徙阻力
        }

        # --- 核心改动 2: 制造常态与场景的巨大反差 ---
        # 节点 0 常态容量大，但在场景 1 下几乎完全瘫痪 (容量从 10 降到 1)
        # 节点 1 虽然贵，但在场景 1 下极其稳健 (容量不缩水)
        self.C_normal = {
            0: {0: 10}, 
            1: {0: 10}
        }
        self.C_s = {
            0: {0: {0: 10, 1: 0.5}}, # 场景1下 Node 0 仅剩 1个核，足以让 u_s 爆炸
            1: {0: {0: 10, 1: 10.0}} # Node 1 是避风港
        }

        # 任务流量需求 (保持不变)
        self.b_in  = {0: 5, 1: 4, 2: 6}
        self.b_out = {0: 2, 1: 1, 2: 3}

        # 接入时延 (调低上限，限制任务只能部署在特定节点)
        self.delay_user_to_m = {
            0: {0: 10, 1: 10},
            1: {0: 10, 1: 10},
            2: {0: 10, 1: 10}
        }
        self.max_access_delay = {0: 100, 1: 100, 2: 100}

        # --- 核心改动 3: 制造链路拥塞 ---
        # 将总带宽设为刚好能容纳总流量 (21)，一旦 sigma 波动，v_s 立即触发
        self.B = {0: 22} 
        self.sigma = {0: {0: 1.0, 1: 0.1}} # 场景1下带宽只剩 10%，负载率飙升至 1000%

        # 路径及其包含的链路
        self.P_in = {}
        self.P_out = {}
        for i in self.I:
            for m in self.M:
                self.P_in[(i, m)]  = [(0,)]
                self.P_out[(i, m)] = [(0,)]

        self.P_cost_in  = {(0,): 2}
        self.P_cost_out = {(0,): 1}

        # 场景概率：让故障场景占 20%
        self.prob = {0: 0.8, 1: 0.2}

        # CVaR 参数
        self.beta_N = 0.95
        self.beta_L = 0.95

        # 预处理：仅保留满足时延和容量约束的 (i,m)
        self.valid_assign = {}
        for i in self.I:
            for m in self.M:
                self.valid_assign[(i, m)] = True # 时延宽松
'''
class SimpleData:
    def __init__(self):
        self.I = [0, 1, 2]
        self.M = [0, 1]
        self.E = [0]
        self.S = [0, 1]
        self.K = [0]

        self.w = {0: {0: 2}, 1: {0: 3}, 2: {0: 4}}
        self.p_price = {0: {0: 10}, 1: {0: 200}}
        self.C_normal = {0: {0: 10}, 1: {0: 10}}
        self.C_s = {
            0: {0: {0: 10, 1: 1.0}},
            1: {0: {0: 10, 1: 10}}
        }

        self.b_in  = {0: 5, 1: 4, 2: 6}
        self.b_out = {0: 2, 1: 1, 2: 3}

        self.delay_user_to_m = {
            0: {0: 10, 1: 10},
            1: {0: 10, 1: 10},
            2: {0: 10, 1: 10}
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

        # 预处理：仅保留满足时延和容量约束的 (i,m)
        self.valid_assign = {}
        for i in self.I:
            for m in self.M:
                delay_ok = (self.delay_user_to_m[i][m] <= self.max_access_delay[i])
                cap_ok = all(self.w[i][k] <= self.C_normal[m][k] for k in self.K)
                self.valid_assign[(i, m)] = delay_ok and cap_ok
'''

def build_weighted_objective_model(data, lambda_val=1.0):
    """
    加权目标模型:
        min  Cost + lambda_val * ( NodeCVaR + LinkCVaR )
    其中 NodeCVaR, LinkCVaR 分别为节点和链路的 CVaR 值。
    """
    model = gp.Model("Weighted_Cost_CVaR")

    # 1. 变量
    y = model.addVars(
        ((i, m) for (i, m), ok in data.valid_assign.items() if ok),
        vtype=GRB.BINARY, name="y"
    )

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

    zeta_N = model.addVar(lb=-GRB.INFINITY, name="zeta_N")
    u_s = model.addVars(data.S, lb=0, name="u_s")
    zeta_L = model.addVar(lb=-GRB.INFINITY, name="zeta_L")
    v_s = model.addVars(data.S, lb=0, name="v_s")

    # 2. 成本分项
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
    total_cost = placement_cost + bw_cost

    # 3. CVaR 表达式（线性）
    node_cvar = zeta_N + (1 / (1 - data.beta_N)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)
    link_cvar = zeta_L + (1 / (1 - data.beta_L)) * gp.quicksum(data.prob[s] * v_s[s] for s in data.S)

    # 4. 加权目标
    model.setObjective(total_cost + lambda_val * (node_cvar + link_cvar), GRB.MINIMIZE)

    # 5. 约束（与之前基本一致，但去掉 Gamma 上界）
    model.addConstrs(
        (gp.quicksum(y[i, m] for m in data.M if (i, m) in y) == 1
         for i in data.I), name="Task_Unique"
    )

    model.addConstrs(
        (gp.quicksum(x_in[i, m][p] for p in data.P_in.get((i, m), [])) == y[i, m] * data.b_in[i]
         for (i, m) in y), name="FlowCons_In")
    model.addConstrs(
        (gp.quicksum(x_out[i, m][q] for q in data.P_out.get((i, m), [])) == y[i, m] * data.b_out[i]
         for (i, m) in y), name="FlowCons_Out")

    for m in data.M:
        for k in data.K:
            model.addConstr(
                gp.quicksum(y[i, m] * data.w[i][k] for i in data.I if (i, m) in y) <= data.C_normal[m][k],
                name=f"NodeCap_{m}_{k}")

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

    for s in data.S:
        for m in data.M:
            for k in data.K:
                model.addConstr(
                    u_s[s] >= gp.quicksum(y[i, m] * data.w[i][k] for i in data.I if (i, m) in y) / data.C_s[m][k][s] - zeta_N,
                    name=f"NodeLoss_{s}_{m}_{k}")

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
    model._y = y
    model._x_in = x_in
    model._x_out = x_out
    model._zeta_N = zeta_N
    model._zeta_L = zeta_L
    model._u = u_s
    model._v = v_s
    model._node_cvar = node_cvar
    model._link_cvar = link_cvar
    model._total_cost = total_cost
    return model


if __name__ == "__main__":
    data = SimpleData()

    # 尝试不同的 lambda 值，观察成本与风险的权衡
    for lam in [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]:
        model = build_weighted_objective_model(data, lambda_val=lam)
        model.setParam('OutputFlag', 0)  # 关闭详细日志
        model.setParam('MIPGap', 1e-4)
        model.optimize()

        if model.status == GRB.OPTIMAL:
            print(f"\n--- lambda = {lam} ---")
            print(f"Objective = {model.objVal:.4f}")
            cost = model._total_cost.getValue()
            node_cvar = model._node_cvar.getValue()
            link_cvar = model._link_cvar.getValue()
            print(f"Total Cost = {cost:.4f}")
            print(f"Node CVaR = {node_cvar:.4f}, Link CVaR = {link_cvar:.4f}")

            # 任务放置
            print("Task Placement:", end=" ")
            for (i, m), var in model._y.items():
                if var.X > 0.5:
                    print(f"T{i}->N{m}", end=" ")
            print()
        else:
            print(f"Lambda {lam}: Model infeasible or error.")