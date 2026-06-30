# TEAVAR-E2E 主线状态说明

> 最后更新：2026-06-30

---

## 三条开发线

### 1. 当前主线：M0 → M1 → M2（推荐）

| 文件位置 | 状态 |
|:--|:--|
| 建模文档 | `docs/m0_m1_m2_建模说明.md`（定稿 v2） |
| M0 代码 | `refactor/m0_models.py`（可用，待提升到 `src/teavar_e2e/`） |
| M1 代码 | `refactor/m1_models.py`（可用，待提升） |
| M2 代码 | `refactor/m2_models.py` + `refactor/m2_cost_models.py`（可用，待提升） |
| M2 helpers | `refactor/m2_cost_helpers.py`（CVaR RU 线性化 + E2E loss + 成本计算） |
| 玩具数据 | `toy_te_data.py`（ToyTE 11 节点多路径）、`toy_two_task_independent_data.py`（独立组件故障）、`refactor/toy_instances_v2.py`（Toy-Mesh 7 节点） |

**M0**：确定性多路径放置与负载均衡诊断（名义硬容量，无场景，无 CVaR）
**M1**：故障场景 adaptive recourse（$r_{i,m,s}, z_{i,s}$，场景链路/算力容量硬约束）
**M2-Service/M2-Lex**：端到端服务损失 CVaR 优化/分层
**M2-C-Cost**：$\min c_p + \mathbb{E}[c_b]$ s.t. $\mathrm{CVaR}_\alpha(L^{E2E})\le\gamma$


### 2. 旧 P0 / Model A/C 主链（仍可用，不再扩展）

| 文件位置 | 状态 |
|:--|:--|
| 建模文档 | `docs/model_ac_建模说明.md`（降为历史参考） |
| 代码 | `teavar_framework_models.py`, `cvar_compare.py`, `b4_joint_data.py`, `toy_instances.py` 等 |
| 实验 | `run_gamma_frontier.py`, `run_p0_sweep.py` 等 |

Model A/C 使用 **SLA CVaR + SF CVaR 双项并列**（非统一 $L^{E2E}$），
玩具 `toy_instances.py` 为**单路径**星型拓扑。作为历史对比 baseline 保留，不再继续扩展。
Phase 2 后将移入 `legacy/duibi_p0_model_ac/`。


### 3. 旧 duibi / physical 模型（仍可用，不再扩展）

| 文件位置 | 状态 |
|:--|:--|
| 代码 | `duibi.py`, `duibi_metrics.py` |

使用**链路利用率 CVaR + 节点利用率 CVaR** 并列，与 TEAVAR 侧形成"physical vs SLA"对比。
Phase 2 后将随 Model A/C 一并移入 `legacy/duibi_p0_model_ac/`。

---

## 已废弃 / 不再维护

- `copo_CVaR.py`, `teavar_cete.py` 等 Copo 草稿（→ `legacy/copo_drafts/`）
- `bilevel_teavar_models.py`, `l2_full_models.py`（L2 双层，→ `legacy/l2_bilevel/`）
- `model_m_monetary_cvar.py`（货币化 CVaR 草稿，→ `legacy/monetary_cvar/`）
- 旧 `TEAVAR_Gurobi.py`, `main.py` 等 TEAVAR WAN 复现（→ `legacy/teavar_original/`）

---

## 迁移路线图

1. **Phase 1** ✅：文档先行，澄清主线
2. **Phase 2** ✅：旧代码归档到 `legacy/`，旧产物归档到 `archive/`
3. **Phase 3** ✅：建立 `src/teavar_e2e/` 包结构，提升 refactor 代码，修复 import
4. **Phase 4** ✅：新增主线实验入口（`run_e2e_mainline.py`、`run_m2_gamma_frontier.py`）
5. **Phase 5** ✅：文档对齐（PROJECT_SUMMARY, MODEL_AUDIT, modeling.md, README）
6. **Phase 6** ✅：最终审计（见 `docs/FINAL_AUDIT.md`）

**审计结论**：PASS WITH DOCUMENTED WARNINGS
**审计基线**：`c4b55ac`
**审计日期**：2026-06-30

## 当前主线实验入口

```bash
# 单次 M2-C-Cost 运行
PYTHONPATH=src python -m teavar_e2e.experiments.run_e2e_mainline \
    --beta 0.95 --gamma 1.0 --max-failed-components 1

# Gamma 前沿扫描
PYTHONPATH=src python -m teavar_e2e.experiments.run_m2_gamma_frontier \
    --beta 0.95 --gamma-list 0.5,1.0 --max-failed-components 1
```

旧 `run_gamma_frontier.py` 已归档到 `legacy/experiment_scripts/`。
