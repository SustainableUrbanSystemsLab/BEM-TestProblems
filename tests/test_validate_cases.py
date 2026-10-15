"""Reference-checked rejections must stay rejected while the audit continues."""

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from bem_testproblems.energyplus import EnergyPlusError, RunResult, sha256_file
from tools import validate_cases as validation


def _model_bytes(problem, x):
    return f"Version,26.2;Test,{problem},{x[0]};\n".encode()


def _diagnostic_files(directory, *, kind="warmup", zone="ZONE ONE", environment="Seattle", code="0"):
    directory.mkdir(parents=True, exist_ok=True)
    message = (f'CheckWarmupConvergence: Loads Initialization, Zone="{zone}" did not converge after 25 warmup days.'
               if kind == "warmup" else "Unexpected HVAC error")
    text = (f' ** Severe ** {message}\n'
            f' ** ~~~ ** ...Environment(RunPeriod)="{environment}"\n')
    if kind == "fatal":
        text += " ** Fatal ** A fatal error\n"
    (directory / "eplusout.err").write_text(text)
    (directory / "eplusout.end").write_text(
        "EnergyPlus Completed Successfully-- 0 Warning; 1 Severe Errors; Elapsed Time=00hr 00min 1sec")
    (directory / "engine-exit-code.txt").write_text(code)


def _expected_failure():
    return {"stage": "simulation", "reason": "simulation", "severe_count": 1, "fatal_count": 0,
            "signatures": [{"zone": "zone one", "environment": "RunPeriod: SEATTLE",
                            "kind": "CheckWarmupConvergence"}]}


@pytest.fixture
def audit(tmp_path, monkeypatch):
    weather = tmp_path / "weather"
    weather.mkdir()
    (weather / "Seattle.epw").write_bytes(b"verified fixture EPW")
    (weather / "synthetic_seattle.epw").write_bytes(b"synthetic fixture")
    (weather / "synthetic_houston.epw").write_bytes(b"synthetic fixture")
    engine = tmp_path / "energyplus"
    engine.write_bytes(b"fixture executable")
    modes, calls, extracted = {}, [], []

    class Problem:
        def __init__(self, identifier):
            self.id = identifier
            self.design_day = identifier == 13
            self.family = "school" if self.design_day else "simple"
            self.weather_filename = "Belgrade.epw" if self.design_day else "Seattle.epw"
            self.objective_unit = "EUR"

        def validate(self, x):
            assert len(x) == 1 or (self.id == 1 and len(x) == 4)

        def render_modern(self, x, destination):
            destination.write_bytes(_model_bytes(self.id, x))
            return destination

        render_legacy = render_modern

        def objective_terms(self, x, outputs):
            return {"total": sum(outputs.values())}

        def outer_loss(self, x, outputs):
            return sum(outputs.values())

    class Runner:
        def __init__(self, executable, *, expected_version, timeout, output_root, cache):
            assert cache is False
            self.executable = executable
            self.executable_sha256 = sha256_file(executable)
            self.version = expected_version
            self.timeout = timeout
            self.output_root = output_root

        def run(self, model, weather=None, *, design_day=False):
            case_id = model.parent.name
            calls.append((case_id, weather, design_day))
            directory = self.output_root / (case_id + "-raw")
            directory.mkdir()
            staged = directory / model.name
            shutil.copyfile(model, staged)
            input_hash = sha256_file(staged)
            weather_hash = sha256_file(weather) if weather else None
            mode = modes.get(case_id, "success")
            if mode != "success":
                _diagnostic_files(directory, kind=mode if mode in {"fatal", "other"} else "warmup",
                                  environment="Houston" if mode == "wrong-environment" else "Seattle")
                metadata = {"status": "failed", "failure_reason": "simulation", "returncode": 0,
                            "version": self.version, "executable_sha256": self.executable_sha256,
                            "input_file": str(staged), "input_sha256": input_hash,
                            "weather_sha256": weather_hash, "elapsed": 0.1}
                (directory / "run.json").write_text(json.dumps(metadata))
                if mode == "incomplete":
                    (directory / "eplusout.end").write_text("EnergyPlus Terminated")
                if mode == "mutate":
                    model.write_bytes(b"changed model")
                raise EnergyPlusError("Strict simulation rejected", directory=directory,
                                      reason="simulation")
            if mode == "success":
                (directory / "eplusout.err").write_text("")
                (directory / "eplusout.end").write_text("EnergyPlus Completed Successfully")
            return RunResult(directory=directory, version=self.version, input_sha256=input_hash,
                             weather_sha256=weather_hash, elapsed=0.1)

    def extract(family, run):
        extracted.append(run.directory.name)
        return {"Q": 8.0, "P": 2.0} if family == "school" else {"Q_h": 10.0}

    monkeypatch.setattr(validation, "EnergyPlusRunner", Runner)
    monkeypatch.setattr(validation, "get_problem", Problem)
    monkeypatch.setattr(validation, "extract_outputs", extract)
    cases = [{"case_id": "first", "problem": 1, "x": [1]},
             {"case_id": "second", "problem": 2, "x": [2]}]
    fixture_file, baseline_file = tmp_path / "cases.json", tmp_path / "baseline.json"
    args = SimpleNamespace(engine=engine, version="26.2.0", timeout=30,
                           weather_dir=weather, weather_kind="canonical", cases=fixture_file,
                           baseline=baseline_file, case_id=None, oracle=None, proxy=None,
                           rtol=1e-6, atol=1e-7, work_dir=tmp_path / "runs", output=tmp_path / "report.json")

    def write(*, failed=("first",), selected=None, baseline_version=None):
        chosen = selected if selected is not None else cases
        fixture_file.write_text(json.dumps({"cases": chosen}))
        rows = []
        for case in chosen:
            identifier = case["problem"]
            weather_name = None if identifier == 13 else "Seattle.epw"
            school = identifier == 13
            outputs = {"Q": 8.0, "P": 2.0} if school else {"Q_h": 10.0}
            row = {**case, "passed": case["case_id"] not in failed,
                   "input_sha256": hashlib.sha256(_model_bytes(identifier, case["x"])).hexdigest(),
                   "weather_file": weather_name,
                   "weather_sha256": sha256_file(weather / weather_name) if weather_name else None}
            if not row["passed"]:
                row.update(objective=None, components=None, terms=None, expected_failure=_expected_failure())
            else:
                row.update(objective=10.0, components=outputs, terms={"total": 10.0})
            rows.append(row)
        baseline_file.write_text(json.dumps({"engine_version": baseline_version or args.version,
                                            "weather_kind": args.weather_kind, "cases": rows}))
        return rows

    return SimpleNamespace(args=args, write=write, modes=modes, calls=calls, extracted=extracted,
                           cases=cases, tmp=tmp_path)


def test_expected_rejection_remains_null_and_later_success_is_compared(audit):
    audit.write()
    audit.modes["first"] = "warmup"
    report = validation.validate(audit.args)
    first, second = report["cases"]
    assert report["passed"]
    assert first["passed"] is False and first["validation_passed"] is True
    assert first["objective"] is first["components"] is first["terms"] is None
    assert first["observed_failure"]["severe_count"] == 1
    assert first["failure_reference_matched"]
    assert second["regression_comparison"]["objective"]["passed"]
    assert audit.extracted == ["second-raw"]
    assert report["accepted_simulations"] == report["reference_checked_rejections"] == 1


@pytest.mark.parametrize("mode,match", [("success", "became successful"),
                                       ("fatal", "severe/fatal counts"),
                                       ("other", "not CheckWarmupConvergence"),
                                       ("wrong-environment", "signatures changed"),
                                       ("incomplete", "completion/severe"),
                                       ("mutate", "bytes changed during")])
def test_changed_rejection_is_a_visible_failure_and_does_not_stop_other_cases(audit, mode, match):
    audit.write()
    audit.modes["first"] = mode
    with pytest.raises(AssertionError, match=match):
        validation.validate(audit.args)
    report = json.loads(audit.args.output.read_text())
    assert not report["passed"]
    assert len(report["cases"]) == len(audit.calls) == 2
    assert report["cases"][0]["objective"] is None
    assert report["cases"][0]["validation_error"]
    assert report["cases"][1]["validation_passed"]


def test_unexpected_strict_failure_has_no_penalty_and_does_not_match_a_success_baseline(audit):
    audit.write(failed=())
    audit.modes["first"] = "warmup"
    with pytest.raises(AssertionError, match="Strict simulation rejected"):
        validation.validate(audit.args)
    report = json.loads(audit.args.output.read_text())
    assert report["cases"][0]["objective"] is None
    assert report["cases"][0]["failure"]["reason"] == "simulation"
    assert "failure_reference_matched" not in report["cases"][0]
    assert report["cases"][1]["passed"]


def test_synthetic_weather_still_cannot_accept_warmup_failures(audit):
    audit.args.weather_kind = "synthetic-ci"
    audit.write()
    with pytest.raises(ValueError, match="Synthetic validation cannot accept expected failures"):
        validation.validate(audit.args)
    assert not audit.calls


@pytest.mark.parametrize("field", ["input_sha256", "weather_sha256"])
def test_hash_guard_prevents_simulation_and_remaining_cases_still_run(audit, field):
    rows = audit.write(failed=())
    rows[0][field] = "0" * 64
    audit.args.baseline.write_text(json.dumps({"engine_version": "26.2.0", "weather_kind": "canonical",
                                             "cases": rows}))
    with pytest.raises(AssertionError, match="Baseline .* bytes"):
        validation.validate(audit.args)
    assert [call[0] for call in audit.calls] == ["second"]
    report = json.loads(audit.args.output.read_text())
    assert len(report["cases"]) == 2


def test_no_weather_is_resolved_for_canonical_school_and_old_namespace_still_works(audit):
    audit.write(failed=(), selected=[{"case_id": "school", "problem": 13, "x": [1]}])
    report = validation.validate(audit.args)
    assert audit.calls == [("school", None, True)]
    assert report["cases"][0]["weather_file"] is None
    assert report["cases"][0]["weather_sha256"] is None


def test_numeric_report_contains_signed_and_percentage_change_and_zero_is_undefined():
    difference = validation.numerical_difference(9, 10, "kWh", rtol=1e-6, atol=1e-7)
    assert difference["signed_difference"] == -1
    assert difference["absolute_difference"] == 1
    assert difference["percentage_difference"] == -10
    assert validation.numerical_difference(0, 0, "kW", rtol=0, atol=0)["percentage_difference"] is None


def test_numeric_failures_keep_all_case_comparisons_and_signed_values(audit):
    rows = audit.write(failed=())
    rows[0]["objective"] = 9.0
    rows[0]["components"]["Q_h"] = 11.0
    audit.args.baseline.write_text(json.dumps({"engine_version": "26.2.0", "weather_kind": "canonical",
                                             "cases": rows}))
    with pytest.raises(AssertionError, match="first Q_h"):
        validation.validate(audit.args)
    report = json.loads(audit.args.output.read_text())
    differences = report["cases"][0]["regression_comparison"]
    assert differences["Q_h"]["signed_difference"] == -1
    assert differences["Q_h"]["percentage_difference"] == pytest.approx(-100 / 11)
    assert differences["objective"]["signed_difference"] == 1
    assert len(report["comparison_failures"]) == 2
    assert "percentage=" in report["comparison_failures"][0]
    statistic = report["regression_summary"]["simple:Q_h"]
    assert statistic["max_absolute_percentage_difference"] == pytest.approx(100 / 11)
    assert statistic["signed_percentage_at_maximum"] == pytest.approx(-100 / 11)
    assert report["cases"][1]["validation_passed"]


def test_optional_orientation_case_can_be_selected_from_existing_26_case_fixture(audit):
    orientation = {"case_id": "p01-orientation90", "problem": 1, "x": [90, 3, 3, 0.5]}
    audit.write(failed=(), selected=[*audit.cases, orientation])
    audit.args.cases.write_text(json.dumps({"cases": audit.cases}))
    audit.args.include_orientation90 = True
    audit.args.case_id = [orientation["case_id"]]
    report = validation.validate(audit.args)
    assert report["cases"][0]["x"] == orientation["x"]
    assert [call[0] for call in audit.calls] == [orientation["case_id"]]


def test_wrong_baseline_engine_is_rejected_before_any_simulation(audit):
    audit.write(failed=(), baseline_version="8.5.0")
    with pytest.raises(ValueError, match="Baseline engine/weather variant"):
        validation.validate(audit.args)
    assert not audit.calls


def test_failed_original_archive_is_checked_but_its_returned_objective_is_diagnostic_only(audit, monkeypatch):
    audit.args.version = "8.5.0"
    audit.args.oracle, audit.args.proxy = Path("oracle.exe"), Path("proxy.exe")
    audit.write()
    audit.modes["first"] = "warmup"
    seen = []

    def oracle(problem, x, weather, directory, *args, **kwargs):
        seen.append((problem.id, kwargs))
        archive = directory / "original-output"
        _diagnostic_files(archive) if kwargs else archive.mkdir()
        shutil.copyfile(directory / "model.idf", archive / "input.idf")
        return (123.0 if kwargs else 10.0), archive

    monkeypatch.setattr(validation, "run_oracle", oracle)
    monkeypatch.setattr(validation, "fixed_row_outputs", lambda problem, directory: {"Q_h": 10.0})
    report = validation.validate(audit.args)
    first = report["cases"][0]
    assert first["reference_diagnostic_objective"] == 123
    assert first["reference_diagnostic_objective_accepted"] is False
    assert first["objective"] is None
    assert seen[0][1]["expected_failure"] == _expected_failure()
    assert report["cases"][1]["reference_comparison"]["objective"]["passed"]


def test_school_original_caller_weather_is_recorded_as_auxiliary_not_python_weather(audit, monkeypatch):
    audit.args.version = "8.5.0"
    audit.args.oracle, audit.args.proxy = Path("oracle.exe"), Path("proxy.exe")
    audit.write(failed=(), selected=[{"case_id": "school", "problem": 13, "x": [1]}])
    original_weather = []

    def oracle(problem, x, weather, directory, *args, **kwargs):
        original_weather.append(weather)
        archive = directory / "original-output"
        archive.mkdir()
        shutil.copyfile(directory / "model.idf", archive / "input.idf")
        return 10.0, archive

    monkeypatch.setattr(validation, "run_oracle", oracle)
    monkeypatch.setattr(validation, "fixed_row_outputs", lambda problem, directory: {"Q": 8.0, "P": 2.0})
    report = validation.validate(audit.args)
    item = report["cases"][0]
    assert audit.calls[0][1] is None
    assert original_weather[0].name == "Seattle.epw"
    assert item["weather_sha256"] is None
    assert item["reference_auxiliary_weather"]["weather_sha256"] == sha256_file(original_weather[0])


@pytest.mark.parametrize("code", ["1", "missing"])
def test_reviewed_original_failure_still_requires_successful_process_completion(tmp_path, code):
    _diagnostic_files(tmp_path, code=code)
    if code == "missing":
        (tmp_path / "engine-exit-code.txt").unlink()
    with pytest.raises(RuntimeError, match="did not return success"):
        validation.require_expected_failure_archive(tmp_path, _expected_failure())


def test_github_summary_is_written_after_aggregate_failure_and_known_rejections_are_warnings(
        audit, monkeypatch, capsys):
    audit.write(selected=[*audit.cases, {"case_id": "unexpected", "problem": 2, "x": [3]}])
    audit.modes.update(first="warmup", unexpected="other")
    summary = audit.tmp / "github-summary.md"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    with pytest.raises(AssertionError, match="Strict simulation rejected"):
        validation.validate(audit.args)
    text = summary.read_text(encoding="utf-8")
    assert "Validation: **FAIL**" in text
    assert "Accepted simulations: **1**. Reference-checked rejections: **1**" in text
    assert "| first | Rejected warmup | PASS | unavailable | unavailable | unavailable |" in text
    assert "| second | Accepted | PASS | 10 | +0 (+0%) | unavailable |" in text
    assert "| unexpected | Rejected | FAIL (simulation) | unavailable" in text
    assert str(audit.args.output).replace("\\", "\\\\") in text
    assert "::warning::first: rejected simulation; failure reference matched" in capsys.readouterr().out


def test_csharp_mismatch_does_not_count_a_native_only_failure_match(audit, monkeypatch):
    audit.args.version = "8.5.0"
    audit.args.oracle, audit.args.proxy = Path("oracle.exe"), Path("proxy.exe")
    audit.write(selected=[audit.cases[0]])
    audit.modes["first"] = "warmup"
    summary = audit.tmp / "github-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def failed_oracle(*args, **kwargs):
        raise AssertionError("Original archived signature changed")

    monkeypatch.setattr(validation, "run_oracle", failed_oracle)
    with pytest.raises(AssertionError, match="Original archived signature changed"):
        validation.validate(audit.args)
    report = json.loads(audit.args.output.read_text())
    assert report["cases"][0]["failure_reference_matched"] is True
    assert report["cases"][0]["validation_passed"] is False
    assert report["reference_checked_rejections"] == 0
    assert "Reference-checked rejections: **0**" in summary.read_text(encoding="utf-8")


def test_summary_reports_signed_reference_deltas_and_escapes_case_metadata():
    difference = validation.numerical_difference(9, 10, "kWh", rtol=1, atol=0)
    report = {"engine_version": "26.2.0", "weather_kind": "canonical", "passed": True,
              "cases": [{"case_id": "case|with\nnewline", "passed": True,
                         "validation_passed": True, "objective": 9,
                         "regression_comparison": {"objective": difference},
                         "reference_comparison": {"objective": difference}}]}
    summary = validation.github_summary(report, "reports/audit.json")
    assert "case\\|with newline" in summary
    assert "| 9 | -1 (-10%) | -1 (-10%) |" in summary
    assert "Report JSON: reports/audit.json" in summary


@pytest.mark.parametrize("family,expected", [
    ("simple", {"E_L": 1, "Q_h": 2, "Q_c": 3}),
    ("school", {"Q": 4, "P": 5.75}),
    ("detailed", {"H_1": 11, "H_2": 12, "H_3": 13, "H_4": 14, "H_5": 15, "H_6": 16,
                  "C": 17, "V_legacy": 18, "L_N": 21, "L_W": 22, "L_E": 23, "L_S": 24, "L_I": 25}),
    ("office", {"Y": 843.38}),
])
def test_independent_csharp_row_contract_and_units(tmp_path, family, expected):
    # Distinct values, including a decoy second fan, detect index/unit mistakes.
    rows = ["0,0"] * 57
    energies = {12: 1, 13: 2, 14: 3, 23: 21, 24: 22, 25: 23, 26: 24, 27: 25,
                28: 11, 29: 12, 30: 13, 31: 14, 32: 15, 33: 16, 34: 18, 35: 99, 36: 17, 55: 4}
    for row, kwh in energies.items():
        rows[row] = f"0,{kwh * 3.6e6}"
    rows[56] = "0,5750"
    (tmp_path / "eplusout.eso").write_text("\n".join(rows))
    table = ["0,0,0,0,0"] * 17
    table[16] = "0,0,0,0,843.38,999"
    (tmp_path / "eplustbl.csv").write_text("\n".join(table))
    assert validation.fixed_row_outputs(SimpleNamespace(family=family), tmp_path) == expected


@pytest.mark.parametrize("compare", [validation.require_close, validation.numerical_difference])
@pytest.mark.parametrize("actual,expected", [(float("inf"), 1), (1, float("nan"))])
def test_nonfinite_reference_values_are_never_accepted(compare, actual, expected):
    with pytest.raises(AssertionError, match="Nonfinite"):
        compare(actual, expected, "output", rtol=1e-6, atol=1e-7)


@pytest.mark.parametrize("change,match", [
    ({"x": [-1]}, "design does not match"),
    ({"passed": "false"}, "outcome is not Boolean"),
    ({"passed": False}, "must not contain accepted"),
    ({"components": {"renamed_output": 10}}, "output schema changed"),
])
def test_invalid_baseline_identity_or_schema_cannot_pass_the_audit(audit, change, match):
    rows = audit.write(failed=())
    rows[0].update(change)
    baseline = json.loads(audit.args.baseline.read_text())
    baseline["cases"] = rows
    audit.args.baseline.write_text(json.dumps(baseline))
    with pytest.raises(AssertionError, match=match):
        validation.validate(audit.args)
    report = json.loads(audit.args.output.read_text())
    assert not report["cases"][0]["validation_passed"]
    assert report["cases"][1]["validation_passed"]


@pytest.mark.parametrize("change,match", [
    ("process", "process/engine provenance"),
    ("engine", "process/engine provenance"),
    ("staged-input", "input bytes changed"),
    ("weather", "weather bytes changed"),
])
def test_reviewed_failure_requires_intact_retained_provenance(audit, change, match):
    audit.write(selected=[audit.cases[0]])
    audit.modes["first"] = "warmup"
    report = validation.validate(audit.args)
    directory = Path(report["cases"][0]["failure"]["directory"])
    runner = validation.EnergyPlusRunner(audit.args.engine, expected_version=audit.args.version,
                                        timeout=30, output_root=audit.args.work_dir, cache=False)
    metadata_file = directory / "run.json"
    metadata = json.loads(metadata_file.read_text())
    if change == "process":
        metadata["returncode"] = 1
    elif change == "engine":
        audit.args.engine.write_bytes(b"replaced executable")
    elif change == "staged-input":
        Path(metadata["input_file"]).write_bytes(b"replaced input")
    else:
        metadata["weather_sha256"] = "0" * 64
    metadata_file.write_text(json.dumps(metadata))
    with pytest.raises(AssertionError, match=match):
        validation.require_native_failure(
            EnergyPlusError("rejected", directory=directory, reason="simulation"), runner,
            audit.args.work_dir / "first" / "model.epJSON", audit.args.weather_dir / "Seattle.epw",
            _expected_failure())


def test_incomplete_timeout_is_not_a_reviewed_warmup_failure_and_audit_continues(audit, monkeypatch):
    audit.write()
    run = validation.EnergyPlusRunner.run
    partial = audit.tmp / "partial-timeout"
    partial.mkdir()

    def timeout_first(runner, model, weather=None, **kwargs):
        if model.parent.name == "first":
            raise EnergyPlusError("process timed out", directory=partial, reason="timeout")
        return run(runner, model, weather, **kwargs)

    monkeypatch.setattr(validation.EnergyPlusRunner, "run", timeout_first)
    with pytest.raises(AssertionError, match="changed stage/reason"):
        validation.validate(audit.args)
    report = json.loads(audit.args.output.read_text())
    assert report["cases"][0]["failure"]["reason"] == "timeout"
    assert report["reference_checked_rejections"] == 0
    assert report["cases"][1]["validation_passed"]


@pytest.mark.parametrize("mutation,match", [("missing-environment", "missing its zone/environment"),
                                            ("wrong-stage", "simulation-stage"),
                                            ("inconsistent-completion", "completion/severe")])
def test_reviewed_rejection_needs_complete_context_and_completion(tmp_path, mutation, match):
    _diagnostic_files(tmp_path)
    expected = _expected_failure()
    if mutation == "missing-environment":
        err = tmp_path / "eplusout.err"
        err.write_text(err.read_text().splitlines()[0])
    elif mutation == "wrong-stage":
        expected["stage"] = "outputs"
    else:
        end = tmp_path / "eplusout.end"
        end.write_text(end.read_text().replace("1 Severe", "2 Severe"))
    with pytest.raises(AssertionError, match=match):
        validation.require_expected_failure_archive(tmp_path, expected)


@pytest.mark.parametrize("mutation,match", [("duplicate-cases", "duplicate case IDs"),
                                            ("duplicate-baseline", "Baseline contains duplicate"),
                                            ("unknown-case", "Unknown validation case")])
def test_ambiguous_case_selection_is_rejected_before_simulation(audit, mutation, match):
    audit.write(failed=())
    if mutation == "duplicate-cases":
        audit.args.cases.write_text(json.dumps({"cases": [audit.cases[0], audit.cases[0]]}))
    elif mutation == "duplicate-baseline":
        baseline = json.loads(audit.args.baseline.read_text())
        baseline["cases"].append(baseline["cases"][0])
        audit.args.baseline.write_text(json.dumps(baseline))
    else:
        audit.args.case_id = ["not-a-case"]
    with pytest.raises(ValueError, match=match):
        validation.validate(audit.args)
    assert not audit.calls


def test_unexercised_baseline_case_cannot_be_reported_as_complete(audit):
    audit.write(failed=())
    baseline = json.loads(audit.args.baseline.read_text())
    baseline["cases"].append({**baseline["cases"][0], "case_id": "unexercised"})
    audit.args.baseline.write_text(json.dumps(baseline))
    with pytest.raises(AssertionError, match="not exercised: unexercised"):
        validation.validate(audit.args)
    report = json.loads(audit.args.output.read_text())
    assert len(report["cases"]) == 2 and report["accepted_simulations"] == 2
    assert not report["passed"]


def test_measurement_without_baseline_does_not_claim_reference_agreement(audit):
    audit.write(failed=())
    audit.args.baseline = None
    report = validation.validate(audit.args)
    assert report["comparison"] == "measurement-only"
    assert "Not compared" in validation.github_summary(report, audit.args.output)
    assert all("regression_comparison" not in case for case in report["cases"])


def test_cli_parses_selection_and_reference_options_without_running_an_engine(monkeypatch):
    calls = []
    monkeypatch.setattr(validation, "validate", lambda args: calls.append(args) or "report")
    assert validation.main([
        "--engine", "energyplus", "--version", "8.5.0", "--weather-dir", "weather",
        "--weather-kind", "canonical", "--work-dir", "runs", "--output", "report.json",
        "--baseline", "baseline.json", "--oracle", "oracle.exe", "--proxy", "proxy.exe",
        "--case-id", "p01-midpoint", "--case-id", "p01-orientation90", "--include-orientation90",
    ]) == "report"
    args = calls[0]
    assert args.version == "8.5.0" and args.weather_kind == "canonical"
    assert args.case_id == ["p01-midpoint", "p01-orientation90"] and args.include_orientation90
    assert args.baseline == Path("baseline.json") and args.oracle == Path("oracle.exe")
    assert (args.rtol, args.atol, args.timeout) == (1e-6, 1e-7, 300)


def test_cli_help_is_available_without_an_installation_or_weather(capsys):
    with pytest.raises(SystemExit) as error:
        validation.main(["--help"])
    assert error.value.code == 0
    assert "--include-orientation90" in capsys.readouterr().out
