# -*- coding: utf-8 -*-
"""
Generate realistic node_compute_resources.csv for ALL topologies.

Realism principles (cloud provider economics):
  - Role assignment: based on degree centrality in the WAN topology
    * Core nodes: highest-degree transit hubs (e.g. major IXP cities). High capacity, low unit cost.
    * Aggregation nodes: regional PoPs. Medium capacity, baseline pricing.
    * Edge nodes: access/tail sites. Lower capacity, premium pricing due to scarcity & cooling constraints.

  - Pricing model (relative units, consistent within the project):
    * CPU  = 0.8~1.5  (commodity, cheapest)
    * GPU  = 3.0~5.5  (3.5-5x CPU, reflecting real GPU premium: A100 ~$1-3/GPU-hr vs CPU ~$0.04/core-hr)
    * HBM  = 1.5~2.5  (1.5-2.5x CPU, high-bandwidth memory cost adder)

  - Capacity scaling by role:
    * Core:      120-500 CPU, 40-200 GPU, 24-100 HBM
    * Aggregation: 80-210 CPU, 20-88 GPU,  8-44  HBM
    * Edge:        40-120 CPU, 8-24 GPU,   4-12  HBM

  - Regional variance: each node gets small random perturbation (~10%) to break symmetry.
"""

from __future__ import annotations

import csv
import os
import random


def _compute_degree_centrality(topology_path: str) -> dict[int, int]:
    """Count undirected degree for each node from topology.txt."""
    degree = {}
    with open(topology_path) as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0] in ("to_node", "#"):
                continue
            try:
                u = int(parts[1]) - 1  # from_node
                v = int(parts[0]) - 1  # to_node
                degree[u] = degree.get(u, 0) + 1
                degree[v] = degree.get(v, 0) + 1
            except (ValueError, IndexError):
                continue
    return degree


def _classify_roles(degree: dict[int, int], num_nodes: int) -> dict[int, str]:
    """
    Classify nodes into 3 tiers by degree percentile:
      - Top 25%: core
      - Middle 50%: aggregation
      - Bottom 25%: edge_pop
    For very small topologies (<=8 nodes), use 1/3, 1/3, 1/3 split.
    """
    sorted_nodes = sorted(degree.items(), key=lambda x: -x[1])
    n = len(sorted_nodes)

    if n <= 8:
        n_core = max(2, n // 3)
        n_edge = max(2, n // 3)
    else:
        n_core = max(3, n // 4)
        n_edge = max(3, n // 4)
    n_agg = n - n_core - n_edge

    roles: dict[int, str] = {}
    for i, (node, _) in enumerate(sorted_nodes):
        if i < n_core:
            roles[node] = "core"
        elif i < n_core + n_agg:
            roles[node] = "aggregation"
        else:
            roles[node] = "edge_pop"
    return roles


def _read_node_names(nodes_path: str) -> list[str]:
    """Read node names, skip header."""
    names = []
    with open(nodes_path) as f:
        for line in f:
            line = line.strip()
            if not line or "String_node_names" in line:
                continue
            names.append(line)
    return names


def _read_topology_capacity(topology_path: str) -> dict[int, float]:
    """Sum of incident edge capacities per node (for capacity scaling)."""
    cap_sum = {}
    with open(topology_path) as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0] in ("to_node", "#"):
                continue
            try:
                u = int(parts[1]) - 1
                v = int(parts[0]) - 1
                cap = float(parts[2])
                cap_sum[u] = cap_sum.get(u, 0.0) + cap
                cap_sum[v] = cap_sum.get(v, 0.0) + cap
            except (ValueError, IndexError):
                continue
    return cap_sum


def _role_multipliers(role: str, num_nodes: int) -> dict:
    """
    Return (capacity_mult, price_mult) for each role.
    Larger topologies get wider spread: edge premium increases with network size.
    """
    size_factor = min(2.0, max(1.0, num_nodes / 12.0))

    base = {
        "core":        {"cap": 1.8 * size_factor, "price": 0.75 / size_factor},
        "aggregation": {"cap": 1.0 * size_factor, "price": 1.0},
        "edge_pop":    {"cap": 0.45 * size_factor, "price": 1.45 * size_factor},
    }
    return base[role]


def _realistic_capacity_and_price(
    node_idx: int,
    role: str,
    degree: int,
    cap_ratio: float,
    num_nodes: int,
    rng: random.Random,
) -> dict:
    """
    Compute realistic CPU/GPU/HBM capacity and pricing.
    cap_ratio: this node's incident capacity / max incident capacity in topology.
    """
    mult = _role_multipliers(role, num_nodes)
    jitter = 1.0 + rng.uniform(-0.10, 0.10)
    cap_jitter = mult["cap"] * jitter * max(0.3, min(2.0, cap_ratio + 0.3))

    # Base CPU capacity: 100 units * cap_jitter
    base_cpu = max(20, min(600, 100.0 * cap_jitter))

    # GPU capacity: ~1/3 of CPU (typical GPU:CPU ratio in cloud clusters)
    base_gpu = max(4, base_cpu * 0.35 * rng.uniform(0.85, 1.15))

    # HBM capacity: ~1/5 of CPU (HBM is specialized, limited quantity)
    base_hbm = max(2, base_cpu * 0.18 * rng.uniform(0.85, 1.15))

    price_mult = mult["price"] * rng.uniform(0.90, 1.10)

    return {
        "node_id": node_idx + 1,
        "node_name": f"s{node_idx+1}",
        "cpu_capacity_units": round(base_cpu, 1),
        "gpu_capacity_units": round(base_gpu, 1),
        "hbm_capacity_units": round(base_hbm, 1),
        "price_cpu": round(1.0 * price_mult, 3),
        "price_gpu": round(4.0 * price_mult, 3),
        "price_hbm": round(2.0 * price_mult, 3),
        "role": role,
    }


def generate_compute_csv(
    topology_name: str,
    base_path: str = "./data",
    seed: int = 42,
    output_path: str | None = None,
):
    """
    Generate node_compute_resources.csv for a topology.

    Args:
        topology_name: e.g. "ATT", "XNet"
        base_path: data directory root
        seed: random seed for reproducibility
        output_path: if None, write to <base_path>/<topology>/node_compute_resources.csv
    """
    dir_path = os.path.join(base_path, topology_name)
    topology_file = os.path.join(dir_path, "topology.txt")
    nodes_file = os.path.join(dir_path, "nodes.txt")

    if not os.path.exists(topology_file):
        print(f"  SKIP {topology_name}: no topology.txt")
        return None

    rng = random.Random(f"{topology_name}_{seed}")

    # Analyze topology
    degree = _compute_degree_centrality(topology_file)
    roles = _classify_roles(degree, len(degree))
    node_names = _read_node_names(nodes_file)
    cap_sum = _read_topology_capacity(topology_file)
    max_cap = max(cap_sum.values()) if cap_sum else 1.0

    # Generate rows
    rows = []
    for nid in range(len(node_names)):
        deg = degree.get(nid, 1)
        role = roles.get(nid, "aggregation")
        cap_ratio = cap_sum.get(nid, 0.0) / max_cap if max_cap > 0 else 0.5
        row = _realistic_capacity_and_price(nid, role, deg, cap_ratio, len(node_names), rng)
        row["node_name"] = node_names[nid]
        rows.append(row)

    # Write CSV
    if output_path is None:
        output_path = os.path.join(dir_path, "node_compute_resources.csv")

    fieldnames = [
        "node_id", "node_name",
        "cpu_capacity_units", "gpu_capacity_units", "hbm_capacity_units",
        "price_cpu", "price_gpu", "price_hbm", "role",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # Print summary
    role_counts = {}
    for r in rows:
        rc = r["role"]
        role_counts[rc] = role_counts.get(rc, 0) + 1

    print(
        f"  {topology_name:10s}: {len(rows)} nodes | "
        + " | ".join(f"{r}={c}" for r, c in sorted(role_counts.items()))
        + f" | CPU range {min(r['cpu_capacity_units'] for r in rows):.0f}-{max(r['cpu_capacity_units'] for r in rows):.0f}"
        + f" | price range {min(r['price_cpu'] for r in rows):.2f}-{max(r['price_cpu'] for r in rows):.2f}"
    )
    return rows


# ============================================================================
# Batch generation
# ============================================================================

if __name__ == "__main__":
    import sys

    base = sys.argv[1] if len(sys.argv) > 1 else "./data"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42

    # All known topologies (exclude 'raw' which is not a topology)
    all_topo = [
        d for d in os.listdir(base)
        if os.path.isdir(os.path.join(base, d))
        and os.path.exists(os.path.join(base, d, "topology.txt"))
        and d != "raw"
    ]

    print(f"Generating compute resources for {len(all_topo)} topologies (seed={seed}):")
    print("-" * 75)
    for name in sorted(all_topo):
        generate_compute_csv(name, base_path=base, seed=seed)
    print("-" * 75)
    print("Done. All topologies now have node_compute_resources.csv")
