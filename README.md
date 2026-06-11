# Model A/C 组件级风险 Toy 实验（6/11）

| 文档 | 说明 |
|:--|:--|
| [`docs/model_ac_建模说明.md`](docs/model_ac_建模说明.md) | Model A（加权目标）与 Model C（风险预算）的完整 MILP 建模 |
| [`reports/工作汇报611.md`](reports/工作汇报611.md) | 6 月 11 日实验周报：ComponentRisk toy、AAA/BBB/CCC/ACC 等结果 |

## 实验内容概览

- **Toy 实例**：3 节点（A/B/C）× 3 任务，9 个独立故障组件 → **512** 个场景
- **Model A**：用 $\lambda_{\mathrm{sla}}$、$\lambda_{\mathrm{sf}}$ 权衡成本与双 CVaR
- **Model C**：用 $\Gamma_{\mathrm{sla}}$、$\Gamma_{\mathrm{sf}}$ 约束风险预算；中间区间出现 **ACC** 混合 placement
- **验证方式**：Gurobi 求解 vs **精确枚举**（`exact_enumeration_solver.py`）逐点对照

## 目录结构

```
model_ac_component_risk_release/
├── README.md                          # 本文件
├── requirements.txt                   # gurobipy
├── cvar_compare.py                    # MILP 内核（CVaR 约束、Model A/C 构建）
├── teavar_framework_models.py         # build_teavar_model_a / build_teavar_model_c
├── teavar_data.py                     # 实例数据结构
├── duibi_metrics.py                   # 路径、成本、流量锚点
├── toy_instances.py                   # ComponentRisk toy 及 Tier-0 小实例
├── component_scenario_generator.py    # 组件级故障 → σ、C_s
├── exact_enumeration_solver.py        # 无 Gurobi 的暴力最优对照
├── metrics_posthoc.py                 # Gurobi 解的事后 CVaR 指标
├── docs/
│   ├── model_ac_建模说明.md
│   └── exact_validation.md            # 精确验证设计说明
├── reports/
│   └── 工作汇报611.md
├── scripts/
│   └── reproduce_weekly_experiments.py  # 复现周报 §4 扫描表格
└── tests/
    ├── test_combined_component_risk_toy.py   # 主实验（512 场景）
    ├── test_exact_validation.py              # Tier-0 手算对照（20 点）
    └── test_combined_conflict_toy.py         # Conflict toy（15 点）
```

## 环境要求

1. **Python** 3.10+
2. **Gurobi** 学术/商业许可（运行 MILP 与含 Gurobi 的测试）
3. 安装依赖：

```bash
pip install -r requirements.txt
```

## 快速运行

在**本目录根路径**下执行（确保 Python 能找到同级 `.py` 模块）：

### 1. 自动化测试（推荐）

```bash
# 主实验：ComponentRisk toy + Gurobi vs exact
python -m unittest tests.test_combined_component_risk_toy -v

# Tier-0 精确验证（SLA / SF 分离 toy）
python -m unittest tests.test_exact_validation -v

# Conflict toy（双 CVaR 冲突结构）
python -m unittest tests.test_combined_conflict_toy -v

# 一次跑完全部
python -m unittest discover -s tests -p "test_*.py" -v
```

### 2. 复现周报表格输出

```bash
python scripts/reproduce_weekly_experiments.py
```

脚本会打印 Model A 的 $\lambda$ 扫描、Model C 的 $\Gamma$ 代表点（含 ACC 区间），与 [`工作汇报611.md`](reports/工作汇报611.md) §4.3–§4.4 对应。终端输出使用英文标签（如 `mid ACC`），避免 Windows GBK 控制台中文乱码；脚本启动时会按系统 locale 配置 stdout 编码。

## 代码入口对照

| 功能 | 入口 |
|:--|:--|
| 构建 ComponentRisk 数据 | `toy_instances.build_toy_combined_component_risk()` |
| Model A MILP | `teavar_framework_models.build_teavar_model_a()` |
| Model C MILP | `teavar_framework_models.build_teavar_model_c()` |
| 精确枚举最优 | `exact_enumeration_solver.solve_exact_model_a/c()` |
| 组件场景生成 | `component_scenario_generator.attach_component_scenarios()` |

## 与主仓库的关系

本发布包**不包含** B4 主实验、P0 frontier、bilevel 双层模型、`duibi.py` 物理利用率 CVaR 对比等后续工作。若需完整项目，请参考 TEAVAR 主仓库。

## 引用建议

审阅时可按顺序阅读：

1. `reports/工作汇报611.md` — 实验动机与结论  
2. `docs/model_ac_建模说明.md` — 数学模型  
3. `tests/test_combined_component_risk_toy.py` — 可执行验证  
4. `scripts/reproduce_weekly_experiments.py` — 数值复现
