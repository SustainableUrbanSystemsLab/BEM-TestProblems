# SPDX-License-Identifier: MIT
"""Adapter contracts and real analytic smoke tests; no EnergyPlus invocation."""

import importlib
import json
from types import SimpleNamespace

import pytest

from bem_testproblems import replication_solvers as adapters

METHODS = ("direct", "crs2", "sbplex", "cma_es", "bobyqa", "pybobyqa")
BOUNDS = ((-2.0, 2.0), (0.0, 10.0))
START = (1.5, 8.0)


def quadratic(x):
    return (x[0] - 0.25) ** 2 + (x[1] - 3.0) ** 2


def test_registry_preserves_paper_order_then_added_bobyqas():
    metadata = adapters.solver_metadata()
    assert tuple(row["name"] for row in metadata) == adapters.SOLVER_ORDER
    assert len(metadata) == 18
    assert all(row["paper_method"] for row in metadata[:16])
    assert [row["name"] for row in metadata[16:]] == ["bobyqa", "pybobyqa"]
    assert not any(row["paper_method"] for row in metadata[16:])
    assert "unverified" in adapters.solver_metadata("cma_es")["fidelity"]
    json.dumps(metadata, allow_nan=False)
    metadata[0]["settings"]["changed"] = True
    assert "changed" not in adapters.solver_metadata("sga")["settings"]


@pytest.mark.parametrize("method", adapters.SOLVER_ORDER[:11] + ("rbfopt",))
def test_unavailable_original_methods_are_skipped_without_objective_calls(method):
    def objective(_):
        pytest.fail("An unavailable paper implementation must not evaluate the objective")

    result = adapters.solve_solver(method, objective, START, BOUNDS, 30, 123)
    assert result["status"] == "skipped"
    assert result["nfev"] == 0
    assert result["x"] is None and result["fun"] is None
    assert result["message"]
    json.dumps(result, allow_nan=False)


def test_missing_optional_dependency_is_an_explicit_skip(monkeypatch):
    real_import = adapters.import_module

    def missing(name):
        if name == "nlopt":
            raise ImportError("test missing package")
        return real_import(name)

    monkeypatch.setattr(adapters, "import_module", missing)
    result = adapters.solve_solver("DIRECT", quadratic, START, BOUNDS, 30, 123)
    assert result["status"] == "skipped" and result["nfev"] == 0
    assert "test missing package" in result["message"]


def test_incompatible_compiled_dependency_is_skipped_before_native_import(monkeypatch):
    monkeypatch.setattr(adapters, "_runtime_incompatibility", lambda _: "ABI mismatch")
    monkeypatch.setattr(adapters, "import_module", lambda _: pytest.fail("No native import"))
    result = adapters.solve_solver("bobyqa", quadratic, START, BOUNDS, 30, 123)
    assert result["status"] == "skipped" and result["nfev"] == 0
    assert result["message"] == "ABI mismatch"


@pytest.mark.parametrize("kwargs", [
    {"max_evaluations": 0}, {"max_evaluations": True}, {"max_evaluations": 1.2},
    {"seed": -1}, {"seed": True}, {"seed": 2**32},
    {"x0": (1.5,)}, {"x0": (3.0, 8.0)}, {"x0": (float("nan"), 8.0)},
    {"bounds": ((0, 0), (0, 10))}, {"bounds": ((0, float("inf")), (0, 10))},
])
def test_invalid_inputs_fail_before_optimizer_import(kwargs, monkeypatch):
    def unexpected(_):
        pytest.fail("Invalid inputs must be checked before optional imports")

    monkeypatch.setattr(adapters, "import_module", unexpected)
    inputs = dict(name="bobyqa", objective=quadratic, x0=START, bounds=BOUNDS,
                  max_evaluations=30, seed=123)
    inputs.update(kwargs)
    with pytest.raises(ValueError):
        adapters.solve_solver(**inputs)


def test_unknown_solver_does_not_silently_substitute_another_method():
    with pytest.raises(ValueError, match="Unknown solver"):
        adapters.solve_solver("ProbIQA", quadratic, START, BOUNDS, 30, 123)


@pytest.mark.parametrize("method", METHODS)
def test_real_adapter_improves_a_bounded_quadratic_and_obeys_hard_budget(method):
    if adapters._runtime_incompatibility(method):
        pytest.skip(adapters._runtime_incompatibility(method))
    pytest.importorskip(adapters.solver_metadata(method)["dependency"])
    calls = []

    def objective(x):
        assert len(x) == 2
        assert all(a <= v <= b for v, (a, b) in zip(x, BOUNDS))
        value = quadratic(x)
        calls.append((tuple(x), value))
        return value

    result = adapters.solve_solver(method, objective, START, BOUNDS, 128, 123)
    assert 0 < result["nfev"] == len(calls) <= 128
    assert result["fun"] < quadratic(START)
    assert (tuple(result["x"]), result["fun"]) in calls
    assert result["fun"] == min(value for _, value in calls)
    assert result["status"] != "skipped"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("method", METHODS)
def test_real_adapter_propagates_objective_failure_without_further_calls(method):
    if adapters._runtime_incompatibility(method):
        pytest.skip(adapters._runtime_incompatibility(method))
    pytest.importorskip(adapters.solver_metadata(method)["dependency"])
    failure = RuntimeError("strict simulator failure")
    calls = 0

    def objective(_):
        nonlocal calls
        calls += 1
        raise failure

    with pytest.raises(RuntimeError) as caught:
        adapters.solve_solver(method, objective, START, BOUNDS, 30, 123)
    assert caught.value is failure
    assert calls == 1


@pytest.mark.parametrize("method", ("crs2", "cma_es", "pybobyqa"))
def test_seeded_real_adapter_reproduces_its_trajectory(method):
    pytest.importorskip(adapters.solver_metadata(method)["dependency"])
    traces = []
    for _ in range(2):
        trace = []

        def objective(x):
            trace.append(tuple(x))
            return quadratic(x)

        adapters.solve_solver(method, objective, START, BOUNDS, 32, 0)
        traces.append(trace)
    assert traces[0] == traces[1]


@pytest.mark.parametrize("method", ("sbplex", "bobyqa", "pybobyqa"))
def test_local_adapters_preserve_the_requested_start(method):
    if adapters._runtime_incompatibility(method):
        pytest.skip(adapters._runtime_incompatibility(method))
    pytest.importorskip(adapters.solver_metadata(method)["dependency"])
    calls = []

    def objective(x):
        calls.append(tuple(x))
        return quadratic(x)

    adapters.solve_solver(method, objective, START, BOUNDS, 30, 123)
    assert calls[0] == pytest.approx(START, abs=1e-14)


def test_cma_incomplete_final_generation_does_not_exceed_budget():
    pytest.importorskip("cma")
    result = adapters.solve_solver("cma_es", quadratic, START, BOUNDS, 3, 4)
    assert result["status"] == "budget"
    assert result["nfev"] == 3


def test_native_guard_preserves_external_budget_exception_and_stops(monkeypatch):
    class ForcedStop(Exception):
        pass

    class RoundoffLimited(Exception):
        pass

    class ExternalBudgetExceeded(Exception):
        pass

    class NativeOptimizer:
        def __init__(self, *args):
            self.callback = None
            self.stopped = False

        def set_lower_bounds(self, _):
            pass

        def set_upper_bounds(self, _):
            pass

        def set_maxeval(self, _):
            pass

        def set_min_objective(self, callback):
            self.callback = callback

        def force_stop(self):
            self.stopped = True

        def optimize(self, x):
            self.callback(x, [])
            assert self.stopped
            self.callback(x, [])  # No new user call while the native optimizer unwinds.
            raise ForcedStop

    fake = SimpleNamespace(opt=NativeOptimizer, GN_CRS2_LM=1, srand=lambda _: None,
                           ForcedStop=ForcedStop, RoundoffLimited=RoundoffLimited)
    real_import = importlib.import_module
    monkeypatch.setattr(adapters, "import_module", lambda n: fake if n == "nlopt"
                        else real_import(n))
    failure = ExternalBudgetExceeded("outer counted budget")

    def objective(_):
        raise failure

    with pytest.raises(ExternalBudgetExceeded) as caught:
        adapters.solve_solver("crs2", objective, START, BOUNDS, 30, 123)
    assert caught.value is failure


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_objective_is_rejected_after_one_call(value):
    pytest.importorskip("cma")
    calls = []

    def objective(x):
        calls.append(x)
        return value

    with pytest.raises(ValueError, match="nonfinite value"):
        adapters.solve_solver("cma_es", objective, START, BOUNDS, 20, 123)
    assert len(calls) == 1


@pytest.mark.parametrize("method", ("bobyqa", "pybobyqa"))
def test_undersized_interpolation_budget_is_rejected_without_objective_calls(method):
    pytest.importorskip(adapters.solver_metadata(method)["dependency"])

    def objective(_):
        pytest.fail("An impossible interpolation budget must not evaluate the objective")

    with pytest.raises(ValueError, match="needs at least dimension"):
        adapters.solve_solver(method, objective, START, BOUNDS, 1, 123)


def test_pybobyqa_restores_the_callers_rng_after_objective_failure():
    pytest.importorskip("pybobyqa")
    np = pytest.importorskip("numpy")
    before = np.random.get_state()
    failure = RuntimeError("simulation rejected")

    def objective(_):
        raise failure

    with pytest.raises(RuntimeError) as caught:
        adapters.solve_solver("pybobyqa", objective, START, BOUNDS, 20, 123)
    after = np.random.get_state()
    assert caught.value is failure
    assert before[0] == after[0] and before[2:] == after[2:]
    np.testing.assert_array_equal(before[1], after[1])
