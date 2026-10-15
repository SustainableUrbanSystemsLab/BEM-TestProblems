"""Check the narrowly scoped normalization needed by the official transition."""

import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import transition_models as tool
from tools.transition_models import normalize_setpoint_manager_names


def test_duplicate_cross_type_manager_name_changes_only_mixedair_identifier():
    source = """SetpointManager:Scheduled,
  Shared Name, ! name
  Temperature,
  Schedule,
  Scheduled Node;
SetpointManager:MixedAir,
  Shared Name, ! name
  Temperature,
  Reference Node,
  Fan Inlet,
  Fan Outlet,
  MixedAir Node;
"""
    actual, changes = normalize_setpoint_manager_names(source)
    assert actual == source.replace("SetpointManager:MixedAir,\n  Shared Name,", "SetpointManager:MixedAir,\n  Shared Name__MixedAir,")
    assert changes[0]["old_name"] == "Shared Name"
    assert changes[0]["new_name"] == "Shared Name__MixedAir"
    assert normalize_setpoint_manager_names(actual) == (actual, [])


def test_referenced_duplicate_manager_name_requires_manual_review():
    source = "SetpointManager:Scheduled,\n  Shared,\n  Temperature;\nSetpointManager:MixedAir,\n  Shared,\n  Temperature;\nOther:Object, Shared;\n"
    with pytest.raises(ValueError, match="manual review"):
        normalize_setpoint_manager_names(source)


@pytest.fixture
def fake_chain(tmp_path, monkeypatch):
    """Tiny official-tool stand-ins; no executable or canonical asset is touched."""
    engine, historical = tmp_path / "engine", tmp_path / "historical"
    current = engine / "PreProcess/IDFVersionUpdater"
    current.mkdir(parents=True)
    historical.mkdir()
    (engine / "ConvertInputFormat").write_text("mock converter")
    for number, (old, new) in enumerate(zip(tool.VERSIONS, tool.VERSIONS[1:])):
        directory = historical if number < 5 else current
        (directory / f"Transition-V{old}-to-V{new}").write_text("mock transition")
        for version in (old, new):
            (directory / f"V{version}-Energy+.idd").write_text("mock dictionary " + version)
        (directory / f"Report Variables {old} to {new}.csv").write_text("mock report rules")
    source = tmp_path / "source.idf"
    source.write_text("! fake DOE Commercial Building Benchmark header\nVersion,8.5;\n"
                      "End Lead Input;\nOther:Object,Simulation Data; ! real field stays\n"
                      "Simulation Data;\nEnd Simulation Data;\n")
    state = {"fault": None, "calls": [], "normalized": None}

    def fake_call(command, cwd, log, timeout):
        name = Path(command[0]).name
        state["calls"].append((name, cwd, timeout))
        log.write_text("mock invocation")
        match = re.fullmatch(r"Transition-V(.+)-to-V(.+)", name)
        if match:
            model = Path(command[-1])
            output = re.sub(r"Version,[^;]+;", "Version," + match[2].replace("-", ".") + ";",
                            model.read_text())
            model.write_text(output)
            if state["fault"] != "missing-transition-output":
                model.with_suffix(".idfnew").write_text(output)
            if state["fault"] == "fatal-transition":
                (cwd / "model.VCpErr").write_text("Completed Successfully; Fatal diagnostic")
        else:
            state["normalized"] = Path(command[-1]).read_text()
            version = "25.2" if state["fault"] == "wrong-converter-version" else "26.2"
            model = {"Version": {"Version 1": {"version_identifier": version}},
                     "Building": {"Office": {"maximum_number_of_warmup_days": 25,
                                             "temperature_convergence_tolerance_value": .004,
                                             "loads_convergence_tolerance_value": .04}}}
            (cwd / "model.epJSON").write_text(json.dumps(model))
            if state["fault"] == "multiple-converter-outputs":
                (cwd / "unexpected.epJSON").write_text(json.dumps(model))
            if state["fault"] == "source-changed":
                source.write_text(source.read_text() + "! concurrent edit\n")
        return .001

    monkeypatch.setattr(tool, "_call", fake_call)
    return source, engine, historical, state


def test_full_transition_chain_preserves_source_and_records_complete_provenance(fake_chain, tmp_path):
    source, engine, historical, state = fake_chain
    original = source.read_bytes()
    target = tmp_path / "result/model.epJSON"
    result = tool.transition_model(source, target, energyplus_root=engine,
                                   historical_dir=historical, source_template=source,
                                   parameters={"x": [1, 2]}, audit_directory=tmp_path / "audit",
                                   minimum_max_warmup_days=100)
    assert source.read_bytes() == original
    assert len(result["transition_steps"]) == 21
    assert result["transition_steps"][0]["from"] == "8.5.0"
    assert result["transition_steps"][-1]["to"] == "26.2.0"
    assert len({cwd for _, cwd, _ in state["calls"]}) == 22
    assert result["removed_obsolete_section_markers"] == [
        "End Lead Input", "Simulation Data", "End Simulation Data"]
    assert "Other:Object,Simulation Data;" in state["normalized"]
    assert "End Lead Input;" not in state["normalized"]
    assert result["additional_notices"]["publication_credit"] == ["DOE", "NREL", "PNNL", "LBNL"]
    assert result["output_sha256"] == tool.sha256(target)
    assert json.loads(target.with_suffix(".provenance.json").read_text()) == result
    building = json.loads(target.read_text())["Building"]["Office"]
    assert building["maximum_number_of_warmup_days"] == 100
    assert building["temperature_convergence_tolerance_value"] == .004
    assert building["loads_convergence_tolerance_value"] == .04
    assert result["baseline_parameters"] == {"x": [1, 2]}


@pytest.mark.parametrize("fault,match", [
    ("missing-transition-output", "did not produce"), ("fatal-transition", "Fatal transition"),
    ("wrong-converter-version", "does not declare"), ("multiple-converter-outputs", "Expected one"),
    ("source-changed", "changed during transition"),
])
def test_transition_failures_never_publish_untrusted_model(fake_chain, tmp_path, fault, match):
    source, engine, historical, state = fake_chain
    state["fault"] = fault
    target = tmp_path / "output.epJSON"
    with pytest.raises(RuntimeError, match=match):
        tool.transition_model(source, target, energyplus_root=engine, historical_dir=historical,
                              audit_directory=tmp_path / "audit")
    assert not target.exists()
    assert not target.with_suffix(".provenance.json").exists()


@pytest.mark.parametrize("option,value", [
    ("timeout", 0), ("timeout", float("nan")), ("minimum_max_warmup_days", -1),
    ("minimum_max_warmup_days", True), ("minimum_max_warmup_days", 12.5),
])
def test_invalid_transition_controls_fail_before_tools_or_publication(tmp_path, option, value):
    source = tmp_path / "source.idf"
    source.write_text("Version,8.5;")
    with pytest.raises(ValueError, match="positive"):
        tool.transition_model(source, tmp_path / "output.epJSON", energyplus_root="missing",
                              historical_dir="missing", **{option: value})


@pytest.mark.parametrize("contents,match", [
    ("Version,8.5;Material,Name,%x%;", "placeholder"),
    ("Version,7.0;", "Unsupported source"), ("Material,Name,1;", "No Version"),
])
def test_unrendered_or_unsupported_source_is_rejected_without_tools(tmp_path, contents, match):
    source = tmp_path / "source.idf"
    source.write_text(contents)
    with pytest.raises(ValueError, match=match):
        tool.transition_model(source, tmp_path / "output.epJSON", energyplus_root="missing",
                              historical_dir="missing")


def test_transition_cannot_overwrite_its_source_or_provenance_alias(tmp_path):
    source = tmp_path / "source.epJSON"
    source.write_text("Version,26.2;")
    before = source.read_bytes()
    with pytest.raises(ValueError, match="must not overwrite"):
        tool.transition_model(source, source, energyplus_root="missing", historical_dir="missing")
    assert source.read_bytes() == before
    sidecar = tmp_path / "output.provenance.json"
    sidecar.write_text("Version,26.2;")
    with pytest.raises(ValueError, match="must not overwrite"):
        tool.transition_model(sidecar, tmp_path / "output.epJSON", energyplus_root="missing",
                              historical_dir="missing")
    assert sidecar.read_text() == "Version,26.2;"


def test_duplicate_manager_rename_rejects_name_collision():
    source = "SetpointManager:Scheduled,\n Shared,\n Temperature;\nSetpointManager:MixedAir,\n Shared,\n Temperature;\nOther:Object, Shared__MixedAir;\n"
    with pytest.raises(ValueError, match="replacement name already exists"):
        normalize_setpoint_manager_names(source)


def test_version_parser_and_executable_lookup_ignore_comments_and_support_windows(tmp_path):
    source = tmp_path / "model.idf"
    source.write_text("! Version,7.0;\n Other,1; vErSiOn,26.2; ! comment\n")
    assert tool.idf_version(source) == "26-2-0"
    executable = tmp_path / "ConvertInputFormat.exe"
    executable.write_text("mock")
    assert tool.executable(tmp_path, "ConvertInputFormat") == executable
    with pytest.raises(FileNotFoundError, match="Missing official tool"):
        tool.executable(tmp_path, "missing")


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_tool_launcher_retains_error_log_on_failure(tmp_path, monkeypatch, failure):
    # Restore the real launcher, independent of the fake-chain fixture.
    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        return SimpleNamespace(returncode=3, stdout="failure details", stderr="stderr details")

    monkeypatch.setattr(tool.subprocess, "run", run)
    log = tmp_path / "launch.log"
    with pytest.raises(RuntimeError, match="timed out|exited 3"):
        tool._call(["never-executed"], tmp_path, log, 10)
    assert log.exists() and ("timed out" if failure == "timeout" else "failure details") in log.read_text()


def test_transition_cli_dispatches_options_and_prints_compact_summary(tmp_path, monkeypatch, capsys):
    captured = {}

    def transition(**kwargs):
        captured.update(kwargs)
        return {"output_epjson": "model.epJSON", "output_sha256": "0" * 64, "transition_steps": [{}, {}]}

    monkeypatch.setattr(tool, "transition_model", transition)
    monkeypatch.setattr(sys, "argv", ["transition.py", "source.idf", "model.epJSON",
                                     "--energyplus-root", "engine", "--historical-dir", "history",
                                     "--audit-directory", str(tmp_path), "--timeout", "9",
                                     "--minimum-max-warmup-days", "100"])
    tool.main()
    assert captured["input_idf"] == Path("source.idf")
    assert captured["minimum_max_warmup_days"] == 100 and captured["timeout"] == 9
    assert json.loads(capsys.readouterr().out)["steps"] == 2
