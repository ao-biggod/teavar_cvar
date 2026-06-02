# 未来扩展：从原子 Task 到微服务 DAG

> **定位**：在现有 **Model A/C（SLA + 两阶段 path-based）** 之上的扩展设计草案；**当前仓库未实现**。  
> 主模型见 [`项目总结_模型AC.md`](./项目总结_模型AC.md)。

---

## 1. 什么变了？（三层对比）

### 1.1 现有模型（原子 task）

```
task i  ──(选一个 m)──►  节点 m  ── ingress + egress 两段路由
```

### 1.2 DAG 模型（每个 task 内部一张 DAG）

```
                    ┌→ ms2 ─→ ms4 ─┐
  task i:  src ─→ ms1 ┤              ├─→ dst
                    └→ ms3 ─────────┘
```

| 层面 | 现在 | DAG 扩展后 |
|------|------|------------|
| **放置** | 一个 task → 一个节点 $m$ | 每个微服务 $v\in V_i$ 各选一个节点 $m$ |
| **流量** | 两段（ingress / egress） | 源→入口微服务→**DAG 弧上传输**→出口微服务→宿 |
| **耦合** | $y_{im}$ 与 $x^{\mathrm{in/out}}$ 直接绑定 | **$u$ 在 $m$、$v$ 在 $n$** 决定中间流量从 $m$ 到 $n$ |

---

## 2. 输入：每个 task 一张 DAG

对任务 $i\in\mathcal{I}$，内部结构为有向无环图 $G_i=(V_i,A_i)$：

| 符号 | 含义 |
|------|------|
| $V_i$ | task $i$ 的微服务集合 |
| $A_i$ | 有向弧；$(u,v)\in A_i$ 表示 $u$ 的输出是 $v$ 的输入 |
| $d_{i,u,v}$ | 弧 $(u,v)$ 上需传输的数据量 |
| $V_i^{\mathrm{in}}\subseteq V_i$ | 入口微服务（接收外部 $b^{\mathrm{in}}_i$） |
| $V_i^{\mathrm{out}}\subseteq V_i$ | 出口微服务（产生外部 $b^{\mathrm{out}}_i$） |
| $w_{i,v,k}$ | 微服务 $v$ 对资源 $k$ 的需求 |

【说明】$G_i$ 为 **DAG**（无环），保证可拓扑排序；与「物理 WAN 可有环」无关。

可选：入口分配权重 $\alpha_{i,v}$（$\sum_{v\in V_i^{\mathrm{in}}}\alpha_{i,v}=1$），替代均分 $1/|V_i^{\mathrm{in}}|$。

---

## 3. 决策变量

### 3.1 放置

$$
y_{i,v,m} \in \{0,1\}, \qquad \forall i,\, v\in V_i,\, m\in\mathcal{M}
$$

$$
\sum_{m\in\mathcal{M}} y_{i,v,m} = 1, \qquad \forall i,\, v\in V_i \tag{P1}
$$

【说明】每个微服务 **恰好放在一个物理节点**；同一 task 的不同微服务 **可放在不同节点**。

---

### 3.2 耦合变量 $z$（放置决定中间流量的起止点）

$$
z_{i,u,v,m,n} \in \{0,1\}, \qquad \forall i,\,(u,v)\in A_i,\, m,n\in\mathcal{M}
$$

【说明】$z_{i,u,v,m,n}=1$ 当且仅当 **微服务 $u$ 在 $m$ 且 $v$ 在 $n$**。

线性化「且」：

$$
z_{i,u,v,m,n} \le y_{i,u,m} \tag{Z1}
$$

$$
z_{i,u,v,m,n} \le y_{i,v,n} \tag{Z1'}
$$

$$
z_{i,u,v,m,n} \ge y_{i,u,m} + y_{i,v,n} - 1 \tag{Z2}
$$

【说明】标准双线性 $z=y^u\cdot y^v$ 的 McCormick/线性化；仅对 **存在路径** 的 $(m,n)$ 对建 $z$（见 §7 剪枝）。

---

### 3.3 流量变量（三部分）

#### （A）Ingress：源 → 入口微服务

$$
x^{\mathrm{in}}_{i,v,m,p} \ge 0, \qquad
p \in \mathcal{P}_{s_{\mathrm{src}},m}
$$

$$
\sum_{m,p} x^{\mathrm{in}}_{i,v,m,p}
= y_{i,v,m}\cdot \alpha_{i,v}\, b^{\mathrm{in}}_i,
\qquad \forall i,\, v\in V_i^{\mathrm{in}} \tag{IN1}
$$

【说明】$\alpha_{i,v}$ 为入口权重（默认可取 $\alpha_{i,v}=1/|V_i^{\mathrm{in}}|$）。与现模型一致：仅 $y_{i,v,m}=1$ 的节点接收 ingress。

---

#### （B）中间传输：DAG 弧 $(u,v)$，$m\to n$

$$
f_{i,u,v,m,n,p} \ge 0, \qquad
p \in \mathcal{P}_{m,n}
$$

$$
\sum_{p\in\mathcal{P}_{m,n}} f_{i,u,v,m,n,p}
= z_{i,u,v,m,n}\cdot d_{i,u,v},
\qquad \forall i,\,(u,v)\in A_i,\, m,n \tag{F1}
$$

【说明】仅当 $u$ 在 $m$、$v$ 在 $n$ 同时成立时，弧 $(u,v)$ 上才有 $d_{i,u,v}$ 的流量经 $m\to n$ 的多路径送出。$m=n$ 时 $\mathcal{P}_{m,m}=\{[\,]\}$，流量可为 0 或视为本地零跳（需与 $d_{i,u,v}$ 语义一致）。

---

#### （C）Egress：出口微服务 → 宿

$$
x^{\mathrm{out}}_{i,v,m,q} \ge 0, \qquad
q \in \mathcal{P}_{m,s_{\mathrm{dst}}}
$$

$$
\sum_{m,q} x^{\mathrm{out}}_{i,v,m,q}
= y_{i,v,m}\cdot \beta_{i,v}\, b^{\mathrm{out}}_i,
\qquad \forall i,\, v\in V_i^{\mathrm{out}} \tag{OUT1}
$$

【说明】$\beta_{i,v}$ 为出口权重（默认可均分）。

---

### 3.4 场景送达（与现模型相同机制）

对每个场景 $s$，在 ingress / 中间 / egress 上定义 $d^{\mathrm{in}}_{i,v,m,p,s}$、$f^{\mathrm{del}}_{i,u,v,m,n,p,s}$、$d^{\mathrm{out}}_{i,v,m,q,s}$：

- 路径上所有边 $\sigma_{es}>0$：送达 $=$ 计划流量（Big-M 与 $y$ 耦合，同 [`项目总结_模型AC.md`](./项目总结_模型AC.md) §6.2）；
- 否则送达 $=0$（**不重路由**）。

---

## 4. 链路负载（注意：三项为加和）

场景 $s$ 下链路 $e$ 上的负载应为 **所有经过 $e$ 的送达量之和**（不是相减）：

$$
\mathrm{flow}_e(s)
=
\sum_{i}\sum_{v\in V_i^{\mathrm{in}}}\sum_{m,p:\,e\in p} d^{\mathrm{in}}_{i,v,m,p,s}
+
\sum_{i,(u,v)\in A_i}\sum_{m,n}\sum_{p:\,e\in p} f^{\mathrm{del}}_{i,u,v,m,n,p,s}
+
\sum_{i}\sum_{v\in V_i^{\mathrm{out}}}\sum_{m,q:\,e\in q} d^{\mathrm{out}}_{i,v,m,q,s}
$$

名义容量：

$$
\mathrm{flow}_e(s) \le B_e \quad \text{（或按场景用 } B_e\sigma_{es}\text{，与现 Physical/SLA 分工一致）}
$$

【说明】原草案中 ingress / 中间 / egress 之间的 **减号是错误的**；三段流量在链路上 **叠加占用带宽**。

---

## 5. 资源约束

$$
\sum_{i\in\mathcal{I}} \sum_{v\in V_i} w_{i,v,k}\, y_{i,v,m}
\le C^{\mathrm{norm}}_{mk},
\qquad \forall m\in\mathcal{M},\, k\in\mathcal{K} \tag{R1}
$$

【说明】同一物理节点 $m$ 上 **所有 task 的所有微服务** 的资源需求逐维求和。

---

## 6. CVaR：结构不变，聚合范围扩大

对每个任务 $i$、场景 $s$，扩展聚合送达，例如：

$$
R^{\mathrm{in}}_{is} = \sum_{v\in V_i^{\mathrm{in}}}\sum_{m,p} d^{\mathrm{in}}_{i,v,m,p,s}
$$

$$
R^{\mathrm{mid}}_{is} = \sum_{(u,v)\in A_i}\sum_{m,n,p} f^{\mathrm{del}}_{i,u,v,m,n,p,s}
$$

$$
R^{\mathrm{out}}_{is} = \sum_{v\in V_i^{\mathrm{out}}}\sum_{m,q} d^{\mathrm{out}}_{i,v,m,q,s}
$$

损失仍用 Rockafellar–Uryasev（与现模型同构），例如对 ingress/egress 仍按 $b^{\mathrm{in}}_i,b^{\mathrm{out}}_i$ 归一化；对中间弧可另设需求上界 $d_{i,u,v}$ 或把 $R^{\mathrm{mid}}_{is}$ 与 $\sum_{(u,v)} d_{i,u,v}$ 比较。**Model A/C 的 $\lambda$ / $\Gamma$ 框架无需改结构**，只扩展 $R$ 的定义。

【说明】需明确 SLA 指标：是「仅关心对外 $b^{\mathrm{in/out}}$」还是「中间弧传输也要满足 SLA」——后者需在损失里为每条 $(u,v)$ 或聚合 $R^{\mathrm{mid}}_{is}$ 加约束行。

---

## 7. 计算代价与剪枝

### 7.1 规模（量级）

| 类别 | 数量级 | 说明 |
|------|--------|------|
| $y_{i,v,m}$ | $O(|\mathcal{I}|\cdot |V_i|_{\max}\cdot |\mathcal{M}|)$ | 微服务放置 |
| $z_{i,u,v,m,n}$ | $O(|\mathcal{I}|\cdot |A_i|_{\max}\cdot |\mathcal{M}|^2)$ | **主要新增瓶颈** |
| $f_{i,u,v,m,n,p}$ | $O(|\mathcal{I}|\cdot |A_i|_{\max}\cdot |\mathcal{M}|^2\cdot K)$ | 中间多路径 |

### 7.2 剪枝策略

1. **预过滤 $(m,n)$**：仅当 $\mathcal{P}_{m,n}\neq\emptyset$ 时建 $z,f$。  
2. **距离剪枝**：$m,n$ 最短 hop $>H_{\max}$ 时不建 $z$（避免远距离传大流量）。  
3. **阶段聚合**：将 DAG 粗化为 2–3 个阶段（预处理→推理→后处理），$|V_i|$ 与 $|A_i|$ 可控。  
4. **同节点**：$m=n$ 且 $d_{i,u,v}$ 大时，可强制 $y_{i,u,m}=y_{i,v,m}$（同机部署）或单独建模本地通信。

---

## 8. 实现路线（分阶段）

### Phase 1：DAG 骨架（中间流量不优化）

- 每个微服务独立放置（P1 + R1）；
- 中间 $(u,v)$ 流量走 **固定最短路径**（不引入 $f$ 的多路径变量）；
- $z$ 仅用于统计/可行性，或省略 $f$，用 $z\cdot d$ 直接计入链路负载上界；
- **目标**：变量数可控，验证 $y+z$ 与资源/CVaR 接口。

### Phase 2：中间多路径 + 完整 SLA

- 加入 $f_{i,u,v,m,n,p}$ 与 (F1)；
- $(m,n)$ 剪枝 + 每对仅保留 top-$K$ 短路；
- CVaR 同时覆盖 ingress + mid + egress（按 §6 选定 SLA 定义）；
- **目标**：完整联合优化，复用现 `cvar_compare` 的 $d$–路径–$\sigma$ 耦合。

### Phase 3：规模与建模范式

- 大网上评估 **flow-based**（AEGIS 式）替代全量 $\mathcal{P}_{m,n}$；
- DAG 弧聚类、场景聚类；
- **目标**：突破 $|M|^2 K$ 路径预计算瓶颈。

---

## 9. 退化到现模型（正确性检查）

当 $|V_i|=1$，$V_i^{\mathrm{in}}=V_i^{\mathrm{out}}=\{v_0\}$，$A_i=\emptyset$ 时：

- $y_{i,v_0,m}\equiv y_{im}$（原子 task）；
- 无 $z,f$；
- 仅余 ingress/egress → **与现 `build_teavar_sla_cvar_model` 一致**。

---

## 10. 一句话

DAG 扩展的核心是 **$y_{i,m}\to y_{i,v,m}$**，并用 **$z_{i,u,v,m,n}=y_{i,u,m}\wedge y_{i,v,n}$** 把「谁与谁通信」和「流量从哪到哪」耦合起来；变量主要涨在 **$O(|A_i||M|^2)$ 的 $z$** 上，靠 $(m,n)$ 过滤与阶段聚合压规模。**多路径、场景送达、CVaR 线性化、Model A/C** 均可复用，链路负载应对 ingress、中间、egress **求和**。

---

## 11. 对原草案的修正备忘

| 项 | 原表述 | 修正 |
|----|--------|------|
| $\mathrm{flow}_e(s)$ | ingress **减** 中间 **减** egress | 三段 **相加**（§4） |
| 代价表 | 表格损坏 | 见 §7.1 |
| SLA 中间段 | 仅文字「扩展聚合」 | 需明确 $R^{\mathrm{mid}}$ 与损失如何进 $u_s$（§6） |
