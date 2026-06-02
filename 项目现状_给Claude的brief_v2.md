# 故障感知算力–网络联合优化：项目完整现状（供 Claude 规划后续进展）

---

## 一句话定位

**故障感知算力–网络联合优化的 MILP 框架**。在有向 WAN 拓扑上，同时决定：
- 每个任务的**异构算力节点放置**（CPU/GPU/HBM 多维资源 + 节点差异化定价）
- ingress/egress **两阶段多路径流量分配**
- 以**双通道 CVaR**（网络送达未满足 + 算力超额未满足）刻画尾部风险

求解器 Gurobi，主数据 B4 拓扑，已扩展至 9 个真实 WAN 拓扑。面向学术论文投稿。

---

## 一、项目文件结构

```
TEAVAR_python/
├── main.py                          # CLI 入口：--mode teavar（论文复现）/ --mode joint（联合放置）
├── TEAVAR_Gurobi.py                 # 原始 TEAVAR 隧道分流 MILP（纯 WAN，无算力）
├── duibi.py                         # Physical CVaR：Model A/B/C/D + 玩具/B4 加载
├── cvar_compare.py                  # SLA CVaR 核心：build_teavar_sla_cvar_model() + 虚拟接入
├── teavar_framework_models.py       # SLA CVaR：Model A/B/C/D（与 duibi 四模型对齐）
├── progressive_pipeline.py          # 递进管线 A→C→B→D + 四项优化原型
├── b4_joint_data.py                 # 数据加载：B4 + 9 拓扑泛化 + K 短路 + UMCF
├── duibi_metrics.py                 # 解后指标：利用率 / 送达 / SLA 损失 / 链路流量
├── parsers.py                       # 拓扑/需求解析（含 Julia 对齐缩放约定）
├── util.py                          # Weibull 链路故障概率 + 子场景生成
├── generate_compute_resources.py    # 多拓扑算力资源自动生成（度数角色分配 + 差异化定价）
├── model_m_monetary_cvar.py         # Model M：纯货币化 CVaR（场景账单 + 违约金）
├── monetary_cvar.py                 # Model M-C：期望账单 + CVaR 预算约束
├── plot_duibi_paper_narrative.py    # 论文图表
├── plot_duibi_umcf_sweep.py         # UMCF 参数扫描
├── experiment_report.py             # 实验报告
├── data/
│   ├── B4/                          # 12 节点 38 有向边 + topology/demand/compute CSV
│   ├── ATT/ IBM/ XNet/ Nextgen/ Abilene/ Sprint/ Custom/ Custom2/
│   │   └── topology.txt + node_compute_resources.csv（自动生成）
│   └── raw/
├── 建模公式说明.md                   # 各函数对应完整数学公式（~700 行，主技术文档）
├── 项目总结_模型AC.md                # Model A/C 公式补全版
├── 论文初稿.md                       # 论文正文初稿（含双层讨论、四模型逻辑链）
├── 建模章节_算力网络联合优化.md       # 论文章节体例版
├── 建模_货币化纯CVaR.md              # Model M/M-C 货币化方向详细说明
├── 改进报告.md                       # 三方向改进记录
├── AEGIS.md                         # AEGIS 论文详细摘要
├── Compute-aware Routing.md         # 实验评估数据
├── 未来扩展_微服务DAG.md             # 原子 task → 微服务 DAG 扩展设计草案
└── README.md                        # 运行说明与 CLI 参数
```

---

## 二、三篇参考论文

### 1. TEAVAR（SIGCOMM 2019）
- **核心**：WAN 隧道分流 + CVaR 度量需求未满足比例的尾部风险
- **借鉴**：CVaR 线性化技术（Rockafellar-Uryasev）、路径预计算 K 短路、离散概率场景
- **不采用**：纯 WAN 无算力、无两阶段业务流

### 2. Copo（ICNP 2025）
- **核心**：放置成本 + 带宽成本联合；KKT/McCormick 将双层压单层
- **借鉴**：放置+带宽联合目标、KKT Indicator 验证思路
- **不采用**：地理区域流模型；实测 McCormick 松弛 CVaR 可偏 210%，不可作主求解器

### 3. AEGIS（IEEE TON 2026）
- **核心**：Flow-based 弹性路由（无路径枚举）+ CVaR 约束 + 正常态吞吐下界 γ
- **借鉴**：CVaR 作约束（Model C）、正常态 δ_min 下界、二分搜索
- **不采用**：Flow-based 弧变量（我们当前仍是 path-based）

---

## 三、核心建模框架

### 3.1 问题设置

地理分布式有向图 $\mathcal{G}=(\mathcal{N},\mathcal{E})$，$\mathcal{M}\subseteq\mathcal{N}$ 为具备算力的节点。每任务 $i$：
- 给定输入/输出数据量 $b_i^{\text{in}}, b_i^{\text{out}}$
- 给定多维算力需求 $\mathbf{w}_i = (w_{i,\text{CPU}}, w_{i,\text{GPU}}, w_{i,\text{HBM}})$
- 选择**一个**执行节点 $m$（任务不可分割）

通信为**两阶段有向路由**（流量可多路径分割）：

$$h \xrightarrow{\text{ingress}} m \xrightarrow{\text{egress}} d$$

其中 $h$ 为 hub 节点（当前 hub 径向简化），或 UMCF 虚拟源/汇 $(V_s, V_t)$。

### 3.2 离散故障场景

3 个场景（可扩展）：
- $s=0$：全通（$\pi_0=0.6$）
- $s=1$：链路中断（$\pi_1=0.3$）
- $s=2$：算力节点降额（$\pi_2=0.1$）

每条链路 $e$ 有场景可用率 $\sigma_{es}\in[0,1]$；每节点每维度有场景可用容量 $C^N_{mks}$。

### 3.3 异构算力建模

**三类资源维度** $\mathcal{K}=\{\text{CPU}, \text{GPU}, \text{HBM}\}$：

| 维度 | 相对价格 | 现实依据 |
|------|---------|---------|
| CPU | 1.0×（基准） | 商品化，最便宜 |
| GPU | 3.5–5.0× | A100 ~\$1-3/GPU-hr vs CPU ~\$0.04/core-hr |
| HBM | 1.5–2.5× | 高带宽内存成本加成 |

**三层角色定价**（按节点度数中心性分配）：

| 角色 | 度数分位 | 价格乘数 | 容量范围 |
|------|---------|---------|---------|
| Core | Top 25% | 0.75× | CPU 120-500, GPU 40-200, HBM 24-100 |
| Aggregation | Mid 50% | 1.0× | CPU 80-210, GPU 20-88, HBM 8-44 |
| Edge_pop | Bottom 25% | 1.45× | CPU 40-120, GPU 8-24, HBM 4-12 |

### 3.4 决策变量一览

| 变量 | 类型 | 含义 |
|------|------|------|
| $y_{im}$ | $\{0,1\}$ | 任务 $i$ 是否放在节点 $m$ |
| $x^{\text{in}}_{i,m,p}$ | $\mathbb{R}_+$ | 计划 ingress 流量（路径 $p$，全场景共用） |
| $x^{\text{out}}_{i,m,q}$ | $\mathbb{R}_+$ | 计划 egress 流量 |
| $d^{\text{in}}_{i,m,p,s}$ | $\mathbb{R}_+$ | 场景 $s$ 下 ingress 实际送达量 |
| $d^{\text{out}}_{i,m,q,s}$ | $\mathbb{R}_+$ | 场景 $s$ 下 egress 实际送达量 |
| $\zeta, u_s$ | $\mathbb{R}, \mathbb{R}_+$ | SLA CVaR 辅助变量 |
| $D_{mk}, e_{mks}, w^{\text{exc}}_{mks}$ | 连续/二元 | 算力缺口线性化变量 |
| $\zeta_{\text{sf}}, \phi_s$ | $\mathbb{R}, \mathbb{R}_+$ | 算力未满足 CVaR 辅助变量 |

---

## 四、四类度量（成本 + 双 CVaR + 货币化扩展）

### 4.1 放置成本（异构多维也）

$$c_p = \sum_{i} \sum_{m} y_{im} \sum_{k} w_{ik} \cdot \pi_{mk}$$

- $\pi_{mk}$：节点 $m$ 上资源 $k$ 的**单位价格**（Core 便宜、Edge 贵；GPU 贵于 CPU）
- 体现**算力异构 + 节点价差**，与场景无关

### 4.2 带宽成本

$$c_b = \sum_{i,m,p} x^{\text{in}}_{i,m,p} \cdot |p| + \sum_{i,m,q} x^{\text{out}}_{i,m,q} \cdot |q|$$

- 按路径 hop 数计费（新版已改为链路价和 $\tau_p = \sum_{e\in p} \pi_e$）

### 4.3 期望送达奖励

$$\mathbb{E}[\text{Del}] = \sum_s \pi_s \left(\sum d^{\text{in}} + \sum d^{\text{out}}\right)$$

$$C_{\text{tot}} = c_p + c_b - \omega \cdot \mathbb{E}[\text{Del}]$$

- **$-\omega \cdot \mathbb{E}[\text{Del}]$ 是关键设计**：防止"压零流省带宽、CVaR 仍为 0"的退化
- $\omega=0$ 时关闭

### 4.4 网络侧 SLA CVaR（需求未满足尾部）

$$R^{\text{in}}_{is} = \sum_{m,p} d^{\text{in}}_{i,m,p,s}, \quad R^{\text{out}}_{is} = \sum_{m,q} d^{\text{out}}_{i,m,q,s}$$

$$u_s \cdot b^{\text{in}}_i \ge b^{\text{in}}_i - R^{\text{in}}_{is} - b^{\text{in}}_i \cdot \zeta \quad \forall i,s$$

$$\text{CVaR}^{\text{SLA}} = \zeta + \frac{1}{1-\beta} \sum_s \pi_s \cdot u_s$$

- $\beta=0.95$ 关注最坏 ~5% 场景的平均未满足程度

### 4.5 算力侧未满足 CVaR（**必选，非可选**）

这是算网联合优化的第二根风险支柱。"数据送到了但算不完"与"数据没送到"是正交的失败模式。

**节点聚合需求：**
$$D_{mk} = \sum_i w_{ik} \cdot y_{im}$$

**场景算力缺口（Big-M 线性化 $e = \max(0, D-C)$）：**
$$e_{mks} \ge D_{mk} - C^N_{mks}, \quad e_{mks} \ge 0$$
$$e_{mks} \le (D_{mk} - C^N_{mks}) + M \cdot (1 - w^{\text{exc}}_{mks})$$
$$e_{mks} \le M \cdot w^{\text{exc}}_{mks}, \quad w^{\text{exc}}_{mks} \in \{0,1\}$$

**场景标量损失与 CVaR：**
$$\phi_s \ge \frac{e_{mks}}{C^N_{mks}} - \zeta_{\text{sf}} \quad \forall m,k,s$$

$$\text{CVaR}^{\text{sf}} = \zeta_{\text{sf}} + \frac{1}{1-\beta_{\text{sf}}} \sum_s \pi_s \cdot \phi_s$$

| 维度 | CVaR^SLA | CVaR^sf |
|------|----------|---------|
| 触发原因 | 路径断、接入差 → d < b | 任务堆叠、容量降额 → D > C |
| 失败语义 | 数据没到 | 数据到了但算不完 |
| 论文定位 | **必选** | **必选**（双 CVaR 联合） |

---

## 五、约束条件（Model A/C 共用可行域）

### 5.1 任务单点放置
$$\sum_m y_{im} = 1 \quad \forall i$$

### 5.2 流量激活
$$\sum_p x^{\text{in}}_{i,m,p} = y_{im} \cdot b^{\text{in}}_i, \quad \sum_q x^{\text{out}}_{i,m,q} = y_{im} \cdot b^{\text{out}}_i$$

### 5.3 名义容量
$$\text{flow}_e \le B_e, \quad \sum_i w_{ik} \cdot y_{im} \le C^{\text{norm}}_{mk}$$

### 5.4 场景送达与计划流耦合（Big-M）
- 路径通且 $y_{im}=1$：$d = x$
- 路径断或 $y_{im}=0$：$d = 0$

### 5.5 可选机制
- **虚拟接入瓶颈** $\sigma^{\text{vs}}_{m,s}$：$R^{\text{in}}_{is} \le \sum_m b^{\text{in}}_i \cdot y_{im} \cdot \sigma^{\text{vs}}_{m,s}$（缓解 hub 空路径退化）
- **UMCF 显式虚拟源/汇** $(V_s, V_t)$：扩展图，变更流锚点
- **正常态下界** $\delta_{\min}$：$s=0$ 时 $R^{\text{in}}_{i,0} \ge \delta_{\min} \cdot b^{\text{in}}_i$

---

## 六、优化模型体系

### 6.1 主线模型（SLA 双 CVaR）

**Model A — 加权标量化（精确 MILP，Pareto 探索）：**

$$\min \quad c_p + c_b - \omega \cdot \mathbb{E}[\text{Del}] + \lambda_{\text{sla}} \cdot \text{CVaR}^{\text{SLA}} + \lambda_{\text{sf}} \cdot \text{CVaR}^{\text{sf}}$$

- 扫 $\lambda$ 得 cost–risk Pareto 前沿
- 为 Model C 标定 $\Gamma$ 上界

**Model C — ε-约束 / 风险预算（精确 MILP，部署落地）：**

$$\min \quad c_p + c_b - \omega \cdot \mathbb{E}[\text{Del}]$$
$$\text{s.t.} \quad \text{CVaR}^{\text{SLA}} \le \Gamma_{\text{sla}}, \quad \text{CVaR}^{\text{sf}} \le \Gamma_{\text{sf}}$$

- $\Gamma$ 可解释为**可签署的双通道风险合同**
- 典型标定：$\Gamma \approx (1+\varepsilon) \times \text{CVaR}^*_A$（从 Model A 扫描得到）

**Model A ↔ Model C 关系**：描述**同一条** cost–risk Pareto 前沿。A 标定参数，C 产出主结果。

### 6.2 辅助模型（验证/消融，非主求解器）

**Model B — KKT + Indicator（精确，仅验证）：**
- 与 Model A 同目标，额外加入 CVaR 子问题的 KKT 互补 Indicator
- 用于验证 RU 线性化等价于严格双层 KKT 单层化
- 慢，大量二元变量，仅一组小实例验证用

**Model D — McCormick 松弛 → 建议舍弃**
- 原意：Copo 式加速
- 实测：事后 CVaR 可偏 210%
- **结论**：不可作主结果，考虑从论文正文移除

### 6.3 扩展方向一：纯货币化 CVaR（Model M / M-C）

**动机**：Model A 存在量纲混合问题（成本是货币，CVaR 是比例），$\lambda$ 的物理含义不直观。

**Model M — 场景货币账单 + 纯 CVaR 最小化：**

定义场景 $s$ 的总账单：

$$L_s = c_p + c_b(s) + \kappa_{\text{sum}} \cdot \text{Shortfall}^{\text{sum}}_s$$

其中：
- $c_b(s)$：场景 $s$ 下**实际送达**的带宽费（而非计划流量）
- $\text{Shortfall}^{\text{sum}}_s = \sum_i (\text{sf}^{\text{in}}_{is} + \text{sf}^{\text{out}}_{is})$：未送达流量的**违约金**
- $\kappa_{\text{sum}}$：单位未送达的罚金率（由 SLA 合同确定）

目标：$\min \text{CVaR}_\beta(L) = \min \zeta + \frac{1}{1-\beta}\sum_s \pi_s u_s$，s.t. $u_s \ge L_s - \zeta$

**特点**：目标函数**量纲统一**（全是货币），无 $\lambda$ 需要标定。

**Model M-C — 期望账单 + CVaR 预算：**

$$\min \mathbb{E}[L_s] = \sum_s \pi_s L_s \quad \text{s.t.} \quad \text{CVaR}_\beta(L) \le \Gamma_{\text{money}}$$

- 更适合**实际部署**：主目标为期望总账单，尾部由合同 $\Gamma_{\text{money}}$ 限制
- $\Gamma$ 通过对 Model M 最优 $\text{CVaR}^*$ 二分标定

**Model M vs Model A 对比**：

| 维度 | Model A | Model M |
|------|---------|---------|
| 目标量纲 | 混合（货币 + 比例） | 纯货币 |
| 可解释性 | λ 无物理含义 | κ 对应 SLA 违约金条款 |
| 参数标定 | 扫 λ 画 Pareto | 从合同取 κ，二分 Γ |
| 舍入风险 | CVaR 比例不直接对应金额 | 账单即最终支付 |

### 6.4 扩展方向二：按决策速度分层的双层分配

**动机**：放置（$y$）是慢时间尺度（分钟/小时级），流量分配（$x, d$）是快时间尺度（秒级）。将不同速度的决策强行放在同一个 MILP 里，在实际上线场景中不自然。

**新双层设计（按执行速度，非按优化层级）：**

```
Layer 1（慢层 — 任务放置）：
  决策：y_im（放哪里）
  约束：算力名义容量、单点放置
  目标：最小化 c_p + CVaR^sf（与路由无关的算力侧风险）

Layer 2（快层 — 流量分配）：
  给定：y*（从 Layer 1 固定）
  决策：x_in, x_out, d（怎么走、送多少）
  约束：链路容量、路径可达性
  目标：min c_b - ω·E[Del] + λ_sla·CVaR^SLA
```

**好处**：
- 两层可独立求解（Layer 2 在固定 y 后是完全的 LP，不含二元变量）
- 适合在线部署：y 不变时只需重解 Layer 2
- 与 Model A（联合单层）的关系类似"松弛 → 验证"

**与 Model A/C 的分工**：
- Model A/C 给出**理论最优**（联合单层，上界）
- 双层给出**可部署解**（下界；gap 衡量"分解的代价"）

---

## 七、当前实现状态矩阵

| 模型 | 代码位置 | 状态 | 备注 |
|------|---------|------|------|
| **Model A（SLA 加权）** | `cvar_compare.py:build_teavar_sla_cvar_model()` | ✅ 完整 | 含双 CVaR + ω 奖励 |
| **Model C（SLA ε-约束）** | `teavar_framework_models.py:build_teavar_model_c()` | ✅ 完整 | 含双 Γ |
| **Model B（KKT）** | `teavar_framework_models.py:build_teavar_model_b()` | ✅ 原型 | 验证用，非日常 |
| **Model D（McCormick）** | `teavar_framework_models.py:build_teavar_model_d()` | ⚠️ 存在 | **建议舍弃**（CVaR 偏 210%） |
| **Physical A/C** | `duibi.py` | ✅ 完整 | 利用率 CVaR 对照 |
| **Model M** | `model_m_monetary_cvar.py` | ✅ 原型 | 货币化 CVaR |
| **Model M-C** | `monetary_cvar.py` | ✅ 原型 | 期望账单 + CVaR 预算 |
| **双层分解** | — | ❌ 未实现 | 设计阶段 |
| **一般化 s_i→m→t_i** | — | ❌ 未实现 | 当前为 hub 径向 |
| **DAG 微服务** | `未来扩展_微服务DAG.md` | ❌ 仅设计文档 | — |

---

## 八、数据集现状

### B4（主实验，12 节点 38 边）
- topology.txt（含 prob_failure）、demand.txt、node_compute_resources.csv（手工）
- 3 个场景

### 9 个扩展拓扑

| 拓扑 | 节点 | 边 | 状态 |
|------|------|-----|------|
| ATT | 25 | 112 | ✅ |
| XNet | 28 | 76 | ⚠️ 缺 prob_failure |
| IBM | 17 | 46 | ✅ |
| Nextgen | 17 | 38 | ⚠️ demand.txt 为空 |
| Abilene | 12 | 30 | ✅ |
| B4 | 12 | 38 | ✅ |
| Sprint | 11 | 36 | ⚠️ 0-based 索引 |
| Custom | 6 | 18 | ✅ |
| Custom2 | 5 | 14 | ⚠️ hub=0 无出向需求 |

算力资源由 `generate_compute_resources.py` 按度数中心性自动生成。

---

## 九、当前已知结果

### 求解性能（玩具数据）

| Model | 耗时 | cost | CVaR vs A |
|-------|------|------|-----------|
| A | 0.07s | 3810 | 基准 |
| B | 0.02s | 3810（gap=0%） | 一致 |
| C | 0.01s | 3810 | 受 Γ 约束 |
| D | 0.02s | 3810 | **+210% 偏差** |

### 关键发现
1. Model A ↔ C：同一条 Pareto 前沿，验证通过
2. Model B：与 A 的 gap=0%，KKT 条件正确
3. Model D：事后 CVaR 严重偏差（210%），**不可作主结果**
4. SLA CVaR 退化条件：全堆 hub + 空路径 → CVaR=0，需虚拟源/stress/min_off_hub 缓解
5. Physical vs SLA：回答不同问题（资源拥塞 vs 用户未满足），不可互相替代

---

## 十、当前不足（分级）

### 🔴 结构性

1. **Path-based 扩展性瓶颈**：K 短路预计算，大网路径数爆炸。AEGIS 证明 flow-based 快 5500 倍。论文初稿列为"未来工作"
2. **Hub 径向未泛化**：代码 `teavar_flow_anchors()` 返回全局锚点 $(h,h)$，非 per-task $(s_i, t_i)$。与论文公式不一致
3. **场景过粗**：仅 3 个场景（TEAVAR 原始用 Weibull 生成更多）

### 🟡 工程与论文

4. **论文与代码不一致处**：
   - 论文公式：$s_i \to m \to t_i$（per-task 源宿）
   - 代码实现：hub 径向 $(h \to m \to h)$
   - 费用公式：论文用 $|p|$，新版代码已改 $\tau_p$
5. **多拓扑实验缺失**：9 个拓扑的完整 cost-risk 对比表未产出
6. **Model M/M-C 未集成到主管线**：原型代码独立存在
7. **双层分解未实现**
8. **DAG 微服务仅设计文档**
9. **无测试、无 CI**

---

## 十一、我的目标与优先级

### 短期（赶论文）
1. 产出 B4 + 多拓扑的完整实验数据（Model A/C + 双 CVaR 主表 + Physical 对照）
2. 统一论文公式与代码（至少明确标注"当前为 hub 特例"）

### 中期（方法论完善）
3. 实现一般化 $s_i \to m \to t_i$（使代码与论文一致）
4. 将 Model M/M-C 集成到主管线，产出货币化对比实验
5. 实现按决策速度的双层分解，与 Model A 对比 gap

### 长期（突破扩展性）
6. 设计 flow-based MILP 版本（对齐 AEGIS 思路）
7. DAG 微服务 + flow-based 联合

---

## 十二、希望 Claude 帮我做的事

1. **细化实现路线图**：基于以上现状，给出具体的 Phase 1→2→3 里程碑和预估工作量
2. **识别速赢项**：哪些是低投入高回报的（例如 Model M 集成、论文公式与代码对齐标注）
3. **评估 flow-based 迁移**：从 path-based → flow-based 的工作量和风险
4. **推荐论文实验结构**：主表用什么、附录用什么、消融放什么
5. **Model D 去留**：是否从论文正文完全移除，仅放一句"McCormick 松弛在此场景下不可靠"
6. **双层分解的实现建议**：是否作为"可扩展性"小节还是单独成章
