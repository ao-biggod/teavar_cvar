# 故障感知算力–网络联合优化：建模、求解与实验

## 一、定位更新（相对于 v1 初稿）



1. **故障模型**：从简单的三个故障场景修改为**独立故障场景生成 + 概率剪枝**，覆盖全部 38 条有向边。
2. **CVaR 线性化**：SLA 送达耦合和算力超额 CVaR 均采用 Rockafellar–Uryasev 标准形式，不使用 Big-M 或额外二元变量，降低数值不稳定性。
3. **链路成本**：带宽成本按独立的链路流量单位成本计费。
4. **节点CVaR细化**：对于不同的CPU,GPU,HBM的需求，设计方法统一量纲

---

## 二、系统模型

### 2.1 拓扑与算力资源

有向图 $\mathcal{G}=(\mathcal{N},\mathcal{E})$，算力节点集合 $\mathcal{M}\subseteq\mathcal{N}$。每节点 $m$ 配置 CPU/GPU/HBM 三维算力容量 $C^{\mathrm{norm}}_{mk}$ 与单位价格 $\pi_{mk}$。有向链路 $e=(u,v)$ 带宽容量 $B_e$。

### 2.2 任务模型

任务集合 $\mathcal{I}$，每任务 $i$ 独立给定：

- 物理源宿 $(s_i, t_i)$，从 B4  demand 矩阵中读取需求
- ingress/egress 数据量 $b^{\mathrm{in}}_i$, $b^{\mathrm{out}}_i$
- 多维算力需求 $\mathbf{w}_i = (w_{i,\mathrm{CPU}}, w_{i,\mathrm{GPU}}, w_{i,\mathrm{HBM}})$，取 3–5 种代表性 workload 模板轮换

路由为两阶段有向多路径：

$$s_i \xrightarrow{\text{ingress}} m \xrightarrow{\text{egress}} t_i$$

ingress/egress 各在预计算的 $K$ 条候选最短路径上分配。

### 2.3 故障模型：独立概率 + 概率剪枝

**数据来源**：B4 topology 对 38 条有向边各提供独立故障概率 $p_e$（量级约 $1.5\times 10^{-3} \sim 4.5\times 10^{-3}$）。

**场景生成**：枚举同时故障边数不超过 $k_{\max}$ 的所有组合。对每个故障边集 $F\subseteq\mathcal{E}$，场景概率为

$$\pi_F = \prod_{e\in F} p_e \cdot \prod_{e\notin F} (1-p_e)$$

丢弃 $\pi_F < \pi_{\min}=10^{-5}$ 的场景。

**场景可用率**：故障边 $e\in F$ 设定 $\sigma_{es}=0$，其余 $\sigma_{es}=1$（二元故障）。路径 $p$ 在场景 $s$ 下可用当且仅当所有边 $\sigma_{es}>0$。

**算力降额**：独立于链路故障，以概率 0.1 叠加 aggregation 节点容量降至名义值的 40%（$C^N_{mks}=0.4\cdot C^{\mathrm{norm}}_{mk}$）。最终场景集为 $\mathcal{S}=\mathcal{S}_{\mathrm{link}}\times\{\text{nominal}, \text{degraded}\}$ 统一切除低概率后 renormalize。



### 2.4 需求标定：过载比 η

$$\sum_{i\in\mathcal{I}} (b^{\mathrm{in}}_i + b^{\mathrm{out}}_i) = \eta \cdot C_{\mathrm{surv}}(s^*)$$

$C_{\mathrm{surv}}(s^*)$ 为最严重故障场景下瓶颈幸存容量（工程近似）。$\eta>1$ 保证最坏态出现结构性容量缺口；正常态利用率约 40–60%。$\eta=1.3$ 为标定默认值，涌现缺口比例 $\rho\approx 23\%$。

---

## 三、优化模型

### 3.1 符号表


## 任务参数

| 符号 | 含义 | 代码 |
|:---|:---|:---|
| $s_i,t_i$ | 任务 $i$ 源、汇节点 | `task_src[i]`, `task_dst[i]` |
| $b_i$ | 任务流量需求（论文主线） | 代码暂分 $b_i^{in}, b_i^{out}$（`b_in[i]`, `b_out[i]`），待对齐 |
| $w_{ik}$ | 任务 $i$ 在资源 $k$ 上的需求权重 | `w[i][k]` |
| $\eta$ | 需求标定因子（survivability calibration） | CLI `--eta`，默认 1.3 |

## 网络参数

| 符号 | 含义 | 代码 |
|:---|:---|:---|
| $p_e^{\mathrm{link}}$ | 链路 $e$ 独立故障概率 | B4 `topology.txt` `prob_failure`；代码 `data.pf[e]` |
| $Z_{e,\omega}^{\mathrm{link}}$ | 场景 $\omega$ 下链路 $e$ 可用指示 | $1$=可用，$0$=故障；代码 `data.sigma[e][s]` |
| $k_{\max}$ | 同时故障边数上界（枚举剪枝） | CLI `--micro-k-max`，默认 2 |
| $\pi_{\min}$ | 场景概率剪枝阈值 | CLI `--micro-pi-min`，默认 $10^{-5}$ |
| $B_e$ | 链路 $e$ 容量 | `data.B[e]` |
| $\pi_e^{\mathrm{price}}$ | 链路单位带宽单价 | `link_price[e]`（勿与 $q_\omega$ 混淆） |
| $\tau_p$ | 路径带宽单价 | `path_bandwidth_tariff` |
| $A_{p,\omega}$ | 路径 $p$ 在场景 $\omega$ 可用指示 | §4.5；代码 `path_up` |
| $q_\omega$ | 场景 $\omega$ 概率 | `data.prob[s]`；剪枝 / renormalize 后 $\sum_\omega q_\omega=1$ |

## 算力参数

| 符号 | 含义 | 代码 |
|:---|:---|:---|
| $C_{mk}^N$ | 节点 $m$ 资源 $k$ 名义容量 | `C_normal[m][k]` |
| $C_{mk,\omega}^{N}$ | 场景 $\omega$ 下有效容量 | `C_s[m][k][s]` |
| $\rho_{mk,\omega}$ | 场景降额乘子 | 由独立节点 / 资源故障事件生成；degraded 臂 aggregation $\times 0.4$ |
| $Z_{m,\omega}^{\mathrm{node}}$ | 节点 $m$ 可用指示（二元故障模型） | 可选；当前实现以 degraded / nominal 臂表达 |
| $D_{ref}$ | SF 短缺归一化分母 | Model C / posthoc：`compute_d_ref` $\equiv M_{ex}$ |
| $M_{ex}$ | SF 归一化上界；$D_{ref}=M_{ex}$ | `compute_d_ref(data)`（**非** Big-M 约束用） |
| $c_{mk}^N$ | 节点 $m$ 资源 $k$ 单位算力价格 | `p_price[m][k]` |

## 决策变量

| 符号 | 含义 | 代码 |
|:---|:---|:---|
| $y_{im}$ | 任务 $i$ 是否放置于 $m$ | `y[i,m]` BINARY |
| $x_{imp}^{in}$ | 计划 ingress 流量 | `xin[i,m,p]` |
| $x_{imp}^{out}$ | 计划 egress 流量 | `xout[i,m,q]` |
| $d_{imp,\omega}^{in/out}$ | 场景 $\omega$ 下 ingress / egress 送达量 | `del_in/out[i,m,p/q,s]` |
| $\mathrm{Del}_{i,\omega}$ | 任务 $i$ 场景 $\omega$ 最终送达（瓶颈变量） | 见 §4.6 |
| $R_\omega^{SLA}$ | 场景 SLA 损失率 $1-\mathrm{Del}_\omega/D$ | **论文主线**；代码暂用 per-task max loss |
| $R_\omega^{sf}$ | 场景 SF 损失 $\sum E/D_{ref}$ | `compute_sf_loss_by_scenario` |
| $\zeta^{SLA}, u_\omega^{SLA}$ | SLA CVaR 辅助变量 | `zeta_sla`, `u_s[s]` |
| $\zeta^{sf}, \phi_\omega^{sf}$ | SF CVaR 辅助变量 | `zeta_sf`, `phi_s[s]` |

## Model M 相关

| 符号 | 含义 |
|:---|:---|
| $L_s$ | 场景 $s$ 货币化账单 |
| $\kappa$ | 送达短缺违约金系数（代码可拆分 `kappa_sum`, `kappa_max`, `kappa_sf`） |
| $\mathrm{Shortfall}_s$ | 场景送达缺口 |
| $\Gamma^M$ | Model M-C 货币 CVaR 预算 |


### 3.2 成本
**设计原则：** 每条链路有自己的流量单价；链路成本按「流量 × 单价」累加；不同区域（节点角色）之间链路不同价。

**角色系数** $\phi(\mathrm{role}[u],\mathrm{role}[v])$：

| | core | aggregation | edge_pop |
|:---|:---:|:---:|:---:|
| **core** | 1.0 | 1.5 | 2.5 |
| **aggregation** | 1.5 | 2.0 | 2.5 |
| **edge_pop** | 2.5 | 2.5 | 3.5 |

**链路单价：**

$$
\pi_e^{\mathrm{price}} = \mathrm{scale} \times \phi(\mathrm{role}[u], \mathrm{role}[v])
$$

**路径价与带宽费：**

$$
\tau_p = \sum_{e\in p} \pi_e^{\mathrm{price}},\qquad
C^{bw} = \sum_{i,m,p} x_{imp}^{\mathrm{in}}\,\tau_p + \sum_{i,m,q} x_{imp}^{\mathrm{out}}\,\tau_q
$$


**放置成本**（异构多维）：

$$c_p = \sum_{i,m} y_{im} \sum_k w_{ik} \cdot \pi_{mk}$$


### 3.3 约束

**单点放置**：$\sum_m y_{im}=1, \forall i$

**流量激活**：$\sum_p x^{\mathrm{in}}_{i,m,p} \le y_{im} b^{\mathrm{in}}_i$（egress 对称）

**名义算力容量**：$\sum_i w_{ik} y_{im} \le C^{\mathrm{norm}}_{mk}, \forall m,k$

**场景送达耦合**（无 Big-M）：

对每个场景 $s$，路径 $p\in\mathcal{P}_{s_i,m}$：

$$\begin{cases}
d^{\mathrm{in}}_{i,m,p,s} = x^{\mathrm{in}}_{i,m,p} & \text{if } \forall e\in p: \sigma_{es} > 0 \\
d^{\mathrm{in}}_{i,m,p,s} = 0 & \text{otherwise}
\end{cases}$$

$\sigma_{es}$ 在 build time 确定，故上述为线性等式约束，无需 Big-M 或二元变量。

### 3.4 网络侧 CVaR（SLA）

场景送达聚合：$R^{\mathrm{in}}_{is}=\sum_{m,p} d^{\mathrm{in}}_{i,m,p,s}$，$R^{\mathrm{out}}_{is}=\sum_{m,q} d^{\mathrm{out}}_{i,m,q,s}$。

**Rockafellar–Uryasev 线性化**（与 TEAVAR 一致）：

$$u_s \cdot b^{\mathrm{in}}_i \ge b^{\mathrm{in}}_i - R^{\mathrm{in}}_{is} - b^{\mathrm{in}}_i \cdot \zeta_{\mathrm{sla}} \quad \forall i,s$$

$$u_s \cdot b^{\mathrm{out}}_i \ge b^{\mathrm{out}}_i - R^{\mathrm{out}}_{is} - b^{\mathrm{out}}_i \cdot \zeta_{\mathrm{sla}} \quad \forall i,s$$

$$u_s \ge 0$$

$$\mathrm{CVaR}^{\mathrm{SLA}} = \zeta_{\mathrm{sla}} + \frac{1}{1-\beta_{\mathrm{sla}}}\sum_s \pi_s \cdot u_s$$

逐任务比例探测：ingress 与 egress 各自约束同一个 $u_s$，$u_s$ 取两者中更紧的损失。目标最小化驱动 $u_s = \max_i\{\max(0, 1-R^{\mathrm{in}}_{is}/b^{\mathrm{in}}_i - \zeta_{\mathrm{sla}}), \max(0, 1-R^{\mathrm{out}}_{is}/b^{\mathrm{out}}_i - \zeta_{\mathrm{sla}})\}$。

### 3.5 算力侧 CVaR（算力未满足）

节点聚合需求：$D_{mk} = \sum_i w_{ik} y_{im}$。

**场景标量损失**：

$$L^{\mathrm{sf}}_s = \max_{m,k}\frac{\max(0, D_{mk} - C^N_{mks})}{D_{\mathrm{ref}}}$$

$D_{\mathrm{ref}}$ 为归一化常数（保守尺度，取 $\max(\max_{m,k}\sum_i w_{ik}, \max_{m,k,s}C^N_{mks})+1$）。

**R&U 线性化**（无 Big-M，无二元变量）：

$$\phi_s \ge \frac{D_{mk} - C^N_{mks}}{D_{\mathrm{ref}}} - \zeta_{\mathrm{sf}} \quad \forall m,k,s$$

$$\phi_s \ge 0$$

$$\mathrm{CVaR}^{\mathrm{sf}} = \zeta_{\mathrm{sf}} + \frac{1}{1-\beta_{\mathrm{sf}}}\sum_s \pi_s \cdot \phi_s$$

**等价性**：目标最小化 $\lambda_{\mathrm{sf}}\cdot\mathrm{CVaR}^{\mathrm{sf}}$ 中 $\phi_s$ 有正系数，$\phi_s$ 在最优点自动取到所有 $(m,k)$ 下界中的最大值——等价于 $\phi_s = \max(0, L^{\mathrm{sf}}_s - \zeta_{\mathrm{sf}})$。整个过程不需要额外二元变量或 Big-M 常数。

---

## 四、Model A 与 Model C

**Model A（加权标化，Pareto 探索）**：

$$\min \quad c_p + c_b - \omega \cdot \mathbb{E}[\mathrm{Del}] + \lambda_{\mathrm{sla}} \cdot \mathrm{CVaR}^{\mathrm{SLA}} + \lambda_{\mathrm{sf}} \cdot \mathrm{CVaR}^{\mathrm{sf}}$$

扫 $\lambda$ 描绘 cost–risk Pareto 前沿，为 Model C 标定风险预算 $\Gamma$。

**Model C（ε-约束，部署/合同）**：

$$\min \quad c_p + c_b - \omega \cdot \mathbb{E}[\mathrm{Del}]$$

$$\text{s.t.} \quad \mathrm{CVaR}^{\mathrm{SLA}} \le \Gamma_{\mathrm{sla}}, \quad \mathrm{CVaR}^{\mathrm{sf}} \le \Gamma_{\mathrm{sf}}$$

A 与 C 描述同一条 Pareto 前沿。C 的价值在于 $\Gamma$ 是可签署的合同语言——运营商可直接将风险预算写入 SLA，而 $\lambda$ 不具备此可解释性。

**理论附注**：加权标量化（Model A）在整数规划上只能保证覆盖 Pareto 前沿的凸包部分（Ehrgott, 2005）；ε-约束（Model C）无此限制。本文将此作为理论完备性陈述（引文献），不做新发现声称。

---

## 五、实验设计（待补）

### 5.1 主实验配置

| 参数 | 值 |
|------|-----|
| 拓扑 | B4（12 节点，38 有向边） |
| 路由 | per-task OD（$s_i\to m\to t_i$） |
| 任务数 | $|I|=8$（为主前沿配置） |
| 故障模型 | micro_pruned（per-edge pf + $k_{\max}=2$ + $\pi_{\min}=10^{-5}$） |
| 过载比 | $\eta=1.3$ |
| CVaR 置信 | $\beta_{\mathrm{sla}}=\beta_{\mathrm{sf}}=0.95$ |
| 链路成本 | uniform（τ_p = |p|） |
| 模型 | Model C，$\Gamma$ 网格 $5\times 5$ |

### 5.2 待补实验

- [ ] 单 vs 双 CVaR 消融（$\lambda_{\mathrm{sf}}=0$ 对照）
- [ ] ATT 代表点（同一 $\eta$ recipe）
- [ ] $\eta$ 敏感性（$\eta\in\{1.2, 1.3, 1.5\}$）
- [ ] 路由模式消融（per_task_od vs UMCF per-task vs UMCF global）

### 5.3 与 v1 初稿的关键方法变化

| 维度 | v1 | v2 |
|------|-----|-----|
| 故障模型 | macro3：top-4 边统一 σ=0.80 | micro_pruned：per-edge pf 独立故障 + 剪枝 |
| CVaR 线性化 | 算力 CVaR 使用 Big-M + w_exc 二元 | 纯 R&U，无 Big-M，无额外二元变量 |
| 链路成本 | inverse_capacity（π_e ∝ 1/B_e） | uniform（π_e = 1.0，按跳数计费） |
| 送达耦合 | Big-M（del ≤ M·y） | 等式约束（del == x 或 del == 0） |
| 路径覆盖 | 34/38 边在故障场景中免疫 | 全部 38 条边均可独立故障 |

---

*草案日期：2026-06-04 | 基于 v1 初稿的方法改进总结*
