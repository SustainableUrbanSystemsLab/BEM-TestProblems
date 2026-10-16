"""Native regression checks require the recorded rejection and a measured repair."""

import json
import math
import os
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import pytest

from bem_testproblems import get_problem
from bem_testproblems.energyplus import EnergyPlusError, RunResult, sha256_file
from tools import validate_replication_failures as validation


@pytest.fixture
def native_audit(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    engine = tmp_path / "energyplus"
    engine.write_bytes(b"test native boundary")
    weather = tmp_path / "Seattle.epw"
    weather.write_bytes(b"verified test climate")
    modes, calls, extracted = {}, [], []

    class Problem:
        design_day = False
        family = "simple"
        weather_filename = "Seattle.epw"
        objective_unit = "kWh"

        def __init__(self, identifier, *, numerical_variant=None):
            self.id = identifier
            self.variant = numerical_variant
            self.provenance = {"numerical_variant": {"name": numerical_variant, "steps": 12}}

        def validate(self, x):
            assert len(x) == 1

        def render_modern(self, x, path):
            path.write_bytes(f"{self.id}:{self.variant}:{x}".encode())
            return path

        render_legacy = render_modern

        def objective_terms(self, x, components):
            return {"heat": components["Q_h"] * 2}

        def outer_loss(self, x, components):
            return components["Q_h"] * 2

    class Runner:
        def __init__(self, executable, *, expected_version, timeout, output_root, cache):
            assert cache is False
            self.executable = executable
            self.executable_sha256 = sha256_file(executable)
            self.version = expected_version
            self.output_root = output_root

        def run(self, model, weather, *, design_day):
            calls.append((model.parent.name, model.stem))
            directory = self.output_root / (model.parent.name + "-" + model.stem)
            directory.mkdir(parents=True)
            staged = directory / model.name
            shutil.copyfile(model, staged)
            model_hash, weather_hash = sha256_file(model), sha256_file(weather)
            mode = modes.get((model.parent.name, model.stem),
                             "warmup" if model.stem == "canonical" else "success")
            rejected = mode in {"warmup", "wrong-signature", "fatal"}
            zone = "OTHER ZONE" if mode == "wrong-signature" else "ZONE ONE"
            text = (f' ** Severe ** CheckWarmupConvergence: Loads Initialization, Zone="{zone}"'
                    ' did not converge after 25 warmup days.\n'
                    ' ** ~~~ ** ...Environment(RunPeriod)="Seattle"\n') if rejected else ""
            if mode == "fatal":
                text += " ** Fatal ** Interrupted simulation\n"
            (directory / "eplusout.err").write_text(text)
            (directory / "eplusout.end").write_text(
                f"EnergyPlus Completed Successfully-- 0 Warning; {int(rejected)} Severe Errors")
            if mode == "summary-severe":
                (directory / "eplusout.end").write_text(
                    "EnergyPlus Completed Successfully-- 0 Warning; 1 Severe Errors")
            if mode == "summary-missing":
                (directory / "eplusout.end").write_text("EnergyPlus Completed Successfully")
            metadata = {"status": "failed" if rejected else "success",
                        "failure_reason": "simulation", "returncode": 0,
                        "version": self.version, "executable_sha256": self.executable_sha256,
                        "input_file": str(staged), "input_sha256": model_hash,
                        "weather_sha256": weather_hash, "elapsed": 0.1}
            (directory / "run.json").write_text(json.dumps(metadata))
            if mode == "mutate":
                model.write_bytes(b"modified during simulation")
            if mode == "staged-mutated":
                staged.write_bytes(b"changed native input")
            if mode == "metadata":
                metadata["status"] = "failed"
                (directory / "run.json").write_text(json.dumps(metadata))
            if rejected and model.stem == "canonical" or mode == "fatal":
                raise EnergyPlusError("strict native rejection", directory=directory, reason="simulation")
            if mode == "timeout":
                raise EnergyPlusError("timeout", directory=directory, reason="timeout")
            return RunResult(directory, self.version, input_sha256=model_hash,
                             weather_sha256=weather_hash, executable_sha256=self.executable_sha256,
                             returncode=1 if mode == "exit" else 0, elapsed=0.1)

    def extract(family, run):
        extracted.append(run.directory.name)
        return {"Q_h": 5.0}

    monkeypatch.setattr(validation, "get_problem", Problem)
    monkeypatch.setattr(validation, "EnergyPlusRunner", Runner)
    monkeypatch.setattr(validation, "extract_outputs", extract)
    args = SimpleNamespace(engine=engine, version="26.2.0", timeout=30, weather_dir=tmp_path,
                           cases=tmp_path / "cases.json", baseline=tmp_path / "baseline.json",
                           work_dir=tmp_path / "runs", output=tmp_path / "report.json")
    cases, rows = [], []
    for index in (1, 2):
        case = {"case_id": f"case-{index}", "version": args.version, "problem": index, "x": [index],
                "weather_file": weather.name, "weather_sha256": sha256_file(weather),
                "expected_failure": {"stage": "simulation", "reason": "simulation", "severe_count": 1,
                                     "fatal_count": 0, "signatures": [{"kind": "CheckWarmupConvergence",
                                                                     "zone": "ZONE ONE",
                                                                     "environment": "Seattle"}]}}
        problem = Problem(index)
        model = problem.render_modern(case["x"], tmp_path / "model.epJSON")
        case["input_sha256"] = sha256_file(model)
        refined = Problem(index, numerical_variant=validation.VARIANT)
        model = refined.render_modern(case["x"], model)
        rows.append({"case_id": case["case_id"], "problem": index, "x": case["x"],
                     "canonical_input_sha256": case["input_sha256"], "input_sha256": sha256_file(model),
                     "weather_file": weather.name, "weather_sha256": sha256_file(weather),
                     "numerical_recipe": refined.provenance["numerical_variant"],
                     "passed": True, "severe_count": 0, "fatal_count": 0, "objective": 10.,
                     "components": {"Q_h": 5.}, "terms": {"heat": 10.}})
        cases.append(case)

    def write():
        args.cases.write_text(json.dumps({"cases": cases}))
        baseline = {"engine_version": args.version, "weather_kind": "canonical",
                    "diagnostics_policy": "strict", "numerical_variant": validation.VARIANT,
                    "case_fixture": {"sha256": sha256_file(args.cases)}, "cases": rows}
        args.baseline.write_text(json.dumps(baseline))

    write()
    return SimpleNamespace(args=args, cases=cases, rows=rows, write=write, modes=modes,
                           calls=calls, extracted=extracted)


def test_checks_recorded_failures_and_strict_repair_values_for_every_case(native_audit, monkeypatch):
    audit = native_audit
    summary = audit.args.output.parent / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    report = validation.validate(audit.args)
    assert report["passed"]
    assert len(audit.calls) == 4
    assert len(audit.extracted) == 2
    for row in report["cases"]:
        assert row["canonical"]["failure_reference_matched"]
        assert row["canonical"]["objective"] is None
        assert row["canonical"]["components"] is None
        assert row["refined"]["objective"] == 10
        assert all(value["passed"] for value in row["refined"]["comparison"].values())
    assert "2/2" in summary.read_text()


@pytest.mark.parametrize("stem,mode,message", [
    ("canonical", "success", "became successful"),
    ("canonical", "wrong-signature", "signatures changed"),
    ("canonical", "fatal", "severe/fatal counts changed"),
    ("canonical", "timeout", "changed stage/reason"),
    ("repaired", "fatal", "strict native rejection"),
    ("repaired", "warmup", "Severe/Fatal"),
    ("repaired", "exit", "completion or provenance"),
    ("repaired", "mutate", "bytes changed"),
    ("repaired", "staged-mutated", "input/engine provenance"),
    ("repaired", "metadata", "input/engine provenance"),
    ("repaired", "summary-severe", "completion or provenance"),
    ("repaired", "summary-missing", "completion or provenance"),
])
def test_changed_failure_or_unsafe_repair_cannot_pass_and_other_cases_are_exercised(
        native_audit, stem, mode, message):
    audit = native_audit
    audit.modes[("case-1", stem)] = mode
    with pytest.raises(AssertionError, match="failure/repair validation failed"):
        validation.validate(audit.args)
    report = json.loads(audit.args.output.read_text())
    assert not report["passed"]
    assert message in report["cases"][0]["failure"]["message"]
    assert report["cases"][1]["passed"]


@pytest.mark.parametrize("field,value", [
    ("objective", 9.0), ("components", {"Q_h": 6.}), ("terms", {"heat": 12.}),
    ("components", {"renamed": 5.}), ("terms", {}),
    ("x", [-1]), ("canonical_input_sha256", "wrong"), ("input_sha256", "wrong"),
    ("weather_sha256", "wrong"), ("numerical_recipe", {"name": "something else"}),
    ("passed", False), ("severe_count", 1), ("fatal_count", 1),
])
def test_reviewed_repair_baseline_is_a_real_numerical_and_identity_check(native_audit, field, value):
    audit = native_audit
    audit.rows[0][field] = value
    audit.write()
    with pytest.raises(AssertionError):
        validation.validate(audit.args)
    assert not json.loads(audit.args.output.read_text())["cases"][0]["passed"]


@pytest.mark.parametrize("change,message", [
    ("version", "engine, weather"), ("fixture-hash", "fixture SHA256"),
    ("extra", "exactly every"), ("missing", "exactly every"), ("duplicate", "exactly every"),
    ("duplicate-fixture", "duplicate case"), ("unsupported-engine", "unsupported engine"),
    ("empty-fixture", "no cases"), ("missing-baseline", "No such file"),
])
def test_preparation_failure_is_reported_before_running_any_native_case(native_audit, change, message):
    audit = native_audit
    baseline = json.loads(audit.args.baseline.read_text())
    if change == "version":
        baseline["engine_version"] = "8.5.0"
    elif change == "fixture-hash":
        baseline["case_fixture"]["sha256"] = "wrong"
    elif change == "extra":
        baseline["cases"].append({**baseline["cases"][0], "case_id": "extra"})
    elif change == "missing":
        baseline["cases"].pop()
    elif change == "duplicate":
        baseline["cases"].append(baseline["cases"][0])
    elif change in {"duplicate-fixture", "unsupported-engine", "empty-fixture"}:
        if change == "duplicate-fixture":
            audit.cases.append(audit.cases[0])
        elif change == "unsupported-engine":
            audit.cases[0]["version"] = "1.0.0"
        else:
            audit.cases.clear()
        audit.write()
        baseline = json.loads(audit.args.baseline.read_text())
    audit.args.baseline.write_text(json.dumps(baseline))
    if change == "missing-baseline":
        audit.args.baseline.unlink()
    with pytest.raises((ValueError, FileNotFoundError), match=message):
        validation.validate(audit.args)
    assert not audit.calls
    assert not json.loads(audit.args.output.read_text())["passed"]


@pytest.mark.parametrize("field", ["input_sha256", "weather_sha256", "weather_file"])
def test_canonical_input_and_weather_identity_cannot_be_replaced(native_audit, field):
    audit = native_audit
    audit.cases[0][field] = "wrong" if field != "weather_file" else "missing.epw"
    audit.write()
    with pytest.raises(AssertionError):
        validation.validate(audit.args)
    assert not json.loads(audit.args.output.read_text())["cases"][0]["passed"]


def test_nonfinite_refined_output_cannot_be_accepted(native_audit, monkeypatch):
    monkeypatch.setattr(validation, "extract_outputs", lambda *args: {"Q_h": float("nan")})
    with pytest.raises(AssertionError):
        validation.validate(native_audit.args)
    report = json.loads(native_audit.args.output.read_text())
    assert "Nonfinite" in report["cases"][0]["failure"]["message"]
    assert report["cases"][0]["refined"]["objective"] is None


def test_cli_requires_reviewed_baseline_and_runtime_failures_write_report(tmp_path):
    output = tmp_path / "report.json"
    arguments = ["--engine", "missing", "--version", "8.5.0", "--weather-dir", str(tmp_path),
                 "--work-dir", str(tmp_path / "runs"), "--output", str(output)]
    with pytest.raises(SystemExit) as missing:
        validation.main(arguments)
    assert missing.value.code == 2
    with pytest.raises(FileNotFoundError):
        validation.main(arguments + ["--baseline", str(tmp_path / "missing.json")])
    assert not json.loads(output.read_text())["passed"]


def test_legacy_engine_uses_the_same_strict_failure_and_repair_contract(native_audit):
    audit = native_audit
    audit.args.version = "8.5.0"
    for case in audit.cases:
        case["version"] = audit.args.version
    audit.write()
    assert validation.validate(audit.args)["passed"]


def test_other_engine_cases_are_not_run_and_small_roundoff_is_allowed(native_audit):
    audit = native_audit
    audit.cases.append({**audit.cases[0], "case_id": "other-engine", "version": "8.5.0"})
    audit.rows[0]["objective"] += 1e-6
    audit.write()
    report = validation.validate(audit.args)
    assert report["passed"] and len(report["cases"]) == 2
    assert all(case_id != "other-engine" for case_id, _ in audit.calls)


def test_native_ci_runs_failure_repairs_only_with_canonical_weather():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/validate.yml").read_text()
    assert workflow.count("tools/validate_replication_failures.py") == 2
    for version in ("8.5.0", "26.2.0"):
        assert f"--baseline reference/baselines/{version}-replication-failures.json" in workflow
    assert workflow.count(".validation-local/reports/replication-failures.json") == 4


def test_direct_script_entrypoint_imports_shared_helpers_without_repo_on_pythonpath(tmp_path):
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run(
        [sys.executable, str(root / "tools/validate_replication_failures.py"), "--help"],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True, text=True, check=False)
    assert process.returncode == 0, process.stderr
    assert "--baseline" in process.stdout


@pytest.mark.parametrize("version,oracle,proxy", [
    ("8.5.0", "oracle.exe", None), ("8.5.0", None, "proxy.exe"),
    ("26.2.0", "oracle.exe", "proxy.exe"),
])
def test_csharp_options_require_both_launchers_and_the_legacy_engine(native_audit, version, oracle, proxy):
    args = native_audit.args
    args.version, args.oracle, args.proxy = version, oracle, proxy
    with pytest.raises(ValueError, match="both --oracle and --proxy"):
        validation.validate(args)
    assert not native_audit.calls
    assert not json.loads(args.output.read_text())["passed"]


@pytest.fixture
def original_audit(native_audit, monkeypatch):
    audit = native_audit
    audit.args.version = "8.5.0"
    audit.args.oracle, audit.args.proxy = Path("Oracle.exe"), Path("EngineProxy.exe")
    for case in audit.cases:
        case["version"] = "8.5.0"
    audit.write()
    modes, calls = {}, []

    def run_oracle(problem, x, weather, directory, oracle, proxy, runner, *, expected_failure):
        calls.append((problem.id, x, expected_failure))
        mode = modes.get(problem.id)
        if mode == "execution":
            raise RuntimeError("Original C# oracle failed")
        archive = directory / "original-output"
        archive.mkdir()
        retained = directory.parent / (directory.name + "-canonical")
        for name in ("eplusout.err", "eplusout.end"):
            shutil.copyfile(retained / name, archive / name)
        (archive / "engine-exit-code.txt").write_text("0")
        shutil.copyfile(directory / "canonical.idf", archive / "input.idf")
        if mode == "input":
            (archive / "input.idf").write_text("Changed,physical,fields;")
        if mode == "fatal":
            with (archive / "eplusout.err").open("a") as handle:
                handle.write(" ** Fatal ** Original fatal error\n")
        if mode == "signature":
            diagnostic_file = archive / "eplusout.err"
            diagnostic_file.write_text(diagnostic_file.read_text().replace("ZONE ONE", "OTHER ZONE"))
        return 666.0, archive

    monkeypatch.setattr(validation.reference_validation, "run_oracle", run_oracle)
    audit.original_modes, audit.original_calls = modes, calls
    return audit


def test_original_csharp_reproduces_every_legacy_failure_without_accepting_its_value(original_audit):
    audit = original_audit
    report = validation.validate(audit.args)
    assert report["passed"] and report["original_csharp_checked"]
    assert len(audit.original_calls) == 2
    for row in report["cases"]:
        canonical = row["canonical"]
        assert canonical["objective"] is None and canonical["components"] is None
        assert canonical["reference_failure"]["severe_count"] == 1
        assert canonical["reference_diagnostic_objective"] == 666.0
        assert canonical["reference_diagnostic_objective_accepted"] is False


@pytest.mark.parametrize("mode,message", [
    ("execution", "Original C# oracle failed"), ("input", "IDF"),
    ("fatal", "severe/fatal counts changed"),
])
def test_csharp_execution_input_or_failure_mismatch_cannot_pass(original_audit, mode, message):
    audit = original_audit
    audit.original_modes[1] = mode
    with pytest.raises(AssertionError):
        validation.validate(audit.args)
    report = json.loads(audit.args.output.read_text())
    assert not report["cases"][0]["passed"]
    assert message in report["cases"][0]["failure"]["message"]
    assert report["cases"][1]["passed"]
    assert report["cases"][0]["canonical"]["objective"] is None
    assert report["original_csharp_requested"] and not report["original_csharp_checked"]


def _check_measured_values(problem, row):
    for group in ({"objective": row["objective"]}, row["components"], row["terms"]):
        assert group
        assert all(type(value) in (float, int) and math.isfinite(value) for value in group.values())
    assert row["objective"] == pytest.approx(
        problem.outer_loss(row["x"], row["components"]), rel=1e-12, abs=1e-9)
    assert row["terms"] == pytest.approx(
        problem.objective_terms(row["x"], row["components"]), rel=1e-12, abs=1e-9)
    assert type(row["severe_count"]) is int and row["severe_count"] == 0
    assert type(row["fatal_count"]) is int and row["fatal_count"] == 0


@pytest.mark.parametrize("version,count", [("8.5.0", 9), ("26.2.0", 5)])
def test_committed_native_repair_baselines_match_all_recorded_cases_and_actual_renderers(
        version, count, tmp_path):
    root = Path(__file__).resolve().parents[1]
    args = SimpleNamespace(version=version, cases=root / "reference/replication-failure-cases.json",
                           baseline=root / f"reference/baselines/{version}-replication-failures.json")
    document = json.loads(args.baseline.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert (document["rtol"], document["atol"]) == (validation.RTOL, validation.ATOL)
    cases, baseline = validation._read_cases(args)
    assert len(cases) == len(baseline) == count
    weather = {row["cache_path"]: row["sha256"] for row in json.loads(
        files("bem_testproblems").joinpath("data/weather-assets.json").read_bytes())["files"]}
    for case in cases:
        original = get_problem(case["problem"])
        repaired = get_problem(case["problem"], numerical_variant=validation.VARIANT)
        render = "render_legacy" if version == "8.5.0" else "render_modern"
        suffix = ".idf" if version == "8.5.0" else ".epJSON"
        canonical_model = getattr(original, render)(case["x"], tmp_path / ("canonical" + suffix))
        refined_model = getattr(repaired, render)(case["x"], tmp_path / ("refined" + suffix))
        assert sha256_file(canonical_model) == case["input_sha256"]
        assert original.weather_filename == case["weather_file"]
        assert weather[case["weather_file"]] == case["weather_sha256"]
        row = baseline[case["case_id"]]
        validation._baseline_identity(case, row, repaired, sha256_file(refined_model),
                                      weather[case["weather_file"]])
        _check_measured_values(repaired, row)


@pytest.mark.parametrize("version,numbers", [("8.5.0", {1, 4, 6, 10}), ("26.2.0", {4, 5, 10})])
def test_valid_control_measurements_preserve_canonical_reference_and_report_actual_model_changes(
        version, numbers, tmp_path):
    root = Path(__file__).resolve().parents[1]
    baseline = json.loads((root / f"reference/baselines/{version}-replication-failures.json").read_text())
    canonical_path = root / f"reference/baselines/{version}-canonical.json"
    canonical = {row["case_id"]: row for row in json.loads(canonical_path.read_text())["cases"]}
    controls = baseline["valid_controls"]
    assert len(controls) == len(numbers) and {row["problem"] for row in controls} == numbers
    for row in controls:
        problem = get_problem(row["problem"], numerical_variant=validation.VARIANT)
        previous = canonical[row["case_id"]]
        assert row["x"] == previous["x"] == list(problem.midpoint)
        assert row["canonical_baseline"] == {
            "path": canonical_path.relative_to(root).as_posix(), "sha256": sha256_file(canonical_path)}
        assert row["canonical_input_sha256"] == previous["input_sha256"]
        assert row["weather_file"] == previous["weather_file"] == problem.weather_filename
        assert row["weather_sha256"] == previous["weather_sha256"]
        assert row["numerical_recipe"] == problem.provenance["numerical_variant"]
        render = problem.render_legacy if version == "8.5.0" else problem.render_modern
        suffix = ".idf" if version == "8.5.0" else ".epJSON"
        assert sha256_file(render(row["x"], tmp_path / ("control" + suffix))) == row["input_sha256"]
        assert row["canonical_objective"] == previous["objective"]
        delta = row["objective"] - previous["objective"]
        assert row["delta_objective"] == pytest.approx(delta, rel=1e-12, abs=1e-9)
        assert row["delta_percent"] == pytest.approx(100 * delta / abs(previous["objective"]),
                                                    rel=1e-12, abs=1e-9)
        _check_measured_values(problem, row)


def test_numerical_mismatch_annotation_reports_the_actual_differences(native_audit, monkeypatch, capsys):
    audit = native_audit
    audit.rows[0]["objective"] = 9.0
    audit.write()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(AssertionError):
        validation.validate(audit.args)
    output = capsys.readouterr().out
    assert output.count("::error title=Recorded failure regression::") == 1
    assert "case-1 [refined-values]" in output
    assert "objective.objective: actual=10, expected=9, signed difference=+1" in output
    assert "percentage=+11.1111111%25" in output
    report = json.loads(audit.args.output.read_text())
    difference = report["cases"][0]["refined"]["comparison"]["objective.objective"]
    assert difference["actual"] == 10 and difference["expected"] == 9 and not difference["passed"]


def test_changed_canonical_signature_annotation_includes_actual_and_reviewed_zone(
        native_audit, monkeypatch, capsys):
    native_audit.modes[("case-1", "canonical")] = "wrong-signature"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(AssertionError):
        validation.validate(native_audit.args)
    output = capsys.readouterr().out
    assert "case-1 [canonical-simulation]" in output
    assert "native reason=simulation, returncode=0" in output
    assert "OTHER ZONE" in output and "reviewed failure=" in output and "ZONE ONE" in output
    assert "CheckWarmupConvergence" in output


def test_rejected_repair_reports_native_cause_and_keeps_its_objective_unavailable(
        native_audit, monkeypatch, capsys):
    native_audit.modes[("case-1", "repaired")] = "fatal"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(AssertionError):
        validation.validate(native_audit.args)
    output = capsys.readouterr().out
    assert "case-1 [refined-simulation]" in output
    assert "Interrupted simulation" in output and "%0A" in output
    report = json.loads(native_audit.args.output.read_text())
    row = report["cases"][0]["refined"]
    assert row["objective"] is None
    assert row["failure"]["reason"] == "simulation"
    assert row["failure"]["returncode"] == 0
    assert row["failure"]["diagnostics"]["fatal_count"] == 1


def test_github_annotations_escape_percent_and_newlines(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    validation._github_error("case: 50%\r\nnext line")
    assert capsys.readouterr().out == (
        "::error title=Recorded failure regression::case: 50%25%0D%0Anext line\n")
    monkeypatch.delenv("GITHUB_ACTIONS")
    validation._github_error("local error")
    assert not capsys.readouterr().out


def test_unavailable_native_diagnostics_preserve_the_original_failure_reason(tmp_path):
    details = validation._native_failure(EnergyPlusError("timed out", reason="timeout",
                                                         directory=tmp_path / "missing"))
    assert details["reason"] == "timeout" and details["message"] == "timed out"
    assert "diagnostics_unavailable" in details


def test_preparation_failure_annotation_explains_the_baseline_problem(native_audit, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    native_audit.args.baseline.unlink()
    with pytest.raises(FileNotFoundError):
        validation.validate(native_audit.args)
    output = capsys.readouterr().out
    assert "::error title=Recorded failure regression::Preparation failed:" in output
    assert "baseline.json" in output
    assert not native_audit.calls


def test_csharp_missing_archive_cannot_mask_original_execution_error(original_audit, monkeypatch, capsys):
    audit = original_audit
    audit.original_modes[1] = "execution"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(AssertionError):
        validation.validate(audit.args)
    output = capsys.readouterr().out
    assert "case-1 [original-csharp]: Original C# oracle failed" in output
    report = json.loads(audit.args.output.read_text())
    context = report["cases"][0]["canonical"]["original_csharp_failure"]
    assert context["message"] == "Original C# oracle failed"
    assert not context["archive_available"] and "diagnostics" not in context


def test_csharp_changed_signature_annotation_includes_actual_and_reviewed_diagnostics(
        original_audit, monkeypatch, capsys):
    audit = original_audit
    audit.original_modes[1] = "signature"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(AssertionError):
        validation.validate(audit.args)
    output = capsys.readouterr().out
    assert "case-1 [original-csharp]" in output and "original C#; diagnostics=" in output
    assert "OTHER ZONE" in output and "reviewed failure=" in output and "ZONE ONE" in output
    report = json.loads(audit.args.output.read_text())
    context = report["cases"][0]["canonical"]["original_csharp_failure"]
    assert context["archive_available"] and context["diagnostics"]["severe_count"] == 1
    assert context["diagnostics"]["signatures"][0]["zone"] == "OTHER ZONE"
    assert "EnergyPlus Completed Successfully" in context["completion"]


def _measurement_notices(output):
    prefix = "::notice title=Strict repaired measurement::"
    return [json.loads(line[len(prefix):].replace("%0D", "\r").replace("%0A", "\n").replace("%25", "%"))
            for line in output.splitlines() if line.startswith(prefix)]


def test_public_strict_measurement_notice_is_complete_and_allowlisted(native_audit, monkeypatch, capsys):
    audit = native_audit
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert validation.validate(audit.args)["passed"]
    measurements = _measurement_notices(capsys.readouterr().out)
    assert len(measurements) == 2
    for case, measured in zip(audit.cases, measurements, strict=True):
        assert set(measured) == {"case_id", "engine_version", "engine_sha256", "platform",
                                 "case_fixture_sha256", "identity", "objective", "components", "terms",
                                 "severe_count", "fatal_count"}
        assert measured["case_id"] == case["case_id"] and measured["engine_version"] == audit.args.version
        assert measured["engine_sha256"] == sha256_file(audit.args.engine)
        assert measured["case_fixture_sha256"] == sha256_file(audit.args.cases)
        assert measured["platform"]
        assert set(measured["identity"]) == {"problem", "x", "canonical_input_sha256", "input_sha256",
                                             "weather_file", "weather_sha256", "numerical_recipe"}
        assert measured["identity"]["canonical_input_sha256"] == case["input_sha256"]
        assert measured["identity"]["weather_sha256"] == case["weather_sha256"]
        assert measured["objective"] == 10 and measured["components"] == {"Q_h": 5}
        assert measured["terms"] == {"heat": 10}
        assert measured["severe_count"] == measured["fatal_count"] == 0
        assert str(audit.args.work_dir.parent) not in json.dumps(measured)


@pytest.mark.parametrize("change", ["numeric", "schema"])
def test_strict_actual_measurements_remain_visible_when_baseline_comparison_fails(
        native_audit, monkeypatch, capsys, change):
    audit = native_audit
    if change == "numeric":
        audit.rows[0]["objective"] = 9.0
    else:
        audit.rows[0]["components"] = {"renamed": 5.0}
    audit.write()
    original_baseline = audit.args.baseline.read_bytes()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(AssertionError):
        validation.validate(audit.args)
    measured = _measurement_notices(capsys.readouterr().out)
    assert len(measured) == 2
    assert measured[0]["case_id"] == "case-1" and measured[0]["objective"] == 10
    assert measured[0]["components"] == {"Q_h": 5.0}
    assert audit.args.baseline.read_bytes() == original_baseline


@pytest.mark.parametrize("failure", ["native", "canonical", "nonfinite", "missing-outputs"])
def test_no_measurement_notice_is_emitted_without_a_strict_finite_repaired_measurement(
        native_audit, monkeypatch, capsys, failure):
    audit = native_audit
    if failure in {"native", "canonical"}:
        for case in audit.cases:
            audit.modes[(case["case_id"], "repaired" if failure == "native" else "canonical")] = (
                "fatal" if failure == "native" else "success")
    elif failure == "nonfinite":
        monkeypatch.setattr(validation, "extract_outputs", lambda *args: {"Q_h": float("nan")})
    else:
        def missing_outputs(*args):
            raise ValueError("Missing simulator outputs")
        monkeypatch.setattr(validation, "extract_outputs", missing_outputs)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(AssertionError):
        validation.validate(audit.args)
    assert not _measurement_notices(capsys.readouterr().out)


def test_measurement_notice_drops_unallowlisted_fields_and_escapes_workflow_data(
        native_audit, monkeypatch, capsys):
    audit = native_audit
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    runner = SimpleNamespace(version=audit.args.version, executable_sha256=sha256_file(audit.args.engine))
    row = audit.rows[0]
    identity = {**row, "machine_path": str(audit.args.work_dir)}
    identity["numerical_recipe"] = {"name": "convergence-refined", "note": "50%\r\nfixed recipe"}
    actual = {"objective": 10., "components": {"Q_h": 5.}, "terms": {"heat": 10.},
              "private_path": str(audit.args.work_dir)}
    validation._publish_measurement(audit.args, runner, audit.cases[0], identity, actual,
                                    {"severe_count": 0, "fatal_count": 0})
    output = capsys.readouterr().out
    assert "50%25" in output and len(output.splitlines()) == 1
    measured = _measurement_notices(output)[0]
    assert measured["identity"]["numerical_recipe"]["note"] == "50%\r\nfixed recipe"
    assert str(audit.args.work_dir) not in output
    assert "machine_path" not in measured["identity"] and "private_path" not in measured
    monkeypatch.delenv("GITHUB_ACTIONS")
    validation._publish_measurement(audit.args, runner, audit.cases[0], identity, actual,
                                    {"severe_count": 0, "fatal_count": 0})
    assert not capsys.readouterr().out


@pytest.mark.parametrize("expected,actual,passes", [
    (100., 100.009, True), (100., 100.011, False),
    (0., 9e-8, True), (0., 1.1e-7, False),
])
def test_reviewed_cross_platform_tolerance_has_real_relative_and_absolute_boundaries(
        native_audit, monkeypatch, expected, actual, passes):
    audit = native_audit
    for row in audit.rows:
        row.update(objective=expected, components={"Q_h": expected / 2}, terms={"heat": expected})
    audit.write()
    monkeypatch.setattr(validation, "extract_outputs", lambda *args: {"Q_h": actual / 2})
    if passes:
        validation.validate(audit.args)
    else:
        with pytest.raises(AssertionError):
            validation.validate(audit.args)
    report = json.loads(audit.args.output.read_text())
    assert report["passed"] is passes
    assert (report["rtol"], report["atol"]) == (1e-4, 1e-7)
    difference = report["cases"][0]["refined"]["comparison"]["objective.objective"]
    assert difference["passed"] is passes
    assert difference["allowed_difference"] == pytest.approx(max(1e-7, 1e-4 * abs(expected)))
    assert difference["signed_difference"] == pytest.approx(actual - expected)
    assert difference["percentage_difference"] == (
        pytest.approx(100 * (actual - expected) / abs(expected)) if expected else None)
