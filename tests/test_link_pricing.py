# -*- coding: utf-8 -*-
"""Pricing profiles: copo_v1 / role_transit (main default) vs uniform vs legacy."""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from b4_joint_data import load_b4_joint_data, load_joint_data
from duibi_metrics import (
    PRICING_PROFILE_COPO_V1,
    PRICING_PROFILE_LEGACY,
    PRICING_PROFILE_UNIFORM,
    build_pricing_audit_record,
    ensure_link_prices,
    link_price_for_edge,
    summarize_link_prices,
)


class LinkPricingTests(unittest.TestCase):
    def test_copo_v1_link_price_is_default(self):
        data = load_b4_joint_data(
            topology_name="B4",
            num_tasks=8,
            routing_mode="per_task_od",
            k_paths=4,
        )
        self.assertEqual(
            getattr(data, "pricing_profile", PRICING_PROFILE_COPO_V1),
            PRICING_PROFILE_COPO_V1,
        )
        self.assertEqual(data.bandwidth_price_mode, "role_transit")
        ensure_link_prices(data)
        prices = sorted(float(v) for v in data.link_price.values())
        self.assertGreater(prices[-1], prices[0])

    def test_uniform_requires_explicit_profile(self):
        data = load_b4_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
            pricing_profile=PRICING_PROFILE_UNIFORM,
            bandwidth_price_mode="uniform",
        )
        self.assertEqual(data.pricing_profile, PRICING_PROFILE_UNIFORM)
        self.assertEqual(data.bandwidth_price_mode, "uniform")
        ensure_link_prices(data)
        for e in data.E[:5]:
            self.assertAlmostEqual(float(data.link_price[e]), 1.0, places=9)

    def test_p0_loader_default_is_copo_v1(self):
        data = load_joint_data(
            topology_name="B4",
            num_tasks=8,
            routing_mode="per_task_od",
            k_paths=4,
        )
        self.assertEqual(getattr(data, "pricing_profile", PRICING_PROFILE_COPO_V1), PRICING_PROFILE_COPO_V1)
        self.assertEqual(data.bandwidth_price_mode, "role_transit")

    def test_legacy_inverse_capacity_requires_explicit_mode(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            data = load_joint_data(
                topology_name="B4",
                num_tasks=4,
                routing_mode="per_task_od",
                k_paths=2,
                pricing_profile=PRICING_PROFILE_LEGACY,
                bandwidth_price_mode="legacy_inverse_capacity",
            )
        self.assertIn("legacy_inverse_capacity", buf.getvalue())
        self.assertEqual(data.pricing_profile, PRICING_PROFILE_LEGACY)
        self.assertEqual(data.bandwidth_price_mode, "legacy_inverse_capacity")
        ensure_link_prices(data)
        e = data.E[0]
        expected = 1.0 / max(float(data.B[e]), 1.0)
        self.assertAlmostEqual(float(data.link_price[e]), expected, places=12)

    def test_copo_v1_uses_role_transit(self):
        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
            pricing_profile=PRICING_PROFILE_COPO_V1,
            bandwidth_price_scale=0.01,
        )
        self.assertEqual(data.pricing_profile, PRICING_PROFILE_COPO_V1)
        self.assertEqual(data.bandwidth_price_mode, "role_transit")
        ensure_link_prices(data)
        prices_by_pair: dict[tuple[str, str], float] = {}
        roles = getattr(data, "node_role", {})
        for e in data.E:
            u, v = e
            ru = str(roles.get(u, "")).lower()
            rv = str(roles.get(v, "")).lower()
            key = tuple(sorted((ru, rv)))
            prices_by_pair[key] = float(data.link_price[e])
        self.assertAlmostEqual(prices_by_pair[("core", "core")], 0.01, places=6)
        self.assertGreater(prices_by_pair[("aggregation", "edge_pop")], prices_by_pair[("core", "core")])

    def test_copo_v1_does_not_use_capacity(self):
        data = load_joint_data(
            topology_name="B4",
            num_tasks=4,
            routing_mode="per_task_od",
            k_paths=2,
            pricing_profile=PRICING_PROFILE_COPO_V1,
            bandwidth_price_scale=0.01,
        )
        ensure_link_prices(data)
        roles = getattr(data, "node_role", {})
        by_role_pair: dict[tuple[str, str], list[float]] = {}
        for e in data.E:
            u, v = e
            key = (str(roles.get(u, "")).lower(), str(roles.get(v, "")).lower())
            by_role_pair.setdefault(key, []).append(float(data.link_price[e]))
        for prices in by_role_pair.values():
            if len(prices) >= 2:
                self.assertAlmostEqual(prices[0], prices[1], places=12)
                break
        else:
            self.skipTest("no role pair with multiple edges on B4")

    def test_apply_topology_pricing_compat_sets_copo_v1(self):
        data = load_b4_joint_data(
            topology_name="B4",
            num_tasks=8,
            routing_mode="per_task_od",
            k_paths=4,
            apply_topology_pricing=True,
        )
        self.assertEqual(data.pricing_profile, PRICING_PROFILE_COPO_V1)
        self.assertEqual(data.bandwidth_price_mode, "role_transit")
        self.assertAlmostEqual(float(data.bandwidth_price_scale), 0.0030563617503325887, places=9)

    def test_copo_v1_calibrated_bandwidth_share_in_target_band(self):
        data = load_joint_data(
            topology_name="B4",
            num_tasks=8,
            routing_mode="per_task_od",
            k_paths=4,
            pricing_profile=PRICING_PROFILE_COPO_V1,
        )
        rec = build_pricing_audit_record(
            data,
            topology="B4",
            routing_mode="per_task_od",
            num_tasks=8,
            target_bandwidth_share=0.30,
        )
        self.assertGreaterEqual(rec["bandwidth_share"], 0.25)
        self.assertLessEqual(rec["bandwidth_share"], 0.35)
        self.assertAlmostEqual(rec["bandwidth_share"], 0.30, delta=0.05)

    def test_pricing_audit_outputs_bandwidth_share(self):
        data = load_joint_data(
            topology_name="B4",
            num_tasks=8,
            routing_mode="per_task_od",
            k_paths=4,
            pricing_profile=PRICING_PROFILE_COPO_V1,
            bandwidth_price_scale=0.01,
        )
        rec = build_pricing_audit_record(
            data,
            topology="B4",
            routing_mode="per_task_od",
            num_tasks=8,
            target_bandwidth_share=0.30,
        )
        self.assertGreater(rec["c_p_ref"], 0.0)
        self.assertGreater(rec["c_b_ref"], 0.0)
        self.assertGreater(rec["bandwidth_share"], 0.0)
        self.assertLess(rec["bandwidth_share"], 1.0)
        self.assertIsNotNone(rec["suggested_bandwidth_price_scale"])
        self.assertGreater(rec["suggested_bandwidth_price_scale"], 0.0)
        stats = summarize_link_prices(data)
        self.assertAlmostEqual(rec["price_min"], stats["price_min"])

    def test_gamma_frontier_records_link_price_mode(self):
        from run_gamma_frontier import FRONTIER_FIELDNAMES, load_p0_data

        self.assertIn("link_price_mode", FRONTIER_FIELDNAMES)
        self.assertIn("pricing_profile", FRONTIER_FIELDNAMES)
        data = load_p0_data(
            base_path="./data",
            topology="B4",
            num_tasks=4,
            k_paths=2,
            eta=1.3,
            joint_demand_scale=None,
            routing_mode="per_task_od",
            s2_derate=0.40,
            s1_link_k=4,
            s1_sigma=0.80,
            link_price_mode="uniform",
            pricing_profile="uniform",
            quiet=True,
        )
        self.assertEqual(data.bandwidth_price_mode, "uniform")
        self.assertEqual(getattr(data, "pricing_profile", ""), PRICING_PROFILE_UNIFORM)


if __name__ == "__main__":
    unittest.main()
