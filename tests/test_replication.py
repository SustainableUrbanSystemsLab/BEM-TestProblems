# SPDX-License-Identifier: MIT
"""Experiment fairness, strict failures, durable budgets and deterministic resumption."""

import copy
import json
import os
import tempfile
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from types import SimpleNamespace

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


def test_hundredfold_budget_for_every_problem_and_engine_preserves_paired_designs(local_setup):
    configuration, _ = local_setup
    configuration.update(problems=replication.PROBLEM_IDS, versions=["8.5.0", "26.2.0"],
                         solvers=["bobyqa", "pybobyqa"], repetitions=20, budget=None)
    original = replication.prepare_manifest(**configuration)
    assert original == replication.prepare_manifest(**configuration, budget_multiplier=1)
    assert "budget_multiplier" not in original
    extended = replication.prepare_manifest(**configuration, budget_multiplier=100)
    assert extended["protocol"] == "extended-budget-experiment"
    assert extended["budget_multiplier"] == 100
    assert extended["effective_budget_rule"] == "100*(dimension+1)*budget_multiplier"
    assert extended["budget_override"] is None
    assert extended["manifest_id"] != original["manifest_id"]
    assert len(extended["runs"]) == 10 * 2 * 2 * 20
    starts = {}
    for previous, current in zip(original["runs"], extended["runs"]):
        assert current["budget"] == previous["budget"] * 100
        assert current["budget"] == 10000 * (get_problem(current["problem"]).dimension + 1)
        assert {key: value for key, value in current.items() if key != "budget"} == {
            key: value for key, value in previous.items() if key != "budget"}
        key = current["problem"], current["repetition"]
        assert starts.setdefault(key, current["x0"]) == current["x0"]


@pytest.mark.parametrize("multiplier", [0, -1, 1.5, "100", True, None])
def test_budget_multiplier_requires_a_positive_integer(local_setup, multiplier):
    configuration, _ = local_setup
    with pytest.raises(ValueError, match="budget_multiplier must be a positive integer"):
        replication.prepare_manifest(**{**configuration, "budget": None},
                                     budget_multiplier=multiplier)


def test_explicit_pilot_budget_cannot_be_combined_with_a_budget_multiplier(local_setup):
    configuration, _ = local_setup
    with pytest.raises(ValueError, match="cannot both override"):
        replication.prepare_manifest(**configuration, budget_multiplier=100)
    assert replication.prepare_manifest(**configuration, budget_multiplier=1)[
        "protocol"] == "pilot-overrides"


def test_extended_experiment_with_fewer_repetitions_is_never_labelled_paper_replication(local_setup):
    configuration, _ = local_setup
    manifest = replication.prepare_manifest(**{**configuration, "budget": None}, budget_multiplier=100)
    assert manifest["protocol"] == "extended-budget-experiment"
    assert manifest["requested_repetitions"] == 1


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


def test_p1_variant_changes_identity_without_changing_starts_seeds_or_budgets(local_setup):
    configuration, _ = local_setup
    configuration.update(problems=[1, 13], versions=["8.5.0", "26.2.0"], budget=None)
    canonical = replication.prepare_manifest(**configuration)
    explicit_default = replication.prepare_manifest(**configuration, p1_warmup_100=False)
    variant = replication.prepare_manifest(**configuration, p1_warmup_100=True)
    assert canonical == explicit_default
    assert "p1_warmup_100" not in canonical
    assert all("numerical_variant" not in row for row in canonical["problem_definitions"].values())
    assert variant["p1_warmup_100"] is True
    assert variant["manifest_id"] != canonical["manifest_id"]
    assert variant["runs"] == canonical["runs"]
    assert variant["problem_definitions"]["1"]["numerical_variant"] == "warmup-100"
    assert variant["problem_definitions"]["13"] == canonical["problem_definitions"]["13"]
    assert variant["diagnostics_policy"] == "strict"


@pytest.mark.parametrize("options", [{"p1_warmup_100": True}, {"p1_warmup_100": 1}])
def test_p1_variant_requires_p1_and_an_explicit_boolean(local_setup, options):
    configuration, _ = local_setup
    with pytest.raises(ValueError, match="p1_warmup_100"):
        replication.prepare_manifest(**configuration, **options)


def test_worker_reconstructs_the_variant_and_still_rejects_severe_outputs(
    local_setup, tmp_path, monkeypatch
):
    configuration, _ = local_setup
    configuration.update(problems=[1], p1_warmup_100=True)
    selected = []
    error = EnergyPlusError("Strict warmup rejection", reason="simulation", directory=tmp_path)

    def bind(problem, **kwargs):
        selected.append(problem)

        def evaluate(x):
            raise error
        return evaluate

    def solver(name, objective, start, *args):
        return {"status": "terminated", "fun": objective(start)}

    monkeypatch.setattr(replication, "make_objective", bind)
    monkeypatch.setattr(replication, "solve_solver", solver)
    monkeypatch.setattr(replication, "extract_outputs", lambda *args:
                        pytest.fail("A Severe diagnostic must not supply simulator outputs"))
    manifest = replication.prepare_manifest(**configuration)
    record = replication._run_one(manifest["runs"][0], manifest, tmp_path / "experiment", "none")
    assert selected == [get_problem(1, numerical_variant="warmup-100")]
    assert record["problem_provenance"]["numerical_variant"] == "warmup-100"
    assert record["status"] == "failed"
    assert record["best_f"] is None and record["best_x"] is None
    assert record["trace"][0]["f"] is None
    assert record["error"]["reason"] == "simulation"
    assert record["strict_benchmark_evaluation"] is True
    assert record["warmup_severe_evaluations_used"] == 0


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
    from tools import continue_replication
    _, records, _ = continue_replication.read_origin(root)
    assert records[record["id"]] == record


@pytest.mark.parametrize("workers,expected", [(1, [1]), (60, [60]), (61, [31, 30]),
                                             (120, [60, 60]), (121, [41, 40, 40])])
def test_worker_pools_cover_the_requested_allocation_and_each_run_once(workers, expected):
    specs = [{"id": f"r{index:03}", "budget": 100 + index % 10}
             for index in range(200)]
    pools = replication.worker_pool_partition(specs, workers)
    assert [size for size, _ in pools] == expected
    assert sorted(row["id"] for _, group in pools for row in group) == sorted(
        row["id"] for row in specs)
    if len(pools) == 1:
        assert pools[0][1] == specs
    else:
        normalized_loads = [sum(row["budget"] for row in group) / size for size, group in pools]
        assert max(normalized_loads) - min(normalized_loads) <= max(
            row["budget"] for row in specs) / min(expected)


def test_two_spawn_pools_share_one_lock_and_resume_without_duplicate_work(
    local_setup, tmp_path, monkeypatch
):
    configuration, calls = local_setup
    configuration.update(repetitions=4, versions=["8.5.0", "26.2.0"], budget=None)
    root = tmp_path / "experiment"
    allocations, submitted = [], []
    original_environment = {name: os.environ.get(name) for name in replication.WORKER_THREAD_VARIABLES}
    monkeypatch.setattr(replication, "solve_solver", lambda name, objective, start, *args: {
        "status": "terminated", "fun": objective(start)})

    class ImmediatePool:
        def __init__(self, max_workers, mp_context):
            assert (root / "experiment.lock").is_file()
            assert mp_context.get_start_method() == "spawn"
            assert all(os.environ[name] == "1" for name in replication.WORKER_THREAD_VARIABLES)
            allocations.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def submit(self, function, spec, *args):
            submitted.append(spec["id"])
            future = Future()
            result = function(spec, *args)
            assert result is None  # Full traces must stay out of retained futures.
            future.set_result(result)
            return future

    monkeypatch.setattr(replication, "ProcessPoolExecutor", ImmediatePool)
    summary = replication.run_replication(output_root=root, workers=120,
                                          budget_multiplier=100, **configuration)
    assert allocations == [60, 60]
    assert len(submitted) == len(set(submitted)) == len(calls) == 8
    assert summary["statuses"]["completed"] == 8
    assert summary["protocol"] == "extended-budget-experiment"
    assert {name: os.environ.get(name) for name in replication.WORKER_THREAD_VARIABLES} == original_environment
    assert not (root / "experiment.lock").exists()
    replication.run_replication(output_root=root, workers=120,
                               budget_multiplier=100, **configuration)
    assert allocations == [60, 60] and len(calls) == 8
    checkpoint = next((root / "runs").glob("*.json"))
    previous = json.loads(checkpoint.read_text())
    checkpoint.write_text(json.dumps({**previous, "status": "running"}))
    replication.run_replication(output_root=root, workers=120,
                               budget_multiplier=100, **configuration)
    assert len(calls) == 9 and submitted.count(previous["id"]) == 2
    resumed = json.loads(checkpoint.read_text())
    assert resumed["attempt"] == 2
    assert resumed["budget"] == previous["budget"]
    assert resumed["x0"] == previous["x0"] and resumed["seed"] == previous["seed"]
    assert not (root / "experiment.lock").exists()


def test_native_thread_environment_is_restored_when_pool_startup_fails(
    local_setup, tmp_path, monkeypatch
):
    configuration, _ = local_setup
    monkeypatch.setenv("OMP_NUM_THREADS", "17")
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)

    def failed_start(**kwargs):
        raise RuntimeError("simulated process startup failure")

    monkeypatch.setattr(replication, "ProcessPoolExecutor", failed_start)
    root = tmp_path / "experiment"
    with pytest.raises(RuntimeError, match="startup failure"):
        replication.run_replication(output_root=root, workers=120, **configuration)
    assert os.environ["OMP_NUM_THREADS"] == "17"
    assert "MKL_NUM_THREADS" not in os.environ
    assert not (root / "experiment.lock").exists()


def test_cli_accepts_extended_budget_and_rejects_ambiguous_budget_options(monkeypatch, capsys):
    from tools import run_replication

    options = []
    monkeypatch.setattr(run_replication, "run_replication", lambda **kwargs: options.append(kwargs) or {})
    run_replication.main(["--budget-multiplier", "100", "--workers", "120"])
    assert options[0]["budget_multiplier"] == 100 and options[0]["workers"] == 120
    assert options[0]["budget"] is None
    with pytest.raises(SystemExit):
        run_replication.main(["--budget", "25", "--budget-multiplier", "100"])
    assert len(options) == 1
    assert "not allowed with argument" in capsys.readouterr().err


def test_long_search_uses_linear_durable_writes_and_a_self_contained_terminal_checkpoint(
    local_setup, tmp_path, monkeypatch
):
    configuration, calls = local_setup
    configuration.update(budget=None)
    manifest = replication.prepare_manifest(**configuration, budget_multiplier=100)
    root = tmp_path / "experiment"
    checkpoint = root / "runs" / (manifest["runs"][0]["id"] + ".json")
    sizes = []
    original_write = replication._atomic_json

    def inspect_write(path, value):
        if path == checkpoint:
            sizes.append(len(json.dumps(value)))
            if value["status"] == "running":
                assert value["trace"] == []
                assert value["trace_storage"]["events"] == value["evaluation_count"]
        original_write(path, value)

    def solver(name, objective, start, bounds, budget, seed):
        assert budget == 110000
        for count in range(1, 161):
            objective(start)
            recovered = replication.read_checkpoint(checkpoint)
            assert len(recovered["trace"]) == recovered["evaluation_count"] == count
        return {"status": "terminated", "success": True}

    monkeypatch.setattr(replication, "_atomic_json", inspect_write)
    monkeypatch.setattr(replication, "solve_solver", solver)
    result = replication._run_one(manifest["runs"][0], manifest, root, "none")
    final = json.loads(checkpoint.read_text())
    assert result == final and len(result["trace"]) == len(calls) == 160
    assert "trace_storage" not in final and final["status"] == "completed"
    assert max(sizes[:-1]) < sizes[1] + 100
    assert sum(sizes) < 165 * sizes[1] + sizes[-1]
    journal = next((checkpoint.parent / "traces").glob("*.jsonl"))
    assert len(journal.read_text().splitlines()) == 160


def test_restarting_a_killed_long_run_archives_the_exact_materialized_prefix(
    local_setup, tmp_path, monkeypatch
):
    configuration, _ = local_setup
    configuration.update(budget=None)
    manifest = replication.prepare_manifest(**configuration, budget_multiplier=100)
    spec = manifest["runs"][0]
    root = tmp_path / "experiment"
    checkpoint = root / "runs" / (spec["id"] + ".json")
    previous = {**spec, "manifest_id": manifest["manifest_id"], "attempt": 1,
                "status": "running", "evaluation_count": 1,
                "trace": [{"evaluation": 1, "status": "success", "f": 17.0}]}
    writer = replication.TraceJournal(checkpoint, 1)
    replication._atomic_json(checkpoint, writer.snapshot(previous))
    with writer.path.open("a") as stream:
        stream.write('{"evaluation":2')
    monkeypatch.setattr(replication, "solve_solver", lambda name, objective, start, *args: {
        "status": "terminated", "fun": objective(start)})
    restarted = replication._run_one(spec, manifest, root, "none")
    archived = json.loads((root / "history" / f"{spec['id']}-attempt1.json").read_text())
    assert archived == previous
    assert archived["status"] == "running"
    assert restarted["attempt"] == 2
    assert restarted["x0"] == previous["x0"] and restarted["seed"] == previous["seed"]
    assert writer.path.read_text().endswith('{"evaluation":2')


@pytest.mark.parametrize("file_id_available", [True, False])
def test_progress_summaries_cache_only_counters_and_observe_new_checkpoint_versions(
    local_setup, tmp_path, monkeypatch, file_id_available
):
    configuration, _ = local_setup
    manifest = replication.prepare_manifest(**{**configuration, "budget": None}, budget_multiplier=100)
    root = tmp_path / "experiment"
    spec = manifest["runs"][0]
    checkpoint = root / "runs" / (spec["id"] + ".json")
    row = {**spec, "status": "running", "evaluation_count": 1, "elapsed_seconds": 4.0,
           "measured_objective_seconds": 3.0,
           "trace": [{"evaluation": 1, "status": "success", "f": 12.0}]}
    writer = replication.TraceJournal(checkpoint, 1)
    replication._atomic_json(checkpoint, writer.snapshot(row))
    previous_stat = checkpoint.stat()
    original_stat = Path.stat
    if not file_id_available:
        def stat_without_file_id(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path != checkpoint:
                return result
            return SimpleNamespace(st_dev=result.st_dev, st_ino=0,
                                   st_mtime_ns=result.st_mtime_ns, st_size=result.st_size)
        monkeypatch.setattr(Path, "stat", stat_without_file_id)
    reads = []
    original_read = Path.read_text

    def count_read(path, *args, **kwargs):
        reads.append(path)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", count_read)
    monkeypatch.setattr(replication, "read_checkpoint", lambda *args:
                        pytest.fail("Live progress counters must not load the growing trace"))
    cache = {}
    first = replication._summary(root, manifest, 120, cache=cache)
    repeated = replication._summary(root, manifest, 120, cache=cache)
    initial_reads = 1 if file_id_available else 2
    assert first == repeated and reads.count(checkpoint) == initial_reads
    assert first["measured_objective_seconds"] == 3.0 and first["evaluation_count"] == 1
    row["trace"].append({"evaluation": 2, "status": "success", "f": 11.0})
    row.update(evaluation_count=2, measured_objective_seconds=6.5, elapsed_seconds=7.0)
    replication._atomic_json(checkpoint, writer.snapshot(row))
    os.utime(checkpoint, ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns))
    updated_stat = original_stat(checkpoint)
    assert (updated_stat.st_mtime_ns, updated_stat.st_size) == (
        previous_stat.st_mtime_ns, previous_stat.st_size)
    updated = replication._summary(root, manifest, 120, cache=cache)
    assert reads.count(checkpoint) == initial_reads + 1
    assert updated["measured_objective_seconds"] == 6.5 and updated["evaluation_count"] == 2
    assert "trace" not in cache[checkpoint][1]


def test_journal_creation_before_a_killed_initial_checkpoint_does_not_block_restart(
    local_setup, tmp_path, monkeypatch
):
    configuration, _ = local_setup
    manifest = replication.prepare_manifest(**{**configuration, "budget": None}, budget_multiplier=100)
    spec = manifest["runs"][0]
    root = tmp_path / "experiment"
    checkpoint = root / "runs" / (spec["id"] + ".json")
    orphan = replication.TraceJournal(checkpoint, 1)
    orphan_bytes = orphan.path.read_bytes()
    assert not checkpoint.exists()
    monkeypatch.setattr(replication, "solve_solver", lambda name, objective, start, *args: {
        "status": "terminated", "fun": objective(start)})
    result = replication._run_one(spec, manifest, root, "none")
    assert result["status"] == "completed" and result["evaluation_count"] == 1
    assert orphan.path.read_bytes() == orphan_bytes
    assert len(list(orphan.path.parent.glob("*.jsonl"))) == 2
