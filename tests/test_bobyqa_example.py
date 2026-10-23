"""Check batch reporting with real PDFO and cheap, known quadratic objectives."""

import json

import pytest

from bem_testproblems.energyplus import EnergyPlusError


@pytest.mark.parametrize(("model_flag", "corrected"), [
    (None, True), ("--canonical-models", False), ("--corrected-models", True),
])
def test_batch_keeps_results_and_continues_after_simulation_error(
        tmp_path, monkeypatch, model_flag, corrected):
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
    initial_points = points[:2 * problem.dimension + 1]
    for index, (lower, upper) in enumerate(problem.bounds):
        largest_step = max(abs(x[index] - problem.midpoint[index]) for x in initial_points)
        assert largest_step / (upper - lower) == pytest.approx(0.25)
