# routing_mode 消融说明

## 目的

对比 **per_task_od**、**umcf_global**、**umcf_per_task** 在小网格（默认 |I|=4, Γ 3×3）下的前沿形态。  
**不替代** P0 主图（`results/p0_gamma_frontier_b4_tasks8_grid5.csv`）。

## 复现

```bash
python run_routing_mode_ablation.py --num-tasks 4 --grid-size 3 \
  --output results/routing_mode_ablation_tasks4.csv

python plot_routing_mode_ablation.py \
  --csv results/routing_mode_ablation_tasks4_points.csv \
  --output results/fig_routing_mode_ablation_tasks4.png \
  --pdf results/fig_routing_mode_ablation_tasks4.pdf
```

## UMCF 虚拟边语义审计（未改模型）

| 项目 | 说明 |
|------|------|
| **link_price** | 与物理边相同策略：`bandwidth_price_mode=inverse_capacity`（B4 默认），π_e = scale / B_e。虚拟边 B = max(物理 B)，故 π_virtual ≈ scale / B_max（很小）。 |
| **sigma** | loader 默认 `umcf_access_sigma=0.99`（各场景常数）；`(m,V_t)` 默认同 access，除非指定 sink σ。 |
| **是否参与 bandwidth_cost_expr** | **是**。ingress/egress 路径价 τ_p = Σ_{e∈p} π_e 含虚拟单跳边；`is_umcf_auxiliary_edge` 仅用于链路**利用率**指标，不剔除带宽费。 |
| **三模式可比性** | UMCF 模式每任务/全局多 1–2 跳虚拟边，带宽费略增但 π_virtual 极小；**cost 差异主要来自路径锚点与 σ 结构，非虚拟边单价**。若 cost 量级不可比，见 ablation CSV 中 `notes` 与 `virtual_edge_*` 列。 |

## 输出文件

| 文件 | 内容 |
|------|------|
| `routing_mode_ablation_tasks{N}.csv` | 每模式一行汇总 |
| `routing_mode_ablation_tasks{N}_points.csv` | 全部 Γ 网格散点（作图用） |
| `fig_routing_mode_ablation_tasks{N}.png/pdf` | 对比图 |
