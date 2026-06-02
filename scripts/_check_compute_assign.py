#!/usr/bin/env python
"""Check whether 12 tasks admit a feasible one-node-per-task compute assignment."""
from run_gamma_frontier import load_p0_data


def greedy_assign(data):
    order = sorted(data.I, key=lambda i: -sum(data.w[i].values()))
    assign = {}
    used = {m: {0: 0.0, 1: 0.0, 2: 0.0} for m in data.M}
    for i in order:
        placed = False
        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            ok = all(
                used[m][k] + data.w[i][k] <= data.C_normal[m][k] + 1e-6
                for k in [0, 1, 2]
            )
            if ok:
                assign[i] = m
                for k in [0, 1, 2]:
                    used[m][k] += data.w[i][k]
                placed = True
                break
        if not placed:
            return None, used
    return assign, used


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
        assign, used = greedy_assign(data)
        print(f"n={n}: greedy={'OK' if assign else 'FAIL'}")
        if assign:
            loads = {
                m: max(
                    used[m][k] / data.C_normal[m][k] if data.C_normal[m][k] > 0 else 0
                    for k in [0, 1, 2]
                )
                for m in data.M
            }
            print(f"  max node util={max(loads.values()):.3f}")


if __name__ == "__main__":
    main()
