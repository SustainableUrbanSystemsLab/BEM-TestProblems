# SPDX-License-Identifier: MIT
"""Opt-in physical model corrections, separate from historical benchmarks.

These fixed recipes change P4 convection/sizing and P10 warmup HVAC availability.
They preserve strict diagnostics, design coordinates, and objective equations.
"""

from .numerical_controls import (
    REPAIRED_PROBLEM_IDS,
    _idf_objects,
    _idf_replace,
    _modern_object,
    repair_legacy,
    repair_modern,
    repaired_provenance,
    sizing_margin_legacy,
    sizing_margin_modern,
)

CORRECTED_PROBLEM_IDS = REPAIRED_PROBLEM_IDS
P4_SIZING_MARGIN = 0.1  # K; a physical sizing correction, not roundoff handling.
_WARMUP_LINES = ("IF WarmupFlag == 1", "SET BEM_WarmupAvailability = 2", "ELSE",
                 "SET BEM_WarmupAvailability = Null", "ENDIF")


def warmup_control_objects():
    """Condition the air loop during warmup; release it for every measured day."""
    return {
        "EnergyManagementSystem:Actuator": {"BEM_WarmupAvailability": {
            "actuated_component_unique_name": "VAV WITH REHEAT", "actuated_component_type": "AirLoopHVAC",
            "actuated_component_control_type": "Availability Status"}},
        "EnergyManagementSystem:Program": {"BEM_WarmupConditioning": {
            "lines": [{"program_line": line} for line in _WARMUP_LINES]}},
        "EnergyManagementSystem:ProgramCallingManager": {"BEM_WarmupControl": {
            "energyplus_model_calling_point": "AfterPredictorAfterHVACManagers",
            "programs": [{"program_name": "BEM_WarmupConditioning"}]}},
    }


def corrected_provenance(problem_id):
    if problem_id not in CORRECTED_PROBLEM_IDS:
        raise ValueError("Unsupported model-corrected variant")
    recipe = repaired_provenance(problem_id)
    if problem_id == 4:
        recipe["controls"] = [
            {"object_type": "Building", "field": "maximum_number_of_warmup_days",
             "canonical_by_engine": {"8.5.0": 25, "26.2.0": 25}, "value": 365},
            {"object_type": "SurfaceConvectionAlgorithm:Inside", "field": "algorithm",
             "canonical_by_engine": {"8.5.0": "CeilingDiffuser", "26.2.0": "CeilingDiffuser"}, "value": "TARP"},
            {"object_type": "Sizing:Zone", "field": "zone_cooling_design_supply_air_temperature",
             "operation": "subtract a fixed physical sizing margin", "offset_kelvin": -P4_SIZING_MARGIN,
             "scope": "five sizing inputs; annual supply-temperature controls unchanged"},
        ]
    elif problem_id == 10:
        recipe["controls"] = [
            {"object_type": "Building", "field": "maximum_number_of_warmup_days", "value": 365,
             "canonical_by_engine": {"8.5.0": 25, "26.2.0": 25}},
            {"objects_added": warmup_control_objects(), "scope": "warmup initialization only; "
             "CycleOn availability during warmup, Null actuator for sizing and annual simulation"},
        ]
    recipe.update(name="model-corrected", physical_model_changes=problem_id in (4, 10),
        historical_equivalence="not claimed", other_fields="unchanged, including decision bounds, "
        "thermostat schedules, objective equations and convergence thresholds")
    return recipe


def correct_legacy(text, problem_id):
    corrected_provenance(problem_id)
    if problem_id == 4:
        text = _idf_replace(text, "Building", 7, "25", 365)
        text = _idf_replace(text, "SurfaceConvectionAlgorithm:Inside", 1, "CeilingDiffuser", "TARP")
        return sizing_margin_legacy(text, P4_SIZING_MARGIN)
    if problem_id == 10:
        if any(_idf_objects(text, kind) for kind in warmup_control_objects()):
            raise ValueError("model-corrected requires canonical P10 without EMS controls")
        text = _idf_replace(text, "Building", 7, "25", 365)
        return text + "\nEnergyManagementSystem:Actuator,BEM_WarmupAvailability,VAV WITH REHEAT," \
            "AirLoopHVAC,Availability Status;\nEnergyManagementSystem:ProgramCallingManager," \
            "BEM_WarmupControl,AfterPredictorAfterHVACManagers,BEM_WarmupConditioning;\n" \
            "EnergyManagementSystem:Program,BEM_WarmupConditioning,\n" + ",\n".join(_WARMUP_LINES) + ";\n"
    return repair_legacy(text, problem_id)


def correct_modern(model, problem_id):
    corrected_provenance(problem_id)
    if problem_id == 4:
        _, building = _modern_object(model, "Building")
        _, convection = _modern_object(model, "SurfaceConvectionAlgorithm:Inside")
        if building.get("maximum_number_of_warmup_days") != 25 or convection.get("algorithm") != "CeilingDiffuser":
            raise ValueError("model-corrected requires canonical P4 warmup and convection controls")
        building["maximum_number_of_warmup_days"] = 365
        convection["algorithm"] = "TARP"
        sizing_margin_modern(model, P4_SIZING_MARGIN)
        return
    if problem_id == 10:
        _, building = _modern_object(model, "Building")
        objects = warmup_control_objects()
        if building.get("maximum_number_of_warmup_days") != 25 or set(objects).intersection(model):
            raise ValueError("model-corrected requires canonical P10 warmup and absent EMS controls")
        building["maximum_number_of_warmup_days"] = 365
        model.update(objects)
        return
    repair_modern(model, problem_id)
