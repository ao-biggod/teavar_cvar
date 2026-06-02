这是一份为您精心整理的 2026 年 IEEE TON 论文 **AEGIS** 的详细技术摘要。摘要采用了标准的 Markdown 格式和严谨的 $\LaTeX$ 数学公式表达，修复了原始 TXT 文本中的所有转换乱码（如将错误的 `X` 还原为 `\sum`，大括号还原等），非常适合直接复制给 **Cursor** 进行上下文读取、代码编写或架构设计。

---

# 论文摘要：AEGIS: Throughput-Guaranteed Resilient Routing via a Conditional Value-at-Risk Approach (2026)

## 一、 主要目的 (Main Objective)

该论文旨在解决现代不确定、对抗性网络环境（如军事任务网络、大型骨干商业网络）中的弹性路由问题。它攻克了以下核心科学与工程问题：

1. **摆脱路径预计算的限制**：传统的流量工程（TE）方案（如 TEAVAR）高度依赖于事前的路径枚举（Path-based）。当网络规模增大时，路径数量呈指数级爆炸，计算极其困难；而若限制路径数量（如只选3条），抗灾吞吐量又会大打折扣。AEGIS 提出了基于流（Flow-based）的建模，不依赖任何预计算路径，从底层打破了这一计算瓶颈。
2. **兼顾多重网络刚性约束**：在主动控灾（最小化风险）的同时，显式保证了正常状态下的最低用户承诺吞吐量（SLA），并且严格不穿透用户的经济/资源预算约束。
3. **消除资源预留引发的环流**：发现并解决了传统多商品流优化在应对灾难预留带宽时必然会产生的“拓扑环路（Cyclic Flows）”问题，通过引入二分法机制（AEGIS-A），在保障风控的前提下实现了完全无环、高资源效率的工程部署。

---

## 二、 建模过程 (Modeling Process)

### 1. 基础系统与符号定义

* **物理拓扑**：无向图 $G = (V, E)$，其中节点数 $|V|=n$，链路数 $|E|=m$。
* **链路属性**：每条链路 $e = (u,v)$ 具有固定的物理容量 $c_e > 0$，以及单位过路费（单位成本） $\kappa_e > 0$（量化延迟、能耗或经济成本）。
* **用户请求**：共有 $K$ 个用户，每个用户的请求表示为四元组 $(s_k, t_k, d_k, b_k)$，分别代表源节点、目的节点、带宽业务需求以及最大总经济预算。
* **概率故障模型**：由一组独立的共享风险链路组（SRLG）失效事件 $Z$ 驱动。全网的故障状态记为二进制随机向量 $q = (q_1, \dots, q_{|Z|})$。每种故障情况 $q \in Q$ 发生的联合概率为：

$$p_q = \prod_{z \in Z} \left( q_z p_z + (1 - q_z)(1 - p_z) \right) \quad \text{}$$



发生故障 $q$ 时，损坏切断的链路集合记为 $E^q$。

### 2. 双层流模型设计

* **工作流 (Working Flow)**：正常无故障时全网的流量分配表，变量为 $W_k(u,v)$，代表用户 $k$ 在单向链路上分配的带宽。其正常吞吐量为 $f_k = \sum_{(u,t_k)\in E} W_k(u, t_k) - \sum_{(t_k,v)\in E} W_k(t_k, v)$，硬性要求 $f_k \ge \gamma d_k$（$\gamma$ 为正常状态保底系数）。
* **恢复流 (Recovery Flow)**：针对故障场景 $q$ 的裁剪抢救流方案，变量为 $R_k^q(u,v)$。该流遵守铁律：在坏路 $E^q$ 上强制清零；在完好路上不允许超过原工作流（$R_k^q(u,v) \le W_k(u,v)$），即“只做减法，绝不增载接盘”。其最终送达信宿的净恢复吞吐量记为 $g_k^q$。

### 3. 风险度量与损失定义

故障场景 $q$ 下，全网大盘的**总吞吐量损失 (Total Throughput Loss)** 定义为：


$$\Omega^q(W) = \sum_{k \in \mathcal{K}} (f_k - g_k^q), \quad \forall q \in Q \quad \text{}$$


为了对冲尾部极端突发大灾难（黑天鹅事件），模型引入置信水平 $\beta \in [0, 1)$，优化目标设定为最小化损失的条件风险价值（Conditional Value-at-Risk）：


$$\min_{W} \text{CVaR}_\beta (\Omega^q(W)) \quad \text{}$$

---

### 4. 核心数学规划模型 formulation

#### 模型一：AEGIS-O-LP (最优多商品流模型——可能含环)

由于原始 $\text{CVaR}$ 函数不可微且非线性，通过引入 Rockafellar-Uryasev 定理中的辅助决策变量 $\alpha$（代表 VaR 阈值）以及针对每种故障情况的损失松弛变量 $\Phi^q$，将其转化为等价的标准线性规划问题：

$$\min_{W, R, \alpha, \Phi^q} \quad \alpha + \frac{1}{1-\beta}\sum_{q \in Q} p_q \Phi^q \quad \text{}$$

$$\text{s.t.} \quad \Phi^q \ge 0, \quad \forall q \in Q \quad \text{}$$

$$\Phi^q \ge \Omega^q(W) - \alpha, \quad \forall q \in Q \quad \text{}$$

**【正常工作流约束 (P1)】**：


$$\sum_{(u,v)\in E} W_k(u,v) - \sum_{(v,u)\in E} W_k(v,u) = 0, \quad \forall k \in \mathcal{K}, \forall v \in V \setminus \{s_k, t_k\} \quad \text{（节点流量守恒）}$$

$$\sum_{(u,t_k)\in E} W_k(u, t_k) - \sum_{(t_k,v)\in E} W_k(t_k, v) \ge \gamma d_k, \quad \forall k \in \mathcal{K} \quad \text{（SLA最低保障吞吐量）}$$

$$\sum_{k \in \mathcal{K}} (W_k(u,v) + W_k(v,u)) \le c_e, \quad \forall e=(u,v) \in E \quad \text{（物理链路容量上限）}$$

$$\sum_{e=(u,v)\in E} \kappa_e (W_k(u,v) + W_k(v,u)) \le b_k, \quad \forall k \in \mathcal{K} \quad \text{（用户花费不超支约束）}$$

**【故障恢复流约束 (P2)】**（$\forall q \in Q, \forall k \in \mathcal{K}$）：


$$\sum_{(u,v)\in E} R_k^q(u,v) - \sum_{(v,u)\in E} R_k^q(v,u) = 0, \quad \forall v \in V \setminus \{s_k, t_k\} \quad \text{（故障下中间节点守恒）}$$

$$R_k^q(u,v) = 0, \ R_k^q(v,u) = 0, \quad \forall (u,v) \in E^q \quad \text{（断裂链路上恢复流量为0）}$$

$$R_k^q(u,v) \le W_k(u,v), \ R_k^q(v,u) \le W_k(v,u), \quad \forall (u,v) \in E \quad \text{（生存流上限受限于正常工作流）}$$

$$g_k^q \le f_k \quad \text{（单商品恢复吞吐量不超过工作吞吐量）}$$

$$W_k(u,v) \ge 0, \ R_k^q(u,v) \ge 0 \quad \text{（非负约束）}$$

#### 模型二：AEGIS-A-LP (无环且低资源资源开销模型)

由于 AEGIS-O 强烈的预留占座特征，其解必然会产生局部无用的环流，引发带宽超载浪费。
AEGIS-A 进行了范式大颠倒：它将 $\text{CVaR}$ 风险限制踢去作为**约束条件**，反过来将最小化全网工作流总体积（消灭环路）作为目标函数：

$$\min_{W, \alpha, \Phi^q} \quad \sum_{k\in\mathcal{K}}\sum_{(u,v)\in E}(W_{k}(u,v)+W_{k}(v,u)) \quad \text{}$$

$$\text{s.t.} \quad \alpha + \frac{1}{1-\beta}\sum_{q\in Q}p_{q}\Phi^{q} \le \lambda \quad \text{（【新增核心】CVaR 风险容忍度紧箍咒约束）}$$

$$\text{同时需满足上述 AEGIS-O-LP 的所有其他工作流与恢复流约束} \quad \text{}$$

* **二分搜索算法 (Bisection Approach)**：
因为环流是否彻底消失取决于风险指标 $\lambda$ 的大小，算法 1 初始化设定损失下界 $LB = 0$，上界 $UB = \gamma \sum_k d_k$（最大可能损失）。每次取中点 $\lambda = (LB+UB)/2$ 送入 Gurobi 求解：若无解或解仍含环，则风险卡得太死，更新 $LB = \lambda$；若跑出了可行的无环完美解，则收缩天花板，更新 $UB = \lambda$。当 $UB - LB \le 10^{-6}$ 时终止，导出经验最优的无环、省资源路由表。

---

## 三、 实验成果 (Experimental Results)

这篇论文在真实世界骨干网络（挪威学术网 Uninett、美国电信商 US Carrier、意大利超宽带网 GARR-X）和 Waxman 随机图上进行了详尽仿真，得出了突破性的惊人数据：

### 1. 计算时延与扩展性：断崖式暴杀 TEAVAR

* **Uninett 网络拓扑（74节点）**：最优模型 AEGIS-O 比包含全路径的 `TeaA`（TEAVAR 全路径基线）**快了大约 5500 倍**！无环模型 AEGIS-A 也快了 **420 倍**。
* **US Carrier 拓扑（158节点）**：AEGIS-O 比 `TeaA` 慢的路径枚举算法**快了 87 倍**。
* **路径爆炸惩罚**：当 Waxman 拓扑节点增至 120 以上时，`TeaA` 由于需要离线枚举海量路径（如 6x6 网格包含超过 **126万条** 路径，导致线性规划矩阵庞大至极），在规定时间内彻底**卡死无法返回解**。而 AEGIS 的多项式级复杂度可以在极短时间内（几十秒内）轻而易举地完美收敛 240 个节点和 6 个 SRLGs 的大盘。

### 2. 灾后生存质量（期望吞吐量与风险控制）

* **期望恢复吞吐量提升**：在各种流量保底比例 $\gamma$ 下，AEGIS-O 的灾后数据存活平均吞吐量比 `TeaA` 高出 **14% ~ 17%**，比受路径限制的 `Tea3` 拔高了 **25% ~ 27%**。
* **尾部极端大灾风险降维**：对于最核心的优化指标（吞吐量损失的 $\text{CVaR}$），AEGIS-O 比 `TeaA` 成功**降低了 22% ~ 43% 的瘫痪量**，比 `Tea3` 更是**暴砍了 46% ~ 64% 的灾难风险**。
* **对比期望最小化方法 (MinEA)**：AEGIS-O 较传统的平均主义方案 MinEA 在吞吐量上提升 9%~15%，在黑天鹅对冲风险（CVaR）上**大幅降低了 39% 至 50%**。

### 3. 资源开销与帮运营商“省钱度” (AEGIS-A 的威力)

* **清除形式主义占座**：由于成功用二分法开除了打转的环流，**AEGIS-A 相比于 AEGIS-O 暴砍了 46% 至 58% 的物理带宽消耗，并为全网用户缩减了 50% 到 67% 的实际总经济/预算成本**。
* **超越经典 TEAVAR**：在资源消耗方面，AEGIS-A 比全路径的 `TeaA` 节省了 18% ~ 31% 的带宽以及 21% ~ 38% 的过路费开销，且其风控和抗灾吞吐指标依然保持和 `TeaA` 完全持平的超高竞技水准。