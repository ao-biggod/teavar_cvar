# Exact-enumeration validation suite



Independent brute-force benchmark for **Model A** and **Model C** on deterministic toy instances.

The benchmark **does not** call Gurobi for the exact optimum; tests compare Gurobi solutions against enumeration.



## Purpose



Complex topologies (e.g. B4) lack closed-form optima. These toys are small enough to enumerate every feasible

placement and routing choice, compute cost / per-scenario losses / CVaR by hand, and verify that

`build_teavar_model_a` and `build_teavar_model_c` return the same optimum on **active** objective and constraint fields.



## Scope of exact validation



Exact enumeration covers:



- **Placement** (per-task compute node)

- **Candidate routing** (ingress/egress path index per task)

- **Metrics that enter the solved problem**: cost, CVaR terms with \(\lambda>0\) or \(\Gamma\) budgets, Model A objective



Exact enumeration does **not** claim unique values for inactive auxiliary metrics (see below).



## Three-tier validation layout

| Tier | Instance | Purpose |
|:---|:---|:---|
| **0** | Toy-SLA, Toy-SF | Single-mechanism exact-validation (frozen) |
| **1** | Toy-Combined-Conflict | SLA vs SF **opposing** risks; joint trade-off |
| **2** | B4 / P0 | Paper-scale experiments |

## Files

| File | Role |
|:---|:---|
| `toy_instances.py` | `build_toy_sla`, `build_toy_sf`, `build_toy_combined` |
| `exact_enumeration_solver.py` | Enumeration + CVaR + exact Model A/C + Gurobi extractors |
| `tests/test_exact_validation.py` | Tier-0 regression (20 tests) |
| `tests/test_combined_conflict_toy.py` | Tier-1 integration (15 tests) |
| `docs/exact_validation.md` | This document |



## CVaR definition (matches MILP / `metrics_posthoc.compute_discrete_cvar`)



For scenario losses \(\{L_s\}\), probabilities \(\{p_s\}\), confidence \(\beta\):



\[

\mathrm{CVaR}_\beta(L) = \min_\zeta \;\zeta + \frac{1}{1-\beta}\sum_s p_s \max(L_s - \zeta, 0)

\]



## SF normalization (per-resource SSOT)



Compute-shortfall normalization uses **per-resource** denominators:



\[

D_{ref}[k] = \max\Bigl(\sum_i w[i,k],\; 1.0\Bigr)

\]



Implemented in `cvar_compare.compute_sf_resource_refs` / `sf_D_ref_by_resource`.

Model A/C SF CVaR constraints use \(D_{ref}[k]\) per dimension \(k\).

Posthoc SF loss uses the same definition via `metrics_posthoc.compute_sf_loss_by_scenario`.



The exact solver computes \(D_{ref}[k]\) **independently** in `_sf_d_ref_by_resource` (does not read Gurobi output).



Legacy global `compute_d_ref` (= \(M_{ex}\) for Big-M in older Model B/D paths) is **not** the SF CVaR denominator.



## Resource dimensions (B4-aligned)



| k | Label | Role in toys |

|:---:|:---|:---|

| 0 | CPU | Primary SF stress on node A (Toy-SF s1) |

| 1 | GPU | Heterogeneous capacity / pricing |

| 2 | HBM | Heterogeneous capacity / pricing |



**Node profiles**



| Node | Toy-SLA C_normal (cpu,gpu,hbm) | Toy-SF C_normal (cpu,gpu,hbm) |
|:---|:---|:---|
| **A** | (4, 2, 2) CPU-lean; s1 path fails | (4, 2, 4) CPU pool; s1 cpu→2 |
| **B** | (2, 4, 4) GPU/HBM-lean | (4, 4, 4) balanced |
| **C** | (3, 3, 3) balanced mid | (4, 4, 4) balanced; cheaper than B |

## Toy-SLA (routing / SLA CVaR)

**Nodes:** S=0, T=1, compute **A=2, B=3, C=4**  
**Task:** i0: S→T, demand (cpu,gpu,hbm)=(1,1,1)  
**Placements:** A, B, or C  
**Scenarios:** s0 all paths up; s1 **only A-side links down** (B, C reliable)  
**Costs:** A=0; B=0.2; **C=0.1**  
**Feasible placements enumerated:** 3

| Placement | CVaR\_SLA | Cost |
|:---|:---:|:---:|
| A | 1.0 | 0 |
| B, C | 0 | 0.2 / 0.1 |

**Model A** (\(\lambda_{sf}=0\)): \(\lambda=1.0\) → **C** (0.1); \(\lambda=0.1\) → **A** (0.1)  
**Model C**: \(\Gamma=0.5\) → **C**; \(\Gamma=1.0\) → **A**



## Toy-SF (compute SF CVaR)

**Nodes:** S1=0, T1=1, S2=2, T2=3, compute **A=4, B=5, C=6**  
**Tasks:** i0: S1→T1, i1: S2→T2; demand (2,1,1) per task  
**Placements:** 3×3 = **9** (AA … CC)  
**Scenarios:** s1 **A CPU only** 4→2; B/C stable; paths always up  
**Costs:** A=0; B=**0.2**/task; C=**0.15**/task  
**D_ref:** cpu=4, gpu=2, hbm=2  

| Placement | Cost | CVaR\_sf (key case) |
|:---|:---:|:---:|
| AA | 0 | **0.5** (s1 CPU overflow) |
| AC / CA | **0.15** | 0 |
| AB / BA | 0.2 | 0 |
| CC | 0.30 | 0 |

**Model A** (\(\lambda_{SLA}=0\)): \(\lambda_{sf}=1\) → **AC or CA** (0.15); \(\lambda_{sf}=0.1\) → **AA** (0.05)  
**Model C**: \(\Gamma_{sf}=0.25\) → split (min cost **0.15**); \(\Gamma_{sf}=0.5\) → **AA**



### Inactive metrics when \(\lambda_{SLA}=0\) and \(\omega_{deliver}=0\)



Toy-SF Model A tests use \(\lambda_{SLA}=0\). With zero bandwidth cost and no delivery bonus,

continuous flow \(x\in[0,b]\) may be **objective-equivalent** at \(x=0\) vs \(x=b\).

Posthoc SLA CVaR is therefore **inactive / N/A** — not compared and not treated as a unique optimum indicator.

Tests compare objective, cost, active SF CVaR (\(\lambda_{sf}>0\)), and placement only.

## Toy-Combined-Conflict (Tier 1 — integration)

**Nodes:** S1/T1/S2/T2 + compute **A=4, B=5, C=6** (same layout as Toy-SF)  
**Tasks:** 2; demand (cpu,gpu,hbm) = (2,1,1) each  
**Placements:** 9  

**Node roles**

| Node | Network (s1) | Compute (s1) | Cost / task |
|:---|:---|:---|:---:|
| **A** | reliable | CPU 4→**0** → SF risk | 0 |
| **B** | **paths down** → SLA risk | stable | 0.02 |
| **C** | reliable | stable | 0.20 |

**Scenario losses (β=0.8, p(s1)=0.2 → CVaR = s1 loss)**

- SF: \(L_{sf}(s1) = n_A/2\) (CPU overflow on A)
- SLA: **per-task max** — any task on B → \(L_{sla}(s1)=1.0\) (not average \(n_B/2\))

| Code | Cost | CVaR\_SLA | CVaR\_SF |
|:---|:---:|:---:|:---:|
| AA | 0.00 | 0.0 | 1.0 |
| AB/BA | 0.02 | **1.0** | 0.5 |
| AC/CA | 0.20 | 0.0 | 0.5 |
| BB | 0.04 | 1.0 | 0.0 |
| BC/CB | 0.22 | 1.0 | 0.0 |
| CC | 0.40 | 0.0 | 0.0 |

**Model A**

| λ\_sla | λ\_sf | Optimum |
|:---:|:---:|:---|
| 0.1 | 0.1 | AA |
| 1.0 | 0.1 | AA |
| 0.1 | 1.0 | BB |
| 1.0 | 1.0 | CC |

**Model C**

| Γ\_sla | Γ\_sf | Optimum |
|:---:|:---:|:---|
| 1.0 | 1.0 | AA |
| 0.0 | 1.0 | AA |
| 1.0 | 0.0 | BB |
| 0.5 | 0.5 | **AC or CA** (not AB: SLA=1.0) |
| 0.0 | 0.0 | CC |

> A is network-safe but compute-risky; B is compute-safe but network-risky; C is the expensive safe hub.

## Run

```bash
python -m unittest tests.test_exact_validation -v
python -m unittest tests.test_combined_conflict_toy -v
python -m unittest tests.test_smoke -v
python -m unittest tests.test_per_task_od -v
python -m unittest tests.test_p0_experiment -v
```



## Scope exclusions (unchanged this round)



B4 P0, `run_gamma_frontier` main logic, UMCF, DAG, Model M, physical foil, pricing, eta calibration, partial sigma.


