# TEAVAR-E2E Modeling Formulation

> 主文档。详细推导见 `docs/m0_m1_m2_建模说明.md`。

---

## Sets and Indices

| 符号 | 含义 |
|:--|:--|
| i ∈ J | 任务 |
| m ∈ M | 计算节点 |
| p ∈ P_in(i,m) | ingress 候选路径 |
| q ∈ P_out(m,i) | egress 候选路径 |
| s ∈ S | 故障场景 |
| e ∈ E | 有向链路 |
| k ∈ K | 资源维度 (CPU/GPU/HBM) |

---

## Decision Variables

| 变量 | 类型 | 含义 |
|:--|:--|:--|
| y_{i,m} | {0,1} | 任务 i 是否放在节点 m |
| r_{i,m,s} | [0, y_{i,m}] | 场景 s 下 (i,m) 服务比例 |
| z_{i,s} | [0,1] | 场景 s 下任务 i 端到端服务比例 |
| x_in_{i,m,p,s} | ≥ 0 | 场景 s ingress 路由流量 |
| x_out_{i,m,q,s} | ≥ 0 | 场景 s egress 路由流量 |
| η | [0,1] | CVaR VaR 阈值 |
| u_s | [0,1] | 场景 s 尾部超额 |

---

## M0 — 确定性诊断

**约束**：名义链路/节点容量硬约束 + U_link, U_node ∈ [0,1]

**目标**：min λ·U_link + (1-λ)·U_node

不含场景、CVaR、成本。

---

## M1 — 场景 Adaptive Recourse

**新增**：固定 placement 下的场景路由 r/z/x_s

**场景硬约束**：

```
LinkLoad_{e,s} ≤ B_e · σ_{e,s}
Σ_i r_{i,m,s} · w_i^{(k)} ≤ C_{m,s}^{(k)}
```

链路/算力故障通过 σ 和 C_s 约束 r 和 z。

---

## M2 — E2E CVaR

**端到端损失**（默认加权平均）：

$$
L_s^{avg} = \sum_i \omega_i (1 - z_{i,s}), \quad \omega_i = \theta_i / \sum_j \theta_j
$$

**公平变体**（max per-flow）：

$$
L_s^{fair} = \max_i (1 - z_{i,s})
$$

**CVaR 线性化（Rockafellar–Uryasev）**：

$$
\mathrm{CVaR}_\beta(L) = \eta + \frac{1}{1-\beta}\sum_s \pi_s u_s
$$

$$
u_s \ge L_s - \eta, \quad u_s \ge 0, \quad 0 \le \eta \le 1
$$

---

## M2-C-Cost — 成本最小化 + CVaR 约束

**目标**：

$$
\min \; c_p(y) + \sum_{s} \pi_s \; c_b(x_s)
$$

**成本定义**：

$$
c_p = \sum_{i,m} y_{i,m} \sum_k w_i^{(k)} \rho_{m,k}
$$

$$
c_b(x_s) = \sum_e \rho^{link}_e \cdot \mathrm{LinkLoad}_{e,s}
$$

**约束**：

```
CVaR_β(L^{E2E}) ≤ γ
z_{i,s0} = 1          (normal scenario full service)
E[z_i] ≥ ρ_i           (expected service floor)
M1 scenario constraints (link + compute capacity per scenario)
placement constraints (∑ y = 1)
```

---

## 与 Legacy 模型的区别

| | Legacy (duibi/P0) | 当前主线 |
|:--|:--|:--|
| 风险度量 | Link CVaR + Node CVaR 并列 | 单一 L^{E2E} CVaR |
| 成本 | 部分有 (Model A/C) | 完整 c_p + E[c_b] |
| 玩具路径 | 旧 toy 为单路径 | Toy-2Task / ToyTE 多路径 |
| 核心结构 | Model A/C/D, L2, duibi | M0 → M1 → M2 / M2-C-Cost |
