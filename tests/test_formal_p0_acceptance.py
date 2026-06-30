# -*- coding: utf-8 -*-
"""Formal P0 acceptance with Pareto filtering."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path


class FormalP0AcceptanceTests(unittest.TestCase):
    def _write(self, rows, fields):
        td = tempfile.mkdtemp()
        path = Path(td) / "frontier.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        return path

    def test_formal_passes_on_four_nd_triples(self):
        from scripts.formal_p0_acceptance import run_formal_acceptance

        rows = []
        triples = [
            (1429.16, 1.0, 0.0209),
            (2330.94, 0.9, 0.0209),
            (2316.46, 0.9, 0.0377),
            (3009.99, 0.8, 0.0209),
        ]
        for i, (c, sla, sf) in enumerate(triples):
            rows.append(
                {
                    "gamma_sla": 0.8 + i * 0.1,
                    "gamma_sf": 0.03 + i * 0.01,
                    "status": "OPTIMAL",
                    "monetary_cost": c,
                    "posthoc_cvar_sla": sla,
                    "posthoc_cvar_sf": sf,
                }
            )
        rows.append(
            {
                "gamma_sla": 1.0,
                "gamma_sf": 0.0377,
                "status": "OPTIMAL",
                "monetary_cost": 1717.93,
                "posthoc_cvar_sla": 1.0,
                "posthoc_cvar_sf": 0.0377,
            }
        )
        fields = list(rows[0].keys())
        path = self._write(rows, fields)
        self.assertEqual(run_formal_acceptance(path, print_pareto_summary=False), 0)

    def test_dominated_point_does_not_fail_v2(self):
        from scripts.formal_p0_acceptance import run_formal_acceptance

        rows = [
            {
                "gamma_sla": 1.0,
                "gamma_sf": 0.03,
                "status": "OPTIMAL",
                "monetary_cost": 1429.16,
                "posthoc_cvar_sla": 1.0,
                "posthoc_cvar_sf": 0.0209,
            },
            {
                "gamma_sla": 1.0,
                "gamma_sf": 0.0377,
                "status": "OPTIMAL",
                "monetary_cost": 1717.93,
                "posthoc_cvar_sla": 1.0,
                "posthoc_cvar_sf": 0.0377,
            },
            {
                "gamma_sla": 0.9,
                "gamma_sf": 0.03,
                "status": "OPTIMAL",
                "monetary_cost": 2330.94,
                "posthoc_cvar_sla": 0.9,
                "posthoc_cvar_sf": 0.0209,
            },
            {
                "gamma_sla": 0.9,
                "gamma_sf": 0.0377,
                "status": "OPTIMAL",
                "monetary_cost": 2316.46,
                "posthoc_cvar_sla": 0.9,
                "posthoc_cvar_sf": 0.0377,
            },
            {
                "gamma_sla": 0.8,
                "gamma_sf": 0.03,
                "status": "OPTIMAL",
                "monetary_cost": 3009.99,
                "posthoc_cvar_sla": 0.8,
                "posthoc_cvar_sf": 0.0209,
            },
        ]
        path = self._write(rows, list(rows[0].keys()))
        self.assertEqual(run_formal_acceptance(path, print_pareto_summary=False), 0)


if __name__ == "__main__":
    unittest.main()
