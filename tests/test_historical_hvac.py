"""The compatibility option must preserve the base experiment and remain explicit."""

import json

import pytest

from bem_testproblems import get_problem
from bem_testproblems.historical_hvac import apply_historical_hvac


@pytest.mark.parametrize("number", [6, 8])
@pytest.mark.parametrize("position", ["midpoint", "lower", "upper"])
def test_historical_hvac_preserves_legacy_inputs_and_non_ems_modern_fields(number, position, tmp_path):
    base = get_problem(number, numerical_variant="model-corrected-v3" if number == 6 else None)
    changed = get_problem(number, numerical_variant="historical-hvac")
    x = {"midpoint": base.midpoint, "lower": [a for a, b in base.bounds],
         "upper": [b for a, b in base.bounds]}[position]
    assert changed.parameters == base.parameters
    assert changed.constants == base.constants
    assert changed.fixed_parameters == base.fixed_parameters
    old = base.render_legacy(x, tmp_path / "old.idf")
    new = changed.render_legacy(x, tmp_path / "new.idf")
    assert new.read_bytes() == old.read_bytes()
    old = json.loads(base.render_modern(x, tmp_path / "old.epJSON").read_text(encoding="utf-8"))
    new = json.loads(changed.render_modern(x, tmp_path / "new.epJSON").read_text(encoding="utf-8"))
    # Every physical field and convergence threshold outside EMS is unchanged.
    def without_ems(model):
        return {k: v for k, v in model.items() if not k.startswith("EnergyManagementSystem:")}
    assert without_ems(new) == without_ems(old)
    assert get_problem(number, numerical_variant=None).numerical_variant is None
    assert "numerical_variant" not in get_problem(number, numerical_variant=None).provenance


@pytest.mark.parametrize("modification", ["extra-design-period", "foreign-control", "different-convection"])
def test_historical_hvac_rejects_inputs_outside_the_audited_scope(modification, tmp_path):
    problem = get_problem(8, numerical_variant=None)
    path = problem.render_modern(problem.midpoint, tmp_path / "model.epJSON")
    model = json.loads(path.read_text(encoding="utf-8"))
    if modification == "extra-design-period":
        model["SizingPeriod:WeatherFileDays"] = {"extra": {}}
    elif modification == "foreign-control":
        model["EnergyManagementSystem:Program"] = {"foreign": {}}
    else:
        next(iter(model["SurfaceConvectionAlgorithm:Inside"].values()))["algorithm"] = "TARP"
    with pytest.raises(ValueError, match="Historical HVAC"):
        apply_historical_hvac(model, 8)


def test_historical_hvac_is_restricted_and_labels_its_limitations():
    with pytest.raises(ValueError, match="Unsupported numerical variant"):
        get_problem(4, numerical_variant="historical-hvac")
    problem = get_problem(6, numerical_variant="historical-hvac")
    recipe = problem.provenance["numerical_variant"]
    assert recipe["base_variant"] == "model-corrected-v3"
    assert "not claimed" in recipe["historical_equivalence"]
    recipe["convection"]["floor"][0] = 99
    assert problem.provenance["numerical_variant"]["convection"]["floor"][0] == 3.873
