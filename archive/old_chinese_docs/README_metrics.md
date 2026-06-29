# Frontier metrics & Model C reporting (Phase B+++)

## Model C objective (not pure cost)

Model C minimizes:

```text
objective = monetary_cost - omega_deliver * expected_delivery
```

where `monetary_cost = compute_cost + bandwidth_cost` (`cost_p + cost_b`).

- CSV `objective` / `obj_val` = Gurobi `ObjVal` (includes delivery reward).
- CSV `monetary_cost` / `cost` = **Pareto x-axis for paper figures**.
- Do **not** plot `obj_val` as "cost" unless explicitly discussing the full objective.

`objective_formula` column documents this in new frontier CSVs.

## Post-hoc CVaR (paper SSOT)

| Column | Use |
|:---|:---|
| `posthoc_cvar_sla`, `posthoc_cvar_sf` | **Paper / frontier validation** |
| `model_cvar_sla`, `model_cvar_sf` | Diagnostic only (aux vars; may be non-tight) |
| `cvar_sla`, `cvar_sf` | Legacy alias of model aux |

## Pareto filtering

Raw Γ grids contain **dominated** duplicates (same SLA, lower SF and cost exists).

- `is_pareto_nondominated` = True → eligible for main frontier plot.
- `dominated_by` = `gamma_sla=…;gamma_sf=…` of a dominating grid point.
- Formal acceptance: `scripts/formal_p0_acceptance.py` (V-1~V-5 on non-dominated triples).

## Link pricing

Main experiments: `link_price_mode=uniform` (per-link coefficient = scale, usually 1.0).

`legacy_inverse_capacity` / `inverse_capacity` = sensitivity only; not default.

## Pure-cost sensitivity (separate track)

If the paper needs `min monetary_cost s.t. CVaR ≤ Γ` without delivery reward:

- Run with `--omega-deliver 0` **and** an explicit delivery floor constraint (not in current Model C).
- Do **not** mix `omega=0` runs into the main `omega=1` Pareto figure.
