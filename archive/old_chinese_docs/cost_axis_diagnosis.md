# Phase C-0：Formal P0 Cost-Axis Determinacy Check

**日期：** 2026-06-04  
**脚本：** `scripts/diagnose_cost_axis.py`  
**JSON 明细：** `results/p0_uniform_v2/cost_axis_diagnosis.json`  
**约束：** 不改 $D_{ref}$、不改风险语义、不改 Model C 主语义；仅诊断 reporting 轴稳定性。

---

## 执行摘要

| 项目 | 结论 |
|:---|:---|
| **推荐方案** | **方案 2**：风险图可用，cost 轴暂缓 |
| **posthoc 风险 SSOT** | `p0_gamma_frontier_b4_tasks8.csv` 的 posthoc SLA/SF **可用于论文风险维** |
| **monetary_cost 轴 SSOT** | **暂不可直接用于论文 cost 维**；需 secondary costing 或明确标注为"零 hop 代表解" |
| **路径构造** | 无 `u≠v` 空路径异常；12 条合法 zero-hop local path |
| **cost 表达式** | 无漏算；`bandwidth_cost = Σ τ_p x` 与正 x 一致 |
| **耦合约束** | `d ≤ x`、`d ≤ x·path_up` 全部满足；无 `d>0` 且无 x 支撑 |

---

## 任务 A：四个诊断点明细

### A.1 `(Γ_sla=1.0, Γ_sf=0.030)`

| 字段 | 值 |
|:---|:---|
| objective / obj_val | −4060.266 |
| monetary_cost | **160.96** |
| compute_cost | 160.96 |
| bandwidth_cost | **0.0** |
| expected_delivery | 4221.23 |
| posthoc_cvar_sla | 1.0 |
| posthoc_cvar_sf | 0.0209 |
| placement | `0:4\|1:5\|2:3\|3:2\|4:10\|5:6\|6:5\|7:4` |

**正 x 的 ingress（全为 zero-hop，`τ=0`）：**

| task | node | src→node | path | x |
|:---:|:---:|:---|:---|---:|
| 0 | 4 | 4→4 | `[]` | 1699.27 |
| 1 | 5 | 5→5 | `[]` | 1035.46 |
| 4 | 10 | 10→10 | `[]` | 522.76 |
| 6 | 5 | 5→5 | `[]` | 378.42 |
| 7 | 4 | 4→4 | `[]` | 321.93 |

**正 x 的 egress：**

| task | node | node→dst | path | x |
|:---:|:---:|:---|:---|---:|
| 3 | 2 | 2→2 | `[]` | 263.39 |

**路径用量统计：**

- 目录中空路径条目（含 catalog）：6
- 正 x 且 τ=0 的路径条目：6
- 零成本路径上 x 总量：**4221.23**（≈ expected_delivery）
- 零成本路径上送达量：**12663.68**（三场景 ingress+egress 求和）

---

### A.2 `(Γ_sla=1.0, Γ_sf=0.0377)`

| 字段 | 值 |
|:---|:---|
| monetary_cost | 149.56 |
| bandwidth_cost | 0.0 |
| expected_delivery | 4323.66 |
| posthoc_cvar_sf | 0.0377 |
| placement | `0:4\|1:5\|2:6\|3:4\|4:10\|5:3\|6:5\|7:5` |

正 x 仍全部落在 **src=node 或 node=dst** 的 zero-hop 空路径（τ=0）。task 7 在 node 5，egress 5→5 空路径 x=160.97。

---

### A.3 `(Γ_sla=0.9, Γ_sf=0.030)`

| 字段 | 值 |
|:---|:---|
| monetary_cost | 1064.27 |
| compute_cost | 160.96 |
| bandwidth_cost | **903.31** |
| expected_delivery | 4632.40 |
| posthoc_cvar_sf | 0.0209 |
| placement | `0:4\|1:5\|2:6\|3:2\|4:10\|5:3\|6:5\|7:4` |

**混合模式：** 5 条 zero-hop ingress（τ=0）+ 多条 **非空 egress**（τ∈{1,2,3,4}）承载对外送达。说明同一 MILP 在不同 Γ 下会选择不同 x 代表点。

---

### A.4 `(Γ_sla=0.8, Γ_sf=0.030)`

| 字段 | 值 |
|:---|:---|
| monetary_cost | 1967.59 |
| bandwidth_cost | **1806.63** |
| expected_delivery | 5043.58 |
| posthoc_cvar_sf | 0.0209 |
| placement | 同 0.9/0.03 |

egress 非空路径 x 更大（如 task 0 四条 egress 各 x≈42.5，τ=4），带宽费显著。

---

## 任务 B：空路径语义审计（`P_cand` 全表）

| 检查项 | 数量 | 判定 |
|:---|:---:|:---|
| `u==v` zero-hop local path（`[]`，τ=0） | **12** | **合法** colocated local service |
| `u!=v` 但 edge list 为空 | **0** | 无路径构造 bug |
| 非空路径 τ=0 | **0** | 无 link price bug |
| τ 缺失 / 默认 0 的非空路径 | **0** | 无 |

**语义说明（代码 `b4_joint_data`）：** 对每个 `(u,v)`，`u==v` 时 `P_cand[u,v]=[[]]`；`u!=v` 时为 k-shortest **非空** 路径列表。`path_bandwidth_tariff` 对空 path 返回 0。

---

## 任务 C：Cost–Delivery 耦合检查

对四个诊断点统一结果：

| 检查 | 结果 | 分类 |
|:---|:---|:---|
| 1. `Del_{i,s}>0` ⇒ 存在对应正 x | **成立**（`del_positive_without_positive_x = 0`） | — |
| 2. `d_in ≤ x_in`（路径可用时） | **成立**（`d_exceeds_x = 0`） | — |
| 3. `d_out ≤ x_out` | **成立** | — |
| 4. `bandwidth_cost` 覆盖所有正 x | **成立**（手动 Στx = Gurobi `cost_b`） | — |
| 5. 正送达但 charged x=0 或 τ=0 | **存在**（18 条/点，`del_on_zero_tau_paths`） | **合法 colocated zero-cost** + **多最优 x** |

**不存在：**

- cost expression 漏算（方案 3 否）
- flow-delivery coupling bug（`d>x` 为 0）
- `u≠v` empty path bug

**存在：**

- **多最优 x 分配**：固定 y 与相同 posthoc 风险时，求解器可选"全 zero-hop x"（Γ=1.0）或"zero-hop ingress + 付费 egress"（Γ=0.8/0.9），导致 monetary_cost 不唯一。

---

## 任务 D：Smoke vs 当前 SSOT 候选对比

**对照文件：**

- Smoke：`results/temp_smoke_posthoc_gamma/uniform_frontier_b4_tasks8_posthoc_gamma.csv`
- SSOT 候选：`results/p0_uniform_v2/p0_gamma_frontier_b4_tasks8.csv`
- Smoke 路径分解参考：`results/temp_smoke_posthoc_gamma/model_c_gamma_diagnostic.csv`

| Γ 点 | placement 一致 | smoke cost | SSOT cost | Δcost | smoke exp_del | SSOT exp_del | posthoc SF 一致 | 差异来源 |
|:---|:---:|---:|---:|---:|---:|---:|:---|:---|
| (1.0, 0.03) | **是** | 1429.16 | 160.96 | −1268 | 5489.43 | 4221.23 | **是** | **带宽**（smoke bw≈1268，SSOT bw=0） |
| (1.0, 0.0377) | **是** | 1717.93 | 149.56 | −1568 | 5892.02 | 4323.66 | **是** | **带宽** |
| (0.9, 0.03) | **是** | 2330.94 | 1064.27 | −1267 | 5899.07 | 4632.40 | **是** | **带宽**（903 vs 2170） |
| (0.8, 0.03) | **是** | 3009.99 | 1967.59 | −1042 | 6058.14 | 5043.58 | **是** | **带宽**（1807 vs 2849） |

**compute_cost：** 四点上 smoke 与 SSOT 均为 **160.96 或 149.56**（仅 placement 变化时 compute 变），**一致**。

**关键观察（Phase B++ diagnostic 交叉验证）：**

- Smoke 在 `(1.0, 0.03)`、placement `7:4` 相同条件下，Phase B++ 曾记录 **bandwidth=1268**、monetary=1429；
- 当前重求解同 placement 得 **bandwidth=0**、monetary=161；
- posthoc SF/SLA **相同** → 证实 **x 多最优**，非 y 或风险语义差异。

**路径级差异（(1.0,0.03)）：**

- Smoke / Phase B++：ingress 走 zero-hop，**egress 对 dst≠node 的任务走非空路径**（产生带宽费）；
- 当前 SSOT 求解：**仅 task 3 egress 2→2 zero-hop 有正 x**；对外 dst 的 egress x 为 0，送达由 ingress zero-hop 路径上的 `d_in` 承担（耦合合法但成本为 0）。

---

## 任务 E：处理建议 — **方案 2**

### 方案 1（否）：当前 cost 可直接使用

不满足：低 cost 虽来自合法 zero-hop，但 **同 placement 下 cost 可在 [161, 1429] 间漂移**，不满足论文 cost 轴确定性。

### 方案 2（**是**）：风险图可用，cost 图暂缓

- posthoc SLA/SF、placement、Pareto 结构 **稳定**；
- monetary_cost 受 x 多最优影响 **大**（Γ=1.0 点可差 ~8×）；
- 需 **secondary costing** 后再画 cost 轴。

### 方案 3（否）：必须修 MILP / cost expression

- 无 `u≠v` 空路径；
- 无 `d>x` 或 `d>0` 无 x；
- 无非空 τ=0；
- `bandwidth_cost_expr` 无漏算。

---

## 任务 F：Secondary Costing 方案设计（仅设计，未实现）

**Stage 1（已有）：** Model C 求 $(y, x, d)$ 满足 CVaR 预算与目标  
$\min C^{money} - \omega_{del}\mathbb{E}[\mathrm{Del}]$。

**Stage 2（建议）：** 固定

- $y_{im}$（placement）
- 各场景/task 已达成的 $d_{imp,s}^{in}, d_{imp,s}^{out}$（或 $\mathrm{Del}_{i,s}$ 总量）

求解：

$$
\min \sum_{i,m,p} \tau_p x_{imp}^{in} + \sum_{i,m,q} \tau_p x_{imp}^{out}
\quad \text{s.t.}\quad d \leq x,\; d \leq \mathbb{1}[path_up]\cdot x
$$

或 $\min C^{money}$（含 compute，但 compute 已由 y 固定）。

| 属性 | 说明 |
|:---|:---|
| 是否改变 y | **否** |
| 是否改变 posthoc CVaR | **否**（若 d 固定） |
| 是否改变 Model C 目标 | **否**（reporting 层） |
| 论文图适用性 | 作为 **"minimum-bandwidth representative cost"** 副轴，与 Model C obj 轴区分标注 |

---

## 最终判定

### 1. `p0_gamma_frontier_b4_tasks8.csv` 可否作为论文 **cost-risk** 图 SSOT？

| 维度 | 可否 | 说明 |
|:---|:---|:---|
| **Risk（posthoc SLA / SF）** | **可以** | 与 Phase B+ gate 一致，formal PASS |
| **Cost（monetary_cost）** | **暂不可以** | 多最优 x 导致轴不稳定；与 smoke 差可达 ~1268（带宽） |
| **联合 cost-risk 图** | **暂缓** | 采用方案 2 + secondary costing 后再定稿 |

### 2. 下一步

1. 实现 secondary costing reporting（不改 MILP）；
2. 对 25 点 grid 生成 `monetary_cost_min_bw` 列；
3. 用 posthoc 风险 + min-bw cost 重绘 Pareto；
4. 在图注中区分 Model C objective 与 representative monetary cost。

---

## 附录：耦合检查计数（四点合计）

| 指标 | 值 |
|:---|:---|
| `del_positive_without_positive_x` | 0 |
| `d_exceeds_x` | 0 |
| `positive_x_zero_tau`（正 x 且 τ=0） | 24 |
| `del_on_zero_tau_paths` | 72 |
| `anomaly_empty_paths_in_P_cand` | 0 |

完整路径表见 `cost_axis_diagnosis.json` → `p_cand_audit`, `point_diagnostics`.
