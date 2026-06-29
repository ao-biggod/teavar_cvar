# P0 uniform v2 (formal rerun gate)

## SSOT status (Phase B++++)

| File | Status |
|:---|:---|
| `p0_gamma_frontier_b4_tasks8_gated.csv` | **SSOT** (Phase B+ smoke + Pareto annotation; formal PASS) |
| `uniform_frontier_b4_tasks8_posthoc_gamma.csv` (in `temp_smoke_posthoc_gamma/`) | **SSOT source** for Phase B+ |
| `p0_gamma_frontier_b4_tasks8.csv` (2026-06 formal rerun, pre-fix) | **NON-SSOT** — per-resource SF refs; posthoc SF single tier ≈0.004 |
| `p0_gamma_frontier_b4_tasks8_grid5_sf_per_resource.csv` | **NON-SSOT** — documents failed per-resource experiment |

After parity fix (`sf_ref_mode=global_M_ex`), re-run produces SSOT candidate `p0_gamma_frontier_b4_tasks8.csv` (**formal PASS**, 2026-06-04).

Parity vs Phase B+ smoke: posthoc SLA/SF tiers match (0.0209 / 0.0377); placement signatures match at key Γ points; monetary_cost differs (~2× lower) due to zero-tariff empty-path x-flow degeneracy in the re-solve (same y, different x multi-optima). Risk structure for paper figures is restored.

## Configuration (approved smoke)

| Parameter | Value |
|:---|:---|
| topology | B4 |
| routing_mode | per_task_od |
| scenario_mode | macro3 |
| link_price_mode | **uniform** |
| num_tasks | 8 (smoke-validated) |
| eta | 1.3 |
| omega_deliver | 1.0 (Model C default) |
| sf_ref_mode | **global_M_ex** (Phase B+ baseline; do not use per_resource for P0) |

### Posthoc-driven Γ grid

```text
gamma_sla = 0.80, 0.90, 1.00, 1.10, 1.20
gamma_sf  = 0.030, 0.035, 0.0377, 0.040, 0.045
```

## Run command

```bash
python run_gamma_frontier.py \
  --topology B4 --routing-mode per_task_od --num-tasks 8 \
  --link-price-mode uniform \
  --gamma-sla-values 0.80,0.90,1.00,1.10,1.20 \
  --gamma-sf-values 0.030,0.035,0.0377,0.040,0.045 \
  --output results/p0_uniform_v2/p0_gamma_frontier_b4_tasks8.csv \
  --check
```

`--check` invokes **formal_p0_acceptance** (Pareto-filtered V-1~V-5).

## Do not overwrite

- `results/p0_*` sealed CSVs from inverse_capacity era.
- This directory is the new uniform + posthoc Γ SSOT.

## Plotting

- X-axis: `monetary_cost` (not `objective`).
- Risk axes: `posthoc_cvar_sla`, `posthoc_cvar_sf`.
- Filter: `is_pareto_nondominated == True` before drawing the main frontier.

See also `results/README_metrics.md`.
