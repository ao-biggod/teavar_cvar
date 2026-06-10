# L2-full 严格双层模型设计

**版本**：Milestone 0 初稿 + M0.5/M1 修订（不修改 P0 主链）  
**仓库基线（核对日）**：branch `fix-sf-per-resource-normalization-ac`，commit `8b78f81`  
**符号主表**：`reports/weekly_report_20250611.md` §3.1  
**相关实现**：L0 枚举见 `bilevel_teavar_models.py`；L1 联合 MILP 见 `teavar_framework_models.py`

---

## 0. 目标与定位

实现 **strict bilevel / Copo-style** 的 **L2-full** 版本，作为当前 TEAVAR-style **单层联合 MILP（L1）** 的严格双层增强版。

| 层级 | 含义 | 代码入口（现状） |
|:--|:--|:--|
| **L0** | 枚举 placement $y$，快层独立 LP，post-hoc 风险 | `bilevel_teavar_models.solve_bilevel_lexicographic` |
| **L1** | $y,x,d$ 同一 MILP 联合优化 | `teavar_framework_models.build_teavar_model_*` |
| **L2-light** | 上层 MIP + 下层 F1 最优性证书 | 待实现：`l2_full_models.py` |
| **L2-full** | 上层 MIP + 下层 F1/F2/F3 三套证书 | 待实现：`l2_full_models.py` |

**L2-full 不替代 P0 主实验**（`run_gamma_frontier.py` / B4 主图），而是：

- 论文中更正统的 Stackelberg 建模路线；
- toy / exact validation 路线；
- 后续 B4 小规模缩放实验路线。

### 核心语义（与 L1 的本质区别）

```text
Upper leader:     choose placement y
Lower follower:   given y, choose routing x,d as the optimal routing response
```

**不能把** $y,x,d$ 简单放进同一个 MILP 里联合优化——那是 **L1**，不是 **L2**。

Copo 本质：性能（SLA CVaR）放在下层独立优化；上层在 follower 反应值上再做字典序决策；**不是** $\mathrm{Cost}+\lambda\cdot\mathrm{Risk}$，**也不是** $\mathrm{Risk}\le\Gamma$ 的单层折中。

---

## 1. L2-full 的数学结构

### 1.1 上层 Leader

**上层变量**

| 符号 | 含义 |
|:--|:--|
| $y_{i,m}$ | 任务 $i$ 是否部署在算力节点 $m$ |
| $\mathrm{open}_m$ | 算力节点 $m$ 是否开启（可选扩展） |

**上层风险（仅依赖 placement）**

$$
\mathrm{CVaR}_\beta\!\left(L^{\mathrm{SF}}\right)(y)
$$

即算力容量故障 / compute overflow risk。**不依赖** routing $x,d$。

**上层目标：三阶段字典序**

$$
\min_{\mathrm{lex}}\;
\begin{cases}
1.\; \mathrm{CVaR}_\beta(L^{\mathrm{SF}})(y) \\
2.\; R^{\mathrm{SLA}*}(y) \\
3.\; C_{\mathrm{deploy}}(y) + C_{\mathrm{bw}}^{*}(y)
\end{cases}
$$

其中：

- $R^{\mathrm{SLA}*}(y) = \min_{x,d \in \mathcal{F}(y)} \mathrm{CVaR}_\beta(L^{\mathrm{SLA}})$ —— 下层在 placement $y$ 给定后能达到的 **最小 SLA CVaR**（快层反应值，非新指标）；
- $C_{\mathrm{bw}}^{*}(y)$ —— 下层 lex follower 在 F3 阶段最终选出的带宽成本；
- $C_{\mathrm{deploy}}(y) = \sum_{i,m,k} w_{i,k}\, p_{m,k}\, y_{i,m}$（与 6/11 报告 §2.5 一致）。

**成本口径（与 L0 代码一致，第一版）**

| 符号 | 含义 | L0 函数 |
|:--|:--|:--|
| $C_{\mathrm{resource}}$ | 资源 placement 成本 $\sum_{i,m,k} w_{i,k} p_{m,k} y_{i,m}$ | `deployment_cost` |
| $C_{\mathrm{open}}$ | 节点开启成本（$\mathrm{open}_m$） | **第一版关闭**，不扩 scope |
| $C_{\mathrm{slow}}$ | $C_{\mathrm{open}} + C_{\mathrm{resource}}$（+ 可选 placement 绑定带宽） | `slow_placement_cost` |
| $C_{\mathrm{bw}}$ / $C_{\mathrm{bw}}^{*}$ | 流量带宽成本（flow 模式） | 快层 `bandwidth_cost` |
| $C_{\mathrm{tot}}$ | $C_{\mathrm{slow}} + C_{\mathrm{bw}}$（flow 模式） | `cost_total` |

说明：

- `bandwidth_mode="flow"` 时 $C_{\mathrm{slow}} = C_{\mathrm{resource}}$，带宽不进 slow cost；
- `bandwidth_mode="placement"` 时 `slow_placement_cost` 额外计入 placement 绑定带宽；
- L0 lex CSV 列 `cost_deploy` = `deployment_cost`（仅资源），**不等于**含 open 的 $C_{\mathrm{slow}}$ 全项。

符号对照（CSV / 报告）：

| 设计符号 | 报告 / CSV |
|:--|:--|
| $C_{\mathrm{resource}}$ / $C_{\mathrm{deploy}}$ | `cost_deploy` |
| $C_{\mathrm{bw}}^{*}$ | `cost_bw` / $C_{\mathrm{fast}}$ |
| $C_{\mathrm{tot}}$ | `cost_total` |
| $R^{\mathrm{SLA}*}$ | `r_sla` |
| $\mathrm{CVaR}_\beta(L^{\mathrm{SF}})$ | `r_sf` |
| $\mathbb{E}[\mathrm{Del}]$ | `e_del` |

### 1.2 下层 Follower

给定 $y$，**只优化 routing 变量**：

```text
x_in / x_out
del_in / del_out
zeta_sla, u_sla          （SLA CVaR R&U 辅助变量）
（及 scenario delivery coupling 相关变量）
```

**可行域** $\mathcal{F}(y)$ 包含：

- flow conservation；
- path / edge capacity；
- scenario delivery coupling；
- partial $\sigma$ failure effect；
- delivery variables；
- SLA CVaR R&U constraints；
- routing mode constraints（hub / per_task_od 等）；
- placement $y$ 诱导的 anchors / valid assignment constraints。

**下层三阶段字典序（optimistic follower）**

| 阶段 | 目标 | 含义 |
|:--:|:--|:--|
| **F1** | $\min \mathrm{CVaR}_\beta(L^{\mathrm{SLA}})$ | SLA 风险最优 |
| **F2** | $\max \mathbb{E}[\mathrm{Del}]$ s.t. F1-optimal | 在 SLA 最优解集中送达最大 |
| **F3** | $\min C_{\mathrm{bw}}$ s.t. F1,F2-optimal | 在 SLA+送达最优解集中带宽成本最低 |

数学形式：

$$
\begin{aligned}
\text{F1:}\quad
R^{\mathrm{SLA}*}(y) &= \min_{z \in \mathcal{F}(y)} \mathrm{CVaR}_\beta(L^{\mathrm{SLA}})(z) \\
\text{F2:}\quad
D^{*}(y) &= \max_{z \in \mathcal{F}(y)} \mathbb{E}[\mathrm{Del}](z)
\quad \text{s.t.}\quad \mathrm{CVaR}_\beta(L^{\mathrm{SLA}})(z) \le R^{\mathrm{SLA}*}(y) + \varepsilon_{\mathrm{lex}} \\
\text{F3:}\quad
C_{\mathrm{bw}}^{*}(y) &= \min_{z \in \mathcal{F}(y)} C_{\mathrm{bw}}(x)
\quad \text{s.t.}\quad \mathrm{CVaR}_\beta(L^{\mathrm{SLA}})(z) \le R^{\mathrm{SLA}*}(y) + \varepsilon_{\mathrm{lex}},\;
\mathbb{E}[\mathrm{Del}](z) \ge D^{*}(y) - \varepsilon_{\mathrm{lex}}
\end{aligned}
$$

Follower 最终返回 F3 的 routing 解：

$$
x^{*}(y),\; d^{*}(y),\; R^{\mathrm{SLA}*}(y),\; D^{*}(y),\; C_{\mathrm{bw}}^{*}(y)
$$

**与 L0 已实现快层的关系**：`bilevel_teavar_models` 中 `fast_objective="lex_sla_delivery_cost"` 通过 **三 pass LP** 实现相同语义；L2-full 需把该语义 **嵌入上层 MIP** 而非枚举 $y$。

### 1.3 固定变量空间（embedded-y，M2+）

L2-light / L2-full **嵌入上层** $y$ 时，不能只为 `placement[i] == node` 的组合创建 routing 变量（那是 fixed-y / L0 快层做法）。

必须为 **全部合法** $(i,m,p)$ / $(i,m,q)$ 创建 `xin` / `xout`，并加入 Big-M 耦合：

```text
xin[i,m,p] <= M_in[i,m,p] * y[i,m]
xout[i,m,q] <= M_out[i,m,q] * y[i,m]
```

**默认 Big-M**（任务需求上界）：

```text
M_in[i,m,p]  <= b_in[i]
M_out[i,m,q] <= b_out[i]
```

若可获得路径容量上界，再收紧为 $\min(\text{task\_demand}, \text{path\_capacity})$。

骨架实现见 `l2_full_models.build_f1_embedded_y_skeleton`（本轮不求解）。

### 1.4 L2-light 语义边界（M2）

**L2-light 只保证 follower F1-optimal**（给定 $y$ 时 routing 最小化 SLA CVaR）。

它 **不保证** 完整 lex follower：

```text
SLA CVaR → expected delivery → bandwidth cost
```

因此 M2 与 L0 对比时，**只能选择不存在 follower tie-break 歧义的 toy case**。若 placement 最优不一致，先检查 lower-level 多解（F2/F3 未嵌入前 $C_{\mathrm{bw}}^{*}(y)$ 可能不稳定）。

---

## 2. Reformulation 路线

L2-full 不能直接交给 Gurobi 求解，因为下层含：

```text
x*(y), d*(y) ∈ argmin(...)
```

需把下层最优性转成约束。

### 2.1 F1：Strong Duality（M2 优先路线）

F1 可优先采用：

```text
primal feasibility
+ dual feasibility
+ strong duality
```

若 strong-duality RHS 中出现 `dual_var * y[i,m]`，且 $y$ 为 binary、对偶变量有有限上下界，可使用 **精确 McCormick 线性化**（不是 continuous×continuous 松弛）。

**第一版避免**手写大量 KKT complementarity（$\lambda_i \cdot s_i = 0$）。

### 2.2 F2/F3：**不能**直接宣称 strong duality → exact single-level MIP

F2 primal lex 约束：

```text
CVaR_sla(z2) <= CVaR_sla(z1) + eps_lex
```

本身是 **线性** 的。

但对 F2 做 dualize 后，strong-duality 的对偶目标会出现：

```text
lambda2 * CVaR_sla(z1)     ← continuous × continuous
```

F3 同理还会出现：

```text
lambda31 * CVaR_sla(z1)
lambda32 * E_Del(z2)
```

因此 **不得**写成：

```text
F1/F2/F3 strong duality → 直接 single-level exact MIP   ✗
```

正确表述：

| 阶段 | Reformulation 定位 |
|:--|:--|
| **F1** | strong-duality embedding → **M2 L2-light 优先路线** |
| **F2/F3** | 独立 **Milestone 2.5**；再评估 KKT+Indicator、SOS1、tight Big-M，或 **明确标注的 relaxation** |
| 任何 CC McCormick 松弛 | **不得** 声称 exact |

M0.5 先在 fixed-y F1 上验证 primal/dual gap（见 §7 Milestone 0.5）。

### 2.3 与现有 Model B/D 的关系

| 现有模块 | 用途 | L2-full 关系 |
|:--|:--|:--|
| `build_teavar_model_b` (KKT) | 单层 SLA 互补 | 参考 Indicator 写法，但 L2 第一版不主用 |
| `build_teavar_model_d` (McCormick) | Copo 互补松弛 | 参考 McCormick 包络；L2 用于 dual×$y$ 双线性 |
| `bilevel_teavar_models._solve_fast_lex_*` | L0 快层三 pass | M1 数值对照基准 |

L2-full 是 **独立模块**（`l2_full_models.py`），不修改 `teavar_framework_models.py` 主链。

---

## 3. Lower-level Certificate 分层规划

下层是三阶段 lex follower。证书路线 **分阶段**，不可一次性宣称 F1/F2/F3 均为 exact strong-duality MIP。

### 3.1 F1 Certificate：min SLA CVaR（M1 / M2）

**变量**：$z_1 = (x_1, d_1, \zeta_1, u_1, \ldots)$

**约束**：

- $\mathcal{F}(y)$ 的 primal feasibility（embedded-y 时用 §1.3 Big-M）；
- F1 的 dual feasibility；
- F1 的 strong duality（$y$ 为常数时 M0.5 已验证；$y$ 为变量时用 McCormick）。

**结果**：$R^{\mathrm{SLA}} = \mathrm{CVaR}_\beta(L^{\mathrm{SLA}})(z_1)$

**M1 入口**：`l2_full_models.solve_f1_fixed_y` / `build_f1_primal_fixed_y`  
**L0 baseline**：`bilevel_teavar_models.solve_fast_routing(..., fast_objective="min_sla_cvar")`

### 3.2 F2 Certificate：max expected delivery（Milestone 2.5，未实现）

**变量**：$z_2 = (x_2, d_2, \zeta_2, u_2, \ldots)$

**Primal lex 约束**（线性）：$\mathrm{CVaR}_\beta(L^{\mathrm{SLA}})(z_2) \le R^{\mathrm{SLA}} + \varepsilon_{\mathrm{lex}}$

**Exact embedding 障碍**：dualize 后出现 $\lambda_2 \cdot \mathrm{CVaR}_\beta(L^{\mathrm{SLA}})(z_1)$（continuous×continuous）。

**待选路线**：KKT+Indicator、SOS1、tight Big-M，或标注 relaxation。**本轮不实现。**

### 3.3 F3 Certificate：min bandwidth cost（Milestone 2.5，未实现）

**Primal lex 约束**（线性）：F1 约束 + $\mathbb{E}[\mathrm{Del}](z_3) \ge D^{*} - \varepsilon_{\mathrm{lex}}$

**Exact embedding 障碍**：$\lambda_{31} \cdot \mathrm{CVaR}_\beta(L^{\mathrm{SLA}})(z_1)$、$\lambda_{32} \cdot \mathbb{E}[\mathrm{Del}](z_2)$。

**本轮不实现。**

### 3.4 实现备注

- F1/F2/F3 可行域结构相同（均依赖 $y$）；可复用 `cvar_compare.add_scenario_delivery_coupling` 与 `duibi_metrics` flow anchor。
- F2/F3 lex 约束用 $\varepsilon_{\mathrm{lex}}$ 松弛（§6.4）。
- L0 三 pass（`_solve_fast_lex_sla_delivery_cost`）在 fixed-y 上仍可作为 F1/F2/F3 **语义**对照，但与 L2 embedding 不等价。

---

## 4. 上层 Lex Solve

**禁止**用一个巨大 weighted objective：

```text
M1 * CVaR_sf + M2 * CVaR_sla + Cost    ← 会引入权重口径问题，不是 lex
```

建议 **三 pass lex solve**（与 L0 `apply_lex_stages` 语义一致）：

### Upper Pass U1

$$
\min\; \mathrm{CVaR}_\beta(L^{\mathrm{SF}})(y)
\quad \Rightarrow \quad \mathrm{SF}_{\mathrm{opt}}
$$

### Upper Pass U2

添加 $\mathrm{CVaR}_\beta(L^{\mathrm{SF}})(y) \le \mathrm{SF}_{\mathrm{opt}} + \varepsilon_{\mathrm{upper}}$，然后：

$$
\min\; R^{\mathrm{SLA}*}(y)
\quad \Rightarrow \quad \mathrm{SLA}_{\mathrm{opt}}
$$

### Upper Pass U3

添加：

```text
CVaR_sf(y) <= SF_opt + eps_upper
R_sla*(y) <= SLA_opt + eps_upper
```

然后：

$$
\min\; C_{\mathrm{deploy}}(y) + C_{\mathrm{bw}}^{*}(y)
$$

最终输出 placement $y^{*}$ 与 follower routing $x_3^{*}, d_3^{*}$。

**L2-light** 仅嵌入 F1 certificate + U1/U2/U3；**L2-full** 额外嵌入 F2/F3 certificate。

---

## 5. 与 L0 / L1 / L2-light 的区别

| 维度 | L0 | L1 | L2-light | L2-full |
|:--|:--|:--|:--|:--|
| placement 搜索 | 枚举 $y$ | 联合 MILP | 上层 MIP | 上层 MIP |
| routing 语义 | 独立 LP（三 pass） | 与 $y$ 联合 | follower F1 最优 | follower F1→F2→F3 lex |
| 下层最优性 | 隐式（枚举+LP） | 无（联合） | strong duality **F1 only** | F1 exact + F2/F3 Milestone 2.5 |
| 可扩展性 | toy only | B4 主链 | 小规模 B4 | 小规模 B4 |
| λ / Γ / ω | lex 版无 | 有 | 无 | 无 |

**SF 与 SLA 分开**：SF 只依赖 $y$（上层）；SLA 依赖 $y$ + routing（下层）。不宜用 $\max\{\mathrm{CVaR}^{\mathrm{SLA}}, \mathrm{CVaR}^{\mathrm{SF}}\}$ 单标量合并。

**不要把 SF 放进 lower-level follower**。

---

## 6. 技术风险与处理

### 6.1 $y$ 与对偶变量的乘积

Strong duality 的 RHS 中若含 placement 变量 $y$，可能出现：

```text
dual_var * y[i,m]     （双线性）
```

**处理**：

- $y$ 为 binary、对偶变量有上下界 → **McCormick linearization**；
- 否则 → Big-M / indicator / Benders。

**必须**显式给对偶变量合理 upper bounds（参考 `build_teavar_model_d` 的 $\alpha_{\max}$, $\mathrm{slack}_{\max}$ 思路）。

### 6.2 Complementarity

若使用 KKT 而非 strong duality：

```text
dual_var * slack = 0
```

处理：Big-M、Indicator、SOS1。

**第一版优先避免**大量 complementarity；primal + dual + strong duality 够用则不用 KKT。

### 6.3 Lower-level 多解（必须处理）

L2-full 必须采用 **optimistic bilevel follower selection**：

```text
在所有 SLA 最优 routing 中，选择 E[Del] 最大；
在 SLA 和 E[Del] 都最优的 routing 中，选择 C_bw 最低。
```

这正是 F1 → F2 → F3 的意义。否则上层 $C_{\mathrm{bw}}^{*}(y)$ 可能不稳定。

### 6.4 数值容差

| 参数 | 建议值 | 用途 |
|:--|:--|:--|
| $\varepsilon_{\mathrm{lex}}$ | $10^{-6}$ ~ $10^{-5}$ | F2/F3 相对 F1/F2 的 lex 约束 |
| $\varepsilon_{\mathrm{upper}}$ | $10^{-6}$ ~ $10^{-5}$ | U2/U3 相对 U1/U2 的 lex 约束 |
| `_NUM_TOL` | $10^{-9}$ | 浮点相等判定（L0 沿用） |

**不要用严格等号**：

```text
CVaR_sla == R_sla          ✗
E[Del] == D_star           ✗

CVaR_sla <= R_sla + eps     ✓
E[Del] >= D_star - eps      ✓
```

L0 实现中 `_LEX_TOL = 1e-7`；L2-full 文档层统一写 $\varepsilon_{\mathrm{lex}}$，实现时可与 L0 对齐后固化常量。

---

## 7. 工程实现顺序

分阶段交付，**不要一口气实现完整 L2-full**。

### Milestone 0：design doc ✅（初稿）

- 本文档 `docs/l2_full_design.md`
- 只写文档，不改主模型

### Milestone 0.5：fixed-y F1 primal / dual validation ✅

**步骤**：

1. 选择一个 fixed placement；
2. 构建并求解原始 F1 LP（`l2_full_models.build_f1_primal_fixed_y`）；
3. 提取每类约束的 Pi（按 `cap_in` / `ru_in` / `del_*` 等分组）；
4. 手写 dual objective：$\sum_i \mathrm{RHS}_i \cdot \Pi_i$（Gurobi min LP 约定）；
5. 输出 primal objective、dual objective、gap；
6. 输出关键 dual multiplier 符号检查（`cap_*` Pi $\le 0$，`ru_*` Pi $\ge 0$，Gurobi min LP 约定）；
7. gap $> \varepsilon$ 时停止（$\varepsilon = 10^{-6}$ 或 $10^{-5}$）。

**交付**：

| 文件 | 职责 |
|:--|:--|
| `l2_full_models.py` | fixed-y F1 builder + dual validation |
| `tests/test_l2_f1_dual.py` | 自动化验收 |
| `scripts/run_l2_f1_dual_check.py` | 命令行报告 |

**L0 对照**：`solve_fast_routing(..., fast_objective="min_sla_cvar")`

### Milestone 1：lower F1 standalone ✅

独立下层 LP / 证书原型：

```text
given fixed placement y
solve min SLA CVaR
```

**验收**：同一 fixed $y$ 下，F1 的 SLA CVaR 与 `solve_fast_routing(..., fast_objective="min_sla_cvar")` 一致；strong-duality gap $\le \varepsilon$。

### Milestone 2.5：F2/F3 exact embedding 评估（未开始）

评估 KKT+Indicator、SOS1、tight Big-M 或明确 relaxation；**不得**用 CC McCormick 后声称 exact。

### Milestone 2：L2-light

```text
Upper chooses y
Lower F1 min SLA CVaR（嵌入 F1 最优性）
Upper lex: SF → SLA → Cost
```

**验收**：ComponentRisk toy 上与 L0 enumeration 的最优 placement 一致；**仅限无 follower tie-break 歧义**的 toy case（§1.4）。

### Milestone 3：add F2 tie-break

加入 F2：在 SLA-optimal routing 中 max $\mathbb{E}[\mathrm{Del}]$。

**验收**：构造多 SLA-optimal routing 的 toy case，F2 选 $\mathbb{E}[\mathrm{Del}]$ 更高者。

### Milestone 4：add F3 tie-break

加入 F3：在 F1+F2 optimal 集合中 min $C_{\mathrm{bw}}$。

**验收**：构造 SLA 与 $\mathbb{E}[\mathrm{Del}]$ 相同但 $C_{\mathrm{bw}}$ 不同的 toy case，F3 选更低带宽成本。

### Milestone 5：L2-full toy validation

在 ComponentRisk toy 或小 B4 子实例上对比：

| 方法 | 入口 |
|:--|:--|
| L0 enumeration | `solve_bilevel_lexicographic` |
| L1 joint MILP | `build_teavar_model_*`（对照） |
| L2-light | `l2_full_models` |
| L2-full | `l2_full_models` |

输出对比表：placement, $\mathrm{CVaR}^{\mathrm{SF}}$, $\mathrm{CVaR}^{\mathrm{SLA}}$, $\mathbb{E}[\mathrm{Del}]$, $C_{\mathrm{bw}}$, $C_{\mathrm{tot}}$, solve time, status。

**验收**：L2-full 与 L0 在 toy 上一致或可解释地一致。

### Milestone 6：B4 small-scale run

先 **不要** 跑完整 8-task × 5×5 Γ grid。先跑：

```text
B4, 4 tasks, macro3 scenarios, per_task_od, small path set, single upper lex solve
```

**验收**：OPTIMAL 或可接受 TIME_LIMIT；结果非退化；SF / SLA / Cost 正常输出。

---

## 8. 文件规划

### 新增（独立模块）

| 文件 | 职责 |
|:--|:--|
| `docs/l2_full_design.md` | 本文档 |
| `l2_full_models.py` | fixed-y F1（M0.5/M1）；L2-light / L2-full 后续 |
| `tests/test_l2_f1_dual.py` | M0.5/M1 验收 |
| `scripts/run_l2_f1_dual_check.py` | M0.5 命令行报告 |
| `tests/test_l2_full_toy.py` | M2+ 验收（未创建） |
| `scripts/run_l2_full_smoke.py` | M5 冒烟（未创建） |

### 不修改（P0 主链）

```text
cvar_compare.py
teavar_framework_models.py
run_gamma_frontier.py
main.py（第一版不挂接）
```

### 可只读复用

```text
bilevel_teavar_models.py      ← L0 对照、快层 LP 逻辑
cvar_compare.py               ← SLA CVaR 约束块
duibi_metrics.py              ← flow anchor、bandwidth cost
toy_instances.py              ← ComponentRisk toy
exact_enumeration_solver.py   ← L0 枚举基准
```

---

## 9. 不要做的事（第一版）

```text
✗ 不要直接替换 P0 主模型
✗ 不要直接跑 8-task × 5×5 Γ grid
✗ 不要把 L1 和 L2-full 混在一个函数里
✗ 不要用 λ 权重模拟 lex
✗ 不要重新引入 inverse_capacity 作为主成本
✗ 不要把 SF 放进 lower-level follower
✗ 不要把 y,x,d 联合优化后声称是 L2
```

---

## 10. 最低验收标准（第一阶段成功）

1. `docs/l2_full_design.md` 清楚定义 L2-full（本文档）；
2. fixed $y$ 的 lower F1 与现有 routing LP 结果一致（M1）；
3. L2-light toy 与 L0 enumeration 一致（M2）；
4. L2-full toy 能体现 F1 → F2 → F3 tie-break（M3–M4）；
5. 输出表包含 SF, SLA, $\mathbb{E}[\mathrm{Del}]$, $C_{\mathrm{bw}}$, $C_{\mathrm{tot}}$（M5）；
6. 所有 L2-full 代码与 P0 主线隔离（M0–M6）。

---

## 11. 论文定位

```text
L0:   exact enumerative bilevel validation on toy instances
L1:   scalable joint MILP / TEAVAR-style implementation for B4 experiments
L2-light:  strict bilevel reformulation with lower-level SLA-CVaR optimality
L2-full:   strict bilevel reformulation with lexicographic follower:
               SLA CVaR → expected delivery → bandwidth cost
```

L2-full 是 **理论最完整** 的 Stackelberg 版本，但 **不应阻塞** 当前 P0 主图。

---

## 12. 附录：L0 快层三 pass 与 L2 证书对照

L0 已实现（`bilevel_teavar_models._solve_fast_lex_sla_delivery_cost`）：

```text
Pass 1: min CVaR_SLA           ↔  F1 certificate（无上层 y 时即 standalone LP）
Pass 2: max E[Del] | CVaR tie  ↔  F2 certificate + eps_lex
Pass 3: min C_bw | CVaR+Del tie ↔  F3 certificate + eps_lex
```

L2-full 的差异在于：**Pass 1–3 的最优性必须作为上层 MIP 的约束**，而非对固定 $y$ 顺序求解三个 LP。

上层 lex（SF → SLA → Cost）在 L0 中由 `apply_lex_stages` + `enumerate_placements` 实现；L2 中由 U1/U2/U3 三 pass MIP 实现，且 U2/U3 中的 $R^{\mathrm{SLA}*}(y)$、$C_{\mathrm{bw}}^{*}(y)$ 来自下层证书而非 post-hoc 评估。

---

## 13. 附录：B4 数据层（不枚举 y）

B4 实例中 K 条候选路径由 `b4_joint_data._k_shortest_edge_paths` 按 **跳数（无权最短简单路径）** 写入 `P_cand`；架构/拓扑决定 OD 对与图，**不是**按 $\pi_e$ 或架构层级排序选路。

L2-full 扩展 B4 时：

- **仍使用** 数据层 K 路径与 `valid_assign` 剪枝；
- **不枚举** $|Y|$（指数爆炸）；
- 上层 MIP 选 $y$，下层证书保证 routing 反应。

此节与 `reports/weekly_report_bilevel_lex_20250613.md` §2.3（若已补充）一致。
