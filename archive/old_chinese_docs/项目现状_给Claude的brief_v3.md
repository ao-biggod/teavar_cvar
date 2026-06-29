# 故障感知算力–网络联合优化：项目完整现状 v3（供 Claude 规划后续进展）

> **版本说明**：本文档取代 `项目现状_给Claude的brief_v2.md`。  
> **文档 SSOT（单一事实源）**：Method 公式以 `建模章节_算力网络联合优化.md`、`项目总结_模型AC.md` 为准；Model M 以 `建模_货币化纯CVaR.md` 为准。  
> `论文初稿.md`、`建模公式说明.md` 部分条目**尚未同步**，引用前需对照 v3。

---

## §0  v2 → v3 修正清单（对照代码 2026-05）

| # | 类别 | v2 问题 | v3 修正 | 代码/待办 |
|---|------|---------|---------|-----------|
| 0.1 | 文件映射 | M 在 `model_m_monetary_cvar.py`，M-C 在 `monetary_cvar.py` | **M 与 M-C 均在 `monetary_cvar.py`**；`model_m_monetary_cvar.py` 为已合并遗留 | 可归档遗留文件 |
| 0.2 | 带宽费 | 主公式写 hop $\|p\|$ | 主公式 $\tau_p=\sum_{e\in p}\pi_e$；SLA 目标用 $x$，Model M 用 $d(s)$ | `duibi_metrics.bandwidth_cost_expr` ✅ |
| 0.3 | 算力 CVaR | $\phi_s \ge e/C^N_{mks}$ | $\phi_s \ge e_{mks}/D_{\mathrm{ref}}$，$D_{\mathrm{ref}}=M_{\mathrm{ex}}$ 常数 | `cvar_compare.py` ✅ |
| 0.4 | 流守恒 | 统一写等号 | **SLA**：$\le$；**Physical**：$=$ | 分模型写论文 |
| 0.5 | 双 CVaR | 写「必选」但默认关 | Method **必选**；`main.py joint` 默认 $\lambda_{\mathrm{sf}}=1$；消融 `--joint-ablation-no-compute-sf` | `main.py` ✅ |
| 0.6 | 路由 | 仅写 hub | **论文标准** $s_i\to m\to t_i$；**代码** hub $(h,m,h)$ 或 UMCF $(V_s,V_t)$ | **→ 阶段 1 必做**（见 `最终路线图.md` §四·补） |
| 0.7 | main.py | 联合放置完整管线 | **joint**：Physical+SLA A 扫 $\lambda$；**monetary**：M/M-C + `--monetary-compare-a` | Model C / 多拓扑 batch 待做 |
| 0.8 | 数据加载 | main 未用泛化 loader | `load_joint_data()` ✅；**joint/monetary 已统一** `_load_joint_data_from_args` | `main.py` ✅ |
| 0.9 | M 事后账单 | recompute 与 MILP $\tau_p$ 不一致 | **`scenario_bandwidth_cost_value`** 统一事后 $c_b(s)$ | `monetary_cvar.py` ✅ |
| 0.10 | 双层 | Layer 2「纯 LP」 | 固定 $y$ 后仍有多场景 $d$ + 可选算力 Big-M → **连续/小规模 MILP**，非必然 LP | 设计表述修正 |
| 0.11 | 实验 | 多拓扑表未产出 | `experiment_report.py` 已有玩具+B4 部分 CSV/PNG | 扩展多拓扑矩阵 |
| 0.12 | Model M 状态 | 「原型」 | MILP + CLI + compare + bisect **已实现**；**`main.py --mode monetary`** | 集成主管线 ✅ |

---

## 一句话定位

**故障感知算力–网络联合优化的 MILP 框架**。在有向 WAN 拓扑上，同时决定：
- 每个任务的**异构算力节点放置**（CPU/GPU/HBM + 节点差异化定价）
- ingress/egress **两阶段多路径流量分配**
- **双通道 CVaR**（网络 SLA 未满足 + 算力超额未满足）刻画尾部风险

求解器 Gurobi；主实验拓扑 B4；数据层已扩展 9 个 WAN 拓扑（批量实验未跑通）。面向学术论文投稿。

---

## 一、项目文件结构

```
TEAVAR_python/
├── main.py                          # CLI：teavar | joint | monetary（见 §七）
├── TEAVAR_Gurobi.py                 # 原始 TEAVAR 隧道分流（纯 WAN，无算力）
├── duibi.py                         # Physical CVaR：Model A/B/C/D
├── cvar_compare.py                  # SLA 核心：build_teavar_sla_cvar_model()
├── teavar_framework_models.py       # SLA Model A/B/C/D
├── progressive_pipeline.py          # 递进 A→C→B→D（非「先 y 后 x」双层求解器）
├── b4_joint_data.py                 # load_b4_joint_data + load_joint_data（多拓扑）
├── duibi_metrics.py                 # 指标 + ensure_link_prices / bandwidth_cost_expr
├── parsers.py / util.py             # 拓扑/需求/Weibull 场景
├── generate_compute_resources.py    # 多拓扑算力 CSV 自动生成
├── monetary_cvar.py                 # ★ Model M + Model M-C + compare + bisect + CLI
├── model_m_monetary_cvar.py         # ⚠ 已合并遗留，勿作入口
├── experiment_report.py             # 玩具+B4 实验 CSV/PNG
├── plot_duibi_*.py / experiment_report.py
├── data/                            # B4 + ATT/IBM/… + raw/
├── 建模章节_算力网络联合优化.md       # ★ 论文章节 SSOT
├── 项目总结_模型AC.md                # ★ Model A/C 公式 SSOT
├── 建模_货币化纯CVaR.md              # ★ Model M/M-C SSOT
├── 论文初稿.md                       # ⚠ 部分仍写「可选 sf」/ hop，待同步
├── 建模公式说明.md                   # ⚠ 部分待同步
├── 改进报告.md / AEGIS.md / …
└── README.md
```

**历史/对照脚本（brief 主树外）**：`pro.py`、`copo_CVaR.py`、`copo_cvar01.py`、`teavar_cete.py` 等，非当前主线。

---

## 二、三篇参考论文

（与 v2 相同，略）

| 论文 | 借鉴 | 不采用 |
|------|------|--------|
| TEAVAR | RU 线性化、K 短路、离散场景 | 纯 WAN、无算力 |
| Copo | 放置+带宽联合、KKT 验证 | 区域流；McCormick 作主求解 |
| AEGIS | CVaR 约束、δ_min、二分 Γ | Flow-based 弧变量（当前仍 path-based） |

---

## 三、核心建模框架

### 3.1 问题设置与路由语义（论文 vs 代码）

**论文标准**（**代码目标，阶段 1 完成后为默认**）：每任务 $i$ 有源 $s_i$、宿 $t_i$，两阶段路由

$$s_i \xrightarrow{\text{ingress}} m \xrightarrow{\text{egress}} t_i$$

**当前代码实现**（阶段 1 完成前，可运行特例）：
- **Hub 径向**（**退化模式**）：`teavar_flow_anchors(data)` → $(h,h)$，路径 $\mathcal{P}_{h,m}$、$\mathcal{P}_{m,h}$
- **UMCF 全局**：显式 $(V_s, V_t)$，**所有任务共用**同一锚点对（阶段 2 将改为 per-task）

**必做演进**（`最终路线图.md` §四·补）：

| 阶段 | 能力 | 状态 |
|------|------|------|
| 0 | `task_src/dst`、`routing_mode`、`valid_assign` per-task | ⬜ |
| 1 | per-task OD 全 MILP 链路 | ⬜ |
| 2 | UMCF per-task $(V_s^{(i)}, V_t^{(i)})$ | ⬜ |
| 3 | 微服务 DAG（链式 MVP → 一般 DAG） | ⬜ |
| 4 | 主实验默认 per_task_od + 部分 σ + η | ⬜ |

> **demand 已有信息**：`hub_pairs` 中 `(vol, dst)` 的 **dst 即 $t_i$**；阶段 0 起不再仅用于标定 $b^{\mathrm{in/out}}$。  
> **Hub 径向**：保留作 `--routing-mode hub` 回归/消融，**不是**论文唯一实现。

每任务选**一个**执行节点 $m$（$y_{im}$）；ingress/egress **可多路径**分割。

### 3.2–3.3 场景与异构算力

（与 v2 相同：3 场景 $\pi=\{0.6,0.3,0.1\}$；CPU/GPU/HBM；Core/Agg/Edge 角色定价。）

### 3.4 决策变量

（与 v2 相同；算力块变量在 `lambda_compute_sf_cvar>0` 或 Model M 的 `kappa_sf>0` 时实例化。）

---

## 四、度量体系

### 4.1 放置成本

$$c_p = \sum_{i,m} y_{im} \sum_k w_{ik}\,\pi_{mk}$$

与场景无关。

### 4.2 带宽成本（流量 × 链路单价）

链路单价 $\pi_e$（`data.link_price`，`ensure_link_prices` 生成；B4 默认 $\pi_e \propto 1/B_e$）。

$$\tau_p = \sum_{e\in p} \pi_e$$

| 模型 | 带宽费 |
|------|--------|
| **SLA Model A/C**（目标） | $c_b = \sum x^{\mathrm{in/out}} \cdot \tau_p$（**计划流量** $x$，不随 $s$） |
| **Physical** | 同左（基于 $x$） |
| **Model M** | $c_b(s) = \sum d^{\mathrm{in/out}}_{s} \cdot \tau_p$（**场景送达** $d$） |

注：若所有 $\pi_e=1$，则 $\tau_p=|p|$（与旧 hop 计费数值一致）。

### 4.3 期望送达与 $C_{\mathrm{tot}}$（仅 SLA A/C）

$$\mathbb{E}[\mathrm{Del}] = \sum_s \pi_s \sum_{i,m,p,q}(d^{\mathrm{in}}+d^{\mathrm{out}}),\quad
C_{\mathrm{tot}} = c_p + c_b - \omega\,\mathbb{E}[\mathrm{Del}]$$

Model M **无** $\omega$（Shortfall 罚金已货币化进 $L_s$）。

### 4.4 网络侧 $\mathrm{CVaR}^{\mathrm{SLA}}$

（与 v2 相同：逐任务 $(s,i)$ 比例探测，同一 $u_s$。）

### 4.5 算力侧 $\mathrm{CVaR}^{\mathrm{sf}}$

**论文 Method：必选**（算网联合第二支柱）。**代码**：`lambda_compute_sf_cvar=0` 时不构建该块 → **仅消融**。

$$D_{mk}=\sum_i w_{ik}y_{im},\quad e_{mks}=\max(0,\,D_{mk}-C^N_{mks}) \text{（Big-M）}$$

**场景标量**（与代码一致）：

$$L^{\mathrm{sf}}_s = \max_{m,k}\frac{e_{mks}}{D_{\mathrm{ref}}},\quad
\phi_s \ge L^{\mathrm{sf}}_s - \zeta_{\mathrm{sf}} \;\Leftrightarrow\; \phi_s \ge \frac{e_{mks}}{D_{\mathrm{ref}}} - \zeta_{\mathrm{sf}}$$

$D_{\mathrm{ref}}=M_{\mathrm{ex}}$ 为全局常数上界（非 $C^N_{mks}$ 逐维归一化）。

$$\mathrm{CVaR}^{\mathrm{sf}} = \zeta_{\mathrm{sf}} + \frac{1}{1-\beta_{\mathrm{sf}}}\sum_s \pi_s \phi_s$$

---

## 五、约束（Model A/C 可行域）

### 5.1 单点放置：$\sum_m y_{im}=1$

### 5.2 流量激活（分模型）

| 模型 | 约束 |
|------|------|
| **SLA**（`cvar_compare`） | $\sum_p x^{\mathrm{in}}_{i,m,p} \le y_{im} b^{\mathrm{in}}_i$（egress 对称 **$\le$**） |
| **Physical**（`duibi`） | 同上但为 **$=$**（拉满管道） |

### 5.3–5.5

名义链路/算力容量；$d$–$x$–路径 Big-M；可选 $\sigma^{\mathrm{vs}}$、UMCF、$\delta_{\min}$。

（与 v2 相同。）

---

## 六、优化模型体系

### 6.1 SLA 主线（Model A / C）

**Model A：**

$$\min\; c_p + c_b - \omega\mathbb{E}[\mathrm{Del}] + \lambda_{\mathrm{sla}}\mathrm{CVaR}^{\mathrm{SLA}} + \lambda_{\mathrm{sf}}\mathrm{CVaR}^{\mathrm{sf}}$$

**Model C：**

$$\min\; c_p + c_b - \omega\mathbb{E}[\mathrm{Del}] \quad
\text{s.t.}\; \mathrm{CVaR}^{\mathrm{SLA}}\le\Gamma_{\mathrm{sla}},\; \mathrm{CVaR}^{\mathrm{sf}}\le\Gamma_{\mathrm{sf}}$$

A 标定 $\Gamma$；C 作部署主结果。**同一可行域、同一条 Pareto 前沿**。

### 6.2 辅助：B（KKT 验证）/ D（McCormick，**正文舍弃**）

Model D：事后 CVaR 可偏 ~210%，仅附录一句消融。

### 6.3 货币化扩展（Model M / M-C）

**实现入口：`monetary_cvar.py`**

$$L_s = c_p + c_b(s) + \kappa_{\mathrm{sum}}\mathrm{Shortfall}^{\mathrm{sum}}_s + \kappa_{\mathrm{max}}\mathrm{Shortfall}^{\mathrm{max}}_s + \sum_{m,k}\kappa^{\mathrm{sf}} e_{mks}$$

| 模型 | 目标 |
|------|------|
| **M** | $\min \mathrm{CVaR}_\beta(L)$ |
| **M-C** | $\min \mathbb{E}[L_s]$ s.t. $\mathrm{CVaR}_\beta(L)\le\Gamma_{\mathrm{money}}$ |

**与 A 对比**：`compare_with_model_a` + 统一 $\kappa$ 事后 `recompute_monetary_bills`（⚠ 见 §0.9 bug）。

**M vs A 结构性差异**：M 默认 Shortfall **求和**；A 为**逐任务**比例 max → 总量相同、分布不同时 CVaR 驱动不同。

### 6.4 双层分解（设计阶段，未实现）

按决策速度分层：**慢层 $y$ / 快层 $x,d$**。注意：
- 快层在固定 $y$ 后**不一定是纯 LP**（多场景 $d$、算力 Big-M 仍可能有整数）
- 慢层须保留 **valid_assign / 路径可达** 否则可能选不可达节点
- 与 `progressive_pipeline`（A→C→B→D 同可行域换目标）**不是同一回事**

单层 Model A/C = **理论基准**；双层 = **可部署近似 + optimality gap 实验**（未来）。

---

## 七、实现状态矩阵

| 组件 | 位置 | 状态 | 备注 |
|------|------|------|------|
| SLA Model A | `cvar_compare.build_teavar_sla_cvar_model` | ✅ | 双 CVaR 需显式开 $\lambda_{\mathrm{sf}}$ |
| SLA Model C | `teavar_framework_models.build_teavar_model_c` | ✅ | 已进 `main.py`（`--joint-run-model-c`） |
| Model B / D | `teavar_framework_models` | ✅ / ⚠ | D 不主用 |
| Physical A/C | `duibi.py` | ✅ | `main.py joint` 只跑 Physical A |
| **Model M + M-C** | **`monetary_cvar.py`** | ✅ 完整 | `main.py --mode monetary`；`--monetary-compare-a` |
| 遗留 M 副本 | `model_m_monetary_cvar.py` | ⚠ 归档 | 已标注合并 |
| 带宽 $\tau_p$ | `duibi_metrics` + 各 builder | ✅ | MILP 与 `recompute_monetary_bills` 一致 |
| 多拓扑 load | `load_joint_data` | ✅ | joint / monetary 经 `main._load_joint_data_from_args` |
| OD $s_i\to t_i$ | — | ⬜ **阶段 1 必做** | 当前 hub/UMCF 全局特例 |
| UMCF per-task | — | ⬜ **阶段 2 必做** | 当前仅 global $(V_s,V_t)$ |
| 双层求解器 | — | ❌ | 设计文档；**下一篇 P2-2** |
| DAG 微服务 | `未来扩展_微服务DAG.md` | ⬜ **阶段 3 必做** | → `dag_sla_model.py` |
| 实验报告 | `experiment_report.py` | 🟡 部分 | 玩具+B4；无 9 拓扑矩阵 |
| 测试/CI | `tests/test_smoke.py` | 🟡 部分 | 4 项冒烟；待 `test_per_task_od` / `test_dag_chain` |

### `main.py` 实际能力

| `--mode` | 行为 |
|----------|------|
| `teavar` | 原 TEAVAR_Gurobi + Weibull 多场景 |
| `joint` | `load_joint_data` + 对每个 $\lambda$：**Physical A** + **SLA A**（默认 $\lambda_{\mathrm{sf}}=1$） |
| `monetary` | `load_joint_data` + Model M/M-C；`--monetary-compare-a` 为 A vs M vs M-C |

**仍未包含**：Model C 批量、多拓扑循环脚本（见 `experiment_report.py`）。

---

## 八、数据集

### B4（主实验）

12 节点 38 边；`topology.txt` / `demand.txt` / `node_compute_resources.csv`；3 场景。

### 九拓扑（`load_joint_data`）

| 拓扑 | 节点 | 边 | 状态 / blocker |
|------|------|-----|----------------|
| B4 | 12 | 38 | ✅ 主实验 |
| ATT | 25 | 112 | ✅ |
| IBM | 17 | 46 | ✅ |
| Abilene | 12 | 30 | ✅ |
| Custom | 6 | 18 | ✅ |
| Sprint | 11 | 36 | ⚠ 0-based 索引需确认 |
| XNet | 28 | 76 | ⚠ 缺 prob_failure |
| Nextgen | 17 | 38 | ⚠ demand.txt 空 |
| Custom2 | 5 | 14 | ⚠ hub=0 可能无出向需求 |

算力 CSV：缺失时 `load_joint_data(auto_generate_compute=True)` 可自动生成。

---

## 九、已知结果（摘要）

- 玩具：A↔C 同 Pareto；B gap=0%；D CVaR +210%
- SLA 退化：全堆 hub + 空路径 → $\mathrm{CVaR}^{\mathrm{SLA}}=0$；需 stress / UMCF / min_off_hub
- Physical vs SLA：拥塞 vs 用户未满足，不可互换
- B4：`monetary_cvar.py --compare-a` 可跑通；统一 $\kappa$ 下 A vs M vs M-C 可对比

---

## 十、不足与待办（按优先级）

### 🔴 影响论文可信度

1. **文档分裂**：`论文初稿.md` 仍「可选 sf」、hop 带宽 → 同步 SSOT  
2. ~~**`recompute_monetary_bills` 用 hop**~~ → ✅ 已修（`scenario_bandwidth_cost_value`）  
3. **主实验 $\lambda_{\mathrm{sf}}$**：`main.py joint` 默认 $=1$；消融用 `--joint-ablation-no-compute-sf`  
4. **Hub vs $s_i\to t_i$** → **per-task OD 为必做实现**（阶段 1）；hub 写为 **§3 退化特例**（见 `最终路线图.md` §二·补、§四·补）  

### 🟡 工程

5. `main.py` 扩展：**monetary ✅**；**Model C ✅**（`--joint-run-model-c`）；多拓扑 batch **`run_batch_experiments.py`** 🟡  
6. 多拓扑 blocker（Nextgen demand、XNet prob、Sprint 索引）→ **XNet prob ✅**；合成 demand ✅；**`assess_topology_readiness`** ✅  
7. ~~Model M 集成 `--mode monetary`~~ → ✅  
8. 冒烟测试 **`tests/test_smoke.py`** ✅；CI 仍待做  

### 🟢 长期（下一篇）

9. Path-based → flow-based（Future Work，P2-3）  
10. 双层分解实现 + gap 实验（P2-2）  

> **DAG / per-task OD / UMCF per-task** 已从本节移出 → **`最终路线图.md` §四·补 阶段 1–3（必做）**

---

## 十一、目标与路线图（修订 — 对齐 `最终路线图.md` v1.4）

### 能力实现（必做，约 3–4 周）

- [ ] **阶段 0**：`task_src/dst`、`routing_mode`、`teavar_flow_anchors(data,i)`、`valid_assign`  
- [ ] **阶段 1**：per-task OD 全链路（`cvar_compare` / A/C / Physical / M）+ `--joint-per-task-od`  
- [ ] **阶段 2**：`attach_umcf_per_task` + `--joint-umcf-per-task`  
- [ ] **阶段 3a**：链式 DAG MVP（`dag_sla_model.py`、`task_dag_templates.py`）  
- [ ] **阶段 3b**：一般 DAG 读入 + fork/join  
- [ ] **阶段 4**：主实验默认 per_task_od；消融 hub / per_task_od / umcf_per_task / dag_chain  

### P0 实验装置（与阶段 4 合并，**依赖阶段 1**）

- [ ] 部分 σ + η 标定 + `run_gamma_frontier.py` + `p0_acceptance.py`  
- [ ] B4 旗舰图 + ATT 一点 + 单 vs 双 CVaR 消融  
- [ ] 三文档 SSOT 同步（论文初稿 + 建模章节 + brief_v3）  

### P1 投稿润色

- [ ] M/M-C 附录 + Physical 附录 + η/ω 敏感性 + 多拓扑 scaling  

### 下一篇（P2）

- [ ] 双层分解（P2-2）  
- [ ] flow-based（P2-3）  

### 已完成（历史）

- [x] 修 §0.9 monetary 事后 $\tau_p$  
- [x] `main.py`：`load_joint_data` + `--mode monetary`  
- [x] Model C 进 `main.py`（`--joint-run-model-c`）  
- [x] `tests/test_smoke.py` 4 项冒烟  

---

## 十二、推荐论文实验结构

| 位置 | 内容 |
|------|------|
| **主表** | B4，**per-task OD 默认**，Model **C**（$\Gamma$ 从 A 标定），双 CVaR **开**，vs Physical |
| **主文图** | CVaR$^{\mathrm{SLA}}$ × CVaR$^{\mathrm{sf}}$ 旗舰前沿（部分 σ + η） |
| **消融** | hub 退化 vs per_task_od vs umcf_per_task vs dag_chain；$\lambda_{\mathrm{sf}}=0$ |
| **附录** | Model M/M-C；旧 global UMCF vs hub；Physical hub-stress foil |
| **不放主结果** | Model D；McCormick 一句带过 |
| **Discussion** | path-based 扩展性；双层 / flow-based 为 future deployment |

---

## 十三、给 Claude 的任务（更新）

1. **优先执行阶段 0→1**（per-task OD）：`b4_joint_data` + `teavar_flow_anchors(data,i)` + `cvar_compare` 冒烟  
2. 阶段 2–3 与 P0 实验装置（部分 σ、η、Γ 网格）**阶段 1 通后并行**  
3. flow-based / 双层：**P2 Future Work**，不绑阶段 1  
4. 同步 `论文初稿.md`：§3 一般 OD + DAG 为**本文实现**；hub 为退化对照  

---

*文档版本：v3.3 | 2026-06-03：对齐 `最终路线图.md` v1.4 — 能力阶段 0–4 升格必做；hub 降为退化模式*
