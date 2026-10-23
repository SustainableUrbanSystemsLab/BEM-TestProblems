# SPDX-License-Identifier: MIT
"""Pipeline commands, native gates, and public-only CI checks without simulations."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from replication import pipeline


@pytest.fixture
def setup(tmp_path):
    config = json.loads((pipeline.ROOT / "replication/continuation.json").read_text())
    manifest = {
        "manifest_id": "origin",
        "master_seed": 2019,
        "engines": {"8.5.0": {}, "26.2.0": {}},
        "solvers": {"direct": {}, "bobyqa": {}},
    }
    origin = tmp_path / config["paths"]["origin"]
    origin.mkdir(parents=True)
    (origin / "manifest.json").write_text(json.dumps(manifest))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return tmp_path, path, config, manifest


def loaded(setup):
    project, path, _, _ = setup
    config, paths, manifest = pipeline.load_config(path, project)
    return config, paths, manifest, project


def test_config_keeps_inputs_and_outputs_in_separate_project_folders(setup):
    config, paths, manifest, project = loaded(setup)
    assert config["workers"] == 118
    assert paths["origin"] == project / ".validation-local/handoff/origin"
    assert list(manifest["engines"]) == ["8.5.0", "26.2.0"]


@pytest.mark.parametrize(
    "edit,match",
    [
        (lambda c: c.update(schema_version=2), "configuration"),
        (lambda c: c.update(workers=True), "positive integers"),
        (lambda c: c["pilot"].update(budget=0), "positive integers"),
        (lambda c: c["paths"].update(extra=".validation-local/extra"), "exactly"),
        (lambda c: c["paths"].update(review="../outside"), "inside .validation-local"),
        (lambda c: c["paths"].update(review=c["paths"]["origin"] + "/review"), "separate"),
        (lambda c: c["paths"].update(publication="src/reports"), "replication/results"),
    ],
)
def test_invalid_config_is_rejected_before_processes(setup, edit, match):
    project, path, config, _ = setup
    edit(config)
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match=match):
        pipeline.load_config(path, project)


def test_origin_engine_version_cannot_escape_paths(setup):
    project, path, config, manifest = setup
    manifest["engines"] = {"../../escape": {}}
    (project / config["paths"]["origin"] / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="engine version"):
        pipeline.load_config(path, project)


@pytest.mark.parametrize("stage", [s for s in pipeline.STAGES if s != "check-export"])
def test_dry_run_starts_no_process_and_builds_real_argument_lists(setup, monkeypatch, stage):
    monkeypatch.setattr(pipeline, "run_command", lambda *a, **k: pytest.fail("process launched"))
    result = pipeline.run_stage(stage, *loaded(setup), dry_run=True)
    assert result["dry_run"] is True
    assert result["commands"]
    assert all(isinstance(arg, str) for command in result["commands"] for arg in command)
    if stage == "run":
        assert "--run" in result["commands"][0]
    if stage == "replay-plan":
        assert "--plan-only" in result["commands"][0]
    if stage == "export-preview":
        assert "--partial-preview" in result["commands"][0]


def test_pilot_derives_solvers_and_versions_from_origin_and_is_separate(setup):
    config, paths, manifest, project = loaded(setup)
    command = pipeline.commands("pilot", config, paths, manifest, project)[0]
    assert command[command.index("--solvers") + 1 : command.index("--versions")] == [
        "direct",
        "bobyqa",
    ]
    assert command[command.index("--output-root") + 1] == str(paths["pilot"])
    assert paths["pilot"] != paths["continuation"]
    with pytest.raises(ValueError, match="Unknown stage"):
        pipeline.commands("bad", config, paths, manifest, project)


def test_joined_commands_use_continuation_only_once_manifest_exists(setup):
    config, paths, manifest, project = loaded(setup)
    assert "--continuation" not in pipeline.commands("status", config, paths, manifest, project)[0]
    paths["continuation"].mkdir(parents=True)
    (paths["continuation"] / "manifest.json").write_text("{}")
    assert "--continuation" in pipeline.commands("status", config, paths, manifest, project)[0]


def test_native_pilot_receives_the_pinned_solver_configuration(setup):
    config, paths, manifest, project = loaded(setup)
    manifest["native_solvers"] = {"config_path": "private-native.json"}
    command = pipeline.commands("pilot", config, paths, manifest, project)[0]
    assert command[command.index("--native-solvers") + 1] == "private-native.json"


def test_repaired_pilot_uses_the_same_numerical_profile_and_strict_diagnostics(setup):
    config, paths, manifest, project = loaded(setup)
    manifest.update(numerical_variant="convergence-repaired", diagnostics_policy="strict")
    command = pipeline.commands("pilot", config, paths, manifest, project)[0]
    assert command[command.index("--numerical-variant") + 1] == "convergence-repaired"
    assert command[command.index("--diagnostics-policy") + 1] == "strict"


@pytest.mark.parametrize("mismatch", [None, "selection", "status_counts"])
def test_reference_warmup_automates_separate_labelled_reviews(setup, monkeypatch, mismatch):
    config, paths, manifest, project = loaded(setup)
    manifest["diagnostics_policy"] = "reference-warmup"
    for stage in ("run", "review"):
        reviews = [c for c in pipeline.commands(stage, config, paths, manifest, project)
                   if Path(c[1]).name == "review_replication.py"]
        assert len(reviews) == 2
        assert "--include-diagnostic-runs" not in reviews[0]
        assert "--include-diagnostic-runs" in reviews[1]

    def execute(command, *, capture=False):
        diagnostic = "--include-diagnostic-runs" in command
        if not capture:
            return
        output_paths = dict(paths, review=paths["review"] / "diagnostic") if diagnostic else paths
        review = review_fixture(output_paths)
        if diagnostic:
            report_path = Path(review["json"])
            report = json.loads(report_path.read_text())
            report["selection"] = "diagnostic-completed-trajectories"
            if mismatch == "selection":
                report["selection"] = "strict-completed-trajectories"
            elif mismatch == "status_counts":
                report["status_counts"] = {"failed": 3}
            report_path.write_text(json.dumps(report))
        return review

    monkeypatch.setattr(pipeline, "run_command", execute)
    selected = pipeline.commands("run", config, paths, manifest, project)
    if mismatch:
        with pytest.raises(ValueError, match="Diagnostic review"):
            pipeline.run_campaign(selected, paths, manifest, {"manifest_id": "target", "remaining_runs": 3})
        assert not json.loads((paths["review"] / "run-completion.json").read_text())["completed"]
    else:
        result = pipeline.run_campaign(selected, paths, manifest, {"manifest_id": "target", "remaining_runs": 3})
        assert result["completed"]
        assert result["diagnostic_review"]["json"] in result["artifacts_sha256"]


def native_fixture(monkeypatch, paths, *, passed=True):
    calls = []

    def fake(command, *, capture=False):
        calls.append(command)
        if Path(command[1]).name == "review_replication.py":
            return review_fixture(paths)
        if capture:
            return {"manifest_id": "target", "remaining_runs": 3}
        if "validate_cases.py" in Path(command[1]).name:
            report = Path(command[command.index("--output") + 1])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"passed": passed}))

    monkeypatch.setattr(pipeline, "run_command", fake)
    return calls


def review_fixture(paths, *, statuses=None, partial=False):
    output = paths["review"]
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "origin_manifest_id": "origin",
        "source_manifests": {"origin": {}, "target": {}},
        "selection": "strict-completed-trajectories",
        "requested_runs": 3,
        "status_counts": statuses or {"completed": 3},
        "partial": partial,
    }
    json_path = output / "review-strict.json"
    json_path.write_text(json.dumps(report))
    md_path = output / "review-strict.md"
    md_path.write_text("Reviewed tables")
    summary = output / "boxplot-summary.json"
    summary.write_text("{}")
    plot = output / "figure8.png"
    plot.write_bytes(b"plot fixture")
    return {"json": str(json_path), "markdown": str(md_path),
            "figures": {"plots": [str(plot)], "summary": str(summary)}}


def test_preflight_creates_gate_and_run_rejects_changed_evidence(setup, monkeypatch):
    config, paths, manifest, project = loaded(setup)
    calls = native_fixture(monkeypatch, paths)
    pipeline.run_stage("preflight", config, paths, manifest, project)
    receipt = paths["preflight"] / "preflight-receipt.json"
    assert json.loads(receipt.read_text())["identity"]["destination_manifest_id"] == "target"
    result = pipeline.run_stage("run", config, paths, manifest, project)
    assert "--run" in calls[-2]
    assert Path(calls[-1][1]).name == "review_replication.py"
    assert result["completed"] and result["exit_code"] == 0
    assert result["artifacts_sha256"][str(paths["review"] / "figure8.png")]
    (paths["preflight"] / "attempt-0001/8.5.0.json").write_text('{"passed": false}')
    with pytest.raises(ValueError, match="evidence changed"):
        pipeline.run_stage("run", config, paths, manifest, project)


@pytest.mark.parametrize(
    "statuses,partial,expected_status",
    [
        ({"completed": 2, "failed": 1}, False, "finished-with-failures"),
        ({"completed": 2, "skipped": 1}, False, "finished-with-failures"),
        ({"completed": 1, "pending": 1, "interrupted": 1}, True, "interrupted"),
    ],
)
def test_nonzero_controller_still_generates_review_and_preserves_failures(
    setup, monkeypatch, statuses, partial, expected_status
):
    config, paths, manifest, project = loaded(setup)
    native_fixture(monkeypatch, paths)
    pipeline.run_stage("preflight", config, paths, manifest, project)
    calls = []

    def execute(command, *, capture=False):
        calls.append(command)
        if "--plan-only" in command:
            return {"manifest_id": "target", "remaining_runs": 3}
        if "--run" in command:
            raise subprocess.CalledProcessError(1, command)
        assert capture and Path(command[1]).name == "review_replication.py"
        return review_fixture(paths, statuses=statuses, partial=partial)

    monkeypatch.setattr(pipeline, "run_command", execute)
    result = pipeline.run_stage("run", config, paths, manifest, project)
    assert result["completed"] is (not partial)
    assert result["campaign_status"] == expected_status
    assert result["exit_code"] == result["controller_exit_code"] == 1
    assert result["status_counts"] == statuses
    assert len(calls) == 3
    assert json.loads(Path(result["completion_record"]).read_text()) == result


def test_finished_campaign_only_refreshes_reports_without_launching_controller(setup, monkeypatch):
    config, paths, manifest, project = loaded(setup)
    native_fixture(monkeypatch, paths)
    pipeline.run_stage("preflight", config, paths, manifest, project)
    calls = []

    def execute(command, *, capture=False):
        calls.append(command)
        assert "--run" not in command
        if "--plan-only" in command:
            return {"manifest_id": "target", "remaining_runs": 0}
        return review_fixture(paths, statuses={"completed": 2, "failed": 1})

    monkeypatch.setattr(pipeline, "run_command", execute)
    result = pipeline.run_stage("run", config, paths, manifest, project)
    assert result["completed"] and result["exit_code"] == 1
    assert result["controller_exit_code"] is None
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["review", "controller", "wrong-manifest", "missing-plot"])
def test_reporting_and_controller_errors_cannot_leave_a_success_record(setup, monkeypatch, failure):
    config, paths, manifest, project = loaded(setup)
    native_fixture(monkeypatch, paths)
    pipeline.run_stage("preflight", config, paths, manifest, project)
    # An earlier successful receipt must not survive a failed refresh as current evidence.
    receipt = paths["review"] / "run-completion.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text('{"completed": true}')

    def execute(command, *, capture=False):
        if "--plan-only" in command:
            return {"manifest_id": "target", "remaining_runs": 3}
        if "--run" in command:
            if failure == "controller":
                raise subprocess.CalledProcessError(2, command)
            return
        if failure == "review":
            raise subprocess.CalledProcessError(1, command)
        review = review_fixture(paths)
        if failure == "wrong-manifest":
            report = json.loads(Path(review["json"]).read_text())
            report["origin_manifest_id"] = "different"
            Path(review["json"]).write_text(json.dumps(report))
        elif failure == "missing-plot":
            Path(review["figures"]["plots"][0]).unlink()
        return review

    monkeypatch.setattr(pipeline, "run_command", execute)
    with pytest.raises((subprocess.CalledProcessError, ValueError, FileNotFoundError)):
        pipeline.run_stage("run", config, paths, manifest, project)
    result = json.loads(receipt.read_text())
    assert not result["completed"]
    assert result["phase"] == "failed" and result["error"]


def test_run_requires_preflight_and_current_destination_identity(setup, monkeypatch):
    config, paths, manifest, project = loaded(setup)
    native_fixture(monkeypatch, paths)
    with pytest.raises(ValueError, match="preflight before"):
        pipeline.run_stage("run", config, paths, manifest, project)
    pipeline.run_stage("preflight", config, paths, manifest, project)
    monkeypatch.setattr(pipeline, "run_command", lambda *a, **k: {"manifest_id": "changed"})
    with pytest.raises(ValueError, match="evidence changed"):
        pipeline.run_stage("run", config, paths, manifest, project)


def test_failed_preflight_cannot_leave_a_pass_receipt(setup, monkeypatch):
    config, paths, manifest, project = loaded(setup)
    native_fixture(monkeypatch, paths)
    pipeline.run_stage("preflight", config, paths, manifest, project)
    native_fixture(monkeypatch, paths, passed=False)
    with pytest.raises(ValueError, match="did not pass"):
        pipeline.run_stage("preflight", config, paths, manifest, project)
    assert not (paths["preflight"] / "preflight-receipt.json").exists()


def test_preflight_retry_uses_new_case_folders_and_preserves_prior_reports(setup, monkeypatch):
    config, paths, manifest, project = loaded(setup)
    calls = native_fixture(monkeypatch, paths)
    pipeline.run_stage("preflight", config, paths, manifest, project)
    first = (paths["preflight"] / "attempt-0001/8.5.0.json").read_bytes()
    pipeline.run_stage("preflight", config, paths, manifest, project)
    assert (paths["preflight"] / "attempt-0001/8.5.0.json").read_bytes() == first
    receipt = json.loads((paths["preflight"] / "preflight-receipt.json").read_text())
    assert receipt["attempt"] == "attempt-0002"
    assert set(receipt["reports"]) == {"attempt-0002/8.5.0.json", "attempt-0002/26.2.0.json"}
    native = [c for c in calls if Path(c[1]).name == "validate_cases.py"]
    assert len({c[c.index("--work-dir") + 1] for c in native}) == 4


def test_process_execution_uses_current_interpreter_no_shell_and_isolated_environment(monkeypatch):
    seen = {}

    def fake(command, **kwargs):
        seen.update(kwargs)
        assert command == [sys.executable, "script.py"]
        return SimpleNamespace(stdout='{"ok":true}')

    monkeypatch.setattr(pipeline.subprocess, "run", fake)
    assert pipeline.run_command([sys.executable, "script.py"], capture=True) == {"ok": True}
    assert seen["check"] and seen["capture_output"]
    assert "shell" not in seen
    assert seen["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert seen["env"]["OPENBLAS_NUM_THREADS"] == "1"
    assert seen["env"]["PYTHONPATH"] == str(pipeline.ROOT / "src")


def test_captured_errors_remain_visible(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="missing engine")

    monkeypatch.setattr(pipeline.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        pipeline.run_command(["fake"], capture=True)
    assert "missing engine" in capsys.readouterr().err


def test_public_ci_checks_need_no_private_handoff(setup, monkeypatch):
    project = setup[0]
    public = project / "replication/results"
    public.mkdir(parents=True)
    (public / "README.md").write_text("Public results")
    (public / "campaign").mkdir()
    calls = []
    monkeypatch.setattr(pipeline, "run_command", lambda command: calls.append(command))
    result = pipeline.main(["check-export", "--project-root", str(project)])
    assert result["packages"] == 1
    assert calls[0][-2:] == ["--verify-export", str(public / "campaign")]
    calls.clear()
    pipeline.check_exports(project, dry_run=True)
    assert not calls
    (public / "accidental.epw").write_text("private weather")
    with pytest.raises(ValueError, match="Unexpected publication"):
        pipeline.check_exports(project)


def test_default_stage_is_read_only_status_and_cli_dry_run_is_honored(setup, monkeypatch):
    project, config, _, _ = setup
    seen = []
    monkeypatch.setattr(pipeline, "run_command", lambda command: seen.append(command))
    pipeline.main(["--config", str(config), "--project-root", str(project)])
    assert "--status-only" in seen[0]
    seen.clear()
    pipeline.main(["run", "--dry-run", "--config", str(config), "--project-root", str(project)])
    assert not seen
