# TEAVAR_python 项目现状详述（供 AI 规划后续进展）

---

## 零、项目一句话定位

**算力–网络联合优化的 MILP 框架**：在广域 WAN 上有向图 + 任务放置 + 两阶段多路径分流 + SLA 型 CVaR 尾部风险，面向学术论文投稿。求解器 Gurobi，主数据 B4 拓扑 + 扩展至 9 个真实 WAN 拓扑。

---

## 一、目录结构与核心文件职责

```
TEAVAR_python/
├── main.py                          # 统一 CLI 入口：--mode teavar（论文复现）/ --mode joint（B4联合放置）
├── TEAVAR_Gurobi.py                 # 原始 TEAVAR 隧道分流 MILP（纯 WAN 无算力）
├── duibi.py                         # Physical CVaR 体系：Model A/B/C/D（玩具数据 + B4 加载）
├── cvar_compare.py                  # SLA CVaR 体系核心：build_teavar_sla_cvar_model() + 虚拟接入瓶颈
├── teavar_framework_models.py       # SLA CVaR 体系：Model A/B/C/D（与 duibi 四模型对齐）
├── progressive_pipeline.py          # 递进管线（A→C→B→D 数据流动）+ 四项优化原型
├── b4_joint_data.py                 # 数据加载器：B4 + 9 拓扑泛化 + K短路 + UMCF虚拟节点
├── duibi_metrics.py                 # 解后指标：利用率/送达/SLA损失/链路流量
├── parsers.py                       # 拓扑/需求解析（含与 Julia 参考对齐的缩放约定）
├── util.py                          # Weibull 链路故障概率 + 子场景生成
├── generate_compute_resources.py    # 多拓扑算力资源自动生成（角色分配+定价）
├── plot_duibi_paper_narrative.py    # 论文图表脚本
├── plot_duibi_umcf_sweep.py         # UMCF 参数扫描图表
├── experiment_report.py             # 实验报告生成
├── data/
│   ├── B4/                          # 原始 B4：topology.txt, demand.txt, paths, node_compute_resources.csv
│   ├── ATT/ IBM/ XNet/ Nextgen/ Abilene/ Sprint/ Custom/ Custom2/
│   │   └── topology.txt, node_compute_resources.csv（自动生成）
│   └── raw/
├── 建模公式说明.md                   # 各函数对应的完整数学公式（主文档，约700行）
├── 项目总结_模型AC.md                # Model A/C 的公式补全版文档
├── 论文初稿.md                       # 论文正文初稿（含双层规划讨论、四模型逻辑链）
├── 改进报告.md                       # 项目改进记录（三方向：递进管线、CVaR对比、多拓扑）
├── AEGIS.md                         # AEGIS 论文详细摘要
├── Compute-aware Routing.md         # 实验数据与评估结果表
├── 未来扩展_微服务DAG.md             # 从原子 task 到微服务 DAG 的扩展设计草案
└── README.md                        # 运行说明与命令行参数
```

---

## 二、三篇参考论文

### 1. TEAVAR（SIGCOMM 2019, Bogle et al.）
- **核心贡献**：在 WAN 上为每条 flow 分配隧道流量，用 CVaR 度量"未满足需求比例"的尾部风险
- **方法**：离散链路故障场景 + Rockafellar-Uryasev 线性化 → 单层 MILP
- **我们借鉴**：CVaR 线性化技术、路径预计算（K 短路）、概率场景生成
- **我们不采用**：纯 WAN（无算力放置）、无向两阶段业务流

### 2. Copo（ICNP 2025, Wang et al.）
- **核心贡献**：任务放置成本 + 带宽成本联合优化；用 KKT/McCormick 将双层（上层成本、下层性能）压为单层
- **方法**：双层规划 → KKT 条件 → Indicator/McCormick 线性化互补约束
- **我们借鉴**：放置+带宽联合目标、KKT Indicator 验证（Model B）、McCormick 松弛消融（Model D）
- **我们不采用**：地理区域流模型、McCormick 作主求解器（我们实测偏210%）

### 3. AEGIS（IEEE TON 2026, Zhang et al.）
- **核心贡献**：Flow-based（无路径枚举）弹性路由 + CVaR 约束 + 正常态吞吐下界 γ
- **方法**：工作流 + 恢复流双层设计；AEGIS-A 将 CVaR 作约束、资源作目标 + 二分搜索
- **我们借鉴**：CVaR 作约束（Model C）、正常态 δ_min 下界、环流讨论
- **我们不采用**：Flow-based 弧变量（我们仍是 path-based）

---

## 三、四模型架构（Model A/B/C/D）

### 共享物理骨架
所有模型共享同一套约束：
- 任务不可分割：Σ_m y_im = 1
- Ingress 流量激活：Σ_p x_in ≤ y_im · b_in_i
- Egress 流量激活：Σ_q x_out ≤ y_im · b_out_i
- 名义链路容量：flow_e ≤ B_e
- 名义算力容量：Σ_i w_ik · y_im ≤ C_norm_mk
- 路径可达性 Big-M：d 与 x 的耦合（路径断则 d=0，路径通则 d=x）
- SLA CVaR 线性化（Rockafellar-Uryasev）：ζ + 1/(1-β) · Σ π_s · u_s
- 算力未满足 CVaR（可选）：e_mks = max(0, D_mk - C_N_mks) 的 Big-M 线性化

### 成本公式
```
c_p = Σ_i,m y_im · Σ_k w_ik · π_mk        # 放置成本
c_b = Σ x_in · τ_p + Σ x_out · τ_q        # 带宽成本（τ_p = Σ_{e∈p} π_e 路径价）
E[Del] = Σ_s π_s Σ(d_in + d_out)          # 期望送达量
C_tot = c_p + c_b - ω · E[Del]            # 总经济成本（含送达奖励）
```

### Model A — 单层加权（精确，主求解器）
```
min  C_tot + λ_sla·CVaR_SLA + λ_sf·CVaR_sf
```
- 用途：λ 扫描绘制 Pareto 前沿，标定 Model C 的 Γ
- 代码：`cvar_compare.build_teavar_sla_cvar_model()` / `duibi.build_single_layer_model()`
- 特点：精确 MILP，不需要额外二元变量

### Model C — ε 约束 / 风险预算（精确，主求解器）
```
min  C_tot   s.t.   CVaR_SLA ≤ Γ_sla,  CVaR_sf ≤ Γ_sf
```
- 用途：风险预算可解释（对齐 AEGIS-A），适合论文主表
- 代码：`teavar_framework_models.build_teavar_model_c()` / `duibi.build_epsilon_constraint_model()`
- 标定：Γ ≈ (1+ε) × CVaR_A*，从 Model A 的 λ 扫描得到
- Model A 和 Model C 描述**同一条 Pareto 前沿**

### Model B — KKT + Indicator（精确，验证件）
```
同 Model A 目标 + SLA CVaR 子问题的 KKT 互补 Indicator 约束
```
- 用途：验证 Model A 的 CVaR 线性化等价于严格双层 KKT 单层化
- 代码：`teavar_framework_models.build_teavar_model_b()` / `duibi.build_kkt_model()`
- 特点：大量二元变量，慢（仅为验证用，非日常求解器）
- 与论文对话：展示与 Copo KKT 路线的等价性

### Model D — McCormick 松弛（近似，消融件）
```
min  C_tot   + McCormick 线性包络松弛 KKT 互补
```
- 用途：复现 Copo 的加速思路，展示"快但不准"的风险穿透
- 代码：`teavar_framework_models.build_teavar_model_d()` / `duibi.build_copo_mccormick_model()`
- 实测：事后 CVaR 可偏离 210%（玩具数据），不可作主结果

---

## 四、两套 CVaR 体系

### 体系一：Physical CVaR（基础设施利用率视角，对照用）
- `duibi.py` 实现
- 算力利用率 CVaR：`CVaR_N = ζ_N + 1/(1-β_N)·Σ π_s·u_s`，其中 `u_s ≥ (Σ w y) / C_N_mks - ζ_N`
- 链路利用率 CVaR：`CVaR_L = ζ_L + 1/(1-β_L)·Σ π_s·v_s`，其中 `v_s ≥ flow_e / (B_e·σ_es) - ζ_L`
- 目标：`min c_p + c_b + λ_N·CVaR_N + λ_L·CVaR_L`
- 回答的问题："资源是否拥塞/超载？"

### 体系二：SLA CVaR（用户需求未满足视角，主线）
- `cvar_compare.py` + `teavar_framework_models.py` 实现
- 场景损失：`L_s = max_i max{1 - R_in_is/b_in_i, 1 - R_out_is/b_out_i}`
- SLA CVaR：`ζ + 1/(1-β_loss)·Σ π_s·u_s`，其中 `u_s ≥ L_s - ζ`
- 可选算力未满足 CVaR：`e_mks = max(0, D_mk - C_N_mks)`，归一化后 CVaR
- 目标含送达奖励：`min C_tot + λ_sla·CVaR_SLA + λ_sf·CVaR_sf`（其中 C_tot 已含 -ω·E[Del]）
- 回答的问题："故障时用户业务断了多少？"

### 关键差异
| 维度 | Physical | SLA |
|------|----------|-----|
| 风险对象 | 资源利用率 | 需求未满足率 |
| 对齐论文 | Copo 风格 | TEAVAR/AEGIS 风格 |
| 退化风险 | λ=0 时忽略风险 | 全堆 hub+空路径时 CVaR=0 |
| 论文角色 | 对照/附录 | 主线 |

---

## 五、数据集现状

### B4 拓扑（主实验）
- 12 节点、38 有向边
- topology.txt（含 prob_failure 列）
- demand.txt（OD 流量矩阵）
- node_compute_resources.csv（手工制作的算力容量+单价）
- 3 个离散场景：s=0 全通，s=1 链路中断，s=2 算力降额

### 9 个扩展拓扑
| 拓扑 | 节点 | 边 | 状态 |
|------|------|-----|------|
| ATT | 25 | 112 | ✅ |
| XNet | 28 | 76 | ⚠️ 缺 prob_failure 列（默认 0.001） |
| IBM | 17 | 46 | ✅ |
| Nextgen | 17 | 38 | ⚠️ demand.txt 为空（synthetic gravity model） |
| Abilene | 12 | 30 | ✅ |
| B4 | 12 | 38 | ✅ |
| Sprint | 11 | 36 | ⚠️ 0-based 节点索引（已自动 shift） |
| Custom | 6 | 18 | ✅ |
| Custom2 | 5 | 14 | ⚠️ hub=0 无出向需求（已自动选 hub） |

### 算力资源生成规则（`generate_compute_resources.py`）
- 按度数中心性分三层角色：Core（高容量低单价 0.75x）、Aggregation（基准 1.0x）、Edge（溢价 1.45x）
- 3 维资源：CPU（基准 ×1.0）、GPU（×3.5-5.0）、HBM（×1.5-2.5）
- 场景 s=2 下 aggregation 节点容量降额到 20%-50%

### 流锚点与路由语义
- **Hub 径向（默认）**：所有任务的源/宿统一锚定在 hub 节点 h（简化特例，代码中 `s_i = t_i = h`）
- **UMCF（显式虚拟源/汇）**：扩展 `V_s, V_t` 虚拟节点，`s_i = V_s, t_i = V_t`
- **虚拟接入瓶颈**：非 UMCF 时为每个 (m,s) 写 `σ_vs[m,s]`（默认 0.99），约束送达上界
- **当前局限**：一般化 `s_i→m→t_i`（per-task OD）尚未实现，`b4_joint_data` 从 demand 读取的 `(hub, dst)` 仅标定 `b_in/b_out` 量级

---

## 六、已实现的关键机制

### 1. 递进管线（`progressive_pipeline.py`）
```
Phase 1: Model A（λ 扫描）→ 输出 CVaR* 值
Phase 2: Model C（用 CVaR* × 1.05 标定 Γ）→ min cost @ 风险预算
Phase 3: Model B（同 λ 验证）→ 确认 gap(A,B) ≈ 0
Phase 4: Model D（松弛消融）→ 展示风险穿透
```

### 2. 退化缓解机制
- **虚拟源/汇接入瓶颈**（`--joint-virtual-source`）：为每个放置点添加逻辑接入边 σ_vs < 1，使空物理路径也有接入风险
- **UMCF 显式虚拟节点**（`--joint-umcf-teavar`）：扩展图添加 V_s, V_t，ingress/egress 路径锚点变更
- **Stress 场景**（`--joint-stress-zero-s1`）：场景 1 切断 hub 所有出边，打破对称
- **min_off_hub**（`--joint-min-off-hub`）：强制至少 N 个任务不在 hub，防止全堆 hub
- **送达奖励 -ω·E[Del]**：防止零流退化解

### 3. 四项优化原型（`progressive_pipeline.py` 中）
- **热启动**：Model A 的 y 解 → Model C/B 的 MIPStart
- **自适应 McCormick**：从 Model A 参考解提取利用率范围收紧 slack（原型，未达到 <20% 偏差）
- **场景聚类**：余弦相似度 > 0.95 的场景合并
- **紧 Big-M**：用路径容量瓶颈推导 per-(i,node) 紧 M

### 4. 解后指标（`duibi_metrics.py`）
- 名义链路/节点利用率
- 最坏场景链路/节点利用率
- 期望送达比例/体积
- per 场景最大需求损失

---

## 七、命令行运行方式

```bash
# 1. 论文 TEAVAR 复现（纯 WAN，无算力）
python main.py --mode teavar --topology B4

# 2. B4 + 联合放置 + CVaR（新模型，主实验）
python main.py --mode joint --topology B4 --joint-lambdas "0.5,5,50"

# 3. 玩具数据上 Physical vs SLA 并排
python cvar_compare.py --lambdas "0.5,5,50"

# 4. duibi 四模型（玩具/B4）
python duibi.py --toy --progressive --lambda 5.0
python duibi.py --b4 --progressive --lambda 5.0

# 5. TEAVAR SLA 递进管线
python progressive_pipeline.py --toy --lambda-sla 0.5

# 6. 两套 CVaR 并排对比
python progressive_pipeline.py --toy --compare --lambda 5.0
```

---

## 八、当前已知结果

### 求解性能（玩具数据实测）
| Model | 耗时 | cost 一致性 | CVaR 偏差 |
|-------|------|-------------|-----------|
| A | 0.07s | 基准 | 基准 |
| B | 0.02s | gap=0% | 与 A 完全一致 |
| C | 0.01s | — | 受 Γ 约束 |
| D | 0.02s | 与 A 一致 | **+210%** (事后) |

### 关键发现
1. **Model A ↔ C 等价性验证通过**：同一条 Pareto 前沿
2. **Model B 验证通过**：KKT 条件正确，与 A 的无差别
3. **Model D 风险穿透严重**：McCormick 松弛使事后 CVaR 远大于精确值
4. **SLA CVaR 退化条件明确**：全堆 hub + 空路径 → CVaR=0；需配合虚拟源/stress/min_off_hub
5. **Physical vs SLA 结论**：Physical CVaR 检测到资源拥塞（玩具上 CVaR=70），而 SLA CVaR 在退化条件下为 0——说明两套度量回答不同问题

---

## 九、当前不足与待解决问题

### 🔴 结构性不足

1. **Path-based 扩展性瓶颈（最核心）**
   - K 短路预计算，大网（>100 节点）路径数指数爆炸
   - AEGIS 已证明 Flow-based 快 5500 倍
   - 论文初稿列为"未来工作"，但尚未开始设计 Flow-based 版本
   - 影响：无法在 ATT(25节点)/XNet(28节点) 上跑完整管线

2. **Hub 径向简化未泛化**
   - `teavar_flow_anchors()` 返回全局单对锚点 `(h,h)` 或 `(V_s,V_t)`
   - 真正的一般形式应为 per-task 的 `(s_i, t_i)`
   - `b4_joint_data` 从 demand 读出的 `(hub, dst)` 目前只用于标定业务量，没有用作路由端点
   - 论文中已写标准形式 `s_i→m→t_i`，但代码与论文不一致

3. **场景建模过粗**
   - 主实验仅 3 个离散场景，缺乏细粒度故障概率分布
   - TEAVAR 原始用 Weibull 生成更多场景（仅在 `--mode teavar` 中使用）
   - 场景聚类原型已写但未集成到主管线

### 🟡 工程性不足

4. **自适应 McCormick 未调优**
   - 原型在 `progressive_pipeline.py` 中，目标将 Model D CVaR 偏差从 210% 降到 <20%
   - 当前 slack_max 保守（~80），实际 slack ~0-5

5. **大规模实验缺失**
   - 9 个拓扑的完整对比表未产出
   - 仅 B4 + 玩具网有完整实验结果
   - 多拓扑下的 cost–risk Pareto 前沿未绘制

6. **论文与代码不一致处**
   - `建模公式说明.md` 写的是标准 `s_i→m→t_i`，代码是 hub 径向
   - `论文初稿.md` 费用公式用 `|p|`（hop 数），新版代码已改为 `τ_p`（链路价和）
   - `项目总结_模型AC.md` 开头声明"上一版没写全"，两版文档并存

7. **数据质量**
   - XNet 缺 prob_failure 列
   - Nextgen demand.txt 为空（用 gravity model 合成）
   - 多处自动生成覆盖了手工文件

8. **无单元测试、无 CI**

---

## 十、我的目标与优先级倾向

我接下来想做的是（请 Claude 帮我细化规划）：

1. **短期（论文着急）**：在 B4 + 多拓扑上产出完整的实验数据（Model A/C 主表 + Physical 对照表 + UMCF/虚拟源消融）
2. **中期（方法论完善）**：将一般化 `s_i→m→t_i` 实现，使代码与论文公式一致
3. **长期（突破扩展性）**：设计 Flow-based MILP 版本（对齐 AEGIS 思路），突破 path-based 瓶颈

请 Claude 基于以上现状，帮我：
- 规划具体的下一步实现顺序和里程碑
- 识别哪些是低投入高回报的"速赢"项
- 评估从 path-based 迁移到 flow-based 的工作量和风险
- 给出论文实验章节的推荐结构
