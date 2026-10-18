"""Physical corrections must remain explicit and preserve all unlisted fields."""

import json

import pytest

from bem_testproblems import get_problem
from tests.test_models import idf_objects


@pytest.mark.parametrize("version", ["8.5.0", "26.2.0"])
@pytest.mark.parametrize("design_kind", ["midpoint", "lower", "upper"])
def test_p4_corrected_model_changes_only_convection_sizing_and_warmup(version, design_kind, tmp_path):
    canonical = get_problem(4)
    corrected = get_problem(4, numerical_variant="model-corrected")
    design = {"midpoint": canonical.midpoint, "lower": tuple(b[0] for b in canonical.bounds),
              "upper": tuple(b[1] for b in canonical.bounds)}[design_kind]
    assert corrected.parameters == canonical.parameters
    assert corrected.constants == canonical.constants
    assert corrected.definition == "model-variant"
    assert corrected.provenance["numerical_variant"]["physical_model_changes"]
    if version == "8.5.0":
        before = canonical.render_legacy(design, tmp_path / "canonical.idf")
        after = corrected.render_legacy(design, tmp_path / "corrected.idf")
        expected = []
        for row in idf_objects(before):
            fields = list(row)
            if row[0].casefold() == "building":
                fields[7] = "365"
            elif row[0].casefold() == "surfaceconvectionalgorithm:inside":
                fields[1] = "TARP"
            elif row[0].casefold() == "sizing:zone":
                fields[3] = repr(float(fields[3]) - 0.1)
            expected.append(tuple(fields))
        assert idf_objects(after) == expected
    else:
        before = canonical.render_modern(design, tmp_path / "canonical.epJSON")
        after = corrected.render_modern(design, tmp_path / "corrected.epJSON")
        expected = json.loads(before.read_text())
        next(iter(expected["Building"].values()))["maximum_number_of_warmup_days"] = 365
        next(iter(expected["SurfaceConvectionAlgorithm:Inside"].values()))["algorithm"] = "TARP"
        for row in expected["Sizing:Zone"].values():
            row["zone_cooling_design_supply_air_temperature"] -= 0.1
        assert json.loads(after.read_text()) == expected


@pytest.mark.parametrize("number", [1, 3, 5, 6, 9])
def test_other_corrected_profiles_keep_the_reviewed_numerical_recipe(number, tmp_path):
    numerical = get_problem(number, numerical_variant="convergence-repaired")
    corrected = get_problem(number, numerical_variant="model-corrected")
    assert not corrected.provenance["numerical_variant"]["physical_model_changes"]
    for renderer in ("render_legacy", "render_modern"):
        original = getattr(numerical, renderer)(numerical.midpoint, tmp_path / "numerical")
        changed = getattr(corrected, renderer)(corrected.midpoint, tmp_path / "corrected")
        assert original.read_bytes() == changed.read_bytes()


def test_corrected_provenance_cannot_mutate_the_recipe():
    corrected = get_problem(4, numerical_variant="model-corrected")
    corrected.provenance["numerical_variant"]["controls"][1]["value"] = "Simple"
    assert corrected.provenance["numerical_variant"]["controls"][1]["value"] == "TARP"
    assert "numerical_variant" not in get_problem(4).provenance


@pytest.mark.parametrize("version", ["8.5.0", "26.2.0"])
@pytest.mark.parametrize("design_kind", ["midpoint", "lower", "upper"])
def test_p10_keeps_annual_controls_and_adds_only_labelled_warmup_conditioning(version, design_kind, tmp_path):
    numerical = get_problem(10)
    corrected = get_problem(10, numerical_variant="model-corrected")
    design = {"midpoint": numerical.midpoint, "lower": tuple(b[0] for b in numerical.bounds),
              "upper": tuple(b[1] for b in numerical.bounds)}[design_kind]
    assert corrected.parameters == numerical.parameters
    assert corrected.constants == numerical.constants
    if version == "8.5.0":
        before = numerical.render_legacy(design, tmp_path / "numerical.idf")
        after = corrected.render_legacy(design, tmp_path / "corrected.idf")
        expected = []
        for row in idf_objects(before):
            fields = list(row)
            if row[0].casefold() == "building":
                fields[7] = "365"
            expected.append(tuple(fields))
        expected.extend([
            ("EnergyManagementSystem:Actuator", "BEM_WarmupAvailability", "VAV WITH REHEAT", "AirLoopHVAC", "Availability Status"),
            ("EnergyManagementSystem:ProgramCallingManager", "BEM_WarmupControl", "AfterPredictorAfterHVACManagers", "BEM_WarmupConditioning"),
            ("EnergyManagementSystem:Program", "BEM_WarmupConditioning", "IF WarmupFlag == 1",
             "SET BEM_WarmupAvailability = 2", "ELSE", "SET BEM_WarmupAvailability = Null", "ENDIF"),
        ])
        assert idf_objects(after) == expected
    else:
        before = numerical.render_modern(design, tmp_path / "numerical.epJSON")
        after = corrected.render_modern(design, tmp_path / "corrected.epJSON")
        expected = json.loads(before.read_text())
        next(iter(expected["Building"].values()))["maximum_number_of_warmup_days"] = 365
        from bem_testproblems.model_controls import warmup_control_objects

        expected.update(warmup_control_objects())
        assert json.loads(after.read_text()) == expected
