# P0 实验结果封存（B4 per-task OD）

本文档记录 P0 Γ 前沿实验的**主图配置**、**验收结果**与**任务规模边界**结论，供论文 §7 图表与复现使用。

---

## 1. 主图配置（flagship）

| 参数 | 值 |
|------|-----|
| 拓扑 | B4 |
| 路由模式 | `per_task_od` |
| 任务数 \|I\| | **8** |
| η 标定 | **1.3** |
| S1 链路部分失效 σ | **0.80**（top-k=4） |
| S2 算力 derate | **0.40** |
| min_off_hub | **2** |
| Γ 网格 | **5×5**（Model C） |
| 标定 | Model A（λ_sla=5, λ_sf=1）→ 自适应 Γ 范围 |

**复现命令：**

```bash
python run_gamma_frontier.py --num-tasks 8 --grid-size 5 \
  --output results/p0_gamma_frontier_b4_tasks8_grid5.csv --check

python plot_p0_frontier.py \
  --csv results/p0_gamma_frontier_b4_tasks8_grid5.csv \
  --output results/fig_p0_frontier_b4_tasks8.png \
  --pdf results/fig_p0_frontier_b4_tasks8.pdf
```

---

## 2. 主图结果

**源 CSV：** `results/p0_gamma_frontier_b4_tasks8_grid5.csv`

| 指标 | 值 |
|------|-----|
| OPTIMAL 点数 | **25 / 25** |
| CVaR^SLA 范围 | **[0.040, 0.100]** |
| CVaR^sf 范围 | **[0.018, 0.030]** |
| cost 范围 | **[219.08, 244.00]** |
| P0 acceptance | **V-1 / V-2 / V-3 PASS** |

**§7 主图资产：** `results/fig_p0_frontier_b4_tasks8.png`（及同名 `.pdf`）

---

## 3. 压力边界（\|I\| = 11 / 12）

汇总表：`results/p0_summary_table.csv`

### \|I\| = 11 — 算力容量上界（可行但前沿退化）

- 源 CSV：`results/p0_gamma_frontier_b4_tasks11_grid3.csv`
- 9 / 9 OPTIMAL，P0 acceptance PASS
- **cost 全为 317.19**（平坦），CVaR 二维前沿无有效 cost 权衡
- 解释：**capacity boundary, feasible but cost-flat**

### \|I\| = 12 — 结构性不可行

- 诊断 CSV：`results/p0_diag_tasks12.csv`
- 18 / 18 参数组合（min_off_hub × s2_derate × η）均失败
- **compute_assignment_feasible = False**（全部）
- Model A 与 loose Model C（Γ_sla=0.95, Γ_sf=1.00）均为 INFEASIBLE
- 解释：**compute placement infeasible, structural ceiling**

**12 任务失败不是：**

- Γ 网格过紧（极宽 Γ 仍不可行）
- η 标定异常（8 与 12 任务总 demand 均为 η·C_surv ≈ 8333）
- 链路 σ=0.80 设置问题（8 任务同配置 PASS）

**12 任务失败是：**

- 在 B4 当前 `C_normal` 与任务权重模板 `w[i]` 下，**12 个任务无法同时找到满足算力上限的一任务一节点 placement**（assignment MILP 不可行）
- 阈值：\|I\|=11 可行，\|I\|=12 不可行

---

## 4. 论文写法建议

1. **风险权衡主图（§7）**：使用 **8-task B4** per-task OD 的 5×5 Γ 前沿（CVaR^SLA × CVaR^sf，颜色/cost 标注）。
2. **算力容量边界说明**：并列引用 **11-task**（最大可行负载、cost 平坦）与 **12-task**（placement 不可行）作为 stress / limitation 段落，而非替代主图。
3. **不要**将 12-task 全 INFEASIBLE 网格误读为「Γ 调参失败」或「需求标定 bug」。

---

## 5. 相关文件索引

| 文件 | 用途 |
|------|------|
| `p0_gamma_frontier_b4_tasks8_grid5.csv` | 主图数据（封存） |
| `fig_p0_frontier_b4_tasks8.png` / `.pdf` | §7 主图 |
| `p0_gamma_frontier_b4_tasks11_grid3.csv` | 11 任务边界参考 |
| `p0_diag_tasks12.csv` | 12 任务诊断矩阵 |
| `p0_summary_table.csv` | 8/11/12 对照汇总 |

---

## 6. 测试基线（封存时）

```bash
python -m unittest tests.test_smoke -v
python -m unittest tests.test_per_task_od -v
python -m unittest tests.test_p0_experiment -v
```

预期：smoke 4/4、per_task_od 7/7、p0_experiment 4/4 全部通过。
