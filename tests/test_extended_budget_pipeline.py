# SPDX-License-Identifier: MIT
"""Exercise experiment isolation and launch gates without native simulations."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from replication import extended_budget as workflow


@pytest.fixture
def setup(tmp_path):
    config = workflow.read(workflow.ROOT / "replication/extended-budget.json")
    config_path = tmp_path / "config.json"
    workflow.write(config_path, config)
    config, paths = workflow.load_config(config_path, tmp_path)
    return config, paths, tmp_path


def fake_manifest(config, paths, project):
    dimensions = {1: 4, 2: 4, 3: 4, 4: 13, 5: 13, 6: 13, 8: 11, 9: 13, 10: 13, 13: 10}
    return {
        "manifest_id": "extended",
        "runs": [
            {
                "id": f"{problem}-{version}-{solver}-{repetition}",
                "budget": 100 * (dimensions[problem] + 1) * config["budget_multiplier"],
            }
            for problem in config["problems"]
            for version in config["versions"]
            for solver in config["solvers"]
            for repetition in range(config["repetitions"])
        ],
    }


@pytest.fixture
def planned(setup, monkeypatch):
    monkeypatch.setattr(workflow, "manifest", fake_manifest)
    workflow.plan(*setup)
    return setup


@pytest.fixture
def multi_solver_planned(setup, monkeypatch):
    config, _, _ = setup
    config["solvers"] = ["bobyqa", "pybobyqa"]
    monkeypatch.setattr(workflow, "manifest", fake_manifest)
    workflow.plan(*setup)
    return setup


def test_default_plan_has_400_separate_runs_and_43_million_call_ceiling(planned):
    config, paths, project = planned
    result = workflow.run_stage("plan", config, paths, project)
    assert config["solvers"] == ["bobyqa"]
    assert result["planned_runs"] == 400
    assert result["evaluation_ceiling"] == 43_200_000
    assert (
        len(config["pilot"]["problems"])
        * len(config["versions"])
        * len(config["solvers"])
        * config["pilot"]["repetitions"]
    ) == 48
    assert (paths["source"] / "src/bem_testproblems/replication.py").is_file()
    assert not paths["campaign"].exists()
    original = workflow.read(workflow.ROOT / "replication/continuation.json")
    assert all(
        str(paths[key]) != str(project / original["paths"]["continuation"])
        for key in workflow.PRIVATE
    )


@pytest.mark.parametrize(
    "edit,match",
    [
        (lambda c: c.update(schema_version=2), "configuration"),
        (lambda c: c.update(workers=True), "positive integers"),
        (lambda c: c.update(budget_multiplier=99), "100 times"),
        (lambda c: c.update(problems=[1]), "all ten"),
        (lambda c: c.update(versions=["8.5.0"]), "both engines"),
        (lambda c: c.update(solvers=["bobyqa", "bobyqa"]), "distinct implemented"),
        (lambda c: c.update(solvers=["unknown"]), "distinct implemented"),
        (lambda c: c["pilot"].update(problems=[2, 2]), "distinct pilot"),
        (lambda c: c["paths"].update(extra=".validation-local/extra"), "exactly"),
        (lambda c: c["paths"].update(source="../external"), "inside .validation-local"),
        (lambda c: c["paths"].update(pilot=c["paths"]["source"] + "/pilot"), "separate"),
        (
            lambda c: c["paths"].update(publication="replication/results"),
            "inside replication/results",
        ),
    ],
)
def test_bad_configuration_cannot_launch(setup, edit, match):
    config, _, project = setup
    edit(config)
    path = project / "changed.json"
    workflow.write(path, config)
    with pytest.raises(ValueError, match=match):
        workflow.load_config(path, project)


@pytest.mark.parametrize("stage", workflow.STAGES)
def test_dry_run_never_creates_snapshot_or_launches_process(setup, monkeypatch, stage):
    config, paths, project = setup
    monkeypatch.setattr(workflow, "plan", lambda *a: pytest.fail("planned during dry run"))
    monkeypatch.setattr(workflow, "run_command", lambda *a, **k: pytest.fail("launched"))
    result = workflow.run_stage(stage, config, paths, project, dry_run=True)
    assert result["dry_run"]
    assert not any(path.exists() for path in paths.values())
    assert all(isinstance(argument, str) for command in result["commands"] for argument in command)


def test_full_and_pilot_commands_keep_budgets_and_output_roots_separate(setup):
    config, paths, project = setup
    full = workflow.commands("run", config, paths, project)[0]
    pilot = workflow.commands("pilot", config, paths, project)[0]
    assert full[full.index("--budget-multiplier") + 1] == "100"
    assert "--budget" not in full
    assert pilot[pilot.index("--budget") + 1] == "25"
    assert "--budget-multiplier" not in pilot
    assert full[full.index("--output-root") + 1] == str(paths["campaign"])
    assert pilot[pilot.index("--output-root") + 1] == str(paths["pilot"])
    assert full[full.index("--workers") + 1] == "120"
    assert pilot[pilot.index("--workers") + 1] == "48"
    with pytest.raises(ValueError, match="Unknown stage"):
        workflow.commands("bad", config, paths, project)


def test_manifest_imports_only_frozen_package_and_passes_extended_configuration(setup, monkeypatch):
    config, paths, project = setup
    captured = {}
    package = paths["source"] / "src/bem_testproblems"
    monkeypatch.setattr(workflow.os, "environ", {})
    monkeypatch.setattr(workflow.sys, "path", list(sys.path))
    monkeypatch.delitem(workflow.sys.modules, "bem_testproblems", raising=False)

    def prepare(**kwargs):
        captured.update(kwargs)
        return {"manifest_id": "prepared"}

    runtime = SimpleNamespace(__file__=str(package / "replication.py"), prepare_manifest=prepare)
    monkeypatch.setattr(workflow.importlib, "import_module", lambda name: runtime)
    assert workflow.manifest(config, paths, project) == {"manifest_id": "prepared"}
    assert captured["problems"] == list(workflow.PROBLEMS)
    assert captured["versions"] == list(workflow.VERSIONS)
    assert captured["budget_multiplier"] == 100
    assert "budget" not in captured
    assert captured["diagnostics_policy"] == "strict"
    assert workflow.sys.path[0] == str(paths["source"] / "src")
    assert workflow.os.environ["BEM_REFERENCE_DIR"] == str(
        project / ".reference-cache/beobenchmark"
    )
    runtime.__file__ = str(project / "another-source/replication.py")
    with pytest.raises(ValueError, match="Loaded source differs"):
        workflow.manifest(config, paths, project)
    monkeypatch.setitem(
        workflow.sys.modules,
        "bem_testproblems",
        SimpleNamespace(__file__=str(project / "another-source/__init__.py")),
    )
    with pytest.raises(ValueError, match="fresh interpreter"):
        workflow.manifest(config, paths, project)


def test_plan_rejects_modified_snapshot_and_configuration(planned):
    config, paths, project = planned
    source = paths["source"] / "src/bem_testproblems/replication.py"
    prior = source.read_bytes()
    source.write_bytes(prior + b"\n# changed\n")
    with pytest.raises(ValueError, match="identity changed"):
        workflow.plan(config, paths, project)
    source.write_bytes(prior)
    config["workers"] = 60
    with pytest.raises(ValueError, match="identity changed"):
        workflow.plan(config, paths, project)


def test_unplanned_campaign_and_incomplete_snapshot_are_rejected(setup, monkeypatch):
    config, paths, project = setup
    monkeypatch.setattr(workflow, "manifest", fake_manifest)
    workflow.write(paths["campaign"] / "untracked.json", {})
    with pytest.raises(ValueError, match="without its immutable plan"):
        workflow.plan(config, paths, project)
    (paths["campaign"] / "untracked.json").unlink()
    paths["source"].mkdir(parents=True)
    with pytest.raises(ValueError, match="snapshot is incomplete"):
        workflow.plan(config, paths, project)


def test_snapshot_rejects_symlink_instead_of_copying_external_content(tmp_path, monkeypatch):
    source = tmp_path / "live"
    (source / "src/bem_testproblems").mkdir(parents=True)
    (source / "src/bem_testproblems/replication.py").write_text("# test source\n")
    try:
        (source / "src/link.py").symlink_to(__file__)
    except OSError as error:
        pytest.skip(f"Symlink creation unavailable: {error}")
    monkeypatch.setattr(workflow, "ROOT", source)
    with pytest.raises(ValueError, match="symbolic links"):
        workflow.snapshot_source(tmp_path / "snapshot")
    assert not (tmp_path / "snapshot").exists()


def test_unplanned_source_snapshot_must_match_current_checkout(setup):
    _, paths, _ = setup
    workflow.snapshot_source(paths["source"])
    workflow.snapshot_source(paths["source"])
    source = paths["source"] / "src/bem_testproblems/replication.py"
    source.write_text(source.read_text() + "\n# changed\n")
    with pytest.raises(ValueError, match="Unplanned source snapshot differs"):
        workflow.snapshot_source(paths["source"])


def install_fake_process(
    monkeypatch,
    setup,
    *,
    preflight_passed=True,
    pilot_complete=True,
    successful_versions=("8.5.0", "26.2.0"),
    successful_solvers=("bobyqa", "pybobyqa"),
    full_complete=True,
):
    config, paths, _ = setup
    calls = []

    def fake(command, project, source, *, capture=False, log=None):
        calls.append(command)
        name = Path(command[1]).name
        if name == "validate_cases.py":
            report = Path(command[command.index("--output") + 1])
            workflow.write(report, {"passed": preflight_passed})
        elif name == "run_replication.py" and "--budget" in command:
            workflow.write(paths["pilot"] / "manifest.json", {"id": "pilot"})
            workflow.write(paths["pilot"] / "summary.json", {"evaluations": 50})
            for version in config["versions"]:
                for solver in config["solvers"]:
                    workflow.write(
                        paths["pilot"] / "runs" / f"{version}-{solver}.json",
                        {
                            "version": version,
                            "solver": solver,
                            "status": "budget_exhausted" if solver in successful_solvers else "skipped",
                            "strict_benchmark_evaluation": version in successful_versions,
                        },
                    )
        elif name == "review_replication.py" and capture:
            if command[command.index("--origin") + 1] == str(paths["pilot"]):
                planned = (
                    len(config["pilot"]["problems"])
                    * len(config["solvers"])
                    * len(config["versions"])
                    * config["pilot"]["repetitions"]
                )
                return {"planned": planned, "terminal": planned if pilot_complete else planned - 1}
            planned = len(fake_manifest(config, paths, project)["runs"])
            return {"planned": planned, "terminal": planned if full_complete else planned - 1}
        elif name == "run_replication.py":
            workflow.write(
                paths["campaign"] / "manifest.json", fake_manifest(config, paths, project)
            )

    monkeypatch.setattr(workflow, "run_command", fake)
    return calls


def test_preflight_and_complete_separate_pilot_gate_full_launch(planned, monkeypatch):
    config, paths, project = planned
    calls = install_fake_process(monkeypatch, planned)
    with pytest.raises(ValueError, match="preflight stage"):
        workflow.run_stage("run", config, paths, project)
    workflow.run_stage("preflight", config, paths, project)
    with pytest.raises(ValueError, match="pilot stage"):
        workflow.run_stage("run", config, paths, project)
    workflow.run_stage("pilot", config, paths, project)
    workflow.run_stage("run", config, paths, project)
    assert "--budget-multiplier" in calls[-2]
    assert "--output-root" in calls[-2]
    evidence = paths["pilot"] / "summary.json"
    workflow.write(evidence, {"evaluations": "changed"})
    with pytest.raises(ValueError, match="evidence changed"):
        workflow.run_stage("run", config, paths, project)


def test_run_rejects_mismatched_existing_campaign_and_incomplete_completion(planned, monkeypatch):
    config, paths, project = planned
    install_fake_process(monkeypatch, planned, full_complete=False)
    workflow.run_stage("preflight", config, paths, project)
    workflow.run_stage("pilot", config, paths, project)
    workflow.write(paths["campaign"] / "manifest.json", {"manifest_id": "different"})
    with pytest.raises(ValueError, match="Existing campaign differs"):
        workflow.run_stage("run", config, paths, project)
    (paths["campaign"] / "manifest.json").unlink()
    with pytest.raises(ValueError, match="campaign is interrupted"):
        workflow.run_stage("run", config, paths, project)


def test_failed_preflight_invalidates_receipt_and_preserves_previous_attempt(planned, monkeypatch):
    config, paths, project = planned
    install_fake_process(monkeypatch, planned)
    workflow.run_stage("preflight", config, paths, project)
    first = paths["preflight"] / "attempt-0001/8.5.0.json"
    prior = first.read_bytes()
    install_fake_process(monkeypatch, planned, preflight_passed=False)
    with pytest.raises(ValueError, match="did not pass"):
        workflow.run_stage("preflight", config, paths, project)
    assert first.read_bytes() == prior
    assert (paths["preflight"] / "attempt-0002/8.5.0.json").is_file()
    assert not (paths["preflight"] / "receipt.json").exists()


@pytest.mark.parametrize(
    "options,match",
    [
        ({"pilot_complete": False}, "pilot is incomplete"),
        ({"successful_versions": ("8.5.0",)}, "26.2.0"),
        ({"successful_solvers": ("bobyqa",)}, "pybobyqa"),
    ],
)
def test_incomplete_or_entirely_failed_engine_pilot_cannot_authorize_run(
    multi_solver_planned, monkeypatch, options, match
):
    config, paths, project = multi_solver_planned
    install_fake_process(monkeypatch, multi_solver_planned, **options)
    workflow.run_stage("preflight", config, paths, project)
    with pytest.raises(ValueError, match=match):
        workflow.run_stage("pilot", config, paths, project)
    assert not (paths["pilot"] / "receipt.json").exists()


@pytest.mark.parametrize("escape", ["../outside.json", "/absolute.json", "link.json"])
def test_receipt_rejects_escaping_evidence(tmp_path, escape):
    directory = tmp_path / "preflight"
    directory.mkdir()
    outside = tmp_path / "outside.json"
    workflow.write(outside, {})
    if escape == "link.json":
        try:
            (directory / "link.json").symlink_to(outside)
        except OSError as error:
            pytest.skip(f"Symlink creation unavailable: {error}")
    binding = {"manifest": "fixed"}
    path = directory / "receipt.json"
    workflow.write(
        path,
        {"plan_sha256": workflow.digest(binding), "files": {escape: workflow.file_digest(outside)}},
    )
    with pytest.raises(ValueError, match="evidence changed"):
        workflow.require_receipt(path, binding)


def test_fresh_subprocess_and_controller_log_use_one_numeric_thread(setup, monkeypatch):
    _, paths, project = setup
    seen = []

    def fake(command, **kwargs):
        seen.append(kwargs)
        if "stdout" in kwargs:
            kwargs["stdout"].write("controller output\n")
        return SimpleNamespace(stdout='{"ok":true}')

    monkeypatch.setattr(workflow.subprocess, "run", fake)
    assert workflow.run_command(
        [sys.executable, "fake.py"], project, paths["source"], capture=True
    ) == {"ok": True}
    log = paths["campaign"] / "controller.log"
    workflow.run_command([sys.executable, "fake.py"], project, paths["source"], log=log)
    assert log.read_text() == "controller output\n"
    assert seen[0]["check"] is True
    assert "shell" not in seen[0]
    assert all(seen[0]["env"][name] == "1" for name in workflow.THREADS)
    assert seen[0]["env"]["PYTHONPATH"] == str(paths["source"] / "src")
    assert seen[1]["stderr"] == subprocess.STDOUT


def test_status_is_read_only_before_launch_and_main_defaults_to_it(setup, monkeypatch):
    config, paths, project = setup
    monkeypatch.setattr(workflow, "run_command", lambda *a, **k: pytest.fail("launched"))
    result = workflow.run_stage("status", config, paths, project)
    assert result == {"stage": "status", "started": False, "plan_exists": False}
    path = project / "config.json"
    assert workflow.main(["--config", str(path), "--project-root", str(project)]) == result
    assert not paths["source"].exists()
