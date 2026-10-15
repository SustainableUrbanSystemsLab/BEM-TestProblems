# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Independent specification checks, not claimed published simulation fixtures.

Source: Waibel et al. (2019), doi:10.1016/j.enbuild.2019.01.048,
Tables 2–5 and 7; Eqs. (5)–(7) and (10); Sections 3.3.1–3.3.5.
The observables used below are synthetic algebra probes. They are never
represented as published input/objective pairs or as EnergyPlus runs.
"""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from bem_testproblems import get_problem
from bem_testproblems.problems import PROBLEM_IDS

ROOT = Path(__file__).resolve().parents[1]

# Physical coordinate bounds transcribed from the named paper tables.
TABLE_3 = ((-180, 180), (0.1, 5.9), (0.1, 5.9), (0.2, 0.8))
TABLE_4 = (
    (1.224, 5.832), (7.344, 25.668), (7.344, 25.668), (1.224, 5.832),
    (0.05, 1.05), (0.05, 1.05), (0.05, 1.05),
    (100, 600), (100, 600), (100, 600), (20, 25), (20, 25), (12, 18),
)
TABLE_5 = ((0.8, 1.25), (1.35, 2.2)) * 4 + (
    (12, 18), (13, 21), (13, 21), (24, 36), (24, 36),
)
TABLE_7 = (
    (0.05, 0.3), (400, 800), (60, 120), (50, 110), (80, 160),
    (20, 50), (80, 180), (140, 280), (380, 760), (350, 700),
)


def test_table_2_continuous_problem_selection_and_dimensions() -> None:
    expected = {1: 4, 2: 4, 3: 4, 4: 13, 5: 13, 6: 13, 8: 11, 9: 13, 10: 13, 13: 10}
    assert PROBLEM_IDS == tuple(expected)
    assert {number: get_problem(number).dimension for number in PROBLEM_IDS} == expected


@pytest.mark.parametrize(
    ("number", "table", "bounds"),
    [(n, 3, TABLE_3) for n in (1, 2, 3)]
    + [(n, 4, TABLE_4) for n in (4, 5, 6)]
    + [(n, 5, TABLE_5) for n in (9, 10)]
    + [(13, 7, TABLE_7)],
)
def test_paper_table_bounds_and_coordinate_order(number, table, bounds) -> None:
    problem = get_problem(number)
    assert problem.paper_table == table
    assert problem.bounds == bounds
    assert tuple(parameter.paper_symbol for parameter in problem.parameters) == tuple(
        f"x{index}" for index in range(1, len(bounds) + 1)
    )


def test_problem_8_table_4_fixed_coordinates_and_reduced_domain() -> None:
    problem = get_problem(8)
    assert problem.bounds == tuple(bound for index, bound in enumerate(TABLE_4) if index not in (10, 12))
    assert tuple(parameter.paper_symbol for parameter in problem.parameters) == tuple(
        f"x{index}" for index in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12)
    )
    expanded = problem.expanded_vector(tuple(lower for lower, _ in problem.bounds))
    assert expanded[10] == 25.0  # Paper x11: summer night cooling.
    assert expanded[12] == 12.0  # Paper x13: cooling supply air.


@pytest.mark.parametrize(
    ("number", "location"),
    [(1, "Seattle"), (2, "Houston"), (3, "Chicago"),
     (4, "Seattle"), (5, "Houston"), (6, "Chicago"), (8, "Chicago"),
     (9, "San.Francisco"), (10, "San.Francisco"), (13, "Belgrade")],
)
def test_section_3_3_climate_assignment(number, location) -> None:
    weather = get_problem(number).weather_filename
    assert location.lower() in weather.lower()
    if number in (1, 2, 3, 4, 5, 6, 8):
        assert weather.endswith("_TMY2.epw")


@pytest.mark.parametrize("number", (1, 2, 3))
def test_equation_5_simple_office_algebra(number) -> None:
    problem = get_problem(number)
    assert problem.paper_equation == 5
    assert problem.constants["heating_efficiency"] == 0.44
    assert problem.constants["cooling_efficiency"] == 0.77
    assert problem.constants["electricity_primary_factor"] == 3.0
    # Synthetic kWh inputs; 96 m2 is the preserved model/reference-code area,
    # while the weighting formula and efficiencies are from paper Eq. (5).
    outputs = {"Q_h": 1234.0, "Q_c": 567.0, "E_L": 89.0}
    expected = (Decimal(1234) / Decimal("0.44")
                + Decimal(567) / Decimal("0.77") + Decimal(3) * Decimal(89)) / Decimal(96)
    assert problem.outer_loss(problem.midpoint, outputs) == pytest.approx(float(expected))


@pytest.mark.parametrize("number", (4, 5, 6, 8))
def test_equation_6_weights_and_documented_reference_fan_exception(number) -> None:
    problem = get_problem(number)
    assert problem.paper_equation == 6
    assert problem.constants["electricity_primary_factor"] == 3.0
    assert problem.constants["gas_primary_factor"] == 1.0
    outputs = {f"H_{index}": 0.0 for index in range(1, 7)}
    outputs.update({f"L_{side}": 0.0 for side in ("N", "W", "E", "S", "I")})
    outputs.update({"C": 0.0, "V_legacy": 10.0})
    # Eq. (6) uses aggregate fan/lighting electricity. It does not identify
    # individual fan rows. The source C# duplicates the supply-fan observable
    # instead of summing separate supply/return observations. These synthetic
    # observations document that mapping; no physical paper run is inferred.
    synthetic_return_fan_kwh = 7.0
    paper_aggregate_fans = 3.0 * (10.0 + synthetic_return_fan_kwh) / 1104.0
    legacy_mapping_difference = 3.0 * (10.0 - synthetic_return_fan_kwh) / 1104.0
    assert problem.outer_loss(problem.midpoint, outputs) == pytest.approx(
        paper_aggregate_fans + legacy_mapping_difference
    )
    outputs.update({"C": 17.0, "V_legacy": 0.0, "H_1": 23.0})
    assert problem.outer_loss(problem.midpoint, outputs) == pytest.approx((3 * 17 + 23) / 1104)


@pytest.mark.parametrize("number", (9, 10))
def test_equation_7_primary_factors_reach_the_actual_idf(number) -> None:
    problem = get_problem(number)
    assert problem.paper_equation == 7
    assert problem.constants["electricity_primary_factor"] == 3.095
    assert problem.constants["gas_primary_factor"] == 1.092
    text = (ROOT / "src/bem_testproblems/data/legacy" / problem.template_filename).read_bytes().decode("cp1252")
    factors = {}
    for block in re.sub(r"!.*", "", text).split(";"):
        fields = [item.strip() for item in block.split(",")]
        if fields[0].casefold() == "fuelfactors":
            factors[fields[1]] = float(fields[4])
    assert factors["Electricity"] == 3.095
    assert factors["NaturalGas"] == 1.092


@pytest.mark.parametrize("number", (9, 10))
@pytest.mark.parametrize(("height", "legacy_factor"), ((0.5487, 1.5), (0.5494, 1.0), (0.5501, 1.0)))
def test_equation_7_boundary_discrepancy_is_explicit(number, height, legacy_factor) -> None:
    problem = get_problem(number)
    vector = list(problem.midpoint)
    vector[0], vector[1] = 0.9, 0.9 + height
    metadata = problem.penalty_metadata(vector)
    assert metadata["comparison"] == ">= 0"
    assert metadata["threshold_m"] == 0.5488
    assert metadata["paper_threshold_m"] == 0.55
    assert metadata["factor"] == legacy_factor
    assert problem.outer_loss(vector, {"Y": 100.0}) == legacy_factor * 100.0
    if height == 0.5494:
        # This height lies between the two printed/reference thresholds.
        paper_violation = Decimal("0.55") - Decimal(str(height)) >= 0
        assert paper_violation and not metadata["violated"][0]


def test_equation_10_additive_school_cost_with_reference_components() -> None:
    problem = get_problem(13)
    assert problem.paper_equation == 10
    vector = tuple(lower for lower, _ in TABLE_7)
    # Synthetic output probes; component constants below come from the cited
    # original C# (lines 143–153), not from a claimed published school run.
    q_kwh, p_kw = 24.0, 12.0
    energy = q_kwh * (2520 * 0.6 * 0.75 / (19 - -11.5)) * 0.034 + p_kw * 12.42
    insulation = 1.4 * (255 * (0.19 * (vector[0] * 100) - 0.15) / 10)
    radiators = (10.5 / 0.3) * (sum(vector[1:]) / 8) / 10
    terms = problem.objective_terms(vector, {"Q": q_kwh, "P": p_kw})
    assert terms == pytest.approx({"energy": energy, "insulation": insulation, "radiators": radiators})
    assert problem.outer_loss(vector, {"Q": q_kwh, "P": p_kw}) == pytest.approx(energy + insulation + radiators)
