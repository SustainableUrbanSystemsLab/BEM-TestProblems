# SPDX-License-Identifier: MIT
"""Historical coordinate boundaries, pinned inputs and native process cleanup."""

import io
import itertools
import json
from pathlib import Path

import pytest

from bem_testproblems import get_problem
from bem_testproblems import replication_native as native
from bem_testproblems.energyplus import sha256_file


def configuration(tmp_path, backend="bbo"):
    directory = tmp_path / backend
    directory.mkdir()
    for name in native.REQUIRED[backend]:
        (directory / name).write_bytes(name.encode())
    executable = "SolverBridge.exe" if backend == "bbo" else "GalapagosBridge.exe"
    path = tmp_path / "native.json"
    path.write_text(json.dumps(dict(schema_version=1, backends={backend: dict(
        executable=str(directory / executable), source="https://example.org/original",
        files={str(p): sha256_file(p) for p in directory.iterdir()} )})))
    return path


@pytest.mark.parametrize("number", [4, 5, 6, 8])
def test_all_geometry_endpoints_are_feasible_and_outside_values_reject(number):
    profile = native.slider_profile(number)
    tail = [(a + b) / 2 for a, b in zip(profile["lower"][7:], profile["upper"][7:])]
    for corner in itertools.product((0, 1), repeat=7):
        physical = native.physical_design(number, [*corner, *tail])
        assert get_problem(number).validate(physical)
    with pytest.raises(ValueError, match="invalid slider"):
        native.physical_design(number, [1.00001, *([0.5] * 6), *tail])


@pytest.mark.parametrize("number", [1, 2, 3, 4, 5, 6, 8, 9, 10, 13])
def test_slider_mapping_roundtrip_preserves_physical_start(number):
    x = get_problem(number).midpoint
    assert native.physical_design(number, native.slider_start(number, x)) == pytest.approx(x)


def test_historical_preset_choice_and_precision_are_explicit():
    assert native.solver_settings("fips", 11)["preset"] == "FIPSO_n11_B"
    assert native.solver_settings("sga_unt", 4)["preset"] == "SGA_WW"
    assert native.slider_profile(1)["digits"] == [2, 3, 3, 4]
    assert native.slider_profile(9)["digits"] == [6] * 13
    assert native.solver_settings("galapagos_ga", 13)["galapagos_tick_precision_cap"] == 5


def test_binary_changes_and_unrecovered_methods_fail_before_launch(tmp_path):
    path = configuration(tmp_path)
    pinned = native.load_configuration(path, ["sga"])
    Path(next(iter(pinned["backends"]["bbo"]["files"]))).write_bytes(b"changed")
    with pytest.raises(ValueError, match="input changed"):
        native.verify_files(pinned)
    with pytest.raises(ValueError, match="only the ten recovered"):
        native.load_configuration(path, ["silvereye"])


def test_native_callback_failure_stops_owned_child_and_keeps_protocol(tmp_path, monkeypatch):
    pinned = native.load_configuration(configuration(tmp_path), ["sga"])
    child = type("Child", (), {})()
    child.stdin = io.StringIO()
    start = list(get_problem(1).midpoint)
    child.stdout = io.StringIO(json.dumps(dict(type="evaluation", x=start)) + "\n")
    child.poll = lambda: None
    child.wait = lambda timeout: 0
    killed = []
    child.kill = lambda: killed.append(True)
    monkeypatch.setattr(native.subprocess, "Popen", lambda *a, **kw: child)
    error = RuntimeError("simulator failed")

    def objective(_):
        raise error

    spec = dict(solver="sga", problem=1, seed=40000, budget=500,
                x0=get_problem(1).midpoint)
    protocol = tmp_path / "attempt" / "protocol.jsonl"
    with pytest.raises(RuntimeError) as raised:
        native.solve(spec, pinned, objective, protocol)
    assert raised.value is error
    assert killed == [True]
    lines = [json.loads(line) for line in protocol.read_text().splitlines()]
    assert lines[0]["request"]["seed"] == 40000 % 32768
    assert lines[1]["physical_x"] == start
    assert not any("objective" in line for line in lines)
