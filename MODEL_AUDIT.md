# MODEL_AUDIT.md

> Generated 2026-06.  Read-only audit — do not modify.

---

## 1. 模型入口函数与文件路径

| 模型 | Builder 函数 | 文件 | Solver |
|:--|:--|:--|:--|
| **M0** | `build_m0_model(data, lambda_m0=0.5)` | `refactor/m0_models.py:197` | 无专用 solver (直接 `.optimize()`) |
| **M1** | `build_m1_model(data, *, quiet, time_limit, mip_gap)` | `refactor/m1_models.py:117` | `solve_m1_model(model)` :328 |
| **M2-Service-Lex** | `build_m2_lex(data, ...)` (no-op) | `refactor/m2_models.py:260` | `solve_m2_lex(data, ...)` :276 |
| **M2-C** | `build_m2_model_c(data, gamma, *, alpha, quiet, ...)` | `refactor/m2_models.py:158` | `solve_m2_model_c(model)` :192 |
| **Toy-2Task** | `build_toy_2task_independent_v1(...)` | `toy_two_task_independent_data.py:394` | — |

---

## 2. M0 变量

| 变量 | 类型 | 含义 |
|:--|:--|:--|
| `y[i,m]` | Binary | 任务 i 是否部署在节点 m |
| `xin[i,m,p]` | Continuous ≥ 0 | 计划 ingress 路径流量 |
| `xout[i,m,q]` | Continuous ≥ 0 | 计划 egress 路径流量 |
| `U_link` | [0,1] | 全局最大链路利用率 (epigraph) |
| `U_node` | [0,1] | 全局最大节点资源利用率 (epigraph) |

## 3. M1 变量（M0 变量 + 以下场景变量）

| 变量 | 类型 | 含义 |
|:--|:--|:--|
| `y[i,m]` | Binary | 放置 (同 M0) |
| `r[i,m,s]` | [0, y[i,m]] | 场景 s 下任务 i 在节点 m 的服务比例 |
| `z[i,s]` | [0,1] | 场景 s 下任务 i 的端到端服务比例 |
| `xin_s[i,m,p,s]` | ≥ 0 | 场景 s 下 ingress 路径流量 |
| `xout_s[i,m,q,s]` | ≥ 0 | 场景 s 下 egress 路径流量 |

M1 中**没有**计划流量变量 `xin[i,m,p]` / `xout[i,m,q]`（即 M0 的诊断流量变量不存在于 M1 模型中）。

## 4. M2 变量

M2 不新增变量。复用 M1 的 `y, r, z, xin_s, xout_s`，外加 CVaR 线性化变量：

| 变量 | 类型 | 含义 |
|:--|:--|:--|
| `η` | [0,1] | VaR 阈值 |
| `u_s[s]` | [0,1] | 场景 s 尾部超额 |

M2 中**没有**：
- 计划流量 `x^0` / 预留容量变量
- 成本变量 (placement cost, bandwidth cost)
- 期望服务变量（仅 LinExpr，非 Var）

---

## 5. 目标函数

| 模型 | 目标 | 方向 | 行 |
|:--|:--|:--|:--|
| **M0** | `min λ·U_link + (1-λ)·U_node` | MIN | `m0_models.py:249` |
| **M1** | 无（feasibility-only 默认）；可选 `set_m1_objective(mode="max_service")` | — | `m1_models.py:117` |
| **M2-C** | `max Σ_s π_s · Σ_i θ_i D_i · z[i,s]`（期望加权服务） | MAX | `m2_models.py:183` (via `add_m1_max_service_objective`) |
| **M2-Lex(P1)** | `min CVaR_α(L)` | MIN | `m2_models.py:297` |
| **M2-Lex(P2)** | `max Σ_s π_s · Σ_i θ_i D_i · z[i,s]`，固定 CVaR ≤ P1 最优值 | MAX | `m2_models.py:318` |

关键：**当前所有 M2 目标都不含成本**。M2-C / M2-Lex 都是服务最大化，成本为零。

---

## 6. 约束列表

### M0 约束（`m0_models.py:197-278`）
1. 唯一放置：`Σ_m y[i,m] = 1`
2. 输入流量守恒：`Σ_p xin[i,m,p] = b_in[i] · y[i,m]`
3. 输出流量守恒：`Σ_q xout[i,m,q] = b_out[i] · y[i,m]`
4. 链路容量：`LinkLoad_e ≤ B_e · U_link`
5. 节点容量：`Σ_i y[i,m] · w[i,k] ≤ C_normal[m][k] · U_node`
6. U_link ∈ [0,1], U_node ∈ [0,1]

### M1 约束（`m1_models.py:169-251`）
1. 唯一放置：`Σ_m y[i,m] = 1`
2. 服务比例上界：`r[i,m,s] ≤ y[i,m]`
3. 服务比例聚合：`z[i,s] = Σ_m r[i,m,s]`
4. 场景输入流量守恒：`Σ_p xin_s[i,m,p,s] = b_in[i] · r[i,m,s]`
5. 场景输出流量守恒：`Σ_q xout_s[i,m,q,s] = b_out[i] · r[i,m,s]`
6. 场景链路容量：`LinkLoad_{e,s} ≤ B_e · sigma[e][s]`
7. 场景计算容量：`Σ_i r[i,m,s] · w[i,k] ≤ C_s[m][k][s]`

### M2 新增约束
- `CVaR_α(L) ≤ γ`（M2-C 专用，`m2_models.py:180`）
- `u_s ≥ L_s - η`（CVaR 线性化）
- M2-Lex(P2)：`CVaR ≤ P1_opt + tol`（`m2_models.py:315`）

M2 中**没有**：
- `z[i,s0] = 1`（正常场景全服务约束）
- `E[z] ≥ ρ`（期望服务下限）
- 任何成本相关约束

---

## 7. Toy-2Task-IndependentComponentRisk-v1 pipeline 接入状态

**当前状态：standalone，未接入任何 runner / pipeline。**

- `build_toy_2task_independent_v1()` 只被 `tests/test_toy_two_task_independent_data.py` 和 `scripts/run_toy_2task_tests_v2.py` 调用。
- 未被 `run_toy_te_validation.py`、`run_gamma_frontier.py`、`refactor/main.py`、`refactor/m0_instances.py` 引用。
- 不在 `scripts/run_parity_matrix.py` 中。
- 兼容 M1 接口需要以下适配层（已部分添加）：`P_cand`（property）、`sigma`（property）、`C_s` 转 M1 格式（`C_s[m][k][s]`）。

---

## 8. Scenario Pruning 实现方式

### 当前实现（`toy_two_task_independent_data.py:250-318`）

1. **方法**：drop + renormalize
2. **保留规则**：故障组件数 ≤ `max_failed_components`（默认 3）
3. **概率处理**：`pi[s] = p_raw / original_mass`（重归一化到 1.0）
4. **元数据记录**：
   - `"original_probability_mass"`: 保留部分原始概率和（≈0.997854）
   - `"dropped_probability_mass"`: 丢弃部分概率和（≈0.002146）
   - `"renormalized"`: True
   - `"num_scenarios"`, `"scenario_mode"`, `"max_failed_components"`
5. **无 aggregate worst-case scenario**：被丢弃的场景被直接忽略，未合并为一个 loss=1 的聚合场景。

---

## 9. M2 中是否存在 `x^0` / nominal reservation variables

**不存在。**

- M0 有 `xin[i,m,p]` / `xout[i,m,q]`（计划流量 / 诊断流量）。
- M1 和 M2 完全使用 `xin_s[i,m,p,s]` / `xout_s[i,m,q,s]`（场景流量），没有任何名义预留变量。
- M1 是 pure adaptive recourse：每个场景独立决定全套路由。
- 无 `h_e` 预留容量，无 `x^0` → `x_s` 之间的耦合。

---

## 10. 当前 M2-Service / M2-Lex 的 loss 定义

文件 `refactor/m2_models.py:88-150`，函数 `add_end_to_end_cvar()`：

```
L_s = Σ_i θ_i · D_i · (1 - z[i,s]) / Σ_i θ_i · D_i
```

其中：
- `θ_i`：任务优先级（默认 1.0）
- `D_i`：需求权重（默认 1.0，来自 `data.D_i` 或 `{i:1.0}`）

**当前默认值**：`θ_i = 1, D_i = 1` → `L_s = (1/N) · Σ_i (1 - z[i,s])`（等权平均）。

---

## 11. 当前 M2 已有的 / 缺失的约束

| 特性 | 当前状态 | 位置 |
|:--|:--|:--|
| Placement cost `c_p` | ❌ 缺失 | — |
| Bandwidth cost `c_b` | ❌ 缺失 | — |
| CVaR budget `CVaR ≤ γ` | ✅ M2-C 有 | `m2_models.py:180` |
| Normal full service `z[i,s0]=1` | ❌ 缺失 | — |
| Expected service floor `E[z] ≥ ρ` | ❌ 缺失 | — |
| Max expected service objective | ✅ M2-C / M2-Lex(P2) 有 | `m2_models.py:183` |
| Min CVaR objective | ✅ M2-Lex(P1) 有 | `m2_models.py:297` |
| Cost objective | ❌ 缺失 | — |
| Scenario link capacity (hard) | ✅ | M1 约束 6 |
| Scenario compute capacity (hard) | ✅ | M1 约束 7 |
| Unique placement (hard) | ✅ | M1 约束 1 |
| Flow conservation (equality) | ✅ | M1 约束 4, 5 |

---

## 12. 实现 M2-C-Cost 所需复用的函数清单

从现有代码复用，**不修改**：

| 函数 | 文件 | 用途 |
|:--|:--|:--|
| `_valid_pairs(data)` | `m0_models.py:141` | 获得有效 (i,m) 对 |
| `_path_edges(path)` | `m0_models.py:148` | 路径 → 边列表 |
| `build_m1_model(data, ...)` | `m1_models.py:117` | 构建 M1 场景模型底座 |
| `teavar_flow_anchors(data, i)` | `duibi_metrics.py:270` | 获得 (src, dst) |
| `_compute_cvar_from_L(L, prob, alpha)` | `m2_models.py:44` | 后验 CVaR 计算 |
| `build_toy_2task_independent_v1(...)` | `toy_two_task_independent_data.py:394` | 加载数据集 |

需要新增（不在审计范围内，仅供参考）：

| 函数 | 用途 |
|:--|:--|
| `build_e2e_loss_weights(...)` | 归一化任务权重 ω_i |
| `add_e2e_loss_constraints(...)` | 损失表达式 L_s = Σ ω_i (1 - z[i,s]) |
| `add_cvar_ru_constraints(...)` | CVaR 线性化 |
| `compute_placement_cost(...)` | c_p = Σ y[i,m] · Σ w[i,k] · ρ_{m,k} |
| `compute_scenario_bandwidth_cost(...)` | c_b(x_s) = Σ ρ_e · LinkLoad_{e,s} |
| `build_m2_c_cost_model(...)` | M2-C-Cost builder |
| `solve_m2_lex3(...)` | M2-Lex-3 三阶段求解 |

---

## 13. 不要修改的 Legacy 文件

> 以下文件直接列在审核清单中，禁止修改。

| 文件 | 原因 |
|:--|:--|
| `model_ac_component_risk_release/*` | 旧 Model A/C 完整模块 |
| `refactor/duibi_metrics.py` | 旧对比框架 |
| `refactor/pareto_frontier.py` | 旧 Pareto frontier |
| `refactor/frontier_reporting.py` | 旧 frontier 报告 |
| `refactor/teavar_framework_models.py` | UMCF 模型 |
| `refactor/parsers.py` | UMCF 解析器 |
| `refactor/util.py` | UMCF 工具 |
| `refactor/generate_compute_resources.py` | 算力生成 |
| `refactor/component_scenario_generator.py` | 旧场景生成 |
| `refactor/toy_instances.py` | 旧 toy 实例 |
| `refactor/toy_instances_v2.py` | 旧多路径 toy |
| `refactor/main.py` | 旧主入口 |
| `refactor/b4_joint_data.py` | B4 数据 |
| `component_scenario_generator.py` (根目录) | 旧场景生成 |
| `toy_te_data.py` (根目录) | ToyTE 数据（旧 toy） |
| `validate_toy_te.py` (根目录) | ToyTE 验证 |

此外，以下已有主线文件只读，**不得修改** `build_*` / `solve_*` / 约束添加逻辑：

- `refactor/m0_models.py`（只读，`_valid_pairs` 和 `_path_edges` 可复用）
- `refactor/m1_models.py`（只读，`build_m1_model` 可调用）
- `refactor/m2_models.py`（只读，`_compute_cvar_from_L` 可复用）
