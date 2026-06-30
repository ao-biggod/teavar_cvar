# TEAVAR-E2E 仓库文件地图

> 最后更新：2026-06-30

---

## 当前主线（current mainline）

| 文件 | 用途 |
|:--|:--|
| `src/teavar_e2e/data/toy_te_data.py` | ToyTE：11 节点端到端多路径流量工程数据集 |
| `src/teavar_e2e/data/toy_two_task_independent_data.py` | 独立组件故障玩具（23 组件 Bernoulli 乘积） |
| `src/teavar_e2e/data/validate_toy_te.py` | ToyTE 数据完整性验证器（28 项检查） |
| `src/teavar_e2e/models/m0_models.py` | M0：确定性 two-stage multi-path placement-routing baseline |
| `src/teavar_e2e/models/m1_models.py` | M1：场景化 adaptive recourse（$r,z$ + 场景硬容量） |
| `src/teavar_e2e/models/m2_models.py` | M2：端到端 CVaR 风险度量 |
| `src/teavar_e2e/models/m2_cost_models.py` | M2-C-Cost：成本最小化 + CVaR 约束 |
| `src/teavar_e2e/models/m2_cost_helpers.py` | CVaR RU 线性化 + E2E loss 权重 + 成本表达式 |
| `docs/m0_m1_m2_建模说明.md` | M0→M1→M2 完整建模公式 |

> 注：Phase 3 前 `src/teavar_e2e/` 尚未创建，当前主线代码分布在 `refactor/` 和根目录。

---

## 可用 baseline（useful baselines，不再扩展）

| 文件 | 用途 |
|:--|:--|
| `legacy/duibi_p0_model_ac/teavar_framework_models.py` | Model A/C/D：SLA+SF 双 CVaR 四种架构 |
| `legacy/duibi_p0_model_ac/cvar_compare.py` | build_teavar_sla_cvar_model + RU 约束工厂函数 |
| `legacy/duibi_p0_model_ac/duibi.py` | physical CVaR 对照模型（利用率尾部） |
| `legacy/duibi_p0_model_ac/b4_joint_data.py` | B4/多拓扑数据加载器 |
| `legacy/duibi_p0_model_ac/toy_instances.py` | 旧确定性玩具（单路径，exact validation 用） |
| `legacy/duibi_p0_model_ac/exact_enumeration_solver.py` | 穷举验证 solver |
| `legacy/duibi_p0_model_ac/metrics_posthoc.py` | 事后 CVaR 计算 |
| `legacy/duibi_p0_model_ac/pareto_frontier.py` | Pareto 前沿构建 |
| `legacy/duibi_p0_model_ac/p0_calibration.py` | η 标定 |
| `legacy/duibi_p0_model_ac/generate_compute_resources.py` | 自动生成算力 CSV |
| `legacy/duibi_p0_model_ac/frontier_config_snapshot.py` | 前沿配置快照 |
| `legacy/duibi_p0_model_ac/frontier_reporting.py` | 前沿报告 |

### 当前主线候选（根目录保留，Phase 3 迁入 `src/teavar_e2e/`）

| 文件 | 用途 |
|:--|:--|
| `toy_te_data.py` | ToyTE 多路径数据集 |
| `toy_two_task_independent_data.py` | 独立组件故障数据集 |
| `validate_toy_te.py` | 数据完整性验证器 |
| `component_scenario_generator.py` | 故障场景生成器 |
| `m0_instances.py` | M0 实例定义 |

### refactor/ 开发快照（保留不动）

`refactor/` 包含 M0/M1/M2 参考实现和 toy_instances_v2.py。作为开发快照保留，Phase 3 将精选文件复制到 `src/teavar_e2e/`。

---

## 旧实验（legacy experiments）

| 文件 | 用途 |
|:--|:--|
| `legacy/teavar_original/` | 旧 TEAVAR WAN 隧道分流复现 |
| `legacy/copo_drafts/` | Copo 早期草稿 |
| `legacy/l2_bilevel/` | L2 双层模型（fixed-y / embedded-y） |
| `legacy/monetary_cvar/` | 货币化 CVaR 早期探索 |
| `legacy/experiment_scripts/` | P0 扫参 / B4 主表 / routing ablation / UMCF sweep / 论文图表 |

---

## 历史产物（historical outputs）

| 目录 | 内容 |
|:--|:--|
| `archive/old_chinese_docs/` | 旧中文建模文档、工作报告、论文初稿、PDF |
| `archive/old_figures/` | 旧实验图表 |
| `archive/old_results/` | 旧实验结果 CSV、PNG |

---

## 独立发布版

| 目录 | 说明 |
|:--|:--|
| `model_ac_component_risk_release/` | 剥离 duibi 依赖的 Model A/C ComponentRisk 独立发布版 |

---

## 当前主线实验入口（Phase 4+）

| 文件 | 用途 |
|:--|:--|
| `src/teavar_e2e/experiments/run_e2e_mainline.py` | 单次 M2-C-Cost 运行 |
| `src/teavar_e2e/experiments/run_m2_gamma_frontier.py` | Gamma 前沿扫描 |
| `src/teavar_e2e/experiments/common.py` | 共享辅助函数（数据加载、求解封装、CSV 输出） |
| `new_results/e2e_mainline/` | 本地输出目录（不进入 Git） |

## 不变更

| 目录/文件 | 原因 |
|:--|:--|
| `data/` | 多拓扑实验数据（B4/ATT/Abilene/…），各实验线共用 |
| `scripts/` | 审计/检查脚本 |
| `model_ac_component_risk_release/` | 独立发布版（嵌入式 git repo，不跟踪） |
| `.claude/` | Claude Code 项目配置 |
| `refactor/` | 保留为开发快照 |
