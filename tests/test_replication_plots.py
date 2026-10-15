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
                "problem_definitions": {"1": {"name": "Example", "objective_unit": "kWh"}},
                "solvers": {"bobyqa": {"implemented": True}},
                "solver_registry": [{"name": "bobyqa", "implemented": True},
                                    {"name": "galapagos_ga", "implemented": False}]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "runs").mkdir()
    for i, status in enumerate(("budget_exhausted", "failed", "running")):
        record = {**specs[i], "manifest_id": "example", "status": status,
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
