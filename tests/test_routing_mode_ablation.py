# -*- coding: utf-8 -*-
"""routing_mode 消融：参数解析、虚拟边元数据、summary/plot 逻辑。"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path


class RoutingModeAblationTests(unittest.TestCase):
    def test_run_gamma_frontier_accepts_umcf_per_task(self):
        import argparse
        from run_gamma_frontier import load_p0_data, resolve_routing_mode

        args = argparse.Namespace(
            routing_mode="per_task_od",
            joint_umcf_per_task=True,
            joint_umcf_teavar=False,
        )
        self.assertEqual(resolve_routing_mode(args), "umcf_per_task")

        data = load_p0_data(
            base_path="./data",
            topology="B4",
            num_tasks=4,
            k_paths=2,
            eta=None,
            joint_demand_scale=1.0,
            routing_mode="umcf_per_task",
            s2_derate=0.4,
            s1_link_k=4,
            s1_sigma=0.8,
            quiet=True,
        )
        self.assertEqual(data.routing_mode, "umcf_per_task")
        self.assertTrue(getattr(data, "umcf_per_task_nodes", False))

    def test_virtual_edge_metadata_present(self):
        from run_gamma_frontier import load_p0_data, collect_virtual_edge_metadata

        data = load_p0_data(
            base_path="./data",
            topology="B4",
            num_tasks=4,
            k_paths=2,
            eta=1.3,
            joint_demand_scale=None,
            routing_mode="umcf_per_task",
            s2_derate=0.4,
            s1_link_k=4,
            s1_sigma=0.8,
            quiet=True,
        )
        meta = collect_virtual_edge_metadata(data)
        self.assertGreater(meta["virtual_edge_count"], 0)
        self.assertIn("virtual_edge_price_policy", meta)
        self.assertIn("virtual_edge_sigma_policy", meta)
        self.assertTrue(meta["virtual_edges_in_bandwidth_cost"])
        self.assertTrue(hasattr(data, "routing_virtual_edge_meta"))

    def test_routing_mode_ablation_summary_synthetic(self):
        from run_routing_mode_ablation import _summarize_mode, write_summary_csv
        from plot_routing_mode_ablation import load_optimal_by_mode, plot_ablation

        rows = []
        for mode in ("per_task_od", "umcf_global"):
            for k, (sla, sf, cost) in enumerate(
                [(0.05, 0.02, 100.0), (0.06, 0.025, 102.0)]
            ):
                rows.append(
                    {
                        "routing_mode": mode,
                        "status": "OPTIMAL",
                        "cvar_sla": sla,
                        "cvar_sf": sf + (0.001 if mode == "umcf_global" else 0.0),
                        "cost": cost + k,
                        "num_tasks": 4,
                        "eta": 1.3,
                        "scenario_s1_link_sigma": 0.8,
                    }
                )

        with tempfile.TemporaryDirectory() as td:
            points = Path(td) / "syn_points.csv"
            summary = Path(td) / "syn_summary.csv"
            with points.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)

            by_mode = load_optimal_by_mode(points)
            self.assertEqual(len(by_mode), 2)

            s = _summarize_mode(
                "per_task_od",
                [r for r in rows if r["routing_mode"] == "per_task_od"],
                num_tasks=4,
                virtual_meta={"virtual_edge_count": 0, "umcf_access_sigma": ""},
            )
            self.assertEqual(s["optimal_points"], 2)

            write_summary_csv(summary, [s])
            self.assertTrue(summary.is_file())

            png = Path(td) / "fig.png"
            plot_ablation(
                by_mode,
                title="synthetic",
                output_png=png,
                output_pdf=None,
            )
            self.assertTrue(png.is_file())


if __name__ == "__main__":
    unittest.main()
