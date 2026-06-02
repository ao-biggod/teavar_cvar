#!/usr/bin/env python
"""Exact MILP: exists assignment y[i,m] satisfying compute caps?"""
import gurobipy as gp
from gurobipy import GRB

from run_gamma_frontier import load_p0_data


def assignment_feasible(data, min_off_hub=0, hub=0):
    m = gp.Model("assign")
    m.Params.OutputFlag = 0
    y = m.addVars(
        [(i, node) for i in data.I for node in data.M if (i, node) in data.valid_assign],
        vtype=GRB.BINARY,
    )
    m.addConstrs((gp.quicksum(y[i, node] for node in data.M if (i, node) in y) == 1 for i in data.I))
    if min_off_hub > 0:
        m.addConstr(
            gp.quicksum(y[i, hub] for i in data.I if (i, hub) in y)
            <= len(data.I) - min_off_hub,
            name="min_off_hub",
        )
    for node in data.M:
        for k in data.K:
            m.addConstr(
                gp.quicksum(y[i, node] * data.w[i][k] for i in data.I if (i, node) in y)
                <= data.C_normal[node][k]
            )
    m.optimize()
    return m.status, m.SolCount


def main():
    for n in [8, 11, 12]:
        data = load_p0_data(
            base_path="./data",
            topology="B4",
            num_tasks=n,
            k_paths=4,
            eta=1.3,
            joint_demand_scale=None,
            routing_mode="per_task_od",
            s2_derate=0.4,
            s1_link_k=4,
            s1_sigma=0.8,
            quiet=True,
        )
        for moh in [0, 2]:
            st, sc = assignment_feasible(data, min_off_hub=moh)
            label = "OPTIMAL" if sc > 0 else ("INFEASIBLE" if st == GRB.INFEASIBLE else str(st))
            print(f"n={n} min_off_hub={moh}: assignment {label}")


if __name__ == "__main__":
    main()
