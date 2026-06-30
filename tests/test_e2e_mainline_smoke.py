# -*- coding: utf-8 -*-
"""Smoke test: verify the src/teavar_e2e package can be imported and
M2-C-Cost model can be built (Gurobi-dependent solve is optional)."""
import sys, os

# Ensure src/ is importable
_src = os.path.join(os.path.dirname(__file__), "..", "src")
_src = os.path.abspath(_src)
if _src not in sys.path:
    sys.path.insert(0, _src)


def _gurobi_available() -> bool:
    try:
        import gurobipy  # noqa: F401
        return True
    except ImportError:
        return False


def test_import_data():
    """Toy data files importable."""
    from teavar_e2e.data.toy_te_data import ToyTEData, build_toy_te_dataset
    from teavar_e2e.data.toy_two_task_independent_data import TwoTaskIndependentData
    from teavar_e2e.data.validate_toy_te import validate_toy_te_data
    assert ToyTEData is not None
    assert TwoTaskIndependentData is not None


def test_import_models():
    """M0/M1/M2 models importable (no solve)."""
    from teavar_e2e.models import m0_models, m1_models, m2_models, m2_cost_models
    assert m0_models is not None
    assert m1_models is not None
    assert m2_models is not None
    assert m2_cost_models is not None


def test_build_toy_te():
    """ToyTE dataset builds without error."""
    from teavar_e2e.data.toy_te_data import build_toy_te_dataset
    from teavar_e2e.data.validate_toy_te import validate_toy_te_data
    data = build_toy_te_dataset()
    result = validate_toy_te_data(data)
    assert result["ok"], f"validation failed: {result.get('summary', '')[:200]}"


def test_build_toy_two_task():
    """TwoTaskIndependent data builds without error."""
    from teavar_e2e.data.toy_two_task_independent_data import (
        build_toy_2task_independent_v1,
    )
    data = build_toy_2task_independent_v1(max_failed_components=2)
    assert len(data.J) == 2
    assert len(data.M) == 3
    assert len(data.S) > 0


def test_build_m2_cost_model():
    """M2-C-Cost model builds (no solve)."""
    if not _gurobi_available():
        return  # optional
    from teavar_e2e.data.toy_two_task_independent_data import (
        build_toy_2task_independent_v1,
    )
    from teavar_e2e.models.m2_cost_models import build_m2_c_cost_model
    data = build_toy_2task_independent_v1(max_failed_components=2)
    model = build_m2_c_cost_model(data, gamma=0.2, quiet=True)
    assert model is not None
    model.dispose()
