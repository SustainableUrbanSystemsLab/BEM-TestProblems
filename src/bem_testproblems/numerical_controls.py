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
_BUILDINGS = {
    1: ("office zone", 0.0040000002),
    4: ("Office Building", 0.004),
    5: ("Office Building", 0.004),
    6: ("Office Building", 0.004),
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
    if problem_id in (4, 10):
        original_steps = 4 if problem_id == 4 else 6
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
    if problem_id in (4, 10):
        original_steps = "4" if problem_id == 4 else "6"
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
    if problem_id in (4, 10):
        original_steps = 4 if problem_id == 4 else 6
        for kind, field in (("Timestep", "number_of_timesteps_per_hour"),
                            ("Sizing:Parameters", "timesteps_in_averaging_window")):
            _, record = _modern_object(model, kind)
            if record.get(field) != original_steps:
                raise ValueError(
                    f"convergence-refined requires canonical {kind}.{field}={original_steps}")
            record[field] = 12
