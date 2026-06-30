# MODEL AUDIT

> 最后更新：2026-06-30（Phase 5 — 对齐到 src 主线）

---

## 1. 当前主线代码地图

| 模块 | 路径 | 状态 |
|:--|:--|:--|
| M0 | `src/teavar_e2e/models/m0_models.py` | import OK |
| M1 | `src/teavar_e2e/models/m1_models.py` | import OK |
| M2 | `src/teavar_e2e/models/m2_models.py` | import OK |
| M2-C-Cost | `src/teavar_e2e/models/m2_cost_models.py` | build + solve OK |
| M2-C-Cost (alt) | `src/teavar_e2e/models/m2_c_cost_models.py` | 变体，import OK |
| Toy-2Task | `src/teavar_e2e/data/toy_two_task_independent_data.py` | build OK |
| ToyTE | `src/teavar_e2e/data/toy_te_data.py` | build OK, 537/537 |
| Runner (single) | `src/teavar_e2e/experiments/run_e2e_mainline.py` | OPTIMAL on smoke |
| Runner (frontier) | `src/teavar_e2e/experiments/run_m2_gamma_frontier.py` | OPTIMAL on smoke |
| CVaR helpers | `src/teavar_e2e/models/m2_cost_helpers.py` | 被 M2-C-Cost 调用 |
| Flow anchors | `src/teavar_e2e/utils.py` | 无 legacy 依赖 |

---

## 2. 主线 vs Legacy

| 位置 | 状态 |
|:--|:--|
| `src/teavar_e2e/` | ★ 当前默认主线 |
| `refactor/` | 开发快照（Phase 3 复制后保留） |
| `legacy/duibi_p0_model_ac/` | 旧 P0/Model A/C（不再扩展） |
| `legacy/teavar_original/` | 旧 TEAVAR 复现 |
| `legacy/copo_drafts/` | Copo 早期草稿 |
| `legacy/l2_bilevel/` | L2 双层模型 |
| `legacy/monetary_cvar/` | 货币化 CVaR 探索 |
| `legacy/experiment_scripts/` | 旧 P0/B4/ablation 脚本 |
| `archive/` | 历史文档/产物 |
| 根目录 `*_models.py` 等 | 兼容 shim（→ `src/teavar_e2e/`） |

---

## 3. 核心约束确认

| 特性 | 状态 | 位置 |
|:--|:--|:--|
| 唯一放置 (∑ y=1) | ✅ | M0→M2 |
| 计划流量守恒 (=) | ✅ | M0 |
| 场景流量守恒 (=) | ✅ | M1→M2 |
| 名义链路容量 (≤ B_e) | ✅ | M0 |
| 场景链路容量 (≤ B_e·σ) | ✅ | M1→M2 |
| 名义节点容量 (≤ C_normal) | ✅ | M0 |
| 场景节点容量 (≤ C_s) | ✅ | M1→M2 |
| 服务比例 r ≤ y | ✅ | M1→M2 |
| z = Σ r | ✅ | M1→M2 |
| z[i,s0]=1 | ✅ | M2-C-Cost |
| E[z] ≥ ρ | ✅ | M2-C-Cost |
| CVaR ≤ γ | ✅ | M2-C / M2-C-Cost |
| Placement cost c_p | ✅ | M2-C-Cost |
| Bandwidth cost c_b | ✅ | M2-C-Cost |
| Cost objective | ✅ | M2-C-Cost |
| E2E CVaR (single) | ✅ | M2-C-Cost |
| Link + Node CVaR (dual) | ❌ (intentional) | legacy only |

---

## 4. 端到端 CVaR 定义

本项目采用**单一 L^{E2E} CVaR**：

$$
L_s^{E2E} = \sum_i \omega_i (1 - z_{i,s}), \qquad
\mathrm{CVaR}_\beta = \eta + \frac{1}{1-\beta}\sum_s \pi_s u_s
$$

链路/算力故障通过场景容量约束影响 z_{i,s}，不另建 link CVaR + node CVaR。

---

## 5. 待审计项

- exact M2-C-Cost exported API names（`build_m2_c_cost_model` / `solve_m2_c_cost` / `solve_m2_lex3`）
- aggregate worst-case pruning 测试
- avg vs fair loss mode 对比测试
- B4 大规模拓扑集成测试
- reserved recovery 变体验证
