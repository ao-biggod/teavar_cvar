# 与 TEAVAR / AEGIS / Copo 的关系

> 本文档说明本项目与三篇核心参考文献的继承与区别。不是为了"全部优于"，
> 而是为了准确界定本文的贡献边界。

---

## TEAVAR（隧道分流 + 链路故障 CVaR）

**论文**：Throughput-Guaranteed Resilient Routing via a Conditional Value-at-Risk Approach

**核心贡献**：
- 在离散 SRG 故障场景下，为每条 flow 在多条隧道间分配流量
- 损失函数：$\displaystyle L(x,y) = \max_i \left[1 - \frac{\sum_{r\in R_i} x_r y_r}{d_i}\right]^+$（per-flow max 公平聚合）
- CVaR 进目标函数（不是约束）
- 场景 pruning：树状遍历，概率 $< 10^{-5}$ 停止展开，剪除场景合并为 aggregate

**本项目继承**：
- CVaR 的 Rockafellar–Uryasev 线性化形式
- max per-flow loss 作为 fairness variant 的参考
- 场景 pruning 的 aggregate scenario 方法（Toy-2Task 的 `prune_mode="aggregate_worst"` 选项）

**本项目区别**：
- TEAVAR 是**纯网络路由**（无计算放置），本项目引入算力节点放置决策
- TEAVAR 损失仅来自**链路故障**，本项目损失同时来自链路故障和算力故障
- TEAVAR 使用 per-flow max 做公平聚合，本项目 M2 采用加权平均 $\sum\omega_i(1-z_i)$（可按需切换为 max）

---

## AEGIS（CVaR 吞吐保证路由）

**论文**：AEGIS: Throughput-Guaranteed Resilient Routing via a Conditional Value-at-Risk Approach（Zhang et al., IEEE/ACM Trans. Networking 2026）

**核心贡献**：
- **AEGIS-O**：$\min \mathrm{CVaR}_\beta(\Omega)$（CVaR 进目标）
- **AEGIS-A**：$\min \sum_k \sum_{(u,v)} (W_k(u,v)+W_k(v,u))$ s.t. $\mathrm{CVaR}_\beta(\Omega) \le \lambda$（CVaR 进约束，min 路由资源使用量）
- 损失函数：$\Omega^q = \sum_k (f_k - g_k^q)$（场景 q 下总吞吐损失）
- 场景生成：SRLG 独立 Bernoulli 乘积

**本项目继承**：
- M2-C-Cost 结构最接近 **AEGIS-A**：$\min$ 资源/成本 + CVaR 约束
- 独立组件故障场景生成方式与本项目 Toy-2Task 一致

**本项目区别**：
- AEGIS 是**纯网络路由**（无计算放置），无 $y_{i,m}$ 变量
- AEGIS 的约束是**链路容量**硬约束（每个场景必须满足），本项目 M2-C-Cost 用 CVaR 软约束
- AEGIS 无计算资源维度 $\mathcal{K}$，无算力容量 $C_{m,s}^{(k)}$
- 本项目引入服务比例变量 $r_{i,m,s}$，将链路送达与算力处理耦合

---

## Copo（计算–网络成本联合优化）

**论文**：Copo: Joint Cost and Performance Optimization for Task Placement in Geo-Distributed Clouds（Wang et al., ICNP 2025）

**核心贡献**：
- $\min E_1 + E_2$：计算资源成本 $E_1 = \sum x_{i,r}^t q_i^t p_r$ + 带宽成本 $E_2 = \sum y_{u,w}^j b_j p_{u,w}$
- 性能通过下层 KKT 条件进入约束
- 链路按流量 × 单价计费

**本项目继承**：
- $\min c_p + c_b$ 的成本目标框架
- 按链路实际流量 × 链路单价计费的方式
- 计算资源按维度定价（CPU/GPU/HBM 分别有 $\rho_{m,k}$）

**本项目区别**：
- Copo 是**确定性模型**：无故障场景、无 CVaR、无 stochastic recourse
- Copo 的 task-to-task 通信是任意图（DAG），本项目是固定的两段式 source→compute→destination
- Copo 无服务比例变量，无链路故障与算力故障的交互
- 本项目 M2-C-Cost 在确定性成本目标上增加 CVaR 约束，引入了场景概率和尾部风险

---

## 符号选择说明

AEGIS 和 Copo 的符号有大量冲突。本项目采用以下统一约定：

| 符号 | 本项目含义 |
|:--|:--|
| $\alpha$ | CVaR 置信水平（Rockafellar & Uryasev 标准） |
| $\eta$ | VaR 辅助变量 |
| $\gamma$ / $\Gamma$ | 风险预算上界（约束式右端） |
| $\lambda$ | M0 负载均衡权重（$\lambda U^{max}_{link}+(1-\lambda)U^{max}_{node}$） |
| $\omega_i$ | M2 端到端损失中任务 $i$ 的权重 |
| $\rho_{m,k}$ | 节点 $m$ 资源 $k$ 的单价 |
| $\rho^{\text{link}}_e$ | 链路 $e$ 的带宽单价 |

---

## 本文的独特贡献

将以上三条线中各自独立解决的问题统一到一个框架中：

1. **从纯路由到联合放置**：引入 $y_{i,m}$，在路由同时优化算力节点选择
2. **从确定性到故障场景**：引入 $\mathcal{S}, \pi_s, C_{m,s}^{(k)}, \sigma_{e,s}$，让链路和算力故障在场景 recourse 中自然交叉
3. **从分离 CVaR 到统一 $L^{E2E}$**：链路送达不足和算力容量不足都通过 $r_{i,m,s}$ 汇入同一损失度量，不做"链路 CVaR + 节点 CVaR"的双项并列
4. **从纯风险到成本+风险**：M2-C-Cost 在 AEGIS-A 的 CVaR 约束结构上，将目标替换为 Copo 风格的计算+传输成本
