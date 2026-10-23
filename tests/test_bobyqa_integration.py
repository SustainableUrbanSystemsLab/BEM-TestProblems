"""Run native BOBYQA searches from the ten canonical problem midpoints."""

import math

import pytest

from bem_testproblems import get_problem, make_objective
from bem_testproblems.problems import PROBLEM_IDS


@pytest.mark.integration
@pytest.mark.parametrize("problem_id", PROBLEM_IDS, ids=lambda number: f"P{number}")
def test_bobyqa_from_midpoint(problem_id, tmp_path):
    from pdfo import pdfo

    problem = get_problem(problem_id)
    objective = make_objective(problem, energyplus_version="26.2.0", output_root=tmp_path)
    initial_value = objective(problem.midpoint)
    result = pdfo(
        objective,
        x0=problem.midpoint,
        bounds=problem.bounds,
        method="bobyqa",
        options={"maxfev": 100, "honour_x0": True},
    )

    assert result.method == "bobyqa"
    assert 0 < result.nfev <= 100
    assert problem.validate(result.x)
    assert math.isfinite(result.fun)
    assert result.fun <= initial_value
