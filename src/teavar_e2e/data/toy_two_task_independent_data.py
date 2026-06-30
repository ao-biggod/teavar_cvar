# -*- coding: utf-8 -*-
"""
Toy-2Task-IndependentComponentRisk-v1

Two tasks, three compute nodes, independent Bernoulli failures on compute
nodes and links.  Scenarios are generated from the product distribution,
not hand-written macro scenarios.

Exhaustive mode enumerates all 2^{|M|+|E|} scenarios (≈ 8.4 M).
Pruned mode (default) keeps only scenarios with ≤ max_failed_components
failures and renormalises probabilities.

Topology (11 nodes, 20 directed edges):

    s1 ──→ a ──→ mA ──→ b ──→ t1
    s2 ──→ c ──→ mB ──→ d ──→ t2
                 mC

Each task-compute pair has 2 ingress paths (via a / via c) and 2 egress
paths (via b / via d).  No forwarding-node failures in this version.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from math import prod
from typing import Any, Optional, Tuple, Union

ComponentId = Union[int, Tuple[int, int]]


# ---------------------------------------------------------------------------
# Node IDs
# ---------------------------------------------------------------------------
S1, S2 = 0, 1
A, C = 2, 3
MA, MB, MC = 4, 5, 6
B_NODE, D_NODE = 7, 8
T1, T2 = 9, 10

NODE_LABELS = {
    S1: "s1", S2: "s2",
    A: "a", C: "c",
    MA: "mA", MB: "mB", MC: "mC",
    B_NODE: "b", D_NODE: "d",
    T1: "t1", T2: "t2",
}

V = [S1, S2, A, C, MA, MB, MC, B_NODE, D_NODE, T1, T2]
M = [MA, MB, MC]
K = [0, 1, 2]                     # CPU=0, GPU=1, HBM=2
K_LABELS = {0: "CPU", 1: "GPU", 2: "HBM"}

# ---------------------------------------------------------------------------
# Edges  (20 directed)
# ---------------------------------------------------------------------------
E: list[tuple[int, int]] = [
    (S1, A), (S1, C),
    (S2, A), (S2, C),
    (A, MA), (A, MB), (A, MC),
    (C, MA), (C, MB), (C, MC),
    (MA, B_NODE), (MA, D_NODE),
    (MB, B_NODE), (MB, D_NODE),
    (MC, B_NODE), (MC, D_NODE),
    (B_NODE, T1), (D_NODE, T1),
    (B_NODE, T2), (D_NODE, T2),
]
E_SET = set(E)


def _edge_label(e):
    return f"{NODE_LABELS[e[0]]}→{NODE_LABELS[e[1]]}"


# ---------------------------------------------------------------------------
# Link parameters: capacity + independent failure probability
# ---------------------------------------------------------------------------
LINK_PARAMS: dict[tuple[int, int], dict[str, float]] = {
    (S1, A):  {"B": 3.0, "p_fail": 0.015},
    (S1, C):  {"B": 3.0, "p_fail": 0.020},
    (S2, A):  {"B": 2.5, "p_fail": 0.020},
    (S2, C):  {"B": 3.0, "p_fail": 0.015},
    (A, MA):  {"B": 3.0, "p_fail": 0.035},
    (C, MA):  {"B": 3.0, "p_fail": 0.030},
    (A, MB):  {"B": 2.8, "p_fail": 0.025},
    (C, MB):  {"B": 2.8, "p_fail": 0.025},
    (A, MC):  {"B": 4.0, "p_fail": 0.015},
    (C, MC):  {"B": 4.0, "p_fail": 0.015},
    (MA, B_NODE):  {"B": 2.4, "p_fail": 0.035},
    (MA, D_NODE):  {"B": 2.4, "p_fail": 0.035},
    (MB, B_NODE):  {"B": 2.6, "p_fail": 0.025},
    (MB, D_NODE):  {"B": 2.6, "p_fail": 0.025},
    (MC, B_NODE):  {"B": 3.2, "p_fail": 0.015},
    (MC, D_NODE):  {"B": 3.2, "p_fail": 0.015},
    (B_NODE, T1):  {"B": 2.0, "p_fail": 0.015},
    (D_NODE, T1):  {"B": 2.0, "p_fail": 0.015},
    (B_NODE, T2):  {"B": 2.0, "p_fail": 0.020},
    (D_NODE, T2):  {"B": 2.0, "p_fail": 0.020},
}

B_CAP: dict[tuple[int, int], float] = {e: p["B"] for e, p in LINK_PARAMS.items()}
P_LINK: dict[tuple[int, int], float] = {e: p["p_fail"] for e, p in LINK_PARAMS.items()}

# Pricing (ρ for compute resources per dimension, ρ for link bandwidth)
RHO_COMPUTE: dict[int, dict[int, float]] = {
    MA: {0: 2.0, 1: 8.0, 2: 5.0},    # CPU cheap, GPU expensive
    MB: {0: 5.0, 1: 3.0, 2: 4.0},    # CPU moderate, GPU moderate
    MC: {0: 3.0, 1: 4.0, 2: 3.0},    # balanced pricing
}
RHO_LINK: dict[tuple[int, int], float] = {
    e: 1.0 for e in E
}  # uniform link price, can be differentiated later

# ---------------------------------------------------------------------------
# Compute node parameters: capacity + independent failure probability
# ---------------------------------------------------------------------------
COMPUTE_PARAMS: dict[int, dict] = {
    MA: {"C": {0: 7.0, 1: 2.0, 2: 4.0}, "p_fail": 0.08},
    MB: {"C": {0: 6.0, 1: 3.0, 2: 5.0}, "p_fail": 0.04},
    MC: {"C": {0: 8.0, 1: 4.0, 2: 6.0}, "p_fail": 0.015},
}

C_NORMAL: dict[int, dict[int, float]] = {m: cp["C"] for m, cp in COMPUTE_PARAMS.items()}
P_COMPUTE: dict[int, float] = {m: cp["p_fail"] for m, cp in COMPUTE_PARAMS.items()}

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
I = [0, 1]

TASK_SRC = {0: S1, 1: S2}
TASK_DST = {0: T1, 1: T2}
B_IN = {0: 4.0, 1: 3.5}
B_OUT = {0: 2.0, 1: 2.5}
W = {
    0: {0: 3.0, 1: 2.0, 2: 2.0},
    1: {0: 4.0, 1: 1.0, 2: 3.0},
}

# w1 + w2 = (7, 3, 5)
VALID_ASSIGN = {(i, m) for i in I for m in M}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
P_IN: dict[tuple[int, int], list[list[tuple[int, int]]]] = {}
P_OUT: dict[tuple[int, int], list[list[tuple[int, int]]]] = {}

for i in I:
    src = TASK_SRC[i]
    dst = TASK_DST[i]
    for cn in M:
        # 2 ingress paths: via a / via c
        P_IN[src, cn] = [
            [(src, A), (A, cn)],
            [(src, C), (C, cn)],
        ]
        # 2 egress paths: via b / via d
        P_OUT[cn, dst] = [
            [(cn, B_NODE), (B_NODE, dst)],
            [(cn, D_NODE), (D_NODE, dst)],
        ]

# Delta: edge-path incidence (for MILP convenience)
DELTA_EDGE_PATH: dict[tuple[int, int], list[tuple[int, int, int, str]]] = {}
for e in E:
    entries = []
    for i in I:
        src = TASK_SRC[i]
        dst = TASK_DST[i]
        for cn in M:
            if (i, cn) not in VALID_ASSIGN:
                continue
            for p_idx, path in enumerate(P_IN.get((src, cn), [])):
                if e in path:
                    entries.append((i, cn, p_idx, "in"))
            for q_idx, path in enumerate(P_OUT.get((cn, dst), [])):
                if e in path:
                    entries.append((i, cn, q_idx, "out"))
    DELTA_EDGE_PATH[e] = entries

# ---------------------------------------------------------------------------
# Independent component failure scenario generation
# ---------------------------------------------------------------------------

ALL_COMPONENTS: list[tuple[str, ComponentId]] = (
    [("compute", m) for m in M]
    + [("link", e) for e in E]
)
NUM_COMPONENTS = len(ALL_COMPONENTS)  # 23


def _component_p(comp_type: str, comp_id: Any) -> float:
    if comp_type == "compute":
        return P_COMPUTE[comp_id]
    elif comp_type == "link":
        return P_LINK[comp_id]
    raise ValueError(f"unknown component type: {comp_type}")


def _scenario_probability(failed_set: set[int]) -> float:
    """Compute product probability of a scenario given a set of failed
    component indices (into ALL_COMPONENTS)."""
    p = 1.0
    for idx, (ctype, cid) in enumerate(ALL_COMPONENTS):
        pf = _component_p(ctype, cid)
        if idx in failed_set:
            p *= pf
        else:
            p *= (1.0 - pf)
    return p


def _scenario_capacities(failed_set: set[int]):
    """Return (C_s, B_s) dicts for a given failure set."""
    Cs: dict[int, dict[int, float]] = {}
    for m in M:
        Cs[m] = dict(C_NORMAL[m])
    Bs: dict[tuple[int, int], float] = dict(B_CAP)

    for idx in failed_set:
        ctype, cid = ALL_COMPONENTS[idx]
        if ctype == "compute":
            for k in K:
                Cs[cid][k] = 0.0
        elif ctype == "link":
            Bs[cid] = 0.0
    return Cs, Bs


def _iter_combinations(max_fail: int, total_components: Optional[int] = None):
    """Yield all failure sets (as frozensets of indices) with ≤ max_fail
    failures.  For exhaustive use max_fail = total_components.

    Parameters
    ----------
    max_fail : int
        Maximum number of simultaneous failures to include.
    total_components : int or None
        Total number of independent components (default: NUM_COMPONENTS).
    """
    if total_components is None:
        total_components = NUM_COMPONENTS
    yield frozenset()  # 0 failures
    for k in range(1, max_fail + 1):
        for combo in combinations(range(total_components), k):
            yield frozenset(combo)


def generate_scenarios(
    scenario_mode: str = "pruned",
    max_failed_components: int = 3,
    renormalize_probabilities: bool = True,
    prune_mode: str = "drop_renormalize",
) -> tuple[list[int], dict[int, float], dict[int, dict], dict[int, dict], dict]:
    """Generate scenarios and return (S, pi, C_s, B_s, metadata).

    Parameters
    ----------
    scenario_mode : "exhaustive" | "pruned"
    max_failed_components : int (default 3)
        Only used in pruned mode.
    renormalize_probabilities : bool (default True)
        Only used in pruned mode with ``prune_mode="drop_renormalize"``.
        If True, rescale so sum(pi) = 1 for kept scenarios.
    prune_mode : "drop_renormalize" | "aggregate_worst" (default "drop_renormalize")
        How to handle the dropped tail probability mass:
          - "drop_renormalize": discard dropped scenarios, renormalise kept ones.
          - "aggregate_worst": keep original probabilities for kept scenarios,
            add one aggregate worst-case scenario with probability = dropped_mass
            and all compute/link capacities set to 0.

    Returns
    -------
    S : list[int]
    pi : dict[s -> float]
    C_s : dict[s -> dict[m -> dict[k -> float]]]
    B_s : dict[s -> dict[e -> float]]
    metadata : dict
    """
    if prune_mode not in ("drop_renormalize", "aggregate_worst"):
        raise ValueError(f"Unknown prune_mode: {prune_mode!r}")

    if scenario_mode == "exhaustive":
        max_fail = NUM_COMPONENTS
    elif scenario_mode == "pruned":
        max_fail = max_failed_components
    else:
        raise ValueError(f"Unknown scenario_mode: {scenario_mode!r}")

    raw: list[tuple[frozenset, float]] = []
    original_mass = 0.0

    for fs in _iter_combinations(max_fail):
        p = _scenario_probability(fs)
        raw.append((fs, p))
        original_mass += p

    total_exhaustive_mass = 1.0
    dropped_mass = total_exhaustive_mass - original_mass

    # Determine scaling and whether to add aggregate worst-case
    if prune_mode == "aggregate_worst":
        scale = 1.0  # keep original probabilities, do NOT renormalise
        add_aggregate = scenario_mode == "pruned" and dropped_mass > 0
    else:
        # drop_renormalize (original behaviour)
        if scenario_mode == "pruned" and renormalize_probabilities and original_mass > 0:
            scale = 1.0 / original_mass
        else:
            scale = 1.0
        add_aggregate = False

    S = list(range(len(raw)))
    pi: dict[int, float] = {}
    C_s: dict[int, dict] = {}
    B_s: dict[int, dict] = {}

    for sid, (fs, p_raw) in enumerate(raw):
        pi[sid] = p_raw * scale
        Cs, Bs = _scenario_capacities(fs)
        C_s[sid] = Cs
        B_s[sid] = Bs

    # If aggregate worst-case mode, add the dropped-mass scenario
    if add_aggregate:
        agg_sid = len(S)
        S.append(agg_sid)
        pi[agg_sid] = dropped_mass  # probability = dropped probability mass
        # Worst-case capacities: all compute resources = 0, all links = 0
        Cs_worst: dict[int, dict[int, float]] = {}
        for m in M:
            Cs_worst[m] = {k: 0.0 for k in K}
        Bs_worst: dict[tuple[int, int], float] = {e: 0.0 for e in E}
        C_s[agg_sid] = Cs_worst
        B_s[agg_sid] = Bs_worst

    metadata: dict = {
        "scenario_mode": scenario_mode,
        "prune_mode": prune_mode,
        "num_scenarios_before_pruning": len(raw),
        "num_scenarios_after_pruning": len(S),
        "max_failed_components": max_failed_components if scenario_mode == "pruned" else NUM_COMPONENTS,
        "num_components": NUM_COMPONENTS,
        "original_probability_mass": original_mass,
        "dropped_probability_mass": dropped_mass,
        "has_aggregate_worst": add_aggregate,
        "aggregate_worst_probability": dropped_mass if add_aggregate else 0.0,
        "renormalized": scenario_mode == "pruned" and renormalize_probabilities and prune_mode == "drop_renormalize",
    }

    return S, pi, C_s, B_s, metadata


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class TwoTaskIndependentData:
    """Toy-2Task-IndependentComponentRisk-v1 data object."""

    name: str = "Toy-2Task-IndependentComponentRisk-v1"
    description: str = (
        "Two tasks, three compute nodes, independent Bernoulli failures. "
        "20 links + 3 compute nodes = 23 independent components. "
        "Scenarios generated from the product distribution (pruned by default)."
    )

    # Topology
    V: list[int] = field(default_factory=lambda: list(V))
    E: list[tuple[int, int]] = field(default_factory=lambda: list(E))
    M: list[int] = field(default_factory=lambda: list(M))
    K: list[int] = field(default_factory=lambda: list(K))

    # Tasks
    J: list[int] = field(default_factory=lambda: list(I))
    task_src: dict[int, int] = field(default_factory=lambda: dict(TASK_SRC))
    task_dst: dict[int, int] = field(default_factory=lambda: dict(TASK_DST))
    b_in: dict[int, float] = field(default_factory=lambda: dict(B_IN))
    b_out: dict[int, float] = field(default_factory=lambda: dict(B_OUT))
    w: dict[int, dict[int, float]] = field(default_factory=lambda: {i: dict(W[i]) for i in I})
    valid_assign: set[tuple[int, int]] = field(default_factory=lambda: set(VALID_ASSIGN))

    # Nominal capacities
    C: dict[int, dict[int, float]] = field(default_factory=lambda: dict(C_NORMAL))
    B: dict[tuple[int, int], float] = field(default_factory=lambda: dict(B_CAP))

    # Pricing
    rho_compute: dict[int, dict[int, float]] = field(default_factory=lambda: dict(RHO_COMPUTE))
    rho_link: dict[tuple[int, int], float] = field(default_factory=lambda: dict(RHO_LINK))

    # CVaR defaults
    beta_cvar: float = 0.8
    theta: dict[int, float] = field(default_factory=lambda: {i: 1.0 for i in I})

    # M1/M2 interface compatibility
    routing_mode: str = "per_task_od"
    prob: dict[int, float] = field(default_factory=dict)  # alias for pi

    @property
    def P_cand(self) -> dict[tuple[int, int], list]:
        """Merge P_in and P_out into a single candidate path dict."""
        merged: dict[tuple[int, int], list] = {}
        for k, v in self.P_in.items():
            merged[k] = v
        for k, v in self.P_out.items():
            merged[k] = v
        return merged

    @property
    def sigma(self) -> dict[tuple[int, int], dict[int, float]]:
        """Link failure indicator: sigma[e][s] = B_s[s][e] / B[e]. Cached."""
        if not hasattr(self, '_sigma_cache') or self._sigma_cache is None:
            sig: dict[tuple[int, int], dict[int, float]] = {}
            for e in self.E:
                sig[e] = {}
                for s in self.S:
                    sig[e][s] = self.B_s.get(s, {}).get(e, 1.0) / float(self.B[e])
            self._sigma_cache = sig
        return self._sigma_cache

    @property
    def C_by_mks(self) -> dict[int, dict[int, dict[int, float]]]:
        """C_s in M1 format: C_s[comp_node][k][s] instead of C_s[s][comp_node][k]."""
        if not hasattr(self, '_C_mks_cache'):
            cmks: dict[int, dict[int, dict[int, float]]] = {}
            for m in self.M:
                cmks[m] = {}
                for k in self.K:
                    cmks[m][k] = {}
                    for s in self.S:
                        cmks[m][k][s] = self.C_s.get(s, {}).get(m, {}).get(k, 0.0)
            self._C_mks_cache = cmks
        return self._C_mks_cache

    # Failure probabilities
    p_compute: dict[int, float] = field(default_factory=lambda: dict(P_COMPUTE))
    p_link: dict[tuple[int, int], float] = field(default_factory=lambda: dict(P_LINK))

    # Paths
    P_in: dict[tuple[int, int], list[list[tuple[int, int]]]] = field(default_factory=lambda: dict(P_IN))
    P_out: dict[tuple[int, int], list[list[tuple[int, int]]]] = field(default_factory=lambda: dict(P_OUT))

    # Scenarios
    S: list[int] = field(default_factory=list)
    pi: dict[int, float] = field(default_factory=dict)
    C_s: dict[int, dict[int, dict[int, float]]] = field(default_factory=dict)
    B_s: dict[int, dict[tuple[int, int], float]] = field(default_factory=dict)
    scenario_metadata: dict = field(default_factory=dict)

    # Derived properties
    @property
    def I(self):
        return self.J

    @property
    def R(self):
        return set(self.V) - set(self.M)

    @property
    def M_i(self):
        return {i: {m for (ii, m) in self.valid_assign if ii == i} for i in self.J}


__all__ = [
    "TwoTaskIndependentData",
    "build_toy_2task_independent_v1",
]


def build_toy_2task_independent_v1(
    scenario_mode: str = "pruned",
    max_failed_components: int = 3,
    renormalize_probabilities: bool = True,
    prune_mode: str = "drop_renormalize",
) -> TwoTaskIndependentData:
    """Build the Toy-2Task-IndependentComponentRisk-v1 dataset.

    Parameters
    ----------
    scenario_mode : "exhaustive" | "pruned"
        "exhaustive" generates all 2^23 ≈ 8.4 M scenarios (for theoretical
        checks only).  "pruned" (default) keeps only scenarios with
        ≤ max_failed_components failures.
    max_failed_components : int
        Maximum number of simultaneously failed components kept.
        Ignored in exhaustive mode.
    renormalize_probabilities : bool
        If True (default), rescale scenario probabilities to sum to 1.
        Only meaningful in pruned mode with ``prune_mode="drop_renormalize"``.
    prune_mode : "drop_renormalize" | "aggregate_worst"
        How to handle the dropped tail probability mass.
        See ``generate_scenarios()``.
    """
    data = TwoTaskIndependentData()

    S, pi, C_s, B_s, meta = generate_scenarios(
        scenario_mode=scenario_mode,
        max_failed_components=max_failed_components,
        renormalize_probabilities=renormalize_probabilities,
        prune_mode=prune_mode,
    )

    data.S = S
    data.pi = pi
    data.prob = pi
    # Store C_s in M1-compatible format: C_s[m][k][s]
    C_s_mks: dict[int, dict[int, dict[int, float]]] = {}
    for m in data.M:
        C_s_mks[m] = {}
        for k in data.K:
            C_s_mks[m][k] = {}
            for s in S:
                C_s_mks[m][k][s] = C_s.get(s, {}).get(m, {}).get(k, 0.0)
    data.C_s = C_s_mks
    data.C_by_original = C_s  # keep original format for reference
    data.B_s = B_s
    data.scenario_metadata = meta
    return data
