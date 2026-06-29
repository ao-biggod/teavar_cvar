# 故障感知算力–网络联合优化 MILP 框架本周阶段性进展报告



---

## 摘要

本周主要是对前面模型的细节进行了完善。完成了 per-task OD 路由从 hub 退化模式向任务级源–汇锚点 $s_i \to m \to t_i$ 的阶段性落地；建立了 Model C 目标函数与 `monetary_cost` 的字段语义诊断；实现了 post-hoc CVaR、Pareto 过滤与 formal acceptance 工具链（Phase B+++）。**论文方法主线**（§0、§14.1）：独立链路 / 节点故障 → $\omega\in\Omega$；path-up 送达 $d_{imp,\omega}=A_{p,\omega}x_{imp}$；聚合 SLA 损失 $R_\omega^{SLA}=1-\mathrm{Del}_\omega/D$；Copo-style role-transit 定价；micro-pruned 场景生成。**当前已验证 fixture**（§14.2）：uniform pricing + gate 25 点 Γ 网格 **PASS**，4 个 non-dominated 风险三元组，**不是**最终论文主图。

**Phase B++++ parity diagnosis 已完成。** 恢复 $D_{ref}=M_{ex}$ 后 formal P0 25 点重跑 **PASS**：posthoc SLA 3 档、posthoc SF 2 档、non-dominated distinct triples = 6。`results/p0_uniform_v2/p0_gamma_frontier_b4_tasks8.csv` 为 **风险结构 SSOT 候选**（fixture 配置）；per-resource SF 文件已归档 NON-SSOT。**Phase C-0 已完成**：raw `monetary_cost` 不宜作论文 cost 轴；**Phase C-1 secondary costing** 为下一步主线。

---

# 1. 项目主要背景

## 1.1 问题定义

本项目研究 **故障感知（failure-aware）算力–网络联合优化**：在广域网（WAN）拓扑上，同时决定

1. **算力放置**（compute placement）：任务 $i$ 部署于物理节点 $m$；
2. **两阶段路径路由**（ingress / egress routing）：任务流量从源 $s_i$ 经 ingress 路径进入放置节点，再经 egress 路径送达目的 $t_i$；
3. **多场景故障下的送达与短缺风险**：在离散场景 $\omega \in \Omega$（代码索引 $s\in S$）下评估网络 SLA 送达能力与算力容量短缺；$\Omega$ 由链路 / 节点独立故障概率生成，**不是**手工「正常 / 链路故障 / 算力降额」三状态编号。

目标是在 **货币成本**（算力租金 + 带宽费）与 **双通道 Conditional Value-at-Risk（CVaR）** 之间做可解释的权衡。

## 1.2 与相关工作的区别（工作层面，非正式 Related Work）

| 方向 | 侧重点 | 本项目差异 |
|:---|:---|:---|
| **TEAVAR**（NeuroIPS 2020） | 单通道 TE 可用性 + hub 径向流 | 双通道 CVaR（网络 SLA + 算力 SF）；per-task OD 泛化 |
| **Copo** 等算力调度 | 算力放置 / 副本 | 显式 ingress–egress 两阶段 WAN 路由与带宽费 |
| **AEGIS** 等故障感知路由 | 网络层恢复 | 算力–网络 **联合** MILP；场景化 CVaR 预算（Model C） |

## 1.3 核心建模贡献（论文方法主线）

1. **双通道 CVaR 风险度量**
   - **SLA 通道：** $R_\omega^{SLA}=1-\mathrm{Del}_\omega/D$，$\mathrm{Del}_{i,\omega}$ 受 ingress/egress 瓶颈约束（§4.6）；
   - **SF 通道：** $R_\omega^{sf}=\sum_{m,k}E_{mk,\omega}/D_{ref}$，$D_{ref}=M_{ex}$（当前已验证 fixture 口径）。

2. **路由模式**
   - **Per-task OD（主线）：** $s_i \to m \to t_i$，每任务独立路径锚点；
   - **Hub 退化特例：** $h \to m \to h`，仅回归测试 / 消融，**不是**论文主实现。

3. **Model A / Model C 双视角**
   - Model A：$\lambda$-加权探索 Pareto 地图；
   - Model C：**risk-budgeted cost-delivery**（$\min C^{money}-\omega_{del}\mathbb{E}[\mathrm{Del}]$，s.t. 双 CVaR $\le\Gamma$），**不是**纯 $\min cost$ epsilon-constraint。

4. **故障模型（论文主线）**
   - 每条链路 $e$ 独立故障概率 $p_e^{\mathrm{link}}$；场景 $\omega$ 下链路可用指示 $Z_{e,\omega}^{\mathrm{link}}\in\{0,1\}$（Bernoulli 采样 / 枚举）；
   - 路径可用 $A_{p,\omega}=\prod_{e\in E(p)} Z_{e,\omega}^{\mathrm{link}}=\min_{e\in E(p)} Z_{e,\omega}^{\mathrm{link}}$（实现为 `path_up` **indicator**，非连乘期望）；
   - 节点 / 资源维独立故障或降额：$C_{mk,\omega}^{N}=\rho_{mk,\omega} C_{mk}^{N}$，$\rho$ 由独立事件生成；
   - 有限场景集 $\Omega$ 由 micro-pruned / top-risk pruning / Monte Carlo 得到（见 §1.4）；legacy `macro3` 仅为 Phase B+ 诊断 fixture。

5. **链路定价（论文主线 — copo_v1 / role_transit）**
   - 每条有向边独立单价 $\pi_e^{\mathrm{price}}=\mathrm{scale}\times\phi(\mathrm{role}[u],\mathrm{role}[v])$，按节点角色（core / aggregation / edge_pop）区分区域间传输成本（见 §1.5）；
   - 路径价 $\tau_p=\sum_{e\in p}\pi_e^{\mathrm{price}}$，带宽费 $C^{bw}=\sum x\cdot\tau_p$；
   - `scale` 由参考策略标定，使带宽费约占总成本 30%（B4×8 tasks 默认 $\mathrm{scale}\approx 0.00306$）。

6. **MILP 线性化（论文主线表述）**
   - 场景送达耦合：$d_{imp,\omega}=A_{p,\omega}x_{imp}$（`add_scenario_delivery_coupling`），**无** Big-M 送达耦合；
   - 算力 SF CVaR：$R_\omega^{sf}=\sum E/D_{ref}$ + Rockafellar–Uryasev 线性化；
   - $D_{ref}=M_{ex}$ 为当前已验证 fixture 口径；per-resource $D_{ref}[k]$ 为候选改进，**不是**当前 SSOT。

> **代码与论文对齐状态：** cap3 path-up 送达、R&U SF CVaR、micro_pruned 场景生成已在代码中落地，但 **尚未** 与 copo_v1 + micro_pruned 完整 pipeline 一起通过 formal acceptance（§14.3）。当前 formal PASS 的 CSV 仍来自 uniform fixture。

## 1.4 故障模型：独立链路 / 节点故障 → 有限场景集 $\Omega$

**论文目标主线（§14.1）：** 故障场景 **不是** 手工 $s=0,1,2$，而是联合 realization $\omega\in\Omega$。目标实现为 `scenario_mode=micro_pruned`（per-edge 伯努利枚举 + 剪枝 + 算力 Cartesian 积；B4 约 71 场景）。**当前已验证 fixture 仍可能使用 legacy `macro3`**（§14.2）——二者必须分开叙述。

### 链路独立故障

每条链路 $e\in E$ 有独立故障概率 $p_e^{\mathrm{link}}$（B4：`topology.txt` `prob_failure`，38 条有向边，量级约 $1.5\times 10^{-3}\sim 4.5\times 10^{-3}$）。在场景 $\omega$ 下：

$$
Z_{e,\omega}^{\mathrm{link}} \in \{0,1\},\qquad
\Pr(Z_{e,\omega}^{\mathrm{link}}=0)=p_e^{\mathrm{link}},\quad
\Pr(Z_{e,\omega}^{\mathrm{link}}=1)=1-p_e^{\mathrm{link}}
$$

不同链路故障事件 **相互独立**（除非后续显式引入相关故障模型）。代码中 $\sigma_{e,s}\equiv Z_{e,\omega}^{\mathrm{link}}$（$s$ 为 $\omega$ 的实现索引）。

### 节点 / 算力资源故障或降额

每个算力节点 $m$（或资源维 $(m,k)$）可有独立故障 / 降额概率 $p_m^{\mathrm{node}}$ 或 $p_{mk}^{\mathrm{res}}$。场景 $\omega$ 下：

$$
Z_{m,\omega}^{\mathrm{node}}\in\{0,1\}\ \Rightarrow\ C_{mk,\omega}^{N}=Z_{m,\omega}^{\mathrm{node}} C_{mk}^{N}
$$

或采用资源维 / 降额乘子：

$$
C_{mk,\omega}^{N}=\rho_{mk,\omega}\, C_{mk}^{N},\qquad 0\le \rho_{mk,\omega}\le 1
$$

其中 $\rho_{mk,\omega}$ **由独立故障或降额事件生成**，不是手工写死的状态编号。当前 micro_pruned 实现：以先验 0.1 叠加 aggregation 节点 **degraded** 臂（$C_{mk,\omega}^{N}=0.4\,C_{mk}^{N}$），与 **nominal** 臂做 Cartesian 积。

### 场景 $\omega$ 与概率 $q_\omega$

$$
\omega \in \Omega = \big\{ \{Z_{e,\omega}^{\mathrm{link}}\}_{e\in E},\; \{Z_{m,\omega}^{\mathrm{node}}\}_{m\in M}\ \text{或}\ \{Z_{mk,\omega}^{\mathrm{res}}\}\ \big\}
$$

**完整枚举**时，场景概率为独立事件乘积：

$$
q_{\omega}
=
\prod_{e\in E}
\left(p_e^{\mathrm{link}}\right)^{1-Z_{e,\omega}^{\mathrm{link}}}
\left(1-p_e^{\mathrm{link}}\right)^{Z_{e,\omega}^{\mathrm{link}}}
\cdot
\prod_{m\in M}
\left(p_m^{\mathrm{node}}\right)^{1-Z_{m,\omega}^{\mathrm{node}}}
\left(1-p_m^{\mathrm{node}}\right)^{Z_{m,\omega}^{\mathrm{node}}}
$$

（资源维建模时将节点乘积换为 $\prod_{m,k}$ 与 $p_{mk}^{\mathrm{res}}$。）**Monte Carlo / micro-pruned 剪枝** 下，$q_\omega$ 为采样权重或剪枝后 renormalize 概率；代码 `data.prob[s]\equiv q_\omega$。

### micro_pruned 生成步骤（当前实现）

| Step | 内容 |
|:---|:---|
| **1** | 读 $p_e^{\mathrm{link}}$ → `data.pf` |
| **2** | 枚举故障边集 $F\subseteq E$，$\|F\|\le k_{\max}$（默认 2）；令 $Z_{e,\omega}^{\mathrm{link}}=0$ 若 $e\in F$，否则 $1$；$q_\omega=\prod_{e\in F}p_e\prod_{e\notin F}(1-p_e)$ |
| **3** | 丢弃 $q_\omega<\pi_{\min}$（默认 $10^{-5}$），renormalize → $S_{\mathrm{link}}$ |
| **4** | $S_{\mathrm{link}}\times\{\mathrm{nominal},\mathrm{degraded}\}$，积概率再剪枝 / renormalize；B4 $\|\Omega\|\approx 71$ |

### 路径可用 $A_{p,\omega}$

$$
A_{p,\omega}=\prod_{e\in E(p)} Z_{e,\omega}^{\mathrm{link}}
=\min_{e\in E(p)} Z_{e,\omega}^{\mathrm{link}}
$$

MILP 使用 **sampled / enumerated binary path-up indicator**（`path_up`），**不对** $\sigma$ 做连乘期望。连乘可用于路径 **先验可靠性** 分析；场景内送达只用 $A_{p,\omega}\in\{0,1\}$。

> **`macro3` / `uniform` 定位：** Phase B+ gate **诊断 fixture**（§14.2），**不是**论文目标主线。论文目标为 micro_pruned + copo_v1（§14.1）；**尚未**与 formal acceptance 合并验收。

## 1.5 链路定价：role_transit（copo_v1）

**设计原则：** 每条链路有自己的流量单价；链路成本按「流量 × 单价」累加；不同区域（节点角色）之间链路不同价。

**角色系数** $\phi(\mathrm{role}[u],\mathrm{role}[v])$（`COPO_V1_ROLE_TRANSIT`，`duibi_metrics.py`）：

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

**示例**（edge→agg→core 两跳路径）：$\phi(\mathrm{edge},\mathrm{agg})=2.5$，$\phi(\mathrm{agg},\mathrm{core})=1.5$，故 $\tau_p = \mathrm{scale}\times 4.0$。

**标定：** `pricing_profile=copo_v1` 时默认 `bandwidth_price_mode=role_transit`；`scale` 由 `cheapest_placement_min_path_tariff` 参考策略自动标定，使 $C^{bw}/(C^{comp}+C^{bw})\approx 30\%$（B4×8 tasks：$\mathrm{scale}\approx 0.003056$）。实现：`configure_pricing_on_data()` / `load_joint_data(..., pricing_profile="copo_v1")`。

**与 uniform 的区别：** uniform 设 $\pi_e^{\mathrm{price}}=1$（仅按跳数计费、不区分区域）；**仅用于 Phase B+ parity fixture 归档**，不是论文主线。

# 2. 本周工作概览

| 阶段 | 内容 | 状态 | 主要产物 |
|:---|:---|:---|:---|
| **Per-task OD 0+1** | 数据加载、路径锚点、valid_assign、指标与单测 | 完成 | `b4_joint_data.py`, `duibi_metrics.py`, `tests/test_per_task_od.py` |
| **Phase B++** | Model C 目标 / monetary_cost 分解诊断；Γ 单调性 | 完成 | `scripts/diagnose_gamma_monotonicity.py`, `results/temp_smoke_posthoc_gamma/model_c_gamma_diagnostic.csv` |
| **Phase B+++** | posthoc CVaR SSOT、Pareto 标注、formal acceptance | 完成 | `metrics_posthoc.py`, `pareto_frontier.py`, `scripts/formal_p0_acceptance.py`, `results/README_metrics.md` |
| **Phase B+ gate** | B4×8 tasks×25 点 Γ 网格；uniform 链路价；posthoc 驱动验收 | **PASS**（fixture） | `results/temp_smoke_posthoc_gamma/uniform_frontier_b4_tasks8_posthoc_gamma.csv`, `results/p0_uniform_v2/p0_gamma_frontier_b4_tasks8_gated.csv` |
| **Formal P0 rerun（历史 FAIL）** | per-resource SF 污染实验 | **FAIL**（已归档 NON-SSOT） | `p0_gamma_frontier_b4_tasks8_NON_SSOT_sf_per_resource.csv` |
| **Phase B++++** | parity diagnosis、config snapshot、四点矩阵 | **完成** | `frontier_config_snapshot.py`, `scripts/compare_frontier_parity.py`, `parity_report.json`, `parity_matrix/summary.json` |
| **Formal P0 rerun（当前）** | $D_{ref}=M_{ex}$ 口径 25 点重跑 | **PASS**（fixture 风险结构） | `results/p0_uniform_v2/p0_gamma_frontier_b4_tasks8.csv` |
| **Phase C-0** | cost-axis determinacy check | **完成** | `cost_axis_diagnosis.md` |
| **Phase C-1** | secondary costing reporting | **待实现** | — |

---

# 3. 符号表

## 3.1 集合与索引

| 符号 | 含义 | 代码对应 |
|:---|:---|:---|
| $G=(V,E)$ | 物理 WAN 图 | `data.M`, `data.E` |
| $V,E$ | 节点集、有向边集 | `M`, `E` |
| $I,i$ | 任务集、任务索引 | `data.I` |
| $M,m,n$ | 可放置物理节点集 | `data.M` |
| $K,k$ | 资源类型（CPU/GPU/HBM） | `data.K` |
| $\Omega,\,\omega$ | 故障场景集 / 场景 realization | 论文符号；代码 `data.S` 与整数索引 $s$ 一一对应 |
| $S,s$ | 离散场景集 / 实现索引 | `data.S`（`scenario_mode=micro_pruned`）；$s\leftrightarrow\omega$，B4 $\|\Omega\|\approx 71$ |
| $F,\,F_\omega$ | 场景 $\omega$ 的链路故障边集 | $\|F_\omega\|\le k_{\max}$；$F_\omega=\emptyset$ 为全链路可用 |
| $\mathcal{P}_{uv}$ | 节点 $u$ 到 $v$ 的候选路径集 | `data.P_cand[u,v]` |
| $\mathcal{P}_{s_i m}^{in}$ | 任务 $i$ ingress：$s_i \to m$ 的路径 | `P_cand[task_src[i], m]` |
| $\mathcal{P}_{m t_i}^{out}$ | 任务 $i$ egress：$m \to t_i$ 的路径 | `P_cand[m, task_dst[i]]` |
| $M_i^{valid}$ | 任务 $i$ 可行放置节点集 | `valid_assign` 键 $(i,m)$ |

## 3.2 任务参数

| 符号 | 含义 | 代码 |
|:---|:---|:---|
| $s_i,t_i$ | 任务 $i$ 源、汇节点 | `task_src[i]`, `task_dst[i]` |
| $b_i$ | 任务流量需求（论文主线） | 代码暂分 $b_i^{in}, b_i^{out}$（`b_in[i]`, `b_out[i]`），待对齐 |
| $w_{ik}$ | 任务 $i$ 在资源 $k$ 上的需求权重 | `w[i][k]` |
| $\eta$ | 需求标定因子（survivability calibration） | CLI `--eta`，默认 1.3 |

## 3.3 网络参数

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

## 3.4 算力参数

| 符号 | 含义 | 代码 |
|:---|:---|:---|
| $C_{mk}^N$ | 节点 $m$ 资源 $k$ 名义容量 | `C_normal[m][k]` |
| $C_{mk,\omega}^{N}$ | 场景 $\omega$ 下有效容量 | `C_s[m][k][s]` |
| $\rho_{mk,\omega}$ | 场景降额乘子 | 由独立节点 / 资源故障事件生成；degraded 臂 aggregation $\times 0.4$ |
| $Z_{m,\omega}^{\mathrm{node}}$ | 节点 $m$ 可用指示（二元故障模型） | 可选；当前实现以 degraded / nominal 臂表达 |
| $D_{ref}$ | SF 短缺归一化分母 | Model C / posthoc：`compute_d_ref` $\equiv M_{ex}$ |
| $M_{ex}$ | SF 归一化上界；$D_{ref}=M_{ex}$ | `compute_d_ref(data)`（**非** Big-M 约束用） |
| $c_{mk}^N$ | 节点 $m$ 资源 $k$ 单位算力价格 | `p_price[m][k]` |

## 3.5 决策变量

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

## 3.6 Model M 相关

| 符号 | 含义 |
|:---|:---|
| $L_s$ | 场景 $s$ 货币化账单 |
| $\kappa$ | 送达短缺违约金系数（代码可拆分 `kappa_sum`, `kappa_max`, `kappa_sf`） |
| $\mathrm{Shortfall}_s$ | 场景送达缺口 |
| $\Gamma^M$ | Model M-C 货币 CVaR 预算 |

---

# 4. 主要建模公式

## 4.1 Per-task OD 路径设计

每任务 $i$ 独立路由：

$$
s_i \longrightarrow m \longrightarrow t_i
$$

**可行放置：**

$$
\mathcal{P}_{s_i m}^{in} \neq \emptyset,\quad \mathcal{P}_{m t_i}^{out} \neq \emptyset \quad \forall m \in M_i^{valid}
$$

**Hub 退化特例**（`routing_mode=hub`）：

$$
h \longrightarrow m \longrightarrow h,\quad s_i \equiv t_i \equiv h \;\text{（路径锚点）}
$$

实现：`b4_joint_data._build_valid_assign_per_task_od`；路径锚点 `duibi_metrics.teavar_flow_anchors(data, i)`。

## 4.2 放置与流量约束

**放置：**

$$
\sum_{m \in M_i^{valid}} y_{im} = 1,\qquad y_{im} \in \{0,1\}
$$

**流量（论文主线 — 统一 $b_i$）：**

$$
\sum_{p\in \mathcal{P}_{s_i m}^{in}} x_{imp}^{in} \le b_i\, y_{im},\qquad
\sum_{q\in \mathcal{P}_{m t_i}^{out}} x_{imp}^{out} \le b_i\, y_{im}
$$

可选要求 ingress / egress 计划流量一致：

$$
\sum_{p\in \mathcal{P}_{s_i m}^{in}} x_{imp}^{in}
=
\sum_{q\in \mathcal{P}_{m t_i}^{out}} x_{imp}^{out}
$$

或由最终送达变量 $\mathrm{Del}_{i,\omega}$ 形成瓶颈（§4.6）。

> **代码现状：** 暂用 $b_i^{in}, b_i^{out}$ 分别门控 ingress/egress（§4.3），与论文统一 $b_i$ 待对齐。

可选 hub 多样性（P0 实验）：至少 $\texttt{min\_off\_hub}$ 个任务不在 hub 上：

$$
\sum_{i} y_{ih} \leq |I| - \texttt{min\_off\_hub}
$$

## 4.3 Ingress / Egress 流量与场景送达耦合（path-up indicator）

**计划流量上界（放置门控）：**

$$
\sum_{p\in \mathcal{P}_{s_i m}^{in}} x_{imp}^{in} \leq b_i^{in}\, y_{im},\qquad
\sum_{q\in \mathcal{P}_{m t_i}^{out}} x_{imp}^{out} \leq b_i^{out}\, y_{im}
$$

$y_{im}=0$ 时 $x=0$；放置语义由上述约束表达，**不在送达耦合中重复 $y$**。

### 4.3.1 路径可用指示与场景送达（论文主线）

给定路径 $p$ 与场景 $\omega$，定义路径可用指示 $A_{p,\omega}\in\{0,1\}$（§4.5）。**场景下可送达流**：

**Ingress：**

$$
d_{imp,\omega}^{in} = A_{p,\omega}^{in}\, x_{imp}^{in}
$$

**Egress：**

$$
d_{imp,\omega}^{out} = A_{p,\omega}^{out}\, x_{imp}^{out}
$$

等价分段形式：

$$
A_{p,\omega}=1 \Rightarrow d_{imp,\omega}=x_{imp},\qquad
A_{p,\omega}=0 \Rightarrow d_{imp,\omega}=0
$$

即：**path-up 时**场景送达等于预分配流；**path-down 时**场景送达为 0；**不再需要 Big-M 送达耦合**。

实现：`cvar_compare.add_scenario_delivery_coupling()`。因 $A_{p,\omega}$ 为参数 / 预计算 indicator，对每个 $(i,m,p,\omega)$ 施加等式 $d=x$ 或 $d=0$（Model C / `build_teavar_sla_cvar_model` 共用）。

若实现中为线性形式 $d_{imp,\omega}\le A_{p,\omega}x_{imp}$ 且目标含送达奖励或最大化 delivery，最优解在可用路径上会把 $d$ 推至上界，与等式语义一致；**论文方法节优先写** $d_{imp,\omega}=A_{p,\omega}x_{imp}$。

**三种路径–放置组合行为（非故障场景编号）：**

1. **$A_{p,\omega}=1$ 且 $y_{im}=1$：** $d=x$。
2. **$A_{p,\omega}=1$ 且 $y_{im}=0$：** 由 $x\le y\cdot b$ 得 $x=0$，故 $d=0$。
3. **$A_{p,\omega}=0$：** 强制 $d=0$，与 $y$ 无关。

**旧版（已废弃于主线）：** Big-M 三不等式 $d\le M y,\; d\ge x-M(1-y)$ 等。**不得**再作为论文方法主线描述。

### 4.3.2 虚拟源/汇接入瓶颈（可选）

实现：`add_teavar_virtual_bottleneck_constraints(m, data, y, del_in, del_out, hub)`。

**作用：** 即使物理 WAN 路径全通（$A_{p,\omega}=1$），每个场景下任务 $i$ 的 ingress/egress **总送达量**仍受虚拟接入可用率上界：

$$
R^{in}(i,\omega) = \sum_{m,p} d_{imp,\omega}^{in} \;\le\; \sum_m b_i^{in}\, y_{im}\, \sigma^{vs}_{m,\omega}
$$

$$
R^{out}(i,\omega) = \sum_{m,q} d_{imp,\omega}^{out} \;\le\; \sum_m b_i^{out}\, y_{im}\, \sigma^{vt}_{m,\omega}
$$

**例子：** $\sigma^{vs}=0.99$ 时，物理路径 100% 通，接入层仍最多送达 99% 需求 → 防止「全放 hub + 空路径 → CVaR=0」退化。

**per-task OD：** $R^{in/out}$ 按 `teavar_flow_anchors(data,i)` 的 $(s_i,t_i)$ 聚合路径，不再用全局 hub 锚点。

**触发条件：** `data.sigma_vs` 非空 **且** 未启用 UMCF 显式虚拟边（`umcf_virtual_nodes=True` 时虚拟边已在 `path_up`/`sigma` 中表达接入语义，**不重复**施加该瓶颈）。

## 4.4 链路容量约束

**待确认：** 当前主线 Model C（`teavar_framework_models.build_teavar_model_c`）**未显式**施加 $\sum_{e} \text{flow}_e \leq B_e$ 型物理链路容量上界；故障影响主要通过 $Z_{e,\omega}^{\mathrm{link}}$、$A_{p,\omega}$ 与 `path_up` 阻断不可达路径上的送达。

_legacy 模块 `teavar_cete.py` / `teavar_cete01.py` 中存在 `load_e <= B[e]`，但与 P0 frontier 主路径是否一致 **待确认**。

若论文需要显式链路容量，须在方法章节单独说明所采用代码路径。

## 4.5 故障模型与路径可用率

**论文主线：** 每条链路与每个节点 / 资源维具有 **独立故障概率**；场景集合 $\Omega$ 由这些独立事件 **生成**（完整枚举、Monte Carlo、top-risk pruning 或 **micro-pruned scenario generation**），为控制规模得到有限代表集。**不是**手工 $s=0,1,2$（正常 / 链路故障 / 算力降额）三状态；legacy `macro3` 仅为 Phase B+ 诊断 fixture（§1.4 脚注）。

### 4.5.1 链路独立 Bernoulli 故障

$$
\Pr(Z_{e,\omega}^{\mathrm{link}}=0)=p_e^{\mathrm{link}},\qquad
\Pr(Z_{e,\omega}^{\mathrm{link}}=1)=1-p_e^{\mathrm{link}}
$$

不同链路 **相互独立**。micro_pruned 实现：枚举 $|F_\omega|\le k_{\max}$ 的故障边集，$Z_{e,\omega}^{\mathrm{link}}=0$ 当且仅当 $e\in F_\omega$；$q_\omega=\prod_{e\in F}p_e^{\mathrm{link}}\prod_{e\notin F}(1-p_e^{\mathrm{link}})$，再经 $\pi_{\min}$ 剪枝与 renormalize（B4：$p_e^{\mathrm{link}}\in[1.5\times 10^{-3},4.5\times 10^{-3}]$，38 边，$\|\Omega\|\approx 71$）。

### 4.5.2 节点 / 算力场景容量

算力维独立于链路：$C_{mk,\omega}^{N}=\rho_{mk,\omega}C_{mk}^{N}$，$\rho_{mk,\omega}$ 由 **独立** nominal / degraded 事件生成（当前：aggregation degraded 臂 $\rho=0.4$，先验 0.1）。与链路场景做 Cartesian 积后再剪枝 / renormalize → `data.prob[s]`。

### 4.5.3 路径可用 $A_{p,\omega}$ 与 path_up

路径 $p$ 的链路集合 $E(p)$：

$$
A_{p,\omega}=\prod_{e\in E(p)} Z_{e,\omega}^{\mathrm{link}}
=\min_{e\in E(p)} Z_{e,\omega}^{\mathrm{link}}
$$

* 任一路径链路故障 → $A_{p,\omega}=0$；
* 全部链路可用 → $A_{p,\omega}=1$。

代码 `duibi_metrics.path_up` 实现 **binary path-up indicator** $\mathbb{1}[\forall e\in p: Z_{e,\omega}^{\mathrm{link}}=1]$，**不**在 MILP 内对 $\sigma$ 做连乘期望（连乘可用于路径先验可靠性，见 TEAVAR 类分析）。$u=v$ 时空路径 `[]` 返回 `True`（零 hop 视为始终可用）。

**路径价（与故障独立）：**

$$
\tau_p = \sum_{e\in p} \pi_e^{\mathrm{price}}
$$

在 uniform 价下，合法 colocated zero-hop 可导致同 placement 下多最优 $x$ 分配（Phase C-0，§9.6）。

## 4.6 场景送达量与 SLA 风险（论文主线）

场景 $\omega$ 下，任务 $i$ 的**最终送达量** $\mathrm{Del}_{i,\omega}$ 受 ingress / egress 两段共同限制：

$$
\mathrm{Del}_{i,\omega} \le
\sum_{m\in M_i^{valid}}\sum_{p\in \mathcal{P}_{s_i m}^{in}} d_{imp,\omega}^{in}
$$

$$
\mathrm{Del}_{i,\omega} \le
\sum_{m\in M_i^{valid}}\sum_{q\in \mathcal{P}_{m t_i}^{out}} d_{imp,\omega}^{out}
$$

$$
0 \le \mathrm{Del}_{i,\omega} \le b_i
$$

**总需求与总送达：**

$$
D = \sum_{i\in I} b_i,\qquad
\mathrm{Del}_{\omega} = \sum_{i\in I} \mathrm{Del}_{i,\omega}
$$

**网络 SLA 损失率（论文主线定义）：**

$$
R_{\omega}^{SLA} = 1 - \frac{\mathrm{Del}_{\omega}}{D}
\quad\text{（等价于}\quad
R_{\omega}^{SLA} = \frac{D - \mathrm{Del}_{\omega}}{D}\text{）}
$$

**期望送达：**

$$
\mathbb{E}[\mathrm{Del}] = \sum_{\omega\in\Omega} q_\omega \sum_{i\in I} \mathrm{Del}_{i,\omega}
$$

**CVaR 线性化** 对 $R_\omega^{SLA}$ 使用 §4.8 公式（$u_\omega^{SLA}\ge R_\omega^{SLA}-\zeta^{SLA}$）。

### 代码实现层（待对齐，非论文主线）

当前 `metrics_posthoc.compute_sla_loss_by_scenario` 与 MILP 内 SLA CVaR 仍采用 **per-task max loss**（分 $b_i^{in/out}$ 的 ingress/egress 分量再取 max）。该口径与上式聚合 $R_\omega^{SLA}$ **不等价**；formal PASS 的 fixture CSV 基于前者验收。**不得**将 per-task max loss 写成论文唯一 SLA 定义；论文方法节以聚合 $R_\omega^{SLA}$ 为准，代码对齐列为后续工作。

## 4.7 算力容量、短缺与 SF CVaR

**节点资源占用：**

$$
U_{mk} = \sum_{i\in I} y_{im}\, w_{ik}
$$

**场景有效容量：**

$$
C_{mk,\omega}^{N} = \rho_{mk,\omega}\, C_{mk}^{N}
$$

**算力 shortfall：**

$$
E_{mk,\omega} \ge U_{mk} - C_{mk,\omega}^{N},\qquad E_{mk,\omega} \ge 0
$$

**场景 SF 风险（论文主线）：**

$$
R_{\omega}^{sf} = \frac{\sum_{m\in M}\sum_{k\in K} E_{mk,\omega}}{D_{ref}}
$$

**归一化分母（当前已验证 fixture）：**

$$
D_{ref} = M_{ex} = \max\Big( \max_{m,k}\sum_i w_{ik} + 1,\; \max_{m,k,\omega} C_{mk,\omega}^{N} + 1,\; 1 \Big)
$$

代码：`metrics_posthoc.compute_d_ref`。

> per-resource $D_{ref,k}$ 为候选改进，**不是**当前已验证 SSOT（§14.3）。cap3 R&U SF 线性化已在代码中，**fixture 尚未重验收**。

**CVaR 线性化：**

$$
\mathrm{CVaR}^{sf} = \zeta^{sf} + \frac{1}{1-\alpha}\sum_{\omega\in\Omega} q_\omega u_\omega^{sf}
$$

$$
u_\omega^{sf} \ge R_\omega^{sf} - \zeta^{sf},\qquad u_\omega^{sf} \ge 0
$$

代码中 cap3 `add_compute_sf_cvar_ru` 为 R&U 纯连续实现（无 $w\_exc$）；**已并入代码主线，但 fixture CSV 验收时尚未以 micro_pruned + copo_v1 重跑确认**（§14.3）。

## 4.8 CVaR 线性化

置信水平 $\alpha = \beta_N$（代码默认 **0.95**）。对任意场景损失 $\{R_\omega\}$（$R_\omega^{SLA}$ 或 $R_\omega^{sf}$）：

$$
\mathrm{CVaR}_\alpha(R) = \zeta + \frac{1}{1-\alpha} \sum_{\omega\in\Omega} q_\omega u_\omega
$$

$$
u_\omega \geq R_\omega - \zeta,\quad u_\omega \geq 0
$$

**SLA 通道：**

$$
\mathrm{CVaR}^{SLA} = \zeta^{SLA} + \frac{1}{1-\alpha}\sum_{\omega\in\Omega} q_\omega u_\omega^{SLA} \le \Gamma_{SLA}
$$

$$
u_\omega^{SLA} \ge R_\omega^{SLA} - \zeta^{SLA},\quad u_\omega^{SLA} \ge 0
$$

**SF 通道：**

$$
\mathrm{CVaR}^{sf} = \zeta^{sf} + \frac{1}{1-\alpha}\sum_{\omega\in\Omega} q_\omega u_\omega^{sf} \le \Gamma_{sf}
$$

Post-hoc 评估用 `compute_discrete_cvar`。**当前 fixture 验收** 基于代码 per-task max SLA loss；**论文方法节** 以 $R_\omega^{SLA}$ 为准（§4.6）。

## 4.9 成本设计

$$
C^{money} = C^{comp} + C^{bw},\qquad
C^{comp} = \sum_{i,m,k} c_{mk}^{N}\, w_{ik}\, y_{im}
$$

**带宽费（论文主线 — Copo-style / role_transit / copo_v1）：**

$$
\pi_e = \mathrm{scale}\cdot \phi(\mathrm{role}[u],\mathrm{role}[v]),\qquad
\tau_p = \sum_{e\in p}\pi_e
$$

$$
C^{bw} =
\sum_{i,m,p} \tau_p x_{imp}^{in}
+
\sum_{i,m,q} \tau_q x_{imp}^{out}
$$

| 配置 | 定位 |
|:---|:---|
| **Copo-style / role-transit（copo_v1）** | **论文主线定价** |
| **uniform**（$\pi_e=1$） | Phase B+ / formal P0 gate fixture 与消融 |
| **inverse_capacity** | legacy / 旧实验，**不是**当前论文主线 |

**论文图表轴语义（Phase C-0 结论）：**

| 轴 | 用什么 | 说明 |
|:---|:---|:---|
| **风险轴** | `posthoc_cvar_sla` / `posthoc_cvar_sf` | **可先定稿** |
| **成本轴** | $C_{report}^{money}$（Phase C-1 secondary costing） | **不得**直接用 raw `monetary_cost` 作最终论文 cost–risk 图横轴 |
| 审计 | raw `monetary_cost` | 保留于 CSV，仅供诊断 |

**不得**用 `obj_val` 代替任何成本轴。

---

# 5. Model A：加权双 CVaR 模型

$$
\min \;
C^{money}
+ \lambda_{SLA}\,\mathrm{CVaR}^{SLA}
+ \lambda_{sf}\,\mathrm{CVaR}^{sf}
- \omega_{del}\,\mathbb{E}[\mathrm{Del}]
$$

其中

$$
\mathbb{E}[\mathrm{Del}] = \sum_{\omega\in\Omega} q_\omega \sum_i \mathrm{Del}_{i,\omega}
$$

**用途：** 扫描 $(\lambda_{SLA},\lambda_{sf})$ 探索 Pareto 地图；P0 Γ 网格的基准 SLA/SF 水平由 Model A（$\lambda_{SLA}=5,\lambda_{sf}=1$）校准（`run_gamma_frontier._default_gamma_grid`）。

---

# 6. Model C：风险预算模型（risk-budgeted cost-delivery）

**当前代码语义（不是纯 $\min C^{money}$ epsilon-constraint）：**

$$
\min \; C^{money} - \omega_{del}\,\mathbb{E}[\mathrm{Del}]
$$

$$
\text{s.t.}\quad \mathrm{CVaR}^{SLA} \leq \Gamma_{SLA},\qquad
\mathrm{CVaR}^{sf} \leq \Gamma_{sf}
$$

以及相同的 placement、routing、scenario delivery、capacity 与 CVaR 约束。

### 必须强调的字段语义

| 字段 | 含义 |
|:---|:---|
| `monetary_cost` / `cost` | raw $C^{money}=C^{comp}+C^{bw}$；**审计用**，非最终论文 cost 轴 |
| `C_report_money`（Phase C-1） | 二阶段 secondary costing 后的 reporting cost |
| `obj_val` / `objective` | $C^{money} - \omega_{del}\mathbb{E}[\mathrm{Del}]$ |
| `posthoc_cvar_sla/sf` | 求解后离散 CVaR，**论文风险轴** |

1. Model C **不是**纯 $\min C^{money}$ 的 cost epsilon-constraint；
2. **`obj_val` $\neq$ `monetary_cost`**；
3. 放宽 $\Gamma_{sf}$ 时 raw monetary_cost **可能上升**，不是实现 bug；
4. 须 posthoc + Pareto 过滤后再绘图；**不得**用 raw `monetary_cost` 作最终 cost 轴（§4.9）。

---

# 7. Model A 与 Model C 的关系

Model A 和 Model C **共享同一套底层 MILP 约束**。

| 维度 | Model A | Model C |
|:---|:---|:---|
| 语言 | 权重 $\lambda_{SLA},\lambda_{sf}$ | 预算 $\Gamma_{SLA},\Gamma_{sf}$ |
| 工程解释 | 探索性 — **画地图** | 合同式 — **按风险预算选点** |
| $\lambda$ vs $\Gamma$ | $\lambda$ 难直接解释 | $\Gamma$ 更符合工程合同 |
| 前沿提取 | 需 posthoc + Pareto | 需 posthoc + Pareto |

**Pareto 支配示例（Phase B+ gate fixture，posthoc 三元组；成本列为 raw monetary，仅作 fixture 参考）：**

$(1429.16,\; 1.00,\; 0.0209)$ **支配** $(1717.93,\; 1.00,\; 0.0377)$

**为何不能直接用求解器目标排序：** 因 $\omega_{del}\mathbb{E}[\mathrm{Del}]$ 项；**论文前沿必须基于 posthoc 风险 + reporting cost（Phase C-1）做 Pareto 过滤**。

---

# 8. Model M / Model M-C

**动机：** Model A 中 $\lambda_{SLA},\lambda_{sf}$ 缺乏直接货币解释；Model M 用违约金 $\kappa$ 将 shortfall 货币化。

**场景账单：**

$$
L_\omega = C^{comp} + C_{\omega}^{bw} + \kappa \cdot \mathrm{Shortfall}_{\omega}
$$

$$
\mathrm{Shortfall}_{\omega} = D - \sum_i \mathrm{Del}_{i,\omega}
$$

**Model M：**

$$
\min \mathrm{CVaR}_\alpha(L_\omega)
$$

**Model M-C：**

$$
\min \mathbb{E}[L_\omega]\quad \text{s.t.}\quad \mathrm{CVaR}_\alpha(L_\omega) \leq \Gamma^M
$$

**定位：** 不替代 A/C 主线；推荐正文半小节 + 附录完整推导。

---

# 9. 本周主要结果

## 9.1 Per-task OD 最小闭环完成

| 模块 | 改动要点 |
|:---|:---|
| `b4_joint_data.py` | OD 任务选取、per-task `valid_assign`、`task_src/dst` |
| `duibi_metrics.py` | `teavar_flow_anchors(data,i)`、per-task `bandwidth_cost_expr` |
| `cvar_compare.py` | per-task 流锚点、虚拟瓶颈约束 |
| `main.py` | CLI 路由模式切换 |
| `tests/test_per_task_od.py` | smoke 测试 |

Hub 模式保持兼容；per-task smoke **通过**（具体用例数以 CI 日志为准，**待确认**）。

## 9.2 Phase B++ 诊断结果

基于 `results/temp_smoke_posthoc_gamma/model_c_gamma_diagnostic.csv`：

| 结论 | 证据 |
|:---|:---|
| Model C 目标 $= C^{money} - \omega_{del}\mathbb{E}[\mathrm{Del}]$ | `obj_reconstruction_error` $\approx 10^{-12}$ |
| `reported_cost` $\equiv$ `monetary_cost` | 分解列 `compute_cost + bandwidth_cost` |
| `obj_val` $\neq$ `monetary_cost` | 当 $\omega_{del}=1$ 且 $\mathbb{E}[\mathrm{Del}]>0$ |
| 放宽 $\Gamma_{sf}$ 后 monetary 上升 | 同一 placement 下更高 SF 预算允许更高带宽/送达组合 |

## 9.3 Phase B+++ 工具链完成

| 组件 | 路径 |
|:---|:---|
| Pareto 过滤 | `pareto_frontier.py` |
| Post-hoc CVaR | `metrics_posthoc.py` |
| 行 enrichment | `frontier_reporting.py` |
| Formal 验收 | `scripts/formal_p0_acceptance.py`（V-1~V-5） |
| Pareto 标注 | `scripts/annotate_frontier_pareto.py` |
| 指标说明 | `results/README_metrics.md` |

## 9.4 Phase B+ 25 点 gate 验收（§14.2 已验证 fixture）

**配置：** uniform pricing + per_task_od + $D_{ref}=M_{ex}$。**不是**最终论文主图（缺 copo_v1、micro_pruned、reporting cost）。

- `results/temp_smoke_posthoc_gamma/uniform_frontier_b4_tasks8_posthoc_gamma.csv`
- `results/p0_uniform_v2/p0_gamma_frontier_b4_tasks8_gated.csv`（Pareto 标注副本）

**Formal acceptance：** **PASS**

| 指标 | 数值 |
|:---|:---|
| distinct_triples | 6 |
| non_dominated_distinct | **4** |
| dominated_grid_points | 12 |
| posthoc SLA 档数 | 3（0.8 / 0.9 / 1.0） |
| posthoc SF 档数 | 2（0.0209 / 0.0377） |

**四个 non-dominated 三元组** $(C^{money},\; \mathrm{posthoc\_SLA},\; \mathrm{posthoc\_SF})$：

1. $(1429.16,\; 1.00,\; 0.0209)$
2. $(2330.94,\; 0.90,\; 0.0209)$
3. $(2316.46,\; 0.90,\; 0.0377)$
4. $(3009.99,\; 0.80,\; 0.0209)$

**被支配剔除示例：**

- $(1717.93,\; 1.00,\; 0.0377)$ ← 被 $(1429.16,\; 1.00,\; 0.0209)$ 支配
- $(3054.20,\; 0.80,\; 0.0377)$ ← 被 $(3009.99,\; 0.80,\; 0.0209)$ 支配

**说明：** 上述为 **§14.2 已验证 fixture**；风险结构已被 formal P0 复现，**不是**最终论文主图。

## 9.5 Formal P0 rerun 当前状态

### 9.5.1 历史 FAIL 归档（NON-SSOT，已解释）

**归档文件：** `p0_gamma_frontier_b4_tasks8_NON_SSOT_sf_per_resource.csv`、`p0_gamma_frontier_b4_tasks8_grid5_sf_per_resource.csv`

| 现象 | 根因 |
|:---|:---|
| posthoc SF 单档 $\approx 0.004$ | 未提交分支中 `compute_sf_resource_refs` 替换 $D_{ref}=M_{ex}$，$\Gamma_{sf}$ 过紧 |
| placement 偏移（如 task 7: 4→5） | 同上 |
| formal acceptance FAIL | 同上 |

**不得**用于论文图或 SSOT 引用。

### 9.5.2 fixture 风险结构候选（$D_{ref}=M_{ex}$，uniform，formal PASS）

**文件：** `results/p0_uniform_v2/p0_gamma_frontier_b4_tasks8.csv`

| 指标 | 数值 |
|:---|:---|
| FORMAL OVERALL | **PASS** |
| posthoc SLA 档数 | 3 |
| posthoc SF 档数 | 2 |
| non-dominated distinct triples | **6** |
| Phase B+ 四类风险结构 | **已复现** |

| 对比项 | Phase B+ smoke | fixture 候选 |
|:---|:---|:---|
| $(1.0,0.03)$ posthoc_sf | 0.0209 | 0.0209（一致） |
| $(1.0,0.03)$ placement | `…\|7:4` | `…\|7:4`（一致） |
| $(1.0,0.03)$ monetary_cost | 1429.16 | **160.96**（**cost 轴差异，见 §9.6**） |

**定位：** 可作为 **posthoc 风险结构 SSOT 候选**（fixture 配置）；**不是**最终论文 cost–risk 图 SSOT（缺 copo_v1、reporting cost、micro_pruned 重跑）。

## 9.6 Phase C-0 cost-axis determinacy（**已完成**）

**产物：** `results/p0_uniform_v2/cost_axis_diagnosis.md`、`cost_axis_diagnosis.json`

| 检查项 | 结论 |
|:---|:---|
| path construction | **无 bug**（$u\ne v$ 空路径 = 0） |
| zero-hop local path | **合法** colocated（$u=v$） |
| 非空路径 $\tau_p=0$ | **0** |
| delivery-flow coupling | **正常** |
| bandwidth cost 漏算 | **否** |
| posthoc risk / placement vs smoke | **对齐** |
| raw monetary_cost vs smoke | **不一致** — 固定 $y$ 下 $x$ 多最优 |

**结论：** 当前 CSV **风险结构可用**；raw `monetary_cost` **不适合**作最终论文 cost 轴 → 进入 **Phase C-1**（§10）。

---

# 10. 下一步主线：Phase C-1 secondary costing

Phase C-0 已闭环。一阶 Model C 在固定 placement 与 achieved delivery 下，$x$ 流可能多最优 → **raw bandwidth cost 不唯一**。

**固定：** $y$、achieved delivery、posthoc 风险结构、场景与约束。**再解** $\min C^{bw}$，得：

$$
C_{report}^{money} = C^{comp}(y) + C_{min}^{bw}
$$

* 不改 Model C 主 MILP 语义；不改 placement / posthoc SLA / SF；
* **只稳定论文 cost 轴**；raw `monetary_cost` 保留审计。

**并行（论文目标 pipeline，尚未 formal PASS）：**

1. micro_pruned + copo_v1 重跑 formal P0；
2. SLA 代码对齐聚合 $R_\omega^{SLA}$（§4.6）；
3. `scripts/audit_scenarios.py` 场景审计；
4. posthoc 风险维 Pareto 图；
5. $\omega_{del}=0$ sensitivity（可选）。

---

# 11. 仍需补全的信息

| # | 项目 | 状态 |
|:---|:---|:---|
| 1 | 可复现 commit hash | `8b78f819` + dirty，**待确认** |
| 2 | Gurobi / Python / 硬件环境表 | **待确认** |
| 3 | $A_{p,\omega}$ vs `path_up` | **已确认一致** |
| 4 | $D_{ref}=M_{ex}$ 实例数值 | **待导出** |
| 5 | posthoc vs MILP CVaR 逐场景 diff | **待完成** |
| 6 | 论文 Pareto 图 | 风险维可先定稿；cost 轴待 C-1 |
| 7 | **Phase C-1 secondary costing** | **待实现** |
| 8 | micro_pruned + copo_v1 formal 重跑 | **待完成** |
| 9 | SLA 聚合 $R_\omega^{SLA}$ 代码对齐 | **待完成** |
| 10 | CSV 升级最终 SSOT | **风险维：fixture 候选；cost 维：待 C-1** |

---

# 14. 实验与结果状态主线

## 14.1 论文目标主线

最终论文实验应收敛于：per-task OD；copo_v1 role-transit；micro-pruned $\Omega$；path-up 送达；聚合 $R_\omega^{SLA}$；Model A/C 双 CVaR + posthoc + Pareto；$C_{report}^{money}$（C-1 通过后）。

## 14.2 当前已验证 fixture / gate baseline

B4×8、`per_task_od`、**uniform** pricing、$D_{ref}=M_{ex}$、25 点 Γ 网格 formal **PASS**；posthoc SLA 3 档、SF 2 档（0.0209 / 0.0377）；gate non-dominated = 4，full grid = 6。**证明双 CVaR 风险结构存在**；**不是**最终论文主图（uniform 定价、raw cost 不唯一、未 micro_pruned+copo 重跑）。

## 14.3 NON-SSOT（不得写成已验证主结果）

per-resource $D_{ref,k}$；R&U/cap3 **代码已落地但 fixture 未重验收**；micro_pruned **目标未 formal PASS**；DAG chain MVP；raw `monetary_cost` 作 cost 轴；`inverse_capacity`；NON-SSOT SF CSV。

## 14.4 禁止出现的错误口径

uniform 是论文主线；$s=0,1,2$ 三状态；hub 是主模型；Model C 是纯 $\min cost$；per-resource $D_{ref,k}$ 已是 SSOT；micro_pruned/copo 已 formal PASS；raw monetary_cost 可直接作 cost 轴；Phase B++++ 未完成；Big-M 送达耦合为主线。

---

# 附录 A：实验配置摘要

## A.1 论文目标配置（§14.1）

| 参数 | 值 |
|:---|:---|
| routing_mode | per_task_od |
| pricing_profile | **copo_v1** / role_transit |
| scenario_mode | **micro_pruned** |
| $D_{ref}$ | $M_{ex}$ |
| SLA | 聚合 $R_\omega^{SLA}$（目标；代码待对齐） |

## A.2 当前已验证 fixture（§14.2）

| 参数 | 值 |
|:---|:---|
| pricing_profile | **uniform** |
| scenario_mode | legacy **macro3** |
| 产物 | `p0_uniform_v2/p0_gamma_frontier_b4_tasks8.csv` 等 |

## A.3 NON-SSOT 归档

per-resource $D_{ref}[k]$；`*_NON_SSOT_sf_per_resource.csv`；`inverse_capacity` 定价。

任务 OD 见 `results/temp_smoke_posthoc_gamma/README_RECONSTRUCTED_CONFIG.md`。

---

# 附录 B：实验文件状态表

| 文件 | 状态 |
|:---|:---|
| `results/p0_uniform_v2/p0_gamma_frontier_b4_tasks8.csv` | **fixture 风险结构 SSOT 候选**（uniform）；cost 维待 C-1 |
| `results/p0_uniform_v2/p0_gamma_frontier_b4_tasks8_gated.csv` | Phase B+ gate baseline，仍有效 |
| `p0_gamma_frontier_b4_tasks8_NON_SSOT_sf_per_resource.csv` | **NON-SSOT**，per-resource SF 实验污染归档 |
| `p0_gamma_frontier_b4_tasks8_grid5_sf_per_resource.csv` | **NON-SSOT**，实验记录 |
| `results/p0_uniform_v2/parity_report.json` | Phase B++++ parity 诊断报告 |
| `results/p0_uniform_v2/parity_matrix/summary.json` | 四点最小矩阵诊断结果 |
| `results/p0_uniform_v2/cost_axis_diagnosis.md` | Phase C-0 cost 轴诊断（方案 2） |

---

# 附录 C：关键工程文件索引

| 类别 | 路径 |
|:---|:---|
| 数据加载 | `b4_joint_data.py` |
| 场景生成 | `scenario_generator.py`（`build_link_scenarios`, `combine_link_compute_scenarios`） |
| Model C | `teavar_framework_models.py` |
| 指标 / 带宽费 | `duibi_metrics.py` |
| Post-hoc CVaR | `metrics_posthoc.py` |
| Frontier 扫描 | `run_gamma_frontier.py` |
| Cost 轴诊断 | `scripts/diagnose_cost_axis.py` |
| 指标 README | `results/README_metrics.md` |

---

# 12. 是否建议用于组会 / 导师汇报

**建议使用本版。**

**可汇报：** per-task OD、Model C 语义分离、posthoc 风险口径、Pareto 过滤、Phase B++++ parity 闭环；fixture 上 formal acceptance **PASS**（风险结构 6 non-dominated triples，SLA/SF 各 2–3 档）。

**须明确区分三层（§14）：**

1. **论文目标主线** — copo_v1 + micro_pruned + 聚合 SLA + reporting cost；
2. **已验证 fixture** — uniform + gate PASS，证明风险结构；
3. **NON-SSOT** — per-resource SF、raw cost 轴等。

**下一步主线是 Phase C-1 secondary costing**，不是继续修风险模型 parity。

---

**报告结束**
