"""Check batch reporting with real PDFO and cheap, known quadratic objectives."""

import json
import os
import time
from pathlib import Path

import pytest

from bem_testproblems.energyplus import EnergyPlusError


def parallel_case(problem_id, directory, corrected_models):
    """Two real workers must overlap before these cheap fixture jobs finish."""
    directory = Path(directory)
    directory.mkdir()
    (directory / "started").write_text(str(os.getpid()))
    deadline = time.monotonic() + 30
    while not all((directory.parent / f"P{number}/started").exists() for number in (1, 2)):
        if time.monotonic() > deadline:
            raise RuntimeError("The first two problems did not run concurrently")
        time.sleep(0.02)
    failed = problem_id == 4
    record = {
        "problem": problem_id, "pid": os.getpid(), "corrected_models": corrected_models,
        "outcome": "failed" if failed else "completed", "elapsed_seconds": 0,
        "objective": None if failed else float(problem_id),
        "best_objective": None if failed else float(problem_id), "objective_unit": "fixture",
        "message": "Fixture outcome", "threads": os.environ.get("OPENBLAS_NUM_THREADS"),
    }
    (directory / "result.json").write_text(json.dumps(record))
    return record


@pytest.mark.parametrize(("model_flag", "corrected"), [
    (None, True), ("--canonical-models", False), ("--corrected-models", True),
])
def test_batch_keeps_results_and_continues_after_simulation_error(
        tmp_path, monkeypatch, capsys, model_flag, corrected):
    pytest.importorskip("pdfo")
    from examples import solve_all_bobyqa as example

    variants = {}

    def analytic_objective(problem, **kwargs):
        variants[problem.id] = problem.numerical_variant
        if problem.id == 4:
            raise EnergyPlusError("Deliberate simulation failure fixture")
        return lambda x: sum((value - middle) ** 2 for value, middle in zip(x, problem.midpoint))

    monkeypatch.setattr(example, "make_objective", analytic_objective)
    args = ["solve_all_bobyqa.py", "--output", str(tmp_path)]
    if model_flag:
        args.append(model_flag)
    monkeypatch.setattr("sys.argv", args)
    previous = tmp_path / "previous-results.txt"
    previous.write_text("preserve me")

    assert example.main() == 1
    output = capsys.readouterr().out
    assert output.count("Final objective:") == 10
    assert output.count("Best observed objective:") == 10
    assert previous.read_text() == "preserve me"
    directory, = [path for path in tmp_path.iterdir() if path.is_dir()]
    records = {}
    for path in directory.glob("P*/result.json"):
        record = json.loads(path.read_text())
        records[record["problem"]] = record
    assert {number: record["max_evaluations"] for number, record in records.items()} == {
        1: 500, 2: 500, 3: 500, 4: 1400, 5: 1400,
        6: 1400, 8: 1200, 9: 1400, 10: 1400, 13: 1100,
    }
    assert records[4]["outcome"] == "failed"
    assert "Deliberate simulation failure" in records[4]["error"]
    assert (directory / "P4/traceback.txt").is_file()
    for number, record in records.items():
        expected_variant = "model-corrected-v3" if corrected and number not in (2, 8, 13) else None
        assert variants[number] == expected_variant
        assert record["model"] == (expected_variant or "canonical")
        if number != 4:
            assert record["outcome"] == "completed"
            assert record["objective"] == pytest.approx(0, abs=1e-12)
            assert record["best_objective"] == pytest.approx(0, abs=1e-12)
            assert record["parameters"] == pytest.approx(record["starting_point"])
            assert 0 < record["evaluations"] <= record["max_evaluations"]


def test_p13_initial_steps_are_comparable_fractions_of_each_bound_width(tmp_path, monkeypatch):
    pytest.importorskip("pdfo")
    from examples import solve_all_bobyqa as example

    problem = example.get_problem(13)
    points = []

    def objective(x):
        points.append(tuple(x))
        return sum((value - middle) ** 2 for value, middle in zip(x, problem.midpoint))

    monkeypatch.setattr(example, "make_objective", lambda *args, **kwargs: objective)
    result = example.solve_problem(13, tmp_path / "P13")
    assert result["outcome"] == "completed"
    assert len(points) == result["evaluations"]  # Reporting must not reevaluate the objective.
    initial_points = points[:2 * problem.dimension + 1]
    for index, (lower, upper) in enumerate(problem.bounds):
        largest_step = max(abs(x[index] - problem.midpoint[index]) for x in initial_points)
        assert largest_step / (upper - lower) == pytest.approx(0.25)


@pytest.mark.parametrize(("cpus", "expected"), [(None, 1), (1, 1), (2, 1), (8, 6)])
def test_auto_workers_leave_two_cpus_when_possible(monkeypatch, cpus, expected):
    from examples import solve_all_bobyqa as example

    monkeypatch.setattr(example.os, "cpu_count", lambda: cpus)
    assert example.worker_count("auto") == expected


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_invalid_workers_are_rejected_before_creating_outputs(tmp_path, monkeypatch, value):
    from examples import solve_all_bobyqa as example

    output = tmp_path / "unused"
    monkeypatch.setattr("sys.argv", ["example", "--workers", value, "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        example.main()
    assert error.value.code == 2
    assert not output.exists()


def test_parallel_workers_overlap_keep_outputs_separate_and_report_failures(
        tmp_path, monkeypatch, capsys):
    from examples import solve_all_bobyqa as example

    monkeypatch.setattr(example.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(example, "solve_problem", parallel_case)
    monkeypatch.setattr("sys.argv", ["example", "--workers", "auto", "--output", str(tmp_path)])
    assert example.main() == 1
    output = capsys.readouterr().out
    assert "Workers: 2 for 10 problems" in output
    assert "9 completed, 1 failed" in output
    assert output.count("Final objective:") == 10
    directory, = tmp_path.iterdir()
    records = [json.loads(path.read_text()) for path in directory.glob("P*/result.json")]
    assert {row["problem"] for row in records} == set(example.PROBLEM_IDS)
    assert len({row["pid"] for row in records}) == 2
    assert all(row["pid"] != os.getpid() and row["threads"] == "1" for row in records)
    assert all(row["corrected_models"] for row in records)
