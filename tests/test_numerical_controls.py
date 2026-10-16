"""Verify recorded-failure repairs change only their explicit numerical recipe."""

import copy
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from bem_testproblems import get_problem
from bem_testproblems.models import _data_resource, legacy_token_values
from bem_testproblems.numerical_controls import refine_legacy, refine_modern
from tests.test_models import idf_objects

IDS = (1, 4, 5, 6, 10)


def _objects(path):
    return {row[0].casefold(): row for row in idf_objects(path)
            if row[0].casefold() in {
                "building", "timestep", "sizing:parameters", "convergencelimits",
                "zoneairheatbalancealgorithm"}}


@pytest.mark.parametrize("number", IDS)
def test_profile_is_explicit_frozen_and_preserves_physical_problem(number):
    base = get_problem(number)
    refined = get_problem(number, numerical_variant="convergence-refined")
    assert refined is get_problem(f"p{number}", numerical_variant="convergence-refined")
    assert refined != base and refined.definition == "numerical-variant"
    assert refined.parameters == base.parameters
    assert refined.constants == base.constants
    assert refined.weather_filename == base.weather_filename
    assert refined.fixed_parameters == base.fixed_parameters
    outputs = {"Q_h": 12.0, "Q_c": 7.0, "E_L": 8.0, "Y": 850.0,
               **{f"H_{i}": float(i) for i in range(1, 7)}, "C": 7.0,
               **{f"L_{side}": 2.0 for side in ("N", "W", "E", "S", "I")},
               "V_legacy": 3.0}
    for design in (base.midpoint, tuple(low for low, _ in base.bounds)):
        assert legacy_token_values(refined, design) == legacy_token_values(base, design)
        assert refined.outer_loss(design, outputs) == base.outer_loss(design, outputs)
        assert refined.objective_terms(design, outputs) == base.objective_terms(design, outputs)
        assert refined.outer_derivatives(design) == base.outer_derivatives(design)
    metadata = refined.provenance["numerical_variant"]
    assert metadata["name"] == "convergence-refined"
    assert metadata["historical_equivalence"] == "not claimed"
    metadata["controls"][0]["value"] = 999
    assert refined.provenance["numerical_variant"]["controls"][0]["value"] == 100
    assert "numerical_variant" not in base.provenance
    with pytest.raises(FrozenInstanceError):
        refined.definition = "historical-implementation"


@pytest.mark.parametrize("number", (2, 3, 8, 9, 13))
def test_profile_cannot_silently_apply_to_unreviewed_problem(number):
    with pytest.raises(ValueError, match="numerical variant"):
        get_problem(number, numerical_variant="convergence-refined")
    with pytest.raises(ValueError, match="numerical variant"):
        replace(get_problem(number), numerical_variant="convergence-refined")


@pytest.mark.parametrize("number", IDS)
@pytest.mark.parametrize("design_kind", ("midpoint", "lower", "upper"))
def test_legacy_profile_keeps_every_unlisted_object_and_field(number, design_kind, tmp_path):
    base = get_problem(number)
    refined = get_problem(number, numerical_variant="convergence-refined")
    design = {"midpoint": base.midpoint, "lower": tuple(b[0] for b in base.bounds),
              "upper": tuple(b[1] for b in base.bounds)}[design_kind]
    original = base.render_legacy(design, tmp_path / "canonical.idf")
    changed = refined.render_legacy(design, tmp_path / "refined.idf")
    before, after = idf_objects(original), idf_objects(changed)
    expected = list(before)
    building_index = next(i for i, row in enumerate(expected) if row[0].casefold() == "building")
    building = list(expected[building_index])
    assert building[7] == "25"
    building[7] = "100"
    expected[building_index] = tuple(building)
    if number in (4, 5):
        expected.append(("ConvergenceLimits", "1", "100", "2", "8"))
    if number in (5, 10):
        expected.append(("ZoneAirHeatBalanceAlgorithm", "AnalyticalSolution"))
    if number in (4, 5, 10):
        original_steps = "4" if number in (4, 5) else "6"
        for i, row in enumerate(expected):
            if row[0].casefold() == "timestep":
                assert row[1] == original_steps
                expected[i] = (row[0], "12")
            elif row[0].casefold() == "sizing:parameters":
                assert row[3] == original_steps
                expected[i] = (*row[:3], "12")
    assert after == expected
    assert base.render_legacy(design, tmp_path / "again.idf").read_bytes() == original.read_bytes()
    if number in (4, 5, 10):
        controls = _objects(changed)
        assert float(controls["sizing:parameters"][3]) / float(controls["timestep"][1]) == 1
        assert controls["convergencelimits"][1:] == (
            ("1", "100", "2", "8") if number in (4, 5) else ("1", "20"))


@pytest.mark.parametrize("number", IDS)
@pytest.mark.parametrize("design_kind", ("midpoint", "lower", "upper"))
def test_modern_profile_keeps_every_unlisted_object_and_field(number, design_kind, tmp_path):
    base = get_problem(number)
    refined = get_problem(number, numerical_variant="convergence-refined")
    design = {"midpoint": base.midpoint, "lower": tuple(b[0] for b in base.bounds),
              "upper": tuple(b[1] for b in base.bounds)}[design_kind]
    original = base.render_modern(design, tmp_path / "canonical.epJSON")
    changed = refined.render_modern(design, tmp_path / "refined.epJSON")
    before = json.loads(original.read_text())
    expected = copy.deepcopy(before)
    next(iter(expected["Building"].values()))["maximum_number_of_warmup_days"] = 100
    if number in (4, 5):
        expected["ConvergenceLimits"] = {"BEM convergence-refined": {
            "maximum_hvac_iterations": 100, "minimum_system_timestep": 1,
            "minimum_plant_iterations": 2, "maximum_plant_iterations": 8}}
    if number in (5, 10):
        expected["ZoneAirHeatBalanceAlgorithm"] = {"BEM convergence-refined": {
            "algorithm": "AnalyticalSolution"}}
    if number in (4, 5, 10):
        next(iter(expected["Timestep"].values()))["number_of_timesteps_per_hour"] = 12
        next(iter(expected["Sizing:Parameters"].values()))["timesteps_in_averaging_window"] = 12
    assert json.loads(changed.read_text()) == expected
    if number == 1:
        assert changed.read_bytes() == original.read_bytes()
    assert base.render_modern(design, tmp_path / "again.epJSON").read_bytes() == original.read_bytes()


@pytest.mark.parametrize("number", IDS)
@pytest.mark.parametrize("mutation", ("missing", "duplicate", "name", "cap", "tolerance"))
def test_legacy_profile_rejects_unexpected_building_before_writing(number, mutation, tmp_path):
    problem = get_problem(number)
    path = problem.render_legacy(problem.midpoint, tmp_path / "canonical.idf")
    text = path.read_text()
    building = next(row for row in idf_objects(path) if row[0].casefold() == "building")
    if mutation == "missing":
        text = text.replace("Building,", "UnexpectedBuilding,", 1)
    elif mutation == "duplicate":
        text += "\n" + ",".join(building) + ";\n"
    elif mutation == "name":
        text = text.replace(building[1] + ",", "UnexpectedBuildingName,", 1)
    else:
        fields = list(building)
        fields[7 if mutation == "cap" else 5] = "999"
        rows = [tuple(fields) if row == building else row for row in idf_objects(path)]
        text = "\n".join(",".join(row) + ";" for row in rows)
    with pytest.raises(ValueError, match="convergence-refined"):
        refine_legacy(text, number)


@pytest.mark.parametrize("number", IDS)
@pytest.mark.parametrize("mutation", ("missing", "duplicate", "name", "cap", "tolerance"))
def test_modern_profile_rejects_unexpected_building(number, mutation):
    model = json.loads(_data_resource("modern", f"problem_{number}.epJSON").read_text())
    name, building = next(iter(model["Building"].items()))
    if mutation == "missing":
        del model["Building"]
    elif mutation == "duplicate":
        model["Building"]["Unexpected duplicate"] = dict(building)
    elif mutation == "name":
        model["Building"]["Unexpected name"] = model["Building"].pop(name)
    elif mutation == "cap":
        building["maximum_number_of_warmup_days"] = 999
    else:
        building["temperature_convergence_tolerance_value"] = 0.9
    with pytest.raises(ValueError, match="convergence-refined"):
        refine_modern(model, number)


@pytest.mark.parametrize("number,kind", [(4, "ConvergenceLimits"), (5, "ConvergenceLimits"),
                                        (5, "ZoneAirHeatBalanceAlgorithm"),
                                        (10, "ZoneAirHeatBalanceAlgorithm")])
def test_refinement_refuses_existing_objects_instead_of_overwriting_them(number, kind, tmp_path):
    problem = get_problem(number)
    original = problem.render_legacy(problem.midpoint, tmp_path / "canonical.idf").read_text()
    text = original + f"\n{kind},unexpected;\n"
    with pytest.raises(ValueError, match=kind):
        refine_legacy(text, number)
    model = json.loads(_data_resource("modern", f"problem_{number}.epJSON").read_text())
    model[kind] = {"Unexpected": {}}
    with pytest.raises(ValueError, match=kind):
        refine_modern(model, number)


@pytest.mark.parametrize("number", (4, 5, 10))
@pytest.mark.parametrize("kind,field,index", [
    ("Timestep", "number_of_timesteps_per_hour", 1),
    ("Sizing:Parameters", "timesteps_in_averaging_window", 3),
])
def test_refinement_requires_original_time_resolution(number, kind, field, index, tmp_path):
    problem = get_problem(number)
    original = problem.render_legacy(problem.midpoint, tmp_path / "canonical.idf")
    rows = []
    for row in idf_objects(original):
        fields = list(row)
        if fields[0].casefold() == kind.casefold():
            fields[index] = "5"
        rows.append(fields)
    text = "\n".join(",".join(row) + ";" for row in rows)
    with pytest.raises(ValueError, match=kind):
        refine_legacy(text, number)
    model = json.loads(_data_resource("modern", f"problem_{number}.epJSON").read_text())
    next(iter(model[kind].values()))[field] = 5
    with pytest.raises(ValueError, match=kind):
        refine_modern(model, number)


def test_p6_recipe_uses_only_additional_initialization_days():
    problem = get_problem(6, numerical_variant="convergence-refined")
    controls = problem.provenance["numerical_variant"]["controls"]
    assert len(controls) == 1
    assert controls[0]["object_type"] == "Building"
    assert controls[0]["field"] == "maximum_number_of_warmup_days"
    assert controls[0]["canonical_by_engine"] == {"8.5.0": 25, "26.2.0": 25}
    assert controls[0]["value"] == 100
