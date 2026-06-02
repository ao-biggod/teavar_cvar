import gurobipy as gp
from gurobipy import GRB

# ============================================================
# 1. 重新设计的复杂数据集：制造成本‑风险冲突
# ============================================================
class TradeoffData:
    def __init__(self):
        self.I = list(range(15))      # 15个任务
        self.M = [0, 1, 2, 3]         # 4个节点
        self.K = [0, 1, 2]            # 0:CPU, 1:GPU, 2:HBM
        self.S = [0, 1, 2]            # 场景0:正常; 1:链路中断; 2:节点0容量暴跌

        # 节点资源价格：节点0便宜，节点2适中，节点3昂贵
        self.p_price = {
            0: {0: 10, 1: 50, 2: 20},   # 便宜但危险
            1: {0: 20, 1: 80, 2: 40},   # 中等
            2: {0: 40, 1: 150, 2: 80},  # 昂贵但安全
            3: {0: 60, 1: 200, 2: 120}  # 最贵最安全
        }

        # 任务三维需求 (w_i,k): 模拟不同类型
        self.w = {}
        for i in range(5):      # AI推理型
            self.w[i] = {0: 4, 1: 2, 2: 8}
        for i in range(5, 10):  # 通用计算型
            self.w[i] = {0: 8, 1: 0, 2: 4}
        for i in range(10, 15): # 内存密集型
            self.w[i] = {0: 2, 1: 1, 2: 32}

        # 总需求：CPU: 5*4+5*8+5*2=70；GPU: 5*2+0+5*1=15；HBM: 5*8+5*4+5*32=220

        # 常态容量：节点0充足，节点2、3更大以容纳迁移
        self.C_normal = {
            0: {0: 80, 1: 20, 2: 200},   # 刚好足够，但场景2会崩
            1: {0: 40, 1: 20, 2: 50},    # 容量小，只能放少量任务
            2: {0: 100, 1: 50, 2: 200},  # 安全且大
            3: {0: 100, 1: 50, 2: 200}   # 安全且大
        }

        # 场景下节点容量：场景2节点0资源几乎清零
        self.C_s = {m: {k: {s: self.C_normal[m][k] for s in self.S} for k in self.K} for m in self.M}
        # 场景1不变，场景2：节点0容量崩塌
        for k in self.K:
            self.C_s[0][k][2] = self.C_normal[0][k] * 0.1   # 只剩10%

        # 拓扑：完全图，12条有向链路
        self.E = [(u, v) for u in self.M for v in self.M if u != v]
        # 链路容量：降低至150，使单个链路可能成为瓶颈
        self.B = {e: 150 for e in self.E}

        # 候选路径：直连 + 一条绕路
        self.P_cand = {}
        for u in self.M:
            for v in self.M:
                if u == v:
                    self.P_cand[u, v] = [[]]
                else:
                    direct = [(u, v)]
                    # 选择中转点：如果 (u+1)%4 != v 则用 (u+1)%4，否则用 (u+2)%4
                    k = (u + 1) % 4
                    if k == v:
                        k = (u + 2) % 4
                    detour = [(u, k), (k, v)]
                    self.P_cand[u, v] = [direct, detour]

        # 场景概率与链路存活
        self.prob = {0: 0.6, 1: 0.3, 2: 0.1}
        self.sigma = {e: {s: 1.0 for s in self.S} for e in self.E}
        # 场景1：核心链路 (0,2) 和 (2,0) 中断
        self.sigma[(0, 2)][1] = 0.0
        self.sigma[(2, 0)][1] = 0.0

        # 业务带宽需求
        self.b_in = {i: 20 for i in self.I}
        self.b_out = {i: 10 for i in self.I}

        self.beta_N, self.beta_L = 0.95, 0.95

        # 为简化，所有分配均视为合法（可进一步加入时延约束，这里省略）
        self.valid_assign = {(i, m): True for i in self.I for m in self.M}


# ============================================================
# 2. 构建加权目标模型
# ============================================================
def build_tradeoff_model(data, lambda_val=1.0):
    model = gp.Model("Tradeoff_CVaR")

    # 决策变量
    y = model.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")

    x_in = {}
    x_out = {}
    for i in data.I:
        for m in data.M:
            for p_idx in range(len(data.P_cand[0, m])):   # 假设源节点为0
                x_in[i, m, p_idx] = model.addVar(lb=0, name=f"xin_{i}_{m}_{p_idx}")
            for q_idx in range(len(data.P_cand[m, 0])):   # 假设目的节点为0
                x_out[i, m, q_idx] = model.addVar(lb=0, name=f"xout_{i}_{m}_{q_idx}")

    zeta_N = model.addVar(lb=-GRB.INFINITY, name="zeta_N")
    u_s = model.addVars(data.S, lb=0, name="u_s")
    zeta_L = model.addVar(lb=-GRB.INFINITY, name="zeta_L")
    v_s = model.addVars(data.S, lb=0, name="v_s")

    # 目标函数
    E_placement = gp.quicksum(
        y[i, m] * sum(data.w[i][k] * data.p_price[m][k] for k in data.K)
        for (i, m) in data.valid_assign
    )
    # 带宽成本：以路径跳数作为成本权重
    E_bandwidth = gp.quicksum(
        x_in[i, m, p_idx] * len(data.P_cand[0, m][p_idx])
        for i in data.I for m in data.M for p_idx in range(len(data.P_cand[0, m]))
    ) + gp.quicksum(
        x_out[i, m, q_idx] * len(data.P_cand[m, 0][q_idx])
        for i in data.I for m in data.M for q_idx in range(len(data.P_cand[m, 0]))
    )

    node_cvar = zeta_N + (1 / (1 - data.beta_N)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)
    link_cvar = zeta_L + (1 / (1 - data.beta_L)) * gp.quicksum(data.prob[s] * v_s[s] for s in data.S)

    model.setObjective(E_placement + E_bandwidth + lambda_val * (node_cvar + link_cvar), GRB.MINIMIZE)

    # 约束
    # 任务唯一性
    model.addConstrs((y.sum(i, '*') == 1 for i in data.I), name="TaskUnique")

    # 流量守恒：去程与回程总和等于任务带宽需求
    for i in data.I:
        for m in data.M:
            model.addConstr(
                gp.quicksum(x_in[i, m, p_idx] for p_idx in range(len(data.P_cand[0, m]))) == y[i, m] * data.b_in[i],
                name=f"FlowCons_In_{i}_{m}"
            )
            model.addConstr(
                gp.quicksum(x_out[i, m, q_idx] for q_idx in range(len(data.P_cand[m, 0]))) == y[i, m] * data.b_out[i],
                name=f"FlowCons_Out_{i}_{m}"
            )

    # 常态节点容量
    for m in data.M:
        for k in data.K:
            model.addConstr(
                gp.quicksum(y[i, m] * data.w[i][k] for i in data.I) <= data.C_normal[m][k],
                name=f"NodeCap_{m}_{k}"
            )

    # 节点 CVaR 约束
    for s in data.S:
        for m in data.M:
            for k in data.K:
                util = gp.quicksum(y[i, m] * data.w[i][k] for i in data.I) / data.C_s[m][k][s]
                model.addConstr(u_s[s] >= util - zeta_N, name=f"NodeRisk_{s}_{m}_{k}")

    # 链路 CVaR 约束
    for s in data.S:
        for e in data.E:
            flow_e = gp.LinExpr()
            # 去程
            for i in data.I:
                for m in data.M:
                    for p_idx, path in enumerate(data.P_cand[0, m]):
                        if e in path:
                            flow_e += x_in[i, m, p_idx]
            # 回程
            for i in data.I:
                for m in data.M:
                    for q_idx, path in enumerate(data.P_cand[m, 0]):
                        if e in path:
                            flow_e += x_out[i, m, q_idx]

            cap_e_s = data.B[e] * data.sigma[e][s]
            if cap_e_s > 1e-6:
                model.addConstr(v_s[s] >= flow_e / cap_e_s - zeta_L, name=f"LinkRisk_{s}_{e}")
            else:
                # 链路完全中断时，该链路流量必须为0（已由生存性约束隐含，此处强制）
                model.addConstr(flow_e == 0, name=f"LinkFail_{s}_{e}")

    model.update()
    # 保存关键变量供后续查询
    model._y = y
    model._zeta_N = zeta_N
    model._u = u_s
    model._v = v_s
    model._node_cvar_expr = node_cvar
    model._link_cvar_expr = link_cvar
    model._cost_expr = E_placement + E_bandwidth
    return model


# ============================================================
# 3. 运行测试：多 λ 扫描
# ============================================================
if __name__ == "__main__":
    data = TradeoffData()
    lambda_list = [0.1, 1.0, 5.0, 20.0, 100.0]

    for lam in lambda_list:
        model = build_tradeoff_model(data, lambda_val=lam)
        model.setParam('OutputFlag', 0)
        model.setParam('MIPGap', 1e-4)
        model.optimize()

        if model.status == GRB.OPTIMAL:
            print(f"\nλ = {lam:6.1f} | Obj = {model.ObjVal:10.2f} | "
                  f"Cost = {model._cost_expr.getValue():8.2f} | "
                  f"NodeCVaR = {model._node_cvar_expr.getValue():6.4f} | "
                  f"LinkCVaR = {model._link_cvar_expr.getValue():6.4f}")
            # 部署分布统计
            dist = {m: sum(1 for i in data.I if model._y[i, m].X > 0.5) for m in data.M}
            print(f"  Deployment: {dist}")

            # 显示部分 u_s, v_s
            u_vals = {s: model._u[s].X for s in data.S}
            v_vals = {s: model._v[s].X for s in data.S}
            print(f"  u_s: {u_vals}")
            print(f"  v_s: {v_vals}")
        else:
            print(f"\nλ = {lam:6.1f} | Infeasible or Error")