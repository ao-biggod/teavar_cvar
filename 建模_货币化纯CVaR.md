# 货币化场景损失与纯 CVaR 目标（Model M / Model M-C）

> **文档定位**：**推荐的主线建模叙事**（金融原教旨 $\min\mathrm{CVaR}_\beta(L)$）；[`项目总结_模型AC.md`](./项目总结_模型AC.md) 描述 **已实现** 的 Model A/C（E + $\lambda$·CVaR + $\omega$），作为对照、Pareto 标定与复现实验基线。  
> **代码状态**：Model M / M-C 已实现于 [`monetary_cvar.py`](./monetary_cvar.py)；本文为公式 spec 与 A 的对照说明。

---

## 0. 阅读说明

- 公式用 `$…$` / `$$…$$`；预览：`Ctrl+Shift+V`。  
- 物理约束、$d$–路径耦合与 [`项目总结_模型AC.md`](./项目总结_模型AC.md) §5–§6 **相同**。  
- 本文改 **$L_s$ 定义、风险聚合语义、目标函数**；§3.5 为 **必读**（与现 Model A 的结构差异）。

---

## 1. 动机

### 1.1 金融原教旨

Rockafellar & Uryasev (2000)：

$$
\min_x \;\mathrm{CVaR}_\beta\bigl(L(x,\xi)\bigr)
$$

$L$ 为 **统一量纲的随机损失**（本文取 **货币**），而非 $\mathbb{E}[\text{成本}]+\lambda\cdot\mathrm{CVaR}(\text{另一损失})$。

### 1.2 现 Model A（`cvar_compare.build_teavar_sla_cvar_model`）

$$
\min \;\; c_p + c_b - \omega\,\mathbb{E}[\mathrm{Del}] + \lambda_{\mathrm{sla}}\,\mathrm{CVaR}^{\mathrm{SLA}} + \cdots
$$

| 问题 | 说明 |
|------|------|
| 量纲 | 成本（钱）与 SLA CVaR（比例损失）需 $\lambda$ 换算 |
| $c_b$ | SLA 模型里 **目标中的** $c_b=\sum x|p|$ **不随场景**；$d$ 仅进 CVaR 与 $\mathbb{E}[\mathrm{Del}]$，**带宽目标费仍按 $x$** |
| $\omega$ | 防零流补丁 |

### 1.3 Model M（本文推荐）

$$
\boxed{\min \;\; \mathrm{CVaR}_\beta(L)}
$$

$L_s$：场景 $s$ 的 **总账单（货币）**。

---

## 2. 符号

| 符号 | 含义 |
|------|------|
| $c_p$ | 放置成本（与 $s$ 无关） |
| $c_b(s)$ | 场景 $s$ 带宽成本（按 **送达** $d$） |
| $\mathrm{Shortfall}_s$ | 场景 $s$ 未送达业务量（见 §3.3–§3.5） |
| $\kappa$ | 未送达 **单位业务量** 违约金（元/单位） |
| $D_{mk}=\sum_i w_{ik}y_{im}$ | 节点 $m$ 资源 $k$ 聚合需求 |
| $e_{mks}=\max(0,D_{mk}-C^N_{mks})$ | 场景 $s$ 算力缺口 |
| $\kappa^{\mathrm{sf}}_{mk}$ | 算力缺口单位罚金；**$\kappa^{\mathrm{sf}}=0$ 即不做算力罚款** |
| $\beta,\,\pi_s,\,\zeta,\,u_s$ | 同主文档 |

---

## 3. 场景总账单 $L_s$

### 3.1 放置成本

$$
c_p = \sum_{i,m} y_{im} \sum_k w_{ik}\,\pi_{mk}
$$

【说明】与场景无关；进入每个 $L_s$ 时加同一 $c_p$。

---

### 3.2 场景带宽成本 $c_b(s)$

$$
c_b(s)
= \sum_{i,m,p} d^{\mathrm{in}}_{i,m,p,s}\,|p|
+ \sum_{i,m,q} d^{\mathrm{out}}_{i,m,q,s}\,|q|
$$

【说明】  
- Model M：**按实际送达** $d$ 计费；断链 $d=0$ 则不付该段带宽费。  
- **现 SLA Model A**：目标里 $c_b=\sum x|p|$（**不随 $s$**），与 $d$ 脱钩；$d$ 只出现在 CVaR 与 $\mathbb{E}[\mathrm{Del}]$。  
- **现 Physical `duibi`**：同样 $c_b$ 基于 $x$。  
- 因此「$c_b$ 从 $x$ 改为 $d(s)$」是 **Model M 相对现 SLA 目标** 的改动，不仅是 physical 侧。

---

### 3.3 任务级未送达量

$$
\mathrm{sf}^{\mathrm{in}}_{is} = b^{\mathrm{in}}_i - R^{\mathrm{in}}_{is},\quad
\mathrm{sf}^{\mathrm{out}}_{is} = b^{\mathrm{out}}_i - R^{\mathrm{out}}_{is}
$$

$$
R^{\mathrm{in}}_{is}=\sum_{m,p} d^{\mathrm{in}}_{i,m,p,s},\quad
R^{\mathrm{out}}_{is}=\sum_{m,q} d^{\mathrm{out}}_{i,m,q,s}
$$

（实现中保证 $R\le b$，使 shortfall $\ge 0$。）

---

### 3.4 算力缺口（$k$ 维，主公式内）

$$
e_{mks} = \max\bigl(0,\, D_{mk} - C^N_{mks}\bigr)
$$

线性化：与 [`项目总结_模型AC.md`](./项目总结_模型AC.md) §8 相同（Big-M + 二元 $w^{\mathrm{exc}}_{mks}$）。

【说明】算力未满足是 **算网联合** 核心；**默认写入 $L_s$**。实验若只关心链路 SLA，设 $\kappa^{\mathrm{sf}}_{mk}=0$ 即可退化。

---

### 3.5 【重要】风险聚合：现 Model A vs Model M

#### 现 Model A：按任务逐条探测（同一 $u_s$）

`cvar_compare.py` 对每个 $(s,i)$：

$$
u_s\, b^{\mathrm{in}}_i \;\ge\; b^{\mathrm{in}}_i - R^{\mathrm{in}}_{is} - b^{\mathrm{in}}_i\,\zeta
$$

$$
u_s\, b^{\mathrm{out}}_i \;\ge\; b^{\mathrm{out}}_i - R^{\mathrm{out}}_{is} - b^{\mathrm{out}}_i\,\zeta
$$

【语义】**单个** $u_s$ 必须覆盖 **每个任务** ingress/egress 的未满足比例；等价于场景损失与 **最差任务相对损失** 挂钩（TEAVAR 同构：「任一用户不能太差」）。

#### Model M 默认：场景总 Shortfall（求和）

$$
\mathrm{Shortfall}^{\mathrm{sum}}_s
= \sum_{i\in\mathcal{I}}
\bigl(\mathrm{sf}^{\mathrm{in}}_{is}+\mathrm{sf}^{\mathrm{out}}_{is}\bigr)
$$

【语义】**总未送达业务量**；关心 **聚合违约量/总罚款**，允许「多数任务略差、无单点崩盘」与「少数任务全丢、其余完好」在 **总量相同** 时等价。

#### 数值对比（10 任务，各 $b=10$ Gbps，同场景 $s$）

| 情况 | 描述 | 现 Model A（最差任务损失比例 $\approx$） | Model M（$\mathrm{Shortfall}^{\mathrm{sum}}$） |
|------|------|------------------------------------------|-----------------------------------------------|
| **A** | 1 任务丢 10，其余全送 | $\max_i \approx 1.0$ → $u_s$ **大** | $10$ Gbps |
| **B** | 10 任务各丢 1 | $\max_i \approx 0.1$ → $u_s$ **小** | $10$ Gbps |

【说明】A 与 B 在 Model M 默认下 **Shortfall 相同**；在现 Model A 下 **CVaR 驱动完全不同**。这是 **结构性差异**，不是 $\kappa$ 能抹平的。

#### 可选：混合聚合（并存）

**（1）求和项（运营商总账单）：**

$$
\kappa_{\mathrm{sum}}\,\mathrm{Shortfall}^{\mathrm{sum}}_s
$$

**（2）最差任务项（用户公平 / TEAVAR 对齐）：**

$$
\kappa_{\max}\,
\max_{i\in\mathcal{I}}
\max\Bigl\{
\frac{\mathrm{sf}^{\mathrm{in}}_{is}}{b^{\mathrm{in}}_i},
\frac{\mathrm{sf}^{\mathrm{out}}_{is}}{b^{\mathrm{out}}_i}
\Bigr\}
$$

线性化 $\max$：引入辅助变量 $\ell_{is}$ 与标准 $u_s\ge \ell_{is}-\zeta$ 型约束，或保留 **分任务** $u_{s,i}$ 再 $\max_i$。

**（3）论文建议**：主文 Model M 用 **$\kappa_{\mathrm{sum}}$**（总违约金额）；附录用 **$\kappa_{\max}$** 或现 Model A 对照「单任务 SLA 公平性」。

---

### 3.6 场景总账单 $L_s$（完整定义）

$$
\boxed{
\begin{aligned}
L_s =\;& c_p
+ c_b(s)
+ \kappa_{\mathrm{sum}}\,\mathrm{Shortfall}^{\mathrm{sum}}_s
+ \kappa_{\max}\,\mathrm{Shortfall}^{\mathrm{max}}_s \\[4pt]
&+ \sum_{m\in\mathcal{M}}\sum_{k\in\mathcal{K}}
\kappa^{\mathrm{sf}}_{mk}\, e_{mks}
\end{aligned}
}
$$

【说明】  
- $\mathrm{Shortfall}^{\mathrm{max}}_s=0$ 且 $\kappa_{\max}=0$ → 纯求和 SLA 罚款。  
- $\kappa^{\mathrm{sf}}_{mk}=0$ → 不算算力罚款。  
- 上式为 **完整模板**；实验可逐项关闭参数 **退化**，而非把算力当「可选附录」。

---

## 4. Model M：纯 CVaR 目标

### 4.1 线性化

$$
\min \;\; \zeta + \frac{1}{1-\beta}\sum_{s\in\mathcal{S}} \pi_s\, u_s
$$

$$
u_s \;\ge\; L_s - \zeta,\quad u_s \ge 0,\quad \forall s
$$

【说明】无 $\lambda$、无 $\omega$；SLA 与算力缺口均已 **货币化** 在 $L_s$ 内。

---

### 4.2 $c_p$ 为常数

连续优化中：$\mathrm{CVaR}_\beta(c_p+X_s)=c_p+\mathrm{CVaR}_\beta(X_s)$，故 **对 $X_s$ 部分的排序与最优 $y$ 的相对权衡** 与把 $c_p$ 放在 $\mathbb{E}[\cdot]$ 中一致。

【说明 — MILP  caveat】目标加上常数 $c_p$ **不改变最优解集**（纯数学），但 **分支定界** 可能因数值容差、热启动路径不同而略有求解时间差异；报告时目标值含 $c_p$。

---

## 5. Model M-C：期望账单 + CVaR 预算（落地优先）

比 Model M **更适合部署**：**不依赖精确 $\kappa$**，用 **货币风险预算 $\Gamma_{\mathrm{money}}$**（AEGIS-A 同构）。

### 5.1 优化问题

$$
\min \;\; \mathbb{E}[L_s]
= \sum_{s\in\mathcal{S}} \pi_s\, L_s
$$

$$
\text{s.t.}\quad
\mathrm{CVaR}_\beta(L) \;\le\; \Gamma_{\mathrm{money}}
$$

即 $\zeta + \frac{1}{1-\beta}\sum_s \pi_s u_s \le \Gamma_{\mathrm{money}}$，且 $u_s\ge L_s-\zeta$。

【说明】  
- **主目标**：平时 **期望总账单** 最小。  
- **约束**：尾部场景账单不超过运营商可接受 **CVaR 预算**（可写进合同）。  
- $\kappa$ 仍进入 $L_s$ 定义，但 **可行性/保守度由 $\Gamma$ 调节**；$\kappa$ 可在合理区间内扫，不必「合同精确到元/Gbps」。

---

### 5.2 标定算法（AEGIS-A 式二分 $\Gamma$）

```
输入: data, β, κ, κ_sf, …
输出: 最小 E[L_s] 的可行解 @ 尾部预算

1. 解 Model M 或 M-C 的松弛端点：
   - 偏小 κ、偏大 Γ → 近似 min E[L]（偏省钱）
   - 偏大 κ、或 Model M 纯 CVaR → 得 CVaR* 作为参考
2. 估计 CVaR 区间 [CVaR_min, CVaR_max]
3. 二分 Γ ∈ [CVaR_min, CVaR_max]:
     解 Model M-C(Γ)
     若可行: 记录解, Γ_upper ← Γ
     若不可行: Γ_lower ← Γ
   直至 Γ_upper - Γ_lower ≤ ε
4. 输出 Γ_upper 对应解 → 「给定尾部账单预算下的最小期望账单」
```

【说明】与 [`AEGIS.md`](./AEGIS.md) 二分 **结构相同**；本文无环流判定，二分仅用于 **$\Gamma$ 可行边界**。

---

### 5.3 与现 Model A/C 对照

| | 现 Model A | Model M | Model M-C |
|--|------------|---------|-----------|
| 目标 | $C_{\mathrm{tot}}+\lambda\,\mathrm{CVaR}^{\mathrm{SLA}}$ | $\min\mathrm{CVaR}(L)$ | $\min\mathbb{E}[L_s]$ s.t. $\mathrm{CVaR}(L)\le\Gamma$ |
| SLA 聚合 | **逐任务** 比例 | 默认 **求和** Shortfall | 同 M |
| 带宽费 | 目标中 $c_b(x)$ | $c_b(s)$ 用 $d$ | 同 M |
| 调参 | $\lambda,\omega$ | $\kappa,\beta$ | $\Gamma$（+ 可选扫 $\kappa$） |
| 落地 | 需扫 $\lambda$ | 需标定 $\kappa$ | **$\Gamma$ 二分，推荐主部署** |

---

## 6. 为何可去掉 $\omega$

Model M 中：$c_b(s)$ 随送达计；$\kappa\,\mathrm{Shortfall}$ 对未送达罚钱 → 零流通常 **提高** $L_s$ 与 CVaR，无需 $\mathbb{E}[\mathrm{Del}]$ 奖励项。

【说明】若 $\kappa_{\mathrm{sum}}$ 过小，仍可能「省带宽、愿付罚款」→ **调 $\kappa$ 或改用 Model M-C 的 $\Gamma$**，而非加 $\omega$。

---

## 7. $\kappa$ 与 $\beta$ 标定（实验可操作）

### 7.1 合同叙事 vs 实验现实

真实 SLA 常为 **分级、分用户、分时段**， seldom 单一「$\kappa$ 元/Gbps」。论文可写 $\kappa$ 为 **等价违约金密度**；**实验不必等合同**。

### 7.2 实验策略（推荐）

**（1）扫 $\kappa$，而非单点设 $\kappa$**

- $\kappa_{\mathrm{sum}}\to 0$：趋近 **min 经营成本**（$L_s\approx c_p+c_b(s)$）。  
- $\kappa_{\mathrm{sum}}\to\infty$（或大值）：趋近 **TEAVAR 式强 SLA 保护**（Shortfall 主导 $L_s$）。  
- Pareto：$(\mathbb{E}[L_s], \mathrm{CVaR}(L))$ 随 $\kappa$ 移动。

**（2）从现 Model A 反推 $\kappa$ 量级**

在 Model A 的 Pareto 最优附近，用有限差分估计：

$$
\kappa_{\mathrm{ref}} \;\approx\;
\left|\frac{\Delta (c_p+c_b)}{\Delta \,\mathrm{Shortfall}^{\mathrm{sum}}}\right|
$$

或 $\Delta\,\mathrm{CVaR}^{\mathrm{SLA}}$ 与 $\Delta\,\mathrm{Shortfall}$ 的钱–量换算，作为 **Model M 初值**。

**（3）用 Model M-C + 二分 $\Gamma$ 替代「精确 $\kappa$」**

固定 $\kappa$ 在 **合理区间**（如反推值的 $0.1\times\sim 10\times$），主扫 **$\Gamma_{\mathrm{money}}$** —— 与 AEGIS-A 一致，**可操作性最强**。

### 7.3 $\beta$ 的作用

见 §8；与 $\kappa$ 分工：$\kappa$ 调「少送 1 单位罚多少钱」；$\beta$ 调「看多重的尾部场景」。

---

## 8. CVaR 与 $\beta$：不只「管尾部」（示意算例）

定义：$\mathrm{CVaR}_\beta(L)=\mathbb{E}[L\mid L>\mathrm{VaR}_\beta(L)]$。

### 8.1 四场景玩具（单任务，$L_s$ 已为货币）

| 场景 | $\pi_s$ | $L_s$ |
|------|---------|-------|
| A | 0.04 | 100（极端） |
| B | 0.32 | 50 |
| C | 0.32 | 20 |
| D | 0.32 | 10 |

**$\beta=0.95$（最坏约 5% 质量）**  
- 仅 **A**（$\pi=0.04<0.05$）落在典型尾部 → $\min\mathrm{CVaR}$ **主要压 A**。  
- B/C/D 对 CVaR 梯度弱，除非 A 已压平。

**$\beta=0.90$（最坏约 10%）**  
- 尾部约含 A 的全部 + B 的部分质量 → **同时压 A 与部分 B**。

**$\beta=0.60$**  
- 大量场景进入尾部加权 → CVaR **接近加权平均 $ \mathbb{E}[L_s]$** 的行为。

【说明】  
- 调 **$\beta$** = 在「只盯极端」与「更看整体均值」之间切换；**不必**用 $\lambda$ 或 $\omega$ 做第二套权衡。  
- 若业务要 **显式控均值**：用 **Model M-C**（$\min\mathbb{E}[L_s]$ + CVaR 约束）比纯 Model M 更清晰。

---

## 9. 微型数值例子（示意，非代码实测）

**设定**：2 task，3 node，2 scenario（$\pi_0=0.7,\pi_1=0.3$），$\beta=0.9$，$\kappa_{\mathrm{sum}}=5$ 元/单位，$\kappa^{\mathrm{sf}}=0$；hop 费 1 元/单位流量/跳；简化 $b^{\mathrm{in}}=b^{\mathrm{out}}=10$。

| | 现 Model A（$\lambda=10,\,\omega=1$） | Model M（$\kappa_{\mathrm{sum}}=5,\,\beta=0.9$） |
|--|----------------------------------------|-----------------------------------------------------|
| 报告目标 | $c_p+c_b-\omega\mathbb{E}[\mathrm{Del}]+10\cdot\mathrm{CVaR}^{\mathrm{SLA}}$ | $\mathrm{CVaR}_\beta(L)$ |
| 示意最优值 | $\approx 142$（目标标量） | $\approx 147.3$ |
| 分解 | $\mathrm{CVaR}^{\mathrm{SLA}}\approx 0.08$（比例） | $c_p=80$；$\mathbb{E}[c_b(s)]\approx 42$；$\mathbb{E}[\kappa\,\mathrm{Shortfall}]\approx 25.3$ |
| $c_b$ 语义 | 目标按 **$x$** 计 $\approx 48$（两场景相同） | 场景 1 断链：$c_b(1)\approx 24$（只付送达）；场景 0：$\approx 48$ |
| SLA 语义 | **最差 task** 未满足比例进 CVaR | **总 Shortfall**×$\kappa$ 进 $L_s$ |

**差异解读（示意）**  
1. Model M 在断链场景 **少付带宽**（$c_b(s)$ 用 $d$），但 **Shortfall 罚款** 抬高 $L_s(1)$。  
2. Model A 的 $\mathrm{CVaR}^{\mathrm{SLA}}$ 无量纲，与 $c_p+c_b$ 靠 $\lambda=10$ 拼接；Model M **一项 CVaR(元)**。  
3. 若 task1 全丢、task2 全送 vs 各丢一半（总 Shortfall 相同），Model A 的 CVaR **不同**，Model M **相同** — 见 §3.5。

> 实现 Model M 后，应用 **同一玩具实例** 替换上表为 **Gurobi 实测值**。

---

## 10. 代码改动要点（`cvar_compare.py` 扩展）

### 10.1 现 SLA 目标（摘要）

```python
cost_b = sum(xin[i,m,p] * len(path) for ...)  # 目标中不随 s
obj = cost_p + cost_b + lambda_cvar * loss_cvar - omega * exp_deliver
# loss_cvar: 对每个 (s,i) 两条 u_s 与 (b-R-b*zeta) 约束
```

### 10.2 Model M 伪代码

```python
cost_p = gp.quicksum(y[i,m] * ... for ...)  # 与现同

for s in data.S:
    cost_b_s = (
        gp.quicksum(del_in[i,m,p,s] * len(path) for ...)
        + gp.quicksum(del_out[i,m,q,s] * len(path) for ...)
    )
    shortfall_sum_s = gp.quicksum(
        (b_in[i] - R_in[i,s]) + (b_out[i] - R_out[i,s])
        for i in data.I
    )  # R_in[i,s], R_out[i,s] 为任务 i 在 s 的标量聚合
    compute_penalty_s = gp.quicksum(
        kappa_sf[m,k] * e_ex[m,k,s] for m,k
    )
    L_s[s] = cost_p + cost_b_s + kappa_sum * shortfall_sum_s + compute_penalty_s
    m.addConstr(u_s[s] >= L_s[s] - zeta)

m.setObjective(
    zeta + (1/(1-beta)) * gp.quicksum(prob[s] * u_s[s] for s in data.S),
    GRB.MINIMIZE,
)
```

【说明】  
- **删除**：`lambda_cvar`、`omega_deliver`、逐 $(s,i)$ 的 SLA 比例行（若采用纯 $\mathrm{Shortfall}^{\mathrm{sum}}$）。  
- **保留**：$y,x,d$ 与 path_up / Big-M 耦合。  
- **可选**：加 $\kappa_{\max}\cdot \mathrm{Shortfall}^{\mathrm{max}}_s$ 与 TEAVAR 对齐。

### 10.3 Model M-C

在 10.2 基础上：目标改为 `gp.quicksum(prob[s] * L_s[s] for s)`，加 `CVaR_expr <= Gamma_money`。

---

## 11. 论文写作立场

| 章节 | 内容 |
|------|------|
| **Method（主）** | Model M / **Model M-C**（推荐 **M-C 落地** + $\Gamma$ 二分） |
| **Method / Implementation** | Model A/C 作 TEAVAR 对齐、$\lambda$ Pareto、与仓库复现 |
| **Discussion** | §3.5 聚合语义（max vs sum）；$\kappa$ 扫 vs $\Gamma$ 二分 |

摘要示例：

> We define a scenario-wise monetary bill $L_s$ and minimize its CVaR (Model M), or minimize expected bill subject to a CVaR budget (Model M-C). This unifies placement, delivered bandwidth, SLA shortfall, and compute deficit penalties in one financial loss, consistent with Rockafellar–Uryasev. Task-level TEAVAR-style probing (Model A) is retained for comparison.

---

## 12. 公式清单

| 公式 | 节 |
|------|-----|
| $c_b(s)$ 用 $d$ | §3.2 |
| $\mathrm{Shortfall}^{\mathrm{sum}}_s$，$\mathrm{Shortfall}^{\mathrm{max}}_s$ | §3.5 |
| 完整 $L_s$（含 $\kappa^{\mathrm{sf}} e_{mks}$） | §3.6 |
| $\min\mathrm{CVaR}_\beta(L)$ | §4 |
| Model M-C + 二分 | §5 |
| $\kappa$ 标定策略 | §7 |
| $\beta$ 四场景例 | §8 |
| 微型数值对比 | §9 |

---

## 13. 相关文档

| 文档 | 关系 |
|------|------|
| [`项目总结_模型AC.md`](./项目总结_模型AC.md) | 已实现 Model A/C |
| [`建模公式说明.md`](./建模公式说明.md) | 函数级公式 |
| [`AEGIS.md`](./AEGIS.md) | M-C 与 AEGIS-A |
