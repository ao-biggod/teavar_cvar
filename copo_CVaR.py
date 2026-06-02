import gurobipy as gp
from gurobipy import GRB

def build_copo_cvar_model(data):
    """
    data: 包含所有输入参数的字典/对象，如 I(任务), M(节点), E(链路), S(场景), K(资源维度) 等
    预处理要求：P_in[i,m] 和 P_out[i,m] 必须在传入前进行时延过滤 (对应Eq.5的静态剪枝)
    """
    model = gp.Model("Copo_CVaR_Joint_Optimization")
    
    # ==========================================
    # 变量定义 (Eq. 17 - Eq. 18)
    # ==========================================
    # 任务部署变量 (Binary)
    y = model.addVars(data.I, data.M, vtype=GRB.BINARY, name="y")
    
    # 流量分配变量 (Continuous, 仅在合法路径上创建变量，极大地降低矩阵规模)
    x_in = {}
    x_out = {}
    for i in data.I:
        for m in data.M:
            for p in data.P_in[i,m]:
                x_in[i,m,p] = model.addVar(lb=0, name=f"x_in_{i}_{m}_{p}")
            for q in data.P_out[i,m]:
                x_out[i,m,q] = model.addVar(lb=0, name=f"x_out_{i}_{m}_{q}")
                
    # CVaR 风险变量
    zeta_N = model.addVar(lb=0, name="zeta_N")
    u_s = model.addVars(data.S, lb=0, name="u_s")
    zeta_L = model.addVar(lb=0, name="zeta_L")
    v_s = model.addVars(data.S, lb=0, name="v_s")
    
    # 对偶变量
    mu = model.addVars(data.S, data.E, lb=0, name="mu")

    # ==========================================
    # 一、目标函数 (Eq. 1 - Eq. 3)
    # ==========================================
    # Eq. 2: 节点 k-dim 部署成本 (向量内积)
    E_placement = gp.quicksum(y[i,m] * sum(data.w[i][k] * data.p_price[m][k] for k in data.K) 
                              for i in data.I for m in data.M)
    
    # Eq. 3: 链路带宽成本
    E_bandwidth = gp.quicksum(x_in[i,m,p] * data.P_cost_in[p] for i in data.I for m in data.M for p in data.P_in[i,m]) + \
                  gp.quicksum(x_out[i,m,q] * data.P_cost_out[q] for i in data.I for m in data.M for q in data.P_out[i,m])
                  
    # Eq. 1: 最小化总成本
    model.setObjective(E_placement + E_bandwidth, GRB.MINIMIZE)

    # ==========================================
    # 二、物理与业务硬约束
    # ==========================================
    # Eq. 4: 任务唯一性部署
    model.addConstrs((y.sum(i, '*') == 1 for i in data.I), name="Eq4_Task_Assignment")
    
    # Eq. 5: 接入时延约束 (动态约束实现)
    model.addConstrs((y[i,m] * data.delay_user_to_m[i][m] <= data.max_access_delay[i] 
                      for i in data.I for m in data.M), name="Eq5_Access_Delay")

    # Eq. 6: 去程流量守恒 (此次严格补全)
    model.addConstrs((gp.quicksum(x_in[i,m,p] for p in data.P_in[i,m]) == y[i,m] * data.b_in[i] 
                      for i in data.I for m in data.M), name="Eq6_Flow_Conservation_In")
    
    # Eq. 7: 回程流量守恒 (此次严格补全)
    model.addConstrs((gp.quicksum(x_out[i,m,q] for q in data.P_out[i,m]) == y[i,m] * data.b_out[i] 
                      for i in data.I for m in data.M), name="Eq7_Flow_Conservation_Out")

    # Eq. 8: 节点 k 维资源容量硬约束 (常态无故障)
    for m in data.M:
        for k in data.K:
            model.addConstr(gp.quicksum(y[i,m] * data.w[i][k] for i in data.I) <= data.C_normal[m][k], 
                            name=f"Eq8_Node_Capacity_{m}_{k}")

    # Eq. 9: 链路带宽物理上限硬约束 (常态无故障)
    for e in data.E:
        load_e_normal = gp.quicksum(x_in[i,m,p] for i in data.I for m in data.M for p in data.P_in[i,m] if e in p) + \
                        gp.quicksum(x_out[i,m,q] for i in data.I for m in data.M for q in data.P_out[i,m] if e in q)
        model.addConstr(load_e_normal <= data.B[e], name=f"Eq9_Link_Capacity_{e}")

    # ==========================================
    # 三、双重 CVaR 风险约束
    # ==========================================
    # Eq. 10 & 11: 算力节点风险约束 (Node CVaR)
    model.addConstr(zeta_N + (1/(1-data.beta_N)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S) <= data.Gamma_N, 
                    name="Eq10_Node_CVaR_Limit")
    for s in data.S:
        for m in data.M:
            for k in data.K:
                # C_s[m][k][s] 表示在场景 s 下节点 m 的实际 k 维容量
                node_util = gp.quicksum(y[i,m] * data.w[i][k] for i in data.I) / data.C_s[m][k][s]
                model.addConstr(u_s[s] >= node_util - zeta_N, name=f"Eq11_Node_Loss_{s}_{m}_{k}")

    # Eq. 12 - 14: 链路网络风险约束 (Link CVaR)
    model.addConstr(zeta_L + (1/(1-data.beta_L)) * gp.quicksum(data.prob[s] * v_s[s] for s in data.S) <= data.Gamma_L, 
                    name="Eq13_Link_CVaR_Limit")
    for s in data.S:
        for e in data.E:
            # Eq. 12: 计算场景 s 下由于存活状态 sigma_e(s) 导致的实际负载折算
            load_e_s = (gp.quicksum(x_in[i,m,p] for i in data.I for m in data.M for p in data.P_in[i,m] if e in p) + \
                        gp.quicksum(x_out[i,m,q] for i in data.I for m in data.M for q in data.P_out[i,m] if e in q)) * data.sigma[e][s]
            
            # Eq. 14: 超额损失计算
            model.addConstr(v_s[s] >= (load_e_s / data.B[e]) - zeta_L, name=f"Eq14_Link_Loss_{s}_{e}")

            # ==========================================
            # 四、KKT 互补松弛与线性化 (Eq. 15 - Eq. 16)
            # ==========================================
            # 使用 Gurobi 原生 Indicator 约束替代显式 Big-M，极大提升 Presolve 效率与数值稳定性
            z = model.addVar(vtype=GRB.BINARY, name=f"z_{s}_{e}")
            
            # 当 z=0 时，对偶变量 mu=0 (未触碰拥塞边界)
            model.addGenConstrIndicator(z, 0, mu[s,e] == 0, name=f"Eq15_KKT_mu_{s}_{e}")
            # 当 z=1 时，v_s 精确贴合当前链路的拥塞溢出值 (触碰拥塞边界)
            model.addGenConstrIndicator(z, 1, v_s[s] == (load_e_s / data.B[e]) - zeta_L, name=f"Eq16_KKT_v_{s}_{e}")

    model.update()
    return model