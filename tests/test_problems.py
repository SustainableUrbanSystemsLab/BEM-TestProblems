"""Published-domain and independent outer-algebra checks; no EnergyPlus needed."""

import math

import pytest

from bem_testproblems.problems import PROBLEM_IDS, get_problem, list_problems


def test_published_continuous_problem_inventory_and_climates():
    assert tuple(p.id for p in list_problems()) == (1, 2, 3, 4, 5, 6, 8, 9, 10, 13)
    assert tuple(get_problem(i).dimension for i in PROBLEM_IDS) == (
        4,
        4,
        4,
        13,
        13,
        13,
        11,
        13,
        13,
        10,
    )
    for first, second, location in ((1, 4, "Seattle"), (2, 5, "Houston"), (3, 6, "Chicago")):
        assert location in get_problem(first).name
        assert get_problem(first).weather_filename == get_problem(second).weather_filename
    assert get_problem("p13").design_day
    assert get_problem("P8").fixed_parameters == {
        "summer_night_cooling_setpoint": 25.0,
        "cooling_supply_temperature": 12.0,
    }


@pytest.mark.parametrize("identifier", [0, 7, 11, 12, 14, 15, True, "seven", 1.0])
def test_noncontinuous_or_ambiguous_ids_are_rejected(identifier):
    with pytest.raises(ValueError):
        get_problem(identifier)


def test_domains_are_physical_and_match_paper_tables():
    assert get_problem(1).bounds == ((-180.0, 180.0), (0.1, 5.9), (0.1, 5.9), (0.2, 0.8))
    assert get_problem(4).bounds[:4] == (
        (1.224, 5.832),
        (7.344, 25.668),
        (7.344, 25.668),
        (1.224, 5.832),
    )
    assert get_problem(4).bounds[4:] == ((0.05, 1.05),) * 3 + ((100, 600),) * 3 + (
        (20, 25),
    ) * 2 + ((12, 18),)
    assert get_problem(9).bounds == ((0.8, 1.25), (1.35, 2.2)) * 4 + (
        (12, 18),
        (13, 21),
        (13, 21),
        (24, 36),
        (24, 36),
    )
    assert get_problem(9).bounds == get_problem(10).bounds
    assert get_problem(13).bounds == (
        (0.05, 0.3),
        (400, 800),
        (60, 120),
        (50, 110),
        (80, 160),
        (20, 50),
        (80, 180),
        (140, 280),
        (380, 760),
        (350, 700),
    )
    problem = get_problem(8)
    expanded = problem.expanded_vector(problem.midpoint)
    assert len(expanded) == 13
    assert expanded[10] == 25.0
    assert expanded[12] == 12.0
    assert expanded[11] == problem.midpoint[-1]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, True, "1.0", -181])
def test_invalid_coordinates_fail_before_simulation(bad):
    problem = get_problem(1)
    with pytest.raises(ValueError):
        problem.validate([bad, 3, 3, 0.5])
    with pytest.raises(ValueError):
        problem.validate([0, 3, 3])


def test_simple_loss_matches_paper_equation_5_and_derivatives():
    problem = get_problem(1)
    outputs = {"Q_h": 0.44 * 96, "Q_c": 0.77 * 96, "E_L": 96 / 3}
    assert problem.outer_loss(problem.midpoint, outputs) == pytest.approx(3.0)
    derivative = problem.outer_derivatives(problem.midpoint)
    assert derivative.output_gradient == pytest.approx(
        {"Q_h": 1 / (0.44 * 96), "Q_c": 1 / (0.77 * 96), "E_L": 3 / 96}
    )
    assert derivative.direct_gradient == (0, 0, 0, 0)
    assert all(value == 0 for row in derivative.output_hessian for value in row)


def detailed_outputs():
    return {
        **{f"H_{i}": float(i) for i in range(1, 7)},
        "C": 7,
        "L_N": 1,
        "L_W": 2,
        "L_E": 3,
        "L_S": 4,
        "L_I": 5,
        "V_legacy": 6,
    }


def test_detailed_loss_retains_explicit_room_multipliers_and_legacy_fan():
    problem = get_problem(6)
    outputs = detailed_outputs()
    expected = (21 + 3 * (7 + 5 * 1 + 2 + 3 + 5 * 4 + 5 + 2 * 6)) / 1104
    assert problem.outer_loss(problem.midpoint, outputs) == pytest.approx(expected)
    # A diagnostic actual second fan does not silently fix the old benchmark.
    assert problem.outer_loss(problem.midpoint, {**outputs, "V_other": 100000}) == pytest.approx(
        expected
    )
    weights = problem.outer_derivatives(problem.midpoint).output_gradient
    assert weights["V_legacy"] == 6 / 1104
    assert weights["L_N"] == weights["L_S"] == 15 / 1104
    assert weights["L_W"] == 3 / 1104


def test_reduced_problem_has_same_loss_and_expanded_design_as_full_problem():
    reduced, full = get_problem(8), get_problem(6)
    expanded = reduced.expanded_vector(reduced.midpoint)
    assert reduced.outer_loss(reduced.midpoint, detailed_outputs()) == full.outer_loss(
        expanded, detailed_outputs()
    )


@pytest.mark.parametrize("number", [9, 10])
def test_each_window_penalty_is_independent_and_uses_source_threshold(number):
    problem = get_problem(number)
    baseline = list(problem.midpoint)
    assert problem.outer_loss(baseline, {"Y": 100}) == 100
    for side in range(4):
        design = baseline.copy()
        design[2 * side] = 1.0
        design[2 * side + 1] = 1.54
        assert problem.outer_loss(design, {"Y": 100}) == 150
        penalty = problem.penalty_metadata(design)
        assert sum(penalty["violated"]) == 1
        assert penalty["jacobian"][side][2 * side : 2 * side + 2] == (1, -1)
    # Height 0.549 is accepted by the implementation but penalized by paper Eq.7.
    baseline[:2] = [1.0, 1.549]
    assert problem.outer_loss(baseline, {"Y": 100}) == 100
    derivative = problem.outer_derivatives(baseline)
    assert derivative.output_gradient == {"Y": 1.0}
    baseline[:2] = [1.0, 1.5488]
    assert not problem.outer_derivatives(baseline).differentiable
    assert problem.outer_derivatives(baseline).direct_gradient is None


def test_school_matches_unsimplified_original_cost_expression():
    problem = get_problem(13)
    design = problem.midpoint
    q, p = 234.567, 9.876
    expected_energy = q * (2520 * 0.6 * 0.75 / (19 - -11.5)) * 0.034 + p * 12.42
    expected_insulation = 1.4 * (255 * (0.19 * (design[0] * 100) - 0.15) / 10)
    expected_radiators = 10.5 / 0.3 * (sum(design[1:]) / 8) / 10
    assert problem.outer_loss(design, {"Q": q, "P": p}) == pytest.approx(
        expected_energy + expected_insulation + expected_radiators, rel=1e-13
    )
    derivative = problem.outer_derivatives(design)
    assert derivative.direct_gradient == (678.3,) + (0.4375,) * 9
    assert derivative.output_gradient == pytest.approx({"Q": 1.2641311475409838, "P": 12.42})


def test_missing_or_nonfinite_observables_are_not_valid_penalties():
    problem = get_problem(1)
    for outputs in ({}, {"Q_h": math.nan}, {"Q_h": 1, "Q_c": 1, "E_L": math.inf}):
        with pytest.raises(ValueError):
            problem.outer_loss(problem.midpoint, outputs)
