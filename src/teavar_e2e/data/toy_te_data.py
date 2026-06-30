# ToyTE: End-to-End Two-Stage Multi-Path Traffic Engineering Dataset
#
# Design principles (v2026-07):
#   Real multi-path routing across shared links with compute-network trade-offs,
#   NOT a placement/knapsack toy.  Two tasks, three compute nodes, three ingress
#   and three egress paths per task-compute pair, shared bottleneck links, and
#   four failure scenarios that exercise the recourse model.
#
# Node IDs:
#   S1=0  S2=1     (sources)
#   A=2   C=3      (forwarding, ingress side)
#   B=4   D=5      (forwarding, egress side)
#   mA=6  mB=7  mC=8   (compute-capable)
#   T1=9  T2=10    (destinations)
#
# Topology:
#
#          ┌──a(2)──┬──mA(6)──┬──b(4)──┐
#   s1(0) ─┤        │         │        ├── t1(9)
#          ├──c(3)──┤         ├──d(5)──┤
#   s2(1) ─┤        │  mB(7)  │        ├── t2(10)
#          │        ├──┘      └──┘      │
#          │  mC(8) │                   │
#          └────────┘                   └──
#
# Edges (24 directed):
#   Source        s1→a  s1→c  s2→a  s2→c
#   Inter-fwd     a→c   c→a
#   Ingress       a→mA  a→mB  a→mC  c→mA  c→mB  c→mC
#   Egress        mA→b  mA→d  mB→b  mB→d  mC→b  mC→d
#   Inter-fwd     b→d   d→b
#   Destination   b→t1  d→t1  b→t2  d→t2
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Node IDs
# ---------------------------------------------------------------------------
S1, S2 = 0, 1
A, C = 2, 3
B, D = 4, 5
MA, MB, MC = 6, 7, 8
T1, T2 = 9, 10

NODE_LABELS = {
    S1: "s1", S2: "s2",
    A: "a", C: "c", B: "b", D: "d",
    MA: "mA", MB: "mB", MC: "mC",
    T1: "t1", T2: "t2",
}

V = [S1, S2, A, C, B, D, MA, MB, MC, T1, T2]
M = [MA, MB, MC]
R = [v for v in V if v not in M]
K = [0, 1, 2]  # CPU=0, GPU=1, HBM=2
K_LABELS = {0: "CPU", 1: "GPU", 2: "HBM"}
I = [0, 1]  # task indices


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------
E = [
    # source → forwarding (ingress side)
    (S1, A), (S1, C),
    (S2, A), (S2, C),
    # inter-forwarder (ingress side)
    (A, C), (C, A),
    # forwarding → compute
    (A, MA), (A, MB), (A, MC),
    (C, MA), (C, MB), (C, MC),
    # compute → forwarding (egress side)
    (MA, B), (MA, D),
    (MB, B), (MB, D),
    (MC, B), (MC, D),
    # inter-forwarder (egress side)
    (B, D), (D, B),
    # forwarding → destination
    (B, T1), (D, T1),
    (B, T2), (D, T2),
]
E_SET = set(E)

# Shared bottleneck links (used by multiple task-compute pairs)
SHARED_INGRESS_BOTTLENECKS = [(A, C), (C, A)]
SHARED_EGRESS_BOTTLENECKS = [(B, D), (D, B)]
ALL_BOTTLENECK_LINKS = SHARED_INGRESS_BOTTLENECKS + SHARED_EGRESS_BOTTLENECKS


# ---------------------------------------------------------------------------
# Ingress / egress paths per (task, compute-node)
# ---------------------------------------------------------------------------

def _path(*nodes: int) -> list[tuple[int, int]]:
    """Convert node sequence ``(u, v, w)`` into edges ``[(u,v), (v,w)]``."""
    return [(nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)]


def _paths_in(src, cn):
    """3 ingress paths: direct via A, direct via C, A→C detour."""
    return [
        _path(src, A, cn),          # direct via A
        _path(src, C, cn),          # direct via C
        _path(src, A, C, cn),       # A→C detour (shares a→c bottleneck)
    ]


def _paths_out(cn, dst):
    """3 egress paths: direct via B, direct via D, B→D detour."""
    return [
        _path(cn, B, dst),          # direct via B
        _path(cn, D, dst),          # direct via D
        _path(cn, B, D, dst),       # B→D detour (shares b→d bottleneck)
    ]


# Task 0:  s1 → compute → t1
P_IN: dict[tuple[int, int], list[list[tuple[int, int]]]] = {}
P_OUT: dict[tuple[int, int], list[list[tuple[int, int]]]] = {}

for cn in M:
    P_IN[S1, cn] = _paths_in(S1, cn)
    P_OUT[cn, T1] = _paths_out(cn, T1)
    P_IN[S2, cn] = _paths_in(S2, cn)
    P_OUT[cn, T2] = _paths_out(cn, T2)


# ---------------------------------------------------------------------------
# Link capacities
# ---------------------------------------------------------------------------
# Each task carries b=10 per direction.  Shared links are tight to force
# multi-path splitting under load.

B_NOM: dict[tuple[int, int], float] = {
    # Source edges — asymmetric: each task's "preferred" path is narrow
    (S1, A): 12.0,
    (S1, C): 8.0,
    (S2, A): 8.0,
    (S2, C): 12.0,
    # Inter-forwarder — narrow bottleneck (6 < 10+10)
    (A, C): 6.0,
    (C, A): 6.0,
    # Ingress to compute — generous
    (A, MA): 10.0, (A, MB): 10.0, (A, MC): 10.0,
    (C, MA): 10.0, (C, MB): 10.0, (C, MC): 10.0,
    # Egress from compute — generous
    (MA, B): 10.0, (MA, D): 10.0,
    (MB, B): 10.0, (MB, D): 10.0,
    (MC, B): 10.0, (MC, D): 10.0,
    # Inter-forwarder egress — narrow bottleneck
    (B, D): 8.0,
    (D, B): 8.0,
    # Destination edges — asymmetric
    (B, T1): 12.0,
    (D, T1): 8.0,
    (B, T2): 8.0,
    (D, T2): 12.0,
}


# ---------------------------------------------------------------------------
# Compute-node capacities (heterogeneous)
# ---------------------------------------------------------------------------
#   mA: CPU-rich, GPU-poor
#   mB: CPU-poor, GPU-rich
#   mC: balanced
# When both tasks colocate, one resource dimension overflows.

C_NORMAL: dict[int, dict[int, float]] = {
    MA: {0: 8.0, 1: 2.0, 2: 2.0},
    MB: {0: 2.0, 1: 8.0, 2: 2.0},
    MC: {0: 5.0, 1: 5.0, 2: 5.0},
}

COMPUTE_BOTTLENECKS: dict[str, str] = {
    "mA_GPU": f"mA GPU cap=2 < task0+task1 GPU demand=5",
    "mB_CPU": f"mB CPU cap=2 < task0+task1 CPU demand=5",
    "mC_tight": f"mC CPU=GPU=5 = both-colocated demand=5",
}


# ---------------------------------------------------------------------------
# Task parameters
# ---------------------------------------------------------------------------
# Task 0: CPU-heavy   (prefers mA)
# Task 1: GPU-heavy   (prefers mB)

TASK_SRC = {0: S1, 1: S2}
TASK_DST = {0: T1, 1: T2}
B_IN = {0: 10.0, 1: 10.0}
B_OUT = {0: 10.0, 1: 10.0}
W = {
    0: {0: 4.0, 1: 1.0, 2: 1.0},   # CPU-heavy
    1: {0: 1.0, 1: 4.0, 2: 1.0},   # GPU-heavy
}
VALID_ASSIGN = {(i, m) for i in I for m in M}


# ---------------------------------------------------------------------------
# Scenarios (4)
# ---------------------------------------------------------------------------
S = [0, 1, 2, 3]
PROB = {0: 0.5, 1: 0.2, 2: 0.2, 3: 0.1}
ALPHA_CVAR = 0.80  # confidence level (not to be confused with η/VaR)

# Link availability per scenario (1.0 = fully available, 0.0 = failed)
SIGMA: dict[tuple[int, int], dict[int, float]] = {}
for e in E:
    SIGMA[e] = {s: 1.0 for s in S}

# s1: forwarding node A is unavailable — all edges incident to A are dead
A_INCIDENT = [e for e in E if e[0] == A or e[1] == A]
for e in A_INCIDENT:
    SIGMA[e][1] = 0.0

# s3: bottleneck a→c derated to 30% capacity
BOTTLENECK_DERATED = (A, C)
SIGMA[BOTTLENECK_DERATED][3] = 0.3

# Compute capacity per scenario
C_S: dict[int, dict[int, dict[int, float]]] = {}
for cn in M:
    C_S[cn] = {}
    for k in K:
        C_S[cn][k] = {s: float(C_NORMAL[cn][k]) for s in S}
# s2: mA completely unavailable
for k in K:
    C_S[MA][k][2] = 0.0


# ---------------------------------------------------------------------------
# Bandwidth per scenario: B_s[e,s] = B[e] * sigma[e][s]
# ---------------------------------------------------------------------------
B_S: dict[tuple[int, int], dict[int, float]] = {}
for e in E:
    B_S[e] = {s: B_NOM[e] * SIGMA[e][s] for s in S}


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class ToyTEData:
    """Unified data object for the ToyTE end-to-end traffic engineering dataset.

    Canonical fields:
      V, E, M, K, J (task set), S (scenarios)
    Derived properties (not stored, computed on access):
      I  — backward-compatible alias to J
      R  — V \\ M (forwarding-only nodes)
      M_i — per-task candidate compute nodes from valid_assign
    """

    # Topology
    V: list[int] = field(default_factory=lambda: list(V))
    E: list[tuple[int, int]] = field(default_factory=lambda: list(E))
    M: list[int] = field(default_factory=lambda: list(M))
    K: list[int] = field(default_factory=lambda: list(K))
    # R and M_i are derived properties — not stored directly

    # Link capacity
    B: dict[tuple[int, int], float] = field(default_factory=lambda: dict(B_NOM))

    # Compute capacity (nominal)
    C_normal: dict[int, dict[int, float]] = field(default_factory=lambda: dict(C_NORMAL))

    # Tasks — J is canonical, I remains as stored field for backward compat
    J: list[int] = field(default_factory=lambda: list(I))
    task_src: dict[int, int] = field(default_factory=lambda: dict(TASK_SRC))
    task_dst: dict[int, int] = field(default_factory=lambda: dict(TASK_DST))
    b_in: dict[int, float] = field(default_factory=lambda: dict(B_IN))
    b_out: dict[int, float] = field(default_factory=lambda: dict(B_OUT))
    w: dict[int, dict[int, float]] = field(default_factory=lambda: {i: dict(W[i]) for i in I})
    valid_assign: set[tuple[int, int]] = field(default_factory=lambda: set(VALID_ASSIGN))

    # Paths
    P_in: dict[tuple[int, int], list[list[tuple[int, int]]]] = field(default_factory=lambda: dict(P_IN))
    P_out: dict[tuple[int, int], list[list[tuple[int, int]]]] = field(default_factory=lambda: dict(P_OUT))

    # Scenarios
    S: list[int] = field(default_factory=lambda: list(S))
    prob: dict[int, float] = field(default_factory=lambda: dict(PROB))
    sigma: dict[tuple[int, int], dict[int, float]] = field(default_factory=lambda: dict(SIGMA))
    B_s: dict[tuple[int, int], dict[int, float]] = field(default_factory=lambda: dict(B_S))
    C_s: dict[int, dict[int, dict[int, float]]] = field(default_factory=lambda: dict(C_S))

    # CVaR params
    alpha_cvar: float = ALPHA_CVAR
    beta_cvar: float = ALPHA_CVAR  # alias for pipeline compatibility
    gamma_cvar: float | None = None

    # Routing mode
    routing_mode: str = "per_task_od"

    # Metadata
    name: str = "ToyTE"
    description: str = (
        "End-to-end two-stage multi-path TE toy: 2 tasks, 3 compute nodes, "
        "3 ingress + 3 egress paths per task-compute pair, shared bottleneck "
        "links, 4 failure scenarios."
    )

    # --- Derived properties ---

    @property
    def I(self) -> list[int]:
        """Backward-compatible alias to J."""
        return self.J

    @property
    def R(self) -> set[int]:
        """Forwarding-only nodes = V \\ M (derived, not stored)."""
        return set(self.V) - set(self.M)

    @property
    def M_i(self) -> dict[int, set[int]]:
        """Per-task candidate compute nodes, derived from valid_assign."""
        return {
            i: {m for (ii, m) in self.valid_assign if ii == i}
            for i in self.J
        }


def build_toy_te_dataset(seed: int = 0) -> ToyTEData:
    """Build the complete ToyTE dataset.

    ``seed`` is accepted for interface compatibility; ToyTE is deterministic
    (no random generation), so the seed is ignored.
    """
    _ = seed
    return ToyTEData()
