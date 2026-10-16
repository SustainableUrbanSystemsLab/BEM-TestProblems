# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Actual replication failures remain reproducible and cannot supply objectives.

Native CI replays these designs separately. Here, recorded diagnostic excerpts
exercise the real process boundary, and short recorded prefixes exercise durable
failure handling without running EnergyPlus or an optimizer.
"""

import copy
import json
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import pytest

from bem_testproblems import get_problem, replication
from bem_testproblems.energyplus import EnergyPlusError, EnergyPlusRunner, sha256_file
from tools.validate_cases import failure_diagnostics, require_failure_signature

FIXTURES = json.loads((Path(__file__).parents[1] / "reference" /
                       "replication-failure-cases.json").read_text(encoding="utf-8"))
CASES = FIXTURES["cases"]
CASE_IDS = [case["case_id"] for case in CASES]


def test_fixture_covers_every_distinct_audited_failure_without_machine_paths():
    assert len(CASES) == len(set(CASE_IDS)) == 23
    assert sum(len(case["source_runs"]) for case in CASES) == FIXTURES["source_record_count"] == 33
    assert len({(case["version"], case["input_sha256"]) for case in CASES}) == 23
    for case in CASES:
        assert all(source["evaluation"] == len(case["preceding_observations"]) + 1
                   for source in case["source_runs"])
        assert {source["experiment"] for source in case["source_runs"]} <= {"campaign", "pilot"}
        assert not any(value in json.dumps(case) for value in ("/Users/", "\\\\", "/private/"))


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_failed_design_still_has_exact_canonical_input_and_weather_identity(case, tmp_path):
    problem = get_problem(case["problem"])
    assert len(case["x"]) == problem.dimension
    problem.validate(case["x"])
    for previous in case["preceding_observations"]:
        problem.validate(previous["x"])
    render = problem.render_legacy if case["version"] == "8.5.0" else problem.render_modern
    suffix = ".idf" if case["version"] == "8.5.0" else ".epJSON"
    assert sha256_file(render(case["x"], tmp_path / ("model" + suffix))) == case["input_sha256"]
    weather = json.loads(files("bem_testproblems").joinpath(
        "data", "weather-assets.json").read_bytes())
    pinned = next(row for row in weather["files"] if row["cache_path"] == problem.weather_filename)
    assert case["weather_file"] == pinned["cache_path"]
    assert case["weather_sha256"] == pinned["sha256"]


def _write_diagnostics(directory, case):
    directory.mkdir(parents=True, exist_ok=True)
    observation = case["native_observation"]
    (directory / "eplusout.err").write_text(
        case["diagnostic_excerpt"] + observation["completion_marker"] + "\n", encoding="utf-8")
    (directory / "eplusout.end").write_text(
        observation["completion_marker"] + "\n", encoding="utf-8")


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_real_diagnostics_reject_even_zero_exit_and_successful_completion(
    case, tmp_path, fake_engine
):
    script = fake_engine.parent / "fake_engine.py"
    source = script.read_text(encoding="utf-8").replace(
        "EnergyPlus, Version 26.2.0-test", "EnergyPlus, Version " + case["version"] + "-test")
    observation = case["native_observation"]
    assert observation["returncode"] == 0
    source += ("\n(out / 'eplusout.err').write_text(" + repr(case["diagnostic_excerpt"] +
               observation["completion_marker"] + "\n") + ", encoding='utf-8')\n" +
               "(out / 'eplusout.end').write_text(" + repr(observation["completion_marker"] +
               "\n") + ", encoding='utf-8')\n")
    script.write_text(source, encoding="utf-8")
    model = tmp_path / "model.epJSON"
    model.write_text(json.dumps({"Version": {"v": {"version_identifier":
                                                  case["version"].rsplit(".", 1)[0]}}}),
                     encoding="utf-8")
    runner = EnergyPlusRunner(fake_engine, expected_version=case["version"],
                              output_root=tmp_path / "runs")
    with pytest.raises(EnergyPlusError) as caught:
        runner.run(model)
    error = caught.value
    assert error.reason == "simulation"
    metadata = json.loads((error.directory / "run.json").read_text(encoding="utf-8"))
    assert metadata["returncode"] == 0
    assert metadata["status"] == "failed"
    assert (error.directory / "eplusout.end").read_text(encoding="utf-8").startswith(
        "EnergyPlus Completed Successfully")
    require_failure_signature(failure_diagnostics(error.directory), case["expected_failure"])
    # Failed runs must not enter the runner cache or lose their diagnostic files.
    with pytest.raises(EnergyPlusError) as retry:
        runner.run(model)
    assert retry.value.directory != error.directory
    assert (error.directory / "eplusout.err").is_file()


@pytest.fixture
def checkpoint_harness(tmp_path, monkeypatch):
    """Stub native execution only; leave the real checkpoint controller in use."""
    executable = tmp_path / "fixture-engine"
    executable.write_bytes(b"No native simulations in this test.\n")
    identity = sha256_file(executable)
    monkeypatch.setattr(replication, "EnergyPlusRunner", lambda *args, **kwargs:
                        SimpleNamespace(version=kwargs["expected_version"],
                                        executable_sha256=identity))
    monkeypatch.setattr(replication, "_model_identity", lambda *args: {"fixture": True})

    def manifest(case, multiplier):
        source = case["source_runs"][0]
        spec = {"id": source["id"], "problem": case["problem"], "version": case["version"],
                "solver": "bobyqa", "repetition": 0, "seed": source["seed"],
                "x0": case["preceding_observations"][0]["x"] if
                case["preceding_observations"] else case["x"],
                "budget": source["evaluation"] + 1}
        return {"manifest_id": "recorded-failure-fixture", "runs": [spec],
                "protocol": "extended-budget-experiment", "budget_multiplier": multiplier,
                "project_root": str(tmp_path), "weather_directory": str(tmp_path),
                "problem_definitions": {str(case["problem"]): {
                    "models": {case["version"]: {"fixture": True}}}},
                "engines": {case["version"]: {"executable": str(executable),
                                               "executable_sha256": identity}},
                "solvers": {"bobyqa": {"implemented": True}}, "diagnostics_policy": "strict"}

    return manifest


@pytest.mark.parametrize("multiplier", [1, 100], ids=["json", "journal"])
@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_recorded_first_and_later_failures_preserve_only_the_valid_prefix(
    case, multiplier, checkpoint_harness, tmp_path, monkeypatch
):
    failed_directory = tmp_path / "failed-native-output"
    _write_diagnostics(failed_directory, case)
    error = EnergyPlusError("Recorded warmup failure", reason="simulation",
                            directory=failed_directory)
    preceding = case["preceding_observations"]
    observations = iter(preceding)
    attempted = []

    def bind(problem, **kwargs):
        def evaluate(x):
            attempted.append(list(x))
            previous = next(observations, None)
            if previous is None:
                assert list(x) == case["x"]
                raise error
            assert list(x) == previous["x"]
            return previous["f"]
        return evaluate

    def solve(name, objective, start, bounds, budget, seed):
        for observation in preceding:
            objective(observation["x"])
        objective(case["x"])
        pytest.fail("A rejected simulation must escape the optimizer immediately")

    monkeypatch.setattr(replication, "make_objective", bind)
    monkeypatch.setattr(replication, "solve_solver", solve)
    manifest = checkpoint_harness(case, multiplier)
    root = tmp_path / "experiment"
    record = replication._run_one(manifest["runs"][0], manifest, root, "none")
    saved = replication.read_checkpoint(root / "runs" / (record["id"] + ".json"))
    assert saved == record
    assert record["status"] == "failed"
    assert record["evaluation_count"] == len(attempted) == len(preceding) + 1
    assert [item["f"] for item in record["trace"][:-1]] == [item["f"] for item in preceding]
    assert record["trace"][-1]["f"] is None
    assert record["trace"][-1]["status"] == "failed"
    if preceding:
        best = min(preceding, key=lambda item: item["f"])
        assert record["best_f"] == best["f"]
        assert record["best_x"] == best["x"]
    else:
        assert record["best_f"] is None and record["best_x"] is None
    assert record["error"]["severe_count"] == case["expected_failure"]["severe_count"]
    assert record["error"]["fatal_count"] == 0
    assert record["strict_benchmark_evaluation"] is True
    assert record["warmup_severe_evaluations_used"] == 0
    assert (failed_directory / "eplusout.err").is_file()


def test_one_actual_failure_does_not_cancel_the_next_scheduled_run(
    checkpoint_harness, tmp_path, monkeypatch
):
    case = CASES[0]
    failed_directory = tmp_path / "failed-native-output"
    _write_diagnostics(failed_directory, case)
    manifest = checkpoint_harness(case, 100)
    healthy = copy.deepcopy(manifest["runs"][0])
    healthy["id"] += "-healthy-control"
    manifest["runs"].append(healthy)
    bound = []

    def bind(problem, **kwargs):
        reject = not bound
        bound.append(problem.id)

        def evaluate(x):
            if reject:
                raise EnergyPlusError("Recorded warmup failure", reason="simulation",
                                      directory=failed_directory)
            return 17.0
        return evaluate

    monkeypatch.setattr(replication, "prepare_manifest", lambda **kwargs: manifest)
    monkeypatch.setattr(replication, "make_objective", bind)
    monkeypatch.setattr(replication, "solve_solver", lambda name, objective, start, *args: {
        "status": "terminated", "success": True, "fun": objective(start)})
    root = tmp_path / "experiment"
    summary = replication.run_replication(output_root=root, workers=1, budget_multiplier=100)
    assert summary["statuses"]["failed"] == summary["statuses"]["completed"] == 1
    assert summary["evaluation_count"] == 2
    assert len(bound) == 2
    success = replication.read_checkpoint(root / "runs" / (healthy["id"] + ".json"))
    assert success["best_f"] == 17.0
    failed = replication.read_checkpoint(root / "runs" / (manifest["runs"][0]["id"] + ".json"))
    assert failed["best_f"] is None
