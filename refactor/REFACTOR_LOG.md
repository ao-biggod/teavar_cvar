# TEAVAR_python 项目重构记录

> 日期：2026-06-24
> 位置：`TEAVAR_python - 副本/refactor/`

---

## 背景与问题诊断

原项目存在四个核心方向性问题：

### 问题 1：玩具数据集退化为背包问题
- **现象**：`toy_instances.py` 中每个 OD-m 对只有 1 条单跳路径（S→A→T）
- **后果**：没有链路共享竞争，决策退化为"把任务放到哪个算力节点"的背包问题
- **对比**：B4 网络有 12 节点、38 条有向边、每 OD 对 2-4 条最短路径

### 问题 2：算力 CVaR 逻辑缺陷
- **现象**：`add_compute_sf_cvar_ru()` 中 `d_mk = sum(y*w)` 只看放置需求
- **后果**：即使链路故障导致数据到不了节点，CVaR^sf 仍然认为节点在"工作"
- **正确逻辑**：shortfall 应基于"到达数据量 vs 节点处理能力"

### 问题 3：缺少端到端 CVaR 设计
- **现象**：CVaR_SLA（基于交付量）和 CVaR_sf（基于放置需求）完全独立
- **后果**：网络故障和算力故障在模型内部无交互，不是真正的端到端风险模型

### 问题 4：CVaR 公式参数命名错误
- **现象**：论文中置信水平应为 α，代码中混用 β 和 Γ
- **标准符号**（Rockafellar & Uryasev）：α = 置信水平，Γ = 风险预算上限

---

## 修改内容

### 阶段 1：玩具数据集多路径重设计

**新文件**：`toy_instances_v2.py`

设计了一个 7 节点 mesh 拓扑：

```
     0 (src1)          5 (src2)
     / |    \          / |    \
    /  |     \        /  |     \
   1   2------2------2   4
  (A) (hub)        (hub) (B)
   \   |     /        \  |     /
    \  |    /          \ |    /
     3 (dst1)         6 (dst2)
```

关键特性：
- **多路径**：每个任务到每个算力节点有 2 条 ingress 路径（直连 + 经 hub）
- **链路竞争**：hub 边（S1→H, S2→H, H→A, H→B）被两个任务共享，容量仅 5.0
- **算力约束**：A(CPU=3), B(CPU=4)，场景故障时降额
- **三场景设计**：s0 全通(p=0.6)、s1 hub→A 断裂(p=0.2)、s2 A CPU 降额(p=0.2)

三个变体：
- `build_toy_mesh()`：基础版，网络+算力风险交叉
- `build_toy_mesh_sf()`：聚焦算力 shortfall，A CPU 严重降额
- `build_toy_mesh_combined()`：冲突风险，s1 网络故障 + s2 算力故障

### 阶段 2：算力 CVaR 端到端修复

**修改文件**：`cvar_compare.py` → `add_compute_sf_cvar_ru()`

核心改动：
```python
# 旧版：只看放置需求
d_mk[node, k] = sum(y[i, node] * w[i, k])

# 新版：基于场景下实际到达数据量
actual_load[node, k, s] = sum_i( arrived_i[m, s] * w[i,k] / b_in[i] )
# 其中 arrived_i[m, s] = sum_p( del_in[i, m, p, s] )
```

函数签名新增参数：
- `del_in: dict | None`：场景级交付变量
- `xin: dict | None`：计划流量变量

兼容性：无 `del_in`/`xin` 时降级回退到旧版放置需求逻辑。

### 阶段 3：端到端 CVaR 设计

随阶段 2 一起完成。`actual_load` 已经是端到端耦合：
- 网络故障 → `del_in` 降低 → `actual_load` 降低 → shortfall 减少
- 算力故障 → `C_s` 降低 → shortfall 增加
- 两者同时发生时自然产生交叉效应

### 阶段 4：参数统一 β → α

**修改文件**（8 个）：
- `duibi.py`：`self.beta_N, self.beta_L` → `self.alpha_N, self.alpha_L`
- `cvar_compare.py`：所有 `data.beta_N` → `data.alpha_N`，help 文档同步
- `teavar_framework_models.py`：所有 `data.beta_N` → `data.alpha_N`
- `b4_joint_data.py`：`obj.beta_N/L` → `obj.alpha_N/L`
- `toy_instances.py`：所有 `data.beta_N/L` → `data.alpha_N/L`
- `toy_instances_v2.py`：直接使用 `alpha_N/L`
- `exact_enumeration_solver.py`：所有 `data.beta_N` → `data.alpha_N`
- `metrics_posthoc.py`：`getattr(data, "beta_N")` → `getattr(data, "alpha_N")`

符号约定：
- **α**（alpha）= CVaR 置信水平（如 0.95）
- **Γ**（Gamma）= 风险预算上限（ε-约束右端项）
- CLI 参数名 `--beta-loss` 等保留向后兼容

---

## 验证结果

| 测试 | cost | loss_cvar | sf_cvar | 放置 |
|------|------|-----------|---------|------|
| Toy-Mesh Model A (λ=1.0) | 0.300 | 0.000 | - | 0→B, 1→A |
| Toy-Mesh Model A (λ_sf=5.0) | 0.600 | 0.000 | 0.000 | 0→B, 1→B |
| Toy-Mesh-SF (λ_sf=5.0) | 0.300 | 0.000 | 0.375 | 0→A, 1→B |
| Toy-Mesh-Combined (λ_sf=5.0) | 0.600 | 0.000 | 0.000 | 0→B, 1→B |
| Toy-Mesh-Combined Model C | OPTIMAL | - | - | - |

端到端交互验证（强制 task0@A, task1@B）：
- s0：task0 全量到达 A，load_CPU=2.0, cap=3.0, overflow=0
- s1：hub→A 断裂，但直连路径不受影响，task0 仍全量到达
- s2：A CPU 降至 1.0，task0 load=2.0 → overflow=1.0 → sf_cvar 反映

---

## 后续待做

1. 将 `refactor/` 的修改合并回主目录
2. 更新 `建模公式说明.md` 等文档中的符号
3. 更新 `--beta-*` CLI 参数名为 `--alpha-*`（可选，向后兼容）
4. 用新玩具数据集重跑完整测试套件
