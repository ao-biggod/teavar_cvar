# TEAVAR_python

本仓库包含 **TEAVAR 论文 WAN 风险模型复现**（隧道分流 + CVaR）、**算力–网络联合放置的对比 MILP**（`duibi` / `cvar_compare`）、以及 **`data/B4` 数据集上的 joint 入口**（`main.py --mode joint`）。优化器为 **Gurobi**。

详细数学定义见独立文档：**[建模公式说明.md](./建模公式说明.md)**。

---

## 环境依赖

| 组件 | 用途 |
|------|------|
| Python 3.x | 运行脚本 |
| `gurobipy` + Gurobi 许可证 | 全部 MILP |
| `numpy` | 数据读取、矩阵 |
| `scipy` | `util.py`（仅 `--mode teavar` 经 `main` 导入时） |
| `networkx` | `parsers.get_tunnels`（仅论文 TEAVAR 路径需 K 短路） |

`--mode joint` 与 `cvar_compare` / `duibi` 可在未安装 `scipy` / `networkx` 时运行（`parsers` 中 `networkx` 为延迟导入）。

---

## 目录结构（核心）

```
├── main.py              # 统一入口：teavar（论文） / joint（B4 + 新 CVaR）
├── TEAVAR_Gurobi.py     # TEAVAR 隧道分流 MILP
├── parsers.py           # 拓扑、需求、tunnels
├── util.py              # Weibull 链路故障、子场景
├── duibi.py             # 玩具数据 + 单层 CVaR / KKT / ε-约束 / Copo 风格模型
├── duibi_metrics.py     # 解后指标（利用率、送达、SLA 损失等）
├── cvar_compare.py      # physical vs teavar_sla 并排 + build_teavar_sla_cvar_model + 虚拟接入瓶颈
├── teavar_framework_models.py  # TEAVAR 视角 SLA CVaR 与 duibi 式 A–D 对齐
├── b4_joint_data.py     # B4 → 与 duibi 同构的数据对象 load_b4_joint_data
├── data/B4/             # 拓扑、需求、paths、node_compute_resources.csv
└── 建模公式说明.md      # 各函数对应公式（主文档外单开）
```

其余如 `copo_CVaR.py`、`huatu.py`、`teavar_cete*.py` 等为扩展/实验脚本，入口以各自文件为准。

---

## 运行方式

### 1. 论文式 TEAVAR（B4 隧道 + 链路场景）

```bash
python main.py --mode teavar --topology B4
```

依赖 `scipy` 与 `networkx`（用于 `get_tunnels`）。场景概率由 `util.weibull_probs` / `sub_scenarios` 生成，**不读取** `topology.txt` 中的 `prob_failure` 列（该列供文档或其它脚本）。

### 2. B4 + 联合放置 + CVaR（新算法 + 新数据）

```bash
python main.py --mode joint --topology B4
```

常用参数：`--hub`、`--joint-num-tasks`、`--joint-demand-row`、`--joint-k-paths`（默认 **4**，便于 B4 绕路）、`--joint-demand-scale`（默认 1，**>1 放大流量加压链路**）、`--joint-lambdas`、`--joint-omega`、`--joint-lambda-node`（**调大**可强迫 teavar 为压低算力 CVaR 而迁移）、`--joint-lambda-compute-sf`、`--joint-min-off-hub`、`--joint-stress-zero-s1` 等（见 `main.py` 与 `data/B4/DATASET_NOTES.txt`）。

**UMCF 显式虚拟源/汇**：`python main.py --mode joint --joint-umcf-teavar` 时，`load_b4_joint_data` 增加 \(V_s,V_t\) 及 \((V_s,m)\)、\((m,V_t)\) 写入 `E,B,sigma`；`build_teavar_sla_cvar_model` 与 **`duibi` / `teavar_framework_models`（A–D）** 的流锚点均经 `teavar_flow_anchors(data)` 与图一致（关闭 UMCF 时为 hub 径向）。可选 `--joint-umcf-sigma`、`--joint-umcf-sink-sigma`。与 `--joint-virtual-source` 同时开时 **以 UMCF 为准**（不再写 `sigma_vs` 瓶颈字典）。

**虚拟源接入（缓解「全堆在 hub 时空路径、SLA CVaR 退化」）**：加 `--joint-virtual-source` 后，`load_b4_joint_data` 会写入 `sigma_vs` / `sigma_vt`（默认可用率 **0.99**），`build_teavar_sla_cvar_model` 等对聚合送达量 `R_in`、`R_out` 施加串联上界（见 `建模公式说明.md` **§6.6**；**非** UMCF 显式虚拟节点图扩展，与严格多入口 UMCF 的对照见 **§6.6 末段与 §6.7**）。可选 `--joint-virtual-sigma`、`--joint-virtual-sink-sigma`（未指定时与前者相同）。

**若 physical 随 λ 变化而 teavar_sla 行不变**：多为 SLA CVaR 与放置在该 λ 扫描下退化；可依次尝试 `--joint-lambda-node 10` 或 `50`、`--joint-k-paths 6`、`--joint-demand-scale 2`、`--joint-lambda-compute-sf 0.3`，或 `--joint-min-off-hub` / `--joint-stress-zero-s1` 打破对称最优。

**`--joint-stress-zero-s1` 且未开 UMCF**：`build_single_layer_model`（physical）与 `build_teavar_sla_cvar_model`（teavar_sla）**约束与目标不同**，可行域不必一致（可出现 physical 不可行而 teavar_sla 仍可解）。与审稿人强调的「同一扩展图上的公平应力对照」请以 **`duibi.py` 的 Model A–D** 或 **同时 `--joint-umcf-teavar`** 为准。

### 3. 玩具数据上对比 physical 与 teavar_sla

```bash
python cvar_compare.py --lambdas "0.5,5,50" --lambda-node 0 --lambda-compute-sf 0.3
```

### 4. 玩具算例单独跑 duibi 内模型

```bash
python duibi.py
```

B4 默认：`python duibi.py`（可加 `--k-paths`、`--hub`、`--stress-zero-s1` 等）。**虚拟源**：`--virtual-source`，可选 `--virtual-sigma`、`--virtual-sink-sigma`；`--toy` 时同样生效。**UMCF**：`--umcf-teavar` 时 `load_b4_joint_data` / 玩具 `attach_umcf_to_data_object` 扩展图，**Model A–D 与链路指标**与 TEAVAR 侧共用同一锚点语义；可选 `--umcf-sigma`、`--umcf-sink-sigma`（与 `main.py --joint-umcf-teavar` 同源字段）。

（以 `duibi.py` 中 `__main__` 为准。）

---

## 模型关系简述

- **TEAVAR_Gurobi.TEAVAR**：在离散链路场景下为每条 flow 分配隧道流量，损失为 **未满足需求比例**，目标为 **VaR + 尾部加权**（见公式文档）。
- **duibi.build_single_layer_model（physical）**：任务放置 + 与 TEAVAR 一致的 **流锚点** `teavar_flow_anchors`（hub 或 UMCF 的 \(V_s,V_t\)），**算力 + 链路利用率 CVaR**；Model B/C/D 同步。
- **cvar_compare.build_teavar_sla_cvar_model（teavar_sla）**：同一数据接口下 **SLA 型需求未满足 CVaR**（与带宽 TEAVAR 叙事对齐），可选 **算力利用率 CVaR**、**算力未满足（超额）CVaR**。
- **b4_joint_data**：将 B4 拓扑、`demand.txt`、`node_compute_resources.csv` 转为上述 MILP 所需字段（hub 径向、K 短路、离散场景 σ/C_s）；可选 `sigma_vs`/`sigma_vt` 瓶颈，或 **`umcf_virtual_nodes`** 显式 \(V_s,V_t\) 边（`--joint-umcf-teavar` / `duibi.py --umcf-teavar`）。
- **duibi_metrics**：解后指标中 TEAVAR 流锚点由 **`teavar_flow_anchors(data)`** 给出（hub 径向或 UMCF 的 \(V_s,V_t\)）；`duibi` 物理模型仍用 `data.hub`。

---

## 引用与论文

TEAVAR 原始论文见仓库内 PDF（如 `3341302.3342069.pdf`）。本仓库实现与论文/Julia 参考在数值上可对齐 `parsers` 中的缩放约定。

---

## 许可证

Gurobi 使用需遵守 **Gurobi 许可协议**；学术许可仅限非商业用途。




### 七、`b4_joint_data.load_b4_joint_data`

**语义（数据对象 `data` 携带的量）**：

- **Hub**：物理入口节点 $h\in\mathcal{M}$。
- **任务需求**：每个任务 $i$ 的 $(b^{in}_i,\,b^{out}_i)$ 来自 `demand.txt` 中第 $h$ 行出向 OD 的 Top 若干条（缩放规则同 `parsers.read_demand`），再乘 **`demand_scale`**（默认 $1$；$>1$ 表示整体加压）。
- **资源与拓扑**：$(w_{ik},\,\pi_{mk},\,C^{norm}_{mk},\,C^N_{mks},\,B_e,\,\sigma_{es})$ 来自拓扑与 `node_compute_resources.csv`（与场景 $s$ 有关的量带下标 $s$）。
- **候选路径族**：$P_{uv}\subseteq$「$u\!\to\!v$ 至多 $K$ 条最短简单路径」（边序列），供路径变量索引。

**场景约定**：

$$
s=0:\ \text{全通};\qquad
s=1:\ \text{可切断高 \texttt{prob\_failure} 边};\qquad
s=2:\ \text{可缩小聚合层 }C^N_{mks}\ \text{（与数据文件一致）}.
$$

**虚拟接入（第 6.6 节）**：`virtual_source=True` 时为每个 $(m,s)$ 写入 $\sigma^{vs}_{m,s}$（默认 $0.99$）及对称 $\sigma^{vt}_{m,s}$（`virtual_sink_sigma` 缺省则与源相同）。

**UMCF（第 6.7 节）**：`umcf_virtual_nodes=True` 时写入 `umcf_vs,umcf_vt` 并扩展 $E,B,\sigma,\texttt{P\_cand}$；**`duibi` physical、`teavar_sla`、`teavar_framework_models` 与 joint 并排**共用该图实例。若与 `virtual_source` 同时打开，**以 UMCF 为准**（不再写 `sigma_vs` 字典）。

---

### 八、`duibi_metrics` 解后指标（非优化，公式）

| 函数 | 公式含义 |
|------|----------|
| `path_up` | 路径上所有边 $\sigma_{es}>0$。 |
| `max_link_util_after_solve` | 名义场景 $s=0$：$\max_e \mathrm{flow}_e/(B_e)$。 |
| `max_node_util_after_solve` | $s=0$：$\max_{m,k} \sum_i w_{ik} y_{im}/C^{norm}_{mk}$。 |
| `worst_max_link_util_across_scenarios` | $\max_s \max_e \mathrm{flow}_e/(B_e\sigma_{es})$。 |
| `worst_max_node_util_across_scenarios` | $\max_s \max_{m,k} \sum_i w_{ik} y_{im}/C^N_{mks}$。 |
| `expected_delivery_ratio` | 各任务在放置节点上 $(x^{in}\!/b^{in}+x^{out}\!/b^{out})/2$ 的平均。 |
| `expected_total_delivered_volume` | $\sum_s \pi_s\sum_{i,m,p} d^{in}_{i,m,p,s}+\cdots$（路径求和与 `teavar_flow_anchors(data)` 给出的 $(u,v)$ 下 $P_{uv}$ 一致） |
| `sla_per_scenario_max_demand_loss` | $L_s=\max_i \max\{1-R^{in}_{is}/b^{in}_i,\,1-R^{out}_{is}/b^{out}_i\}$。 |

以下为与上表**同义**的块公式（便于对照代码中的 `flow_e`、`y` 等变量）：

$$
\begin{aligned}
\texttt{max\_link\_util\_after\_solve} &: \quad U^{\mathrm{link}}_0 = \max_{e\in E}\frac{\mathrm{flow}_e}{B_e} \quad (s=0),\\[4pt]
\texttt{max\_node\_util\_after\_solve} &: \quad U^{\mathrm{node}}_0 = \max_{m,k}\frac{\sum_i w_{ik}\,y_{im}}{C^{norm}_{mk}} \quad (s=0),\\[4pt]
\texttt{worst\_max\_link\_util\_across\_scenarios} &: \quad \max_{s}\max_{e\in E}\frac{\mathrm{flow}_e(x,s)}{B_e\,\sigma_{es}},\\[4pt]
\texttt{worst\_max\_node\_util\_across\_scenarios} &: \quad \max_{s}\max_{m,k}\frac{\sum_i w_{ik}\,y_{im}}{C^N_{mks}},\\[4pt]
\texttt{expected\_total\_delivered\_volume} &: \quad \sum_{s}\pi_s\Bigl(\sum_{i,m,p} d^{in}_{i,m,p,s}+\sum_{i,m,q} d^{out}_{i,m,q,s}\Bigr).
\end{aligned}
$$

**实现注**：涉及 $P_{uv}$ 的送达与链路流量指标均以 **`teavar_flow_anchors(data)`** 为 $(u,v)$ 锚点（hub 径向或 UMCF 的 $V_s,V_t$）。**放置**、`min_off_hub`、**应力**（切断 hub 出边）仍用物理 **`data.hub`**；二者分工与 README「模型关系」一致。

---

### 九、`parsers` / `util`（数据与场景，非单一 MILP）

- **`read_topology`**：容量 $\mathrm{cap}=\mathrm{raw}/1000/\text{downscale}$（与 Julia 对齐）。
- **`read_demand`**：$d=\mathrm{raw}/(\text{downscale}\cdot 1000)\cdot \text{scale}$。
- **`util.weibull_probs` / `sub_scenarios`**：生成链路故障率与子场景概率 $\pi_s$，供 `TEAVAR` 使用。

---

### 十、其它脚本（索引）

- `copo_CVaR.py`、`copo_cvar01.py`、`teavar_cete.py` 等：独立实验/变体，公式以各自文件内注释为准。
- `huatu.py`：批量调用 `main` 并绘图。

---

### 十一、`teavar_framework_models`（TEAVAR 视角与 duibi 四架构对齐）

**结构**：与 `duibi.py` 中 A–D 平行——**横轴**为 SLA 需求损失 CVaR（及可选算力未满足 CVaR）；**纵轴**为加权 / KKT / $\varepsilon$-约束 / McCormick。

**流锚点**（与 `cvar_compare.build_teavar_sla_cvar_model` 一致）：由 **`teavar_flow_anchors(data)`** 得到 $(s_{\mathrm{src}},s_{\mathrm{dst}})$。

- 未开 UMCF：hub $h$ 径向，候选路径族 $P_{h,m},\,P_{m,h}$（代码里 $h=\texttt{getattr(data,'hub',0)}$）。
- 开 UMCF：候选为 $P_{V_s,m},\,P_{m,V_t}$。

在 `del` 与物理链路耦合之后，**Model B/C/D** 调用 `cvar_compare.add_teavar_virtual_bottleneck_constraints`（当 `data.sigma_vs` 非空且**未**做 UMCF 图扩展时），与第 6.6 节一致；**Model A** 委托 `build_teavar_sla_cvar_model`（支持 `data.umcf_virtual_nodes`，见第 6.7 节）。**放置**仍用物理 hub $h$。

**共通标量**（与实现字段同名）：

$$
\begin{aligned}
\mathbb{E}[\mathrm{Del}] &= \sum_{s}\pi_s\sum_{i,m,p} d^{in}_{i,m,p,s}+\sum_{s}\pi_s\sum_{i,m,q} d^{out}_{i,m,q,s},\\[4pt]
c_{\mathrm{total}} &= c_p + c_b - \omega\,\mathbb{E}[\mathrm{Del}].
\end{aligned}
$$

**SLA 尾部（Rockafellar–Uryasev）**：引入 $(\zeta,u_s)$，对每个任务 $i$、场景 $s$：

$$
\begin{aligned}
u_s\,b^{in}_i &\ge b^{in}_i - R^{in}_{is} - b^{in}_i\,\zeta,\\
u_s\,b^{out}_i &\ge b^{out}_i - R^{out}_{is} - b^{out}_i\,\zeta .
\end{aligned}
$$

$$
\mathrm{CVaR}^{\mathrm{SLA}}=\zeta+\frac{1}{1-\beta}\sum_{s}\pi_s\,u_s .
$$

**算力未满足尾部（可选，与第 6.4 节同构）**：

$$
\begin{aligned}
D_{mk} &= \sum_i w_{ik}\,y_{im},\\
e_{mks} &= \max\{0,\,D_{mk}-C^N_{mks}\},\\
L^{\mathrm{sf}}_s &= \max_{m,k}\frac{e_{mks}}{D_{\mathrm{ref}}},\\
\phi_s &\ge L^{\mathrm{sf}}_s-\zeta_{\mathrm{sf}},\qquad
\mathrm{CVaR}^{\mathrm{sf}}=\zeta_{\mathrm{sf}}+\frac{1}{1-\beta_{\mathrm{sf}}}\sum_{s}\pi_s\,\phi_s .
\end{aligned}
$$

| 模型 | 目标 / 约束 | 实现函数 |
|------|----------------|----------|
| **A** 单层加权 | $\min\, c_{total}+\lambda_{sla}\mathrm{CVaR}^{SLA}+\lambda_{sf}\mathrm{CVaR}^{sf}$（$\lambda_{sf}=0$ 时不建 sf 块） | `build_teavar_model_a` → 委托 `cvar_compare.build_teavar_sla_cvar_model`（`lambda_node=0`） |
| **B** KKT | 与 A 同目标；对 SLA 的每条 $(s,i)$ 探测行加 $\mathrm{slack}^{SLA}$ 与对偶 $\alpha$ 的 **Indicator** 互补；若 $\lambda_{sf}>0$ 且 `kkt_sf=True`，对 $\phi$ 层 $(s,m,k)$ 再加一套 KKT Indicator | `build_teavar_model_b` |
| **C** ε-约束 | $\min\, c_{total}$ s.t. $\mathrm{CVaR}^{SLA}\le\Gamma_{sla}$，（可选）$\mathrm{CVaR}^{sf}\le\Gamma_{sf}$ | `build_teavar_model_c` |
| **D** McCormick | $\min\, c_{total}$；用线性包络 $\frac{\alpha}{\alpha_{max}}+\frac{\mathrm{slack}}{\mathrm{slack}_{max}}\le 1$ 松弛 SLA 与 sf 的互补（与 `duibi.build_copo_mccormick_model` 同构思想） | `build_teavar_model_d` |

**说明**：Model D 事后在解上读取的 $\mathrm{CVaR}^{SLA},\mathrm{CVaR}^{sf}$ 与 Model A 最优 CVaR **不必同界**（松弛松），与 physical 的 Model D 相同 phenomenon。

---

若某函数在仓库中增删，请同步更新本文件对应小节。

