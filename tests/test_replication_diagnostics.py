# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Keep experimental warmup recovery narrow and its diagnostics immutable."""

import json

import pytest

from bem_testproblems.energyplus import EnergyPlusError, RunResult, sha256_file
from bem_testproblems.outputs import extract_outputs
from bem_testproblems.replication_diagnostics import ReferenceWarmupRunner


@pytest.fixture
def failed_run(tmp_path):
    directory = tmp_path / "retained"
    directory.mkdir()
    source = tmp_path / "source.idf"
    source.write_text("Version,8.5;\n")
    staged = directory / "input.idf"
    staged.write_bytes(source.read_bytes())
    executable = tmp_path / "energyplus"
    executable.write_text("Independent fake executable\n")
    weather = tmp_path / "fixture.epw"
    weather.write_text("Independent fake weather\n")
    (directory / "eplusout.err").write_text(
        '   ** Warning ** Independent test warning.\n'
        '   ** Severe ** CheckWarmupConvergence: Loads Initialization, '
        'Zone="ZONE ONE" did not converge after 25 warmup days.\n'
        '   ** ~~~ ** Minimum temperature comparison failed.\n'
        'EnergyPlus Completed Successfully-- 1 Warning; 1 Severe Errors\n'
    )
    (directory / "eplusout.end").write_text(
        "EnergyPlus Completed Successfully-- 1 Warning; 1 Severe Errors\n"
    )
    (directory / "eplusout.eio").write_text(
        "Environment:WarmupDays, 25\n"
        " Warmup Convergence Information,ZONE ONE,RunPeriod: TEST,0,0,Pass,Fail,0,0,Pass,Pass\n"
    )
    (directory / "eplusout.eso").write_text(
        "6,1,ZONE1AIR,Zone Ideal Loads Supply Air Sensible Heating Energy [J] !RunPeriod\n"
        "7,1,ZONE1AIR,Zone Ideal Loads Supply Air Sensible Cooling Energy [J] !RunPeriod\n"
        "8,1,ZONE ONE,Zone Lights Electric Energy [J] !RunPeriod\n"
        "End of Data Dictionary\n6,3600000\n7,7200000\n8,10800000\nEnd of Data\n"
    )
    metadata = {
        "version": "8.5.0", "directory": str(directory), "input_file": str(staged),
        "input_sha256": sha256_file(staged), "weather_file": str(weather),
        "weather_sha256": sha256_file(weather), "executable": str(executable),
        "executable_sha256": sha256_file(executable),
        "command": [str(executable), "-d", str(directory), "-w", str(weather), str(staged)],
        "status": "failed", "failure_reason": "simulation", "returncode": 0, "elapsed": 0.5,
    }
    (directory / "run.json").write_text(json.dumps(metadata))
    error = EnergyPlusError("Strict diagnostics rejected this run", directory=directory,
                            reason="simulation")

    class Native:
        version = "8.5.0"
        executable_sha256 = metadata["executable_sha256"]

        def __init__(self):
            self.executable = executable
            self.error = error
            self.result = None
            self.calls = []

        def run(self, input_file, weather_file=None, *, design_day=False):
            self.calls.append((input_file, weather_file, design_day))
            if self.result is not None:
                return self.result
            raise self.error

    return Native(), source, weather, directory, metadata


def test_completed_warmup_only_run_recovers_with_visible_metrics_and_unchanged_files(failed_run):
    native, source, weather, directory, metadata = failed_run
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    runner = ReferenceWarmupRunner(native, family="simple")
    result = runner.run(source, weather)
    assert isinstance(result, RunResult)
    assert runner.version == native.version
    assert runner.executable_sha256 == native.executable_sha256
    assert result.input_sha256 == metadata["input_sha256"]
    assert result.weather_sha256 == metadata["weather_sha256"]
    assert extract_outputs("simple", result) == {"Q_h": 1, "Q_c": 2, "E_L": 3}
    assert runner.last_diagnostics["accepted_warmup_only"]
    assert not runner.last_diagnostics["strict_benchmark_evaluation"]
    assert runner.last_diagnostics["severe_count"] == 1
    assert runner.last_diagnostics["warmup_severe_count"] == 1
    assert runner.last_diagnostics["fatal_count"] == 0
    assert runner.last_diagnostics["warning_count"] == 1
    assert runner.last_diagnostics["actual_warmup_days"] == [25]
    assert runner.last_diagnostics["warmup_eio_rows"]
    assert len(runner.recovered_runs) == 1
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before
    assert json.loads((directory / "run.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("change", [
    "other_severe", "fatal", "no_severe", "incomplete_end", "inconsistent_severe_summary",
    "missing_observable", "truncated_eso", "nonfinite_observable", "wrong_unit",
    "nonzero_returncode", "wrong_failure_reason", "missing_metadata", "corrupt_metadata",
    "changed_input", "changed_weather", "changed_engine", "changed_source", "wrong_version",
])
def test_any_other_diagnostic_output_or_identity_failure_preserves_original_error(failed_run, change):
    native, source, weather, directory, metadata = failed_run
    if change == "other_severe":
        with (directory / "eplusout.err").open("a") as handle:
            handle.write("** Severe ** Unrelated HVAC convergence error.\n")
    elif change == "fatal":
        with (directory / "eplusout.err").open("a") as handle:
            handle.write("** Fatal ** Simulation terminated.\n")
    elif change == "no_severe":
        (directory / "eplusout.err").write_text("Only a summary: 1 Severe Errors\n")
    elif change in {"incomplete_end", "inconsistent_severe_summary"}:
        (directory / "eplusout.end").write_text(
            "EnergyPlus Terminated" if change == "incomplete_end"
            else "EnergyPlus Completed Successfully-- 1 Warning; 2 Severe Errors\n"
        )
    elif change == "missing_observable":
        (directory / "eplusout.eso").unlink()
    elif change in {"truncated_eso", "nonfinite_observable", "wrong_unit"}:
        path = directory / "eplusout.eso"
        text = path.read_text()
        replacements = {
            "truncated_eso": ("End of Data\n", ""),
            "nonfinite_observable": ("6,3600000", "6,nan"),
            "wrong_unit": ("Heating Energy [J]", "Heating Energy [W]"),
        }
        before, after = replacements[change]
        path.write_text(text.replace(before, after))
    elif change in {"nonzero_returncode", "wrong_failure_reason", "wrong_version"}:
        key, value = {
            "nonzero_returncode": ("returncode", 1),
            "wrong_failure_reason": ("failure_reason", "exit"),
            "wrong_version": ("version", "26.2.0"),
        }[change]
        metadata[key] = value
        (directory / "run.json").write_text(json.dumps(metadata))
    elif change in {"missing_metadata", "corrupt_metadata"}:
        path = directory / "run.json"
        if change == "missing_metadata":
            path.unlink()
        else:
            path.write_text("not JSON")
    else:
        path = {
            "changed_input": directory / "input.idf", "changed_weather": weather,
            "changed_engine": native.executable, "changed_source": source,
        }[change]
        path.write_text("Changed bytes\n")
    runner = ReferenceWarmupRunner(native, family="simple")
    with pytest.raises(EnergyPlusError) as caught:
        runner.run(source, weather)
    assert caught.value is native.error
    assert runner.recovered_runs == []


@pytest.mark.parametrize("reason", ["timeout", "exit", "incomplete", "input_changed", "version"])
def test_non_diagnostic_execution_errors_are_never_recovered(failed_run, reason):
    native, source, weather, directory, metadata = failed_run
    native.error = EnergyPlusError("Execution failure", reason=reason, directory=directory)
    runner = ReferenceWarmupRunner(native, family="simple")
    with pytest.raises(EnergyPlusError) as caught:
        runner.run(source, weather)
    assert caught.value is native.error
    assert runner.last_diagnostics is None
    assert runner.recovered_runs == []


def test_strict_success_is_forwarded_without_recovery(failed_run):
    native, source, weather, directory, metadata = failed_run
    (directory / "eplusout.err").write_text("** Warning ** Independent warning\n")
    native.result = RunResult(directory, version=native.version, cache_hit=True)
    runner = ReferenceWarmupRunner(native, family="simple")
    assert runner.run(source, weather) is native.result
    assert runner.last_diagnostics["strict_benchmark_evaluation"]
    assert not runner.last_diagnostics["accepted_warmup_only"]
    assert runner.recovered_runs == []


def test_unknown_output_family_fails_before_execution(failed_run):
    native, *_ = failed_run
    with pytest.raises(ValueError, match="family"):
        ReferenceWarmupRunner(native, family="unknown")
    assert native.calls == []


def test_conflicting_exception_returncode_is_not_overridden_by_metadata(failed_run):
    native, source, weather, directory, metadata = failed_run
    native.error = EnergyPlusError("Process failed", directory=directory,
                                   reason="simulation", returncode=1)
    runner = ReferenceWarmupRunner(native, family="simple")
    with pytest.raises(EnergyPlusError) as caught:
        runner.run(source, weather)
    assert caught.value is native.error
    assert runner.recovered_runs == []


def test_school_design_day_without_weather_validates_its_daily_observables(failed_run):
    native, source, weather, directory, metadata = failed_run
    (directory / "eplusout.eso").write_text(
        "6,1,HOTWATER,District Heating Water Energy [J] !Daily\n"
        "7,1,HOTWATER,District Heating Water Rate [W] !Daily\n"
        "End of Data Dictionary\n6,3600000\n7,2000\nEnd of Data\n"
    )
    metadata["weather_file"] = None
    metadata["weather_sha256"] = None
    metadata["command"] = [str(native.executable), "-D", metadata["input_file"]]
    (directory / "run.json").write_text(json.dumps(metadata))
    runner = ReferenceWarmupRunner(native, family="school")
    result = runner.run(source, design_day=True)
    assert result.weather_file is None
    assert extract_outputs("school", result) == {"Q": 1, "P": 2}
    assert runner.last_diagnostics["accepted_warmup_only"]


def test_office_recovery_requires_the_conditioned_area_energy_table(failed_run):
    native, source, weather, directory, metadata = failed_run
    runner = ReferenceWarmupRunner(native, family="office")
    with pytest.raises(EnergyPlusError) as caught:
        runner.run(source, weather)
    assert caught.value is native.error
    assert runner.recovered_runs == []
    (directory / "eplustbl.csv").write_text(
        "Site and Source Energy\n"
        ",Energy Per Conditioned Building Area [MJ/m2]\n"
        "Total Source Energy,100\n"
    )
    result = runner.run(source, weather)
    assert extract_outputs("office", result) == {"Y": 100}
    assert runner.last_diagnostics["accepted_warmup_only"]
