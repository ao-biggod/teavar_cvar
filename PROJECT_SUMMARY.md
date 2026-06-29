# TEAVAR: 端到端多路径流量工程与计算资源联合优化

> 项目代号 TEAVAR（Traffic Engineering and Adaptive Variability-Aware Routing）
> 最后更新：2026-06

---

## 一、参考论文

### [1] Rockafellar & Uryasev (2000) — CVaR 优化
- **论文**：Optimization of Conditional Value-at-Risk
- **核心贡献**：提出 CVaR 的线性化公式，将尾部风险度量转化为线性规划可解的形式
- **关键公式**：
  \[
  \text{CVaR}_\beta(L) = \min_{\alpha} \left\{ \alpha + \frac{1}{1-\beta} \mathbb{E}[\max(L - \alpha, 0)] \right\}
  \]
  其中 \(\beta\) 是置信水平，\(\alpha\) 是 VaR 阈值

### [2] TEAVAR 流量工程基础
- **来源**：TEAVAR: Throughput-Guaranteed Resilient Routing via CVaR（项目早期基础论文）
- **核心问题**：传统 TE 按"能抗几个故障"设计，忽略故障概率差异 → 过度保守或忽略高风险
- **核心理念**：不问"能抗几个故障"，而问"在 \(\beta\) 可用性目标下最多保证多少带宽"
- **损失函数（公式 3）**：\(\displaystyle L(x,y) = \max_i \left[1 - \frac{\sum_{r\in R_i} x_r y_r}{d_i}\right]^+\)
  - 用 **max per-flow loss** 做 fair 聚合，非加权平均
- **CVaR 优化（公式 4）**：
  \[
  \min_{x,\alpha} \; \alpha + \frac{1}{1-\beta} \sum_q p_q [L(x,y(q)) - \alpha]^+
  \]
  - CVaR **进目标函数**（不是约束）
- **场景生成**：SRG 独立 Bernoulli，同 AEGIS 公式 (1)
- **场景 Pruning**：
  - 树状遍历，概率 \(< 10^{-5}\) 时停止展开
  - 被剪场景合并为 aggregate scenario，loss 设 1.0
  - 得到 **CVaR 上界**（吞吐保证的保守下界）
- **从 loss 转可用带宽（公式 7）**：\(b_i = (1 - V_\beta(x^*)) d_i\)
- **对本项目的启发**：
  - max per-flow loss 可作为 fairness variant 替代 aggregate loss
  - 场景 pruning 的 aggregate scenario 方法可解决 Toy-2Task 的尾部遗漏问题
  - TEAVAR 是纯风险目标，本项目结合 Copo 成本 + AEGIS-A 约束结构

### [3] 多路径流量工程
- ECMP/WCMP、Segment Routing、SDN 集中式优化

### [4] 算力网络联合优化
- VNF Placement 在故障场景下的放置与服务链约束

### [5] AEGIS (Zhang et al., IEEE/ACM Trans. Networking 2026)
- **核心贡献**：用 CVaR 度量故障场景下的吞吐量尾部风险，保证最低吞吐量
- **两版本**：
  - **AEGIS-O**：CVaR 进目标 `min CVaR_β(吞吐损失)`
  - **AEGIS-A**：CVaR 进约束 `min 路由资源使用量 s.t. CVaR ≤ λ`
- **损失函数**：\(\Omega^q = \sum_k (f_k - g_k^q)\)，场景 q 下总吞吐损失
- **CVaR 线性化 (RU 形式)**：\(\text{CVaR}_\beta(\Omega) = \min_\alpha \{\alpha + \frac{1}{1-\beta} \sum_q p_q (\Omega^q - \alpha)^+\}\)
- **AEGIS-A (Theorem 2)**：
  \[
  \min \sum_k \sum_{(u,v)} (W_k(u,v)+W_k(v,u)) \quad \text{s.t.} \quad \text{CVaR}_\beta(\Omega) \le \lambda
  \]
- **场景生成**：SRLG 独立 Bernoulli（公式 (1)），\(p_{\hat q} = \prod_z [\hat q_z p_z + (1-\hat q_z)(1-p_z)]\)
- **与本项目的关系**：
  - M2-C-Cost 结构最接近 **AEGIS-A**（min 资源使用量 + CVaR 约束）
  - 场景生成方式与本项目 Toy-2Task 的独立组件故障一致
  - AEGIS 是纯网络路由（无计算放置），链路容量为硬约束
  - AEGIS 的 user budget \(\sum_e \kappa_e (W_k(u,v)+W_k(v,u)) \le b_k\) 可作为成本参考

### [6] Copo (Wang et al., ICNP 2025)
- **核心贡献**：地理分布式云中任务放置的计算成本 + 网络传输成本联合优化
- **放置成本 (公式 7)**：\(E_1 = \sum_r \sum_t \sum_i x^t_{i,r} q^t_i p_r\)（电力消耗 × 区域电价）
- **带宽成本 (公式 8)**：\(E_2 = \sum_j \sum_{(u,w)} y^j_{u,w} b_j p_{u,w}\)（通信流量 × 链路单价）
- **主目标 (公式 9)**：\(\min E_1 + E_2\)，性能通过下层 KKT 进入约束
- **确定性模型**：无故障场景、无 CVaR、无 stochastic recourse
- **与本项目的关系**：
  - `min E1+E2` 框架可作为 M2-C-Cost 的目标函数原型
  - 链路计费方式（按链路 traffic × link price）与本项目一致
  - Copo 的 task-to-task 通信（非两段式）与本项目结构不同

### 符号冲突提醒

AEGIS 和 Copo 的符号有大量冲突，不能直接混用。本项目采用以下统一符号：

| 符号 | AEGIS 含义 | Copo 含义 | **本项目** |
|:--|:--|:--|:--|
| \(q\) / \(\omega\) | failure situation | Copo 中 \(q_i^t\) 是电力消耗 | **\(\omega \in \Omega\)** 表示故障场景 |
| \(p\) | failure probability | price | **\(\pi_\omega\)** 场景概率，**\(\rho\)** 价格 |
| \(b\) | user budget | bandwidth demand | **\(b_i^{in/out}\)** 带宽需求 |
| \(\mathcal K\) | commodities | 不用 | **\(\mathcal I\)** 任务集，**\(\mathcal K\)** 资源维度 |
| \(\alpha\) | VaR threshold | KKT multiplier | **\(\alpha\)** VaR 阈值 |
| \(\beta\) | CVaR confidence | KKT multiplier | **\(\beta\)** CVaR 置信水平 |
| \(\gamma\) | throughput guarantee ratio | 不用 | **\(\gamma\)** CVaR 风险预算 |
| \(W\) | working flow | 不用 | **\(x^0\)** 计划流，**\(x^\omega\)** 场景流 |

---

## 二、设计特点与重要假设

### 2.1 两段式多路径路由

```
source s_i  →  多路径 ingress  →  execution node m  →  多路径 egress  →  destination d_i
```

选中节点后用等式守恒，不允许主动少送流量来降低链路负载。

### 2.2 端到端单一风险度量

所有故障的影响统一反映在 \(z_{i,s}\)（任务完成比例）中：

- 路径断 → 数据到不了 → \(z_{i,s}\) 下降
- 算力降额 → 处理不了 → \(z_{i,s}\) 下降
- 两者同时发生 → 自然交叉效应

一个任务在场景中可以完成任意比例（0%–100%），输入/计算/输出按相同比例缩放。**任务被建模为可分割、可部分服务的流体负载**。不可分割的原子任务不在当前主模型范围内。

### 2.3 自适应 Recourse（已知上界）

当前模型假设故障后控制器能够立即、无成本地重新计算全部路由。这是 **perfect-information adaptive recourse**，忽略：
- 故障检测延迟
- 路由更新延迟
- 重配置成本
- 路由震荡和规则数量限制

此外，当前只能重路由，**不能迁移 placement**——因为 \(r_{i,m,s} \le y_{i,m}\)，故障计算节点上的任务无法被迁移到另一节点。因此准确说法是"固定 placement 下的场景重路由"。

### 2.4 Pruned 场景用于 CVaR 的注意事项

独立 Bernoulli 故障模型产生 \(2^{23} = 8,388,608\) 个场景。为求解可行性，默认只保留故障组件数 ≤3 的场景并重新归一化（2,048 场景，概率质量 0.997854）。

**对被 CVaR 的影响**：被删除的场景（概率 ≈ 0.002146）虽然概率小，但通常是损失最严重的尾部。当 \(\beta = 0.99\) 时，CVaR 只观察最坏的 1%，被删除概率约占尾部质量的 1/5。

因此：
- Pruned CVaR 结果不是精确 CVaR，而是**下界估计**（遗漏了最坏尾部）
- 实验应包含 \(\text{max\_failed\_components} = 3,4,5\) 的敏感性分析
- 需始终报告 `dropped_probability_mass`

**TEAVAR 的解决方案**（推荐）：不直接丢弃被剪场景，而是将它们**合并为一个 aggregate scenario**，概率等于所有 pruned 概率之和，loss 设为最大值 1。这样得到的 CVaR 是**上界**（保守估计），而不是忽略尾部后的下界。详见 §一[2]。

---

## 三、建模变量与符号

### 3.1 拓扑与任务

| 符号 | 含义 |
|:--|:--|
| \(\mathcal{G}=(\mathcal{V},\mathcal{E})\) | 有向网络拓扑 |
| \(\mathcal{M}\subseteq\mathcal{V}\) | 计算节点 |
| \(\mathcal{R}=\mathcal{V}\setminus\mathcal{M}\) | 转发节点 |
| \(B_e\) | 链路 e 带宽容量（见量纲说明） |
| \(C_m^{(k)}\) | 节点 m 第 k 维资源容量 |
| \(\mathcal{J}\) | 任务集（代码中 I/J） |
| \(s_i, d_i\) | 源/宿节点 |
| \(w_i^{(k)}\) | 任务 i 对资源 k 的需求 |
| \(b_i^{in}, b_i^{out}\) | 输入/输出带宽需求（见量纲说明） |

> **量纲统一**：\(b_i^{in/out}\) 和 \(B_e\) 必须具有相同量纲，本文采用**规划周期内的数据总量**（如 GB/周期）。\(x\) 变量表示在该周期内通过路径传输的数据量，\(B_e\) 表示该周期内链路能承载的总数据量。论文中必须明确规划时间窗口。

### 3.2 决策变量

| 变量 | 类型 | 含义 |
|:--|:--|:--|
| \(y_{i,m}\) | \(\{0,1\}\) | 任务 i 是否部署在节点 m |
| \(x_{i,m,p}^{in/out}\) | \(\ge 0\) | **非场景**计划流量（M0 诊断用） |
| \(r_{i,m,s}\) | \([0, y_{i,m}]\) | 场景 s 下任务 i 在节点 m 的服务比例 |
| \(z_{i,s}\) | \([0,1]\) | 场景 s 下任务 i 的端到端服务比例 |
| \(x_{i,m,p,s}^{in/out}\) | \(\ge 0\) | 场景 s 下的实际路由流量（adaptive recourse） |

### 3.3 CVaR 与成本变量

| 变量/参数 | 类型 | 含义 |
|:--|:--|:--|
| \(\alpha\) | \([0,1]\) | VaR 阈值（\(\beta\)-分位数） |
| \(u_s\) | \([0,1]\) | 场景 s 尾部超额 |
| \(L_s^{E2E}\) | — | 端到端损失（中间量） |
| \(\gamma\) | 参数 | CVaR 风险预算上界 |
| \(\beta\) | 参数 | CVaR 置信水平 |
| \(\theta_i\) | 参数 | 任务业务优先级权重（默认 1） |
| \(\rho_{m,k}\) | 参数 | 节点 m 资源 k 的单位价格 |
| \(\rho_e\) | 参数 | 链路 e 的单位带宽价格 |

---

## 四、模型实现状态

```
M0                  [implemented + validated]   确定性负载均衡诊断
M1                  [implemented]               场景化 recourse + 服务比例
M2-Service-Lex      [implemented + validated]   最大化期望服务 + CVaR 约束（旧 M2-Lex）
M2-C-Cost           [mathematical design only]  成本最小化 + CVaR 约束
M2-Lex-3            [mathematical design only]  三阶段词典序（CVaR → 服务 → 成本）
```

M2-C-Cost 尚未编码，以下为数学设计。

---

## 五、M2-C-Cost：成本最小化 + 单一端到端 CVaR

### 5.1 目标函数

\[
\min \; c_p(y) + \sum_{s \in \mathcal{S}} \pi_s \, c_b(x_s)
\]

- \\(c_p(y) = \sum_{i,m} y_{i,m} \sum_k w_i^{(k)} \rho_{m,k}\\)：计算节点资源费（Stage 1 决定，不随场景变化）
- \\(c_b(x_s) = \sum_e \rho_e \cdot \text{LinkLoad}_{e,s}\\)：**场景期望带宽成本**（按 adaptive recourse 实际流量计费）

**重要**：带宽成本按场景流量 \(x_s\) 计算，**不是** M0 的计划流量 \(x\)。因为 adaptive recourse 下实际执行的是 \(x_s\)，不是故障前预定的 \(x\)。

### 5.2 约束

**端到端 CVaR 约束**
\[
\text{CVaR}_\beta(L^{E2E}) \le \gamma
\]

端到端损失定义为加权平均未满足服务比例（不引入 \(D_i\)）：
\[
L_s^{E2E} = \frac{\sum_{i} \theta_i (1 - z_{i,s})}{\sum_{i} \theta_i} = \sum_i \omega_i (1 - z_{i,s}), \quad
\omega_i = \frac{\theta_i}{\sum_j \theta_j}
\]

默认 \(\theta_i = 1\)，此时 \(L_s^{E2E}\) 退化为所有任务未满足比例的算术平均。\(\theta_i\) 仅在需要区分业务优先级时设置为离散值（如 3/2/1）。

> **为什么不用 \(D_i\)**：\(b_i^{in}, b_i^{out}, w_i^{(k)}\) 已分别描述网络和算力需求，再引入 \(D_i\) 会导致重复计权、量纲混乱、与 \(\theta_i\) 功能重叠。当前主模型中 \(D_i\) 没有独立语义，最优做法是 \(D_i \equiv 1\) 即直接从公式中删除。流量加权损失（如 \(L_s^{traffic} = \sum b_i^{in}(1-z)/\sum b_i^{in}\)）可作为 post-hoc 敏感性指标，不建议替换主 E2E 损失。

**正常场景全服务保障**
\[
z_{i,s_0} = 1, \quad \forall i
\]
防止模型在无故障的正常场景下主动降服务来省钱。

**期望服务保障**
\[
\sum_{s} \pi_s \, z_{i,s} \ge \rho_i, \quad \forall i, \quad \rho_i \in [0,1]
\]
防止模型为了省带宽而系统性降低服务比例。\(\rho_i\) 是 SLA 合同约定的最低平均服务水平。

**M1 场景化约束**（保持不变）
\[
\begin{aligned}
&0 \le r_{i,m,s} \le y_{i,m} \\
&z_{i,s} = \sum_m r_{i,m,s} \\
&\sum_p x_{i,m,p,s}^{in} = b_i^{in} r_{i,m,s}, \quad
\sum_q x_{i,m,q,s}^{out} = b_i^{out} r_{i,m,s} \\
&\text{LinkLoad}_{e,s} \le B_e \sigma_{e,s} \\
&\sum_i r_{i,m,s} w_i^{(k)} \le C_{m,s}^{(k)}
\end{aligned}
\]

**M0 确定性约束**（仅用于标称容量可行性）
\[
\sum_{m} y_{i,m} = 1, \quad
\sum_p x_{i,m,p}^{in} = b_i^{in} y_{i,m}, \quad
\sum_q x_{i,m,q}^{out} = b_i^{out} y_{i,m}
\]
\[
\text{LinkLoad}_e \le B_e, \quad
\sum_i y_{i,m} w_i^{(k)} \le C_m^{(k)}
\]

### 5.3 为何需要服务保障

如果只有 `min cost + CVaR ≤ γ`，模型可能主动少服务来省钱——因为少发送流量直接降低成本，只要 CVaR 不超过 \(\gamma\) 就可以。增加 \(z_{i,s_0}=1\) 和 \(\mathbb{E}[z] \ge \rho\) 两个约束后，模型必须在保证基本服务水平的前提下优化成本，不会出现"便宜但主动丢服务"的解。

### 5.4 CVaR 线性化

**端到端服务损失（加权平均版本，主线）**
\[
L_s^{E2E} = \frac{\sum_i \theta_i (1 - z_{i,s})}{\sum_i \theta_i}
\]
默认 \(\theta_i = 1\)，等权算术平均。不引入 \(D_i\)。

**公平性变体（TEAVAR 式 max per-flow loss）**
\[
L_s^{fair} = \max_i (1 - z_{i,s})
\]
用 epigraph 线性化：\(L_s^{fair} \ge 1 - z_{i,s}, \forall i\)。不会因加权平均而牺牲小任务，适合做敏感性对比。

**Rockafellar-Uryasev 线性化**
\[
\text{CVaR}_\beta(L) = \alpha + \frac{1}{1-\beta} \sum_s \pi_s u_s
\]
\[
u_s \ge L_s^{E2E} - \alpha, \quad u_s \ge 0, \quad 0 \le \alpha \le 1
\]

---

## 六、M2-Lex-3：三阶段词典序验证模型

不依赖人工设定的 \(\gamma\) 和 \(\rho\)，按优先级依次优化：

```
Pass 1: min CVaR_β(L^{E2E})           ← 系统理论上能达到的最低风险
Pass 2: max E[z]  (fix CVaR at Pass 1) ← 在最低风险下最大化服务
Pass 3: min cost (fix CVaR and E[z])   ← 前两者固定后的最低成本
```

这个版本可以分别回答两个问题：
- **M2-Lex-3**：系统理论上能达到多低的风险 + 多高的服务？
- **M2-C-Cost**：在给定 SLA 合同 \((\gamma, \rho)\) 下，最低成本是多少？

---

## 七、约束条件汇总

### 7.1 放置约束

\[
\sum_{m\in\mathcal{M}_i} y_{i,m} = 1, \quad \forall i
\]

### 7.2 流量守恒

**计划流量（M0 诊断）**
\[
\sum_p x_{i,m,p}^{in} = b_i^{in} y_{i,m}, \quad
\sum_q x_{i,m,q}^{out} = b_i^{out} y_{i,m}
\]

**场景流量（adaptive recourse）**
\[
\sum_p x_{i,m,p,s}^{in} = b_i^{in} r_{i,m,s}, \quad
\sum_q x_{i,m,q,s}^{out} = b_i^{out} r_{i,m,s}
\]

### 7.3 容量约束

**标称容量（M0，硬约束）**
\[
\text{LinkLoad}_e \le B_e, \quad
\sum_i y_{i,m} w_i^{(k)} \le C_m^{(k)}
\]

**场景容量（每场景独立检查，硬约束）**
\[
\text{LinkLoad}_{e,s} \le B_e \sigma_{e,s}, \quad
\sum_i r_{i,m,s} w_i^{(k)} \le C_{m,s}^{(k)}
\]

### 7.4 服务比例约束

\[
0 \le r_{i,m,s} \le y_{i,m}, \quad
z_{i,s} = \sum_m r_{i,m,s}, \quad
z_{i,s_0} = 1, \quad
\sum_s \pi_s z_{i,s} \ge \rho_i
\]

---

## 八、成本设计

### 8.1 计算节点成本

\[
c_p = \sum_{i,m} y_{i,m} \sum_{k} w_i^{(k)} \rho_{m,k}
\]

Stage 1 决策，不随场景变化。

### 8.2 带宽成本

**自适应 recourse 版本（主线）**
\[
c_b(x_s) = \sum_e \pi_e \cdot \text{LinkLoad}_{e,s}
\]
期望成本：\(\sum_s \pi_s c_b(x_s)\)

**非场景计划流量版本（M0 诊断用）**
\[
c_b = \sum_e \rho_e \cdot \text{LinkLoad}_e
\]

### 8.3 模型对照

| 模型 | 计算成本 | 带宽成本 | 风险成本 |
|:--|:--|:--|:--|
| Copo (ICNP 2025) | 按资源量×单价 | 按流量×链路价格 | 无 |
| AEGIS (Trans. Networking) | 无 | 无 | CVaR 尾部风险 |
| 旧 Model A/C | 有（`p_price`） | 有（`bandwidth_cost_expr`） | 双 CVaR |
| **M2-C-Cost（设计）** | **Stage 1 固定** | **期望场景流量** | **单一 CVaR(L^{E2E})** |

---

## 九、玩具数据集设计

### 9.1 ToyTE（11 节点 mesh 拓扑，宏场景）

```
        ┌──a──┬──mA──┬──b──┐
s1 ────┤     │      │     ├── t1
        ├──c──┤      ├──d──┤
s2 ────┤     │ mB   │     ├── t2
        │     ├──┘   └──┘  │
        │  mC │            │
        └─────┘            └──
```

- 11 节点, 24 有向边, 3 计算节点, 2 任务, 每对 3+3 路径
- 4 手写宏场景：normal / node-a fail / mA fail / a→c derate

### 9.2 Toy-2Task-IndependentComponentRisk-v1（独立 Bernoulli 故障）

- 11 节点, 20 有向边, 3 计算节点, 2 任务, 每对 2+2 路径
- 23 独立组件, 8,388,608 穷举场景, 2,048 pruned 场景
- Task1 必须多路径 ingress (单路径瓶颈 ≤3.0 < 4.0)
- Task2 必须多路径 egress (单路径瓶颈 ≤2.0 < 2.5)

---

## 十、验证结果

### 10.1 M0 λ 端点测试（ToyTE）

| λ | peak_link | peak_node | U_link_solver | U_node_solver |
|:--|:--|:--|:--|:--|
| 0 | 1.000 | 0.500 | 1.000 | 0.500 |
| 0.5 | 0.556 | 0.500 | 0.556 | 0.500 |
| 1 | 0.556 | 0.500 | 0.556 | 1.000 |

### 10.2 已实现模型

- M0：确定性负载均衡诊断 ✅
- M1：场景化 adaptive recourse ✅
- M2-Service / M2-Lex：最大化服务 + CVaR ✅

### 10.3 待实现模型

- M2-C-Cost：成本最小化 + 单一 CVaR 约束（本文档设计）
- M2-Lex-3：三阶段词典序（CVaR → 服务 → 成本）

### 10.4 Pipeline 集成状态

- Toy-2Task-IndependentComponentRisk-v1 是 standalone data builder + validation tests
- 尚未接入 `m0_instances.py` 或 `run_gamma_frontier.py` 等实验入口
- `build_toy_2task_independent_v1()` 暂时只由 tests / script 调用
- Pipeline integration 留到下一轮
