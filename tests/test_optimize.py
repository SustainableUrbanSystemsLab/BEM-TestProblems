"""Exercise the public optimizer against a bounded analytic objective."""

import sys
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


@pytest.mark.parametrize("budget", [True, 1.5, 0, 3])
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
        assert options == {"maxfev": 20, "scale": True, "quiet": True}
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
