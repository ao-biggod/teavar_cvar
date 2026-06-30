# TEAVAR-E2E: Risk-Aware End-to-End Traffic Engineering with Compute Placement

> 项目代号：TEAVAR-E2E
> 最后更新：2026-06-30

---

## 1. 当前主线

**TEAVAR-E2E**：故障不确定下的端到端多路径流量工程与计算资源联合优化。

按复杂度递进：

| 模型 | 解决的问题 | 当前状态 |
|:--|:--|:--|
| **M0** | 确定性多路径放置与负载均衡诊断 | ✅ 实现 + 验证 |
| **M1** | 故障场景 adaptive recourse（固定 placement） | ✅ 实现 |
| **M2-Service / M2-Lex** | 端到端服务损失 CVaR 优化 | ✅ 实现 |
| **M2-C-Cost** | minimize 放置成本 + 期望带宽成本，s.t. E2E CVaR ≤ γ | ✅ 实现 + smoke 验证 |

推荐实验入口：

```bash
# 单次 M2-C-Cost
PYTHONPATH=src python -m teavar_e2e.experiments.run_e2e_mainline \
    --beta 0.95 --gamma 0.5 --max-failed-components 2

# Gamma 前沿扫描
PYTHONPATH=src python -m teavar_e2e.experiments.run_m2_gamma_frontier \
    --beta 0.95 --gamma-list 0.2,0.4,0.6,0.8,1.0 --max-failed-components 2
```

---

## 2. 核心建模思路

### 2.1 两段式端到端服务

```
source s_i  →  多路径 ingress  →  execution node m  →  多路径 egress  →  destination d_i
```

每个任务选择候选计算节点和多条 ingress/egress 路径。

### 2.2 端到端单一风险度量

所有故障的影响统一反映在场景服务比例 z_{i,s} 中：

- 链路故障 → 数据到不了 → z_{i,s} 下降
- 算力故障 / 容量下降 → 处理不了 → z_{i,s} 下降
- 两者同时发生 → 自然交叉效应

端到端损失 L_s^{E2E} 从 z_{i,s} 推导，做单一 CVaR 度量，**不是 link CVaR + node CVaR 双风险模型**。

### 2.3 M2-C-Cost 目标

$$
\min \; c_p(y) + \sum_{s} \pi_s \, c_b(x_s)
$$

$$
\text{s.t.} \quad \mathrm{CVaR}_\beta(L^{E2E}) \le \gamma, \quad z_{i,s_0}=1, \quad \mathbb{E}[z_i] \ge \rho_i
$$

Copo 的成本框架 + AEGIS-A 的风险约束 + 本项目 E2E two-stage flow 结构。

---

## 3. 与相关工作的关系

| 工作 | 核心贡献 | 区别 |
|:--|:--|:--|
| **TEAVAR** | 隧道分流 CVaR | 纯路由，无计算放置 |
| **AEGIS** | CVaR 约束的弹性路由 | 纯路由，无计算放置 |
| **Copo** | 放置成本 + 带宽成本联合优化 | 确定性模型，无故障场景 / CVaR |
| **本项目** | 计算放置 + 两段多路径 + 场景 recourse + E2E CVaR + cost 目标 | — |

---

## 4. 仓库状态

```
src/teavar_e2e/          ← 当前主线（Phase 3+）
  data/                  ← 多路径玩具数据集（ToyTE, Toy-2Task）
  models/                ← M0 / M1 / M2 / M2-C-Cost
  risk/                  ← 故障场景生成
  experiments/           ← run_e2e_mainline, run_m2_gamma_frontier
refactor/                ← 开发快照
legacy/                  ← 历史 baseline（P0/Model A/C, duibi, TEAVAR 复现）
archive/                 ← 历史文档/产物
model_ac_component_risk_release/  ← 独立发布版（不跟踪）
new_results/e2e_mainline/         ← 本地输出（gitignore）
```

---

## 5. 当前验证结果

| 测试 | Phase | 结果 |
|:--|:--|:--|
| ToyTE 数据验证 | 3 | ✅ 537/537 |
| Toy-2Task 数据构建 | 3 | ✅ \|J\|=2, \|S\|=24–277 |
| M2-C-Cost 模型构建 | 3 | ✅ 8870 vars, 13575 constrs |
| run_e2e_mainline (γ=1.0) | 4 | ✅ OPTIMAL, obj=67.2 |
| run_m2_gamma_frontier (γ=0.5,1.0) | 4 | ✅ both OPTIMAL |
| 全 smoke test (import + build + solve) | 3.5 | ✅ |

---

## 6. 已知限制与后续工作

- gamma=0.2 on larger Toy-2Task settings may be infeasible — 参数密度/容量问题，非代码 bug。
- aggregate worst-case scenario pruning 需要最终比较。
- fair loss mode (max per-flow) 需要实验对照。
- B4/ATT/Abilene scaling 未接入 src 主线。
- reserved recovery 变体未实现。
- 论文完整图表/表格未生成。
