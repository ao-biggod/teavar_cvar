# 6月12日工作报告（快慢双层 TEAVAR）

**项目**：TEAVAR 算力网络联合优化验证框架  
**报告周期**：本周，截至 2025 年 6 月 12 日  
**本周重点**：在**不修改单层 Model A/C 代码**的前提下，实现 L0 枚举式快慢双层 baseline，完成 toy 验证、Γ 前沿扫描，并与单层 Model C 对照分析 placement 一致性与 gap。

**前置基础**：本报告在 ComponentRisk toy 上展开（场景与节点角色见 [`weekly_report_20250611.md`](weekly_report_20250611.md)）。

---

## 1. 本周工作概述

本周在单层联合 MILP 之外，新增独立的**快慢时间尺度分解**验证模块。核心思路是：

1. **慢层（战略 / placement）**：枚举可行 placement $y$，用 Model A（$\lambda$）或 Model C（$\Gamma$）表达长期成本–风险偏好；
2. **快层（战术 / routing）**：给定 placement 后，用连续优化求解 $x$、$d$；
3. **风险评价**：不在快层模型内读松弛变量，而在快层解固定后 **post-hoc** 重算 SLA CVaR 与 SF CVaR。

该模块的定位是：

> **L0 枚举式快慢双层 baseline**（reaction-based placement–routing decomposition）  
> 适合 toy / exact validation / 单层对照；**尚未**作为 B4 大规模主链。

**相关代码：**

| 文件 | 作用 |
|:--|:--|
| `bilevel_teavar_models.py` | 快层 routing、慢层 Model A/C、post-hoc CVaR、单层对照 API |
| `scripts/run_bilevel_smoke.py` | 单点冒烟（λ / Γ / ω / 单层 A 对比） |
| `scripts/run_bilevel_gamma_frontier.py` | $\Gamma_{\mathrm{sla}} \times \Gamma_{\mathrm{sf}}$ 网格扫描 + 单层 C 对比 |
| `tests/test_bilevel_teavar.py` | 8 项自动化测试 |
| `results/bilevel_gamma_frontier_cr_smoke.csv` | 3×3 Γ 前沿冒烟结果 |

**明确不做的事：**

- 未修改 `cvar_compare.py`、`teavar_framework_models.py` 等单层加权程序；
- 未挂接 `main.py`（等 Γ 前沿与 gap 表跑清楚后再接 CLI）；
- 未实现 KKT 嵌入的严格 Stackelberg 单模型。

---

## 2. 双层架构设计

### 2.1 设计动机

单层 Model A 的局限在于：

- 必须扫描 $\lambda_{\mathrm{sla}}, \lambda_{\mathrm{sf}}$ 才能描出 cost–risk Pareto，没有「一键最优」；
- 放置（慢）与路由（快）挤在同一 MILP，语义与规模都偏紧。

双层分解试图回答**不同的问题**：

| 问题 | 由什么解决 |
|:--|:--|
| 谁在什么时间尺度决策 | 慢层 $y$ / 快层 $x,d$ |
| 便宜还是安全 | $\lambda$ 或 $\Gamma$（慢层偏好） |
| 给定 placement 后如何送流 | $\omega$（快层送达激励） |

**重要区分：** 双层解决「时间尺度」，$\lambda/\Gamma$ 解决「成本–风险取舍」——二者不能互相替代。

### 2.2 求解流程（L0 反应式）

```text
对每个可行 placement y（本 toy：27 种）
  → 快层：固定 y，解 routing 子问题，得 x*(y), d*(y)
  → post-hoc：CVaR_SLA(y), CVaR_SF(y)
  → 慢层：按 Model A 或 Model C 选最优 y
```

这不是「上层 MILP 内嵌下层 KKT」的严格 Stackelberg，而是：

```text
enumerative bilevel baseline
reaction-based placement–routing decomposition
```

报告与论文中应使用上述表述，避免声称「已实现完整双层优化」而遭遇 KKT、强对偶、下层唯一性追问。

### 2.3 慢层 / 快层分工

| | 慢层（placement） | 快层（routing） |
|:--|:--|:--|
| **时间尺度** | 慢（小时~天） | 快（秒~分钟） |
| **决策变量** | $y_{im}$（枚举） | $x^{\mathrm{in/out}}_{im,p}$，$d^{\mathrm{in/out}}_{im,p,s}$ |
| **主要成本** | 资源 +（本 toy）placement 带宽 | 带宽绑 $x$ 时：$x$ 上带宽费 |
| **主要风险** | post-hoc CVaR（SLA 经 $x^*$，SF 仅经 $y$） | 不直接进慢层目标 |
| **偏好参数** | $\lambda_{\mathrm{sla}}, \lambda_{\mathrm{sf}}$ 或 $\Gamma_{\mathrm{sla}}, \Gamma_{\mathrm{sf}}$ | $\omega$（及快层目标模式） |

### 2.4 快层实现要点

**（1）placement 以常数嵌入，无 binary $y$**

快层不再创建 $y \in \{0,1\}$ 再固定，而是直接把 placement 写入容量约束与虚拟接入瓶颈。Gurobi 侧为**纯连续 LP**（本 toy 单路径时规模极小）。

**（2）快层目标模式 `fast_objective`**

| 模式 | 行为 | 用途 |
|:--|:--|:--|
| `delivery`（默认） | $\min C_{\mathrm{bw}}(x) - \omega\,\mathbb{E}[\mathrm{Del}]$ | 与单层 $\omega$ 语义对齐的快层 routing |
| `lexicographic` | max $\mathbb{E}[\mathrm{Del}$] → min $\mathbb{E}[L^{\mathrm{SLA}}]$ → min $C_{\mathrm{bw}}$ | 多路径时稳定 $\mathrm{Risk}(y)$ |
| `min_sla_cvar` | 快层直接 min $\mathrm{CVaR}^{\mathrm{SLA}}$（RU 线性化） | 给定 $y$ 下最小化尾部 SLA |

**（3）Risk(y) 定义**

$$
\mathrm{CVaR}^{\mathrm{SLA}}(y) = \mathrm{CVaR}\!\left(L^{\mathrm{SLA}} \mid x^*(y), d^*(y)\right), \qquad
\mathrm{CVaR}^{\mathrm{SF}}(y) = \mathrm{CVaR}\!\left(L^{\mathrm{SF}} \mid y\right)
$$

SF 风险与路由无关；SLA 风险依赖快层最优反应 $x^*(y)$。

---

## 3. 完整公式体系

符号表见 [`weekly_report_20250611.md`](weekly_report_20250611.md) §3.1。本节只写**双层**相对单层的决策分工与两个目标函数。

### 3.1 决策变量

| 变量 | 所属层 | 含义 |
|:--|:--|:--|
| $y_{i,m}\in\{0,1\}$ | **慢层** | 任务 $i$ 是否放在节点 $m$ |
| $x^{\mathrm{in}}_{i,m,p}\ge 0$ | **快层** | ingress 计划流量 |
| $x^{\mathrm{out}}_{i,m,q}\ge 0$ | **快层** | egress 计划流量 |
| $d^{\mathrm{in}}_{i,m,p,s}\ge 0$ | **快层** | 场景 $s$ 下 ingress 实际送达 |
| $d^{\mathrm{out}}_{i,m,q,s}\ge 0$ | **快层** | 场景 $s$ 下 egress 实际送达 |

双层实现中：慢层**枚举**可行 $y$；对每个固定 $y$，快层只求 $(x,d)$。

---

### 3.2 成本分解

**慢层成本（只含 placement）：**

$$
C_{\mathrm{slow}}(y)
=\sum_{i,m,k} w_{i,k}\,p_{m,k}\,y_{i,m}
+\mathbb{1}[\text{placement 计费}]\cdot\sum_{i,m} b_i\,\tau_{i,m}\,y_{i,m}
$$

**快层带宽成本（只含计划流量 $x$）：**

$$
C_{\mathrm{fast}}(x;y)
=\sum_{i,m,p}\tau^{\mathrm{in}}_{i,m,p}\,x^{\mathrm{in}}_{i,m,p}
+\sum_{i,m,q}\tau^{\mathrm{out}}_{i,m,q}\,x^{\mathrm{out}}_{i,m,q}
$$

ComponentRisk toy 设 `bandwidth_cost_on_placement=True` 时，第二项已在 $C_{\mathrm{slow}}$，故 $C_{\mathrm{fast}}\equiv 0$。

**总成本：**

$$
C_{\mathrm{tot}}(y,x)=C_{\mathrm{slow}}(y)+C_{\mathrm{fast}}(x;y)
$$

---

### 3.3 快层可行域 $\mathcal{F}(y)$（给定 placement 后的 routing 约束）

对每个**已固定**的 $y$，快层变量 $(x,d)$ 满足：

**（F1）放置–流量耦合**

$$
\sum_p x^{\mathrm{in}}_{i,m,p}\le y_{i,m}\,b^{\mathrm{in}}_i,\qquad
\sum_q x^{\mathrm{out}}_{i,m,q}\le y_{i,m}\,b^{\mathrm{out}}_i
\qquad \forall i,m
$$

**（F2）名义算力容量（规划可行）**

$$
\sum_i w_{i,k}\,y_{i,m}\le C^{\mathrm{norm}}_{mk}
\qquad \forall m,k
$$

**（F3）场景送达与路径可用性（无 Big-M）**

$$
d^{\mathrm{in}}_{i,m,p,s}=
\begin{cases}
x^{\mathrm{in}}_{i,m,p}, & \text{路径 }p\text{ 在场景 }s\text{ 上 }\sigma_{es}>0 \\
0, & \text{否则}
\end{cases}
$$

egress 的 $d^{\mathrm{out}}_{i,m,q,s}$ 同理。路径可用当且仅当路径上所有边 $\sigma_{es}>0$。

**（F4）期望送达量**

$$
\mathbb{E}[\mathrm{Del}]
=\sum_{s\in\mathcal{S}}\pi_s
\left(
\sum_{i,m,p} d^{\mathrm{in}}_{i,m,p,s}
+\sum_{i,m,q} d^{\mathrm{out}}_{i,m,q,s}
\right)
$$

---

### 3.4 快层目标函数（Follower，给定 $y$）

记快层最优反应为 $(x^*(y),d^*(y))$。默认模式 **`delivery`**：

$$
\boxed{
(x^*(y),d^*(y))
\in
\arg\min_{(x,d)\in\mathcal{F}(y)}
\;
C_{\mathrm{fast}}(x;y)-\omega\,\mathbb{E}[\mathrm{Del}(x,d)]
}
$$

| 参数 | 作用 |
|:--|:--|
| $\omega\ge 0$ | 快层**唯一**的送达激励；$\omega=0$ 易零流退化 |
| $\lambda,\Gamma$ | **不进**快层目标 |

**备选快层目标（代码 `fast_objective`）：**

- **`lexicographic`**：$\max\mathbb{E}[\mathrm{Del}] \;\Rightarrow\; \min\mathbb{E}[L^{\mathrm{SLA}}] \;\Rightarrow\; \min C_{\mathrm{fast}}$（字典序，非加权）
- **`min_sla_cvar`**：$\min\;\mathrm{CVaR}^{\mathrm{SLA}}_\beta(x,d;y)$（快层内直接最小化 SLA 尾部）

---

### 3.5 场景损失与 CVaR（post-hoc，用于慢层评价）

快层解出 $d^*(y)$ 后，**不再用 MILP 松弛变量**，重算场景损失。

**（R1）任务级 SLA 损失**

$$
\ell_{is}(y)
=\max\left\{
\left[1-\frac{R^{\mathrm{in}}_{is}(y)}{b^{\mathrm{in}}_i}\right]_+,\;
\left[1-\frac{R^{\mathrm{out}}_{is}(y)}{b^{\mathrm{out}}_i}\right]_+
\right\}
$$

其中 $R^{\mathrm{in}}_{is}(y)=\sum_{m,p}d^{*\,\mathrm{in}}_{i,m,p,s}$，$R^{\mathrm{out}}_{is}$ 同理。

**（R2）场景级 SLA 损失（worst-task，非平均）**

$$
L^{\mathrm{SLA}}_s(y)=\max_{i\in\mathcal{I}}\ell_{is}(y)
$$

**（R3）节点需求与 SF 场景损失**

$$
D_{mk}(y)=\sum_i w_{i,k}\,y_{i,m}
$$

$$
L^{\mathrm{SF}}_s(y)
=\max_{m\in\mathcal{M},\,k\in\mathcal{K}}
\frac{\bigl(D_{mk}(y)-C^{\mathrm{N}}_{mks}\bigr)_+}{\bar{D}_k},
\qquad
\bar{D}_k=\max\!\left(\sum_i w_{i,k},\,1\right)
$$

**（R4）CVaR（离散 Rockafellar–Uryasev，与单层相同）**

$$
\mathrm{CVaR}^{\mathrm{SLA}}_\beta(y)
=\min_{\zeta}\left\{
\zeta+\frac{1}{1-\beta}\sum_{s\in\mathcal{S}}\pi_s\,\bigl[L^{\mathrm{SLA}}_s(y)-\zeta\bigr]_+
\right\}
$$

$\mathrm{CVaR}^{\mathrm{SF}}_\beta(y)$ 将 $L^{\mathrm{SLA}}_s$ 换为 $L^{\mathrm{SF}}_s$ 即可。  
**注意：** $\mathrm{CVaR}^{\mathrm{SF}}(y)$ **只依赖 $y$**，与 $x,d$ 无关。

---

### 3.6 慢层 Model A（Leader，加权选 placement）

$$
\boxed{
y^*
\in
\arg\min_{y\in\mathcal{Y}}
\;
C_{\mathrm{tot}}\bigl(y,x^*(y)\bigr)
+\lambda_{\mathrm{sla}}\,\mathrm{CVaR}^{\mathrm{SLA}}_\beta(y)
+\lambda_{\mathrm{sf}}\,\mathrm{CVaR}^{\mathrm{SF}}_\beta(y)
}
$$

| 项 | 进入慢层 A？ |
|:--|:--:|
| $C_{\mathrm{slow}}(y)$ | ✓ |
| $C_{\mathrm{fast}}(x^*(y))$ | ✓ |
| $\lambda_{\mathrm{sla}}\mathrm{CVaR}^{\mathrm{SLA}}(y)$ | ✓ |
| $\lambda_{\mathrm{sf}}\mathrm{CVaR}^{\mathrm{SF}}(y)$ | ✓ |
| $-\omega\,\mathbb{E}[\mathrm{Del}]$ | **✗**（仅在快层） |

$\mathcal{Y}$：满足 $\sum_m y_{i,m}=1$ 且名义容量可行的 placement 集合（toy 上 $|\mathcal{Y}|=27$）。

---

### 3.7 慢层 Model C（Leader，风险预算选 placement）

$$
\boxed{
\begin{aligned}
y^*
\in \arg\min_{y\in\mathcal{Y}} \;& C_{\mathrm{tot}}\bigl(y,x^*(y)\bigr) \\
\text{s.t.}\quad
& \mathrm{CVaR}^{\mathrm{SLA}}_\beta(y)\le \Gamma_{\mathrm{sla}}, \\
& \mathrm{CVaR}^{\mathrm{SF}}_\beta(y)\le \Gamma_{\mathrm{sf}}
\end{aligned}
}
$$

无可行 $y$ 时报告 INFEASIBLE。

---

### 3.8 整体双层问题（反应式，非 KKT 单模型）

$$
\boxed{
\begin{aligned}
\text{【快层】}\quad
&(x^*(y),d^*(y))
=\arg\min_{(x,d)\in\mathcal{F}(y)}
\bigl\{C_{\mathrm{fast}}(x;y)-\omega\,\mathbb{E}[\mathrm{Del}]\bigr\}
\\[6pt]
\text{【评价】}\quad
&\mathrm{CVaR}^{\mathrm{SLA}}(y),\;
\mathrm{CVaR}^{\mathrm{SF}}(y)
\;\text{由 §3.5 对 } d^*(y), y \text{ 重算}
\\[6pt]
\text{【慢层 A】}\quad
&\min_{y\in\mathcal{Y}}
\;C_{\mathrm{tot}}(y,x^*)
+\lambda_{\mathrm{sla}}\mathrm{CVaR}^{\mathrm{SLA}}(y)
+\lambda_{\mathrm{sf}}\mathrm{CVaR}^{\mathrm{SF}}(y)
\\[6pt]
\text{【慢层 C】}\quad
&\min_{y\in\mathcal{Y}} C_{\mathrm{tot}}(y,x^*)
\;\text{s.t.}\;
\mathrm{CVaR}^{\mathrm{SLA}}(y)\le\Gamma_{\mathrm{sla}},\;
\mathrm{CVaR}^{\mathrm{SF}}(y)\le\Gamma_{\mathrm{sf}}
\end{aligned}
}
$$

**求解方式（L0）：** 枚举 $y\in\mathcal{Y}$，每个 $y$ 解一次快层 LP，再按慢层 A/C 选最优。不是把快层 KKT 嵌入慢层 MILP。

---

### 3.9 与单层 Model A / C 对照（公式级）

**单层 Model A（联合 $y,x,d$ 一个 MILP）：**

$$
\min_{y,x,d}
\;
C_{\mathrm{tot}}(y,x)
+\lambda_{\mathrm{sla}}\mathrm{CVaR}^{\mathrm{SLA}}_\beta(x,d)
+\lambda_{\mathrm{sf}}\mathrm{CVaR}^{\mathrm{SF}}_\beta(y)
-\omega\,\mathbb{E}[\mathrm{Del}(x,d)]
$$

**单层 Model C：**

$$
\min_{y,x,d}\; C_{\mathrm{tot}}(y,x)
\quad\text{s.t.}\quad
\mathrm{CVaR}^{\mathrm{SLA}}_\beta(x,d)\le\Gamma_{\mathrm{sla}},\;
\mathrm{CVaR}^{\mathrm{SF}}_\beta(y)\le\Gamma_{\mathrm{sf}}
$$

| 对比项 | 单层 | 双层 |
|:--|:--|:--|
| 决策 | $y,x,d$ **同时** | 先 $y$（枚举），再 $x,d$ |
| 目标个数 | **1 个** | **2 个**（快层 + 慢层） |
| $\omega$ 出现位置 | 联合目标内 | **仅快层** |
| CVaR 计算 | 模型内 RU 变量 | 快层解固定后 **post-hoc** |
| 数学等价 | — | **否**；toy 上 placement 常相同 |

---

### 3.10 参数分工一览

| 参数 | 快层 | 慢层 A | 慢层 C |
|:--|:--:|:--:|:--:|
| $\omega$ | ✓ | ✗ | ✗ |
| $\lambda_{\mathrm{sla}},\lambda_{\mathrm{sf}}$ | ✗ | ✓ | ✗ |
| $\Gamma_{\mathrm{sla}},\Gamma_{\mathrm{sf}}$ | ✗ | ✗ | ✓ |

---

## 4. 模型与符号说明（摘要）

**完整符号表**见 [`weekly_report_20250611.md`](weekly_report_20250611.md) **§3.1**。§3 已给出双层双目标完整公式；此处仅保留风险聚合摘要。

**（1）不是每任务一个 CVaR，也不是场景内取平均**

| 风险 | 场景内聚合 | 跨场景 |
|:--|:--|:--|
| SLA | 先算每任务 $\ell_{is}$，再 **$\max_i$**（worst-task） | 对 $L^{\mathrm{SLA}}_s$ 求 CVaR → **一个标量** |
| SF | 同节点需求先加总 $D_{mk}$，再 **$\max_{m,k}$** | 对 $L^{\mathrm{SF}}_s$ 求 CVaR → **一个标量** |

快层只影响 SLA 的 $R^{\mathrm{in/out}}_{is}$（经 $x^*,d^*$）；SF 只依赖 placement $y$，与路由无关。

**（2）$\bar{D}_k = \max(\sum_i w_{i,k}, 1)$ 是资源维 $k$ 的固定归一化尺度**

- $k$ = CPU / GPU / HBM，**不是**任务编号；
- 本 toy：$\bar{D}_{\mathrm{CPU}}=6$，$\bar{D}_{\mathrm{GPU}}=\bar{D}_{\mathrm{HBM}}=3$；
- AAA 全挤 A 且 CPU 全失效 → $L^{\mathrm{SF}}_s$ 可达 1.0；ACC 分散放置 → 同故障下分子更小。

---

## 5. 实验结果与分析

**实验实例：** 与 6/11 报告相同的 ComponentRisk toy（3 任务 × 3 节点，27 placements，512 场景，$\beta = 0.8$，$\omega = 1$）。  
**快层模式：** `delivery`（默认）。  
**脚本：** `python scripts/run_bilevel_gamma_frontier.py --grid-size 3 --compare-single`

### 5.1 单点冒烟

| 模型 | placement | cost | CVaR_SLA | CVaR_SF | 与单层 |
|:--|:--:|--:|--:|--:|:--:|
| 双层 A | CCC | 0.84 | 0.050 | 0.025 | placement 一致 |
| 双层 C | CCC | 0.84 | 0.050 | 0.025 | placement 一致 |
| 单层 A（对照） | CCC | 0.84 | 0.050 | 0.025 | cost_gap = 0 |

在 tight $\Gamma$ 与均衡 $\lambda$ 下，双层与单层 placement、成本、CVaR **完全一致**。

### 5.2 Γ 前沿扫描

| $\Gamma_{\mathrm{sla}}$ | $\Gamma_{\mathrm{sf}}$ | 双层 placement | cost | 单层 placement | match | cost_gap |
|--:|--:|:--:|--:|:--:|:--:|--:|
| 0.05 | 0.025 | CCC | 0.84 | CCC | ✓ | 0 |
| 0.05 | 1.0 | AAA | 0.12 | AAA | ✓ | 0 |
| 0.525 | 0.5125 | **ACC** | 0.60 | **CCA** | ✗ | 0 |
| 1.0 | 0.5125 | ABB | 0.14 | BBA | ✗ | 0 |
| 1.0 | 1.0 | AAA | 0.12 | AAA | ✓ | 0 |

**汇总：** 9/9 双层可行；7/9 与单层 placement 一致；2/9 不一致但 cost/CVaR 接近。

### 5.3 结果解读

**（1）纯 placement 结构复现**

- $\Gamma$ 双紧 → **CCC**（高可靠高成本）；
- $\Gamma_{\mathrm{sf}}$ 很宽 → **AAA**（最低成本）；
- $\Gamma_{\mathrm{sla}}$ 宽、$\Gamma_{\mathrm{sf}}$ 中等 → **ABB** 类混合（两任务 B + 一任务 A，成本 0.14，低于纯 BBB 的 0.15）。

与 6/11 单层 Model C 的节点级 trade-off **一致**，说明快慢分解在 toy 上能复现主要 placement 结构。

**（2）中间预算出现混合解 ACC**

在 $(\Gamma_{\mathrm{sla}}, \Gamma_{\mathrm{sf}}) = (0.525, 0.5125)$ 时，双层最优为 **ACC**（cost = 0.60，SLA CVaR ≈ 0.099，SF CVaR ≈ 0.342），与单层 Model C 在中间区间出现混合解的现象**同型**。

**（3）不一致点：对称等价类 tie-break**

| 网格点 | 双层 | 单层 | 说明 |
|:--|:--|:--|:--|
| (0.525, 0.5125) | ACC | CAC | 1A+2C 排列等价，成本与 CVaR 相同（0.60） |
| (1.0, 0.5125) | ABB | BBA | 2B+1A 排列等价，成本与 CVaR 相同（0.14） |

这些不一致**不是实现错误**，而是：

- 对称任务下多个等价最优 placement；
- 双层 post-hoc CVaR vs 单层模型内 CVaR 变量在边界点的数值/ tie-break 差异。

报告时应写「等价类一致 / tie-break 不同」，而非简单说「模型错了」。

### 5.4 Model A 方向性验证

| 设置 | 双层最优 | 解释 |
|:--|:--|:--|
| $\lambda_{\mathrm{sf}} = 10, \lambda_{\mathrm{sla}} = 0$ | 非 AAA | 算力风险权重高，避开 A |
| $\lambda_{\mathrm{sla}} = \lambda_{\mathrm{sf}} = 1$ | CCC | 与单层 A 一致 |

### 5.5 运行时

单网格点双层枚举 27 placements × 快层 LP：约 **2~3 s** / 点（Gurobi academic license）。  
3×3 全网格约 **24 s**。toy 可接受；B4 不能直接枚举，需后续分解式或启发式慢层。

---

## 6. 自动化验证状态

| 测试内容 | 数量 | 状态 |
|:--|--:|:--:|
| 双层 TEAVAR（快层、A/C、单层对照、AAA 成本） | 8 | 通过 |
| ComponentRisk toy（单层回归） | 14 | 通过 |

`tests/test_bilevel_teavar.py` 覆盖：

- 快层 OPTIMAL 与 $\mathbb{E}[\mathrm{Del}] > 0$；
- `lexicographic` 与 `delivery` 送达量一致；
- 高 $\lambda_{\mathrm{sf}}$ 避开 AAA；
- tight $\Gamma$ 选 CCC；
- 双层 C vs 单层 C @ tight $\Gamma$ placement 一致；
- AAA 慢层成本 = 0.12 手算验证。

---

## 7. 本周结论

1. **独立模块已就绪：** `bilevel_teavar_models.py` 将慢层 placement、快层 routing、Model A/C、post-hoc risk 解耦，**未改动单层代码**。

2. **定位清晰：** L0 枚举式反应双层 baseline，用于验证「快慢时间尺度分解能否复现单层 placement 结构」，不是 B4 主链，也不是 Stackelberg KKT 单模型。

3. **toy 验证通过：** ComponentRisk 上双层 C 的 Γ 扫描复现 AAA / BBB / CCC，并在中间预算出现 **ACC** 类混合解；与单层 7/9 网格点 placement 完全一致，2/9 为对称 tie-break 或边界 gap。

4. **概念边界已文档化：** 双层 A ≠ 单层 A；$\omega$ 仅快层；$\lambda/\Gamma$ 仍必需且主要作用于慢层。

5. **工程缺口明确：** B4 规模需慢层非枚举 + 快层 LP 批量；多路径应用 `lexicographic`；Γ 标定应分单层/双层两套口径说明。

**论文可用表述：**

> 我们实现了一个独立的 L0 枚举式快慢双层 TEAVAR 验证模块。慢层枚举可行 placement 并按 Model A 或 Model C 选择；快层在给定 placement 后求解连续 routing 子问题；SLA/SF CVaR 在快层解固定后 post-hoc 计算。该模块用于 toy 上与单层精确模型对照，验证 placement–routing 时间尺度分解能否复现节点级 cost–risk 结构。当前版本不是 KKT 嵌入的严格 Stackelberg 模型；双层 Model A 与单层 Model A 不等价（$\omega$ 仅作用于快层 routing）。

---

## 8. 下一步计划

1. **扩大 Γ 前沿**  
   运行 `--grid-size 7`，输出完整 frontier CSV，汇总 mismatch 区间与 ACC 出现带。

2. **mismatch 汇总脚本**  
   读取 `bilevel_gamma_frontier_*.csv`，按等价类（ACC/CCA）合并统计，避免对称解误判为「模型不一致」。

3. **快层 lexicographic 对照实验**  
   在有多路径实例上对比 `delivery` vs `lexicographic` 的 $\mathrm{Risk}(y)$ 稳定性。

4. **双层 vs 单层 gap 表进论文 §7**  
   报告 cost_gap、CVaR_gap、runtime；单层 Model C 为基准，双层为可扩展近似方向。

5. **暂不挂 main.py**  
   等 frontier 与 gap 表稳定后，再以 `--bilevel` 可选 flag 接入，默认路径保持单层。

6. **B4 路径预研（文档级）**  
   慢层：启发式 / 列生成 / 受限枚举；快层：固定 $y$ 的 LP 批量；不急于 KKT Stackelberg。

---

## 9. 附录：常用命令

```bash
# 单点冒烟
python scripts/run_bilevel_smoke.py --lambda-sla 1 --lambda-sf 1 --omega 1 --compare-single

# Γ 前沿（含单层 C 对照）
python scripts/run_bilevel_gamma_frontier.py --grid-size 5 --compare-single \
  --output results/bilevel_gamma_frontier_cr.csv

# 快层 lexicographic
python scripts/run_bilevel_gamma_frontier.py --fast-objective lexicographic --compare-single

# 单元测试
python -m unittest tests.test_bilevel_teavar -v
```

---

**本周小结**：在保留单层 Model A/C 不变的前提下，完成了 L0 枚举式快慢双层 TEAVAR 模块及 Γ 前沿对照实验。结果表明，在 ComponentRisk toy 上，双层 Model C 能复现单层的主要 placement 结构（含 ACC 混合解），并明确了与单层 Model A 的非等价关系及当前模块作为 validation baseline 的边界。
