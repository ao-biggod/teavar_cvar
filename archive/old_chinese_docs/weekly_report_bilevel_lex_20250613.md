# 6月13日工作报告（严格风险优先字典序双层 TEAVAR）


## 1. 本周工作概述

本周在 6/12 双层基线（$\lambda$/$\Gamma$ 慢层 + 送达优化快层）之外，新增**独立扩展模块**：严格风险优先的字典序双层 TEAVAR。

核心变化：

1. **不再使用** $\lambda$、$\Gamma$、$\varepsilon$、$\omega$——避免 $c_{\mathrm{tot}}$ 与 CVaR 量纲混合；
2. **快层**（Copo 跟随者）：给定放置 $y$，按字典序 min $\mathrm{CVaR}^{\mathrm{SLA}}_\beta$ → max $\mathbb{E}[\mathrm{Del}]$ → min $c_b$；
3. **慢层**（领导者）：严格字典序 min $\mathrm{CVaR}^{\mathrm{SF}}_\beta$ → min $R^{\mathrm{SLA}}(y)$ → min $c_{\mathrm{tot}}(y,x^*)$；
4. **带宽成本**改为流量计价：$c_b=\sum_{i,m,p}x_{i,m,p}^{in}\tau_p+\sum_{i,m,q}x_{i,m,q}^{out}\tau_q$（`bandwidth_cost_on_placement=False`）。

**模型定位（写死）：**

> **严格风险优先字典序双层 TEAVAR**  
> *本模型是严格风险优先的字典序双层模型，不是成本–风险折中模型。*

该版本**不用于**刻画成本–风险连续折中或帕累托前沿；用于回答：在不手动设定 $\lambda$/$\Gamma$ 的情况下，**严格风险优先**的最优方案是什么。

---

## 2. 模型设计

### 2.1 设计动机：从 Copo 到字典序双层

Copo 的核心不是「消掉参数」，而是：

| 范式 | 形式 | 问题 |
|:--|:--|:--|
| 加权 | $\min c_{\mathrm{tot}} + \lambda_{\mathrm{sla}}\cdot\text{风险}$ | 量纲混合，需扫 $\lambda$ |
| $\varepsilon$-约束 | $\min c_{\mathrm{tot}}$ s.t. $\mathrm{CVaR}^{\mathrm{SLA}}_\beta\le\Gamma_{\mathrm{sla}}$ | 需手设合同线 $\Gamma_{\mathrm{sla}}$ |
| **Copo / 字典序** | 上层 $\min c_{\mathrm{tot}}$；下层 $\min$ 性能 | 性能不进成本目标 |

本项目将 $\mathrm{CVaR}^{\mathrm{SLA}}_\beta$ 作为快层性能指标（类似 Copo 的负载均衡）；$\mathrm{CVaR}^{\mathrm{SF}}_\beta$ 仅依赖放置 $y$，放在慢层字典序前两阶段。

**与 6/12 双层基线的区别：**

| 对比项 | 6/12 基线 | 本周字典序模型 |
|:--|:--|:--|
| 慢层偏好 | $\lambda$ 或 $\Gamma$ | 严格字典序 SF → SLA → 成本 |
| 快层默认 | `delivery`（含 $\omega$） | `lex_sla_delivery_cost`（无 $\omega$） |
| 带宽计费 | 放置绑定价（玩具默认） | **流量 × 路径单价** |
| 模型语义 | 成本–风险可调 | **严格风险优先，非折中** |

### 2.2 优先级与理由

默认优先级：

```text
CVaR^SF_β  ≻  R^SLA(y)  ≻  c_tot
```

其中 $R^{\mathrm{SLA}}(y)$ 为给定 $y$ 下快层最优路由反应对应的 $\mathrm{CVaR}^{\mathrm{SLA}}_\beta$（见 §3.2）。

**SF 优先于 SLA 的理由（放置慢决策 vs 路由快决策）：**

- 算力放置是慢决策，一旦节点降级（$C^{\mathrm{N}}_{m,k,s}$ 下降），快层路由**无法修复** $\mathrm{CVaR}^{\mathrm{SF}}_\beta$；
- SLA 尾部风险部分可通过重路由缓解；
- 因此先保证 $y$ 不落入算力高风险结构，再比较 $R^{\mathrm{SLA}}(y)$，最后才谈 $c_{\mathrm{tot}}$。

**重要声明：**

> 该模型不是「自动折中模型」，而是**风险字典序模型**。  
> 若结果偏向 **CCC / 偏 C 节点**，是严格风险优先语义的自然结果，**不是实现缺陷**。

### 2.3 求解流程（L0 枚举 + 快层三阶段线性规划）

```text
对每个可行放置 y（27 种）
  → 快层 F1: min CVaR^SLA_β
  → 快层 F2: CVaR^SLA_β ≤ R^SLA(y) + tol, max E[Del]
  → 快层 F3: 上式 + E[Del] ≥ E[Del]* - tol, min c_b
  → 得 x*(y), d*(y), R^SLA(y), c_p(y), c_b(x*;y)
  → 事后重算: CVaR^SF_β（仅依赖 y）

慢层字典序（全体 27 行）:
  阶段 1: min CVaR^SF_β     → Y1
  阶段 2: 在 Y1 上 min R^SLA(y) → Y2
  阶段 3: 在 Y2 上 min c_tot     → y*
```

仍属**枚举式双层基线**，不是 KKT 嵌入的斯塔克尔伯格单模型。

### 2.4 快层 / 慢层分工

| | 快层（路由） | 慢层（放置枚举） |
|:--|:--|:--|
| **决策** | $x_{i,m,p}^{in}$，$x_{i,m,q}^{out}$，$d_{i,m,p,s}^{in}$，$d_{i,m,q,s}^{out}$ | $y_{i,m}$（枚举 27 种） |
| **优化** | min $\mathrm{CVaR}^{\mathrm{SLA}}_\beta$ → max $\mathbb{E}[\mathrm{Del}]$ → min $c_b$ | min SF → min SLA → min $c_{\mathrm{tot}}$ |
| **算力 CVaR** | 不参与（路由无法改变 $D_{m,k}$） | 阶段 1：$\mathrm{CVaR}^{\mathrm{SF}}_\beta$ |
| **SLA CVaR** | 快层直接优化 $R^{\mathrm{SLA}}(y)$ | 阶段 2：比较 $R^{\mathrm{SLA}}(y)$ |
| **成本** | $c_b(x;y)$ | $c_{\mathrm{tot}}=c_p(y)+c_b(x^*;y)$，阶段 3 |
| **参数** | 无 $\lambda$/$\Gamma$/$\varepsilon$/$\omega$ | 无 $\lambda$/$\Gamma$/$\varepsilon$/$\omega$ |

---

## 3. 完整公式体系

**符号约定：** 集合、决策变量、场景概率、$\sigma_{e,s}$、$C^{\mathrm{norm}}_{m,k}$、$C^{\mathrm{N}}_{m,k,s}$、$D_{m,k}$、$x_{i,m,p}^{in/out}$、$d_{i,m,p,s}^{in/out}$、$L^{\mathrm{SLA}}_s$、$L^{\mathrm{SF}}_s$、$\bar D_k$、$\mathrm{CVaR}^{\mathrm{SLA}}_\beta$、$\mathrm{CVaR}^{\mathrm{SF}}_\beta$、$c_p$、$c_b$、$c_{\mathrm{tot}}$ 等**一律沿用** [`docs/model_ac_建模说明.md`](../docs/model_ac_建模说明.md) **§2–§6**。本节只补充双层字典序专用符号。

### 3.1 双层字典序专用符号（增量）

| 符号 | 含义 |
|:--|:--|
| $R^{\mathrm{SLA}}(y)$ | 给定放置 $y$ 后，快层最优路由反应下的 SLA CVaR：$R^{\mathrm{SLA}}(y)=\min_{x,d\in\mathcal{F}(y)}\mathrm{CVaR}^{\mathrm{SLA}}_\beta$ |
| $(x^*(y),d^*(y))$ | 快层字典序（F1→F2→F3）选定的最优路由解 |
| $R^{\mathrm{SF},*}$ | 慢层阶段 1 边界：$\min_{y\in\mathcal{Y}}\mathrm{CVaR}^{\mathrm{SF}}_\beta$ |
| $R^{\mathrm{SLA},*}$ | 慢层阶段 2 边界：$\min_{y\in\mathcal{Y}_1} R^{\mathrm{SLA}}(y)$ |
| $\mathcal{Y}_1,\mathcal{Y}_2$ | 阶段 1 / 2 最优放置集合 |
| $\texttt{tol}$ | 数值容差（$10^{-9}$），仅用于浮点相等判断，**不是**业务松弛 $\varepsilon$ |

**与单层 Model A/C 符号的关系：**

- $\mathrm{CVaR}^{\mathrm{SLA}}_\beta$、$\mathrm{CVaR}^{\mathrm{SF}}_\beta$：与 Model A/C **同名、同口径**（worst-task 聚合 SLA；节点–资源 max 聚合 SF）；
- $R^{\mathrm{SLA}}(y)$ **不是**新风险度量，而是「固定 $y$ 后对 routing 取 min 的 $\mathrm{CVaR}^{\mathrm{SLA}}_\beta$」；
- 场景损失仍为 $L^{\mathrm{SLA}}_s=\max_i\max\{\ell^{\mathrm{in}}_{is},\ell^{\mathrm{out}}_{is}\}$，算力场景损失仍为 $L^{\mathrm{SF}}_s=\max_{m,k}(D_{m,k}-C^{\mathrm{N}}_{m,k,s})_+/\bar D_k$（见 model_ac §6）。

### 3.2 成本分解（与 Model A/C §2.5 一致；本轮为 flow 模式）

**资源部署成本 $c_p(y)$：**

$$
c_p(y)=\sum_{i,m,k} w_{i,k}\, p_{m,k}\, y_{i,m}
$$

**带宽成本 $c_b(x;y)$（计划流量口径，flow 模式）：**

$$
c_b(x;y)
=\sum_{i,m,p}\tau_p\, x_{i,m,p}^{in}
+\sum_{i,m,q}\tau_q\, x_{i,m,q}^{out}
$$

其中 $\tau_p=\sum_{e\in p}\pi^{\mathrm{price}}_e$，$\tau_q$ 同理（model_ac §2.2）。

**总成本（字典序模型无 $\omega$，故无送达奖励项）：**

$$
c_{\mathrm{tot}}(y,x)=c_p(y)+c_b(x;y)
$$

**本轮 flow 模式：** `bandwidth_cost_on_placement=False`，故带宽全部由 $c_b(x^*;y)$ 进入 $c_{\mathrm{tot}}$。  
（placement 计费时，$c_b=\sum_{i,m} b_i^{in}(\tau_p^{in}+\tau_q^{out})y_{i,m}$ 且快层 $c_b\equiv 0$，见 model_ac §2.5。）

### 3.3 快层：给定 $y$ 的字典序路由

**可行域** $\mathcal{F}(y)$：放置–流量耦合、场景送达、$\sigma_{e,s}$ 路径可用性、链路名义容量 $ \sum x\delta \le B_e$ 等（与 model_ac §8；$y_{i,m}$ 以常数嵌入）。

**阶段 F1：**

$$
R^{\mathrm{SLA}}(y)
=
\min_{x,d \in \mathcal{F}(y)}
\mathrm{CVaR}^{\mathrm{SLA}}_\beta
$$

$$
\mathcal{X}_1(y)
=
\arg\min_{x,d \in \mathcal{F}(y)}
\mathrm{CVaR}^{\mathrm{SLA}}_\beta
$$

**阶段 F2（CVaR 已达 $R^{\mathrm{SLA}}(y)$）：**

$$
(x,d)
\in
\arg\max_{
(x,d)\in\mathcal{F}(y),\;
\mathrm{CVaR}^{\mathrm{SLA}}_\beta\le R^{\mathrm{SLA}}(y)+\texttt{tol}}
\mathbb{E}[\mathrm{Del}]
$$

**阶段 F3（次级排序）：**

$$
(x^*(y),d^*(y))
\in
\arg\min_{
(x,d)\ \text{满足 F1–F2}}
c_b(x;y)
$$

**期望送达（与 model_ac §5.2 一致）：**

$$
\mathbb{E}[\mathrm{Del}]
=
\sum_{s\in\mathcal{S}}\pi_s
\left(
\sum_{i,m,p} d_{i,m,p,s}^{in}
+\sum_{i,m,q} d_{i,m,q,s}^{out}
\right)
$$

实现为**顺序重求**三个线性规划。代码模式名：`fast_objective="lex_sla_delivery_cost"`。

### 3.4 慢层：严格字典序放置

**阶段 SF：**

$$
R^{\mathrm{SF},*}
=
\min_{y \in \mathcal{Y}}
\mathrm{CVaR}^{\mathrm{SF}}_\beta
$$

$$
\mathcal{Y}_1
=
\left\{
y\in\mathcal{Y}:
\mathrm{CVaR}^{\mathrm{SF}}_\beta=R^{\mathrm{SF},*}
\right\}
$$

**阶段 SLA：**

$$
R^{\mathrm{SLA},*}
=
\min_{y \in \mathcal{Y}_1}
R^{\mathrm{SLA}}(y)
$$

$$
\mathcal{Y}_2
=
\left\{
y\in\mathcal{Y}_1:
R^{\mathrm{SLA}}(y)=R^{\mathrm{SLA},*}
\right\}
$$

**阶段 成本：**

$$
y^*
\in
\arg\min_{y \in \mathcal{Y}_2}
c_{\mathrm{tot}}\bigl(y,x^*(y)\bigr)
=
\arg\min_{y \in \mathcal{Y}_2}
\Big[
c_p(y)+c_b\big(x^*(y);y\big)
\Big]
$$

### 3.5 风险损失与 CVaR 聚合（复述 model_ac §6 口径，无新定义）

**SLA（与 model_ac §6.1 相同）：**

$$
\ell^{\mathrm{in}}_{is}
=
\left[1-\frac{R^{\mathrm{in}}_{is}}{b_i^{in}}\right]_+,
\quad
\ell^{\mathrm{out}}_{is}
=
\left[1-\frac{R^{\mathrm{out}}_{is}}{b_i^{out}}\right]_+,
\qquad
L^{\mathrm{SLA}}_s=\max_{i\in\mathcal{I}}\max\{\ell^{\mathrm{in}}_{is},\,\ell^{\mathrm{out}}_{is}\}
$$

**SF（与 model_ac §6.2 相同）：**

$$
D_{m,k}=\sum_i w_{i,k}\,y_{i,m},
\qquad
L^{\mathrm{SF}}_s
=
\max_{m,k}
\frac{\bigl(D_{m,k}-C^{\mathrm{N}}_{m,k,s}\bigr)_+}{\bar D_k}
$$

**CVaR（Rockafellar–Uryasev，置信水平 $\beta=0.8$）：**

$$
\mathrm{CVaR}^{\mathrm{SLA}}_\beta
=
\zeta + \frac{1}{1-\beta}\sum_{s\in\mathcal{S}}\pi_s\, u_s,
\qquad
\mathrm{CVaR}^{\mathrm{SF}}_\beta
=
\zeta^{\mathrm{sf}} + \frac{1}{1-\beta_{\mathrm{sf}}}\sum_{s\in\mathcal{S}}\pi_s\, \phi_s
$$

（线性化约束见 model_ac §6；本轮 $\beta_{\mathrm{sla}}=\beta_{\mathrm{sf}}=\beta=0.8$。）  
**不是**每任务一个 CVaR，也**不是**场景内对任务取平均。

快层只影响 $R^{\mathrm{in/out}}_{is}$（经 $x^*,d^*$）；$\mathrm{CVaR}^{\mathrm{SF}}_\beta$ 只依赖 $y$。

### 3.6 与 Copo 的对应

| Copo | 本模型（符号与 model_ac 一致） |
|:--|:--|
| 上层：$\min$ 电力 + 带宽 | 慢层阶段 3：$\min c_{\mathrm{tot}}=c_p+c_b$ |
| 下层：$\min$ 性能 | 快层：$\min \mathrm{CVaR}^{\mathrm{SLA}}_\beta$（+ 字典序次级排序） |
| 性能不与 cost 加权 | CVaR 不与 $c_{\mathrm{tot}}$ 加权 |
| KKT 单层化 | 暂不；L0 枚举 + 快层线性规划 |

---

## 4. 数据与配置口径

### 4.1 故障场景

与 model_ac §2.4 相同：**9 组件独立故障率 → 512 场景**（`component_scenario_generator.py`）。

| 类型 | 组件 | $q_c$ |
|:--|:--|--:|
| A 链路 | A_in, A_out | 0.005 |
| B 链路 | B_in, B_out | 0.10 |
| C 链路 | C_in, C_out | 0.005 |
| 算力降级 | A / B / C 算力组件 | 0.20 / 0.01 / 0.005 |

场景概率 $\pi_s=\prod_{c\in\mathcal{F}_s} q_c \prod_{c\notin\mathcal{F}_s}(1-q_c)$。  
CVaR 置信水平 $\beta=0.8$（与 model_ac §2.6 一致，记 $\beta_{\mathrm{sla}}=\beta_{\mathrm{sf}}=\beta$）。

### 4.2 带宽成本：流量计价模式

本轮实验使用：

```text
bandwidth_mode = "flow"
bandwidth_cost_on_placement = False
pricing_mode = uniform（显式 π_e / link_price）
```

**原因：** 字典序第三阶段要最小化 $c_{\mathrm{tot}}$；若带宽仍在 placement 模式的 $c_b=\sum b_i^{in}(\tau_p+\tau_q)y_{i,m}$ 项，快层计划流 $c_b(x)$ 无法体现路由差异。

遗留 regression 保留：`build_toy_combined_component_risk()` 默认仍为 placement 计费（见 model_ac §2.5 放置模式）。

### 4.3 解析后配置（本轮运行）

| 字段 | 值 |
|:--|:--|
| 实例名 | Toy-Combined-ComponentRisk |
| 场景类型 | 组件独立故障 |
| $|\mathcal{S}|$ | 512 |
| 带宽模式 | flow（$c_b(x)$ 计价） |
| 快层目标 | lex_sla_delivery_cost |
| 优先级 | SF → SLA → $c_{\mathrm{tot}}$ |
| 模型名 | 严格风险优先字典序双层 TEAVAR |

完整 JSON：`results/bilevel_lex_cr_flow.resolved_config.json`。

### 4.4 CSV 列名与报告符号对照

代码输出列名保持 snake_case；报告与 model_ac 符号对应如下：

| CSV 列 | 报告符号 | 含义 |
|:--|:--|:--|
| `cost_deploy` | $c_p(y)=\sum_{i,m,k} w_{i,k}p_{m,k}y_{i,m}$ | 资源部署成本 |
| `cost_bw` | $c_b(x^*;y)$ | 快层计划流量带宽费 |
| `cost_total` | $c_{\mathrm{tot}}(y,x^*)=c_p+c_b$ | 总成本 |
| `r_sla` | $R^{\mathrm{SLA}}(y)$ | 快层最优 SLA CVaR 反应 |
| `r_sf` | $\mathrm{CVaR}^{\mathrm{SF}}_\beta$ | 算力 CVaR（仅依赖 $y$） |
| `e_del` | $\mathbb{E}[\mathrm{Del}]$ | 期望送达量 |
| `x_sum` | $\sum x_{i,m,p}^{in}+\sum x_{i,m,q}^{out}$ | 计划流量和（诊断用） |

---

## 5. 实验结果与分析

**实验实例：** ComponentRisk 玩具实例，$|\mathcal{I}|=3$，$|\mathcal{M}|=3$，27 种放置，$|\mathcal{S}|=512$。  
**脚本：** `python scripts/run_bilevel_lex_smoke.py`  
**运行时：** 约 **10.8 秒**（27 × 快层 3 阶段线性规划，Gurobi 学术许可）。

### 5.1 字典序求解汇总

| 指标 | 值 |
|:--|:--|
| 求解状态 | 最优 |
| **最优放置** | **CCC** |
| $R^{\mathrm{SF},*}$ | 0.025 |
| $R^{\mathrm{SLA},*}$ | 0.049875 |
| $\min c_{\mathrm{tot}}$ | 0.840 |
| $|\mathcal{Y}_1|$ | **1** |
| $|\mathcal{Y}_2|$ | **1** |
| 最优解个数 | 1 |

**三阶段过滤过程：**

1. **阶段 SF：** 全表最低 $\mathrm{CVaR}^{\mathrm{SF}}_\beta=0.025$，**仅 CCC** 达到 → $\mathcal{Y}_1=\{\mathrm{CCC}\}$；
2. **阶段 SLA：** 在 $\mathcal{Y}_1$ 内 $R^{\mathrm{SLA}}=0.049875$ → $\mathcal{Y}_2=\{\mathrm{CCC}\}$；
3. **阶段 成本：** 在 $\mathcal{Y}_2$ 内 $\min c_{\mathrm{tot}}$ → **CCC**（$c_{\mathrm{tot}}=0.84$）。

AAA（$c_{\mathrm{tot}}=0.12$）虽 $R^{\mathrm{SLA}}(y)$ 与 CCC 接近（$\mathrm{CVaR}^{\mathrm{SLA}}_\beta\approx 0.05$），但 $\mathrm{CVaR}^{\mathrm{SF}}_\beta=1.0$（与 ComponentRisk 纯 AAA 一致），在阶段 1 即被淘汰。

### 5.2 代表性放置对比（27 行表摘要）

| 放置 | $c_p$ | $c_b$ | $c_{\mathrm{tot}}$ | $R^{\mathrm{SLA}}(y)$ | $\mathrm{CVaR}^{\mathrm{SF}}_\beta$ | $\mathbb{E}[\mathrm{Del}]$ | $\in\mathcal{Y}_1$ | 最优 |
|:--:|--:|--:|--:|--:|--:|--:|:--:|:--:|
| **CCC** | 0.36 | 0.48 | **0.84** | **0.049875** | **0.025** | 5.97 | ✓ | ✓ |
| AAA | 0.00 | 0.12 | 0.12 | 0.049875 | 1.000 | 5.97 | | |
| BBB | 0.09 | 0.06 | 0.15 | 0.950 | 0.050 | 5.40 | | |
| ACC | 0.24 | 0.36 | 0.60 | 0.099 | 0.342 | 5.97 | | |

（表中 $c_p$ 即 CSV 列 `cost_deploy`；$c_b$ 即 `cost_bw`。）

**观察：**

- flow 模式下 $c_b>0$ 且随 $x^*$ 变化（AAA 为 0.12，CCC 为 0.48）；
- $\mathbb{E}[\mathrm{Del}]>0$，计划流量和 $\approx 6$，无低 $R^{\mathrm{SLA}}$ 零流异常解；
- Model C 中间 $\Gamma$ 下的 **ACC 混合解**在本模型下不出现——ACC 的 $\mathrm{CVaR}^{\mathrm{SF}}_\beta=0.342$ 在阶段 1 已被淘汰。

### 5.3 与 Model C / 6/12 双层 / 字典序双层的对照

| 模型 | 典型结果 | 语义 |
|:--|:--|:--|
| 模型 C（$\Gamma$ 中等） | ACC、ABB 等混合 | 成本–风险**折中** |
| 双层基线（$\lambda$/$\Gamma$） | 与单层 7/9 网格一致 | 验证快慢分解 |
| **字典序双层（本周）** | **CCC** | **严格风险优先** |

三种模型回答**不同问题**——不应以「未出现 ACC」判定实现错误。

### 5.4 SF 与 SLA 分开优化的必要性

本轮**未**使用 $\max\{\mathrm{CVaR}^{\mathrm{SLA}}_\beta,\mathrm{CVaR}^{\mathrm{SF}}_\beta\}$ 单标量，原因见 model_ac §6：两类损失 $L^{\mathrm{SLA}}_s$、$L^{\mathrm{SF}}_s$ 聚合机制不同，数值同在 $[0,1]$ 不可互换。

---

## 6. 自动化验证状态

| 测试内容 | 数量 | 状态 |
|:--|--:|:--:|
| 字典序双层 | 6 | **通过** |
| 原双层基线 | 8 | **通过**（未回归） |

---

## 7. 本周结论

1. **独立扩展已就绪**，未改动单层默认路径。  
2. **符号与 model_ac 一致**：$c_{\mathrm{tot}}$、$c_p$、$c_b$、$\ell^{\mathrm{in/out}}_{is}$、$L^{\mathrm{SLA}}_s$、$L^{\mathrm{SF}}_s$、$\mathrm{CVaR}^{\mathrm{SLA}}_\beta$、$\mathrm{CVaR}^{\mathrm{SF}}_\beta$；双层增量仅 $R^{\mathrm{SLA}}(y)$、$R^{\mathrm{SF},*}$、$R^{\mathrm{SLA},*}$。  
3. **最优 CCC** 与 ComponentRisk 纯 CCC 风险特征一致；AAA 的 $\mathrm{CVaR}^{\mathrm{SF}}_\beta=1.0$ 导致字典序阶段 1 淘汰——**语义结果，非缺陷**。

**论文可用表述：**

> 在 ComponentRisk 实例上，严格字典序双层模型按 $\mathrm{CVaR}^{\mathrm{SF}}_\beta\succ R^{\mathrm{SLA}}(y)\succ c_{\mathrm{tot}}$ 选取放置；快层最小化 $\mathrm{CVaR}^{\mathrm{SLA}}_\beta$ 并字典序优化 $\mathbb{E}[\mathrm{Del}]$ 与 $c_b$。风险损失与 CVaR 定义与单层 Model A/C 完全相同（[`model_ac_建模说明.md`](../docs/model_ac_建模说明.md) §6）。最优解为 CCC，与严格风险优先语义一致。

---

## 8. 下一步计划

1. 优先级敏感性：`priority=("SLA","SF","Cost")`。  
2. 可选 $\varepsilon$ 软化（与 strict lex 分支，不混入主模型）。  
3. 三模型对照表（Model C / 6/12 双层 / 字典序双层）。  
4. 精确枚举交叉验证。  
5. B4 路径预研；暂不挂 `main.py`。

---

## 9. 附录：常用命令

```bash
python -m unittest tests.test_bilevel_lexicographic -v
python scripts/run_bilevel_lex_smoke.py
```

**输出文件：**

| 路径 | 内容 |
|:--|:--|
| `results/bilevel_lex_cr_flow.csv` | 27 行；列名见 §4.4 对照表 |
| `results/bilevel_lex_cr_flow.resolved_config.json` | 配置 + $R^{\mathrm{SF},*}$ / $R^{\mathrm{SLA},*}$ / $\min c_{\mathrm{tot}}$ |

---

*报告结束。符号 master 表见 [`docs/model_ac_建模说明.md`](../docs/model_ac_建模说明.md) §2。*
