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
    refine_legacy,
    refine_modern,
    repair_legacy,
    repair_modern,
    repaired_provenance,
    sizing_margin_legacy,
    sizing_margin_modern,
)

CORRECTED_PROBLEM_IDS = REPAIRED_PROBLEM_IDS
P4_SIZING_MARGIN = 0.1  # K; a physical sizing correction, not roundoff handling.
V2_SIZING_MARGIN = 0.01  # K; exceeds the observed P6 sizing drift of 0.00025 K.
WARMUP_CONVECTION = 2.5  # W/(m2 K); initialization only, released before measured days.
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


def warmup_convection_objects(surfaces, coefficient=WARMUP_CONVECTION):
    """Stabilize initialization; explicitly release every surface before measured days."""
    if not surfaces or len(surfaces) != len(set(surfaces)):
        raise ValueError("Warmup convection requires unique heat-transfer surfaces")
    names = [f"BEM_WarmupH{i:03}" for i in range(len(surfaces))]
    release = [f"SET {name} = Null" for name in names]
    lines = ["IF WarmupFlag == 1 && CurrentEnvironment > 2"]
    lines += [f"SET {name} = {coefficient}" for name in names]
    lines += ["ELSE", *release, "ENDIF"]
    return {
        "EnergyManagementSystem:Actuator": {name: {
            "actuated_component_unique_name": surface, "actuated_component_type": "Surface",
            "actuated_component_control_type": "Interior Surface Convection Heat Transfer Coefficient"}
            for name, surface in zip(names, surfaces, strict=True)},
        "EnergyManagementSystem:Program": {
            "BEM_WarmupConvection": {"lines": [{"program_line": line} for line in lines]},
            "BEM_ReleaseWarmupConvection": {"lines": [{"program_line": line} for line in release]}},
        "EnergyManagementSystem:ProgramCallingManager": {
            "BEM_WarmupConvection": {"energyplus_model_calling_point": "BeginTimestepBeforePredictor",
                                    "programs": [{"program_name": "BEM_WarmupConvection"}]},
            "BEM_ReleaseWarmupConvection": {
                "energyplus_model_calling_point": "AfterNewEnvironmentWarmUpIsComplete",
                "programs": [{"program_name": "BEM_ReleaseWarmupConvection"}]}},
    }


def corrected_v2_provenance(problem_id):
    recipe = corrected_provenance(problem_id)
    recipe["name"] = "model-corrected-v2"
    if problem_id not in (4, 5, 6):
        return recipe
    recipe["physical_model_changes"] = True
    for control in recipe["controls"]:
        if control.get("field") == "maximum_number_of_warmup_days":
            control["value"] = 365
        elif problem_id in (5, 6) and control.get("object_type") == "Sizing:Zone":
            control.update(offset_kelvin=-V2_SIZING_MARGIN,
                           operation="subtract a fixed physical sizing margin")
    recipe["controls"].append({
        "object_type": "EnergyManagementSystem:Actuator", "component_type": "Surface",
        "control_type": "Interior Surface Convection Heat Transfer Coefficient",
        "surfaces": "all rendered BuildingSurface:Detailed and FenestrationSurface:Detailed objects",
        "warmup_value_w_per_m2_k": WARMUP_CONVECTION, "measured_period_value": "Null",
        "calling_points": ["BeginTimestepBeforePredictor", "AfterNewEnvironmentWarmUpIsComplete"],
        "condition": "WarmupFlag == 1 && CurrentEnvironment > 2",
        "scope": "weather-run warmup only; the two design-day environments keep native convection",
    })
    if problem_id == 6:
        recipe["controls"].extend([
            {"object_type": "ConvergenceLimits", "field": "maximum_hvac_iterations", "value": 100,
             "canonical_by_engine": {"8.5.0": 20, "26.2.0": 20},
             "preserved_effective_defaults": {"minimum_system_timestep": 1,
                 "minimum_plant_iterations": 2, "maximum_plant_iterations": 8}},
            {"object_type": "ZoneAirHeatBalanceAlgorithm", "field": "algorithm", "value": "AnalyticalSolution",
             "canonical_by_engine": {"8.5.0": "ThirdOrderBackwardDifference", "26.2.0": "ThirdOrderBackwardDifference"}},
        ])
    return recipe


def _convection_idf(objects):
    blocks = []
    for name, row in objects["EnergyManagementSystem:Actuator"].items():
        blocks.append(f"EnergyManagementSystem:Actuator,{name},{row['actuated_component_unique_name']},"
                      f"{row['actuated_component_type']},{row['actuated_component_control_type']};")
    for name, row in objects["EnergyManagementSystem:Program"].items():
        blocks.append(f"EnergyManagementSystem:Program,{name},"
                      + ",".join(line["program_line"] for line in row["lines"]) + ";")
    for name, row in objects["EnergyManagementSystem:ProgramCallingManager"].items():
        blocks.append(f"EnergyManagementSystem:ProgramCallingManager,{name},{row['energyplus_model_calling_point']},"
                      + ",".join(program["program_name"] for program in row["programs"]) + ";")
    return "\n" + "\n".join(blocks) + "\n"


def correct_v2_legacy(text, problem_id, *, coefficient=WARMUP_CONVECTION):
    if problem_id not in (4, 5, 6):
        return correct_legacy(text, problem_id)
    if problem_id == 4:
        text = correct_legacy(text, problem_id)
    else:
        text = refine_legacy(text, problem_id)
        text = _idf_replace(text, "Building", 7, "100", 365)
        text = sizing_margin_legacy(text, V2_SIZING_MARGIN)
        if problem_id == 6:
            if _idf_objects(text, "ConvergenceLimits") or _idf_objects(text, "ZoneAirHeatBalanceAlgorithm"):
                raise ValueError("P6 v2 requires the canonical HVAC limits and zone-air algorithm")
            text += "\nConvergenceLimits,1,100,2,8;\nZoneAirHeatBalanceAlgorithm,AnalyticalSolution;\n"
    if (len(_idf_objects(text, "SizingPeriod:DesignDay")) != 2
            or _idf_objects(text, "SizingPeriod:WeatherFileDays")
            or _idf_objects(text, "SizingPeriod:WeatherFileConditionType")):
        raise ValueError("Weather-only warmup correction requires the two canonical design-day environments")
    surfaces = sorted(fields[1][1].strip()
                      for kind in ("BuildingSurface:Detailed", "FenestrationSurface:Detailed")
                      for _, fields in _idf_objects(text, kind))
    objects = warmup_convection_objects(surfaces, coefficient)
    if any(_idf_objects(text, kind) for kind in objects):
        raise ValueError("Warmup convection requires a model without existing EMS objects")
    return text + _convection_idf(objects)


def correct_v2_modern(model, problem_id, *, coefficient=WARMUP_CONVECTION):
    if problem_id not in (4, 5, 6):
        return correct_modern(model, problem_id)
    if problem_id == 4:
        correct_modern(model, problem_id)
    else:
        refine_modern(model, problem_id)
        _, building = _modern_object(model, "Building")
        building["maximum_number_of_warmup_days"] = 365
        sizing_margin_modern(model, V2_SIZING_MARGIN)
        if problem_id == 6:
            if model.get("ConvergenceLimits") or model.get("ZoneAirHeatBalanceAlgorithm"):
                raise ValueError("P6 v2 requires the canonical HVAC limits and zone-air algorithm")
            model["ConvergenceLimits"] = {"BEM v2 convergence": {
                "minimum_system_timestep": 1, "maximum_hvac_iterations": 100,
                "minimum_plant_iterations": 2, "maximum_plant_iterations": 8}}
            model["ZoneAirHeatBalanceAlgorithm"] = {"BEM v2 convergence": {"algorithm": "AnalyticalSolution"}}
    if (len(model.get("SizingPeriod:DesignDay", {})) != 2
            or model.get("SizingPeriod:WeatherFileDays") or model.get("SizingPeriod:WeatherFileConditionType")):
        raise ValueError("Weather-only warmup correction requires the two canonical design-day environments")
    surfaces = sorted(name for kind in ("BuildingSurface:Detailed", "FenestrationSurface:Detailed")
                      for name in model.get(kind, {}))
    objects = warmup_convection_objects(surfaces, coefficient)
    if set(objects).intersection(model):
        raise ValueError("Warmup convection requires a model without existing EMS objects")
    model.update(objects)


def corrected_v3_provenance(problem_id):
    """Disclose the fixed initialization correction separately from version 2."""
    recipe = corrected_v2_provenance(problem_id)
    recipe["name"] = "model-corrected-v3"
    if problem_id in (4, 5):
        for control in recipe["controls"]:
            if control.get("control_type") == "Interior Surface Convection Heat Transfer Coefficient":
                control["warmup_value_w_per_m2_k"] = 1
    elif problem_id == 10:
        recipe["controls"].append({
            "object_type": "EnergyManagementSystem:Actuator", "component_type": "Surface",
            "control_type": "Interior Surface Convection Heat Transfer Coefficient",
            "surfaces": "all rendered BuildingSurface:Detailed and FenestrationSurface:Detailed objects",
            "warmup_value_w_per_m2_k": 1, "measured_period_value": "Null",
            "calling_points": ["BeginTimestepBeforePredictor", "AfterNewEnvironmentWarmUpIsComplete"],
            "condition": "WarmupFlag == 1 && CurrentEnvironment > 2",
            "scope": "weather-run warmup only; sizing and measured-day convection unchanged",
        })
    return recipe


def correct_v3_legacy(text, problem_id):
    if problem_id in (4, 5):
        return correct_v2_legacy(text, problem_id, coefficient=1)
    text = correct_v2_legacy(text, problem_id)
    if problem_id != 10:
        return text
    if (len(_idf_objects(text, "SizingPeriod:DesignDay")) != 2
            or _idf_objects(text, "SizingPeriod:WeatherFileDays")
            or _idf_objects(text, "SizingPeriod:WeatherFileConditionType")):
        raise ValueError("Weather-only warmup correction requires the two canonical design-day environments")
    surfaces = sorted(fields[1][1].strip()
                      for kind in ("BuildingSurface:Detailed", "FenestrationSurface:Detailed")
                      for _, fields in _idf_objects(text, kind))
    return text + _convection_idf(warmup_convection_objects(surfaces, coefficient=1))


def correct_v3_modern(model, problem_id):
    if problem_id in (4, 5):
        return correct_v2_modern(model, problem_id, coefficient=1)
    correct_v2_modern(model, problem_id)
    if problem_id != 10:
        return
    if (len(model.get("SizingPeriod:DesignDay", {})) != 2
            or model.get("SizingPeriod:WeatherFileDays") or model.get("SizingPeriod:WeatherFileConditionType")):
        raise ValueError("Weather-only warmup correction requires the two canonical design-day environments")
    surfaces = sorted(name for kind in ("BuildingSurface:Detailed", "FenestrationSurface:Detailed")
                      for name in model.get(kind, {}))
    for kind, rows in warmup_convection_objects(surfaces, coefficient=1).items():
        if set(rows).intersection(model.get(kind, {})):
            raise ValueError("Warmup convection requires unique EMS object names")
        model.setdefault(kind, {}).update(rows)
