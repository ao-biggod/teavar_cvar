import gurobipy as gp
from gurobipy import GRB

from duibi_metrics import teavar_flow_anchors, is_umcf_auxiliary_edge, bandwidth_cost_expr

# 1.实验数据集
class UltraComplexData:
    def __init__(self):
        self.I = list(range(10))
        self.M = [0, 1, 2, 3]  # 4个节点
        self.K = [0, 1, 2]    #节点计算资源维度：0-CPU, 1-GPU, 2-HBM
        self.S = [0, 1, 2]    #场景：0-正常, 1-链路中断, 2-节点0容量暴跌

        self.p_price = {
            0: {0: 10, 1: 50, 2: 20},
            1: {0: 15, 1: 70, 2: 30},
            2: {0: 40, 1: 180, 2: 90},
            3: {0: 50, 1: 220, 2: 120}
        }#节点价格：节点0和节点3价格差异大，方便后续判断

        self.w = {i: {0: 4, 1: 2, 2: 8} for i in range(4)}    
        self.w.update({i: {0: 8, 1: 0, 2: 4} for i in range(4, 7)}) 
        self.w.update({i: {0: 2, 1: 1, 2: 32} for i in range(7, 10)}) # 10个任务：前4个AI推理型需要GPU，后3个通用计算型不需要GPU但是CPU用量大，最后3个HBM用量大

        self.E = [(u, v) for u in self.M for v in self.M if u != v]  #路径生成，全连接有向线路12条3*2*2
        self.B = {e: 200 for e in self.E}  #路径容量，简单定义成每条路径容量相等

        self.P_cand = {}
        for u in self.M:
            for v in self.M:
                if u == v: self.P_cand[u, v] = [[]]
                else:
                    path_direct = [(u, v)]
                    k = (u + 1) % 4 if (u + 1) % 4 != v else (u + 2) % 4
                    path_detour = [(u, k), (k, v)]
                    self.P_cand[u, v] = [path_direct, path_detour]
        #候选路径选择，每两个节点间有两条路径：一条直连，一条绕路，且不相交，没有应用到KSP等路径算法

        self.prob = {0: 0.6, 1: 0.3, 2: 0.1}  #节点故障概率，正常场景占60%，链路中断占30%，节点0容量暴跌占10%
        self.sigma = {e: {s: 1.0 for s in self.S} for e in self.E} #链路可用性设计：正常场景全可用，链路中断场景所有链路不可用，节点0容量暴跌场景所有链路可用（因为是节点问题不是链路问题）
        self.sigma[(0, 2)][1] = 0.0 #//链路中断场景下，链路(0,2)不可用
        self.sigma[(2, 0)][1] = 0.0 #//链路中断场景下，链路(2,0)不可用

        self.C_s = {m: {k: {s: 150.0 for s in self.S} for k in self.K} for m in self.M}   
        for k in self.K:
            self.C_s[0][k][2] = 2.0  #// 场景2下节点0容量暴跌，所有资源维度都只剩2，极大增加风险权重时会倾向于避开节点0
            self.C_s[1][k][2] = 2.0  #// 中等区灾难坍塌，增加风险权重时会倾向于避开节点0和节点1
            
        self.C_normal = {m: {k: 150 for k in self.K} for m in self.M}  #常态容量，所有节点和资源维度都充足，方便观察风险权重调整时的迁移行为
        self.b_in = {i: 20 for i in self.I}  #输入数据量，所有任务相同，方便观察风险权重调整时的迁移行为
        self.b_out = {i: 10 for i in self.I} #输出数据量，所有任务相同，方便观察风险权重调整时的迁移行为
        self.alpha_N, self.alpha_L = 0.95, 0.95  # CVaR confidence level (paper: α)
        self.valid_assign = {(i, m): True for i in self.I for m in self.M}  #//预处理：所有任务和节点组合都合法，方便观察风险权重调整时的迁移行为
        self.hub = 0
        self.sigma_vs = None
        self.sigma_vt = None
        self.umcf_virtual_nodes = False
        self.bandwidth_price_scale = 1.0
        self.bandwidth_price_mode = "uniform"


def _placement_hub(data) -> int:
    """放置、min_off_hub、stress 仍用的物理 hub（与 B4 hub_index / 玩具默认 0 一致）。"""
    return int(getattr(data, "hub", 0))


# 2. 模型 A：单层加权模型
def build_single_layer_model(data, lambda_val):
    h = _placement_hub(data)
    src, dst = teavar_flow_anchors(data)
    m = gp.Model("Single_Layer")
    m.setParam('OutputFlag', 0)
    
    y = m.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")
    xin = {(i, node, p): m.addVar(lb=0) for i in data.I for node in data.M for p in range(len(data.P_cand[src, node]))}
    xout = {(i, node, q): m.addVar(lb=0) for i in data.I for node in data.M for q in range(len(data.P_cand[node, dst]))}

    zeta_N, zeta_L = m.addVar(lb=-GRB.INFINITY), m.addVar(lb=-GRB.INFINITY)
    u_s, v_s = m.addVars(data.S, lb=0), m.addVars(data.S, lb=0)

    cost_p = gp.quicksum(y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K) for i, node in y)
    cost_b = bandwidth_cost_expr(data, xin, xout, src, dst)
    
    node_cvar = zeta_N + (1 / (1 - data.alpha_N)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)
    link_cvar = zeta_L + (1 / (1 - data.alpha_L)) * gp.quicksum(data.prob[s] * v_s[s] for s in data.S)
    
    m.setObjective(cost_p + cost_b + lambda_val * (node_cvar + link_cvar), GRB.MINIMIZE)

    m.addConstrs((y.sum(i, '*') == 1 for i in data.I))
    for i in data.I:
        for node in data.M:
            m.addConstr(gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[src, node]))) == y[i, node] * data.b_in[i])
            m.addConstr(gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, dst]))) == y[i, node] * data.b_out[i])
            for k in data.K:
                m.addConstr(gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) <= data.C_normal[node][k])

    for s in data.S:
        for node in data.M:
            for k in data.K:
                m.addConstr(u_s[s] >= gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) / data.C_s[node][k][s] - zeta_N)

    for s in data.S:
        for e in data.E:
            flow_e = gp.LinExpr()
            for i, node, p in xin:
                if e in data.P_cand[src, node][p]: flow_e += xin[i, node, p]
            for i, node, q in xout:
                if e in data.P_cand[node, dst][q]: flow_e += xout[i, node, q]
            cap = data.B[e] * data.sigma[e][s]
            if cap > 0: m.addConstr(v_s[s] >= flow_e / cap - zeta_L)
            else: m.addConstr(flow_e == 0)

    m.optimize()
    if m.status != GRB.OPTIMAL:
        return m, None, None, None, y, xin, xout
    return m, (cost_p.getValue() + cost_b.getValue()), node_cvar.getValue(), link_cvar.getValue(), y, xin, xout

# 3. 模型 B：双层 KKT 模型 
def build_kkt_model(data, lambda_weight=1.0):
    h = _placement_hub(data)
    src, dst = teavar_flow_anchors(data)
    m = gp.Model("BiLevel_KKT_Weighted")
    m.setParam('OutputFlag', 0)
    m.setParam('MIPGap', 0.05) 
    
    y = m.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")
    xin = {(i, node, p): m.addVar(lb=0) for i in data.I for node in data.M for p in range(len(data.P_cand[src, node]))}
    xout = {(i, node, q): m.addVar(lb=0) for i in data.I for node in data.M for q in range(len(data.P_cand[node, dst]))}

    zeta_N, zeta_L = m.addVar(lb=-GRB.INFINITY), m.addVar(lb=-GRB.INFINITY)
    u_s, v_s = m.addVars(data.S, lb=0), m.addVars(data.S, lb=0)

    cost_p = gp.quicksum(y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K) for i, node in y)
    cost_b = bandwidth_cost_expr(data, xin, xout, src, dst)
    
    node_cvar = zeta_N + (1 / (1 - data.alpha_N)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)
    link_cvar = zeta_L + (1 / (1 - data.alpha_L)) * gp.quicksum(data.prob[s] * v_s[s] for s in data.S)
    
    # 核心修正：利用 lambda_weight 决定 KKT 模型的倾向
    m.setObjective(cost_p + cost_b + lambda_weight * (node_cvar + link_cvar), GRB.MINIMIZE)

    m.addConstrs((y.sum(i, '*') == 1 for i in data.I))
    for i in data.I:
        for node in data.M:
            m.addConstr(gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[src, node]))) == y[i, node] * data.b_in[i])
            m.addConstr(gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, dst]))) == y[i, node] * data.b_out[i])
            for k in data.K:
                m.addConstr(gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) <= data.C_normal[node][k])

    # KKT 1: 算力
    lam = m.addVars(data.S, data.M, data.K, lb=0)
    mu = m.addVars(data.S, lb=0)
    z_lam = m.addVars(data.S, data.M, data.K, vtype=GRB.BINARY)
    z_mu = m.addVars(data.S, vtype=GRB.BINARY)

    m.addConstr(gp.quicksum(lam[s, node, k] for s in data.S for node in data.M for k in data.K) == 1)
    for s in data.S:
        m.addConstr(gp.quicksum(lam[s, node, k] for node in data.M for k in data.K) + mu[s] == data.prob[s]/(1-data.alpha_N))
        for node in data.M:
            for k in data.K:
                util = gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) / data.C_s[node][k][s]
                m.addConstr(u_s[s] >= util - zeta_N) 
                m.addGenConstrIndicator(z_lam[s, node, k], True, u_s[s] - util + zeta_N == 0)
                m.addGenConstrIndicator(z_lam[s, node, k], False, lam[s, node, k] == 0)
        m.addGenConstrIndicator(z_mu[s], True, u_s[s] == 0)
        m.addGenConstrIndicator(z_mu[s], False, mu[s] == 0)

    # KKT 2: 网络
    alpha = {(s, e): m.addVar(lb=0) for s in data.S for e in data.E}
    gamma = m.addVars(data.S, lb=0)
    z_alpha = {(s, e): m.addVar(vtype=GRB.BINARY) for s in data.S for e in data.E}
    z_gamma = m.addVars(data.S, vtype=GRB.BINARY)

    m.addConstr(gp.quicksum(alpha[s, e] for s in data.S for e in data.E) == 1)
    for s in data.S:
        m.addConstr(gp.quicksum(alpha[s, e] for e in data.E) + gamma[s] == data.prob[s]/(1-data.alpha_L))
        for e in data.E:
            flow_e = gp.LinExpr()
            for i, node, p in xin:
                if e in data.P_cand[src, node][p]: flow_e += xin[i, node, p]
            for i, node, q in xout:
                if e in data.P_cand[node, dst][q]: flow_e += xout[i, node, q]
            cap = data.B[e] * data.sigma[e][s]
            if cap > 0:
                m.addConstr(v_s[s] >= flow_e / cap - zeta_L)
                m.addGenConstrIndicator(z_alpha[s, e], True, v_s[s] - (flow_e / cap) + zeta_L == 0)
                m.addGenConstrIndicator(z_alpha[s, e], False, alpha[s, e] == 0)
            else:
                m.addConstr(flow_e == 0)
                m.addConstr(v_s[s] >= -zeta_L) 
                m.addGenConstrIndicator(z_alpha[s, e], True, v_s[s] + zeta_L == 0)
                m.addGenConstrIndicator(z_alpha[s, e], False, alpha[s, e] == 0)
        m.addGenConstrIndicator(z_gamma[s], True, v_s[s] == 0)
        m.addGenConstrIndicator(z_gamma[s], False, gamma[s] == 0)

    m.optimize()
    if m.status != GRB.OPTIMAL:
        return m, None, None, None, y
    node_cvar = zeta_N.X + (1 / (1 - data.alpha_N)) * sum(data.prob[s] * u_s[s].X for s in data.S)
    link_cvar = zeta_L.X + (1 / (1 - data.alpha_L)) * sum(data.prob[s] * v_s[s].X for s in data.S)
    return m, (cost_p.getValue() + cost_b.getValue()), node_cvar, link_cvar, y


def _mccormick_slack_upper_bounds(data):
    """
    由 B4 等真实数据上的最大可能利用率量级，给出 McCormick 松弛中 slack 的保守上界
    （过小易不可行，过大则松弛变松）。仅用于 build_copo_mccormick_model。
    """
    max_ratio = 0.0
    for k in data.K:
        tot_w = sum(data.w[i][k] for i in data.I)
        for s in data.S:
            for node in data.M:
                den = float(data.C_s[node][k][s])
                if den > 1e-9:
                    max_ratio = max(max_ratio, tot_w / den)
    slack_n = max(80.0, 3.0 * max_ratio + 10.0)

    total_flow_ub = sum(float(data.b_in[i]) + float(data.b_out[i]) for i in data.I)
    max_link_ratio = 0.0
    for s in data.S:
        for e in data.E:
            if is_umcf_auxiliary_edge(data, e):
                continue
            cap = float(data.B[e]) * float(data.sigma[e][s])
            if cap > 1e-9:
                max_link_ratio = max(max_link_ratio, total_flow_ub / cap)
    slack_l = max(80.0, 3.0 * max_link_ratio + 10.0)
    return slack_n, slack_l


def build_epsilon_constraint_model(data, Gamma_N, Gamma_L):
    """
    ε-约束法模型 (风险预算模型)
    :param data: 实验数据集对象
    :param Gamma_N: 算力节点的最大允许风险阈值 (Risk Budget for Nodes)
    :param Gamma_L: 网络链路的最大允许风险阈值 (Risk Budget for Links)
    """
    h = _placement_hub(data)
    src, dst = teavar_flow_anchors(data)
    m = gp.Model("Epsilon_Constraint_CVaR")
    m.setParam('OutputFlag', 0)
    
    # 1. 决策变量 (只有物理变量和风险辅助变量，彻底抛弃 KKT 相关的 lam/alpha)
    y = m.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")
    xin = {(i, node, p): m.addVar(lb=0) for i in data.I for node in data.M for p in range(len(data.P_cand[src, node]))}
    xout = {(i, node, q): m.addVar(lb=0) for i in data.I for node in data.M for q in range(len(data.P_cand[node, dst]))}

    zeta_N, zeta_L = m.addVar(lb=-GRB.INFINITY), m.addVar(lb=-GRB.INFINITY)
    u_s, v_s = m.addVars(data.S, lb=0), m.addVars(data.S, lb=0)

    # 2. 目标函数：纯粹的成本最小化 (不再有 lambda 权重)
    cost_p = gp.quicksum(y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K) for i, node in y)
    cost_b = bandwidth_cost_expr(data, xin, xout, src, dst)
    
    m.setObjective(cost_p + cost_b, GRB.MINIMIZE)

    # 3. 基础物理约束 (部署与流量)
    m.addConstrs((y.sum(i, '*') == 1 for i in data.I))
    for i in data.I:
        for node in data.M:
            m.addConstr(gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[src, node]))) == y[i, node] * data.b_in[i])
            m.addConstr(gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, dst]))) == y[i, node] * data.b_out[i])
    for node in data.M:
        for k in data.K:
            m.addConstr(gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) <= data.C_normal[node][k])

    # 4. CVaR 风险测度的线性化探测约束
    for s in data.S:
        for node in data.M:
            for k in data.K:
                util = gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) / data.C_s[node][k][s]
                m.addConstr(u_s[s] >= util - zeta_N)

    for s in data.S:
        for e in data.E:
            flow_e = gp.LinExpr()
            for i, node, p in xin:
                if e in data.P_cand[src, node][p]: flow_e += xin[i, node, p]
            for i, node, q in xout:
                if e in data.P_cand[node, dst][q]: flow_e += xout[i, node, q]
            
            cap = data.B[e] * data.sigma[e][s]
            if cap > 0: 
                m.addConstr(v_s[s] >= flow_e / cap - zeta_L)
            else: 
                m.addConstr(flow_e == 0)

    # 5. 【核心修改】CVaR 转化为硬约束
    node_cvar = zeta_N + (1 / (1 - data.alpha_N)) * gp.quicksum(data.prob[s] * u_s[s] for s in data.S)
    link_cvar = zeta_L + (1 / (1 - data.alpha_L)) * gp.quicksum(data.prob[s] * v_s[s] for s in data.S)

    # 强制要求最终风险不能超过你设定的阈值 Gamma
    m.addConstr(node_cvar <= Gamma_N, name="Node_Risk_Budget")
    m.addConstr(link_cvar <= Gamma_L, name="Link_Risk_Budget")

    # 6. 求解与返回
    m.optimize()
    
    # 检查是否有解 (如果 Gamma 设得太严格，可能导致无解)
    if m.status == GRB.OPTIMAL:
        return m, m.ObjVal, node_cvar.getValue(), link_cvar.getValue(), y
    else:
        return m, None, None, None, None


def build_copo_mccormick_model(data, slack_max_node=None, slack_max_link=None):
    """
    模型架构：
    - 上层优化：纯成本 (min Cost)
    - 下层约束：算力 CVaR & 链路 CVaR
    - 数学处理：KKT 条件 + McCormick 包络松弛 (解决互补松弛的变量相乘)
    """
    h = _placement_hub(data)
    src, dst = teavar_flow_anchors(data)
    sn, sl = _mccormick_slack_upper_bounds(data)
    slack_max_N = float(slack_max_node) if slack_max_node is not None else sn
    slack_max_L = float(slack_max_link) if slack_max_link is not None else sl

    m = gp.Model("Copo_Style_McCormick")
    m.setParam('OutputFlag', 0)
    m.setParam('MIPGap', 0.05) 
    
    # 1. 基础物理变量
    y = m.addVars(data.valid_assign, vtype=GRB.BINARY, name="y")
    xin = {(i, node, p): m.addVar(lb=0) for i in data.I for node in data.M for p in range(len(data.P_cand[src, node]))}
    xout = {(i, node, q): m.addVar(lb=0) for i in data.I for node in data.M for q in range(len(data.P_cand[node, dst]))}

    # CVaR 基础变量
    zeta_N, zeta_L = m.addVar(lb=-GRB.INFINITY), m.addVar(lb=-GRB.INFINITY)
    u_s, v_s = m.addVars(data.S, lb=0), m.addVars(data.S, lb=0)

    # 2. 目标函数：【纯成本优化】
    cost_p = gp.quicksum(y[i, node] * sum(data.w[i][k] * data.p_price[node][k] for k in data.K) for i, node in y)
    cost_b = bandwidth_cost_expr(data, xin, xout, src, dst)
    
    m.setObjective(cost_p + cost_b, GRB.MINIMIZE)

    # 3. 基础物理约束
    m.addConstrs((y.sum(i, '*') == 1 for i in data.I))
    for i in data.I:
        for node in data.M:
            m.addConstr(gp.quicksum(xin[i, node, p] for p in range(len(data.P_cand[src, node]))) == y[i, node] * data.b_in[i])
            m.addConstr(gp.quicksum(xout[i, node, q] for q in range(len(data.P_cand[node, dst]))) == y[i, node] * data.b_out[i])
    for node in data.M:
        for k in data.K:
            m.addConstr(gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) <= data.C_normal[node][k])

    # ==========================================
    # 4. 下层 KKT 约束 (算力 CVaR) + McCormick 松弛
    # ==========================================
    lam = m.addVars(data.S, data.M, data.K, lb=0)
    mu = m.addVars(data.S, lb=0)
    slack_N = m.addVars(data.S, data.M, data.K, lb=0) # 物理松弛变量

    m.addConstr(gp.quicksum(lam[s, node, k] for s in data.S for node in data.M for k in data.K) == 1)
    
    for s in data.S:
        lam_max = data.prob[s] / (1 - data.alpha_N) # 对偶变量理论上界
        m.addConstr(gp.quicksum(lam[s, node, k] for node in data.M for k in data.K) + mu[s] == lam_max)
        
        for node in data.M:
            for k in data.K:
                util = gp.quicksum(y[i, node] * data.w[i][k] for i in data.I) / data.C_s[node][k][s]
                m.addConstr(u_s[s] >= util - zeta_N) 
                m.addConstr(slack_N[s, node, k] == u_s[s] - util + zeta_N)
                
                # 【替换 Indicator】：使用 McCormick 包络松弛互补条件 (lam * slack = 0)
                m.addConstr(lam[s, node, k] / lam_max + slack_N[s, node, k] / slack_max_N <= 1.0)
                
        # mu 的 McCormick 松弛
        m.addConstr(mu[s] / lam_max + u_s[s] / slack_max_N <= 1.0)

    # ==========================================
    # 5. 下层 KKT 约束 (链路 CVaR) + McCormick 松弛
    # ==========================================
    alpha = {(s, e): m.addVar(lb=0) for s in data.S for e in data.E}
    gamma = m.addVars(data.S, lb=0)
    slack_L = {(s, e): m.addVar(lb=0) for s in data.S for e in data.E}

    m.addConstr(gp.quicksum(alpha[s, e] for s in data.S for e in data.E) == 1)
    
    for s in data.S:
        alpha_max = data.prob[s] / (1 - data.alpha_L)
        m.addConstr(gp.quicksum(alpha[s, e] for e in data.E) + gamma[s] == alpha_max)
        
        for e in data.E:
            flow_e = gp.LinExpr()
            for i, node, p in xin:
                if e in data.P_cand[src, node][p]: flow_e += xin[i, node, p]
            for i, node, q in xout:
                if e in data.P_cand[node, dst][q]: flow_e += xout[i, node, q]
                
            cap = data.B[e] * data.sigma[e][s]
            if cap > 0:
                m.addConstr(v_s[s] >= flow_e / cap - zeta_L)
                m.addConstr(slack_L[s, e] == v_s[s] - (flow_e / cap) + zeta_L)
            else:
                m.addConstr(flow_e == 0)
                m.addConstr(v_s[s] >= -zeta_L) 
                m.addConstr(slack_L[s, e] == v_s[s] + zeta_L)
                
            # 【替换 Indicator】：McCormick 包络松弛
            m.addConstr(alpha[s, e] / alpha_max + slack_L[s, e] / slack_max_L <= 1.0)
            
        m.addConstr(gamma[s] / alpha_max + v_s[s] / slack_max_L <= 1.0)

    m.optimize()

    if m.status != GRB.OPTIMAL:
        return m, None, None, None, y

    # 求解结束后，手动计算一波真实的 CVaR 表现（虽然模型目标函数根本没管它）
    node_cvar_val = zeta_N.X + (1 / (1 - data.alpha_N)) * sum(data.prob[s] * u_s[s].X for s in data.S)
    link_cvar_val = zeta_L.X + (1 / (1 - data.alpha_L)) * sum(data.prob[s] * v_s[s].X for s in data.S)

    return m, (cost_p.getValue() + cost_b.getValue()), node_cvar_val, link_cvar_val, y


def _gamma_lists_from_baseline(data, lambda_baseline=20.0):
    """用单层加权一次最优解的 CVaR 量级生成 Model C 的 Γ 扫描列表，适配 B4 尺度。
    返回 (gamma_n 列表, gamma_l 列表, nn 基线, ll 基线)。"""
    m0, _c0, nn, ll, *_ = build_single_layer_model(data, lambda_val=lambda_baseline)
    if m0.status != GRB.OPTIMAL or nn is None or ll is None:
        return [50.0, 20.0, 10.0, 5.0, 2.0], [50.0, 20.0, 10.0, 5.0, 2.0], None, None
    eps = 1e-9
    hi_n = max(nn * 2.0, nn + 0.5, 0.5)
    hi_l = max(ll * 3.0, ll + 0.02, 0.02, eps)
    gamma_n = sorted(
        {
            hi_n,
            max(nn * 1.25, eps),
            max(nn, eps),
            max(nn * 0.85, eps),
            max(nn * 0.65, eps),
            max(nn * 0.45, eps),
        },
        reverse=True,
    )
    gamma_l = sorted(
        {
            hi_l,
            max(ll * 1.5, eps),
            max(ll * 1.1, eps),
            max(ll, eps),
            max(ll * 0.85, eps),
            max(ll * 0.65, eps),
        },
        reverse=True,
    )
    return gamma_n, gamma_l, nn, ll


def _parse_int_flag(argv, flag, default):
    """从 argv 解析 ``--flag N``。"""
    try:
        i = argv.index(flag)
        return int(argv[i + 1])
    except (ValueError, IndexError):
        return default


def _parse_float_flag(argv, flag, default):
    try:
        i = argv.index(flag)
        return float(argv[i + 1])
    except (ValueError, IndexError):
        return default


def _parse_lambdas(argv, default):
    if "--lambdas" not in argv:
        return list(default)
    i = argv.index("--lambdas")
    return [float(x.strip()) for x in argv[i + 1].split(",") if x.strip()]


def _placement_dist_str(data, y_vars):
    dist = {n: int(sum(y_vars[i, n].X for i in data.I if y_vars[i, n].X > 0.5)) for n in data.M}
    return ", ".join(f"{k}:{v}" for k, v in dist.items() if v > 0)


if __name__ == "__main__":
    import os
    import sys

    from b4_joint_data import load_b4_joint_data

    argv = sys.argv[1:]
    base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    use_toy = "--toy" in argv

    # ── 递进管线模式：Model A → C (ε-约束) → B (KKT验证) → D (McCormick近似) ──
    if "--progressive" in argv:
        from progressive_pipeline import run_physical_pipeline

        lam = _parse_float_flag(argv, "--lambda", 5.0)
        if use_toy:
            data = UltraComplexData()
            print("数据: 玩具 UltraComplexData (--toy)")
        else:
            data = load_b4_joint_data(base_path=base_path, topology_name="B4", k_paths=6)
            print(f"数据: B4 | hub={getattr(data, 'hub', 0)} | |I|={len(data.I)}")
        print()
        print("递进关系: A(加权→标定Γ) → C(ε-约束→成本最优) → B(KKT→验证) → D(McCormick→近似加速)")
        print()
        report = run_physical_pipeline(data, lambda_val=lam)
        report.print()
        sys.exit(0)

    k_paths = _parse_int_flag(argv, "--k-paths", 6)
    hub = _parse_int_flag(argv, "--hub", 0)
    num_tasks = _parse_int_flag(argv, "--num-tasks", 10)
    demand_row = _parse_int_flag(argv, "--demand-row", 0)
    demand_scale = _parse_float_flag(argv, "--demand-scale", 1.0)
    demand_downscale = _parse_float_flag(argv, "--demand-downscale", 2.0)
    topology = "B4"
    if "--topology" in argv:
        try:
            topology = argv[argv.index("--topology") + 1]
        except IndexError:
            pass
    stress_s1 = "--stress-zero-s1" in argv
    virtual_src = "--virtual-source" in argv
    virtual_sig = _parse_float_flag(argv, "--virtual-sigma", 0.99)
    virtual_sink_sig = _parse_float_flag(argv, "--virtual-sink-sigma", 0.99) if "--virtual-sink-sigma" in argv else None
    umcf_teavar = "--umcf-teavar" in argv
    umcf_sig = _parse_float_flag(argv, "--umcf-sigma", 0.99)
    umcf_sink_sig = _parse_float_flag(argv, "--umcf-sink-sigma", 0.99) if "--umcf-sink-sigma" in argv else None

    # 玩具模型求解快，可扫更长 λ 列表；B4 默认略短，可用 --lambdas 自定义
    default_lambdas = (0.5, 5.0, 50.0, 500.0, 5000.0, 50000.0) if use_toy else (0.5, 5.0, 50.0, 500.0, 5000.0)
    lambdas = _parse_lambdas(argv, default_lambdas)

    if use_toy:
        data = UltraComplexData()
        if umcf_teavar:
            from b4_joint_data import attach_umcf_to_data_object

            attach_umcf_to_data_object(data, umcf_sig, umcf_sink_sig)
        if virtual_src and not umcf_teavar:
            data.sigma_vs = {m: {s: virtual_sig for s in data.S} for m in data.M}
            st = virtual_sink_sig if virtual_sink_sig is not None else virtual_sig
            data.sigma_vt = {m: {s: st for s in data.S} for m in data.M}
        print(
            "数据: 玩具 UltraComplexData（`--toy`）"
            + (f" | UMCF V_s={data.umcf_vs}, V_t={data.umcf_vt}, σ={umcf_sig}" if umcf_teavar else "")
            + "\n"
        )
        if stress_s1:
            print(
                "提示：场景1 已切断 hub 出边，部分 λ 下 Model A/B/C/D 可能无可行解。"
                + (" UMCF 开启时 ingress 经 (V_s,m)，仍可能可行。\n" if umcf_teavar else "\n")
            )
    else:
        data = load_b4_joint_data(
            base_path=base_path,
            topology_name=topology,
            hub_index=hub,
            num_tasks=num_tasks,
            demand_row=demand_row,
            demand_downscale=demand_downscale,
            demand_scale=demand_scale,
            k_paths=k_paths,
            stress_zero_s1=stress_s1,
            virtual_source=virtual_src and not umcf_teavar,
            virtual_source_sigma=virtual_sig,
            virtual_sink_sigma=virtual_sink_sig,
            umcf_virtual_nodes=umcf_teavar,
            umcf_access_sigma=umcf_sig,
            umcf_sink_access_sigma=umcf_sink_sig,
        )
        hub_v = getattr(data, "hub", hub)
        print(
            f"数据: B4 联合 load_b4_joint_data | topology={topology} | hub={hub_v} | |I|={len(data.I)} | "
            f"k_paths={k_paths} | demand_scale={demand_scale} | demand_downscale={demand_downscale} | "
            f"demand_row={demand_row} | stress_s1_hub_out={stress_s1} | umcf_teavar_sla={umcf_teavar}"
            + (f" | V_s={getattr(data, 'umcf_vs', '?')}, V_t={getattr(data, 'umcf_vt', '?')} | σ_vs_edge={umcf_sig}" if umcf_teavar else "")
            + (
                f" | virtual_source={virtual_src}"
                + (
                    f" | σ_vs={virtual_sig}"
                    + (f" | σ_vt={virtual_sink_sig}" if virtual_sink_sig is not None else "")
                    if virtual_src
                    else ""
                )
                if not umcf_teavar
                else ""
            )
            + "\n"
        )
        print(
            "可选参数: --toy | --k-paths N | --hub N | --num-tasks N | --demand-row N | "
            "--demand-scale x | --demand-downscale x | --topology NAME | --stress-zero-s1 | "
            "--virtual-source | --virtual-sigma x | --virtual-sink-sigma x | "
            "--umcf-teavar | --umcf-sigma x | --umcf-sink-sigma x | "
            '--lambdas "0.5,5,50" | --teavar-four | --omega-teavar x'
            "\n"
        )
        if stress_s1:
            print(
                "提示：场景1 已切断 hub 出边，远端任务 ingress 可能无法满足，"
                "部分 λ 下 Model A/B/C/D 可能无可行解（将显示 status，不再抛错）。"
                + (" UMCF 开启时 ingress 经 (V_s,m)，仍可能可行。\n" if umcf_teavar else "\n")
            )

    print("=" * 90)
    print(f"{'实验一：单层加权 (Model A)':^90}")
    print("=" * 90)
    print(f"{'Lambda':>10} | {'总成本':>10} | {'算力CVaR':>10} | {'链路CVaR':>10} | {'部署':<38}")
    print("-" * 90)
    for l_val in lambdas:
        m_single, cost, n_cvar, l_cvar, y_vars, _xin, _xout = build_single_layer_model(data, lambda_val=l_val)
        if m_single.status == GRB.OPTIMAL and cost is not None:
            print(
                f"{l_val:10.4g} | {cost:10.2f} | {n_cvar:10.4f} | {l_cvar:10.4f} | "
                f"{_placement_dist_str(data, y_vars):<38}"
            )
        else:
            print(f"{l_val:10.4g} | {'非最优 / 无可行解':<48} | status={m_single.status}")

    print("\n" + "=" * 90)
    print(f"{'实验二：双层 KKT 加权 (Model B)':^90}")
    print("=" * 90)
    print(f"{'Lambda':>10} | {'总成本':>10} | {'算力CVaR':>10} | {'链路CVaR':>10} | {'部署':<38}")
    print("-" * 90)
    for l_val in lambdas:
        m_kkt, cost_kkt, n_cvar_kkt, l_cvar_kkt, y_kkt = build_kkt_model(data, lambda_weight=l_val)
        if m_kkt.status == GRB.OPTIMAL and cost_kkt is not None:
            print(
                f"{l_val:10.4g} | {cost_kkt:10.2f} | {n_cvar_kkt:10.4f} | {l_cvar_kkt:10.4f} | "
                f"{_placement_dist_str(data, y_kkt):<38}"
            )
        else:
            print(f"{l_val:10.4g} | {'非最优 / 无可行解':<48} | status={m_kkt.status}")

    print("\n" + "=" * 90)
    print(f"{'实验三：ε-约束风险预算 (Model C)':^90}")
    print("=" * 90)
    print("min 成本 s.t. 算力CVaR≤Γ_N 且 链路CVaR≤Γ_L；Γ 由当前数据集上单次单层(λ=20)参考解拉伸得到。")
    gn_seq, gl_seq, nn_b, ll_b = _gamma_lists_from_baseline(data, lambda_baseline=20.0)
    gamma_l_fixed = max(ll_b * 1.08, 1e-6) if ll_b is not None else max(gl_seq[0] * 0.5, 1e-6)

    print(f"{'Gamma_N':>12} | {'Gamma_L(固定)':>14} | {'总成本':>10} | {'算力CVaR':>10} | {'链路CVaR':>10} | {'部署':<28}")
    print("-" * 90)
    for g_n in gn_seq:
        m_eps, cost_eps, n_cvar_eps, l_cvar_eps, y_eps = build_epsilon_constraint_model(
            data, Gamma_N=g_n, Gamma_L=gamma_l_fixed
        )
        if m_eps.status == GRB.OPTIMAL and y_eps is not None:
            dist = {n: int(sum(y_eps[i, n].X for i in data.I if y_eps[i, n].X > 0.5)) for n in data.M}
            dist_str = ", ".join(f"{k}:{v}" for k, v in dist.items() if v > 0)
            print(
                f"{g_n:12.4f} | {gamma_l_fixed:14.4f} | {cost_eps:10.2f} | "
                f"{n_cvar_eps:10.4f} | {l_cvar_eps:10.4f} | {dist_str:<28}"
            )
        else:
            print(f"{g_n:12.4f} | {gamma_l_fixed:14.4f} | {'无解 / 非最优':<58}")

    print("\n" + "=" * 90)
    print(f"{'实验四：Γ_N × Γ_L 网格 (Model C 细化，步数已压缩)':^90}")
    print("=" * 90)
    gn_grid = gn_seq[::2] if len(gn_seq) >= 3 else gn_seq
    gl_grid = gl_seq[::2] if len(gl_seq) >= 3 else gl_seq
    print(f"{'G_N':>10} | {'G_L':>10} | {'总成本':>10} | {'算力CVaR':>10} | {'链路CVaR':>10} | {'部署':<22}")
    print("-" * 90)
    for g_n in gn_grid:
        for g_l in gl_grid:
            m_eps, cost_eps, n_cvar_eps, l_cvar_eps, y_eps = build_epsilon_constraint_model(
                data, Gamma_N=g_n, Gamma_L=g_l
            )
            if m_eps.status == GRB.OPTIMAL and y_eps is not None:
                dist = {n: int(sum(y_eps[i, n].X for i in data.I if y_eps[i, n].X > 0.5)) for n in data.M}
                dist_str = ", ".join(f"{k}:{v}" for k, v in dist.items() if v > 0)
                print(
                    f"{g_n:10.4f} | {g_l:10.4f} | {cost_eps:10.2f} | "
                    f"{n_cvar_eps:10.4f} | {l_cvar_eps:10.4f} | {dist_str:<22}"
                )
            else:
                print(f"{g_n:10.4f} | {g_l:10.4f} | {'无解':<52}")

    print("\n" + "=" * 90)
    print(f"{'实验五：Copo 式 McCormick 松弛 (Model D)':^90}")
    print("=" * 90)
    sn, sl = _mccormick_slack_upper_bounds(data)
    print(f"McCormick slack 上界(数据驱动): node={sn:.2f}, link={sl:.2f}")
    m_copo, cost_copo, n_cvar_copo, l_cvar_copo, y_copo = build_copo_mccormick_model(data)
    if m_copo.status == GRB.OPTIMAL and cost_copo is not None and y_copo is not None:
        dist = {n: int(sum(y_copo[i, n].X for i in data.I if y_copo[i, n].X > 0.5)) for n in data.M}
        dist_str = ", ".join(f"{k}:{v}" for k, v in dist.items() if v > 0)
        print(f"-> 总成本   : {cost_copo:.2f}")
        print(f"-> 部署分布 : {dist_str}")
        print(f"-> 算力CVaR : {n_cvar_copo:.4f}")
        print(f"-> 链路CVaR : {l_cvar_copo:.4f}")
        print(
            "\n说明：Model D 只对互补条件做 McCormick 松弛，不保证与单层 Model A 的 CVaR 同界；"
            "上面 CVaR 是在该松弛可行点上事后计算，数值偏大属松弛松而非数据错误。"
            "可比尾部风险请以 Model A 或 Model C 最优解为准。"
        )
    else:
        print(f"求解状态: {m_copo.status}（不可行或达到时间/间隙限制时可调 MIPGap 或 slack 上界）")

    if "--teavar-four" in argv:
        from teavar_framework_models import (
            build_teavar_model_a,
            build_teavar_model_b,
            build_teavar_model_c,
            build_teavar_model_d,
        )

        omega_t = _parse_float_flag(argv, "--omega-teavar", 1.0)
        lam_sla_t = _parse_float_flag(argv, "--teavar-lambda-sla", 0.5)
        lam_sf_t = _parse_float_flag(argv, "--teavar-lambda-sf", 0.5)

        print("\n" + "=" * 90)
        print(f"{'实验六～九：TEAVAR 视角（SLA + 算力未满足）与 duibi A–D 对齐':^90}")
        print("=" * 90)
        print(f"omega_teavar={omega_t} | lambda_sla={lam_sla_t} | lambda_sf={lam_sf_t}（详见 teavar_framework_models.py）")

        print("\n[TEAVAR-A] 单层加权")
        mta, cta, lta, sta, yta, *_ = build_teavar_model_a(
            data, lam_sla_t, lam_sf_t, omega_deliver=omega_t
        )
        if cta is not None:
            print(f"  cost={cta:.2f}  CVaR_SLA={lta:.4f}  CVaR_sf={sta:.4f}  部署={_placement_dist_str(data, yta)}")
        else:
            print(f"  status={mta.status}")

        print("\n[TEAVAR-B] KKT（SLA Indicator + 可选 sf KKT）")
        mtb, ctb, ltb, stb, ytb, *_ = build_teavar_model_b(
            data, lam_sla_t, lam_sf_t, omega_deliver=omega_t, kkt_sf=True
        )
        if ctb is not None:
            print(f"  cost={ctb:.2f}  CVaR_SLA={ltb:.4f}  CVaR_sf={stb:.4f}  部署={_placement_dist_str(data, ytb)}")
        else:
            print(f"  status={mtb.status}")

        g_sla = (lta or 1.0) * 1.5 if lta is not None else 1.0
        g_sf = (sta or 0.1) * 2.0 + 0.01 if sta is not None else 1.0
        print(f"\n[TEAVAR-C] ε-约束（示例 Γ_sla={g_sla:.4f}, Γ_sf={g_sf:.4f}，由 A 解拉伸）")
        mtc, ctc, ltc, stc, ytc, *_ = build_teavar_model_c(
            data, g_sla, g_sf, omega_deliver=omega_t, include_sf_budget=True
        )
        if ctc is not None:
            print(f"  cost={ctc:.2f}  CVaR_SLA={ltc:.4f}  CVaR_sf={stc:.4f}  部署={_placement_dist_str(data, ytc)}")
        else:
            print(f"  status={mtc.status}")

        print("\n[TEAVAR-D] McCormick 松弛（目标仅 c-ωE；CVaR 为事后读数）")
        mtd, ctd, ltd, std, ytd, *_ = build_teavar_model_d(data, omega_deliver=omega_t, include_sf=True)
        if ctd is not None:
            print(f"  cost={ctd:.2f}  事后CVaR_SLA={ltd:.4f}  事后CVaR_sf={std:.4f}  部署={_placement_dist_str(data, ytd)}")
        else:
            print(f"  status={mtd.status}")