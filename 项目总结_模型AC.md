# 算力–网络联合优化：完整建模公式（Model A / Model C）

> **阅读说明**：公式用 `$…$` / `$$…$$` 书写；请用 **Markdown 预览**（`Ctrl+Shift+V`）查看。  
> **格式约定**：每个公式后紧跟 **【说明】**，解释符号含义与建模意图。  
> **路由语义**：正文标准形式为 **每任务** $s_i\to m\to t_i$（源–算力–宿）；当前代码为 **Hub 径向特例** $h\to m\to h$，见 §2.3。论文章节体例见 [`建模章节_算力网络联合优化.md`](./建模章节_算力网络联合优化.md)。  
> 代码实现见 [`cvar_compare.py`](./cvar_compare.py)、[`teavar_framework_models.py`](./teavar_framework_models.py)、[`duibi.py`](./duibi.py)。

---

## 0. 关于上一版文档

上一版 [`项目总结_模型AC.md`](./项目总结_模型AC.md) **没有**做到「公式写全、每条都有说明」：送达耦合只写了文字、缺 Big-M；$\mathrm{CVaR}^{\mathrm{sf}}$、虚拟接入、Physical 利用率 CVaR、变量域等均未展开。**本文档为补全版**，与仓库 SLA 主线（Model A/C）及 Physical 对照（duibi）对齐。

---

## 1. 问题概述

每个任务 $i\in\mathcal{I}$ 给定**源节点** $s_i$ 与**宿节点** $t_i$，并选择**一个**算力节点 $m$ 执行。广域通信为 **两阶段有向路由**（流量可分割、任务不可分割）：

$$
\boxed{
s_i \;\xrightarrow{\text{ingress，可多路径}}\; m \;\xrightarrow{\text{egress，可多路径}}\; t_i
}
$$

【说明】例如：输入从「北京」$s_i$ 经多路径送到「西安」$m$ 处理，结果从西安经多路径送到「上海」$t_i$。**不是**从同一 Hub 发出再送回同一 Hub。Hub 径向 $h\to m\to h$ 仅为 §2.3 中的实现特例（$s_i=t_i=h$）。

在离散故障场景 $s\in\mathcal{S}$（概率 $\pi_s$）下，联合决定 **放哪里（$m$）、怎么走、成本与 SLA 尾部风险如何权衡**。

---

## 2. 集合、参数与流锚点

### 2.1 集合

| 符号 | 【说明】 |
|------|----------|
| $\mathcal{I}$ | 任务集合 |
| $\mathcal{M}$ | 算力/交换节点 |
| $\mathcal{K}$ | 资源类型，如 $\{\mathrm{CPU},\mathrm{GPU},\mathrm{HBM}\}$ |
| $\mathcal{S}$ | 离散不确定性场景 |
| $\mathcal{E}$ | 有向链路集合，元素 $e=(u,v)$ |
| $\mathcal{P}_{uv}$ | 预计算的、从 $u$ 到 $v$ 的至多 $K$ 条**最短简单路径**（边序列） |

### 2.2 参数

| 符号 | 【说明】 |
|------|----------|
| $s_i,\,t_i$ | 任务 $i$ 的源 / 宿节点（ingress 从 $s_i$ 发出，egress 到 $t_i$ 结束） |
| $b^{\mathrm{in}}_i,\,b^{\mathrm{out}}_i$ | 任务 $i$ 的 ingress（$s_i\to m$）/ egress（$m\to t_i$）业务量 |
| $w_{ik}$ | 任务 $i$ 对资源 $k$ 的需求量 |
| $\pi_{mk}$ | 节点 $m$ 上资源 $k$ 的单位价格 |
| $B_e$ | 链路 $e$ 的名义容量 |
| $\sigma_{es}\in[0,1]$ | 场景 $s$ 下链路 $e$ 的可用率；$\sigma_{es}=0$ 表示该边在场景 $s$ 中断 |
| $C^{\mathrm{norm}}_{mk}$ | 名义（设计态，通常 $s=0$）下节点 $m$ 资源 $k$ 的容量上界 |
| $C^N_{mks}$ | 场景 $s$ 下节点 $m$ 资源 $k$ 的可用容量（可小于 $C^{\mathrm{norm}}_{mk}$，表示算力降额） |
| $\beta_{\mathrm{loss}}\in(0,1)$ | SLA CVaR 的置信水平（如 $0.95$） |
| $\beta_{\mathrm{sf}}$ | 算力未满足 CVaR 的置信水平（与 $\beta_{\mathrm{loss}}$ 可同取 `beta_N`） |
| $D_{\mathrm{ref}}$ | 算力缺口归一化常数（与 $M_{\mathrm{ex}}$ 同量级） |
| $\omega\ge 0$ | 期望送达奖励系数 |
| $M$ | 足够大的常数（Big-M，用于线性化逻辑约束） |
| $h$ | 物理 Hub 节点（**仅 Hub 径向特例**下 $s_i=t_i=h$；应力实验用） |

### 2.3 流锚点与路由语义

#### 标准形式（建模与论文正文）

对每个任务 $i$，ingress / egress 路径集**依赖该任务的 OD**：

$$
\mathcal{P}^{\mathrm{in}}_{i,m} = \mathcal{P}_{s_i,m}, \qquad
\mathcal{P}^{\mathrm{out}}_{i,m} = \mathcal{P}_{m,t_i}
$$

【说明】$y_{im}=1$ 时，仅在 $s_i\to m$ 与 $m\to t_i$ 的候选路径上分配 $x^{\mathrm{in/out}}$ 与场景送达 $d$。

#### 特例（当前代码 `teavar_flow_anchors`）

函数 `teavar_flow_anchors(data)` 返回**全局**一对端点，用于简化实现：

| 模式 | 条件 | 等价于 |
|------|------|--------|
| **Hub 径向（当前默认）** | 对所有 $i$：$s_i=t_i=h$ | $\mathcal{P}_{h,m}$、$\mathcal{P}_{m,h}$ |
| **UMCF** | 对所有 $i$：$s_i=V_s,\,t_i=V_t$ | $\mathcal{P}_{V_s,m}$、$\mathcal{P}_{m,V_t}$ |

【说明】路径索引 $p,q$ 在 Hub/UMCF 模式下相对全局锚点；**一般 OD 实现后**应改为 per-task 的 $s_i,t_i$。`b4_joint_data` 从 demand 读取的 $(hub,dst)$ 目前主要标定 $b^{\mathrm{in/out}}$，**尚未**将 $dst$ 设为 $t_i$。

---

## 3. 决策变量与变量域

| 变量 | 域 | 【说明】 |
|------|-----|----------|
| $y_{im}$ | $\{0,1\}$ | 任务 $i$ 是否部署在节点 $m$ |
| $x^{\mathrm{in}}_{i,m,p}$ | $\mathbb{R}_+$ | 任务 $i$ 在节点 $m$ 上、ingress 路径 $p$ 的**计划流量**（全场景共用） |
| $x^{\mathrm{out}}_{i,m,q}$ | $\mathbb{R}_+$ | egress 路径 $q$ 的计划流量 |
| $d^{\mathrm{in}}_{i,m,p,s}$ | $\mathbb{R}_+$ | 场景 $s$ 下 ingress 路径 $p$ 的**实际送达量** |
| $d^{\mathrm{out}}_{i,m,q,s}$ | $\mathbb{R}_+$ | 场景 $s$ 下 egress 实际送达量 |
| $\zeta$ | $\mathbb{R}$ | SLA CVaR 的 VaR 阈值（Rockafellar–Uryasev 辅助变量） |
| $u_s$ | $\mathbb{R}_+$ | 场景 $s$ 上 SLA 损失超过 $\zeta$ 的超额量 |
| $\zeta_{\mathrm{sf}},\,\phi_s$ | $\mathbb{R}$ / $\mathbb{R}_+$ | 算力未满足 CVaR 辅助变量（**完整模型必选**） |
| $D_{mk},\,e_{mks},\,w^{\mathrm{exc}}_{mks}$ | 连续 / 二元 | 节点需求、场景超额、$\max(0,\cdot)$ 线性化（**完整模型必选**） |

【说明】Model A 与 Model C 使用**同一套变量与约束**（含 §7 SLA 与 §8 算力 CVaR 线性化）；差别仅在双 CVaR 进入目标（$\lambda$ 加权）还是约束（$\Gamma$ 预算）。

---

## 4. 成本公式

### 4.1 放置成本

$$
c_p \;=\; \sum_{i\in\mathcal{I}} \sum_{m\in\mathcal{M}} y_{im} \sum_{k\in\mathcal{K}} w_{ik}\,\pi_{mk}
$$

【说明】任务 $i$ 一旦放在 $m$（$y_{im}=1$），按 **$k$ 维异构资源** 的「需求量 × 单价」求和，计入运营商账单。体现 **算力异构与节点价差**。

---

### 4.2 带宽成本（流量 × 链路单价）

对每条物理链路 $e\in\mathcal{E}$ 给定带宽单价 $\pi_e$（元/单位业务量，代码 `data.link_price[e]`，由 `duibi_metrics.ensure_link_prices` 生成；B4 默认可取 $\pi_e \propto 1/B_e$）。路径 $p$ 的**路径价**为

$$
\tau_p \;=\; \sum_{e\in p} \pi_e .
$$

计划流量带宽费：

$$
c_b \;=\; \sum_{i,m,p} x^{\mathrm{in}}_{i,m,p}\,\tau_p \;+\; \sum_{i,m,q} x^{\mathrm{out}}_{i,m,q}\,\tau_q
\;=\; \sum_{i,m,p} x^{\mathrm{in}}_{i,m,p} \sum_{e\in p}\pi_e \;+\; \cdots
$$

【说明】即 **流量 ×（路径上各链路单价之和）**，不再用 hop 数 $|p|$ 代理。若所有 $\pi_e\equiv 1$ 且每条边只计一次，则 $\tau_p=|p|$，与旧版跳数计费数值一致。

---

### 4.3 期望送达量 $\mathbb{E}[\mathrm{Del}]$

$$
\mathbb{E}[\mathrm{Del}]
\;=\;
\sum_{s\in\mathcal{S}} \pi_s
\left(
\sum_{i\in\mathcal{I}} \sum_{m\in\mathcal{M}} \sum_{p} d^{\mathrm{in}}_{i,m,p,s}
\;+\;
\sum_{i\in\mathcal{I}} \sum_{m\in\mathcal{M}} \sum_{q} d^{\mathrm{out}}_{i,m,q,s}
\right)
$$

【说明】  
- 对 **每个场景 $s$** 按概率 $\pi_s$ 加权，求 **ingress 与 egress 实际送达量** $d$ 之和（不是计划流量 $x$）。  
- $d$ 已含路径断链：断则 $d=0$，因此 $\mathbb{E}[\mathrm{Del}]$ 反映 **期望意义下真正送到的业务量**。  
- **不含** DAG 中间段（当前原子 task 模型无中间弧）；Physical 对照模型 `duibi` **不含** 此项。

---

### 4.4 期望送达奖励项 $-\omega\,\mathbb{E}[\mathrm{Del}]$

代码中参数名：`omega_deliver`（默认 **$\omega=1.0$**，CLI：`--omega`）。

$$
\boxed{
\text{目标中的奖励项：}\quad
-\,\omega\,\mathbb{E}[\mathrm{Del}]
}
$$

【说明 — 为何需要这一项】  
1. **防止「零流/极低流」退化解**：若目标只有 $c_p+c_b+\lambda\,\mathrm{CVaR}$，在 $\lambda$ 较小或 CVaR 对放置不敏感时，求解器可能把 $x^{\mathrm{in/out}}$ 压到 0 以省带宽成本，而 CVaR 仍可为 0（无流量则无损失）。**减去** $\omega\,\mathbb{E}[\mathrm{Del}]$ 等价于 **奖励送达**，驱使模型在成本允许时 **多送流量**。  
2. **与 $\mathrm{CVaR}^{\mathrm{SLA}}$ 分工不同**：  
   - $\mathrm{CVaR}^{\mathrm{SLA}}$：惩罚 **尾部场景** 的未满足（最坏 $(1-\beta)$ 质量）；  
   - $-\omega\,\mathbb{E}[\mathrm{Del}]$：提高 **全场景期望** 送达体积（一阶矩/平均水平）。  
   二者 **不重复**：可理解为「平均要多送」+「尾部不能太差」。  
3. **符号**：目标里是 **减号** $\min(\cdots - \omega\,\mathbb{E}[\mathrm{Del}])$，故 $\omega>0$ 时 **增大** $\mathbb{E}[\mathrm{Del}]$ 会 **降低** 目标值（被奖励）。  
4. **退化**：$\omega=0$ 时该项关闭，目标变为 $c_p+c_b+\lambda\,\mathrm{CVaR}+\cdots$（纯成本 + 风险）。

【说明 — 与代码一致】`cvar_compare.build_teavar_sla_cvar_model` 中：

$$
\min\;\; c_p + c_b + \lambda_{\mathrm{sla}}\,\mathrm{CVaR}^{\mathrm{SLA}} + \cdots \;-\; \omega\,\mathbb{E}[\mathrm{Del}]
$$

即 **奖励项与 $c_p,c_b$ 同级** 写入目标，**不是** 约束。

---

### 4.5 运营商总成本 $C_{\mathrm{tot}}$

$$
\boxed{
C_{\mathrm{tot}} \;=\; c_p + c_b - \omega\,\mathbb{E}[\mathrm{Del}]
}
$$

【说明】  
- **SLA 主线 Model A/C** 的经济部分 **恒含** $-\omega\,\mathbb{E}[\mathrm{Del}]$（除非设 $\omega=0$）。  
- Model A：在 $C_{\mathrm{tot}}$ 之上 **再加** $\lambda_{\mathrm{sla}}\mathrm{CVaR}^{\mathrm{SLA}}+\cdots$。  
- Model C：**最小化** $C_{\mathrm{tot}}$，CVaR 进约束。  
- **Physical 对照**（`duibi.build_single_layer_model`）：目标为 $c_p+c_b+\lambda(\mathrm{CVaR}^N+\mathrm{CVaR}^L)$，**无** $\omega$ 项。

---

## 5. 物理与业务约束

### 5.1 任务不可分割（单点放置）

$$
\sum_{m\in\mathcal{M}} y_{im} = 1, \qquad \forall i\in\mathcal{I}
$$

【说明】每个任务 **恰好选一个** 执行节点。当前模型 **不含** microservice DAG 拆分（未来扩展）。

---

### 5.2 Ingress 流量激活与守恒

$$
\sum_{p\in\mathcal{P}_{s_i,m}} x^{\mathrm{in}}_{i,m,p} \;\le\; y_{im}\, b^{\mathrm{in}}_i, \qquad \forall i\in\mathcal{I},\, m\in\mathcal{M}
$$

【说明】仅当 $y_{im}=1$ 时，节点 $m$ 最多从源 $s_i$ 方向接收 $b^{\mathrm{in}}_i$ 的 ingress 流量，并可拆到 $\mathcal{P}_{s_i,m}$ 上多条路径；$y_{im}=0$ 时右侧为 0。Hub 特例下 $s_i=h$，即 $\mathcal{P}_{h,m}$。实现为 **$\le$**（允许不拉满管道）。

---

### 5.3 Egress 流量激活与守恒

$$
\sum_{q\in\mathcal{P}_{m,t_i}} x^{\mathrm{out}}_{i,m,q} \;\le\; y_{im}\, b^{\mathrm{out}}_i, \qquad \forall i\in\mathcal{I},\, m\in\mathcal{M}
$$

【说明】与 5.2 对称：只有被选中的 $m$ 才向宿 $t_i$ 发送 egress，并可 multipath 分流。Hub 特例下 $t_i=h$，即 $\mathcal{P}_{m,h}$。

---

### 5.4 链路负载定义

$$
\mathrm{flow}_e \;=\; \sum_{i,m,p:\, e\in p} x^{\mathrm{in}}_{i,m,p} \;+\; \sum_{i,m,q:\, e\in q} x^{\mathrm{out}}_{i,m,q}, \qquad \forall e\in\mathcal{E}
$$

【说明】两阶段计划流量在每条有向链路上的叠加。用于容量与（Physical 模型中）链路利用率风险。

---

### 5.5 名义链路容量

$$
\mathrm{flow}_e \;\le\; B_e, \qquad \forall e\in\mathcal{E}
$$

【说明】设计态下链路负载不超过名义容量 $B_e$（与场景 $s=0$ 全通一致）。

---

### 5.6 $k$ 维算力容量（名义）

$$
\sum_{i\in\mathcal{I}} w_{ik}\, y_{im} \;\le\; C^{\mathrm{norm}}_{mk}, \qquad \forall m\in\mathcal{M},\, k\in\mathcal{K}
$$

【说明】每个节点、每种资源维度独立约束。任务需求向量 $\mathbf{w}_i=(w_{ik})$ 与节点容量向量 $\mathbf{C}_m^{\mathrm{norm}}$ **逐维** 比较。

---

## 6. 路径可达性与场景送达（SLA 核心）

### 6.1 路径在场景 $s$ 下是否可用

定义指示（代码 `path_up`）：

$$
\mathrm{up}_{m,p,s} = 1 \quad \Longleftrightarrow \quad \forall e\in p:\; \sigma_{es} > 0
$$

【说明】路径上 **任一边断** 则该路径在场景 $s$ 不可用。无动态 reroute：不可用路径上的计划流量 **不转移** 到其他路径。

---

### 6.2 送达量与计划流量的耦合（Big-M 线性化）

当 $\mathrm{up}_{m,p,s}=1$ 时，对 ingress：

$$
d^{\mathrm{in}}_{i,m,p,s} \;\le\; x^{\mathrm{in}}_{i,m,p}
$$

$$
d^{\mathrm{in}}_{i,m,p,s} \;\le\; M\, y_{im}
$$

$$
d^{\mathrm{in}}_{i,m,p,s} \;\ge\; x^{\mathrm{in}}_{i,m,p} - M\,(1-y_{im})
$$

当 $\mathrm{up}_{m,p,s}=0$ 时：

$$
d^{\mathrm{in}}_{i,m,p,s} = 0
$$

【说明】  
- 路径通且 $y_{im}=1$：$d^{\mathrm{in}}_{i,m,p,s}=x^{\mathrm{in}}_{i,m,p}$（计划多少、场景 $s$ 下最多送多少）。  
- $y_{im}=0$：送达为 0。  
- 路径断：送达为 0，该份额计入后续 SLA 损失。  

Egress 对 $d^{\mathrm{out}}_{i,m,q,s}$ 有 **完全对称** 的一组约束。

---

### 6.3 场景下聚合送达

$$
R^{\mathrm{in}}_{is} = \sum_{m\in\mathcal{M}} \sum_{p} d^{\mathrm{in}}_{i,m,p,s}, \qquad
R^{\mathrm{out}}_{is} = \sum_{m\in\mathcal{M}} \sum_{q} d^{\mathrm{out}}_{i,m,q,s}
$$

【说明】任务 $i$ 在场景 $s$ 下 ingress/egress **各路径送达之和**。是 SLA 损失计算的输入。

---

## 7. SLA 需求未满足与 $\mathrm{CVaR}^{\mathrm{SLA}}$

### 7.1 相对未满足损失（与 TEAVAR 的 $1-R/d$ 同构）

对每个场景 $s$、任务 $i$：

$$
u_s\, b^{\mathrm{in}}_i \;\ge\; b^{\mathrm{in}}_i - R^{\mathrm{in}}_{is} - b^{\mathrm{in}}_i\,\zeta
$$

$$
u_s\, b^{\mathrm{out}}_i \;\ge\; b^{\mathrm{out}}_i - R^{\mathrm{out}}_{is} - b^{\mathrm{out}}_i\,\zeta
$$

$$
u_s \;\ge\; 0
$$

【说明】  
- $b-R$：该场景下未送达的业务量。  
- 除以 $b^{\mathrm{in}}_i$ 即得 **未满足比例** $1-R^{\mathrm{in}}_{is}/b^{\mathrm{in}}_i$；上式为与其等价的线性形式。  
- ingress 与 egress **分别** 约束，同一 $u_s$ 取两者中更紧的损失（最坏一侧）。  
- $\zeta$：VaR 阈值；$u_s$：场景 $s$ 损失超出 $\zeta$ 的部分。

---

### 7.2 SLA CVaR（Rockafellar–Uryasev）

$$
\mathrm{CVaR}^{\mathrm{SLA}} \;=\; \zeta \;+\; \frac{1}{1-\beta_{\mathrm{loss}}} \sum_{s\in\mathcal{S}} \pi_s\, u_s
$$

【说明】  
- $\mathrm{CVaR}^{\mathrm{SLA}}$：**最坏 $(1-\beta_{\mathrm{loss}})$ 概率质量下** 的平均未满足程度。  
- $\beta_{\mathrm{loss}}=0.95$ 表示关注尾部约 5% 场景质量。  
- 这是 **主风险度量**，对齐 TEAVAR / 用户 SLA 视角。

---

## 8. 算力未满足 $\mathrm{CVaR}^{\mathrm{sf}}$（**算网联合必选**）

### 8.0 为何不是「可选项」

算力–网络联合优化的定义要求：**放置**（$y_{im}$、$w_{ik}$）与 **路由/送达**（$x,d$）在同一随机场景下共同评估。仅含 §7 的 $\mathrm{CVaR}^{\mathrm{SLA}}$ 时，优化器可把任务放到 **网络可达但场景算力不足** 的节点：此时 $R^{\mathrm{in/out}}_{is}$ 可接近 $b$，SLA 损失很小，但任务仍无法完成。

因此 **完整问题** 必须包含本节算力缺口块，与 §7 **并列** 构成双 CVaR：

$$
\underbrace{\mathrm{CVaR}^{\mathrm{SLA}}}_{\text{网络：未送达}} 
\;+\;
\underbrace{\mathrm{CVaR}^{\mathrm{sf}}}_{\text{算力：超额需求}}
$$

【说明】  
- Model A/C 的目标或约束中 **应写** $\lambda_{\mathrm{sf}}\mathrm{CVaR}^{\mathrm{sf}}$ 或 $\mathrm{CVaR}^{\mathrm{sf}}\le\Gamma_{\mathrm{sf}}$。  
- 代码中 `lambda_compute_sf_cvar=0` 时不实例化该块，仅用于 **「仅链路 SLA」消融**；论文 Method 仍应以本节为完整模型，Experiments 再报告 $\lambda_{\mathrm{sf}}=0$ 对照。  
- 与 Physical 模型的 $\mathrm{CVaR}^{N}$（利用率尾部）不同：§8 基于 **超额量** $e_{mks}$，与 SLA 主线一致。

### 8.1 节点资源总需求

$$
D_{mk} = \sum_{i\in\mathcal{I}} w_{ik}\, y_{im}, \qquad \forall m,k
$$

【说明】节点 $m$ 上资源 $k$ 的 **聚合需求**（所有放置在该节点的任务之和）。

---

### 8.2 场景超额（$\max(0, D-C)$ 的线性化）

$$
e_{mks} \;\ge\; D_{mk} - C^N_{mks}
$$

$$
e_{mks} \;\ge\; 0
$$

$$
e_{mks} \;\le\; (D_{mk} - C^N_{mks}) + M_{\mathrm{ex}}\,(1 - w^{\mathrm{exc}}_{mks})
$$

$$
e_{mks} \;\le\; M_{\mathrm{ex}}\, w^{\mathrm{exc}}_{mks}
$$

其中 $w^{\mathrm{exc}}_{mks}\in\{0,1\}$，$M_{\mathrm{ex}}$ 为足够大常数。

【说明】$e_{mks}=\max(0,\,D_{mk}-C^N_{mks})$：场景 $s$ 下算力 **缺口**（绝对量）。语义：**包到了但算力不够**——与 §7「包没到」互补。

【说明 — $M_{\mathrm{ex}}$】取 $\max\bigl(\max_{m,k}\sum_i w_{ik},\, \max_{m,k,s} C^N_{mks}\bigr)+1$ 量级，保证 $D_{mk}-C^N_{mks}$ 正端与 $e_{mks}$ 上界均可被 Big-M 覆盖。

---

### 8.3 场景标量损失与 CVaR

$$
L^{\mathrm{sf}}_s = \max_{m\in\mathcal{M},\,k\in\mathcal{K}} \frac{e_{mks}}{D_{\mathrm{ref}}}
$$

线性化（对每个 $m,k$）：

$$
\phi_s \;\ge\; \frac{e_{mks}}{D_{\mathrm{ref}}} - \zeta_{\mathrm{sf}}
$$

$$
\mathrm{CVaR}^{\mathrm{sf}} \;=\; \zeta_{\mathrm{sf}} \;+\; \frac{1}{1-\beta_{\mathrm{sf}}} \sum_{s\in\mathcal{S}} \pi_s\, \phi_s
$$

【说明】  
- $L^{\mathrm{sf}}_s$：场景 $s$ 下 **最严重** 的（归一化）算力缺口，$\max_{m,k}$ 聚合。  
- $D_{\mathrm{ref}}$：常数上界（实现中与 $M_{\mathrm{ex}}$ 同源），使 $L^{\mathrm{sf}}_s$ 与 SLA 侧损失尺度可比，便于设 $\lambda_{\mathrm{sla}}$ 与 $\lambda_{\mathrm{sf}}$。  
- $\phi_s$ 对 **每个** $(m,k)$ 约束，故 $\phi_s\ge L^{\mathrm{sf}}_s-\zeta_{\mathrm{sf}}$。  
- 刻画 **算网联合** 核心：**送达 ≠ 任务成功**。

### 8.4 与 Model A / C 的衔接

| 模型 | 算力风险如何进入 |
|------|------------------|
| **Model A** | $+\,\lambda_{\mathrm{sf}}\,\mathrm{CVaR}^{\mathrm{sf}}$（与 $\lambda_{\mathrm{sla}}$ 并列，权重宜分开标定） |
| **Model C** | $\mathrm{CVaR}^{\mathrm{sf}}\le\Gamma_{\mathrm{sf}}$（与 $\Gamma_{\mathrm{sla}}$ 并列） |

【说明】$\lambda_{\mathrm{sla}}$ 与 $\lambda_{\mathrm{sf}}$ **不要求** 之和为 1；二者惩罚不同物理机制，应分别扫 Pareto 或分别二分 $\Gamma$。

---

## 9. 可选：虚拟源/汇接入瓶颈

（`virtual_source=True` 且未开 UMCF 时；函数 `add_teavar_virtual_bottleneck_constraints`。）

$$
R^{\mathrm{in}}_{is} \;\le\; \sum_{m\in\mathcal{M}} b^{\mathrm{in}}_i\, y_{im}\, \sigma^{\mathrm{vs}}_{m,s}
$$

$$
R^{\mathrm{out}}_{is} \;\le\; \sum_{m\in\mathcal{M}} b^{\mathrm{out}}_i\, y_{im}\, \sigma^{\mathrm{vt}}_{m,s}
$$

【说明】  
- $\sigma^{\mathrm{vs}}_{m,s},\sigma^{\mathrm{vt}}_{m,s}\in(0,1]$：逻辑 **接入/离开** 物理网的串联可靠性上界。  
- 当任务放在 hub 且 hub↔hub 为空路径时，仍可通过 $\sigma^{\mathrm{vs}}<1$ 保留接入风险，避免 SLA CVaR 对 $\lambda$ **无梯度**（退化）。

---

## 10. 可选：正常态送达下界（AEGIS 式 $\gamma$ 约束）

对名义场景 $s=0$（若启用 `delta_min_normal`）：

$$
\sum_{m,p} d^{\mathrm{in}}_{i,m,p,0} \;\ge\; \delta_{\min}\, b^{\mathrm{in}}_i \sum_m y_{im}, \qquad \forall i
$$

$$
\sum_{m,q} d^{\mathrm{out}}_{i,m,q,0} \;\ge\; \delta_{\min}\, b^{\mathrm{out}}_i \sum_m y_{im}, \qquad \forall i
$$

【说明】  
- $\delta_{\min}\in[0,1]$：无故障时至少保证的需求满足比例（类似 AEGIS 的 $\gamma$）。  
- 与 CVaR **正交**：CVaR 管尾部，$\delta_{\min}$ 管 **平时底线**。

---

## 11. Model A — 完整优化问题（SLA 主线）

**紧凑写法**（$C_{\mathrm{tot}}$ 已含 $-\omega\,\mathbb{E}[\mathrm{Del}]$，见 §4.5）：

$$
\min \quad C_{\mathrm{tot}} \;+\; \lambda_{\mathrm{sla}}\,\mathrm{CVaR}^{\mathrm{SLA}} \;+\; \lambda_{\mathrm{sf}}\,\mathrm{CVaR}^{\mathrm{sf}}
$$

**展开写法**（与代码逐项对应）：

$$
\boxed{
\min \quad
c_p + c_b
\;-\; \omega\,\mathbb{E}[\mathrm{Del}]
\;+\; \lambda_{\mathrm{sla}}\,\mathrm{CVaR}^{\mathrm{SLA}}
\;+\; \lambda_{\mathrm{sf}}\,\mathrm{CVaR}^{\mathrm{sf}}
}
$$

**约束：** 第 5 节（5.1–5.6）+ 第 6 节（6.2–6.3）+ 第 7 节（7.1–7.2）+ **第 8 节（算力 CVaR，完整模型必选）** + 按需第 9–10 节。

【说明】  
- **单层 MILP**，Rockafellar–Uryasev 线性化 **精确**（有限场景下）。  
- **$- \omega\,\mathbb{E}[\mathrm{Del}]$** 不是 CVaR 的一部分，而是 **期望送达奖励**（§4.4）；调大 $\omega$ 更倾向提高送达、减轻零流退化。  
- $\lambda_{\mathrm{sla}}$、$\lambda_{\mathrm{sf}}$：**双 CVaR 权重**，宜分开标定；$\lambda_{\mathrm{sf}}=0$ 仅为代码/实验消融，**不**改变 §8 在完整模型中的地位。  
- $\lambda$ **不要求** 之和为 1（惩罚标量化，非百分比权重）。  
- **用途**：扫 $(\lambda_{\mathrm{sla}},\lambda_{\mathrm{sf}})$ 或固定其一扫另一描绘 cost–risk 前沿，标定 Model C 的 $(\Gamma_{\mathrm{sla}},\Gamma_{\mathrm{sf}})$。

---

## 12. Model C — 完整优化问题（SLA 主线）

**紧凑写法**：

$$
\min \quad C_{\mathrm{tot}}
$$

**展开写法**（$C_{\mathrm{tot}}$ 同样含 $-\omega\,\mathbb{E}[\mathrm{Del}]$）：

$$
\boxed{
\min \quad c_p + c_b - \omega\,\mathbb{E}[\mathrm{Del}}
}
$$

$$
\text{s.t.} \quad \mathrm{CVaR}^{\mathrm{SLA}} \;\le\; \Gamma_{\mathrm{sla}}
$$

$$
\mathrm{CVaR}^{\mathrm{sf}} \;\le\; \Gamma_{\mathrm{sf}}
$$

**以及** 第 5–7 节 + **第 8 节** + 按需第 9–10 节**全部约束**。

【说明】  
- 与 Model A **同一可行域**；$\mathrm{CVaR}$ 与 $\mathbb{E}[\mathrm{Del}]$ 定义完全相同。  
- Model C **不** 把 CVaR 放进目标，但 **仍保留** $-\omega\,\mathbb{E}[\mathrm{Del}]$ 在 $C_{\mathrm{tot}}$ 里——最小化成本时仍 **奖励期望送达**（与 `build_teavar_model_c` 一致）。  
- $\Gamma_{\mathrm{sla}}$：**可解释的风险合同/预算**（对齐 AEGIS-A：CVaR 约束 + min 经济目标）。  
- 典型标定：Model A 得 $\mathrm{CVaR}^{\mathrm{SLA},*}$ 后，设 $\Gamma_{\mathrm{sla}}\approx(1+\varepsilon)\,\mathrm{CVaR}^{\mathrm{SLA},*}$。  
- $\Gamma$ 过紧 → 不可行，可探测最小可行风险边界。

---

## 13. Model A 与 Model C 的关系

| 项目 | Model A | Model C |
|------|---------|---------|
| 目标 | $\min c_p+c_b-\omega\mathbb{E}[\mathrm{Del}]+\lambda_{\mathrm{sla}}\mathrm{CVaR}^{\mathrm{SLA}}+\cdots$ | $\min c_p+c_b-\omega\mathbb{E}[\mathrm{Del}]$ |
| 风险参数 | $\lambda_{\mathrm{sla}}$（权衡系数） | $\Gamma_{\mathrm{sla}}$（风险预算） |
| Pareto | 扫 $\lambda$ 描绘前沿 | 前沿上每点对应一个 $\Gamma$ |
| 求解 | 精确 MILP | 精确 MILP |

【说明】加权标量化与 ε-约束描述 **同一条 Pareto 前沿**；正文建议 **A 标定 + C 主表**。

---

## 14. 附录 A：Physical 对照模型（利用率 CVaR）

主文以 SLA 为准；以下为 `duibi.py` 中 **基础设施利用率** 风险（对照实验用）。

### 14.1 算力利用率 CVaR

$$
\mathrm{CVaR}^{N} \;=\; \zeta_N \;+\; \frac{1}{1-\beta_N} \sum_{s\in\mathcal{S}} \pi_s\, u_s
$$

$$
u_s \;\ge\; \frac{\sum_{i\in\mathcal{I}} w_{ik}\, y_{im}}{C^N_{mks}} - \zeta_N, \qquad \forall s,m,k
$$

【说明】$u_s$ 在此为 **节点利用率超阈** 的超额（与 SLA 的 $u_s$ 符号同名、不同块）。刻画 **算力拥塞尾部**。

---

### 14.2 链路利用率 CVaR

$$
\mathrm{CVaR}^{L} \;=\; \zeta_L \;+\; \frac{1}{1-\beta_L} \sum_{s\in\mathcal{S}} \pi_s\, v_s
$$

当 $\sigma_{es}>0$：

$$
v_s \;\ge\; \frac{\mathrm{flow}_e}{B_e\,\sigma_{es}} - \zeta_L, \qquad \forall s,e
$$

当 $\sigma_{es}=0$：

$$
\mathrm{flow}_e = 0
$$

【说明】  
- 分母 $B_e\sigma_{es}$：场景 $s$ 下有效容量。  
- 断链时强制该边 **计划流量为 0**（与 SLA 模型「路径断则 $d=0$」不同，此处更保守地约束全局 $x$）。

---

### 14.3 Physical Model A

$$
\min \quad c_p + c_b + \lambda_N\,\mathrm{CVaR}^{N} + \lambda_L\,\mathrm{CVaR}^{L}
$$

【说明】$\lambda_N,\lambda_L$ **宜分开**（算力拥塞 vs 链路拥塞机制不同）；不增加变量，仅多一个目标系数。

---

### 14.4 Physical Model C

$$
\min \quad c_p + c_b
\quad \text{s.t.} \quad \mathrm{CVaR}^{N} \le \Gamma_N,\;\; \mathrm{CVaR}^{L} \le \Gamma_L
$$

【说明】与 SLA Model C 同构，风险换为利用率 CVaR 预算。

---

## 15. 附录 B：Model B / Model D（简述）

| 模型 | 形式 | 【说明】 |
|------|------|----------|
| **B** | Model A 目标 + CVaR 块 KKT/Indicator 互补 | 与 A **同解**，用于证明 RU 线性化 = 双层 KKT 单层化；**大网慢**，正文可不跑 |
| **D** | Model B 互补的 McCormick 松弛 | **CVaR 可严重偏离 A**；仅 Copo 消融，不作主结果 |

---

## 16. 附录 C：代码对照

| 内容 | 实现 |
|------|------|
| SLA Model A（第 5–11 节） | `cvar_compare.build_teavar_sla_cvar_model` |
| SLA Model C（第 5–7、12 节） | `teavar_framework_models.build_teavar_model_c` |
| Physical A/C（第 14 节） | `duibi.build_single_layer_model` / `build_epsilon_constraint_model` |
| 虚拟接入（第 9 节） | `cvar_compare.add_teavar_virtual_bottleneck_constraints` |
| B4 数据与 K 短路 | `b4_joint_data.load_b4_joint_data` |

---

## 17. 公式清单自检

| 模块 | 是否含完整公式 | 是否逐条说明 |
|------|----------------|--------------|
| 成本 $c_p,c_b,C_{\mathrm{tot}}$ | ✅ | ✅ |
| $\mathbb{E}[\mathrm{Del}]$ 与 $-\omega\,\mathbb{E}[\mathrm{Del}]$（§4.3–4.5） | ✅ | ✅ |
| Model A/C **展开目标** 显含 $\omega$ | ✅ | ✅ |
| 放置/流/链路/算力约束 | ✅ | ✅ |
| 送达 Big-M 与 path_up | ✅ | ✅ |
| $\mathrm{CVaR}^{\mathrm{SLA}}$ | ✅ | ✅ |
| $\mathrm{CVaR}^{\mathrm{sf}}$ 线性化（§8，算网联合必选） | ✅ | ✅ |
| 虚拟接入 $\sigma^{\mathrm{vs/vt}}$ | ✅ | ✅ |
| 正常态 $\delta_{\min}$ | ✅ | ✅ |
| Model A / C 完整问题 | ✅ | ✅ |
| Physical CVaR$^{N,L}$ | ✅ | ✅ |
