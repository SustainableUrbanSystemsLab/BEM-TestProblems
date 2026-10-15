#!/usr/bin/env python3
"""Apply two documented input-compatibility repairs after official transition.

Legacy assets are never changed. Detailed-office surface reciprocity follows
the effective 8.5 resolver relationship. The school's inactive capacity-sizing
field is made explicit while preserving its physical UA and water-flow inputs.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_SOURCE = "https://github.com/NatLabRockies/EnergyPlus/blob/v8.5.0/src/EnergyPlus/"
NEW_SOURCE = "https://github.com/NatLabRockies/EnergyPlus/blob/v26.2.0/src/EnergyPlus/"


def area(surface):
    vertices = [
        tuple(vertex[f"vertex_{axis}_coordinate"] for axis in "xyz")
        for vertex in surface["vertices"]
    ]
    cross_sum = [0.0, 0.0, 0.0]
    for first, second in zip(vertices, vertices[1:] + vertices[:1]):
        cross_sum[0] += first[1] * second[2] - first[2] * second[1]
        cross_sum[1] += first[2] * second[0] - first[0] * second[2]
        cross_sum[2] += first[0] * second[1] - first[1] * second[0]
    return math.sqrt(sum(value * value for value in cross_sum)) / 2.0


def apply_compatibility(model, number):
    changes = []
    if number in (4, 5, 6):
        name, adjacent = "ZONE INTERIOR SURFACE NORTH", "ZONE NORTH SURFACE SOUTH"
        surface = model["BuildingSurface:Detailed"][name]
        other = model["BuildingSurface:Detailed"][adjacent]
        original = surface["outside_boundary_condition_object"]
        if original == adjacent:
            return changes
        if (
            original != "ZONE NORTH"
            or surface["outside_boundary_condition"] != "Surface"
            or other["outside_boundary_condition"] != "Surface"
            or other["outside_boundary_condition_object"] != name
            or surface["zone_name"] != "ZONE INTERIOR"
            or other["zone_name"] != "ZONE NORTH"
            or surface["construction_name"] != other["construction_name"]
        ):
            raise ValueError(
                f"Problem {number}: unexpected historical adjacency; manual review required"
            )
        interior_area, north_area = area(surface), area(other)
        multiplier = model["Zone"][other["zone_name"]]["multiplier"]
        if not math.isclose(interior_area, north_area * multiplier, abs_tol=1e-10):
            raise ValueError(
                f"Problem {number}: interzone areas do not match the original multiplier relationship"
            )
        surface["outside_boundary_condition_object"] = adjacent
        changes.append(
            {
                "path": ["BuildingSurface:Detailed", name, "outside_boundary_condition_object"],
                "before": original,
                "after": adjacent,
                "reason": "Make the effective EnergyPlus 8.5 reciprocal surface relationship explicit before 26.2 validates raw surface names. The 8.5 resolver sets the opposing surface pointer while processing the existing NorthSouth-to-InteriorNorth reference.",
                "evidence": {
                    "interior_surface_area_m2": interior_area,
                    "north_surface_area_m2": north_area,
                    "north_zone_multiplier": multiplier,
                    "construction": surface["construction_name"],
                    "geometry_preserved": True,
                    "geometry_caveat": "Original zone-relative surfaces are not coincident. This repair preserves their geometry and the historical solver relationship; it does not reconstruct the building.",
                },
                "source": OLD_SOURCE + "SurfaceGeometry.cc#L1330-L1505",
            }
        )
    if number == 13:
        if model.get("Sizing:Zone") or any(
            value.get("do_zone_sizing_calculation", "No") != "No"
            for value in model.get("SimulationControl", {}).values()
        ):
            raise ValueError(
                "School compatibility repair requires the historical no-zone-sizing configuration"
            )
        radiators = model["ZoneHVAC:Baseboard:Convective:Water"]
        if len(radiators) != 9:
            raise ValueError("School compatibility repair expects exactly nine original radiators")
        for name, radiator in radiators.items():
            original = radiator["heating_design_capacity"]
            if original == 0:
                continue
            if (
                original != "Autosize"
                or radiator["heating_design_capacity_method"] != "HeatingDesignCapacity"
                or not isinstance(radiator["u_factor_times_area_value"], (int, float))
                or not radiator["u_factor_times_area_value"] > 0
                or not isinstance(radiator["maximum_water_flow_rate"], (int, float))
                or not radiator["maximum_water_flow_rate"] > 0
            ):
                raise ValueError(f"School radiator {name}: UA and flow must remain hard-sized")
            radiator["heating_design_capacity"] = 0.0
            changes.append(
                {
                    "path": [
                        "ZoneHVAC:Baseboard:Convective:Water",
                        name,
                        "heating_design_capacity",
                    ],
                    "before": original,
                    "after": 0.0,
                    "reason": "Explicit inactive sizing-field value. With hard UA, hard maximum water flow and no zone sizing, both 8.5 and 26.2 bypass capacity sizing. Version 26.2 newly checks an unused Autosize capacity at startup; runtime heat transfer depends on UA and water flow, so this field does not cap heat output.",
                    "preserved_fields": ["u_factor_times_area_value", "maximum_water_flow_rate"],
                    "source": [
                        OLD_SOURCE + "BaseboardRadiator.cc#L692-L789",
                        NEW_SOURCE + "BaseboardRadiator.cc#L590-L708",
                        NEW_SOURCE + "BaseboardRadiator.cc#L908-L917",
                        NEW_SOURCE + "BaseboardRadiator.cc#L965-L1030",
                    ],
                }
            )
    return changes


def repair_file(path, number):
    raw = path.read_bytes()
    model = json.loads(raw)
    changes = apply_compatibility(model, number)
    if not changes:
        return 0
    sidecar = path.with_suffix(".provenance.json")
    provenance = json.loads(sidecar.read_bytes())
    provenance.setdefault("transitioned_epjson_sha256", hashlib.sha256(raw).hexdigest())
    updated = (json.dumps(model, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(updated)
    provenance.setdefault("compatibility_adjustments", []).extend(changes)
    provenance["output_sha256"] = hashlib.sha256(updated).hexdigest()
    sidecar.write_bytes((json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return len(changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modern-directory", type=Path, default=ROOT / "src/bem_testproblems/data/modern"
    )
    args = parser.parse_args()
    for number in (4, 5, 6, 13):
        path = args.modern_directory / f"problem_{number}.epJSON"
        print(f"Problem {number}: {repair_file(path, number)} documented compatibility adjustments")


if __name__ == "__main__":
    main()
