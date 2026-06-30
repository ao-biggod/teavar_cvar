"""Quick validation runner — no pytest needed."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from toy_te_data import build_toy_te_dataset, NODE_LABELS, K_LABELS, SHARED_INGRESS_BOTTLENECKS, SHARED_EGRESS_BOTTLENECKS, COMPUTE_BOTTLENECKS
from validate_toy_te import validate_toy_te_data


def main():
    data = build_toy_te_dataset()
    result = validate_toy_te_data(data)
    print(result["summary"])
    print()

    # Summary stats
    print("=" * 56)
    print("  Dataset Statistics")
    print("=" * 56)
    print(f"  Nodes:              {len(data.V)}  ({', '.join(NODE_LABELS[v] for v in data.V)})")
    print(f"  Directed edges:     {len(data.E)}")
    print(f"  Compute nodes:      {len(data.M)}  ({', '.join(NODE_LABELS[m] for m in data.M)})")
    print(f"  Tasks:              {len(data.I)}")
    print(f"  Scenarios:          {len(data.S)}")
    print(f"  Resource dims:      {len(data.K)}  ({', '.join(K_LABELS[k] for k in data.K)})")
    print()

    # Task details
    print(f"  Task details:")
    for i in data.I:
        candidates = [NODE_LABELS[m] for m in data.M if (i, m) in data.valid_assign]
        src = NODE_LABELS[data.task_src[i]]
        dst = NODE_LABELS[data.task_dst[i]]
        demand = ", ".join(f"{K_LABELS[k]}={data.w[i][k]:.0f}" for k in data.K)
        print(f"    task {i}: {src}→{dst}, b_in={data.b_in[i]:.0f}, b_out={data.b_out[i]:.0f}")
        print(f"      demand: {demand}")
        print(f"      candidates: {', '.join(candidates)}")

        for m in data.M:
            if (i, m) not in data.valid_assign:
                continue
            n_in = len(data.P_in.get((data.task_src[i], m), []))
            n_out = len(data.P_out.get((m, data.task_dst[i]), []))
            print(f"      → {NODE_LABELS[m]}: {n_in} ingress paths, {n_out} egress paths")
    print()

    # Path examples
    print(f"  Path examples (task 0 → mA):")
    for p_idx, path in enumerate(data.P_in.get((0, 6), [])):
        nodes = [NODE_LABELS[e[0]] for e in path] + [NODE_LABELS[path[-1][1]]]
        print(f"    ingress[{p_idx}]: {'→'.join(nodes)}")
    for p_idx, path in enumerate(data.P_out.get((6, 9), [])):
        nodes = [NODE_LABELS[e[0]] for e in path] + [NODE_LABELS[path[-1][1]]]
        print(f"    egress[{p_idx}]:  {'→'.join(nodes)}")
    print()

    # Bottlenecks
    all_bottlenecks = SHARED_INGRESS_BOTTLENECKS + SHARED_EGRESS_BOTTLENECKS
    print(f"  Shared bottleneck links:")
    for e in all_bottlenecks:
        print(f"    {NODE_LABELS[e[0]]}→{NODE_LABELS[e[1]]}: cap={data.B[e]:.1f}")
    print(f"  Compute bottleneck summary:")
    for name, desc in COMPUTE_BOTTLENECKS.items():
        print(f"    {name}: {desc}")
    print()

    # Compute capacity matrix
    print(f"  Compute capacity matrix:")
    header = f"    {'':>6s}" + "".join(f"{K_LABELS[k]:>8s}" for k in data.K)
    print(header)
    for m in data.M:
        vals = "".join(f"{data.C_normal[m][k]:>8.0f}" for k in data.K)
        print(f"    {NODE_LABELS[m]:>6s}{vals}")
    print()

    # Scenario details
    print(f"  Scenarios:")
    for s in data.S:
        print(f"    s{s}: prob={data.prob[s]:.1f}")
        if s == 1:
            a_edges = [(u, v) for (u, v) in data.E if u == 2 or v == 2]
            for e in a_edges:
                sig = data.sigma[e][s]
                if sig == 0.0:
                    print(f"      → {NODE_LABELS[e[0]]}→{NODE_LABELS[e[1]]}: σ=0 (node A fail)")
        elif s == 2:
            for k in data.K:
                print(f"      → {NODE_LABELS[6]}[{K_LABELS[k]}]=0.0 (mA fail)")
        elif s == 3:
            for e, _, _ in [((2, 3), None, None)]:
                sig = data.sigma.get((2, 3), {}).get(3, 1.0)
                cap = data.B_s.get((2, 3), {}).get(3, 0.0)
                if sig < 1.0:
                    print(f"      → a→c: σ={sig}, B_s={cap:.1f} (derated)")

    print()
    if result["ok"]:
        print("✓ ALL SANITY CHECKS PASSED")
    else:
        print("✗ SOME CHECKS FAILED — see above")
        sys.exit(1)


if __name__ == "__main__":
    main()
