import gurobipy as gp
from gurobipy import GRB

# =====================================================================
# 1. 构建模拟数据集 (Mock Data) - 保证代码复制即运行
# =====================================================================
class MockData:
    def __init__(self):
        self.I = ['task1', 'task2']        # 任务集
        self.M = ['node1', 'node2']        # 计算节点集
        self.E = ['link1', 'link2']        # 物理链路集
        self.S = ['scen1', 'scen2']        # 故障场景集
        self.K = ['cpu', 'gpu']            # k-dim 资源维度

        self.w = {'task1': {'cpu': 4, 'gpu': 1}, 'task2': {'cpu': 8, 'gpu': 2}}
        self.p_price = {'node1': {'cpu': 0.1, 'gpu': 1.5}, 'node2': {'cpu': 0.15, 'gpu': 1.2}}
        self.b_in = {'task1': 10, 'task2': 20}
        self.b_out = {'task1': 5, 'task2': 10}
        
        self.P_in = {('task1', 'node1'): ['p_in_1'], ('task1', 'node2'): ['p_in_2'],
                     ('task2', 'node1'): ['p_in_3'], ('task2', 'node2'): ['p_in_4']}
        self.P_out = {('task1', 'node1'): ['p_out_1'], ('task1', 'node2'): ['p_out_2'],
                      ('task2', 'node1'): ['p_out_3'], ('task2', 'node2'): ['p_out_4']}
        
        self.P_cost_in = {'p_in_1': 2, 'p_in_2': 3, 'p_in_3': 2, 'p_in_4': 4}
        self.P_cost_out = {'p_out_1': 1, 'p_out_2': 2, 'p_out_3': 1, 'p_out_4': 3}
        
        self.path_links = {
            'p_in_1': ['link1'], 'p_in_2': ['link2'], 'p_in_3': ['link1'], 'p_in_4': ['link1', 'link2'],
            'p_out_1': ['link2'], 'p_out_2': ['link1'], 'p_out_3': ['link2'], 'p_out_4': ['link1', 'link2']
        }
        
        self.delay_user_to_m = {'task1': {'node1': 10, 'node2': 50}, 'task2': {'node1': 20, 'node2': 15}}
        self.max_access_delay = {'task1': 30, 'task2': 30}
        
        self.C_normal = {'node1': {'cpu': 32, 'gpu': 4}, 'node2': {'cpu': 64, 'gpu': 8}}
        self.B = {'link1': 100, 'link2': 100}
        
        self.prob = {'scen1': 0.99, 'scen2': 0.01} 
        self.sigma = {'link1': {'scen1': 1, 'scen2': 0}, 'link2': {'scen1': 1, 'scen2': 1}} 
        self.C_s = {
            'node1': {'cpu': {'scen1': 32, 'scen2': 16}, 'gpu': {'scen1': 4, 'scen2': 2}},
            'node2': {'cpu': {'scen1': 64, 'scen2': 64}, 'gpu': {'scen1': 8, 'scen2': 8}}
        }
        
        # KKT双层模型中，下层CVaR通过导数为0被强制推向绝对极小值
        self.beta_N = 0.95
        self.beta_L = 0.95

data = MockData()

# =====================================================================
# 2. 构建 Gurobi 模型 (Copo KKT 版本)
# =====================================================================
model = gp.Model("Copo_CVaR_BiLevel_KKT")

# --- 1. 上层决策变量 ---
y = model.addVars(data.I, data.M, vtype=GRB.BINARY, name="y")
x_in = model.addVars(data.I, data.M, [p for paths in data.P_in.values() for p in paths], lb=0, name="x_in")
x_out = model.addVars(data.I, data.M, [q for paths in data.P_out.values() for q in paths], lb=0, name="x_out")

# --- 2. 下层 CVaR 原始变量 ---
zeta_N = model.addVar(lb=-GRB.INFINITY, name="zeta_N")
u_s = model.addVars(data.S, lb=0, name="u_s")
zeta_L = model.addVar(lb=-GRB.INFINITY, name="zeta_L")
v_s = model.addVars(data.S, lb=0, name="v_s")

# --- 3. 下层 KKT 对偶变量 ---
lam = model.addVars(data.S, data.M, data.K, lb=0, name="lam")  # 算力对偶
mu = model.addVars(data.S, lb=0, name="mu")                    # 算力对偶(非负)
alpha = model.addVars(data.S, data.E, lb=0, name="alpha")      # 网络对偶
gamma = model.addVars(data.S, lb=0, name="gamma")              # 网络对偶(非负)

# --- 4. 互补松弛二进制辅助变量 (替代大 M 法) ---
z_lam = model.addVars(data.S, data.M, data.K, vtype=GRB.BINARY, name="z_lam")
z_mu = model.addVars(data.S, vtype=GRB.BINARY, name="z_mu")
z_alpha = model.addVars(data.S, data.E, vtype=GRB.BINARY, name="z_alpha")
z_gamma = model.addVars(data.S, vtype=GRB.BINARY, name="z_gamma")

# =====================================================================
# 3. 上层目标函数 (Cost Minimization)
# =====================================================================
E_placement = gp.quicksum(y[i,m] * sum(data.w[i][k] * data.p_price[m][k] for k in data.K) for i in data.I for m in data.M)
E_bandwidth = gp.quicksum(x_in[i,m,p] * data.P_cost_in[p] for i in data.I for m in data.M for p in data.P_in[i,m]) + \
              gp.quicksum(x_out[i,m,q] * data.P_cost_out[q] for i in data.I for m in data.M for q in data.P_out[i,m])

model.setObjective(E_placement + E_bandwidth, GRB.MINIMIZE)

# =====================================================================
# 4. 上层基础物理约束 (与单层法完全相同)
# =====================================================================
model.addConstrs((y.sum(i, '*') == 1 for i in data.I), name="Task_Assignment")
model.addConstrs((y[i,m] * data.delay_user_to_m[i][m] <= data.max_access_delay[i] for i in data.I for m in data.M), name="Access_Delay")
model.addConstrs((gp.quicksum(x_in[i,m,p] for p in data.P_in[i,m]) == y[i,m] * data.b_in[i] for i in data.I for m in data.M), name="Flow_In")
model.addConstrs((gp.quicksum(x_out[i,m,q] for q in data.P_out[i,m]) == y[i,m] * data.b_out[i] for i in data.I for m in data.M), name="Flow_Out")

for m in data.M:
    for k in data.K:
        model.addConstr(gp.quicksum(y[i,m] * data.w[i][k] for i in data.I) <= data.C_normal[m][k], name=f"Cap_Node_{m}_{k}")

for e in data.E:
    load_e_normal = gp.quicksum(x_in[i,m,p] for i in data.I for m in data.M for p in data.P_in[i,m] if e in data.path_links[p]) + \
                    gp.quicksum(x_out[i,m,q] for i in data.I for m in data.M for q in data.P_out[i,m] if e in data.path_links[q])
    model.addConstr(load_e_normal <= data.B[e], name=f"Cap_Link_{e}")

# =====================================================================
# 5. 下层 KKT 约束 (强制下层性能最优)
# =====================================================================

# ----------------- [A] 算力 CVaR 的 KKT -----------------
# 1. KKT 平稳性 (导数为0)
model.addConstr(gp.quicksum(lam[s,m,k] for s in data.S for m in data.M for k in data.K) == 1, name="KKT_Stat_zeta_N")
for s in data.S:
    model.addConstr(gp.quicksum(lam[s,m,k] for m in data.M for k in data.K) + mu[s] == data.prob[s]/(1-data.beta_N), name=f"KKT_Stat_u_{s}")

# 2. KKT 原始可行性 (Primal) 与 互补松弛 (Complementary Slackness)
for s in data.S:
    for m in data.M:
        for k in data.K:
            node_util_s = gp.quicksum(y[i,m] * data.w[i][k] for i in data.I) / data.C_s[m][k][s]
            # 原始可行性
            model.addConstr(u_s[s] >= node_util_s - zeta_N, name=f"Primal_Node_{s}_{m}_{k}")
            
            # 互补松弛 (利用 Indicator 替代大 M)
            # z_lam=1 => 对偶变量 lam=0
            model.addGenConstrIndicator(z_lam[s,m,k], True, lam[s,m,k] == 0)
            # z_lam=0 => 约束紧边界 (等号成立)
            model.addGenConstrIndicator(z_lam[s,m,k], False, u_s[s] - node_util_s + zeta_N == 0)

    # u_s 的非负互补松弛
    model.addGenConstrIndicator(z_mu[s], True, mu[s] == 0)
    model.addGenConstrIndicator(z_mu[s], False, u_s[s] == 0)

# ----------------- [B] 链路 CVaR 的 KKT -----------------
# 1. KKT 平稳性 (导数为0)
model.addConstr(gp.quicksum(alpha[s,e] for s in data.S for e in data.E) == 1, name="KKT_Stat_zeta_L")
for s in data.S:
    model.addConstr(gp.quicksum(alpha[s,e] for e in data.E) + gamma[s] == data.prob[s]/(1-data.beta_L), name=f"KKT_Stat_v_{s}")

# 2. KKT 原始可行性 (Primal) 与 互补松弛 (Complementary Slackness)
for s in data.S:
    for e in data.E:
        L_e_s = (gp.quicksum(x_in[i,m,p] for i in data.I for m in data.M for p in data.P_in[i,m] if e in data.path_links[p]) + \
                 gp.quicksum(x_out[i,m,q] for i in data.I for m in data.M for q in data.P_out[i,m] if e in data.path_links[q])) * data.sigma[e][s]
        
        # 原始可行性
        model.addConstr(v_s[s] >= L_e_s / data.B[e] - zeta_L, name=f"Primal_Link_{s}_{e}")
        
        # 互补松弛 (利用 Indicator 替代大 M)
        model.addGenConstrIndicator(z_alpha[s,e], True, alpha[s,e] == 0)
        model.addGenConstrIndicator(z_alpha[s,e], False, v_s[s] - (L_e_s / data.B[e]) + zeta_L == 0)

    # v_s 的非负互补松弛
    model.addGenConstrIndicator(z_gamma[s], True, gamma[s] == 0)
    model.addGenConstrIndicator(z_gamma[s], False, v_s[s] == 0)

# =====================================================================
# 6. 执行求解
# =====================================================================
# 设置 MIPGap 或 TimeLimit 以防大规模 KKT 模型求解过久
model.setParam('MIPGap', 0.05)
model.optimize()

if model.status == GRB.OPTIMAL:
    print("\n[KKT 双层优化 - 求解成功]")
    print(f"最小化总成本 (Objective Cost): {model.ObjVal:.2f}")
    
    # 通过变量计算实际的下层优化极值 (CVaR)
    cvar_node = zeta_N.X + (1/(1-data.beta_N)) * sum(data.prob[s]*u_s[s].X for s in data.S)
    cvar_link = zeta_L.X + (1/(1-data.beta_L)) * sum(data.prob[s]*v_s[s].X for s in data.S)
    
    print(f"被 KKT 强制逼近的算力最小 CVaR: {cvar_node:.4f}")
    print(f"被 KKT 强制逼近的网络最小 CVaR: {cvar_link:.4f}")
    
    print("\n--- 任务部署方案 ---")
    for i in data.I:
        for m in data.M:
            if y[i,m].X > 0.5:
                print(f"任务 {i} -> 部署节点 {m}")
else:
    print("\n[求解失败] 双层规划 KKT 约束过于严格或无可行解。")