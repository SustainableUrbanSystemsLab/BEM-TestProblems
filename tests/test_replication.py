# SPDX-License-Identifier: MIT
"""Experiment fairness, strict failures, durable budgets and deterministic resumption."""

import copy
import json
import tempfile
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest

from bem_testproblems import get_problem, replication, replication_diagnostics
from bem_testproblems.energyplus import EnergyPlusError, RunResult, sha256_file


@pytest.fixture
def local_setup(tmp_path, monkeypatch):
    engines = {}
    for version in ("8.5.0", "26.2.0"):
        path = tmp_path / version / "fake-engine"
        path.parent.mkdir()
        path.write_text(version)
        engines[version] = path

    class FakeNativeRunner:
        def __init__(self, executable, *, expected_version, output_root=None, cache=True):
            assert cache is False
            self.executable = Path(executable)
            self.executable_sha256 = sha256_file(executable)
            self.version = expected_version
            self.version_output = "EnergyPlus, Version " + expected_version
            self.output_root = Path(output_root) if output_root is not None else None

        def run(self, input_file, weather_file=None, *, design_day=False):
            self.output_root.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(dir=self.output_root))
            (directory / "input.idf").write_bytes(Path(input_file).read_bytes())
            (directory / "eplusout.err").write_text(
                "EnergyPlus Completed Successfully-- 2 Warning; 0 Severe Errors")
            (directory / "eplusout.end").write_text("EnergyPlus Completed Successfully")
            (directory / "run.json").write_text('{"status":"success"}')
            (directory / "large-output.eso").write_bytes(b"Large output fixture" * 100)
            return RunResult(directory=directory, version=self.version,
                             input_sha256=sha256_file(input_file), elapsed=0.001)

    metadata = {item["name"]: item for item in replication.solver_metadata()}
    monkeypatch.setattr(replication, "solver_metadata", lambda name=None: copy.deepcopy(
        list(metadata.values()) if name is None else metadata[name.lower()]))
    monkeypatch.setattr(replication, "EnergyPlusRunner", FakeNativeRunner)
    monkeypatch.setattr(replication, "_model_identity", lambda problem, version: {
        "template_sha256": f"fixture-p{problem.id}-{version}"})
    monkeypatch.setattr(replication, "_weather_identity", lambda problem, directory: {
        "filename": None if problem.design_day else problem.weather_filename,
        "sha256": None if problem.design_day else "canonical-fixture"})
    monkeypatch.setattr(replication, "_dependency_identity", lambda name: {
        "available": True, "runtime_version": "test-fixture"})
    calls = []

    def bind(problem, *, runner, weather_dir):
        def objective(x):
            calls.append(tuple(x))
            return sum(x)
        return objective

    monkeypatch.setattr(replication, "make_objective", bind)
    configuration = {"problems": [13], "solvers": ["bobyqa"], "versions": ["26.2.0"],
                     "repetitions": 1, "budget": 3, "seed": 19,
                     "project_root": tmp_path, "executables": engines}
    return configuration, calls


def test_paper_budget_paired_uniform_starts_and_balanced_schedule(local_setup):
    configuration, _ = local_setup
    configuration.update(problems=[1, 13], versions=["8.5.0", "26.2.0"],
                         solvers=["bobyqa", "direct"], repetitions=20, budget=None)
    manifest = replication.prepare_manifest(**configuration)
    assert manifest["protocol"] == "paper-start-and-budget-protocol"
    assert len(manifest["runs"]) == 20 * 2 * 2 * 2
    # Each first-repetition problem is scheduled before any second repetition.
    assert all(run["repetition"] == 0 for run in manifest["runs"][:8])
    assert manifest["runs"][8]["repetition"] == 1
    for number in (1, 13):
        problem = get_problem(number)
        paired = [run for run in manifest["runs"] if run["problem"] == number
                  and run["repetition"] == 0]
        random = [run for run in paired if run["solver"] == "bobyqa"]
        assert random[0]["x0"] == random[1]["x0"]
        assert random[0]["seed"] == random[1]["seed"]
        assert random[0]["x0"] != list(problem.midpoint)
        assert problem.validate(random[0]["x0"])
        assert all(run["x0"] == list(problem.midpoint) for run in paired
                   if run["solver"] == "direct")
        assert all(run["budget"] == 100 * (problem.dimension + 1) for run in paired)
    assert "pso" in manifest["omitted_solvers"]
    assert manifest["manifest_id"] == replication.prepare_manifest(**configuration)["manifest_id"]


def test_solver_alias_is_canonical_before_direct_initialization(local_setup):
    configuration, _ = local_setup
    manifest = replication.prepare_manifest(**{**configuration, "solvers": ["DIRECT"]})
    assert manifest["runs"][0]["solver"] == "direct"
    assert manifest["runs"][0]["x0"] == list(get_problem(13).midpoint)


def test_problem_first_schedule_changes_only_execution_order(local_setup):
    configuration, _ = local_setup
    configuration.update(problems=[1, 13], versions=["8.5.0", "26.2.0"],
                         solvers=["direct", "bobyqa"], repetitions=2)
    balanced = replication.prepare_manifest(**configuration)
    problem_first = replication.prepare_manifest(**configuration, schedule="problem-first")
    assert balanced["schedule"] == "balanced"
    assert problem_first["schedule"] == "problem-first"
    assert {run["id"]: run for run in balanced["runs"]} == {
        run["id"]: run for run in problem_first["runs"]}
    assert [run["problem"] for run in problem_first["runs"]] == [1] * 8 + [13] * 8
    assert [run["repetition"] for run in problem_first["runs"][:8]] == [0] * 4 + [1] * 4
    assert balanced["runs"] != problem_first["runs"]


def test_hard_budget_retains_independently_observed_best_and_trace(local_setup, tmp_path, monkeypatch):
    configuration, calls = local_setup

    def greedy(solver, objective, start, bounds, budget, seed):
        for _ in range(budget + 10):
            objective(start)
        pytest.fail("The callback must stop before budget+1 is evaluated")

    monkeypatch.setattr(replication, "solve_solver", greedy)
    root = tmp_path / "experiment"
    summary = replication.run_replication(output_root=root, workers=1, **configuration)
    record = json.loads(next((root / "runs").glob("*.json")).read_text())
    assert record["status"] == "budget_exhausted"
    assert record["evaluation_count"] == len(calls) == len(record["trace"]) == 3
    assert record["best_f"] == sum(record["x0"])
    assert record["best_x"] == record["x0"]
    assert all(row["f"] == record["best_f"] for row in record["trace"])
    assert summary["protocol"] == "pilot-overrides"
    assert summary["statuses"]["budget_exhausted"] == 1


def test_severe_failure_keeps_best_valid_point_and_is_never_a_penalty(local_setup, tmp_path, monkeypatch):
    configuration, _ = local_setup
    failed_directory = tmp_path / "failed-simulation"
    failed_directory.mkdir()
    (failed_directory / "eplusout.err").write_text(
        '** Severe ** CheckWarmupConvergence: Zone="TEST" did not converge\n'
        '** ~~~ ** ..Max Temp Comparison = 0.01 vs Temperature Convergence Tolerance=0.004\n')
    error = EnergyPlusError("Warmup did not converge", directory=failed_directory, reason="simulation")
    attempted = []

    def bind(problem, **kwargs):
        def evaluate(x):
            attempted.append(tuple(x))
            if len(attempted) == 2:
                raise error
            return 17.0
        return evaluate

    def solver(name, objective, start, bounds, budget, seed):
        objective(start)
        objective(start)
        pytest.fail("A strict simulator failure must leave the solver")

    monkeypatch.setattr(replication, "make_objective", bind)
    monkeypatch.setattr(replication, "solve_solver", solver)
    manifest = replication.prepare_manifest(**configuration)
    record = replication._run_one(manifest["runs"][0], manifest, tmp_path / "experiment", "none")
    assert record["status"] == "failed"
    assert record["best_f"] == 17
    assert record["evaluation_count"] == 2
    assert record["trace"][-1]["f"] is None
    assert record["error"]["severe_count"] == 1
    assert record["error"]["fatal_count"] == 0
    assert record["error"]["reason"] == "simulation"
    assert (failed_directory / "eplusout.err").is_file()


def test_resume_skips_terminal_runs_and_restarts_interrupted_attempts(local_setup, tmp_path, monkeypatch):
    configuration, calls = local_setup

    def solver(name, objective, start, bounds, budget, seed):
        return {"status": "terminated", "fun": objective(start), "message": "test stop"}

    monkeypatch.setattr(replication, "solve_solver", solver)
    root = tmp_path / "experiment"
    replication.run_replication(output_root=root, workers=1, **configuration)
    checkpoint = next((root / "runs").glob("*.json"))
    original = json.loads(checkpoint.read_text())
    replication.run_replication(output_root=root, workers=1, **configuration)
    assert len(calls) == 1
    assert json.loads(checkpoint.read_text()) == original
    interrupted = {**original, "status": "running"}
    checkpoint.write_text(json.dumps(interrupted))
    replication.run_replication(output_root=root, workers=1, **configuration)
    restarted = json.loads(checkpoint.read_text())
    assert restarted["attempt"] == 2
    assert restarted["x0"] == original["x0"]
    assert restarted["seed"] == original["seed"]
    assert calls == [tuple(original["x0"])] * 2
    assert json.loads(next((root / "history").glob("*.json")).read_text()) == interrupted


def test_resume_rejects_changed_budget_or_diagnostic_policy(local_setup, tmp_path, monkeypatch):
    configuration, _ = local_setup
    monkeypatch.setattr(replication, "solve_solver", lambda name, objective, start, *args: {
        "status": "terminated", "fun": objective(start)})
    root = tmp_path / "experiment"
    replication.run_replication(output_root=root, workers=1, **configuration)
    before = (root / "manifest.json").read_bytes()
    for changed in ({**configuration, "budget": 4},
                    {**configuration, "diagnostics_policy": "reference-warmup"}):
        with pytest.raises(ValueError, match="manifest differs"):
            replication.run_replication(output_root=root, workers=1, **changed)
    assert (root / "manifest.json").read_bytes() == before


def test_engine_mutation_after_manifest_fails_before_any_evaluation(local_setup, tmp_path):
    configuration, calls = local_setup
    manifest = replication.prepare_manifest(**configuration)
    configuration["executables"]["26.2.0"].write_text("Replaced executable")
    record = replication._run_one(manifest["runs"][0], manifest, tmp_path / "experiment", "none")
    assert record["status"] == "failed"
    assert "Engine executable changed" in record["error"]["message"]
    assert record["evaluation_count"] == 0
    assert calls == []


@pytest.mark.parametrize("termination,native,expected_status", [
    ("roundoff", -4, "completed"),
    ("unexpected-error", -7, "failed"),
    ("terminated", -2, "failed"),
])
def test_native_solver_termination_preserves_observed_incumbent_and_explicit_status(
    local_setup, tmp_path, monkeypatch, termination, native, expected_status
):
    configuration, _ = local_setup

    def limited(name, objective, start, *args):
        value = objective(start)
        return {"status": termination, "success": False, "native_status": native,
                "fun": value, "message": "Native termination diagnostic"}

    monkeypatch.setattr(replication, "solve_solver", limited)
    manifest = replication.prepare_manifest(**configuration)
    record = replication._run_one(manifest["runs"][0], manifest, tmp_path / "experiment", "none")
    assert record["status"] == expected_status
    assert record["solver_termination"] == termination
    assert record["solver_success"] is False
    assert record["optimizer_termination_warning"] == (expected_status == "completed")
    assert record["best_f"] == sum(record["x0"])
    assert record["solver_result"]["native_status"] == native


def test_success_outputs_are_deleted_only_after_durable_value_and_hash_checkpoint(
    local_setup, tmp_path, monkeypatch
):
    configuration, _ = local_setup
    model = tmp_path / "model.idf"
    model.write_text("Synthetic unit-test model")

    def bind(problem, *, runner, weather_dir):
        def evaluate(x):
            runner.run(model, design_day=True)
            return 12.0
        return evaluate

    def solver(name, objective, start, *args):
        return {"status": "terminated", "fun": objective(start)}

    original_cleanup = replication._compact_success

    def inspected_cleanup(result, attempt_root, policy):
        checkpoint = next((tmp_path / "experiment" / "runs").glob("*.json"))
        saved = json.loads(checkpoint.read_text())
        assert saved["best_f"] == 12
        assert saved["trace"][0]["diagnostic_sha256"]["run.json"]
        assert saved["trace"][0]["input_sha256"] == sha256_file(model)
        assert saved["trace"][0]["components"] == {"Q": 3, "P": 1}
        return original_cleanup(result, attempt_root, policy)

    monkeypatch.setattr(replication, "make_objective", bind)
    monkeypatch.setattr(replication, "solve_solver", solver)
    monkeypatch.setattr(replication, "extract_outputs", lambda family, result: {"Q": 3, "P": 1})
    monkeypatch.setattr(replication, "_compact_success", inspected_cleanup)
    manifest = replication.prepare_manifest(**configuration)
    record = replication._run_one(manifest["runs"][0], manifest, tmp_path / "experiment", "none")
    assert record["status"] == "completed"
    assert record["trace"][0]["diagnostics"]["warning_count"] == 2
    assert not Path(record["trace"][0]["simulation_directory"]).exists()


def test_live_coordinator_lock_prevents_duplicate_experiment_work(tmp_path):
    with replication._experiment_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already holds"):
            with replication._experiment_lock(tmp_path):
                pytest.fail("Two coordinators must not own the same output root")
    assert not (tmp_path / "experiment.lock").exists()


def test_reference_policy_records_recovered_severes_and_retains_compact_diagnostics(
    local_setup, tmp_path, monkeypatch
):
    configuration, _ = local_setup
    model = tmp_path / "model.idf"
    model.write_text("Unit-test model")

    class RecoveredRunner:
        def __init__(self, native, *, family):
            self.native = native
            self.version = native.version
            self.last_diagnostics = None

        def run(self, input_file, weather_file=None, *, design_day=False):
            result = self.native.run(input_file, weather_file, design_day=design_day)
            (result.directory / "eplusout.err").write_text(
                "** Severe ** CheckWarmupConvergence: Zone=TEST did not converge\n")
            self.last_diagnostics = {"accepted_warmup_only": True,
                "strict_benchmark_evaluation": False, "warning_count": 2,
                "severe_count": 1, "fatal_count": 0,
                "warmup_eio_rows": [{"maximum_temperature_difference_c": 0.01}]}
            return result

    def bind(problem, *, runner, weather_dir):
        def evaluate(x):
            runner.run(model, design_day=True)
            return 18.0
        return evaluate

    monkeypatch.setattr(replication_diagnostics, "ReferenceWarmupRunner", RecoveredRunner)
    monkeypatch.setattr(replication, "make_objective", bind)
    monkeypatch.setattr(replication, "extract_outputs", lambda family, result: {"Q": 3, "P": 1})
    monkeypatch.setattr(replication, "solve_solver", lambda name, objective, start, *args: {
        "status": "budget", "success": False, "fun": objective(start)})
    root = tmp_path / "experiment"
    summary = replication.run_replication(output_root=root, workers=1,
        **{**configuration, "diagnostics_policy": "reference-warmup"})
    record = json.loads(next((root / "runs").glob("*.json")).read_text())
    assert record["status"] == "budget_exhausted"
    assert record["strict_benchmark_evaluation"] is False
    assert record["warmup_severe_evaluations_used"] == summary["warmup_severe_evaluations_used"] == 1
    assert record["trace"][0]["diagnostics"]["severe_count"] == 1
    assert record["trace"][0]["diagnostics"]["fatal_count"] == 0
    assert record["trace"][0]["diagnostics"]["warmup_eio_rows"]
    directory = Path(record["trace"][0]["simulation_directory"])
    assert (directory / "eplusout.err").is_file()
    assert (directory / "run.json").is_file()
    assert not (directory / "large-output.eso").exists()


def test_worker_exit_is_checkpointed_as_interrupted_without_fabricating_an_objective(
        local_setup, tmp_path, monkeypatch):
    configuration, calls = local_setup

    class FailedPool:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def submit(self, *_):
            future = Future()
            future.set_exception(BrokenProcessPool("worker exited"))
            return future

    monkeypatch.setattr(replication, "ProcessPoolExecutor", FailedPool)
    root = tmp_path / "experiment"
    summary = replication.run_replication(output_root=root, workers=2, **configuration)
    record = json.loads(next((root / "runs").glob("*.json")).read_text())
    assert summary["statuses"]["interrupted"] == 1
    assert record["status"] == "interrupted" and record["best_f"] is None
    assert record["error"]["reason"] == "worker-process-failure"
    assert record["error"]["message"] == "worker exited"
    assert record["evaluation_count"] == 0 and calls == []
    assert not (root / "experiment.lock").exists()
