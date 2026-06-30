# Model A / Model C 单层联合放置–路由–风险建模说明

---

## 1. 问题背景

在离散故障场景集合上，同时决定：

1. **放置**：每个计算任务放到哪个算力节点；
2. **路由**：每个任务从源侧到放置节点、再从放置节点到宿侧的候选路径上分配多少计划流量；
3. **场景送达**：在每个故障场景下，路径通断决定实际能送达多少流量。

在此基础上，用 **货币化成本**（资源占用费 + 带宽费）与 **两类尾部风险**（SLA 送达不足、算力容量不足）做权衡：

| 模型 | 经济含义 |
|:--|:--|
| **Model A** | 成本与风险加权求和：通过权重 $\lambda$ 调节「省钱」与「控险」的相对重要性 |
| **Model C** | 成本最小化 + 硬风险预算：在 SLA / 算力 CVaR 不超过给定上限的前提下，找最低成本方案 |

二者共用同一套变量、成本口径与风险线性化；**唯一本质区别**是风险进入问题的方式（进目标 vs 进约束）。

---

## 2. 符号总表


### 2.0 符号



| 符号 | 代码 | 说明 |
|:--|:--|:--|
| $\mathcal{I}$ | `data.I` | 任务集合 |
| $s_i$ | $s_i$ 或 `task_src[i]` | 任务源节点 |
| $d_i$ | $d_i$ 或 `task_dst[i]` | 任务宿节点 |
| $\mathcal{P}_{i,m}^{in}$ | `data.P_cand[s_i, m]` | 源→执行节点候选路径 |
| $\mathcal{P}_{i,m}^{out}$ | `data.P_cand[m, d_i]` | 执行节点→宿候选路径 |
| $x_{i,m,p}^{in}$ | `xin[i,m,p]` | 入站计划流量 |
| $x_{i,m,q}^{out}$ | `xout[i,m,q]` | 出站计划流量 |
| $C_m\in\mathbb{R}^d$ | `C_normal[m][k]`，$k\in\mathcal{K}$；$d$ 为资源维数 | 名义算力容量向量 |

---

### 2.1 拓扑相关符号（Topology-related）

| 符号 | 域 / 类型 | 含义 | 
|:--|:--|:--|
| $\mathcal{G}=(\mathcal{V},\mathcal{E})$ | — | 网络拓扑：节点集 + 有向链路集 | 
| $\mathcal{M}\subseteq\mathcal{V}$ | 节点子集 | **可部署算力**的节点集合 | 
| $\mathcal{R}=\mathcal{V}\setminus\mathcal{M}$ | 节点子集 | **仅转发、不部署任务**的节点（源/宿） | 
| $\mathcal{K}$ | 有限集 | 资源维度（CPU、GPU、HBM 等） |
| $m\in\mathcal{M}$ | 索引 | 某个算力节点 | 
| $e=(u,v)\in\mathcal{E}$ | 有向边 | 一条物理链路 | 
| $B_e\in\mathbb{R}_{+}$ | 标量 | 链路 $e$ 的**名义带宽容量** | 
| $C_m\in\mathbb{R}^d$ | 向量 | 节点 $m$ 各资源维正常容量；$d=\lvert\mathcal{K}\rvert$ | 
| $C^{\mathrm{N}}_{m,k,s}$ | 标量 | 场景 $s$ 下节点 $m$ 资源 $k$ 的**可用容量**（故障后） |
| $\sigma_{e,s}\in[0,1]$ | 标量 | 场景 $s$ 下链路 $e$ 的**可用率**；$0$ 表示断链 | 
| $h\in\mathcal{V}$ | 索引 | 逻辑 hub（hub 径向路由锚点） |
| $\pi^{\mathrm{price}}_e$ | 标量 | 链路 $e$ 的**单位带宽单价**（定价，非故障率） | 

**组件级故障**：多条物理 ingress 边（如各任务源→A）在**故障模型**中共属一个组件（如 `A_in`），一次故障同时令这些边 $\sigma_{e,s}=0$；与 $\pi^{\mathrm{price}}_e$ 分开定义。

---

### 2.2 任务相关符号（Task-related）

| 符号 | 域 / 类型 | 含义 |
|:--|:--|:--|
| $i\in\mathcal{I}$ | 索引 | 任务编号 | 
| $s_i\in\mathcal{V}$ | 节点 | 任务 $i$ 的**源节点**（输入数据从此进入网络） | 
| $d_i\in\mathcal{V}$ | 节点 | 任务 $i$ 的**宿节点**（输出数据送达此处） | 
| $w_i\in\mathbb{R}^d_+$ | 向量 | 任务 $i$ 的算力需求（各资源维）；$d=\lvert\mathcal{K}\rvert$ | 
| $\mathcal{M}_i\subseteq\mathcal{M}$ | 节点子集 | 任务 $i$ 的**候选执行节点** | 
| $m\in\mathcal{M}_i$ | 索引 | 为任务 $i$ 选定的执行节点 | 
| $b_i^{in}\in\mathbb{R}_{+}$ | 标量 | 任务 $i$ 从 $s_i$ 到执行节点 $m$ 的**入站数据量/带宽需求** | 
| $b_i^{out}\in\mathbb{R}_{+}$ | 标量 | 任务 $i$ 从执行节点 $m$ 到 $d_i$ 的**出站数据量/带宽需求** | 
| $p\in\mathcal{P}_{i,m}^{in}$ | 路径索引 | 从 $s_i$ 到 $m$ 的第 $p$ 条候选路径 | 
| $q\in\mathcal{P}_{i,m}^{out}$ | 路径索引 | 从 $m$ 到 $d_i$ 的第 $q$ 条候选路径 | 
| $\delta_{e,p}\in\{0,1\}$ | 指示量 | 链路 $e$ 是否在入站路径 $p$ 上 |
| $\delta_{e,q}\in\{0,1\}$ | 指示量 | 链路 $e$ 是否在出站路径 $q$ 上 | 
| $\tau_p$ | 标量 | 入站路径 $p$ 的带宽单价 | 
| $\tau_q$ | 标量 | 出站路径 $q$ 的带宽单价 | 

**hub 径向特例**：所有任务 $s_i=d_i=h$，候选路径为 $h\to m$ 与 $m\to h$。  
**多源多宿特例**（ComponentRisk）：每任务有独立 $(s_i,d_i)$，路径集合按任务区分。

---

### 2.3 决策变量（Decision Variables）

| 符号 | 域 / 类型 | 含义 | 
|:--|:--|:--|
| $y_{i,m}\in\{0,1\}$ | 二元 | 任务 $i$ 是否部署在算力节点 $m$ | 
| $x_{i,m,p}^{in}\ge 0$ | 连续 | 任务 $i$ 在节点 $m$、路径 $p$ 上的**入站计划流量** | 
| $x_{i,m,q}^{out}\ge 0$ | 连续 | 任务 $i$ 在节点 $m$、路径 $q$ 上的**出站计划流量** | 
| $d_{i,m,p,s}^{in}\ge 0$ | 连续 | 场景 $s$ 下，同上路径的**实际入站送达量** | 
| $d_{i,m,q,s}^{out}\ge 0$ | 连续 | 场景 $s$ 下，同上路径的**实际出站送达量** |

**放置约束（由变量含义隐含）**：$\sum_{m\in\mathcal{M}_i} y_{i,m}=1$。

---

### 2.4 场景与故障参数

| 符号 | 域 / 类型 | 含义 | 
|:--|:--|:--|
| $\mathcal{S}$ | 有限集 | 离散故障/运营场景集合 | 
| $s\in\mathcal{S}$ | 索引 | 场景编号 | 
| $\pi_s\in[0,1]$ | 概率 | 场景 $s$ 发生概率，$\sum_s\pi_s=1$ | 
| $q_c\in[0,1]$ | 概率 | 独立故障组件 $c$ 的故障率 | 
| $\mathcal{C}$ | 有限集 | 故障组件集合（链路 trunk + 算力组件） | 
| $\sigma^{\mathrm{vs}}_{m,s}$ | 标量 | 虚拟源侧接入可用率（可选） | 
| $\sigma^{\mathrm{vt}}_{m,s}$ | 标量 | 虚拟宿侧接出可用率（可选） | 

场景概率（组件独立）：$\pi_s=\prod_{c\in\mathcal{F}_s} q_c \prod_{c\notin\mathcal{F}_s}(1-q_c)$，$\mathcal{F}_s$ 为场景 $s$ 中故障组件集。

---

### 2.5 成本参数（本文扩展）

| 符号 | 域 / 类型 | 含义 |
|:--|:--|:--|
| $p_{m,k}\in\mathbb{R}_{+}$ | 标量 | 节点 $m$ 上资源 $k$ 的**单位占用价格** | 
| $c_p$ | 标量 | **资源部署成本** | 
| $c_b$ | 标量 | **带宽成本** | 
| $\omega\in\mathbb{R}_{+}$ | 标量 | 期望送达奖励权重 | 

**带宽成本 $c_b$ 两种模式**：

| 模式 | 公式 | 含义 |
|:--|:--|:--|
| **流量模式**（默认） | $c_b=\sum_{i,m,p} x_{i,m,p}^{in}\tau_p + \sum_{i,m,q} x_{i,m,q}^{out}\tau_q$ | 计划流量 × 路径价 |
| **放置模式** （弃用）| $c_b=\sum_{i,m} b_i^{in}(\tau_p^{in}+\tau_q^{out})y_{i,m}$ | 仅与放置有关 |

**总成本（进入目标）**：

$$
c_{\mathrm{tot}} = c_p + c_b - \omega\,\mathbb{E}[\mathrm{Del}]
$$

---

### 2.6 目标与风险相关参数（Objective-related）

**Model A/C 主线**为 **尾部 CVaR + 成本**，对应关系如下：

| 符号 | 域 / 类型 | 含义 | Model A | Model C | 
|:--|:--|:--|:--|:--|
| $\lambda_{\mathrm{sla}}\ge 0$ | 标量 | SLA（送达不足）CVaR 权重 | **目标系数** | — | 
| $\lambda_{\mathrm{sf}}\ge 0$ | 标量 | 算力容量缺口 CVaR 权重 | **目标系数** | — | 
| $\Gamma_{\mathrm{sla}}\ge 0$ | 标量 | SLA CVaR **风险预算上界** | — | **约束右端** | 
| $\Gamma_{\mathrm{sf}}\ge 0$ | 标量 | 算力 SF CVaR **风险预算上界** | — | **约束右端** | 
| $\beta\in(0,1)$ | 标量 | CVaR 置信水平 | 共用 | 共用 |
| $\beta_{\mathrm{sf}}$ | 标量 | SF 块 CVaR 置信水平 | 共用 | 共用 | 
| $\bar D_k$ | 标量 | 资源 $k$ 的 SF 归一化分母 | 共用 | 共用 |
| $\zeta$ | 自由 | SLA CVaR 的 VaR 层辅助变量 | 决策 | 决策 | 
| $u_s\ge 0$ | 连续 | 场景 $s$ 的 SLA 尾部超额 | 决策 | 决策 | 
| $\zeta^{\mathrm{sf}}\ge 0$ | 连续 | SF CVaR 的 VaR 层辅助变量 | 决策 | 决策 | 
| $\phi_s\ge 0$ | 连续 | 场景 $s$ 的 SF 尾部超额 | 决策 | 决策 | 
| $D_{m,k}\ge 0$ | 连续 | 节点 $m$ 资源 $k$ 聚合需求 | 决策 | 决策 | 

**Model A 目标**：

$$
\min\; c_{\mathrm{tot}} + \lambda_{\mathrm{sla}}\,\mathrm{CVaR}^{\mathrm{SLA}} + \lambda_{\mathrm{sf}}\,\mathrm{CVaR}^{\mathrm{SF}}
$$

**Model C 目标**（$\varepsilon$-约束：成本主目标，风险进约束）：

$$
\min\; c_{\mathrm{tot}} \quad \text{s.t.}\quad \mathrm{CVaR}^{\mathrm{SLA}}\le\Gamma_{\mathrm{sla}},\;\; \mathrm{CVaR}^{\mathrm{SF}}\le\Gamma_{\mathrm{sf}}
$$




---

### 2.7 ComponentRisk toy 参数实例

| 类别 | 取值 |
|:--|:--|
| $|\mathcal{I}|=3$，$|\mathcal{M}|=3$，$|\mathcal{S}|=512$ | 27 种 placement |
| $w_i=(2,1,1)$，$b_i^{in}=b_i^{out}=1$ | CPU/GPU/HBM |
| $C_m=(6,3,3)$（正常） | 三任务同放单节点刚好满配 |
| 链路组件 $q$ | A/B/C 的 in/out：0.005 / 0.10 / 0.005 |
| 算力组件 $q$ | A:0.20，B:0.01，C:0.005 |
| $\beta=0.8$ | 尾部权重 $1/(1-\beta)=5$ |
| 单任务成本（A/B/C） | 0.04 / 0.05 / 0.28；纯 AAA/BBB/CCC 为 0.12/0.15/0.84 |

---

## 5. 中间量定义

### 5.1 场景下任务送达聚合

$$
R^{\mathrm{in}}_{is} = \sum_{m,p} d^{\mathrm{in}}_{i,m,p,s}, \qquad
R^{\mathrm{out}}_{is} = \sum_{m,q} d^{\mathrm{out}}_{i,m,q,s}
$$

**含义**：场景 $s$ 下，任务 $i$ 所有入站/出站路径上实际送达带宽之和。

### 5.2 期望送达量（目标中的奖励项）

$$
\mathbb{E}[\mathrm{Del}] = \sum_{s\in\mathcal{S}} \pi_s \left( \sum_{i,m,p} d^{\mathrm{in}}_{i,m,p,s} + \sum_{i,m,q} d^{\mathrm{out}}_{i,m,q,s} \right)
$$

**含义**：按场景概率加权的总送达带宽；目标中以 $-\omega\,\mathbb{E}[\mathrm{Del}]$ 进入，即鼓励多送达。

### 5.3 路径可达性

路径 $p\in\mathcal{P}_{u_iv}$ 在场景 $s$ **可用**，当且仅当路径上每条边 $e$ 满足 $\sigma_{e,s}>0$。

---

## 6. 风险度量（概念形式 + MILP 线性化）

### 6.1 SLA 风险：带宽送达不足

**概念**（按任务取最坏方向，再对任务取最大）：

$$
\ell^{\mathrm{in}}_{is} = \left[1 - \frac{R^{\mathrm{in}}_{is}}{b_i}\right]_+, \quad
\ell^{\mathrm{out}}_{is} = \left[1 - \frac{R^{\mathrm{out}}_{is}}{b_i}\right]_+, \quad
L^{\mathrm{SLA}}_s = \max_{i\in\mathcal{I}} \max\{\ell^{\mathrm{in}}_{is},\, \ell^{\mathrm{out}}_{is}\}
$$

**含义**：只要有一个任务在入站或出站方向出现明显缺口，该场景的 SLA 损失就升高；采用 min–max 结构，避免平均值掩盖个别任务的严重失败。

**CVaR**（Rockafellar–Uryasev）：

$$
\mathrm{CVaR}^{\mathrm{SLA}}_\beta(L^{\mathrm{SLA}}) = \zeta + \frac{1}{1-\beta}\sum_{s\in\mathcal{S}} \pi_s\, u_s
$$

**线性化约束**（对每个场景 $s$、每个任务 $i$ 各写一行，$u_s$ 在所有任务间共享，从而取 max）：

$$
u_s\, b_i \;\ge\; b_i - R^{\mathrm{in}}_{is} - b_i\,\zeta 
$$

$$
u_s\, b_i \;\ge\; b_i - R^{\mathrm{out}}_{is} - b_i\,\zeta 
$$

$$
u_s \ge 0 
$$

**文字说明**：$u_s$ 必须同时覆盖每个任务、每个方向的「超额未满足比例」；共享的 $u_s$ 等价于对 $L^{\mathrm{SLA}}_s$ 取上确界后再做 CVaR 线性化。

---

### 6.2 算力 SF 风险：容量不足（按资源维归一化）

**节点需求**：

$$
D_{m,k} = \sum_{i\in\mathcal{I}} w_{i,k}\, y_{i,m}
$$

**概念损失**：

$$
L^{\mathrm{SF}}_s = \max_{m\in\mathcal{M},\,k\in\mathcal{K}} \frac{\left(D_{m,k} - C^{\mathrm{N}}_{m,k,s}\right)_+}{\bar D_k}
$$

**含义**：在故障场景 $s$ 下，若某节点某资源出现容量缺口，按该资源维的全局需求规模 $\bar D_k$ 归一化；避免 CPU 数值较大时掩盖 GPU/HBM 缺口。

**CVaR 线性化**（对每个 $s,m,k$ 写一行，$\phi_s$ 在节点与资源间共享）：

$$
\phi_s \;\ge\; \frac{D_{m,k} - C^{\mathrm{N}}_{m,k,s}}{\bar D_k} - \zeta^{\mathrm{sf}} 
$$

$$
\mathrm{CVaR}^{\mathrm{SF}}_\beta(L^{\mathrm{SF}}) = \zeta^{\mathrm{sf}} + \frac{1}{1-\beta_{\mathrm{sf}}}\sum_{s\in\mathcal{S}} \pi_s\, \phi_s 
$$

$$
D_{m,k} = \sum_i w_{i,k}\, y_{i,m} 
$$

**文字说明**：当 $D_{m,k}\le C^{\mathrm{N}}_{m,k,s}$ 时右端 $\le -\zeta^{\mathrm{sf}}$，由 $\phi_s\ge 0$ 自动满足；当容量不足时 $\phi_s$ 被推高，进而推高 CVaR。


---

## 7. 总成本

$$
c_{\mathrm{tot}} = c_p + c_b - \omega\,\mathbb{E}[\mathrm{Del}]
$$

| 项 | 说明 |
|:--|:--|
| $c_p$ | 资源占用费：任务占用的 CPU/GPU/HBM 按节点单价计费 |
| $c_b$ | 带宽费：流量传输费用 |
| $-\omega\,\mathbb{E}[\mathrm{Del}]$ | 送达奖励：期望送达越大，目标越小 |

---

## 8. Model A：加权目标模型

### 8.1 目标函数

$$
\min \;\; c_{\mathrm{tot}}
+ \lambda_{\mathrm{sla}}\,\mathrm{CVaR}^{\mathrm{SLA}}_\beta(L^{\mathrm{SLA}})
+ \lambda_{\mathrm{sf}}\,\mathrm{CVaR}^{\mathrm{SF}}_\beta(L^{\mathrm{SF}})
$$

**文字说明**：

- $\lambda_{\mathrm{sla}}$ SLA 风险项系数
- $\lambda_{\mathrm{sf}}$  SF 风险项系数
- 经济含义：在「总成本 − 送达奖励」与两类尾部风险之间做 **软权衡**；权重越大，越愿意为降风险而接受更高成本。


---

### 8.2 约束条件（Model A 与 Model C 共用）

以下约束两组模型 **完全相同**（除 Model C 额外增加 §9.2 的风险预算行）。

---

#### 约束 A：任务唯一放置

$$
\sum_{m\in\mathcal{M}} y_{i,m} = 1 \qquad \forall i\in\mathcal{I} 
$$

**说明**：每个任务恰好放在一个算力节点上。



---

#### 约束 B1–B2：计划流量与放置耦合

$$
\sum_{p} x^{\mathrm{in}}_{i,m,p} \;= y_{i,m}\, b_i \qquad \forall i,m 
$$

$$
\sum_{q} x^{\mathrm{out}}_{i,m,q} \;= y_{i,m}\, b_i \qquad \forall i,m 
$$

**说明**：

- 去程流量守恒：只有被选中的计算节点会收到全部输入数据
- 回程流量守恒：只有被选中的计算节点会发送全部输出数据到目的节点
- 若 $y_{i,m}=0$，右侧为 0，计划流量被压到 0；

---

#### 约束 C：正常状态算力容量

$$
\sum_{i\in\mathcal{I}} w_{i,k}\, y_{i,m} \;\le\; C^{\mathrm{norm}}_{m,k} \qquad \forall m,k 
$$

**说明**：在**无故障的名义设计点**下，任一节点上各资源维的总需求不得超过该节点的名义容量；这是放置可行性约束，与场景 $s$ 下的 $C^{\mathrm{N}}_{m,k,s}$（故障后容量）区分。

---

#### 约束 C2：链路名义带宽容量（计划流量）

$$
\sum_{i,m,p} x_{i,m,p}^{in}\,\delta_{e,p} + \sum_{i,m,q} x_{i,m,q}^{out}\,\delta_{e,q} \;\le\; B_e \qquad \forall e\in\mathcal{E} 
$$

**说明**：

- $\delta_{e,p}=1$ 当且仅当链路 $e$ 在路径 $p$ 上；代码用 `e in path` 判断；
- **计划阶段**每条物理边上的总流量不超过名义带宽 $B_e$（**不区分场景**）；
- 大规模实例中 $B_e$ 可能紧，此约束保证路由方案物理可行；
- UMCF 虚拟辅助边跳过；`data.enforce_link_capacity=False` 时可关闭（仅 toy 调试）；
- **与 SLA CVaR 分工**：本条限制「计划流不超容量」；故障后送达不足仍由场景 $d$ + SLA 块刻画。

---

#### 约束 D1–D2：场景送达与计划流量 / 路径通断

对每个场景 $s$、任务 $i$、节点 $m$、路径索引 $p,q$：

$$
d^{\mathrm{in}}_{i,m,p,s} = x^{\mathrm{in}}_{i,m,p} \quad \text{若路径 } (u_i,m,p) \text{ 在 } s \text{ 可用} 
$$

$$
d^{\mathrm{in}}_{i,m,p,s} = 0 \quad \text{若该路径在 } s \text{ 不可用} 
$$

$$
d^{\mathrm{out}}_{i,m,q,s} = x^{\mathrm{out}}_{i,m,q} \quad \text{若路径 } (m,v_i,q) \text{ 在 } s \text{ 可用} 
$$

$$
d^{\mathrm{out}}_{i,m,q,s} = 0 \quad \text{若该路径在 } s \text{ 不可用} 
$$

**说明**：

- 路径可用性由边上 $\sigma_{e,s}$ 决定（任一边断则整条路径断）；
- 断路径时送达为 0，但计划流量 $x$ 可仍为正（「计划了但送不出去」→ SLA 风险上升）；
- **不在**此约束中重复写 $y$：放置语义已由 B1–B2 保证。

---

#### 约束 E1–E2（拓展）：虚拟源/汇接入瓶颈

当 `data.sigma_vs` 非空且未启用显式 UMCF 图扩展时：

$$
R^{\mathrm{in}}_{is} \;\le\; \sum_{m} b_i\, y_{i,m}\, \sigma^{\mathrm{vs}}_{m,s} 
$$

$$
R^{\mathrm{out}}_{is} \;\le\; \sum_{m} b_i\, y_{i,m}\, \sigma^{\mathrm{vt}}_{m,s} 
$$

**说明**：将「经虚拟源/汇进入物理网」建模为与物理送达 **串联** 的可靠性上界；即使物理路径全通，接入侧仍可能因 $\sigma^{\mathrm{vs}}<1$ 限制送达。ComponentRisk 实例通常 **不启用** 此项（`sigma_vs=None`）。

---

#### 约束 F1–F3：SLA CVaR 线性化

见 §6.1 之 (SLA-RU-in)、(SLA-RU-out)、(SLA-RU-nonneg)。

---

#### 约束 G1–G3：SF CVaR 线性化

见 §6.2 之 (SF-demand)、(SF-RU)、(SF-CVaR)。


---

## 9. Model C：风险预算（$\varepsilon$-约束）模型

### 9.1 目标函数

$$
\min \;\; c_{\mathrm{tot}}
$$

**文字说明**：在风险可控的前提下 **纯最小化成本**（仍保留送达奖励项在 $c_{\mathrm{tot}}$ 内）。不再问「风险权重取多少」，而问「给定风险上限，最便宜方案是什么」。

---

### 9.2 额外硬约束（相对 Model A）

$$
\mathrm{CVaR}^{\mathrm{SLA}}_\beta(L^{\mathrm{SLA}}) \;\le\; \Gamma_{\mathrm{sla}} 
$$

$$
\mathrm{CVaR}^{\mathrm{SF}}_\beta(L^{\mathrm{SF}}) \;\le\; \Gamma_{\mathrm{sf}} 
$$

**说明**：

- (Gamma-SLA) **恒启用**；
- (Gamma-SF) 仅当 `include_sf_budget=True` 且 $\Gamma_{\mathrm{sf}}$ 有限时启用；否则不建 SF 块，(Gamma-SF) 不出现；
- 工程含义：业务方指定「SLA 尾部风险不超过 $\Gamma_{\mathrm{sla}}$、算力尾部风险不超过 $\Gamma_{\mathrm{sf}}$」，优化器在可行域内找最低 $c_{\mathrm{tot}}$。

**代码**：`build_teavar_model_c` 自建 MILP，约束组与 Model A 共用 §8.2，并添加 `loss_cvar <= gamma_sla` 与可选 `shortfall_cvar <= gamma_sf`。

---

## 10. Model A 与 Model C 对照

| 维度 | Model A | Model C |
|:--|:--|:--|
| 目标 | $c_{\mathrm{tot}} + \lambda_{\mathrm{sla}}\mathrm{CVaR}^{\mathrm{SLA}} + \lambda_{\mathrm{sf}}\mathrm{CVaR}^{\mathrm{SF}}$ | $\min c_{\mathrm{tot}}$ |
| 风险进入方式 | 加权惩罚（软） | 上界约束（硬） |
| 主超参 | $\lambda_{\mathrm{sla}},\lambda_{\mathrm{sf}}$ | $\Gamma_{\mathrm{sla}},\Gamma_{\mathrm{sf}}$ |
| 变量与物理约束 | 相同 | 相同 |
| 典型解释 | 调参扫 frontier：权重 ↔ 方案 | 合同式：给定风险预算 → 最低成本 |

---

## 11. 求解流程（概念）

```text
输入 data（场景、容量、价格、路径）
  → 创建 y, x, d, ζ, u（及可选 SF 变量）
  → 添加放置、流量、容量、送达耦合约束
  → 添加 SLA，SF CVaR 线性化
  → Model A：设加权目标；Model C：设 min cost + Γ 约束
  → Gurobi MILP 求解
  → 输出 placement、成本、CVaR 值
```

---
