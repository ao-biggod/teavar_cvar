# -*- coding: utf-8 -*-
"""Smoke test: runners importable, CLI args parse, minimal solve if Gurobi present."""
import sys, os

_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _src not in sys.path:
    sys.path.insert(0, _src)


def _gurobi_available() -> bool:
    try:
        import gurobipy  # noqa: F401
        return True
    except ImportError:
        return False


def test_import_runners():
    from teavar_e2e.experiments import run_e2e_mainline, run_m2_gamma_frontier
    assert run_e2e_mainline is not None
    assert run_m2_gamma_frontier is not None


def test_parse_gamma_list():
    from teavar_e2e.experiments.common import parse_gamma_list
    assert parse_gamma_list("0.1,0.2,0.4") == [0.1, 0.2, 0.4]
    assert parse_gamma_list("0.5 1.0") == [0.5, 1.0]
    assert parse_gamma_list("0.3") == [0.3]


def test_mainline_runner_args():
    from teavar_e2e.experiments.run_e2e_mainline import main
    ret = main(["--beta", "0.95", "--gamma", "0.5", "--max-failed-components", "1",
                "--time-limit", "5", "--output-dir", "new_results/e2e_mainline"])
    assert ret == 0


def test_gamma_frontier_args():
    from teavar_e2e.experiments.run_m2_gamma_frontier import main
    ret = main(["--beta", "0.95", "--gamma-list", "1.0", "--max-failed-components", "1",
                "--time-limit", "5", "--output-dir", "new_results/e2e_mainline"])
    assert ret == 0


def test_build_toy2task():
    from teavar_e2e.experiments.common import build_toy2task_data
    data = build_toy2task_data(max_failed_components=1)
    assert len(data.J) == 2
    assert len(data.M) == 3
    assert len(data.S) > 0


def test_output_path():
    from teavar_e2e.experiments.common import output_path
    p = output_path("test", "new_results/e2e_mainline")
    assert "new_results" in p
    assert p.endswith(".csv")
