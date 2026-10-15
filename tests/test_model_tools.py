# SPDX-License-Identifier: MIT
"""Small independent models protect semantic bindings and narrow modern repairs."""

import copy
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from tools import build_parameter_bindings as bindings
from tools import repair_modern_models as repairs


def vertices(width, height):
    return [{f"vertex_{axis}_coordinate": value for axis, value in zip("xyz", point)}
            for point in ((0, 0, 0), (width, 0, 0), (width, 0, height), (0, 0, height))]


def detailed_model():
    return {"Zone": {"ZONE NORTH": {"multiplier": 2}}, "BuildingSurface:Detailed": {
        "ZONE INTERIOR SURFACE NORTH": {
            "outside_boundary_condition": "Surface", "outside_boundary_condition_object": "ZONE NORTH",
            "zone_name": "ZONE INTERIOR", "construction_name": "Wall", "vertices": vertices(4, 3)},
        "ZONE NORTH SURFACE SOUTH": {
            "outside_boundary_condition": "Surface", "outside_boundary_condition_object": "ZONE INTERIOR SURFACE NORTH",
            "zone_name": "ZONE NORTH", "construction_name": "Wall", "vertices": vertices(2, 3)},
    }}


def school_model():
    return {"SimulationControl": {"Control": {"do_zone_sizing_calculation": "No"}},
            "ZoneHVAC:Baseboard:Convective:Water": {f"Radiator {n}": {
                "heating_design_capacity": "Autosize", "heating_design_capacity_method": "HeatingDesignCapacity",
                "u_factor_times_area_value": 100 + n, "maximum_water_flow_rate": .0002,
                "inlet_node_name": f"Inlet {n}", "outlet_node_name": f"Outlet {n}"}
                for n in range(9)}}


@pytest.mark.parametrize("problem", [4, 5, 6])
def test_surface_repair_changes_only_verified_reciprocal_reference(problem):
    model = detailed_model()
    original = copy.deepcopy(model)
    assert repairs.area(model["BuildingSurface:Detailed"]["ZONE NORTH SURFACE SOUTH"]) == 6
    changes = repairs.apply_compatibility(model, problem)
    original["BuildingSurface:Detailed"]["ZONE INTERIOR SURFACE NORTH"]["outside_boundary_condition_object"] = (
        "ZONE NORTH SURFACE SOUTH")
    assert model == original
    assert changes[0]["evidence"]["geometry_preserved"] is True
    assert changes[0]["evidence"]["north_zone_multiplier"] == 2
    assert repairs.apply_compatibility(model, problem) == []


@pytest.mark.parametrize("change", ["construction", "reciprocity", "area"])
def test_surface_repair_rejects_unproven_adjacency_without_mutation(change):
    model = detailed_model()
    north = model["BuildingSurface:Detailed"]["ZONE NORTH SURFACE SOUTH"]
    if change == "construction":
        north["construction_name"] = "Different wall"
    elif change == "reciprocity":
        north["outside_boundary_condition_object"] = "Another surface"
    else:
        north["vertices"] = vertices(3, 3)
    before = copy.deepcopy(model)
    with pytest.raises(ValueError, match="manual review|areas do not match"):
        repairs.apply_compatibility(model, 4)
    assert model == before


def test_school_repair_preserves_all_active_physics_and_is_idempotent():
    model = school_model()
    before = copy.deepcopy(model)
    changes = repairs.apply_compatibility(model, 13)
    assert len(changes) == 9
    for radiator in before["ZoneHVAC:Baseboard:Convective:Water"].values():
        radiator["heating_design_capacity"] = 0.0
    assert model == before
    assert repairs.apply_compatibility(model, 13) == []


@pytest.mark.parametrize("change", [
    "zone_sizing", "count", "ua", "flow", "capacity_method", "infinite_ua", "infinite_flow", "boolean_ua",
])
def test_school_repair_refuses_changed_historical_assumptions(change):
    model = school_model()
    radiators = model["ZoneHVAC:Baseboard:Convective:Water"]
    if change == "zone_sizing":
        model["Sizing:Zone"] = {"Sizing": {}}
    elif change == "count":
        radiators.pop("Radiator 8")
    elif change == "ua":
        radiators["Radiator 0"]["u_factor_times_area_value"] = "Autosize"
    elif change == "flow":
        radiators["Radiator 0"]["maximum_water_flow_rate"] = 0
    elif change == "infinite_ua":
        radiators["Radiator 0"]["u_factor_times_area_value"] = float("inf")
    elif change == "infinite_flow":
        radiators["Radiator 0"]["maximum_water_flow_rate"] = float("inf")
    elif change == "boolean_ua":
        radiators["Radiator 0"]["u_factor_times_area_value"] = True
    else:
        radiators["Radiator 0"]["heating_design_capacity_method"] = "CapacityPerFloorArea"
    with pytest.raises(ValueError, match="no-zone-sizing|nine|hard-sized"):
        repairs.apply_compatibility(model, 13)


def test_repair_file_keeps_notices_records_hashes_and_does_not_reapply(tmp_path):
    path = tmp_path / "model.epJSON"
    raw = json.dumps(school_model()).encode()
    path.write_bytes(raw)
    provenance = {"license": "BSD-3-Clause", "source_template_sha256": "0" * 64,
                  "output_sha256": hashlib.sha256(raw).hexdigest(), "additional_notices": {"notice": "retained"}}
    sidecar = path.with_suffix(".provenance.json")
    sidecar.write_text(json.dumps(provenance))
    assert repairs.repair_file(path, 13) == 9
    updated = json.loads(sidecar.read_bytes())
    assert updated["license"] == provenance["license"]
    assert updated["additional_notices"] == provenance["additional_notices"]
    assert updated["transitioned_epjson_sha256"] == hashlib.sha256(raw).hexdigest()
    assert updated["output_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(updated["compatibility_adjustments"]) == 9
    final = path.read_bytes(), sidecar.read_bytes()
    assert repairs.repair_file(path, 13) == 0
    assert final == (path.read_bytes(), sidecar.read_bytes())


def test_missing_provenance_cannot_partially_rewrite_a_model(tmp_path):
    path = tmp_path / "model.epJSON"
    path.write_text(json.dumps(school_model()))
    before = path.read_bytes()
    with pytest.raises(FileNotFoundError):
        repairs.repair_file(path, 13)
    assert path.read_bytes() == before


def test_stale_provenance_cannot_attest_a_changed_model(tmp_path):
    path = tmp_path / "model.epJSON"
    path.write_text(json.dumps(school_model()))
    sidecar = path.with_suffix(".provenance.json")
    sidecar.write_text(json.dumps({"output_sha256": "0" * 64}))
    before = path.read_bytes(), sidecar.read_bytes()
    with pytest.raises(ValueError, match="transition provenance"):
        repairs.repair_file(path, 13)
    assert before == (path.read_bytes(), sidecar.read_bytes())


@pytest.fixture
def binding_case(tmp_path, monkeypatch):
    legacy = tmp_path / "old.idd"
    legacy.write_text("Material,\n  A1, \\field Name\n  N1; \\field Thickness\n")
    schema = {"properties": {"Material": {"legacy_idd": {"fields": ["name", "thickness"],
              "field_info": {"name": {"field_name": "Name"}, "thickness": {"field_name": "Thickness"}}}}}}
    modern_schema = tmp_path / "schema.json"
    modern_schema.write_text(json.dumps(schema))
    source = tmp_path / "source.idf"
    source.write_text("Material, Insulation, %x%; ! preserved source\n")
    directory = tmp_path / "modern"
    directory.mkdir()
    model_path = directory / "problem_1.epJSON"
    model_path.write_text(json.dumps({"Material": {"Insulation": {"thickness": 2.5}}}))
    problem = SimpleNamespace(id=1, midpoint=(2.5,), template_filename="source.idf")
    monkeypatch.setattr(bindings, "list_problems", lambda: [problem, SimpleNamespace(id=8)])
    monkeypatch.setattr(bindings, "legacy_template_path", lambda _: source)
    monkeypatch.setattr(bindings, "legacy_token_values", lambda *a: {"%x%": 2.5})
    return legacy, modern_schema, directory, source, model_path


def test_binding_manifest_traces_verified_semantic_fields_without_changing_inputs(binding_case):
    legacy, schema, directory, source, model = binding_case
    before = source.read_bytes(), model.read_bytes()
    manifest = bindings.build_manifest(legacy, schema, directory, problem_ids={1})
    record = manifest["models"]["1"]
    assert manifest["license"] == "BSD-3-Clause"
    assert record["source_template_sha256"] == bindings.sha256(source)
    assert record["model_sha256"] == bindings.sha256(model)
    assert record["token_count"] == record["binding_count"] == 1
    assert record["bindings"][0]["path"] == ["Material", "Insulation", "thickness"]
    assert record["bindings"][0]["source_field_name"] == "Thickness"
    assert before == (source.read_bytes(), model.read_bytes())


@pytest.mark.parametrize("failure", ["midpoint", "coverage", "embedded", "duplicate"])
def test_binding_generation_rejects_incomplete_or_ambiguous_maps(binding_case, monkeypatch, failure):
    legacy, schema, directory, source, model = binding_case
    if failure == "midpoint":
        model.write_text(json.dumps({"Material": {"Insulation": {"thickness": 9}}}))
    elif failure == "coverage":
        monkeypatch.setattr(bindings, "legacy_token_values", lambda *a: {"%x%": 2.5, "%unused%": 1})
    elif failure == "embedded":
        source.write_text("Material, Insulation, %x% m;")
    else:
        source.write_text("Material, Insulation, %x%; Material, Insulation, %x%;")
    with pytest.raises(ValueError, match="midpoint mismatch|token bindings|embedded|more than once"):
        bindings.build_manifest(legacy, schema, directory)


def test_idf_reading_and_idd_mapping_preserve_blank_fields_and_old_encoding(tmp_path):
    source = tmp_path / "old.idf"
    source.write_bytes(b"! degree \xb0\r\nMaterial, Wall,, 1; ! ignored; Object,not-real;\r\n")
    text = bindings.read_template(source)
    assert "°" in text
    assert list(bindings.idf_objects(text)) == [("Material", ["Wall", "", "1"])]
    empty = tmp_path / "empty.idd"
    empty.write_text("! no field definitions")
    with pytest.raises(ValueError, match="No IDD field"):
        bindings.idd_fields(empty)


def test_field_mapping_handles_extensible_groups_and_rejects_ambiguous_labels():
    schema = {"properties": {kind: {"legacy_idd": {"field_info": {}}}
                             for kind in ("Shading:Zone:Detailed", "Schedule:Compact")}}
    assert bindings.field_path("Shading:Zone:Detailed", "Vertex 2 Y-coordinate", schema) == [
        "vertices", 1, "vertex_y_coordinate"]
    assert bindings.field_path("Schedule:Compact", "Field 3", schema) == ["data", 2, "field"]
    schema["properties"]["Material"] = {"legacy_idd": {"field_info": {
        "a": {"field_name": "Thickness [m]"}, "b": {"field_name": "Thickness {m}"}}}}
    with pytest.raises(ValueError, match="uniquely map"):
        bindings.field_path("Material", "Thickness (m)", schema)
    assert bindings.at_path({"a": [{"b": 7}]}, ["a", 0, "b"]) == 7


def test_nameless_objects_are_matched_by_unique_semantic_reference():
    schema = {"properties": {"Sizing:Zone": {"legacy_idd": {"fields": ["zone_or_zonelist_name"]}}}}
    model = {"Sizing:Zone": {"generated-name": {"zone_or_zonelist_name": "Zone A"}}}
    assert bindings.object_names("Sizing:Zone", "ZONE A", model, [], {}, schema) == (
        "Sizing:Zone", ["generated-name"])
    model["Sizing:Zone"]["ambiguous"] = {"zone_or_zonelist_name": "Zone A"}
    with pytest.raises(ValueError, match="uniquely identify"):
        bindings.object_names("Sizing:Zone", "Zone A", model, [], {}, schema)


def test_generated_key_cannot_override_a_nameless_objects_actual_zone_reference():
    schema = {"properties": {"Sizing:Zone": {"legacy_idd": {"fields": ["zone_or_zonelist_name"]}}}}
    model = {"Sizing:Zone": {"Zone A": {"zone_or_zonelist_name": "Zone B"}}}
    with pytest.raises(ValueError, match="uniquely identify"):
        bindings.object_names("Sizing:Zone", "Zone A", model, [], {}, schema)


def test_shading_control_split_requires_complete_original_window_membership():
    schema = {"properties": {"WindowShadingControl": {"legacy_idd": {"fields": ["name"]}}}}
    fields = {"FenestrationSurface:Detailed": ["Name", "Shading Control Name"]}
    originals = [("FenestrationSurface:Detailed", [name, "Original"])
                 for name in ("Window A", "Window B")]
    model = {"WindowShadingControl": {name: {"fenestration_surfaces": [
        {"fenestration_surface_name": window}]} for name, window in
        (("North renamed", "Window A"), ("South renamed", "Window B"))}}
    assert bindings.object_names("WindowProperty:ShadingControl", "Original", model,
                                 originals, fields, schema) == (
                                     "WindowShadingControl", ["North renamed", "South renamed"])
    duplicated = copy.deepcopy(model)
    duplicated["WindowShadingControl"]["Duplicate"] = {
        "fenestration_surfaces": [{"fenestration_surface_name": "Window A"}]}
    with pytest.raises(ValueError, match="multiple transitioned"):
        bindings.object_names("WindowProperty:ShadingControl", "Original", duplicated,
                             originals, fields, schema)
    model["WindowShadingControl"]["North renamed"]["fenestration_surfaces"].append(
        {"fenestration_surface_name": "Foreign window"})
    with pytest.raises(ValueError, match="unexpected original windows"):
        bindings.object_names("WindowProperty:ShadingControl", "Original", model,
                             originals, fields, schema)


def test_model_maintenance_clis_dispatch_only_requested_files(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(repairs, "repair_file", lambda path, number: calls.append((path, number)) or 0)
    monkeypatch.setattr(sys, "argv", ["repair.py", "--modern-directory", str(tmp_path)])
    repairs.main()
    assert [number for _, number in calls] == [4, 5, 6, 13]
    assert all(path.parent == tmp_path for path, _ in calls)
    capsys.readouterr()
    monkeypatch.setattr(bindings, "build_manifest", lambda *a: {"models": {"1": {"binding_count": 2}}})
    output = tmp_path / "bindings.json"
    monkeypatch.setattr(sys, "argv", ["bindings.py", "--legacy-idd", "old.idd",
                                     "--modern-schema", "schema.json", "--output", str(output)])
    bindings.main()
    assert json.loads(output.read_text())["models"]["1"]["binding_count"] == 2
    assert "Verified 2 physical field bindings" in capsys.readouterr().out
