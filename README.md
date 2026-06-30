# TEAVAR-E2E: Risk-Aware End-to-End Traffic Engineering with Compute Placement

**端到端多路径流量工程与计算资源联合优化** — 在故障不确定环境下，联合优化任务放置、多路径路由、场景化服务比例和端到端风险约束。

优化器：**Gurobi**（Academic license）

---

## 当前主线模型

本项目将业务任务建模为 `source → compute node → destination` 的两段式服务过程。按复杂度递进：

| 模型 | 解决的问题 | 关键约束 | CVaR |
|:--|:--|:--|:--|
| **M0** | 确定性放置与负载均衡诊断 | 名义链路/节点容量硬约束，$U^{max}_{link},U^{max}_{node}\le 1$ | 无 |
| **M1** | 故障场景 adaptive recourse | 场景链路容量 $B_e\sigma_{e,s}$，场景算力容量 $C_{m,s}^{(k)}$，服务比例 $r_{i,m,s},z_{i,s}$ | 无 |
| **M2-Service** | 端到端服务损失 CVaR | 继承 M1 + $\mathrm{CVaR}_\alpha(L^{E2E})$ | 有 |
| **M2-C-Cost** | 成本最小化 + CVaR 约束 | $\min\; c_p + \mathbb{E}[c_b(x_s)]$ s.t. $\mathrm{CVaR}_\alpha(L^{E2E})\le\gamma$ | 有（约束） |

**核心公式**（M2-C-Cost）：

端到端损失（加权未满足服务率）：

$$L_s^{E2E} = \sum_{i\in\mathcal{I}} \omega_i (1 - z_{i,s}), \qquad z_{i,s} = \sum_{m} r_{i,m,s}$$

CVaR 线性化（Rockafellar–Uryasev）：

$$\mathrm{CVaR}_\alpha(L^{E2E}) = \eta + \frac{1}{1-\alpha}\sum_{s\in\mathcal{S}} \pi_s u_s, \quad u_s \ge L_s^{E2E} - \eta, \quad u_s \ge 0$$

链路容量与算力容量（M1/M2 场景硬约束）：

$$\mathrm{LinkLoad}_{e,s} \le B_e \cdot \sigma_{e,s}, \qquad \sum_i r_{i,m,s} \cdot w_i^{(k)} \le C_{m,s}^{(k)}$$

成本目标（M2-C-Cost）：

$$c_p = \sum_{i,m} y_{i,m} \sum_k w_i^{(k)} \rho_{m,k}, \qquad \mathbb{E}[c_b] = \sum_s \pi_s \sum_e \rho^{\text{link}}_e \cdot \mathrm{LinkLoad}_{e,s}$$

---

## 与相关工作的关系

本项目参考 **TEAVAR**（隧道分流 CVaR）、**AEGIS**（AEGIS-A：min 资源使用量 s.t. CVaR ≤ λ）和 **Copo**（min 计算成本 + 链路传输成本）的思想，
但区别在于：

- 不是纯网络路由（TEAVAR / AEGIS 无计算放置）
- 不是单纯任务放置（Copo 无故障场景、无 CVaR、无 stochastic recourse）
- 将**计算放置、两段式多路径路由和端到端风险度量统一建模**，链路故障与算力故障通过场景 recourse 在同一个 $L^{E2E}$ 中自然交叉

详见 **[docs/related_work.md](docs/related_work.md)**。

---

## Repository Layout

```
├── README.md                        ← 当前文件
├── PROJECT_SUMMARY.md               ← 项目参考论文与符号体系
├── MODEL_AUDIT.md                   ← 模型审计记录
│
├── src/teavar_e2e/                  ← ★ 当前主线代码
│   ├── data/                        ← 多路径玩具数据集
│   ├── models/                      ← M0 / M1 / M2 / M2-C-Cost
│   ├── risk/                        ← CVaR + 场景 pruning
│   └── experiments/                 ← 主线实验入口
│
├── docs/                            ← 主线文档
│   ├── MAINLINE_STATUS.md           ← 三条线状态说明
│   ├── REPOSITORY_MAP.md            ← 文件分类地图
│   ├── modeling.md                  ← 完整建模公式（M0→M2）
│   ├── related_work.md              ← 与 TEAVAR/AEGIS/Copo 的关系
│   └── toy_dataset_design.md        ← 玩具数据集设计
│
├── tests/                           ← 主线测试
├── data/                            ← 多拓扑实验数据（B4/ATT/Abilene/…）
│
├── legacy/                          ← 历史参考代码（非主线）
│   ├── teavar_original/             ← 旧 TEAVAR WAN 隧道复现
│   ├── duibi_p0_model_ac/           ← Model A/C + physical CVaR 对比 + B4 joint
│   ├── copo_drafts/                 ← Copo 草稿
│   ├── l2_bilevel/                  ← L2 双层模型
│   ├── monetary_cvar/               ← 货币化 CVaR 草稿
│   └── experiment_scripts/          ← 旧 P0/B4/ablation 实验脚本
│
└── archive/                         ← 历史产物（不再活跃）
    ├── old_chinese_docs/             ← 旧中文文档与 PDF
    ├── old_figures/                  ← 旧图表
    └── old_results/                  ← 旧实验结果
```

---

## Quick Start

```bash
# 依赖
pip install gurobipy numpy networkx

# 运行 M2-C-Cost smoke test（需要 Gurobi Academic license）
PYTHONPATH=src python -m teavar_e2e.experiments.run_m2_toy \
    --beta 0.95 --gamma 0.2 --max-failed-components 2

# 运行主线 smoke tests
PYTHONPATH=src python -m pytest tests/test_e2e_mainline_smoke.py -v
```

详细运行说明和旧实验复现见 `legacy/experiment_scripts/`（历史参考）。

---

## 许可证

Gurobi 使用需遵守 **Gurobi 许可协议**；学术许可仅限非商业用途。
