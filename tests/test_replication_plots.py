# SPDX-License-Identifier: MIT
"""Protect scientific plot denominators against incomplete and failed results."""

import json

import pytest

from bem_testproblems.replication_plots import collect_boxplot_data, plot_replication


def experiment(tmp_path):
    specs = [{"id": str(i), "problem": 1, "version": "8.5.0", "solver": "bobyqa"}
             for i in range(4)]
    manifest = {"manifest_id": "example", "runs": specs, "protocol": "pilot-overrides",
                "requested_repetitions": 4, "engines": {"8.5.0": {}},
                "problem_definitions": {"1": {"name": "Example", "dimension": 1,
                                                "objective_unit": "kWh"}},
                "solvers": {"bobyqa": {"implemented": True}},
                "solver_registry": [{"name": "bobyqa", "implemented": True},
                                    {"name": "galapagos_ga", "implemented": False}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "runs").mkdir()
    for i, status in enumerate(("budget_exhausted", "failed", "running")):
        record = {**specs[i], "manifest_id": "example", "status": status,
                  "strict_benchmark_evaluation": True,
                  "best_f": [10, -100, -200][i], "best_x": [i]}
        (tmp_path / "runs" / f"{i}.json").write_text(json.dumps(record))
    return tmp_path


def test_failed_and_running_incumbents_cannot_enter_boxplot(tmp_path):
    _, data = collect_boxplot_data(experiment(tmp_path))
    assert data[0]["values"] == [10]
    assert data[0]["accepted"] == 1
    assert data[0]["requested"] == 4
    assert data[0]["statuses"] == {"budget_exhausted": 1, "failed": 1,
                                  "running": 1, "pending": 1}


def test_mismatched_run_provenance_is_rejected(tmp_path):
    root = experiment(tmp_path)
    path = root / "runs/0.json"
    record = json.loads(path.read_text())
    record["manifest_id"] = "other-experiment"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="provenance"):
        collect_boxplot_data(root)


def test_wrong_engine_and_duplicate_ids_are_rejected(tmp_path):
    root = experiment(tmp_path)
    path = root / "runs/0.json"
    record = json.loads(path.read_text())
    record["version"] = "26.2.0"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="specification"):
        collect_boxplot_data(root)
    record["version"] = "8.5.0"
    path.write_text(json.dumps(record))
    (root / "runs/duplicate.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="specification"):
        collect_boxplot_data(root)


def test_partial_plot_is_labeled_and_numerical_summary_is_preserved(tmp_path):
    pytest.importorskip("matplotlib")
    result = plot_replication(experiment(tmp_path))
    assert result["scope"] == "PILOT / INCOMPLETE"
    report = json.loads((tmp_path / "plots/boxplot-summary.json").read_text())
    assert report["partial"] is True
    assert report["groups"][0]["statistics"]["median"] == 10
    assert report["skipped_original_methods"][0]["name"] == "galapagos_ga"
    assert len(result["plots"]) == 2
    assert (tmp_path / "plots/figure8-energyplus-8.5.0.png").stat().st_size > 0
    svg = (tmp_path / "plots/figure8-energyplus-8.5.0.svg").read_text()
    assert "Example (n=1)" in svg
    assert "runs: 1/4; failed runs: 1" in svg
    assert "n=1/4" not in svg


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_completed_records_need_a_finite_best_objective(tmp_path, value):
    root = experiment(tmp_path)
    path = root / "runs/0.json"
    record = json.loads(path.read_text())
    record["best_f"] = value
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="finite best objective"):
        collect_boxplot_data(root)


def test_duplicate_manifest_specs_are_rejected_before_plotting(tmp_path):
    root = experiment(tmp_path)
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["runs"].append(manifest["runs"][0])
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Duplicate run IDs"):
        collect_boxplot_data(root)


@pytest.mark.parametrize("number", (1, 13))
def test_paired_engine_summary_uses_completed_medians_and_the_old_engine_denominator(tmp_path, number):
    pytest.importorskip("matplotlib")
    root = experiment(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["problem_definitions"] = {str(number): manifest["problem_definitions"]["1"]}
    for spec in manifest["runs"]:
        spec["problem"] = number
    manifest["protocol"] = "paper-start-and-budget-protocol"
    manifest["engines"]["26.2.0"] = {}
    for version, values in (("8.5.0", (10, 20, 30, 40)), ("26.2.0", (12, 24, 36, 48))):
        for i, value in enumerate(values):
            spec = {"id": str(i) if version == "8.5.0" else f"modern-{i}",
                    "problem": number, "version": version, "solver": "bobyqa"}
            if version != "8.5.0":
                manifest["runs"].append(spec)
            record = {**spec, "manifest_id": "example", "status": "completed",
                      "strict_benchmark_evaluation": i != 0,
                      "best_f": value, "best_x": [i], "warmup_severe_evaluations_used": 2 if i == 0 else 0}
            (root / "runs" / f"{spec['id']}.json").write_text(json.dumps(record))
    manifest_path.write_text(json.dumps(manifest))
    result = plot_replication(root, include_diagnostic_runs=True)
    report = json.loads((root / "plots-diagnostic/boxplot-summary.json").read_text())
    assert result["scope"] == "PAPER BUDGET" and not report["partial"]
    assert report["groups"][0]["statistics"] == {
        "minimum": 10, "q1": 17.5, "median": 25, "q3": 32.5, "maximum": 40}
    comparison = report["engine_median_comparisons"][0]
    assert comparison["median_8.5"] == 25 and comparison["median_26.2"] == 30
    assert comparison["signed_difference"] == 5 and comparison["percentage_change"] == 20
    assert comparison["accepted_8.5"] == comparison["accepted_26.2"] == 4
    assert report["groups"][0]["runs_using_warmup_severe_outputs"] == 1
    assert report["groups"][0]["warmup_severe_evaluations_used"] == 2
    assert report["result_selection"] == "diagnostic-completed-trajectories"
    assert not (root / "plots").exists()


@pytest.mark.parametrize("strict,used", [(False, 2), (True, 2), (None, 0)])
def test_non_strict_search_is_excluded_even_when_its_winning_value_is_finite(tmp_path, strict, used):
    root = experiment(tmp_path)
    path = root / "runs/0.json"
    record = json.loads(path.read_text())
    record.update(strict_benchmark_evaluation=strict, warmup_severe_evaluations_used=used)
    path.write_text(json.dumps(record))
    _, groups = collect_boxplot_data(root)
    assert groups[0]["values"] == []
    assert groups[0]["accepted"] == 0
    assert groups[0]["requested"] == 4
    assert groups[0]["excluded_non_strict_completed_runs"] == 1
    _, diagnostics = collect_boxplot_data(root, include_diagnostic_runs=True)
    assert diagnostics[0]["values"] == [10]


def test_strict_plot_reports_excluded_searches_and_preserves_failure_counts(tmp_path):
    pytest.importorskip("matplotlib")
    root = experiment(tmp_path)
    path = root / "runs/0.json"
    record = json.loads(path.read_text())
    record.update(strict_benchmark_evaluation=False, warmup_severe_evaluations_used=1)
    path.write_text(json.dumps(record))
    result = plot_replication(root)
    report = json.loads((tmp_path / "plots/boxplot-summary.json").read_text())
    assert report["result_selection"] == "strict-completed-trajectories"
    assert report["groups"][0]["statistics"] is None
    assert report["groups"][0]["excluded_non_strict_completed_runs"] == 1
    assert report["groups"][0]["statuses"]["failed"] == 1
    assert len(result["plots"]) == 2
    svg = (root / "plots/figure8-energyplus-8.5.0.svg").read_text()
    assert "runs: 0/4; failed runs: 1" in svg
    assert "excluded non-strict runs: 1" in svg


def test_numerical_variant_is_visible_in_figures_and_numerical_groups(tmp_path):
    pytest.importorskip("matplotlib")
    root = experiment(tmp_path)
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["problem_definitions"]["1"]["numerical_variant"] = "warmup-100"
    path.write_text(json.dumps(manifest))
    plot_replication(root)
    report = json.loads((root / "plots/boxplot-summary.json").read_text())
    assert report["groups"][0]["numerical_variant"] == "warmup-100"
    assert "Numerical variant: warmup-100" in (
        root / "plots/figure8-energyplus-8.5.0.svg").read_text()
