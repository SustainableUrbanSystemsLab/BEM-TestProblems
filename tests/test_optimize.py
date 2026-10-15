"""Exercise the public optimizer against a bounded analytic objective."""

import pytest

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
