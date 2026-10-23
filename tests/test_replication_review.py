# SPDX-License-Identifier: MIT
"""Joined reviews preserve denominators and reject altered evidence."""

import copy
import json
from collections import Counter

import pytest

from bem_testproblems import get_problem
from tools.continue_replication import _digest, read_origin
from tools.review_replication import build_review, load_review, main, review_markdown, write_review


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False))


def seal(manifest):
    manifest.pop("manifest_id", None)
    manifest["manifest_id"] = _digest(manifest)
    return manifest


def record(spec, manifest, value=10, status="completed", strict=True):
    return {**spec, "manifest_id": manifest["manifest_id"], "status": status,
            "evaluation_count": 1, "best_x": spec["x0"], "best_f": value,
            "strict_benchmark_evaluation": strict, "warmup_severe_evaluations_used": 0 if strict else 1,
            "trace": [{"evaluation": 1, "status": "success", "x": spec["x0"], "f": value}],
            "problem_provenance": manifest["problem_definitions"][str(spec["problem"])],
            "engine_provenance": manifest["engines"][spec["version"]],
            "solver_metadata": manifest["solvers"][spec["solver"]]}


@pytest.fixture
def campaign(tmp_path):
    origin, target = tmp_path / "origin", tmp_path / "continuation"
    problem = get_problem(1)
    specs = [{"id": f"{version}-{solver}-{rep}", "problem": 1, "version": version,
              "solver": solver, "repetition": rep, "seed": rep, "budget": 500,
              "x0": list(problem.midpoint)} for version in ("8.5.0", "26.2.0")
             for solver in ("bobyqa", "sbplex") for rep in range(2)]
    original = seal({"runs": specs, "platform": "Darwin-arm64", "protocol": "pilot-overrides",
                     "requested_repetitions": 2, "diagnostics_policy": "reference-warmup",
                     "budget_override": 500, "master_seed": 2019, "code_sha256": {"a.py": "frozen"},
                     "engines": {"8.5.0": {"executable_sha256": "old"},
                                 "26.2.0": {"executable_sha256": "modern"}},
                     "solvers": {"bobyqa": {"implemented": True}, "sbplex": {"implemented": True}},
                     "problem_definitions": {"1": {"dimension": 4, "name": problem.name,
                         "objective_unit": problem.objective_unit,
                         "bounds": [list(pair) for pair in problem.bounds],
                         "parameter_names": [p.name for p in problem.parameters]}}})
    write(origin / "manifest.json", original)
    for spec, value, strict in ((specs[0], 10, True), (specs[1], 1, False)):
        write(origin / "runs" / (spec["id"] + ".json"), record(spec, original, value, strict=strict))
    write(origin / "runs" / (specs[2]["id"] + ".json"), record(specs[2], original, 5, "interrupted"))
    _, old_records, identity = read_origin(origin)
    new = copy.deepcopy(original)
    new["runs"] = specs[2:]
    new["platform"] = "Windows-AMD64"
    new["engines"]["8.5.0"]["executable_sha256"] = "windows-native"
    new["continuation"] = {"origin_manifest_id": original["manifest_id"], **identity,
                            "retained_terminal_runs": 2,
                            "origin_statuses": dict(Counter(r["status"] for r in old_records.values())),
                            "frozen_package_sha256": "source", "driver_sha256": "driver"}
    seal(new)
    write(target / "manifest.json", new)
    write(target / "runs" / (specs[2]["id"] + ".json"), record(specs[2], new, 7))
    write(target / "runs" / (specs[4]["id"] + ".json"), record(specs[4], new, 12))
    return origin, target, original, new


def test_review_cannot_replace_native_inputs(campaign, tmp_path):
    origin, _, original, _ = campaign
    inputs = tmp_path / "native-inputs"
    config, binary = inputs / "review-strict.json", inputs / "SolverBridge.exe"
    write(config, {"schema_version": 1})
    binary.write_bytes(b"original solver")
    original["native_solvers"] = {"config_path": str(config), "backends": {
        "bbo": {"files": {str(binary): "pinned"}}}}
    write(origin / "manifest.json", seal(original))
    for path in (origin / "runs").glob("*.json"):
        row = json.loads(path.read_text())
        row["manifest_id"] = original["manifest_id"]
        write(path, row)
    before = {path: path.read_bytes() for path in (config, binary)}
    with pytest.raises(ValueError):
        write_review(load_review(origin), inputs)
    assert all(path.read_bytes() == value for path, value in before.items())


def test_joined_records_keep_actual_manifests_and_full_denominators(campaign):
    origin, target, original, new = campaign
    dataset = load_review(origin, target)
    assert len(dataset["specs"]) == 8 and len(dataset["records"]) == 4
    assert dataset["status_counts"] == {"completed": 4, "pending": 4}
    assert dataset["records"][original["runs"][0]["id"]]["manifest_id"] == original["manifest_id"]
    assert dataset["records"][original["runs"][2]["id"]]["manifest_id"] == new["manifest_id"]
    report = build_review(dataset)
    assert report["partial"] and report["requested_runs"] == 8
    assert sum(row["requested"] for row in report["per_solver_best"]) == 8
    assert report["best_across_methods"][0]["winner"]["best_f"] == 7
    assert report["best_across_methods"][0]["winner"]["parameters"][0]["name"] == "orientation"
    assert report["engine_best_comparisons"][0]["percentage_change"] == pytest.approx(100 * 5 / 7)
    assert report["source_manifests"][new["manifest_id"]]["platform"] == "Windows-AMD64"
    assert build_review(dataset, include_diagnostic_runs=True)["best_across_methods"][0]["winner"]["best_f"] == 1


def test_origin_only_and_not_started_continuation_are_reviewable(campaign, tmp_path):
    origin, _, _, _ = campaign
    report = build_review(load_review(origin, tmp_path / "not-started"))
    assert report["status_counts"]["interrupted"] == 1
    assert report["status_counts"]["pending"] == 5
    assert report["best_across_methods"][1]["winner"] is None


def test_review_distinguishes_call_cap_from_early_solver_termination(campaign):
    origin, _, _, _ = campaign
    dataset = load_review(origin)
    winner = next(row for row in dataset["records"].values()
                  if row["status"] == "completed" and row["strict_benchmark_evaluation"])
    winner.update(solver_termination="terminated", solver_success=True)
    report = build_review(dataset)
    assert report["evaluation_budgets"] == {"1": [500]}
    selected = next(row["winner"] for row in report["per_solver_best"] if row["winner"])
    assert selected["solver_success"] is True
    text = review_markdown(report)
    assert "maximum call counts; solvers can terminate earlier" in text
    assert "| 1 | 500 |" in text and "1/500 | terminated" in text


def long_trace(campaign):
    origin, _, manifest, _ = campaign
    spec = manifest["runs"][0]
    path = origin / "runs" / (spec["id"] + ".json")
    row = json.loads(path.read_text())
    row["trace"] = [
        {"evaluation": index, "status": "success", "x": spec["x0"],
         "f": 10 if index == 321 else 11,
         "components": {"heating": 10 if index == 321 else 11},
         "strict_benchmark_evaluation": True,
         "input_sha256": "f" * 64,
         "diagnostics": {"severe_count": 0, "fatal_count": 0}}
        for index in range(1, 501)
    ]
    row["evaluation_count"] = 500
    write(path, row)
    return origin, path, row


def test_review_retains_only_validated_winning_observations_and_original_identity(campaign):
    from tools.replay_replication import strict_incumbents

    origin, path, row = long_trace(campaign)
    original = path.read_bytes()
    _, full, identity = read_origin(origin)
    _, compact, compact_identity = read_origin(origin, retain_traces=False)
    assert identity == compact_identity and path.read_bytes() == original
    assert len(full[row["id"]]["trace"]) == 500
    summarized = compact[row["id"]]
    assert summarized["evaluation_count"] == 500
    assert summarized["trace"] == [row["trace"][320]]
    assert summarized["trace_summary"] == {
        "validated_observations": 500, "retained_observations": 1,
        "strict_whole_trajectory": True,
    }
    dataset = load_review(origin)
    assert all(len(record["trace"]) <= 1 for record in dataset["records"].values())
    incumbent = strict_incumbents(dataset)[0]
    assert incumbent["f"] == 10 and incumbent["components"] == {"heating": 10}
    assert incumbent["input_sha256"] == "f" * 64


@pytest.mark.parametrize("contradiction", [
    {"strict_benchmark_evaluation": False},
    {"diagnostics": {"severe_count": 1, "fatal_count": 0}},
    {"diagnostics": {"severe_count": 0, "fatal_count": 1}},
    {"diagnostics": {"accepted_warmup_only": True}},
])
def test_trace_reduction_preserves_earlier_diagnostic_contradictions(campaign, contradiction):
    origin, path, row = long_trace(campaign)
    row["trace"][0].update(contradiction)
    # The aggregate flag and winning call look strict; the earlier call does not.
    assert row["strict_benchmark_evaluation"] and row["warmup_severe_evaluations_used"] == 0
    write(path, row)
    dataset = load_review(origin)
    summarized = dataset["records"][row["id"]]
    assert summarized["trace"][0]["strict_benchmark_evaluation"] is True
    assert summarized["strict_benchmark_evaluation"] is False
    assert summarized["trace_summary"]["strict_whole_trajectory"] is False
    assert all(group["winner"] is None for group in build_review(dataset)["per_solver_best"])


def test_trace_reduction_validates_observations_after_the_winner(campaign):
    origin, path, row = long_trace(campaign)
    row["trace"][-1]["evaluation"] = 999
    write(path, row)
    with pytest.raises(ValueError, match="Invalid checkpoint trace"):
        read_origin(origin, retain_traces=False)


@pytest.mark.parametrize("field,value", [
    ("budget_multiplier", 100),
    ("effective_budget_rule", "100*(dimension+1)*budget_multiplier"),
    ("paper_budget_rule", "1000*(dimension+1)"),
    ("native_solvers", {"config_sha256": "different native libraries"}),
])
def test_continuation_cannot_change_scientific_definition_metadata(campaign, field, value):
    origin, target, _, new = campaign
    new[field] = value
    for path in (target / "runs").glob("*.json"):
        path.unlink()
    write(target / "manifest.json", seal(new))
    with pytest.raises(ValueError, match="scientific definition differs"):
        load_review(origin, target)


@pytest.mark.parametrize("mutation", ["link", "source", "definitions", "schedule", "overlap", "counts"])
def test_join_rejects_wrong_lineage_and_scientific_inputs(campaign, mutation):
    origin, target, original, new = campaign
    if mutation == "link":
        new["continuation"]["origin_manifest_id"] = "another"
    elif mutation == "source":
        new["code_sha256"]["a.py"] = "changed"
    elif mutation == "definitions":
        new["problem_definitions"]["1"]["name"] = "changed"
    elif mutation == "schedule":
        new["runs"].reverse()
    elif mutation == "overlap":
        new["runs"].append(original["runs"][0])
    else:
        new["continuation"]["retained_terminal_runs"] = 100
    # Remove destination records so the manifest itself is the failed check.
    for path in (target / "runs").glob("*.json"):
        path.unlink()
    write(target / "manifest.json", seal(new))
    with pytest.raises(ValueError):
        load_review(origin, target)


def test_origin_checkpoint_modification_is_detected_by_continuation_link(campaign):
    origin, target, original, _ = campaign
    path = origin / "runs" / (original["runs"][0]["id"] + ".json")
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="hashes"):
        load_review(origin, target)


def test_malformed_checkpoints_are_rejected(campaign):
    origin, target, original, _ = campaign
    path = target / "runs" / (original["runs"][2]["id"] + ".json")
    row = json.loads(path.read_text())
    row["best_f"] = -99
    write(path, row)
    with pytest.raises(ValueError, match="incumbent"):
        load_review(origin, target)


def test_reports_and_joined_plots_are_separate_and_label_platforms(campaign, tmp_path):
    pytest.importorskip("matplotlib")
    origin, target, original, new = campaign
    before = (origin / "manifest.json").read_bytes()
    output = tmp_path / "review"
    result = write_review(load_review(origin, target), output)
    report = json.loads((output / "review-strict.json").read_text())
    assert report["partial"] and report["per_solver_best"][0]["requested"] == 2
    assert "orientation" in (output / "review-strict.md").read_text()
    svg = (output / "plots-strict/figure8-energyplus-8.5.0.svg").read_text()
    assert "Darwin-arm64" in svg and "Windows-AMD64" in svg
    assert "INCOMPLETE" in svg
    assert str(origin) not in svg and str(target) not in svg
    assert result["figures"]["scope"] == "PILOT / INCOMPLETE"
    assert (origin / "manifest.json").read_bytes() == before
    assert new["manifest_id"] in report["source_manifests"]
    with pytest.raises(ValueError, match="source experiment"):
        write_review(load_review(origin, target), origin)


def test_cli_writes_review_without_simulation(campaign, tmp_path, capsys):
    origin, target, _, _ = campaign
    main(["--origin", str(origin), "--continuation", str(target), "--output-dir", str(tmp_path / "out"),
          "--no-plots", "--include-diagnostic-runs"])
    result = json.loads(capsys.readouterr().out)
    assert result["json"].endswith("review-diagnostic.json")
    assert "figures" not in result


def test_status_only_never_creates_output(campaign, tmp_path, capsys):
    origin, target, _, _ = campaign
    main(["--origin", str(origin), "--continuation", str(target), "--status-only"])
    status = json.loads(capsys.readouterr().out)
    assert status["planned"] == 8 and status["terminal"] == 4
    assert status["strict_completed"] == 3
    assert status["excluded_non_strict_completed"] == 1
    assert not (tmp_path / "review").exists()


def test_missing_output_and_unmanifested_continuation_are_rejected(campaign, tmp_path):
    origin, _, _, _ = campaign
    with pytest.raises(SystemExit):
        main(["--origin", str(origin)])
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "stray.json").write_text("{}")
    with pytest.raises(ValueError, match="no manifest"):
        load_review(origin, invalid)


def test_parameter_metadata_drift_is_rejected(campaign):
    origin, target, _, _ = campaign
    dataset = load_review(origin, target)
    dataset["origin_manifest"]["problem_definitions"]["1"]["parameter_names"][0] = "wrong"
    with pytest.raises(ValueError, match="parameter metadata"):
        build_review(dataset)


@pytest.mark.parametrize("alias", ["report-symlink", "report-hardlink", "plot-directory", "plot-file"])
def test_review_rejects_output_aliases_before_touching_any_report(campaign, tmp_path, alias):
    origin, target, original, _ = campaign
    protected = origin / "runs" / (original["runs"][0]["id"] + ".json")
    before = protected.read_bytes()
    output = tmp_path / "alias-review"
    output.mkdir()
    try:
        if alias == "report-symlink":
            (output / "review-strict.json").symlink_to(protected)
        elif alias == "report-hardlink":
            (output / "review-strict.json").hardlink_to(protected)
        elif alias == "plot-directory":
            (output / "plots-strict").symlink_to(origin / "runs", target_is_directory=True)
        else:
            (output / "plots-strict").mkdir()
            (output / "plots-strict/figure8-energyplus-8.5.0.svg").symlink_to(protected)
    except OSError as error:
        pytest.skip(f"Filesystem alias creation unavailable: {error}")
    with pytest.raises(ValueError, match="symlink|hard-linked"):
        write_review(load_review(origin, target), output)
    assert protected.read_bytes() == before
    assert not (output / "review-strict.md").exists()


def test_review_rejects_frozen_source_and_can_refresh_regular_reports(campaign, tmp_path):
    origin, target, _, _ = campaign
    dataset = load_review(origin, target)
    with pytest.raises(ValueError, match="protected"):
        write_review(dataset, origin.parent / "source/generated")
    with pytest.raises(ValueError, match="protected"):
        write_review(dataset, origin.with_name(origin.name + "-source") / "generated")
    output = tmp_path / "ordinary-review"
    first = write_review(dataset, output, plots=False)
    second = write_review(dataset, output, plots=False)
    assert first == second
    assert json.loads((output / "review-strict.json").read_text())["requested_runs"] == 8


def test_review_rejects_root_alias_and_nested_manifest_input(campaign, tmp_path):
    origin, target, _, _ = campaign
    alias = tmp_path / "output-alias"
    try:
        alias.symlink_to(origin, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symlink creation unavailable: {error}")
    with pytest.raises(ValueError, match="symlink"):
        write_review(load_review(origin, target), alias)
    dataset = load_review(origin, target)
    dataset["protected_roots"].append(str(tmp_path / "input-models"))
    with pytest.raises(ValueError, match="protected"):
        write_review(dataset, tmp_path / "input-models/generated")


def test_project_result_tags_are_allowed_while_workflow_sources_remain_protected(campaign, tmp_path):
    origin, target, original, new = campaign
    project = tmp_path / "project"
    workflow = project / "replication"
    workflow.mkdir(parents=True)
    (workflow / "pipeline.py").write_text("# protected workflow input\n")
    # Origin-only metadata can record a local checkout without changing any result.
    original["project_root"] = str(project)
    seal(original)
    write(origin / "manifest.json", original)
    for path in (origin / "runs").glob("*.json"):
        row = json.loads(path.read_text())
        row["manifest_id"] = original["manifest_id"]
        write(path, row)
    dataset = load_review(origin)
    output = workflow / "results" / "new-tag"
    result = write_review(dataset, output, plots=False)
    assert result["json"] == str(output / "review-strict.json")
    with pytest.raises(ValueError, match="protected"):
        write_review(dataset, workflow)
    assert (workflow / "pipeline.py").read_text() == "# protected workflow input\n"
