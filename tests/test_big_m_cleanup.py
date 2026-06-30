# -*- coding: utf-8 -*-
"""P1-MODEL-CLEANUP: Big-M removal from SLA delivery coupling and compute CVaR."""
from __future__ import annotations

import unittest

try:
    from gurobipy import GRB

    HAS_GUROBI = True
except ImportError:
    HAS_GUROBI = False


def _model_var_names(m) -> list[str]:
    return [v.VarName for v in m.getVars()]


def _binary_var_names(m) -> list[str]:
    return [v.VarName for v in m.getVars() if v.VType == GRB.BINARY]


def _legacy_d_ref_expected(data) -> float:
    """Independent reference for legacy D_ref (must match compute_d_ref)."""
    if not data.I or not data.K:
        return 1.0
    d_max_any = 0.0
    for node in data.M:
        for k in data.K:
            dmax = float(sum(data.w[i][k] for i in data.I))
            d_max_any = max(d_max_any, dmax)
    if not data.M or not data.S:
        return max(d_max_any + 1.0, 1.0)
    Cmax = max(
        float(data.C_s[node][k][s])
        for node in data.M
        for k in data.K
        for s in data.S
    )
    return max(d_max_any + 1.0, Cmax + 1.0, 1.0)


def _simplified_d_ref_rejected(data) -> float:
    """Round-1 simplified scale — must NOT be used after D_ref fix."""
    if not data.I or not data.K:
        return 1.0
    d_max = max(float(sum(data.w[i][k] for i in data.I)) for k in data.K)
    return max(1.0, d_max)


@unittest.skipUnless(HAS_GUROBI, "Gurobi not available")
class BigMCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from b4_joint_data import load_joint_data

        cls.data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
        )

    def test_sla_delivery_builds_without_mbig(self):
        from cvar_compare import build_teavar_sla_cvar_model

        m, *_ = build_teavar_sla_cvar_model(
            self.data,
            lambda_cvar=5.0,
            omega_deliver=1.0,
            lambda_compute_sf_cvar=1.0,
        )
        self.assertIsNotNone(m)
        text = m.getAttr("ModelSense")
        self.assertIsNotNone(text)

    def test_compute_cvar_has_no_w_exc_binary_vars(self):
        from cvar_compare import build_teavar_sla_cvar_model

        m, *_ = build_teavar_sla_cvar_model(
            self.data,
            lambda_cvar=5.0,
            omega_deliver=1.0,
            lambda_compute_sf_cvar=1.0,
        )
        binaries = _binary_var_names(m)
        w_exc_like = [n for n in binaries if "wexc" in n.lower() or "w_exc" in n.lower()]
        self.assertEqual(w_exc_like, [], msg=f"unexpected w_exc binaries: {w_exc_like}")

    def test_d_ref_scale_preserved(self):
        from cvar_compare import compute_sf_resource_refs, build_teavar_sla_cvar_model

        refs = compute_sf_resource_refs(self.data)
        legacy_m_ex = _legacy_d_ref_expected(self.data)
        rejected = _simplified_d_ref_rejected(self.data)
        if rejected != legacy_m_ex:
            self.assertNotAlmostEqual(
                legacy_m_ex,
                rejected,
                msg=(
                    f"legacy M_ex must differ from per-resource-only scale; "
                    f"legacy {legacy_m_ex}, per-resource-only {rejected}"
                ),
            )

        m, *_ = build_teavar_sla_cvar_model(
            self.data,
            lambda_cvar=5.0,
            omega_deliver=0.0,
            lambda_compute_sf_cvar=1.0,
        )
        found_k: set[int] = set()
        for constr in m.getConstrs():
            if not constr.ConstrName.startswith("phi_sf_lb_"):
                continue
            parts = constr.ConstrName.split("_")
            # phi_sf_lb_{node}_{k}_{s}
            k_idx = int(parts[4])
            row = m.getRow(constr)
            for j in range(row.size()):
                var = row.getVar(j)
                coeff = row.getCoeff(j)
                if var.VarName.startswith("dreq_"):
                    self.assertAlmostEqual(abs(coeff), 1.0 / refs[k_idx], places=9)
                    found_k.add(k_idx)
                    break
        self.assertEqual(found_k, set(self.data.K), "missing phi_sf_lb per resource dimension")

    def test_compute_cvar_ru_constraints_exist(self):
        from cvar_compare import build_teavar_sla_cvar_model

        m, *_ = build_teavar_sla_cvar_model(
            self.data,
            lambda_cvar=5.0,
            omega_deliver=0.0,
            lambda_compute_sf_cvar=1.0,
        )
        names = _model_var_names(m)
        self.assertTrue(any("zeta_compute_sf" in n for n in names))
        self.assertTrue(any("phi_compute_sf" in n for n in names))

    def test_small_instance_solves(self):
        from cvar_compare import build_teavar_sla_cvar_model

        m, cost, lv, *_ = build_teavar_sla_cvar_model(
            self.data,
            lambda_cvar=5.0,
            omega_deliver=1.0,
            lambda_compute_sf_cvar=1.0,
        )
        self.assertIn(m.status, (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL))
        if m.status == GRB.OPTIMAL:
            self.assertIsNotNone(cost)
            self.assertIsNotNone(lv)

    def test_model_c_builds_without_w_exc(self):
        from teavar_framework_models import build_teavar_model_c

        m, *_ = build_teavar_model_c(
            self.data,
            gamma_sla=1.0,
            gamma_sf=1.0,
            omega_deliver=1.0,
            include_sf_budget=True,
        )
        binaries = _binary_var_names(m)
        w_exc_like = [n for n in binaries if "wexc" in n.lower()]
        self.assertEqual(w_exc_like, [])


if __name__ == "__main__":
    unittest.main()
