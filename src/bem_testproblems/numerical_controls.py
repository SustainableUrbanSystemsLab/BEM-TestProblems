# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Explicit numerical recipes for recorded convergence failures.

These controls define separate numerical functions. They never change the
canonical assets, decision coordinates, convergence tolerances, or objectives.
Each recipe is fixed for the selected problem; no design-dependent fallback is
performed during evaluation.
"""

import re

REFINED_PROBLEM_IDS = (1, 4, 5, 6, 10)
REPAIRED_PROBLEM_IDS = (1, 3, 4, 5, 6, 9, 10)
SIZING_MARGIN = 1e-5  # K; sizing inputs only, below the 0.004 K convergence tolerance.
_BUILDINGS = {
    1: ("office zone", 0.0040000002),
    3: ("office zone", 0.0040000002),
    4: ("Office Building", 0.004),
    5: ("Office Building", 0.004),
    6: ("Office Building", 0.004),
    9: ("Benchmark Small Office New", 0.2),
    10: ("Benchmark Large Office New", 0.2),
}


def refined_provenance(problem_id):
    """Return fresh, complete recipe metadata, including effective defaults."""
    if problem_id not in REFINED_PROBLEM_IDS:
        raise ValueError("Unsupported convergence-refined numerical variant")
    controls = [{
        "object_type": "Building",
        "object_name": _BUILDINGS[problem_id][0],
        "field": "maximum_number_of_warmup_days",
        "canonical_by_engine": {"8.5.0": 25, "26.2.0": 100 if problem_id == 1 else 25},
        "value": 100,
    }]
    if problem_id in (4, 5):
        controls.append({
            "object_type": "ConvergenceLimits",
            "field": "maximum_hvac_iterations",
            "canonical_by_engine": {"8.5.0": 20, "26.2.0": 20},
            "value": 100,
            "preserved_effective_defaults": {
                "minimum_system_timestep": 1,
                "minimum_plant_iterations": 2,
                "maximum_plant_iterations": 8,
            },
        })
    if problem_id in (5, 10):
        controls.append({
            "object_type": "ZoneAirHeatBalanceAlgorithm",
            "field": "algorithm",
            "canonical_by_engine": {
                "8.5.0": "ThirdOrderBackwardDifference",
                "26.2.0": "ThirdOrderBackwardDifference",
            },
            "value": "AnalyticalSolution",
        })
    if problem_id in (4, 5, 6, 10):
        original_steps = 4 if problem_id in (4, 5, 6) else 6
        controls.extend([
            {"object_type": "Timestep", "field": "number_of_timesteps_per_hour",
             "canonical_by_engine": {"8.5.0": original_steps, "26.2.0": original_steps},
             "value": 12},
            {"object_type": "Sizing:Parameters", "field": "timesteps_in_averaging_window",
             "canonical_by_engine": {"8.5.0": original_steps, "26.2.0": original_steps},
             "value": 12},
        ])
    return {"name": "convergence-refined", "controls": controls,
            "other_fields": "unchanged, including physical inputs and convergence tolerances",
            "selection": "fixed per problem; no design-dependent fallback",
            "historical_equivalence": "not claimed"}


def repaired_provenance(problem_id):
    if problem_id not in REPAIRED_PROBLEM_IDS:
        raise ValueError("Unsupported convergence-repaired numerical variant")
    if problem_id in (3, 9):
        recipe = {
            "controls": [{"object_type": "Building", "object_name": _BUILDINGS[problem_id][0],
                "field": "maximum_number_of_warmup_days", "value": 365 if problem_id == 9 else 100,
                "canonical_by_engine": {"8.5.0": 25, "26.2.0": 100 if problem_id == 3 else 25}}],
            "selection": "fixed per problem; no design-dependent fallback",
            "historical_equivalence": "not claimed",
        }
        if problem_id == 9:
            recipe["controls"].extend([
                {"object_type": "Timestep", "field": "number_of_timesteps_per_hour", "value": 12,
                 "canonical_by_engine": {"8.5.0": 6, "26.2.0": 6}},
                {"object_type": "Sizing:Parameters", "field": "timesteps_in_averaging_window", "value": 12,
                 "canonical_by_engine": {"8.5.0": 6, "26.2.0": 6}},
                {"object_type": "ConvergenceLimits", "field": "maximum_hvac_iterations", "value": 100,
                 "canonical_by_engine": {"8.5.0": 20, "26.2.0": 20},
                 "preserved_effective_defaults": {"minimum_system_timestep": 1,
                     "minimum_plant_iterations": 2, "maximum_plant_iterations": 8}},
                {"object_type": "ZoneAirHeatBalanceAlgorithm", "field": "algorithm", "value": "AnalyticalSolution",
                 "canonical_by_engine": {"8.5.0": "ThirdOrderBackwardDifference",
                                         "26.2.0": "ThirdOrderBackwardDifference"}},
            ])
    else:
        recipe = refined_provenance(problem_id)
    recipe["name"] = "convergence-repaired"
    if problem_id in (4, 5, 6):
        recipe["controls"].append({
            "object_type": "Sizing:Zone", "field": "zone_cooling_design_supply_air_temperature",
            "operation": "subtract a fixed numerical sizing margin", "offset_kelvin": -SIZING_MARGIN,
            "scope": "five sizing inputs only; annual supply-temperature controls unchanged",
        })
    recipe["other_fields"] = "unchanged, including annual controls, bounds, objectives and convergence tolerances"
    return recipe


def _idf_objects(text, kind):
    masked = re.sub(r"![^\r\n]*", lambda match: " " * len(match[0]), text)
    result = []
    for block in re.finditer(r"[^;]*;", masked):
        fields = list(re.finditer(r"([^,;]*)([,;])", block[0]))
        if fields and fields[0][1].strip().casefold() == kind.casefold():
            result.append((block.start(), fields))
    return result


def _idf_object(text, kind):
    matches = _idf_objects(text, kind)
    if len(matches) != 1:
        raise ValueError(f"convergence-refined requires exactly one {kind} object")
    return matches[0]


def _idf_replace(text, kind, index, expected, value):
    start, fields = _idf_object(text, kind)
    if index >= len(fields) or fields[index][1].strip() != expected:
        raise ValueError(f"convergence-refined requires the canonical {kind} field {index}")
    field = fields[index]
    token = re.search(r"\S+", field[1])
    left = start + field.start(1) + token.start()
    right = start + field.start(1) + token.end()
    return text[:left] + str(value) + text[right:]


def refine_legacy(text, problem_id):
    """Apply only checked numerical fields to one rendered original IDF."""
    refined_provenance(problem_id)
    _, building = _idf_object(text, "Building")
    name, tolerance = _BUILDINGS[problem_id]
    if (len(building) != 9 or building[1][1].strip() != name
            or float(building[4][1]) != 0.04 or float(building[5][1]) != tolerance):
        raise ValueError("convergence-refined requires the canonical Building and tolerances")
    text = _idf_replace(text, "Building", 7, "25", 100)
    if problem_id in (4, 5):
        if _idf_objects(text, "ConvergenceLimits"):
            raise ValueError("convergence-refined requires absent canonical ConvergenceLimits")
        text = text.rstrip() + "\n\nConvergenceLimits,1,100,2,8;\n"
    if problem_id in (5, 10):
        if _idf_objects(text, "ZoneAirHeatBalanceAlgorithm"):
            raise ValueError("convergence-refined requires absent canonical ZoneAirHeatBalanceAlgorithm")
        text = text.rstrip() + "\n\nZoneAirHeatBalanceAlgorithm,AnalyticalSolution;\n"
    if problem_id in (4, 5, 6, 10):
        original_steps = "4" if problem_id in (4, 5, 6) else "6"
        text = _idf_replace(text, "Timestep", 1, original_steps, 12)
        text = _idf_replace(text, "Sizing:Parameters", 3, original_steps, 12)
    return text


def _modern_object(model, kind):
    objects = model.get(kind, {})
    if len(objects) != 1:
        raise ValueError(f"convergence-refined requires exactly one {kind} object")
    return next(iter(objects.items()))


def refine_modern(model, problem_id):
    """Change the same reviewed fields in a freshly loaded modern model."""
    refined_provenance(problem_id)
    name, building = _modern_object(model, "Building")
    expected_name, tolerance = _BUILDINGS[problem_id]
    expected_cap = 100 if problem_id == 1 else 25
    if (name != expected_name or building.get("maximum_number_of_warmup_days") != expected_cap
            or building.get("loads_convergence_tolerance_value") != 0.04
            or building.get("temperature_convergence_tolerance_value") != tolerance):
        raise ValueError("convergence-refined requires the canonical Building and tolerances")
    building["maximum_number_of_warmup_days"] = 100
    if problem_id in (4, 5):
        if "ConvergenceLimits" in model:
            raise ValueError("convergence-refined requires absent canonical ConvergenceLimits")
        model["ConvergenceLimits"] = {"BEM convergence-refined": {
            "minimum_system_timestep": 1, "maximum_hvac_iterations": 100,
            "minimum_plant_iterations": 2, "maximum_plant_iterations": 8,
        }}
    if problem_id in (5, 10):
        if "ZoneAirHeatBalanceAlgorithm" in model:
            raise ValueError("convergence-refined requires absent canonical ZoneAirHeatBalanceAlgorithm")
        model["ZoneAirHeatBalanceAlgorithm"] = {"BEM convergence-refined": {
            "algorithm": "AnalyticalSolution",
        }}
    if problem_id in (4, 5, 6, 10):
        original_steps = 4 if problem_id in (4, 5, 6) else 6
        for kind, field in (("Timestep", "number_of_timesteps_per_hour"),
                            ("Sizing:Parameters", "timesteps_in_averaging_window")):
            _, record = _modern_object(model, kind)
            if record.get(field) != original_steps:
                raise ValueError(
                    f"convergence-refined requires canonical {kind}.{field}={original_steps}")
            record[field] = 12


def repair_legacy(text, problem_id):
    """Apply the fixed convergence recipe and explicit cooling sizing margin."""
    if problem_id in (3, 9):
        _, building = _idf_object(text, "Building")
        name, tolerance = _BUILDINGS[problem_id]
        if (building[1][1].strip() != name or float(building[4][1]) != 0.04
                or float(building[5][1]) != tolerance):
            raise ValueError("convergence-repaired requires the canonical Building and tolerances")
        text = _idf_replace(text, "Building", 7, "25", 365 if problem_id == 9 else 100)
        if problem_id == 9:
            text = _idf_replace(text, "Timestep", 1, "6", 12)
            text = _idf_replace(text, "Sizing:Parameters", 3, "6", 12)
            text = _idf_replace(text, "ConvergenceLimits", 2, "20", 100)
            if _idf_objects(text, "ZoneAirHeatBalanceAlgorithm"):
                raise ValueError("convergence-repaired requires the canonical zone-air algorithm")
            text += "\nZoneAirHeatBalanceAlgorithm,AnalyticalSolution;\n"
        return text
    text = refine_legacy(text, problem_id)
    if problem_id not in (4, 5, 6):
        return text
    objects = _idf_objects(text, "Sizing:Zone")
    if len(objects) != 5:
        raise ValueError("convergence-repaired requires five Sizing:Zone objects")
    for start, fields in reversed(objects):
        if fields[2][1].strip() != "SupplyAirTemperature" or not 12 <= float(fields[3][1]) <= 18:
            raise ValueError("convergence-repaired requires canonical cooling sizing inputs")
        field = fields[3]
        token = re.search(r"\S+", field[1])
        left, right = start + field.start(1) + token.start(), start + field.start(1) + token.end()
        text = text[:left] + repr(float(field[1]) - SIZING_MARGIN) + text[right:]
    return text


def repair_modern(model, problem_id):
    if problem_id in (3, 9):
        name, building = _modern_object(model, "Building")
        expected_name, tolerance = _BUILDINGS[problem_id]
        expected_cap = 100 if problem_id == 3 else 25
        if (name != expected_name or building.get("maximum_number_of_warmup_days") != expected_cap
                or building.get("loads_convergence_tolerance_value") != 0.04
                or building.get("temperature_convergence_tolerance_value") != tolerance):
            raise ValueError("convergence-repaired requires the canonical Building and tolerances")
        building["maximum_number_of_warmup_days"] = 365 if problem_id == 9 else 100
        if problem_id == 9:
            for kind, field, expected, value in (
                ("Timestep", "number_of_timesteps_per_hour", 6, 12),
                ("Sizing:Parameters", "timesteps_in_averaging_window", 6, 12),
                ("ConvergenceLimits", "maximum_hvac_iterations", 20, 100),
            ):
                _, row = _modern_object(model, kind)
                if row.get(field) != expected:
                    raise ValueError(f"convergence-repaired requires canonical {kind}.{field}")
                row[field] = value
            if "ZoneAirHeatBalanceAlgorithm" in model:
                raise ValueError("convergence-repaired requires the canonical zone-air algorithm")
            model["ZoneAirHeatBalanceAlgorithm"] = {"BEM convergence-repaired": {"algorithm": "AnalyticalSolution"}}
        return
    refine_modern(model, problem_id)
    if problem_id not in (4, 5, 6):
        return
    objects = model.get("Sizing:Zone", {})
    if len(objects) != 5:
        raise ValueError("convergence-repaired requires five Sizing:Zone objects")
    for row in objects.values():
        field = "zone_cooling_design_supply_air_temperature"
        if (row.get("zone_cooling_design_supply_air_temperature_input_method") != "SupplyAirTemperature"
                or not 12 <= row[field] <= 18):
            raise ValueError("convergence-repaired requires canonical cooling sizing inputs")
        row[field] -= SIZING_MARGIN
