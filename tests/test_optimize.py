"""Exercise the public optimizer against a bounded analytic objective."""

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import bem_testproblems.optimize as optimize
from bem_testproblems import get_problem
from bem_testproblems.optimize import solve


class Quadratic:
    dimension = 2
    bounds = ((-2.0, 2.0), (-2.0, 2.0))
    midpoint = (0.0, 0.0)

    def __init__(self):
        self.calls = 0

    def evaluate(self, x, *, runner, weather):
        self.calls += 1
        assert all(lo <= value <= hi for value, (lo, hi) in zip(x, self.bounds, strict=True))
        return (x[0] - 0.4) ** 2 + (x[1] + 0.8) ** 2


def test_bobyqa_solves_and_honors_budget():
    pytest.importorskip("pdfo")
    problem = Quadratic()
    result = solve(problem, runner=None, max_evaluations=30)
    assert result.fun < 1e-12
    assert 0 < problem.calls <= 30
    assert result.nfev == problem.calls


@pytest.mark.parametrize("budget", [True, 1.5, 0, 3, 4])
def test_invalid_budget(budget):
    with pytest.raises(ValueError):
        solve(Quadratic(), runner=None, max_evaluations=budget)


@pytest.mark.parametrize("x0", [(0,), (3, 0), (float("nan"), 0)])
def test_invalid_start(x0):
    with pytest.raises(ValueError):
        solve(Quadratic(), runner=None, x0=x0)


def test_simulator_errors_propagate():
    pytest.importorskip("pdfo")

    class Broken(Quadratic):
        def evaluate(self, x, **kwargs):
            raise RuntimeError("simulation failed")

    with pytest.raises(RuntimeError, match="simulation failed"):
        solve(Broken(), runner=None, max_evaluations=10)


def test_benchmark_setup_is_bound_once_before_solver_receives_physical_vectors(monkeypatch):
    problem = get_problem(1)
    runner = object()
    weather = object()
    bindings = []
    evaluations = []
    trial = [45.0, 2.5, 4.5, 0.3]

    def bind(selected, **kwargs):
        bindings.append((selected, kwargs))

        def objective(x):
            evaluations.append(tuple(x))
            return sum(x)

        return objective

    def fake_pdfo(objective, start, *, bounds, method, options):
        assert bindings == [(problem, {"runner": runner, "weather": weather})]
        assert start == problem.midpoint
        assert bounds == problem.bounds
        assert method == "bobyqa"
        assert options == {
            "maxfev": 20, "npt": 9, "scale": True, "quiet": True, "honour_x0": True,
        }
        objective(start)
        return SimpleNamespace(x=trial, fun=objective(trial), nfev=2)

    monkeypatch.setattr(optimize, "make_objective", bind)
    monkeypatch.setitem(sys.modules, "pdfo", SimpleNamespace(pdfo=fake_pdfo))
    result = solve(problem, runner=runner, weather=weather, max_evaluations=20)
    assert result.fun == sum(trial)
    assert evaluations == [problem.midpoint, tuple(trial)]
    assert len(bindings) == 1


def test_missing_benchmark_setup_fails_before_entering_solver(monkeypatch):
    expected = FileNotFoundError("Missing project-local EnergyPlus; run the installer")

    def bind(*args, **kwargs):
        raise expected

    def forbidden_solver(*args, **kwargs):
        pytest.fail("Setup errors must not enter a compiled optimizer callback")

    monkeypatch.setattr(optimize, "make_objective", bind)
    monkeypatch.setitem(sys.modules, "pdfo", SimpleNamespace(pdfo=forbidden_solver))
    with pytest.raises(FileNotFoundError) as error:
        solve(get_problem(1), max_evaluations=20)
    assert error.value is expected


@pytest.mark.parametrize("failure", [RuntimeError("simulation failed"), KeyboardInterrupt("stop")])
def test_callback_failure_stops_future_simulations_and_reraises_original(monkeypatch, failure):
    calls = []

    class Broken(Quadratic):
        def evaluate(self, x, **kwargs):
            calls.append(tuple(x))
            raise failure

    def fake_pdfo(objective, start, **kwargs):
        # Fortran must receive a numeric sentinel, never a Python exception.
        assert all(value != value for value in [objective(start), objective(start), objective(start)])
        return object()

    monkeypatch.setitem(sys.modules, "pdfo", SimpleNamespace(pdfo=fake_pdfo))
    with pytest.raises(type(failure)) as error:
        solve(Broken(), max_evaluations=10)
    assert error.value is failure
    assert calls == [(0.0, 0.0)]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_scalar_objectives_are_rejected_after_solver_unwinds(monkeypatch, value):
    class Nonfinite(Quadratic):
        def evaluate(self, x, **kwargs):
            return value

    monkeypatch.setitem(sys.modules, "pdfo", SimpleNamespace(
        pdfo=lambda objective, start, **kwargs: objective(start),
    ))
    with pytest.raises(ValueError, match="nonfinite objective"):
        solve(Nonfinite(), max_evaluations=10)


def test_optional_solver_import_error_has_actionable_installation_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "pdfo", None)
    with pytest.raises(ImportError, match=r"bem-testproblems\[optimize\]"):
        solve(Quadratic())


@pytest.mark.parametrize("dimension", [2, 4, 13])
def test_smallest_budget_is_a_hard_cap_with_real_pdfo(dimension):
    pytest.importorskip("pdfo")

    class Problem:
        bounds = ((-1.0, 1.0),) * dimension
        midpoint = (0.0,) * dimension

        def __init__(self):
            self.dimension = dimension
            self.calls = 0

        def evaluate(self, x, **kwargs):
            self.calls += 1
            return sum((value - 0.2) ** 2 for value in x)

    problem = Problem()
    budget = dimension + 3
    result = solve(problem, max_evaluations=budget)
    assert 0 < problem.calls <= budget
    assert result.nfev == problem.calls


def test_real_pdfo_first_evaluates_the_requested_near_bound_start():
    pytest.importorskip("pdfo")
    points = []

    class Problem(Quadratic):
        def evaluate(self, x, **kwargs):
            points.append(tuple(float(value) for value in x))
            return super().evaluate(x, **kwargs)

    problem = Problem()
    start = (1.99, -1.99)
    result = solve(problem, x0=start, max_evaluations=20)
    assert points[0] == start
    assert len(points) == result.nfev <= 20


def test_solver_cannot_evaluate_beyond_the_public_budget(monkeypatch):
    problem = Quadratic()
    budget = 5

    def overrun(objective, start, **kwargs):
        for _ in range(budget + 2):
            objective(start)
        return object()

    monkeypatch.setitem(sys.modules, "pdfo", SimpleNamespace(pdfo=overrun))
    with pytest.raises(RuntimeError, match="evaluation budget"):
        solve(problem, max_evaluations=budget)
    assert problem.calls == budget


ENDPOINT_CASES = json.loads((Path(__file__).parents[1] / "reference" /
                            "pdfo-endpoint-cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", ENDPOINT_CASES, ids=lambda case: case["case_id"])
def test_public_solve_replays_saved_failures_through_the_feasible_endpoint(case, monkeypatch):
    pytest.importorskip("pdfo")
    problem = get_problem(case["problem"])
    calls = []

    class EndOfSavedTrace(Exception):
        pass

    end = EndOfSavedTrace("No objective was measured beyond this saved prefix")

    def objective(x):
        problem.validate(x)
        index = len(calls)
        calls.append(tuple(x))
        if index < len(case["observations"]):
            observation = case["observations"][index]
            assert tuple(x) == pytest.approx(observation["x"], rel=1e-14, abs=1e-14)
            return observation["f"]
        assert index == len(case["observations"])
        assert tuple(x) == pytest.approx(case["expected_evaluated_x"], rel=1e-14, abs=1e-14)
        for entry in case["roundoff"]:
            assert x[entry["index"]] == entry["endpoint"]
        raise end

    monkeypatch.setattr(optimize, "make_objective", lambda *args, **kwargs: objective)
    with pytest.raises(EndOfSavedTrace) as caught:
        solve(problem, x0=case["x0"], max_evaluations=case["budget"])
    assert caught.value is end
    assert len(calls) == len(case["observations"]) + 1
    assert calls[0] == pytest.approx(case["x0"], rel=1e-14, abs=1e-14)
    with pytest.raises(ValueError):
        problem.validate(case["rejected_proposal"])


@pytest.mark.parametrize("bound,direction", [(1.224, -math.inf), (5.832, math.inf)])
def test_public_solve_returns_the_feasible_evaluated_endpoint_and_optimize_result_type(
    monkeypatch, bound, direction
):
    np = pytest.importorskip("numpy")
    scipy = pytest.importorskip("scipy.optimize")
    calls = []

    class Box(Quadratic):
        bounds = ((1.224, 5.832), (0.05, 1.05))
        midpoint = (3., 0.5)

        def evaluate(self, x, **kwargs):
            calls.append(tuple(x))
            return super().evaluate(x, **kwargs)

    raw = np.array([math.nextafter(bound, direction), 0.5])
    native = scipy.OptimizeResult()

    def pdfo(objective, *args, **kwargs):
        native.update(x=raw.copy(), fun=objective(raw), nfev=1)
        return native

    monkeypatch.setitem(sys.modules, "pdfo", SimpleNamespace(pdfo=pdfo))
    result = solve(Box(), max_evaluations=8)
    assert result is native and isinstance(result, scipy.OptimizeResult)
    assert isinstance(result.x, np.ndarray)
    assert calls == [(bound, 0.5)]
    assert tuple(result.x) == calls[0]
    assert result.nfev == 1


@pytest.mark.parametrize("bad", [
    (math.nextafter(math.nextafter(1.224, -math.inf), -math.inf), 0.5),
    (math.nextafter(math.nextafter(5.832, math.inf), math.inf), 0.5),
    (float("nan"), 0.5), (float("inf"), 0.5), (-float("inf"), 0.5),
    (1.223, 0.5), (5.833, 0.5), (2.,), (2., 0.5, 0.5),
])
def test_public_solver_rejects_invalid_proposals_before_any_objective_call(monkeypatch, bad):
    class Box(Quadratic):
        bounds = ((1.224, 5.832), (0.05, 1.05))
        midpoint = (3., 0.5)

        def evaluate(self, *args, **kwargs):
            pytest.fail("Invalid solver proposals must not reach the objective")

    def pdfo(objective, start, **kwargs):
        assert math.isnan(objective(bad))
        assert math.isnan(objective(start))  # The original failure remains latched.
        return object()

    monkeypatch.setitem(sys.modules, "pdfo", SimpleNamespace(pdfo=pdfo))
    with pytest.raises(ValueError, match="nonfinite or out-of-bounds"):
        solve(Box(), max_evaluations=8)
