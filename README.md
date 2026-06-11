# Model A/C 组件级风险 Toy 实验（6/11）

| 文档 | 说明 |
|:--|:--|
| [`docs/model_ac_建模说明.md`](docs/model_ac_建模说明.md) | Model A（加权目标）与 Model C（风险预算）的完整 MILP 建模 |
| [`reports/工作汇报611.md`](reports/工作汇报611.md) | 6 月 11 日实验周报：组件级风险 toy、AAA/BBB/CCC/ACC 等结果 |

## 术语说明

### 模型

| 术语 | 中文含义 |
|:--|:--|
| **Model A** | 加权目标模型：最小化「成本 + λ_sla·SLA CVaR + λ_sf·SF CVaR − ω·期望送达」；调大 λ 即更重视风险 |
| **Model C** | 风险预算模型：在 SLA CVaR ≤ Γ_sla、SF CVaR ≤ Γ_sf 下最小化成本；Γ 越紧，最优 placement 越保守 |
| **MILP** | 混合整数线性规划；Gurobi 求解 |
| **精确枚举** | 遍历全部可行 placement 手算 cost/CVaR，不依赖 Gurobi，用于验证 MILP 是否正确 |
| **posthoc / 事后指标** | 用 Gurobi 解出的 placement/流量重算 CVaR（`metrics_posthoc.py`） |

### 风险与符号

| 术语 | 中文含义 |
|:--|:--|
| **CVaR** | 条件风险价值：置信水平 β 下尾部场景的平均损失（默认 β=0.8） |
| **SLA CVaR** | 网络送达风险：ingress/egress 需求未满足的 CVaR |
| **SF CVaR** | 算力未满足风险：场景下 CPU 等容量不足（如降级为 0）的 CVaR |
| **λ_sla / λ_sf** | Model A 风险权重 |
| **Γ_sla / Γ_sf** | Model C 风险预算上界 |
| **ω (omega)** | 期望送达奖励系数，防止零流退化 |
| **σ (sigma)** | 链路可用率；组件故障时 σ=0 |
| **C_s** | 场景下节点算力容量 |

### 实例与验证分层

| 术语 | 中文含义 |
|:--|:--|
| **toy / 玩具实例** | 小规模可解释算例，可枚举或手算，用于 sanity check，非性能 benchmark |
| **ComponentRisk toy** | **组件级风险玩具实例**：3 任务 × 3 节点 A/B/C，9 个独立故障组件 → **512** 场景；6/11 周报主实验 |
| **Tier-0** | 验证第 0 层（最基础）：Toy-SLA / Toy-SF，每次只测 **一种** 风险机制；约 20 项测试 |
| **Tier-1** | 验证第 1 层：Conflict toy，SLA 与 SF 风险 **方向相反**，测联合权衡；约 15 项测试 |
| **Tier-2** | 验证第 2 层：B4 / P0 论文规模实验（**不在本发布包**） |
| **Toy-SLA** | Tier-0：1 任务，验证 SLA CVaR |
| **Toy-SF** | Tier-0：2 任务，验证 SF CVaR |
| **Conflict toy** | Tier-1：A 网络稳/算力险，B 算力稳/网络险，C 双稳但贵 |

### 放置方案（placement）

三任务时每位字母表示该任务放到 A / B / C 哪个节点：

| 记号 | 中文含义 |
|:--|:--|
| **placement** | 任务放置方案 |
| **AAA / BBB / CCC** | 三任务全放 A / B / C |
| **ACC** | 1 任务放 A、2 任务放 C；Model C 中间预算下的典型折中解 |
| **ABC** | 每节点各 1 任务；本参数下因含 B（链路差）通常不是最优 |

**ComponentRisk toy 三节点角色：**

| 节点 | 特征 | 设计意图 |
|:--:|:--|:--|
| A | 便宜、算力风险高 | λ_sf 大时应避开 |
| B | 算力稳、链路风险高 | λ_sla 大时应避开 |
| C | 双风险低、成本高 | 预算紧时的保守选择 |

## 实验内容概览

- **玩具实例**：3 节点（A/B/C）× 3 任务，9 个独立故障组件 → **512** 个场景
- **Model A**：用 $\lambda_{\mathrm{sla}}$、$\lambda_{\mathrm{sf}}$ 权衡成本与双 CVaR
- **Model C**：用 $\Gamma_{\mathrm{sla}}$、$\Gamma_{\mathrm{sf}}$ 约束风险预算；中间区间出现 **ACC** 混合 placement
- **验证方式**：Gurobi 求解 vs **精确枚举**（`exact_enumeration_solver.py`）逐点对照

## 目录结构

```
├── README.md                          # 本文件（含术语说明）
├── requirements.txt
├── cvar_compare.py                    # MILP 内核（CVaR 约束、Model A/C 构建）
├── teavar_framework_models.py         # build_teavar_model_a / build_teavar_model_c
├── teavar_data.py                     # 实例数据结构
├── duibi_metrics.py                   # 路径、成本、流量锚点
├── toy_instances.py                   # 组件级风险 toy 及 Tier-0 小实例
├── component_scenario_generator.py    # 组件级故障 → σ、C_s
├── exact_enumeration_solver.py        # 精确枚举最优对照
├── metrics_posthoc.py                 # 事后 CVaR 指标
├── docs/
│   ├── model_ac_建模说明.md
│   └── exact_validation.md
├── reports/工作汇报611.md
├── scripts/reproduce_weekly_experiments.py
└── tests/
    ├── test_combined_component_risk_toy.py   # 主实验（512 场景）
    ├── test_exact_validation.py              # Tier-0（约 20 项）
    └── test_combined_conflict_toy.py         # Tier-1（约 15 项）
```

## 环境要求

1. **Python** 3.10+
2. **Gurobi** 学术/商业许可
3. `pip install -r requirements.txt`

## 快速运行

在本目录根路径下执行：

```bash
# 主实验：组件级风险 toy
python -m unittest tests.test_combined_component_risk_toy -v

# Tier-0：Toy-SLA / Toy-SF
python -m unittest tests.test_exact_validation -v

# Tier-1：Conflict toy
python -m unittest tests.test_combined_conflict_toy -v

# 全部测试
python -m unittest discover -s tests -p "test_*.py" -v

# 复现周报表格
python scripts/reproduce_weekly_experiments.py
```

复现脚本终端标签用英文（如 `mid ACC`），避免 Windows GBK 乱码。

## 代码入口

| 功能 | 入口 |
|:--|:--|
| 构建组件级风险 toy | `toy_instances.build_toy_combined_component_risk()` |
| Model A / C MILP | `teavar_framework_models.build_teavar_model_a/c()` |
| 精确枚举最优 | `exact_enumeration_solver.solve_exact_model_a/c()` |
| 组件场景生成 | `component_scenario_generator.attach_component_scenarios()` |

## 阅读顺序

1. `reports/工作汇报611.md` — 实验动机与结论  
2. `docs/model_ac_建模说明.md` — 数学模型  
3. `tests/test_combined_component_risk_toy.py` — 可执行验证  
4. `scripts/reproduce_weekly_experiments.py` — 数值复现
