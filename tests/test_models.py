"""Check actual rendered model geometry and independently derived parameter effects."""

import json
import re
from collections import Counter
from importlib.resources import files
from pathlib import Path

import pytest

import bem_testproblems.models as models
from bem_testproblems.models import csharp_number, legacy_token_values
from bem_testproblems.problems import PROBLEM_IDS, get_problem
from bem_testproblems.reference import legacy_template_path, reference_root


def idf_objects(path):
    text = re.sub(r"!.*", "", Path(path).read_text(encoding="utf-8"))
    return [
        tuple(field.strip() for field in block.split(","))
        for block in text.split(";")
        if block.strip()
    ]


def find_object(objects, kind, name):
    return next(obj for obj in objects if obj[:2] == (kind, name))


@pytest.mark.parametrize("number", PROBLEM_IDS)
def test_all_original_templates_render_without_placeholders(number, tmp_path):
    problem = get_problem(number)
    path = problem.render_legacy(problem.midpoint, tmp_path / f"p{number}.idf")
    raw = path.read_bytes()
    assert not re.search(rb"%[A-Za-z0-9_]+%", raw)
    assert b"\n" in raw and b"\r\n" not in raw
    objects = idf_objects(path)
    assert any(obj[0].lower() == "version" and obj[1] == "8.5" for obj in objects)


def test_simple_geometry_material_and_orientation_follow_physical_inputs(tmp_path):
    problem = get_problem(3)
    path = problem.render_legacy([45, 2.5, 4.5, 0.3], tmp_path / "simple.idf")
    objects = idf_objects(path)
    assert float(find_object(objects, "Building", "office zone")[2]) == 45
    shade = find_object(objects, "WindowMaterial:Shade", "ExtShade")
    assert tuple(float(shade[i]) for i in (2, 4, 7)) == (0.3, 0.3, 0.3)
    for name, width in (
        ("ZONE SUBSURFACE 1 EAST WINDOW", 4.5),
        ("ZONE SUBSURFACE 2 WEST WINDOW", 2.5),
    ):
        window = find_object(objects, "FenestrationSurface:Detailed", name)
        vertices = [tuple(map(float, window[i : i + 3])) for i in range(11, len(window), 3)]
        # The horizontal window span is the requested width, in its local wall plane.
        span = max(max(v[i] for v in vertices) - min(v[i] for v in vertices) for i in (0, 1))
        assert span == pytest.approx(width)


def test_detailed_window_centering_overhang_margin_and_schedule(tmp_path):
    problem = get_problem(6)
    design = list(problem.midpoint)
    design[0], design[4], design[10], design[11], design[12] = 4, 0.75, 24, 21, 16
    path = problem.render_legacy(design, tmp_path / "detailed.idf")
    objects = idf_objects(path)
    window = find_object(objects, "FenestrationSurface:Detailed", "ZONE NORTH WINDOW")
    vertices = [tuple(map(float, window[i : i + 3])) for i in range(11, len(window), 3)]
    assert {vertex[0] for vertex in vertices} == {1.0, 5.0}
    overhang = find_object(objects, "Shading:Zone:Detailed", "ZONE NORTH OVERHANG")
    over_vertices = [tuple(map(float, overhang[i : i + 3])) for i in range(5, len(overhang), 3)]
    assert {vertex[0] for vertex in over_vertices} == {0.5, 5.5}
    assert float(find_object(objects, "Sizing:Zone", "ZONE NORTH")[3]) == 16
    summer = find_object(objects, "Schedule:Day:Hourly", "Clg-SetP-DSch-Sum")
    winter = find_object(objects, "Schedule:Day:Hourly", "Clg-SetP-DSch-Win")
    assert float(summer[3]) == 24
    assert float(winter[3]) == 21


def test_office_upper_floor_window_coordinates_and_humidity_coupling():
    problem = get_problem(10)
    design = list(problem.midpoint)
    design[0], design[1], design[8] = 0.9, 2.0, 16.0
    values = legacy_token_values(problem, design)
    assert values["%0%"] == 0.9
    assert values["%13%"] == pytest.approx(0.9 + 16.7683)
    assert values["%14%"] == pytest.approx(2.0 + 16.7683)
    assert values["%21%"] == pytest.approx(0.9 + 33.5366)
    assert values["%29%"] == pytest.approx(0.01075)


def test_school_changes_actual_insulation_and_all_nine_radiators(tmp_path):
    problem = get_problem(13)
    design = list(problem.midpoint)
    path = problem.render_legacy(design, tmp_path / "school.idf")
    objects = idf_objects(path)
    assert float(find_object(objects, "Material", "MineralWoolOut")[3]) == design[0]
    radiators = {
        obj[1]: float(obj[9]) for obj in objects if obj[0] == "ZoneHVAC:Baseboard:Convective:Water"
    }
    names = (
        "ClassZone2Radiant",
        "WorkZoneRadiant",
        "KitchenZoneRadiant",
        "MusiceZoneRadiant",
        "ServiceZoneRadiant",
        "WashingZoneRadiant",
        "BigZoneRadiant",
        "ClassZone1Radiant",
        "OfficeZoneRadiant",
    )
    assert tuple(radiators[name] for name in names) == tuple(design[1:])
    assert not any(obj[0].lower() == "runperiod" for obj in objects)


def test_classic_dotnet_number_format_is_invariant():
    assert csharp_number(-0.0) == "0"
    assert csharp_number(1 / 3) == "0.333333333333333"
    assert csharp_number(1e-9) == "1E-09"


def modern_model(problem, design, tmp_path):
    path = problem.render_modern(design, tmp_path / f"problem_{problem.id}.epJSON")
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_original_physical_placeholder_occurrence_has_a_modern_binding():
    data = files("bem_testproblems").joinpath("data")
    manifest = json.loads(data.joinpath("modern", "parameter_bindings.json").read_bytes())
    total = 0
    assert set(manifest["models"]) == {"1", "2", "3", "4", "5", "6", "9", "10", "13"}
    for number in PROBLEM_IDS:
        if number == 8:
            continue
        problem = get_problem(number)
        raw = legacy_template_path(problem.template_filename).read_bytes()
        # Token syntax and comments are ASCII in both UTF-8 and CP1252 sources.
        objects = re.sub(rb"!.*", b"", raw)
        original = Counter(
            token.decode("ascii") for token in re.findall(rb"%[A-Za-z0-9_]+%", objects)
        )
        bindings = manifest["models"][str(number)]["bindings"]
        assert Counter(binding["token"] for binding in bindings) == original
        assert len(bindings) == manifest["models"][str(number)]["binding_count"]
        assert len({tuple(binding["path"]) for binding in bindings}) == len(bindings)
        total += len(bindings)
    assert total == 399


@pytest.mark.parametrize("number", PROBLEM_IDS)
def test_every_modern_model_has_target_version_and_all_bindings(number, tmp_path):
    problem = get_problem(number)
    model = modern_model(problem, problem.midpoint, tmp_path)
    assert {str(value["version_identifier"]) for value in model["Version"].values()} == {"26.2"}
    assert not re.search(r"%[A-Za-z0-9_]+%", json.dumps(model))


def test_modern_simple_physical_geometry_and_material_are_independent(tmp_path):
    model = modern_model(get_problem(1), [45, 2.5, 4.5, 0.3], tmp_path)
    assert model["Building"]["office zone"]["north_axis"] == 45
    shade = model["WindowMaterial:Shade"]["ExtShade"]
    assert (
        tuple(
            shade[key]
            for key in ("solar_transmittance", "visible_transmittance", "infrared_transmittance")
        )
        == (0.3,) * 3
    )
    for side, width in (("EAST", 4.5), ("WEST", 2.5)):
        window = next(
            value
            for name, value in model["FenestrationSurface:Detailed"].items()
            if name.endswith(f"{side} WINDOW")
        )
        coordinates = [window[f"vertex_{i}_y_coordinate"] for i in range(1, 5)]
        assert max(coordinates) - min(coordinates) == pytest.approx(width)
    east_overhang = next(
        value for name, value in model["Shading:Zone:Detailed"].items() if "EAST" in name
    )
    ys = [vertex["vertex_y_coordinate"] for vertex in east_overhang["vertices"]]
    assert max(ys) - min(ys) == pytest.approx(4.5)


def test_modern_detailed_all_faces_depths_setpoints_and_hvac_couplings(tmp_path):
    design = (2, 13, 17, 4, 0.2, 0.4, 0.8, 111, 333, 555, 20.5, 24, 17)
    model = modern_model(get_problem(4), design, tmp_path)
    for side, width, center in (
        ("NORTH", 2, 3),
        ("WEST", 13, 12),
        ("EAST", 17, 12),
        ("SOUTH", 4, 3),
    ):
        window = model["FenestrationSurface:Detailed"][f"ZONE {side} WINDOW"]
        assert {window[f"vertex_{i}_x_coordinate"] for i in range(1, 5)} == {
            center - width / 2,
            center + width / 2,
        }
        assert min(window[f"vertex_{i}_z_coordinate"] for i in range(1, 5)) == 0.6
        overhang = model["Shading:Zone:Detailed"][f"ZONE {side} OVERHANG"]["vertices"]
        assert {v["vertex_x_coordinate"] for v in overhang} == {
            center - width / 2 - 0.5,
            center + width / 2 + 0.5,
        }
    for side, depth, setpoint in (("WEST", 0.2, 111), ("EAST", 0.4, 333), ("SOUTH", 0.8, 555)):
        overhang = model["Shading:Zone:Detailed"][f"ZONE {side} OVERHANG"]["vertices"]
        assert max(v["vertex_y_coordinate"] for v in overhang) == pytest.approx(8 + depth)
        controls = [
            value
            for value in model["WindowShadingControl"].values()
            if any(
                item["fenestration_surface_name"] == f"ZONE {side} WINDOW"
                for item in value["fenestration_surfaces"]
            )
        ]
        assert len(controls) == 1
        assert controls[0]["setpoint"] == setpoint
    assert {
        v["zone_cooling_design_supply_air_temperature"] for v in model["Sizing:Zone"].values()
    } == {17}
    system_sizing = next(
        value for value in model["Sizing:System"].values() if value["airloop_name"] == "VAV Sys 1"
    )
    assert system_sizing["central_cooling_design_supply_air_temperature"] == 17
    assert model["Schedule:Day:Hourly"]["Clg-SetP-DSch-Sum"]["hour_1"] == 20.5
    assert model["Schedule:Day:Hourly"]["Clg-SetP-DSch-Win"]["hour_1"] == 24


@pytest.mark.parametrize("number", (9, 10))
def test_modern_office_all_window_faces_floors_schedules_and_humidity(number, tmp_path):
    design = (0.85, 1.5, 0.95, 1.7, 1.1, 2.0, 1.2, 2.1, 17, 14, 20, 27, 34)
    model = modern_model(get_problem(number), design, tmp_path)
    for name, window in model["FenestrationSurface:Detailed"].items():
        if "_Window" not in name:
            continue
        direction = next(
            index
            for index, side in enumerate(("North", "East", "South", "West"))
            if f"_{side}_" in name
        )
        offset = 16.7683 if "_mid_" in name else 33.5366 if "_top_" in name else 0.0
        zs = [window[f"vertex_{i}_z_coordinate"] for i in range(1, 5)]
        assert min(zs) == pytest.approx(design[2 * direction] + offset)
        assert max(zs) == pytest.approx(design[2 * direction + 1] + offset)
    heating = model["Schedule:Compact"]["HTGSETP_SCH"]["data"]
    cooling = model["Schedule:Compact"]["CLGSETP_SCH"]["data"]
    assert {heating[i]["field"] for i in (3, 7, 13, 17)} == {14}
    assert heating[20]["field"] == 20
    assert {cooling[i]["field"] for i in (3, 7, 10, 14)} == {27}
    assert cooling[20]["field"] == 34
    for sizing in model["Sizing:Zone"].values():
        assert sizing["zone_cooling_design_supply_air_temperature"] == 17
        assert sizing["zone_cooling_design_supply_air_humidity_ratio"] == pytest.approx(
            17 * 0.0006875 - 0.00025
        )
    for sizing in model["Sizing:System"].values():
        assert sizing["central_cooling_design_supply_air_temperature"] == 17
        assert sizing["central_cooling_design_supply_air_humidity_ratio"] == pytest.approx(
            17 * 0.0006875 - 0.00025
        )
        assert sizing["precool_design_humidity_ratio"] == pytest.approx(17 * 0.0006875 - 0.00025)


def test_modern_school_all_nine_distinct_radiator_values(tmp_path):
    design = (0.12, 710, 83, 91, 127, 42, 131, 219, 540, 603)
    model = modern_model(get_problem(13), design, tmp_path)
    assert model["Material"]["MineralWoolOut"]["thickness"] == 0.12
    names = (
        "ClassZone2Radiant",
        "WorkZoneRadiant",
        "KitchenZoneRadiant",
        "MusiceZoneRadiant",
        "ServiceZoneRadiant",
        "WashingZoneRadiant",
        "BigZoneRadiant",
        "ClassZone1Radiant",
        "OfficeZoneRadiant",
    )
    radiators = model["ZoneHVAC:Baseboard:Convective:Water"]
    assert tuple(radiators[name]["u_factor_times_area_value"] for name in names) == design[1:]
    assert {radiator["heating_design_capacity"] for radiator in radiators.values()} == {0.0}


@pytest.mark.parametrize("number", (4, 5, 6))
def test_modern_detailed_boundary_explicitly_preserves_historical_resolver_pair(number, tmp_path):
    model = modern_model(get_problem(number), get_problem(number).midpoint, tmp_path)
    surfaces = model["BuildingSurface:Detailed"]
    assert (
        surfaces["ZONE INTERIOR SURFACE NORTH"]["outside_boundary_condition_object"]
        == "ZONE NORTH SURFACE SOUTH"
    )
    assert (
        surfaces["ZONE NORTH SURFACE SOUTH"]["outside_boundary_condition_object"]
        == "ZONE INTERIOR SURFACE NORTH"
    )


def test_legacy_reference_cache_is_explicit_and_never_fetched_implicitly(tmp_path, monkeypatch):
    missing = tmp_path / "absent-reference-cache"
    monkeypatch.setenv("BEM_REFERENCE_DIR", str(missing))
    assert reference_root() == missing
    problem = get_problem(1)
    with pytest.raises(FileNotFoundError, match="fetch_reference.py"):
        problem.render_legacy(problem.midpoint, tmp_path / "legacy.idf")
    assert not missing.exists()
    # Normal native model rendering uses only the packaged modern assets.
    assert problem.render_modern(problem.midpoint, tmp_path / "modern.epJSON").is_file()


def test_legacy_reference_bytes_are_checked_against_the_packaged_manifest(tmp_path, monkeypatch):
    filename = get_problem(1).template_filename
    original = legacy_template_path(filename).read_bytes()
    cache = tmp_path / "reference-cache"
    (cache / "models").mkdir(parents=True)
    (cache / "models" / filename).write_bytes(original + b"\n")
    monkeypatch.setenv("BEM_REFERENCE_DIR", str(cache))
    with pytest.raises(ValueError, match="checksum mismatch"):
        legacy_template_path(filename)
    with pytest.raises(ValueError, match="known original template"):
        legacy_template_path("../outside.idf")


@pytest.mark.parametrize("encoding", ["cp1252", "utf-8-sig"])
def test_original_comment_encoding_is_preserved_in_portable_rendering(tmp_path, monkeypatch, encoding):
    template = tmp_path / "original.idf"
    text = "! Temperature in °C\r\nVersion,8.5;\r\n%azimuth%,%w_we_win%,%w_ea_win%,%tau%;\r\n"
    template.write_bytes(text.encode(encoding))
    monkeypatch.setattr(models, "legacy_template_path", lambda filename: template)
    result = get_problem(1).render_legacy([45, 2.5, 4.5, 0.3], tmp_path / "output.idf")
    assert result.read_bytes() == "! Temperature in °C\nVersion,8.5;\n45,2.5,4.5,0.3;\n".encode()
    assert template.read_bytes() == text.encode(encoding)


@pytest.mark.parametrize("tokens", [
    "%azimuth%,%w_we_win%,%w_ea_win%;",
    "%azimuth%,%w_we_win%,%w_ea_win%,%tau%,%unexpected%;",
])
def test_legacy_token_mismatch_fails_without_writing_output(tmp_path, monkeypatch, tokens):
    template = tmp_path / "original.idf"
    template.write_text(tokens)
    monkeypatch.setattr(models, "legacy_template_path", lambda filename: template)
    output = tmp_path / "output.idf"
    with pytest.raises(ValueError, match="Template/token mismatch"):
        get_problem(1).render_legacy(get_problem(1).midpoint, output)
    assert not output.exists()


def test_incomplete_modern_binding_manifest_fails_without_writing_output(tmp_path, monkeypatch):
    real_resource = models._data_resource
    bindings = json.loads(real_resource("modern", "parameter_bindings.json").read_text())
    bindings["models"]["1"]["bindings"] = [
        binding for binding in bindings["models"]["1"]["bindings"] if binding["token"] != "%tau%"
    ]
    incomplete = tmp_path / "bindings.json"
    incomplete.write_text(json.dumps(bindings))

    def resource(directory, filename):
        return incomplete if filename == "parameter_bindings.json" else real_resource(directory, filename)

    monkeypatch.setattr(models, "_data_resource", resource)
    output = tmp_path / "output.epJSON"
    with pytest.raises(ValueError, match="Modern binding coverage differs"):
        get_problem(1).render_modern(get_problem(1).midpoint, output)
    assert not output.exists()


def test_modern_rendering_is_deterministic_and_keeps_packaged_model_immutable(tmp_path):
    problem = get_problem(1)
    resource = models._data_resource("modern", "problem_1.epJSON")
    original = resource.read_bytes()
    first = problem.render_modern([45, 2.5, 4.5, 0.3], tmp_path / "one.epJSON")
    problem.render_modern(problem.midpoint, tmp_path / "different.epJSON")
    again = problem.render_modern([45, 2.5, 4.5, 0.3], tmp_path / "two.epJSON")
    assert first.read_bytes() == again.read_bytes()
    assert resource.read_bytes() == original
