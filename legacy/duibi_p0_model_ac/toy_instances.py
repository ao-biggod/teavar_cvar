# -*- coding: utf-8 -*-
"""
Deterministic minimal toy instances for exact-enumeration validation.

Node naming (documented in docs/exact_validation.md):
  Toy-SLA: S=0, T=1, A=2, B=3, C=4
  Toy-SF:  S1=0, T1=1, S2=2, T2=3, A=4, B=5, C=6
  Toy-Combined: same endpoints as Toy-SF (integration SLA×SF conflict)
  Toy-ComponentRisk: three tasks, component-level link/compute failures (512 scenarios)

Resource dimensions (aligned with B4):
  K[0]=CPU, K[1]=GPU, K[2]=HBM
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

K_CPU, K_GPU, K_HBM = 0, 1, 2
RESOURCE_LABELS = {K_CPU: "cpu", K_GPU: "gpu", K_HBM: "hbm"}
TOY_K = [K_CPU, K_GPU, K_HBM]

# Compute node ids (shared labels A/B/C; numeric ids differ by toy)
SLA_A, SLA_B, SLA_C = 2, 3, 4
SF_A, SF_B, SF_C = 4, 5, 6
COMB_A, COMB_B, COMB_C = 4, 5, 6  # same layout as Toy-SF
CR_A, CR_B, CR_C = 6, 7, 8  # Toy-ComponentRisk compute nodes


@dataclass(frozen=True)
class ToySpec:
    name: str
    description: str


TOY_SLA = ToySpec(
    name="Toy-SLA",
    description="Single-task SLA CVaR; heterogeneous compute A/B/C.",
)

TOY_SF = ToySpec(
    name="Toy-SF",
    description="Two-task SF CVaR; heterogeneous compute A/B/C; AA CPU overflow in s1.",
)

TOY_COMBINED = ToySpec(
    name="Toy-Combined-Conflict",
    description="Integration: A network-safe/SF-risky, B compute-safe/SLA-risky, C safe/expensive.",
)

TOY_COMPONENT_RISK = ToySpec(
    name="Toy-Combined-ComponentRisk",
    description=(
        "Component-level link/compute failures (512 scenarios); "
        "placement + bandwidth cost; joint SLA/SF trade-off."
    ),
)


def _blank_data() -> Any:
    """Minimal attribute bag compatible with TEAVAR Model A/C."""
    from duibi import UltraComplexData

    return UltraComplexData()


def _cs_from_normal(data, C_normal: dict[int, dict[int, float]]) -> dict:
    """Scenario capacity C_s[node][k][s] = C_normal (unless overridden per scenario)."""
    out: dict = {}
    for node in data.M:
        out[node] = {}
        for k in data.K:
            out[node][k] = {s: float(C_normal[node][k]) for s in data.S}
    return out


def _one_path(u: int, v: int) -> list[list[tuple[int, int]]]:
    return [[(u, v)]]


def _add_od_paths(data, src: int, dst: int, compute_nodes: list[int]) -> None:
    """Single-hop ingress/egress candidate paths via each compute node."""
    for m in compute_nodes:
        data.P_cand[src, m] = _one_path(src, m)
        data.P_cand[m, dst] = _one_path(m, dst)


def build_toy_sla() -> Any:
    """
    Toy-SLA: one task, placement A / B / C, two scenarios.

    Heterogeneity:
      A — CPU-oriented, free, s1 path fails
      B — GPU/HBM-oriented, premium (w·p=0.2), reliable path
      C — balanced mid-tier, moderate (w·p=0.1), reliable path

    Manual expectations (beta_sla=0.8, omega=0):
      - A: SLA cvar=1, cost=0
      - B/C: SLA cvar=0; cost 0.2 / 0.1
      - Model A λ=1.0 → C (cheapest safe); λ=0.1 → A
      - Model C Γ=0.5 → C; Γ=1.0 → A
    """
    data = _blank_data()
    data.routing_mode = "per_task_od"

    data.M = [SLA_A, SLA_B, SLA_C]
    data.I = [0]
    data.K = list(TOY_K)
    data.S = [0, 1]
    data.hub = 0

    data.task_src = {0: 0}
    data.task_dst = {0: 1}

    data.b_in = {0: 10.0}
    data.b_out = {0: 10.0}
    data.w = {0: {K_CPU: 1.0, K_GPU: 1.0, K_HBM: 1.0}}

    data.p_price = {
        SLA_A: {K_CPU: 0.0, K_GPU: 0.0, K_HBM: 0.0},
        SLA_B: {K_CPU: 0.10, K_GPU: 0.05, K_HBM: 0.05},  # 0.2
        SLA_C: {K_CPU: 0.05, K_GPU: 0.025, K_HBM: 0.025},  # 0.1
    }
    C_normal = {
        SLA_A: {K_CPU: 4.0, K_GPU: 2.0, K_HBM: 2.0},
        SLA_B: {K_CPU: 2.0, K_GPU: 4.0, K_HBM: 4.0},
        SLA_C: {K_CPU: 3.0, K_GPU: 3.0, K_HBM: 3.0},
    }
    data.C_normal = C_normal

    data.valid_assign = {(0, SLA_A), (0, SLA_B), (0, SLA_C)}

    edges = [
        (0, SLA_A), (SLA_A, 1),
        (0, SLA_B), (SLA_B, 1),
        (0, SLA_C), (SLA_C, 1),
    ]
    data.E = edges
    data.B = {e: 100.0 for e in edges}
    data.P_cand = {}
    _add_od_paths(data, 0, 1, data.M)

    data.prob = {0: 0.8, 1: 0.2}
    data.beta_N = 0.8
    data.beta_L = 0.8

    data.sigma = {e: {0: 1.0, 1: 1.0} for e in edges}
    data.sigma[(0, SLA_A)][1] = 0.0
    data.sigma[(SLA_A, 1)][1] = 0.0

    data.C_s = _cs_from_normal(data, C_normal)

    data.sigma_vs = None
    data.sigma_vt = None
    data.umcf_virtual_nodes = False
    data.bandwidth_price_scale = 0.0
    data.bandwidth_price_mode = "uniform"
    data.link_price = {e: 0.0 for e in edges}

    return data


def build_toy_sf() -> Any:
    """
    Toy-SF: two tasks, placement on A/B/C, SF overflow on AA in s1.

    Heterogeneity:
      A — CPU pool; s1 CPU 4→2
      B — balanced; cost 0.2/task (cpu price 0.1×2)
      C — balanced; cost 0.15/task (cpu price 0.075×2)

    D_ref: cpu=4, gpu=2, hbm=2.  AA s1 CPU overflow = 0.5.
    Model A λ_sf=1.0 → AC/CA (cost 0.15); λ_sf=0.1 → AA.
    """
    data = _blank_data()
    data.routing_mode = "per_task_od"

    data.M = [SF_A, SF_B, SF_C]
    data.I = [0, 1]
    data.K = list(TOY_K)
    data.S = [0, 1]
    data.hub = 0

    data.task_src = {0: 0, 1: 2}
    data.task_dst = {0: 1, 1: 3}

    data.b_in = {0: 10.0, 1: 10.0}
    data.b_out = {0: 10.0, 1: 10.0}
    data.w = {
        0: {K_CPU: 2.0, K_GPU: 1.0, K_HBM: 1.0},
        1: {K_CPU: 2.0, K_GPU: 1.0, K_HBM: 1.0},
    }

    data.p_price = {
        SF_A: {K_CPU: 0.0, K_GPU: 0.0, K_HBM: 0.0},
        SF_B: {K_CPU: 0.1, K_GPU: 0.0, K_HBM: 0.0},
        SF_C: {K_CPU: 0.075, K_GPU: 0.0, K_HBM: 0.0},
    }
    C_normal = {
        SF_A: {K_CPU: 4.0, K_GPU: 2.0, K_HBM: 4.0},
        SF_B: {K_CPU: 4.0, K_GPU: 4.0, K_HBM: 4.0},
        SF_C: {K_CPU: 4.0, K_GPU: 4.0, K_HBM: 4.0},
    }
    data.C_normal = C_normal

    data.valid_assign = {
        (0, SF_A), (0, SF_B), (0, SF_C),
        (1, SF_A), (1, SF_B), (1, SF_C),
    }

    edges = []
    for src, dst in ((0, 1), (2, 3)):
        for m in data.M:
            edges.extend([(src, m), (m, dst)])
    data.E = edges
    data.B = {e: 100.0 for e in edges}
    data.P_cand = {}
    _add_od_paths(data, 0, 1, data.M)
    _add_od_paths(data, 2, 3, data.M)

    data.prob = {0: 0.8, 1: 0.2}
    data.beta_N = 0.8
    data.beta_L = 0.8

    data.sigma = {e: {0: 1.0, 1: 1.0} for e in edges}

    data.C_s = _cs_from_normal(data, C_normal)
    data.C_s[SF_A][K_CPU][1] = 2.0

    data.sigma_vs = None
    data.sigma_vt = None
    data.umcf_virtual_nodes = False
    data.bandwidth_price_scale = 0.0
    data.bandwidth_price_mode = "uniform"
    data.link_price = {e: 0.0 for e in edges}

    return data


def build_toy_combined() -> Any:
    """
    Toy-Combined-Conflict: SLA vs SF risks point at opposite nodes.

    A — network reliable (s1), CPU capacity 4→0 → SF risk when colocated
    B — compute reliable, s1 all B task paths down → SLA risk when used
    C — both safe, expensive (0.20/task vs B 0.02/task)

    Task demand (2,1,1); D_ref cpu=4, gpu=2, hbm=2.
    With per-task-max SLA aggregation: any task on B in s1 → scenario SLA loss 1.0.
    SF: L_sf(s1) = n_A / 2 (CPU overflow on A).
    """
    data = _blank_data()
    data.routing_mode = "per_task_od"

    data.M = [COMB_A, COMB_B, COMB_C]
    data.I = [0, 1]
    data.K = list(TOY_K)
    data.S = [0, 1]
    data.hub = 0

    data.task_src = {0: 0, 1: 2}
    data.task_dst = {0: 1, 1: 3}

    data.b_in = {0: 10.0, 1: 10.0}
    data.b_out = {0: 10.0, 1: 10.0}
    data.w = {
        0: {K_CPU: 2.0, K_GPU: 1.0, K_HBM: 1.0},
        1: {K_CPU: 2.0, K_GPU: 1.0, K_HBM: 1.0},
    }

    data.p_price = {
        COMB_A: {K_CPU: 0.0, K_GPU: 0.0, K_HBM: 0.0},
        COMB_B: {K_CPU: 0.005, K_GPU: 0.005, K_HBM: 0.005},
        COMB_C: {K_CPU: 0.05, K_GPU: 0.05, K_HBM: 0.05},
    }
    cap = {K_CPU: 4.0, K_GPU: 2.0, K_HBM: 2.0}
    C_normal = {m: dict(cap) for m in data.M}
    data.C_normal = C_normal

    data.valid_assign = {
        (0, COMB_A), (0, COMB_B), (0, COMB_C),
        (1, COMB_A), (1, COMB_B), (1, COMB_C),
    }

    edges = []
    for src, dst in ((0, 1), (2, 3)):
        for m in data.M:
            edges.extend([(src, m), (m, dst)])
    data.E = edges
    data.B = {e: 100.0 for e in edges}
    data.P_cand = {}
    _add_od_paths(data, 0, 1, data.M)
    _add_od_paths(data, 2, 3, data.M)

    data.prob = {0: 0.8, 1: 0.2}
    data.beta_N = 0.8
    data.beta_L = 0.8

    data.sigma = {e: {0: 1.0, 1: 1.0} for e in edges}
    b_edges = [
        (0, COMB_B), (COMB_B, 1),
        (2, COMB_B), (COMB_B, 3),
    ]
    for e in b_edges:
        data.sigma[e][1] = 0.0

    data.C_s = _cs_from_normal(data, C_normal)
    data.C_s[COMB_A][K_CPU][1] = 0.0

    data.sigma_vs = None
    data.sigma_vt = None
    data.umcf_virtual_nodes = False
    data.bandwidth_price_scale = 0.0
    data.bandwidth_price_mode = "uniform"
    data.link_price = {e: 0.0 for e in edges}

    return data


def build_toy_combined_component_risk(*, bandwidth_mode: str = "placement") -> Any:
    """
    Toy-Combined-ComponentRisk: 3 tasks, 3 compute nodes, 9 binary components → 512 scenarios.

    Risk (from independent failure rates, not macro scenarios):
      A — low link fail, high CPU derate (SLA ok, SF risky)
      B — high link fail, low CPU derate (SLA risky, SF ok)
      C — low link fail, low CPU derate (both ok, expensive)

    Cost (per task, resource + bandwidth on placement):
      A: 0.04 (bw 0.04 + place 0)
      B: 0.05 (bw 0.02 + place 0.03)
      C: 0.28 (bw 0.16 + place 0.12)

    ``bandwidth_mode``:
      ``placement`` — bandwidth fee tied to placement (default; legacy regression).
      ``flow`` — ``bandwidth_cost_on_placement=False``; ``c_b = sum x * tau``.
    """
    if bandwidth_mode not in ("placement", "flow"):
        raise ValueError(f"bandwidth_mode must be 'placement' or 'flow', got {bandwidth_mode!r}")
    from component_scenario_generator import FailureComponent, attach_component_scenarios

    data = _blank_data()
    data.routing_mode = "per_task_od"

    data.M = [CR_A, CR_B, CR_C]
    data.I = [0, 1, 2]
    data.K = list(TOY_K)
    data.hub = 0

    od_pairs = [(0, 1), (2, 3), (4, 5)]
    data.task_src = {i: src for i, (src, _dst) in enumerate(od_pairs)}
    data.task_dst = {i: dst for i, (_src, dst) in enumerate(od_pairs)}

    data.b_in = {i: 1.0 for i in data.I}
    data.b_out = {i: 1.0 for i in data.I}
    data.w = {
        i: {K_CPU: 2.0, K_GPU: 1.0, K_HBM: 1.0}
        for i in data.I
    }

    data.p_price = {
        CR_A: {K_CPU: 0.0, K_GPU: 0.0, K_HBM: 0.0},
        CR_B: {K_CPU: 0.0075, K_GPU: 0.0075, K_HBM: 0.0075},
        CR_C: {K_CPU: 0.03, K_GPU: 0.03, K_HBM: 0.03},
    }
    cap = {K_CPU: 6.0, K_GPU: 3.0, K_HBM: 3.0}
    C_normal = {m: dict(cap) for m in data.M}
    data.C_normal = C_normal

    data.valid_assign = {
        (i, m) for i in data.I for m in data.M
    }

    compute_labels = {"A": CR_A, "B": CR_B, "C": CR_C}
    link_pi = {"A": 0.02, "B": 0.01, "C": 0.08}
    ingress_edges: dict[str, list[tuple[int, int]]] = {lab: [] for lab in compute_labels}
    egress_edges: dict[str, list[tuple[int, int]]] = {lab: [] for lab in compute_labels}

    edges: list[tuple[int, int]] = []
    link_price: dict[tuple[int, int], float] = {}
    for i, (src, dst) in enumerate(od_pairs):
        for lab, node in compute_labels.items():
            e_in = (src, node)
            e_out = (node, dst)
            edges.extend([e_in, e_out])
            ingress_edges[lab].append(e_in)
            egress_edges[lab].append(e_out)
            link_price[e_in] = link_pi[lab]
            link_price[e_out] = link_pi[lab]

    data.E = edges
    data.B = {e: 100.0 for e in edges}
    data.P_cand = {}
    for src, dst in od_pairs:
        _add_od_paths(data, src, dst, data.M)

    data.beta_N = 0.8
    data.beta_L = 0.8

    components = [
        FailureComponent("link", "A_in", 0.005),
        FailureComponent("link", "A_out", 0.005),
        FailureComponent("link", "B_in", 0.10),
        FailureComponent("link", "B_out", 0.10),
        FailureComponent("link", "C_in", 0.005),
        FailureComponent("link", "C_out", 0.005),
        FailureComponent("compute_derate", "A", 0.20),
        FailureComponent("compute_derate", "B", 0.01),
        FailureComponent("compute_derate", "C", 0.005),
    ]
    attach_component_scenarios(
        data,
        components=components,
        compute_nodes=compute_labels,
        ingress_edges=ingress_edges,
        egress_edges=egress_edges,
        derate_resource=K_CPU,
        derate_capacity=0.0,
    )

    data.sigma_vs = None
    data.sigma_vt = None
    data.umcf_virtual_nodes = False
    data.bandwidth_price_scale = 0.0
    data.bandwidth_price_mode = "uniform"
    data.bandwidth_cost_on_placement = bandwidth_mode == "placement"
    data.link_price = link_price
    data.bandwidth_mode = bandwidth_mode

    return data


def node_label_sla(node: int) -> str:
    return {0: "S", 1: "T", 2: "A", 3: "B", 4: "C"}.get(node, str(node))


def node_label_sf(node: int) -> str:
    return {0: "S1", 1: "T1", 2: "S2", 3: "T2", 4: "A", 5: "B", 6: "C"}.get(node, str(node))


def format_combined_placement(placement: dict[int, int]) -> str:
    """Two-task code like AA, AB, … using A/B/C labels on COMB nodes."""
    lab = {COMB_A: "A", COMB_B: "B", COMB_C: "C"}
    return "".join(lab[placement[i]] for i in sorted(placement))


def format_component_risk_placement(placement: dict[int, int]) -> str:
    """Three-task code like AAA, ABC, … on CR_A/B/C nodes."""
    lab = {CR_A: "A", CR_B: "B", CR_C: "C"}
    return "".join(lab[placement[i]] for i in sorted(placement))


def count_placement_nodes(placement: dict[int, int], node: int) -> int:
    return sum(1 for i in placement if placement[i] == node)


def format_placement(data, placement: dict[int, int]) -> str:
    if len(data.I) == 1:
        m = placement[data.I[0]]
        return node_label_sla(m) if max(data.M) <= SLA_C else node_label_sf(m)
    parts = []
    for i in data.I:
        m = placement[i]
        lab = node_label_sf(m)
        parts.append(f"i{i}->{lab}")
    return "|".join(parts)
