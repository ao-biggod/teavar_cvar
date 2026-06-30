# -*- coding: utf-8 -*-
"""
Refactored toy instances with **multipath routing** and **link competition**.

The old design was a star topology (src → compute_node → dst) with single-hop
paths — degenerating into a knapsack problem.  The new design adds:

  1. An intermediate hub node shared by multiple OD pairs
  2. Two-path ingress per compute node (direct + via hub)
  3. Shared hub edges that create real routing competition
  4. Compute-node capacity constraints that interact with routing decisions

Topology (7 nodes, 12 directed edges):

       0 (src1)          5 (src2)
       / |    \          / |    \
      /  |     \        /  |     \
     1   2------2------2   4
    (A) (hub)        (hub) (B)
     \   |     /        \  |     /
      \  |    /          \ |    /
       3 (dst1)         6 (dst2)

  Nodes 1 (A) and 4 (B) are compute nodes.
  Node 2 is a shared hub (no compute, just routing).
  Nodes 0/5 are sources, 3/6 are destinations.

  Shared edges: (0,2), (2,1), (2,4), (5,2) — hub ingress/egress
  Direct edges: (0,1), (0,4), (5,1), (5,4) — direct to compute
  Egress edges: (1,3), (4,3), (1,6), (4,6) — compute to dst

Key properties vs old design:
  - Task 0 has 2 ingress paths to A: direct (0→1) and via hub (0→2→1)
  - Task 1 has 2 ingress paths to A: direct (5→1) and via hub (5→2→1)
  - Hub edges (0,2), (2,1), (5,2), (2,4) are shared → link competition
  - Compute capacity: A(CPU=3), B(CPU=4) — both tasks on A → overflow in s2
  - Scenarios create cross-domain risk: network failure (s1) × compute failure (s2)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

K_CPU, K_GPU, K_HBM = 0, 1, 2
RESOURCE_LABELS = {K_CPU: "cpu", K_GPU: "gpu", K_HBM: "hbm"}
TOY_K = [K_CPU, K_GPU, K_HBM]

# Node IDs
SRC1, A, HUB, DST1, B, SRC2, DST2 = 0, 1, 2, 3, 4, 5, 6
COMPUTE_NODES = [A, B]

# Edge labels (for readability)
E_SRC1_A = (SRC1, A)
E_SRC1_HUB = (SRC1, HUB)
E_SRC1_B = (SRC1, B)
E_HUB_A = (HUB, A)
E_HUB_B = (HUB, B)
E_A_DST1 = (A, DST1)
E_B_DST1 = (B, DST1)
E_SRC2_A = (SRC2, A)
E_SRC2_HUB = (SRC2, HUB)
E_SRC2_B = (SRC2, B)
E_A_DST2 = (A, DST2)
E_B_DST2 = (B, DST2)

ALL_EDGES = [
    E_SRC1_A, E_SRC1_HUB, E_SRC1_B,
    E_HUB_A, E_HUB_B,
    E_A_DST1, E_B_DST1,
    E_SRC2_A, E_SRC2_HUB, E_SRC2_B,
    E_A_DST2, E_B_DST2,
]

# Hub edges — shared between tasks, create routing competition
HUB_EDGES = [E_SRC1_HUB, E_SRC2_HUB, E_HUB_A, E_HUB_B]


@dataclass(frozen=True)
class ToySpec:
    name: str
    description: str


TOY_MESH = ToySpec(
    name="Toy-Mesh",
    description=(
        "2-task mesh with shared hub, multipath ingress, link competition, "
        "and compute capacity constraints."
    ),
)

TOY_MESH_SF = ToySpec(
    name="Toy-Mesh-SF",
    description=(
        "2-task mesh focused on compute shortfall: A CPU drops in s2, "
        "forcing tasks to B (more expensive)."
    ),
)

TOY_MESH_COMBINED = ToySpec(
    name="Toy-Mesh-Combined",
    description=(
        "2-task mesh with conflicting risks: s1 breaks hub→A (SLA risk), "
        "s2 drops A CPU (SF risk). B is safe but expensive."
    ),
)


def _blank_data() -> Any:
    """Minimal attribute bag compatible with TEAVAR Model A/C."""
    from duibi import UltraComplexData
    return UltraComplexData()


def _cs_from_normal(data, C_normal: dict[int, dict[int, float]]) -> dict:
    """Scenario capacity C_s[node][k][s] = C_normal (unless overridden)."""
    out: dict = {}
    for node in data.M:
        out[node] = {}
        for k in data.K:
            out[node][k] = {s: float(C_normal[node][k]) for s in data.S}
    return out


def build_toy_mesh() -> Any:
    """
    Toy-Mesh: 2 tasks, 2 compute nodes (A/B), shared hub.

    Network:
      0(src1) --10--> 1(A,CPU=3) --10--> 3(dst1)
      0(src1) --5---> 2(hub) ----5-----> 1(A)
      0(src1) --10--> 4(B,CPU=4) --10--> 3(dst1)
      2(hub) --5----> 4(B)
      5(src2) --10--> 1(A) --10--------> 6(dst2)
      5(src2) --5---> 2(hub) ----5-----> 4(B)
      5(src2) --10--> 4(B) --10--------> 6(dst2)

    Paths (per task):
      Task 0 to A: P0=(0→1), P1=(0→2→1) via hub
      Task 0 to B: P2=(0→4), P3=(0→2→4) via hub
      Task 1 to A: P0=(5→1), P1=(5→2→1) via hub
      Task 1 to B: P2=(5→4), P3=(5→2→4) via hub

    Scenarios:
      s0 (p=0.6): nominal — all links and compute at full capacity
      s1 (p=0.2): hub→A link (2,1) fails — hub paths to A broken
      s2 (p=0.2): A CPU drops 3→1 — both tasks on A causes overflow

    Expected behavior:
      - Both tasks on A: s2 causes compute overflow (CPU 4 > cap 1)
      - Both tasks on B: safe but expensive (no hub→A risk either)
      - Mixed A+B: no compute overflow, but A has hub risk in s1
      - Hub paths: cheaper but vulnerable to s1
      - Direct paths: more expensive but robust to s1
    """
    data = _blank_data()
    data.routing_mode = "per_task_od"

    data.M = COMPUTE_NODES
    data.I = [0, 1]
    data.K = list(TOY_K)
    data.S = [0, 1, 2]
    data.hub = HUB

    data.task_src = {0: SRC1, 1: SRC2}
    data.task_dst = {0: DST1, 1: DST2}

    # Bandwidth demand per task
    data.b_in = {0: 10.0, 1: 10.0}
    data.b_out = {0: 10.0, 1: 10.0}

    # Compute demand per task (same for both)
    data.w = {
        0: {K_CPU: 2.0, K_GPU: 1.0, K_HBM: 1.0},
        1: {K_CPU: 2.0, K_GPU: 1.0, K_HBM: 1.0},
    }

    # Placement cost per compute node (B is more expensive)
    data.p_price = {
        A: {K_CPU: 0.0, K_GPU: 0.0, K_HBM: 0.0},
        B: {K_CPU: 0.10, K_GPU: 0.05, K_HBM: 0.05},
    }

    # Compute capacity
    C_normal = {
        A: {K_CPU: 3.0, K_GPU: 3.0, K_HBM: 3.0},
        B: {K_CPU: 4.0, K_GPU: 4.0, K_HBM: 4.0},
    }
    data.C_normal = C_normal

    # Valid assignments
    data.valid_assign = {
        (0, A), (0, B),
        (1, A), (1, B),
    }

    # Edge capacities
    cap_direct = 10.0
    cap_hub = 5.0
    data.E = ALL_EDGES
    data.B = {
        E_SRC1_A: cap_direct, E_SRC1_HUB: cap_hub, E_SRC1_B: cap_direct,
        E_HUB_A: cap_hub, E_HUB_B: cap_hub,
        E_A_DST1: cap_direct, E_B_DST1: cap_direct,
        E_SRC2_A: cap_direct, E_SRC2_HUB: cap_hub, E_SRC2_B: cap_direct,
        E_A_DST2: cap_direct, E_B_DST2: cap_direct,
    }

    # Multipath candidate paths
    data.P_cand = {}

    # Task 0: src1(0) → compute → dst1(3)
    data.P_cand[SRC1, A] = [[(SRC1, A)], [(SRC1, HUB), (HUB, A)]]
    data.P_cand[SRC1, B] = [[(SRC1, B)], [(SRC1, HUB), (HUB, B)]]
    data.P_cand[A, DST1] = [[(A, DST1)]]
    data.P_cand[B, DST1] = [[(B, DST1)]]

    # Task 1: src2(5) → compute → dst2(6)
    data.P_cand[SRC2, A] = [[(SRC2, A)], [(SRC2, HUB), (HUB, A)]]
    data.P_cand[SRC2, B] = [[(SRC2, B)], [(SRC2, HUB), (HUB, B)]]
    data.P_cand[A, DST2] = [[(A, DST2)]]
    data.P_cand[B, DST2] = [[(B, DST2)]]

    # Scenario probabilities
    data.prob = {0: 0.6, 1: 0.2, 2: 0.2}

    # CVaR confidence (paper: alpha)
    data.alpha_N = 0.8
    data.alpha_L = 0.8

    # Link availability per scenario
    data.sigma = {e: {0: 1.0, 1: 1.0, 2: 1.0} for e in ALL_EDGES}
    # s1: hub→A link fails — hub paths to A broken for both tasks
    data.sigma[E_HUB_A][1] = 0.0

    # Compute capacity per scenario
    data.C_s = _cs_from_normal(data, C_normal)
    # s2: A CPU drops 3→1 — colocating tasks causes overflow
    data.C_s[A][K_CPU][2] = 1.0

    # No virtual source/sink
    data.sigma_vs = None
    data.sigma_vt = None
    data.umcf_virtual_nodes = False

    # Bandwidth pricing
    data.bandwidth_price_scale = 0.0
    data.bandwidth_price_mode = "uniform"
    data.link_price = {e: 0.0 for e in ALL_EDGES}

    return data


def build_toy_mesh_sf() -> Any:
    """
    Toy-Mesh-SF: focused on compute shortfall scenario.

    Same topology as Toy-Mesh but with stronger SF signal:
      s0 (p=0.5): nominal
      s1 (p=0.3): A CPU drops 3→0.5 (severe shortage)
      s2 (p=0.2): B CPU drops 4→2 (mild shortage)

    With both tasks on A: s1 shortfall = (4-0.5)/4 = 0.875
    With both on B: s2 shortfall = (4-2)/4 = 0.5
    Mixed: no overflow in any scenario
    """
    data = build_toy_mesh()

    data.S = [0, 1, 2]
    data.prob = {0: 0.5, 1: 0.3, 2: 0.2}

    # Reset sigma to all nominal
    data.sigma = {e: {0: 1.0, 1: 1.0, 2: 1.0} for e in ALL_EDGES}

    # Compute drops
    data.C_s = _cs_from_normal(data, data.C_normal)
    data.C_s[A][K_CPU][1] = 0.5  # severe A shortage
    data.C_s[B][K_CPU][2] = 2.0  # mild B shortage

    return data


def build_toy_mesh_combined() -> Any:
    """
    Toy-Mesh-Combined: conflicting network vs compute risks.

    s0 (p=0.5): nominal
    s1 (p=0.3): hub→A link fails (SLA risk for hub paths to A)
    s2 (p=0.2): A CPU drops 3→0.5 (SF risk if colocated on A)

    B is safe in both failure scenarios but more expensive.
    """
    data = build_toy_mesh()

    data.S = [0, 1, 2]
    data.prob = {0: 0.5, 1: 0.3, 2: 0.2}

    # s1: hub→A fails
    data.sigma = {e: {0: 1.0, 1: 1.0, 2: 1.0} for e in ALL_EDGES}
    data.sigma[E_HUB_A][1] = 0.0

    # s2: A CPU drops
    data.C_s = _cs_from_normal(data, data.C_normal)
    data.C_s[A][K_CPU][2] = 0.5

    return data


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

NODE_LABELS = {SRC1: "S1", A: "A", HUB: "H", DST1: "T1", B: "B", SRC2: "S2", DST2: "T2"}


def node_label(node: int) -> str:
    return NODE_LABELS.get(node, str(node))


def format_placement(data, placement: dict[int, int]) -> str:
    """e.g. 'S1→A|S2→B'"""
    parts = []
    for i in sorted(data.I):
        m = placement[i]
        parts.append(f"{node_label(data.task_src[i])}→{node_label(m)}")
    return "|".join(parts)
