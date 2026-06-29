# Phase B+ smoke — reconstructed resolved config

> **Purpose:** Phase B+ source run (`uniform_frontier_b4_tasks8_posthoc_gamma.csv`) predates
> `<output>.resolved_config.json` snapshots. Fields below are reconstructed from CSV columns,
> `model_c_gamma_diagnostic.csv`, and documented CLI; uncertain items are marked **UNKNOWN**.

## Confirmed from CSV / diagnostic artifacts

| Field | Value | Source |
|:---|:---|:---|
| topology | B4 | CSV `routing_mode` context + project default |
| routing_mode | `per_task_od` | CSV column |
| num_tasks | 8 | CSV column |
| link_price_mode | `uniform` | CSV column |
| pricing_profile | `uniform` | CSV column |
| eta | 1.3 | CSV column |
| scenario_mode | `macro3` | CSV column |
| num_scenarios | 3 | CSV column |
| scenario_s1_link_sigma | 0.8 | CSV column |
| s2_derate | 0.4 | CSV column |
| min_off_hub | 2 | CSV column |
| umcf_access_sigma | 0.99 | CSV column |
| virtual_edge_count | 0 | CSV column |
| omega_deliver | 1.0 | Model C default; diagnostic CSV `omega_deliver=1.0` |
| gamma_sla_values | 0.80, 0.90, 1.00, 1.10, 1.20 | CSV rows |
| gamma_sf_values | 0.030, 0.035, 0.0377, 0.040, 0.045 | CSV rows |
| sf_ref_mode (Model C) | **global `D_ref=M_ex`** | Phase B++ diagnostic matches posthoc SF tiers; per-resource refs break parity |
| loader entrypoint | `run_gamma_frontier.load_p0_data` → `b4_joint_data.load_joint_data` | codebase convention |

## Task selection (reconstructed from current loader with same parameters)

Deterministic: top-8 off-diagonal OD pairs by scaled demand, sorted descending.
No explicit random seed in smoke CSV — selection is **order-deterministic**, not RNG-based.

| task_id | src | dst | b_in (η=1.3) | b_out |
|:---:|:---:|:---:|:---:|:---:|
| 0 | 4 | 11 | 1699.27 | 849.63 |
| 1 | 5 | 11 | 1035.46 | 517.73 |
| 2 | 4 | 10 | 621.01 | 310.50 |
| 3 | 4 | 2 | 526.79 | 263.39 |
| 4 | 10 | 11 | 522.76 | 261.38 |
| 5 | 4 | 7 | 449.70 | 224.85 |
| 6 | 5 | 10 | 378.42 | 189.21 |
| 7 | 4 | 5 | 321.93 | 160.97 |

demand_total_b_in ≈ **8333.34** (matches legacy smoke exp_deliver reference 8333 in grid3 runs).

## Scenario probabilities / σ

| Scenario | Probability | σ summary |
|:---:|:---:|:---|
| s=0 | **UNKNOWN** (macro3 default ≈ baseline) | all edges up (1.0) — inferred from loader |
| s=1 | **UNKNOWN** | partial top-k link stress, σ=0.8 on k=4 edges |
| s=2 | **UNKNOWN** | aggregation derate ×0.4 on compute |

Exact edge-level σ lists: **UNKNOWN** (not stored in smoke CSV).

## Link price summary

uniform coefficient **1.0** on all physical edges; min=max=mean=1.0; `is_uniform=true`.

## Compute capacity

Per-node CSV caps from `data/B4/compute_resources.csv` at load time: **UNKNOWN** snapshot hash;
current loader reproduces Phase B+ placements when `sf_ref_mode=global_M_ex`.

## Phase B+ key non-dominated triples (posthoc SSOT)

`(monetary_cost, posthoc_sla, posthoc_sf)` — from gated/smoke CSV:

1. (3009.99, 0.80, 0.0209)
2. (2330.94, 0.90, 0.0209)
3. (2316.46, 0.90, 0.0377)
4. (1429.16, 1.00, 0.0209)

Placement signature at `(1.0, 0.03)` from Phase B++ diagnostic:
`0:4|1:5|2:3|3:2|4:10|5:6|6:5|7:4`

## UNKNOWN / not recorded

- Git commit at smoke run time
- Gurobi version / random seed (deterministic MIP; seed **UNKNOWN**)
- `--time-limit` / `--mip-gap` at smoke run (diagnostic used 120s / 0.02 — **likely**, not proven)
- `k_paths` (default 4 — **likely**)
- demand_row index in demand.txt (**UNKNOWN**, default 0 in loader)

## Parity note (Phase B++++ root cause)

Formal FAIL rerun `p0_gamma_frontier_b4_tasks8.csv` was produced with **per-resource SF normalization**
(`sf_refs[k]` branch). Phase B+ used **global `D_ref=M_ex`**. Restoring global normalization
reproduces posthoc SF tiers (0.0209 / 0.0377) and the four non-dominated structures.
