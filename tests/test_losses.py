"""Check known partial derivatives and reject unusable simulator observables."""

import math

import pytest

from bem_testproblems import get_problem


@pytest.mark.parametrize("number", [1, 4, 8, 9, 10, 13])
def test_outer_partial_derivatives_match_independent_perturbations(number):
    problem = get_problem(number)
    x = list(problem.midpoint)
    if problem.family == "office":
        x[:2] = [1.0, 1.5]  # Inside one penalty region, away from its jump.
    derivatives = problem.outer_derivatives(x)
    outputs = {name: 100.0 + index for index, name in enumerate(derivatives.output_gradient)}
    step = 1e-3
    for name, expected in derivatives.output_gradient.items():
        below, above = dict(outputs), dict(outputs)
        below[name] -= step
        above[name] += step
        observed = (problem.outer_loss(x, above) - problem.outer_loss(x, below)) / (2 * step)
        assert observed == pytest.approx(expected, rel=1e-7, abs=1e-9)
    for index, expected in enumerate(derivatives.direct_gradient):
        below, above = x.copy(), x.copy()
        below[index] -= step
        above[index] += step
        observed = (problem.outer_loss(above, outputs) - problem.outer_loss(below, outputs)) / (2 * step)
        assert observed == pytest.approx(expected, rel=1e-7, abs=1e-9)
    assert derivatives.differentiable
    assert len(derivatives.output_hessian) == len(outputs)
    assert all(value == 0 for row in derivatives.output_hessian for value in row)


@pytest.mark.parametrize("number", [9, 10])
def test_office_penalties_accumulate_for_all_window_combinations(number):
    problem = get_problem(number)
    for mask in range(16):
        x = list(problem.midpoint)
        for side in range(4):
            x[2 * side:2 * side + 2] = [1.0, 1.5 if mask & (1 << side) else 1.7]
        terms = problem.objective_terms(x, {"Y": 80.0})
        assert terms == {"source_energy": 80.0, "window_penalty": 40.0 * mask.bit_count()}
        assert problem.outer_loss(x, {"Y": 80.0}) == 80.0 + 40.0 * mask.bit_count()


@pytest.mark.parametrize("value", [None, object(), "not numeric", math.nan, math.inf, -math.inf])
def test_invalid_observables_raise_contextual_value_error(value):
    problem = get_problem(1)
    with pytest.raises(ValueError, match="Q_h.*finite"):
        problem.outer_loss(problem.midpoint, {"Q_h": value, "Q_c": 1, "E_L": 1})


def test_unused_diagnostics_do_not_change_outer_loss():
    problem = get_problem(4)
    outputs = {name: 1.0 for name in problem.outer_derivatives(problem.midpoint).output_gradient}
    original = problem.outer_loss(problem.midpoint, outputs)
    assert problem.outer_loss(problem.midpoint, {**outputs, "V_return": math.nan}) == original
