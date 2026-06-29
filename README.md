# TEAVAR_python

本仓库包含 **TEAVAR 论文 WAN 风险模型复现**（隧道分流 + CVaR）、**算力–网络联合放置的对比 MILP**（`duibi` / `cvar_compare`）、以及 **`data/B4` 数据集上的 joint 入口**（`main.py --mode joint`）。优化器为 **Gurobi**。

详细数学定义见独立文档：**[建模公式说明.md](./建模公式说明.md)**。

---

## 环境依赖

| 组件 | 用途 |
|------|------|
| Python 3.x | 运行脚本 |
| `gurobipy` + Gurobi 许可证 | 全部 MILP |
| `numpy` | 数据读取、矩阵 |
| `scipy` | `util.py`（仅 `--mode teavar` 经 `main` 导入时） |
| `networkx` | `parsers.get_tunnels`（仅论文 TEAVAR 路径需 K 短路） |

`--mode joint` 与 `cvar_compare` / `duibi` 可在未安装 `scipy` / `networkx` 时运行（`parsers` 中 `networkx` 为延迟导入）。

---

## 目录结构（核心）

```
├── main.py                     # 统一入口：teavar（论文） / joint（B4 + 新 CVaR）
├── TEAVAR_Gurobi.py            # TEAVAR 隧道分流 MILP
├── parsers.py                  # 拓扑、需求、tunnels
├── util.py                     # Weibull 链路故障、子场景
│
├── duibi.py                    # 玩具数据 + 单层 CVaR / KKT / ε-约束 / Copo 风格模型
├── duibi_metrics.py            # 解后指标（利用率、送达、SLA 损失等）+ 链路定价
│
├── cvar_compare.py             # ★ physical vs teavar_sla 并排 + build_teavar_sla_cvar_model
│                               #   + 虚拟接入瓶颈 + 链路名义容量 + 算力 SF CVaR（RU 纯连续）
├── teavar_framework_models.py  # ★ TEAVAR 视角 SLA CVaR 与 duibi 式 Model A–D 四种架构对齐
│                               #   (加权/KKT Indicator/ε-约束/McCormick)
├── bilevel_teavar_models.py    # ★ L0 双层 baseline：慢层枚举 placement → 快层 routing → post-hoc CVaR
├── l2_full_models.py           # ★ L2 模块：fixed-y F1 primal/dual 校验 + embedded-y 全变量
│                               #   + F1 strong-duality exact McCormick
│
├── b4_joint_data.py            # ★ B4 及多拓扑 → 与 duibi 同构的联合数据对象
│                               #   支持 hub / per_task_od / umcf_global / umcf_per_task 路由模式
│
├── toy_instances.py            # 确定性小规模玩具算例（Toy-SLA/Toy-SF/Toy-Combined/Toy-ComponentRisk）
│                               #   供 exact-enumeration 验证
├── toy_te_data.py              # ★ ToyTE：端到端两阶段多路径流量工程玩具数据集
│                               #   2 任务 × 3 算力节点 × (3 ingress + 3 egress) 路径 × 4 场景
├── toy_two_task_independent_data.py  # ★ 独立组件故障玩具：2 任务 × 3 节点 × 23 组件 × 产品分布
├── validate_toy_te.py          # ToyTE 自动完整性验证器（25+ 检查项）
├── component_scenario_generator.py   # 独立组件故障场景生成器（Bernoulli 乘积 → 512/8.4M 场景）
│
├── m0_instances.py             # M0 快层枚举实例（exhaustive placement 遍历）
├── m0_models.py                # M0 快层路由 MILP（给定 y 的 x/d 子问题）
├── exact_enumeration_solver.py # 穷举 placement → 解 routing → 算 CVaR（full enumeration baseline）
│
├── metrics_posthoc.py          # 事后 CVaR 计算（从解提取 y，重算 SLA/SF CVaR）
├── pareto_frontier.py          # Pareto 前沿构建（Model C ε-扫描 + Model A λ-扫描）
├── p0_calibration.py           # η 标定（需求放大 scale 搜索使得 feasible 条件触发）
│
├── generate_compute_resources.py   # 自动生成算力 CSV（按度中心性分 core/aggregation/edge）
├── experiment_report.py            # 实验报告生成（图表 + 表格 + LaTeX）
├── progressive_pipeline.py         # progressive 实验流水线（多轮校准）
│
├── run_gamma_frontier.py           # ★ Γ 前沿扫描脚本（Model C）
├── run_routing_mode_ablation.py    # 路由模式消融实验
├── run_b4_main_table.py            # B4 主表生成
├── run_p0_sweep.py / run_p0_diag_tasks12.py  # P0 λ/Γ 扫参
├── plot_duibi_paper_narrative.py   # 论文叙事图
├── plot_duibi_umcf_sweep.py        # UMCF 扫参图
├── summarize_p0_results.py         # P0 结果汇总
│
├── data/B4/            # 拓扑、需求、paths、node_compute_resources.csv
├── data/Abilene/       # 同上（6 节点）
├── data/ATT/           # 同上（25 节点）
├── data/Sprint/        # 同上（11 节点）
├── data/IBM/           # 同上（18 节点）
├── data/Nextgen/       # 同上（10 节点）
├── data/XNet/          # 同上（29 节点）
├── data/Custom/        # 自定义小型拓扑
├── data/Custom2/       # 自定义小型拓扑
│
├── docs/
│   ├── model_ac_建模说明.md       # ★ Model A/C 完整数学定义（符号、约束、CVaR 公式）
│   ├── toy_dataset_design.md      # ★ ToyTE 数据集设计文档
│   ├── l2_full_design.md          # L2 双层嵌入设计
│   ├── m0_m1_m2_建模说明.md       # M0/M1/M2 建模与校验
│   └── exact_validation.md        # Exact enumeration 验证
│
├── model_ac_component_risk_release/  # ★ 独立发布版（剥离 duibi 依赖）
│   ├── cvar_compare.py
│   ├── teavar_framework_models.py
│   ├── duibi_metrics.py
│   ├── metrics_posthoc.py
│   ├── exact_enumeration_solver.py
│   ├── component_scenario_generator.py
│   ├── toy_instances.py
│   ├── teavar_data.py
│   └── tests/   (test_exact_validation / test_combined_conflict_toy / test_combined_component_risk_toy)
│
├── tests/
│   ├── test_smoke.py                 # 冒烟测试
│   ├── test_per_task_od.py           # per_task_od 路由模式测试
│   ├── test_umcf_per_task.py         # UMCF per-task 测试
│   ├── test_routing_mode_ablation.py # 路由模式消融测试
│   ├── test_p0_experiment.py         # P0 实验测试
│   └── test_l2_f1_dual.py            # L2 F1 对偶验证测试
│
├── scripts/
│   ├── p0_acceptance.py              # P0 验收脚本
│   ├── run_l2_f1_dual_check.py       # L2 F1 对偶检查
│   ├── audit_datasets.py             # 数据集审计
│   └── _check_assign_milp.py / _check_compute_assign.py
│
├── reports/ / results/ / output/ / figures/   # 实验结果、图表输出
└── 建模公式说明.md      # ★ 各函数对应公式（主文档外单开）
```

### 核心文件详细说明

#### 数据准备层

| 文件 | 设计思路 | 核心内容 |
|:--|:--|:--|
| **`b4_joint_data.py`** | 将任意拓扑（B4/Abilene/ATT/…）转为与 MILP 同构的数据对象。支持 5 种路由模式：`hub`（径向）、`per_task_od`（每任务独立 OD）、`umcf_global`（全局 UMCF 虚拟源汇）、`umcf_per_task`（每任务独立 UMCF）、`dag`（占位）。自动检测 1-based/0-based 拓扑索引；缺 demand/compute CSV 时自动合成。 | `load_b4_joint_data()` / `load_joint_data()` — 拓扑解析、K 短路候选路径生成、场景构造（s0 全通/s1 链路故障/s2 算力降级）、节点角色自动标注、链路定价配置 |
| **`toy_te_data.py`** | 设计端到端两阶段多路径流量工程玩具。**不是 placement/knapsack toy**，而是显式多路径、共享链路竞争的 TE 数据集。11 节点 24 有向边、2 任务含不同资源偏好（CPU-heavy vs GPU-heavy）、3 算力节点异构、3 条 ingress + 3 条 egress 候选路径/对。 | `ToyTEData` dataclass + `build_toy_te_dataset()` — 共享瓶颈链路 a→c/c→a（容量 6.0 < 10+10）、b→d/d→b（容量 8.0）、算力瓶颈（colocation 导致 CPU/GPU 溢出）、4 场景（正常/转发节点 A 失效/mA 失效/链路降额） |
| **`toy_two_task_independent_data.py`** | 独立 Bernoulli 组件故障模型（23 组件 = 3 算力节点 + 20 链路），场景由产品分布生成。支持 `pruned`（≤max_fail 组件故障）/ `exhaustive`（全部 2²³≈8.4M 场景）/ `aggregate_worst`（尾部聚合）三种模式。 | `TwoTaskIndependentData` dataclass + `generate_scenarios()` — 每个组件有独立故障概率 p_fail，场景概率 = ∏ 组件成功/失败概率。链路和算力节点分别有独立价格 ρ_compute 和 ρ_link |
| **`toy_instances.py`** | 4 个确定性最小玩具：Toy-SLA（单任务 SLA CVaR）、Toy-SF（双任务 SF CVaR）、Toy-Combined-Conflict（SLA×SF 冲突）、Toy-ComponentRisk（512 场景组件级故障）。用于 exact enumeration 对照验证。 | `build_toy_sla()` / `build_toy_sf()` / `build_toy_combined()` / `build_toy_combined_component_risk()` |
| **`validate_toy_te.py`** | ToyTE 专用自动验证器（28 项检查），确保数据集可用性。 | 检查：M⊆V、task_src/dst∈V、路径完整性、≥2 路径/对、共享瓶颈存在、概率和=1、容量非负等 |
| **`component_scenario_generator.py`** | 独立故障组件场景生成基础设施。将链路和算力节点抽象为 `FailureComponent`，按独立 Bernoulli 乘积生成场景概率和容量。 | `FailureComponent` 类 + `attach_component_scenarios()` — 支持 `link` 和 `compute_derate` 两种组件类型 |

#### 优化模型层

| 文件 | 模型架构 | 数学公式与约束 |
|:--|:--|:--|
| **`cvar_compare.py`** | **核心 MILP 工厂**。`build_teavar_sla_cvar_model()` 是 Model A 的底层实现（被 `teavar_framework_models` 调用）。 | **目标**: $\min\; c_p + c_b + \lambda_{sla}\text{CVaR}^{SLA} + \lambda_{sf}\text{CVaR}^{SF} - \omega\mathbb{E}[\text{Del}]$ <br> **SLA CVaR** (Rockafellar-Uryasev): $\text{CVaR}^{SLA}_\beta = \zeta + \frac{1}{1-\beta}\sum_s \pi_s u_s$，$u_s b_i \ge b_i - R_{is} - b_i\zeta$ <br> **SF CVaR**: 每资源维归一化 $L^{SF}_s = \max_{m,k} (D_{mk}-C_{mks})_+ / \bar D_k$，$\phi_s \ge L^{SF}_s - \zeta_{sf}$ <br> **约束**: ①任务唯一放置 $\sum_m y_{im}=1$ ②计划流量≤放置 $x \le y\cdot b$ ③算力名义容量 $D_{mk}\le C^{norm}_{mk}$ ④链路名义容量 $\sum x\delta_{ep} \le B_e$ ⑤场景送达耦合 $d=x$ if path_up else $d=0$ ⑥虚拟接入瓶颈 |
| **`teavar_framework_models.py`** | **TEAVAR 视角四架构**（Model A/B/C/D），与 `duibi.py` 物理四架构平行对照。 | **Model A**: 单层加权 MILP（委托 `build_teavar_sla_cvar_model`）<br> **Model B**: Model A 目标 + KKT Indicator 互补条件：$z^{lam}_{s,i,t}=1 \Rightarrow slack=0$，$z^{mu}_s=1 \Rightarrow u_s=0$<br> **Model C**: ε-约束：$\min c_p+c_b-\omega\mathbb{E}[Del]$ s.t. $\text{CVaR}^{SLA}\le\Gamma_{sla}$，$\text{CVaR}^{SF}\le\Gamma_{sf}$<br> **Model D**: McCormick 线性包络松弛：$\lambda/\lambda_{max} + slack/slack_{max} \le 1$ |
| **`bilevel_teavar_models.py`** | **L0 双层分解 baseline**。慢层枚举 placement → 快层解 routing → post-hoc CVaR。非 KKT 嵌入的严格 Stackelberg 单模型，而是 reaction-based decomposition。 | 快层目标模式：`delivery`（min cost−ωE[Del]）、`lexicographic`（max E[Del]→min SLA loss→min cost）、`min_sla_cvar`（直接 min CVaR_SLA）、`lex_sla_delivery_cost`（min CVaR_SLA→max E[Del]→min cost）。严格 risk-first lexicographic 双层：SF→SLA→Cost |
| **`l2_full_models.py`** | **L2 全变量双层嵌入**（M0.5/M1/M2）。F1 为 SLA CVaR 最小化的 follower 问题。 | **M0.5**: fixed-y F1 primal + strong-duality gap 校验（手写 dual objective = ΣRHS·Pi，符号检查 cap_in/cap_out≤0, ru_in/ru_out≥0）<br> **M2**: embedded-y 全变量 + F1 strong-duality exact McCormick（π×y 线性化）<br> 上层: lex SF→SLA→Cost |
| **`duibi.py`** | 物理层四架构对照（算力+链路利用率 CVaR），与 TEAVAR 侧形成"物理 CVaR vs SLA CVaR"对比基线。 | 与 `teavar_framework_models` 共享 Model A–D 结构，但风险度量为**利用率尾部**而非需求损失尾部 |
| **`exact_enumeration_solver.py`** | 小规模 exhaustive 枚举验证。对 27 种 placement 逐一解 routing LP → 算 CVaR → 排名。 | `enumerate_placements()` + `compute_cvar()` — 提供 ground-truth baseline 供 MILP 对齐 |

#### 风险度量约束体系

**SLA (链路送达) CVaR 约束**(`cvar_compare.py:439-455`):
$$u_s \cdot b_i^{\text{in}} \ge b_i^{\text{in}} - R_{is}^{\text{in}} - b_i^{\text{in}}\zeta \qquad \forall s,i$$
$$u_s \cdot b_i^{\text{out}} \ge b_i^{\text{out}} - R_{is}^{\text{out}} - b_i^{\text{out}}\zeta \qquad \forall s,i$$
$$u_s \ge 0$$

**算力 SF (节点容量) CVaR 约束**(`cvar_compare.py:122-159`):
$$D_{mk} = \sum_i w_{ik} y_{im} \qquad \forall m,k$$
$$\phi_s \ge \frac{D_{mk} - C_{mks}^N}{\bar D_k} - \zeta^{\text{sf}} \qquad \forall s,m,k$$
$$\phi_s \ge 0$$

**链路容量约束**(`cvar_compare.py:229-247`):
$$\sum_{i,m,p} x_{i,m,p}^{\text{in}} \delta_{e,p} + \sum_{i,m,q} x_{i,m,q}^{\text{out}} \delta_{e,q} \le B_e \qquad \forall e\in\mathcal{E}$$

**算力容量约束**(`cvar_compare.py:418-423`):
$$\sum_{i} w_{ik} y_{im} \le C_{mk}^{\text{normal}} \qquad \forall m\in\mathcal{M}, k\in\mathcal{K}$$

**场景送达耦合**(`cvar_compare.py:79-119`):
$$d_{i,m,p,s}^{\text{in}} = \begin{cases} x_{i,m,p}^{\text{in}} & \text{if } \prod_{e\in p} \sigma_{es} > 0 \\ 0 & \text{otherwise} \end{cases}$$

#### 实验与工作流层

| 文件 | 用途 |
|:--|:--|
| `run_gamma_frontier.py` | Model C Γ 前沿扫描：网格化 (Γ_sla, Γ_sf) → 解每个预算组合 → 构建 Pareto 前沿 |
| `run_routing_mode_ablation.py` | 路由模式消融：对比 hub / per_task_od / umcf_global / umcf_per_task |
| `run_b4_main_table.py` | B4 主实验结果表（多 λ / Γ / ω / stress 条件） |
| `progressive_pipeline.py` | 三阶段流水线：物理 CVaR 扫描 → TEAVAR SLA CVaR 扫描 → UMCF 对照 |
| `p0_calibration.py` | η 标定：对给定 eta 搜索 demand_scale 使得 s1 下 feasible 条件恰好触发 |
| `pareto_frontier.py` | 从扫描结果构建 Pareto 前沿并拟合 trade-off 曲线 |
| `experiment_report.py` | 自动生成 LaTeX 表格 + matplotlib 图表 |

#### 新推送到 `fix-sf-per-resource-normalization-ac` 分支的关键变更

| 变更 | 文件 | 说明 |
|:--|:--|:--|
| **SF CVaR 按资源维分别归一化** | `cvar_compare.py` | 新增 `compute_sf_resource_refs()`：$\bar D_k = \max(\sum_i w_{ik}, 1)$。之前全局标量 D_ref 掩盖了 CPU/GPU/HBM 的不同尺度（CPU 10×GPU），改为每维独立归一化 |
| **per_resource SF CVaR RU 连续形式** | `cvar_compare.py` | `add_compute_sf_cvar_ru()`：移除 Big-M 和辅助二元变量 $w_{ex}$，使用纯连续 RU 约束 $\phi_s \ge (D_{mk}-C_{mks})/\bar D_k - \zeta_{sf}$ |
| **UMCF per-task 路由模式** | `b4_joint_data.py` | 新增 `attach_umcf_per_task()`：为每个任务 i 创建独立虚拟源 $V_s^{(i)}$ 和虚拟汇 $V_t^{(i)}$，保留物理 OD |
| **Model C 支持 per_task_od** | `teavar_framework_models.py` | 原 Model B/D 仅支持 hub 径向，Model C 完整支持 per_task_od 路由（按 task_src/dst 构建流变量） |
| **ToyTE 端到端多路径数据集** | `toy_te_data.py` | 全新设计：11 节点、24 边、3 ingress/egress 路径、共享瓶颈链路、异构算力 |
| **独立组件故障场景生成** | `toy_two_task_independent_data.py` | 23 独立 Bernoulli 组件、产品分布场景、支持 pruned/exhaustive/aggregate_worst |
| **L2 F1 对偶验证** | `l2_full_models.py` | M0.5 fixed-y primal/dual gap 验证 + M2 full embedded-y + exact McCormick dual×y |
| **ComponentRisk 独立发布版** | `model_ac_component_risk_release/` | 剥离 duibi 依赖的精简版，含 3 个测试（exact validation / combined conflict / component risk） |

---

## 运行方式

### 1. 论文式 TEAVAR（B4 隧道 + 链路场景）

```bash
python main.py --mode teavar --topology B4
```

依赖 `scipy` 与 `networkx`（用于 `get_tunnels`）。场景概率由 `util.weibull_probs` / `sub_scenarios` 生成，**不读取** `topology.txt` 中的 `prob_failure` 列（该列供文档或其它脚本）。

### 2. B4 + 联合放置 + CVaR（新算法 + 新数据）

```bash
python main.py --mode joint --topology B4
```

常用参数：`--hub`、`--joint-num-tasks`、`--joint-demand-row`、`--joint-k-paths`（默认 **4**，便于 B4 绕路）、`--joint-demand-scale`（默认 1，**>1 放大流量加压链路**）、`--joint-lambdas`、`--joint-omega`、`--joint-lambda-node`（**调大**可强迫 teavar 为压低算力 CVaR 而迁移）、`--joint-lambda-compute-sf`、`--joint-min-off-hub`、`--joint-stress-zero-s1` 等（见 `main.py` 与 `data/B4/DATASET_NOTES.txt`）。

**UMCF 显式虚拟源/汇**：`python main.py --mode joint --joint-umcf-teavar` 时，`load_b4_joint_data` 增加 \(V_s,V_t\) 及 \((V_s,m)\)、\((m,V_t)\) 写入 `E,B,sigma`；`build_teavar_sla_cvar_model` 与 **`duibi` / `teavar_framework_models`（A–D）** 的流锚点均经 `teavar_flow_anchors(data)` 与图一致（关闭 UMCF 时为 hub 径向）。可选 `--joint-umcf-sigma`、`--joint-umcf-sink-sigma`。与 `--joint-virtual-source` 同时开时 **以 UMCF 为准**（不再写 `sigma_vs` 瓶颈字典）。

**虚拟源接入（缓解「全堆在 hub 时空路径、SLA CVaR 退化」）**：加 `--joint-virtual-source` 后，`load_b4_joint_data` 会写入 `sigma_vs` / `sigma_vt`（默认可用率 **0.99**），`build_teavar_sla_cvar_model` 等对聚合送达量 `R_in`、`R_out` 施加串联上界（见 `建模公式说明.md` **§6.6**；**非** UMCF 显式虚拟节点图扩展，与严格多入口 UMCF 的对照见 **§6.6 末段与 §6.7**）。可选 `--joint-virtual-sigma`、`--joint-virtual-sink-sigma`（未指定时与前者相同）。

**若 physical 随 λ 变化而 teavar_sla 行不变**：多为 SLA CVaR 与放置在该 λ 扫描下退化；可依次尝试 `--joint-lambda-node 10` 或 `50`、`--joint-k-paths 6`、`--joint-demand-scale 2`、`--joint-lambda-compute-sf 0.3`，或 `--joint-min-off-hub` / `--joint-stress-zero-s1` 打破对称最优。

**`--joint-stress-zero-s1` 且未开 UMCF**：`build_single_layer_model`（physical）与 `build_teavar_sla_cvar_model`（teavar_sla）**约束与目标不同**，可行域不必一致（可出现 physical 不可行而 teavar_sla 仍可解）。与审稿人强调的「同一扩展图上的公平应力对照」请以 **`duibi.py` 的 Model A–D** 或 **同时 `--joint-umcf-teavar`** 为准。

### 3. 玩具数据上对比 physical 与 teavar_sla

```bash
python cvar_compare.py --lambdas "0.5,5,50" --lambda-node 0 --lambda-compute-sf 0.3
```

### 4. 玩具算例单独跑 duibi 内模型

```bash
python duibi.py
```

B4 默认：`python duibi.py`（可加 `--k-paths`、`--hub`、`--stress-zero-s1` 等）。**虚拟源**：`--virtual-source`，可选 `--virtual-sigma`、`--virtual-sink-sigma`；`--toy` 时同样生效。**UMCF**：`--umcf-teavar` 时 `load_b4_joint_data` / 玩具 `attach_umcf_to_data_object` 扩展图，**Model A–D 与链路指标**与 TEAVAR 侧共用同一锚点语义；可选 `--umcf-sigma`、`--umcf-sink-sigma`（与 `main.py --joint-umcf-teavar` 同源字段）。

（以 `duibi.py` 中 `__main__` 为准。）

---

## 模型关系简述

- **TEAVAR_Gurobi.TEAVAR**：在离散链路场景下为每条 flow 分配隧道流量，损失为 **未满足需求比例**，目标为 **VaR + 尾部加权**（见公式文档）。
- **duibi.build_single_layer_model（physical）**：任务放置 + 与 TEAVAR 一致的 **流锚点** `teavar_flow_anchors`（hub 或 UMCF 的 \(V_s,V_t\)），**算力 + 链路利用率 CVaR**；Model B/C/D 同步。
- **cvar_compare.build_teavar_sla_cvar_model（teavar_sla）**：同一数据接口下 **SLA 型需求未满足 CVaR**（与带宽 TEAVAR 叙事对齐），可选 **算力利用率 CVaR**、**算力未满足（超额）CVaR**。
- **b4_joint_data**：将 B4 拓扑、`demand.txt`、`node_compute_resources.csv` 转为上述 MILP 所需字段（hub 径向、K 短路、离散场景 σ/C_s）；可选 `sigma_vs`/`sigma_vt` 瓶颈，或 **`umcf_virtual_nodes`** 显式 \(V_s,V_t\) 边（`--joint-umcf-teavar` / `duibi.py --umcf-teavar`）。
- **duibi_metrics**：解后指标中 TEAVAR 流锚点由 **`teavar_flow_anchors(data)`** 给出（hub 径向或 UMCF 的 \(V_s,V_t\)）；`duibi` 物理模型仍用 `data.hub`。

---

## 引用与论文

TEAVAR 原始论文见仓库内 PDF（如 `3341302.3342069.pdf`）。本仓库实现与论文/Julia 参考在数值上可对齐 `parsers` 中的缩放约定。

---

## 许可证

Gurobi 使用需遵守 **Gurobi 许可协议**；学术许可仅限非商业用途。




### 七、`b4_joint_data.load_b4_joint_data`

**语义（数据对象 `data` 携带的量）**：

- **Hub**：物理入口节点 $h\in\mathcal{M}$。
- **任务需求**：每个任务 $i$ 的 $(b^{in}_i,\,b^{out}_i)$ 来自 `demand.txt` 中第 $h$ 行出向 OD 的 Top 若干条（缩放规则同 `parsers.read_demand`），再乘 **`demand_scale`**（默认 $1$；$>1$ 表示整体加压）。
- **资源与拓扑**：$(w_{ik},\,\pi_{mk},\,C^{norm}_{mk},\,C^N_{mks},\,B_e,\,\sigma_{es})$ 来自拓扑与 `node_compute_resources.csv`（与场景 $s$ 有关的量带下标 $s$）。
- **候选路径族**：$P_{uv}\subseteq$「$u\!\to\!v$ 至多 $K$ 条最短简单路径」（边序列），供路径变量索引。

**场景约定**：

$$
s=0:\ \text{全通};\qquad
s=1:\ \text{可切断高 \texttt{prob\_failure} 边};\qquad
s=2:\ \text{可缩小聚合层 }C^N_{mks}\ \text{（与数据文件一致）}.
$$

**虚拟接入（第 6.6 节）**：`virtual_source=True` 时为每个 $(m,s)$ 写入 $\sigma^{vs}_{m,s}$（默认 $0.99$）及对称 $\sigma^{vt}_{m,s}$（`virtual_sink_sigma` 缺省则与源相同）。

**UMCF（第 6.7 节）**：`umcf_virtual_nodes=True` 时写入 `umcf_vs,umcf_vt` 并扩展 $E,B,\sigma,\texttt{P\_cand}$；**`duibi` physical、`teavar_sla`、`teavar_framework_models` 与 joint 并排**共用该图实例。若与 `virtual_source` 同时打开，**以 UMCF 为准**（不再写 `sigma_vs` 字典）。

---

### 八、`duibi_metrics` 解后指标（非优化，公式）

| 函数 | 公式含义 |
|------|----------|
| `path_up` | 路径上所有边 $\sigma_{es}>0$。 |
| `max_link_util_after_solve` | 名义场景 $s=0$：$\max_e \mathrm{flow}_e/(B_e)$。 |
| `max_node_util_after_solve` | $s=0$：$\max_{m,k} \sum_i w_{ik} y_{im}/C^{norm}_{mk}$。 |
| `worst_max_link_util_across_scenarios` | $\max_s \max_e \mathrm{flow}_e/(B_e\sigma_{es})$。 |
| `worst_max_node_util_across_scenarios` | $\max_s \max_{m,k} \sum_i w_{ik} y_{im}/C^N_{mks}$。 |
| `expected_delivery_ratio` | 各任务在放置节点上 $(x^{in}\!/b^{in}+x^{out}\!/b^{out})/2$ 的平均。 |
| `expected_total_delivered_volume` | $\sum_s \pi_s\sum_{i,m,p} d^{in}_{i,m,p,s}+\cdots$（路径求和与 `teavar_flow_anchors(data)` 给出的 $(u,v)$ 下 $P_{uv}$ 一致） |
| `sla_per_scenario_max_demand_loss` | $L_s=\max_i \max\{1-R^{in}_{is}/b^{in}_i,\,1-R^{out}_{is}/b^{out}_i\}$。 |

以下为与上表**同义**的块公式（便于对照代码中的 `flow_e`、`y` 等变量）：

$$
\begin{aligned}
\texttt{max\_link\_util\_after\_solve} &: \quad U^{\mathrm{link}}_0 = \max_{e\in E}\frac{\mathrm{flow}_e}{B_e} \quad (s=0),\\[4pt]
\texttt{max\_node\_util\_after\_solve} &: \quad U^{\mathrm{node}}_0 = \max_{m,k}\frac{\sum_i w_{ik}\,y_{im}}{C^{norm}_{mk}} \quad (s=0),\\[4pt]
\texttt{worst\_max\_link\_util\_across\_scenarios} &: \quad \max_{s}\max_{e\in E}\frac{\mathrm{flow}_e(x,s)}{B_e\,\sigma_{es}},\\[4pt]
\texttt{worst\_max\_node\_util\_across\_scenarios} &: \quad \max_{s}\max_{m,k}\frac{\sum_i w_{ik}\,y_{im}}{C^N_{mks}},\\[4pt]
\texttt{expected\_total\_delivered\_volume} &: \quad \sum_{s}\pi_s\Bigl(\sum_{i,m,p} d^{in}_{i,m,p,s}+\sum_{i,m,q} d^{out}_{i,m,q,s}\Bigr).
\end{aligned}
$$

**实现注**：涉及 $P_{uv}$ 的送达与链路流量指标均以 **`teavar_flow_anchors(data)`** 为 $(u,v)$ 锚点（hub 径向或 UMCF 的 $V_s,V_t$）。**放置**、`min_off_hub`、**应力**（切断 hub 出边）仍用物理 **`data.hub`**；二者分工与 README「模型关系」一致。

---

### 九、`parsers` / `util`（数据与场景，非单一 MILP）

- **`read_topology`**：容量 $\mathrm{cap}=\mathrm{raw}/1000/\text{downscale}$（与 Julia 对齐）。
- **`read_demand`**：$d=\mathrm{raw}/(\text{downscale}\cdot 1000)\cdot \text{scale}$。
- **`util.weibull_probs` / `sub_scenarios`**：生成链路故障率与子场景概率 $\pi_s$，供 `TEAVAR` 使用。

---

### 十、其它脚本（索引）

- `copo_CVaR.py`、`copo_cvar01.py`、`teavar_cete.py` 等：独立实验/变体，公式以各自文件内注释为准。
- `huatu.py`：批量调用 `main` 并绘图。

---

### 十一、`teavar_framework_models`（TEAVAR 视角与 duibi 四架构对齐）

**结构**：与 `duibi.py` 中 A–D 平行——**横轴**为 SLA 需求损失 CVaR（及可选算力未满足 CVaR）；**纵轴**为加权 / KKT / $\varepsilon$-约束 / McCormick。

**流锚点**（与 `cvar_compare.build_teavar_sla_cvar_model` 一致）：由 **`teavar_flow_anchors(data)`** 得到 $(s_{\mathrm{src}},s_{\mathrm{dst}})$。

- 未开 UMCF：hub $h$ 径向，候选路径族 $P_{h,m},\,P_{m,h}$（代码里 $h=\texttt{getattr(data,'hub',0)}$）。
- 开 UMCF：候选为 $P_{V_s,m},\,P_{m,V_t}$。

在 `del` 与物理链路耦合之后，**Model B/C/D** 调用 `cvar_compare.add_teavar_virtual_bottleneck_constraints`（当 `data.sigma_vs` 非空且**未**做 UMCF 图扩展时），与第 6.6 节一致；**Model A** 委托 `build_teavar_sla_cvar_model`（支持 `data.umcf_virtual_nodes`，见第 6.7 节）。**放置**仍用物理 hub $h$。

**共通标量**（与实现字段同名）：

$$
\begin{aligned}
\mathbb{E}[\mathrm{Del}] &= \sum_{s}\pi_s\sum_{i,m,p} d^{in}_{i,m,p,s}+\sum_{s}\pi_s\sum_{i,m,q} d^{out}_{i,m,q,s},\\[4pt]
c_{\mathrm{total}} &= c_p + c_b - \omega\,\mathbb{E}[\mathrm{Del}].
\end{aligned}
$$

**SLA 尾部（Rockafellar–Uryasev）**：引入 $(\zeta,u_s)$，对每个任务 $i$、场景 $s$：

$$
\begin{aligned}
u_s\,b^{in}_i &\ge b^{in}_i - R^{in}_{is} - b^{in}_i\,\zeta,\\
u_s\,b^{out}_i &\ge b^{out}_i - R^{out}_{is} - b^{out}_i\,\zeta .
\end{aligned}
$$

$$
\mathrm{CVaR}^{\mathrm{SLA}}=\zeta+\frac{1}{1-\beta}\sum_{s}\pi_s\,u_s .
$$

**算力未满足尾部（可选，与第 6.4 节同构）**：

$$
\begin{aligned}
D_{mk} &= \sum_i w_{ik}\,y_{im},\\
e_{mks} &= \max\{0,\,D_{mk}-C^N_{mks}\},\\
L^{\mathrm{sf}}_s &= \max_{m,k}\frac{e_{mks}}{D_{\mathrm{ref}}},\\
\phi_s &\ge L^{\mathrm{sf}}_s-\zeta_{\mathrm{sf}},\qquad
\mathrm{CVaR}^{\mathrm{sf}}=\zeta_{\mathrm{sf}}+\frac{1}{1-\beta_{\mathrm{sf}}}\sum_{s}\pi_s\,\phi_s .
\end{aligned}
$$

| 模型 | 目标 / 约束 | 实现函数 |
|------|----------------|----------|
| **A** 单层加权 | $\min\, c_{total}+\lambda_{sla}\mathrm{CVaR}^{SLA}+\lambda_{sf}\mathrm{CVaR}^{sf}$（$\lambda_{sf}=0$ 时不建 sf 块） | `build_teavar_model_a` → 委托 `cvar_compare.build_teavar_sla_cvar_model`（`lambda_node=0`） |
| **B** KKT | 与 A 同目标；对 SLA 的每条 $(s,i)$ 探测行加 $\mathrm{slack}^{SLA}$ 与对偶 $\alpha$ 的 **Indicator** 互补；若 $\lambda_{sf}>0$ 且 `kkt_sf=True`，对 $\phi$ 层 $(s,m,k)$ 再加一套 KKT Indicator | `build_teavar_model_b` |
| **C** ε-约束 | $\min\, c_{total}$ s.t. $\mathrm{CVaR}^{SLA}\le\Gamma_{sla}$，（可选）$\mathrm{CVaR}^{sf}\le\Gamma_{sf}$ | `build_teavar_model_c` |
| **D** McCormick | $\min\, c_{total}$；用线性包络 $\frac{\alpha}{\alpha_{max}}+\frac{\mathrm{slack}}{\mathrm{slack}_{max}}\le 1$ 松弛 SLA 与 sf 的互补（与 `duibi.build_copo_mccormick_model` 同构思想） | `build_teavar_model_d` |

**说明**：Model D 事后在解上读取的 $\mathrm{CVaR}^{SLA},\mathrm{CVaR}^{sf}$ 与 Model A 最优 CVaR **不必同界**（松弛松），与 physical 的 Model D 相同 phenomenon。

---

若某函数在仓库中增删，请同步更新本文件对应小节。

