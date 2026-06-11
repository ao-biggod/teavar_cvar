# -*- coding: utf-8 -*-
"""Minimal instance container for TEAVAR Model A/C toy experiments."""
from __future__ import annotations


class UltraComplexData:
    """Attribute bag shared by toy builders and MILP models."""

    def __init__(self) -> None:
        self.I = list(range(10))
        self.M = [0, 1, 2, 3]
        self.K = [0, 1, 2]
        self.S = [0, 1, 2]

        self.p_price = {
            0: {0: 10, 1: 50, 2: 20},
            1: {0: 15, 1: 70, 2: 30},
            2: {0: 40, 1: 180, 2: 90},
            3: {0: 50, 1: 220, 2: 120},
        }

        self.w = {i: {0: 4, 1: 2, 2: 8} for i in range(4)}
        self.w.update({i: {0: 8, 1: 0, 2: 4} for i in range(4, 7)})
        self.w.update({i: {0: 2, 1: 1, 2: 32} for i in range(7, 10)})

        self.E = [(u, v) for u in self.M for v in self.M if u != v]
        self.B = {e: 200 for e in self.E}

        self.P_cand: dict = {}
        for u in self.M:
            for v in self.M:
                if u == v:
                    self.P_cand[u, v] = [[]]
                else:
                    path_direct = [(u, v)]
                    k = (u + 1) % 4 if (u + 1) % 4 != v else (u + 2) % 4
                    path_detour = [(u, k), (k, v)]
                    self.P_cand[u, v] = [path_direct, path_detour]

        self.prob = {0: 0.6, 1: 0.3, 2: 0.1}
        self.sigma = {e: {s: 1.0 for s in self.S} for e in self.E}
        self.sigma[(0, 2)][1] = 0.0
        self.sigma[(2, 0)][1] = 0.0

        self.C_s = {m: {k: {s: 150.0 for s in self.S} for k in self.K} for m in self.M}
        for k in self.K:
            self.C_s[0][k][2] = 2.0
            self.C_s[1][k][2] = 2.0

        self.C_normal = {m: {k: 150 for k in self.K} for m in self.M}
        self.b_in = {i: 20 for i in self.I}
        self.b_out = {i: 10 for i in self.I}
        self.beta_N, self.beta_L = 0.95, 0.95
        self.valid_assign = {(i, m): True for i in self.I for m in self.M}
        self.hub = 0
        self.sigma_vs = None
        self.sigma_vt = None
        self.umcf_virtual_nodes = False
        self.bandwidth_price_scale = 1.0
        self.bandwidth_price_mode = "uniform"
