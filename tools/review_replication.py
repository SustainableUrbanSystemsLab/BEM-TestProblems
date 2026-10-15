# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Review origin and continuation checkpoints without relabeling their provenance."""

import argparse
import json
from collections import Counter
from pathlib import Path

from bem_testproblems.problems import get_problem
from bem_testproblems.replication_plots import (
    ACCEPTED,
    group_records,
    plot_replication,
    strict_trajectory,
    validate_output_tree,
)

if __package__:
    from .continue_replication import TERMINAL, read_origin
else:
    from continue_replication import TERMINAL, read_origin


def load_review(origin, continuation=None):
    """Validate linked evidence; retain actual manifests and full origin denominators."""
    original, records, identity = read_origin(origin)
    manifests = {original["manifest_id"]: original}
    roots = {original["manifest_id"]: str(Path(origin).resolve())}
    if continuation is not None:
        path = Path(continuation)
        if (path / "manifest.json").is_file():
            target, newer, _ = read_origin(path)
            link = target.get("continuation", {})
            if (link.get("origin_manifest_id") != original["manifest_id"]
                    or any(link.get(key) != value for key, value in identity.items())):
                raise ValueError("Continuation origin linkage or checkpoint hashes differ")
            for key in ("problem_definitions", "solvers", "code_sha256", "diagnostics_policy",
                        "protocol", "requested_repetitions", "budget_override", "master_seed"):
                if target.get(key) != original.get(key):
                    raise ValueError(f"Continuation scientific definition differs: {key}")
            terminal = {key for key, row in records.items() if row["status"] in TERMINAL}
            expected = [spec for spec in original["runs"] if spec["id"] not in terminal]
            if target["runs"] != expected or terminal.intersection(newer):
                raise ValueError("Continuation schedule differs from unfinished origin runs")
            if (link.get("retained_terminal_runs") != len(terminal)
                    or link.get("origin_statuses") != dict(Counter(
                        row["status"] for row in records.values()))):
                raise ValueError("Continuation origin status counts differ")
            records = {key: row for key, row in records.items() if key in terminal}
            records.update(newer)
            manifests[target["manifest_id"]] = target
            roots[target["manifest_id"]] = str(path.resolve())
        elif path.exists() and any(path.iterdir()):
            raise ValueError("Continuation directory has no manifest")
    counts = Counter(row["status"] for row in records.values())
    counts["pending"] = len(original["runs"]) - len(records)
    protected = list(roots.values())
    # The handoff's sibling source tree is immutable; manifest paths identify
    # additional local inputs on the machine that produced each segment.
    protected.extend(str(Path(root).parent / "source") for root in roots.values())
    protected.extend(str(Path(root).with_name(Path(root).name + "-source"))
                     for root in roots.values())
    for manifest in manifests.values():
        if manifest.get("weather_directory") and Path(manifest["weather_directory"]).is_absolute():
            protected.append(manifest["weather_directory"])
        for engine in manifest["engines"].values():
            if engine.get("executable") and Path(engine["executable"]).is_absolute():
                protected.append(str(Path(engine["executable"]).parent))
        if manifest.get("project_root") and Path(manifest["project_root"]).is_absolute():
            project = Path(manifest["project_root"])
            protected.extend(str(project / relative) for relative in (
                "src", "tools", "reference", "assets", "constraints",
                "tests", "docs", ".github", ".reference-cache", ".tools", ".venv"))
            workflow = project / "replication"
            protected.extend(str(workflow / name) for name in (
                "pipeline.py", "continuation.json", "README.md", "results/README.md"))
            if workflow.is_dir():
                protected.extend(str(path) for path in workflow.iterdir() if path.name != "results")
    dataset = {"origin_manifest": original, "manifests": manifests,
               "specs": original["runs"], "records": records, "source_roots": roots,
               "status_counts": dict(counts), "protected_roots": protected}
    dataset["groups"] = group_records(original, records)
    return dataset


def _winner(record, manifest):
    problem = get_problem(record["problem"])
    definition = manifest["problem_definitions"][str(problem.id)]
    names = [parameter.name for parameter in problem.parameters]
    if (definition["parameter_names"] != names
            or definition["bounds"] != [list(pair) for pair in problem.bounds]):
        raise ValueError(f"Current parameter metadata differs from frozen P{problem.id}")
    problem.validate(record["best_x"])
    result = {key: record[key] for key in (
        "problem", "version", "solver", "manifest_id", "seed", "budget", "evaluation_count",
        "best_x", "best_f", "status", "repetition", "x0")}
    result["run_id"] = record["id"]
    result["objective_unit"] = definition["objective_unit"]
    result["dimension"] = problem.dimension
    result["strict_benchmark_evaluation"] = strict_trajectory(record)
    result["warmup_severe_evaluations_used"] = record.get("warmup_severe_evaluations_used", 0)
    result["parameters"] = [
        {"name": parameter.name, "symbol": parameter.paper_symbol, "unit": parameter.unit,
         "lower": parameter.lower, "upper": parameter.upper, "value": value}
        for parameter, value in zip(problem.parameters, record["best_x"], strict=True)]
    result["fixed_parameters"] = dict(problem.fixed_parameters)
    return result


def review_status(dataset):
    """Small read-only status view suitable for a running campaign."""
    counts = dataset["status_counts"]
    return {"planned": len(dataset["specs"]),
            "terminal": sum(counts.get(key, 0) for key in TERMINAL),
            "statuses": counts,
            "strict_completed": sum(row["strict_completed_runs"] for row in dataset["groups"]),
            "excluded_non_strict_completed": sum(row["excluded_non_strict_completed_runs"]
                                                  for row in dataset["groups"]),
            "source_manifest_ids": list(dataset["manifests"])}


def build_review(dataset, *, include_diagnostic_runs=False):
    """Summarize whole-trajectory selection, including every pending combination."""
    manifest, records = dataset["origin_manifest"], dataset["records"]
    groups = group_records(manifest, records, include_diagnostic_runs=include_diagnostic_runs)
    per_solver = []
    for group in groups:
        candidates = [row for row in records.values()
                      if row["problem"] == group["problem"] and row["version"] == group["version"]
                      and row["solver"] == group["solver"] and row["status"] in ACCEPTED
                      and (include_diagnostic_runs or strict_trajectory(row))]
        winner = min(candidates, key=lambda row: (row["best_f"], row["id"]), default=None)
        per_solver.append({"problem": group["problem"], "version": group["version"],
                           "solver": group["solver"], "requested": group["requested"],
                           "included": group["accepted"], "statuses": group["statuses"],
                           "excluded_non_strict": group["excluded_non_strict_completed_runs"],
                           "winner": _winner(winner, manifest) if winner else None})
    best = []
    for number in manifest["problem_definitions"]:
        for version in manifest["engines"]:
            winners = [row["winner"] for row in per_solver if row["problem"] == int(number)
                       and row["version"] == version and row["winner"] is not None]
            best.append({"problem": int(number), "version": version,
                         "winner": min(winners, key=lambda row: (row["best_f"], row["run_id"]),
                                       default=None)})
    comparisons = []
    lookup = {(row["problem"], row["version"]): row["winner"] for row in best}
    for number in map(int, manifest["problem_definitions"]):
        old, new = lookup.get((number, "8.5.0")), lookup.get((number, "26.2.0"))
        if old and new:
            delta = new["best_f"] - old["best_f"]
            comparisons.append({"problem": number, "signed_difference": delta,
                                "percentage_change": 100 * delta / abs(old["best_f"])
                                if old["best_f"] else None,
                                "baseline": "best included EnergyPlus 8.5 objective",
                                "different_designs_possible": True})
    issues = []
    for row in records.values():
        if row["status"] not in ACCEPTED or not strict_trajectory(row):
            issues.append({"run_id": row["id"], "manifest_id": row["manifest_id"],
                           "problem": row["problem"], "version": row["version"],
                           "solver": row["solver"], "status": row["status"],
                           "evaluation_count": row["evaluation_count"],
                           "warmup_severe_evaluations_used": row.get("warmup_severe_evaluations_used", 0),
                           "error_type": (row.get("error") or {}).get("type")})
    partial = any(dataset["status_counts"].get(key, 0)
                  for key in ("pending", "running", "interrupted"))
    return {"schema_version": 1, "origin_manifest_id": manifest["manifest_id"],
            "source_manifests": {key: {"platform": value.get("platform"),
                                         "engines": {version: {field: engine.get(field) for field in
                                             ("executable_sha256", "version_output", "supporting_sha256")}
                                             for version, engine in value["engines"].items()}}
                                 for key, value in dataset["manifests"].items()},
            "protocol": manifest["protocol"], "diagnostics_policy": manifest["diagnostics_policy"],
            "selection": "diagnostic-completed-trajectories" if include_diagnostic_runs
                         else "strict-completed-trajectories",
            "partial": partial, "requested_runs": len(dataset["specs"]),
            "status_counts": dataset["status_counts"], "run_issues": issues,
            "per_solver_best": per_solver,
            "best_across_methods": best, "engine_best_comparisons": comparisons,
            "caution": "New seeded rerun; exact historical trajectories unavailable. "
                       "Completed-trajectory selection can bias distributions."}


def review_markdown(report):
    """Readable status, winning objectives, and complete physical designs."""
    lines = ["# Replication review", "", f"**{'INCOMPLETE' if report['partial'] else 'ALL RUNS TERMINAL'}**; "
             f"{report['selection']}; {report['protocol']}.", "", report["caution"], "",
             f"Planned runs: {report['requested_runs']}. Statuses: `{json.dumps(report['status_counts'])}`.", "",
             "Severe means EnergyPlus reported a serious simulation problem; Fatal means it stopped.", "",
             "| Problem | EnergyPlus | Solver | Included/planned | Best objective |", "|---|---|---|---:|---:|"]
    for row in report["per_solver_best"]:
        winner = row["winner"]
        value = f"{winner['best_f']:.12g}" if winner else "—"
        lines.append(f"| {row['problem']} | {row['version']} | {row['solver']} | "
                     f"{row['included']}/{row['requested']} | {value} |")
    lines.extend(["", "## Runs requiring attention", "",
                  "Interrupted runs remain unfinished. Warmup-error trajectories are excluded from strict results.", "",
                  "| Run | Actual manifest | Status | Calls | Warmup-error calls | Error type |",
                  "|---|---|---|---:|---:|---|"])
    for row in report["run_issues"]:
        lines.append(f"| {row['run_id']} | {row['manifest_id']} | {row['status']} | "
                     f"{row['evaluation_count']} | {row['warmup_severe_evaluations_used']} | "
                     f"{row['error_type'] or '—'} |")
    for number, version in dict.fromkeys((row["problem"], row["version"])
                                         for row in report["per_solver_best"]):
        selected = [row for row in report["per_solver_best"]
                    if row["problem"] == number and row["version"] == version]
        available = next((row["winner"] for row in selected if row["winner"]), None)
        if available is None:
            continue
        labels = [f"{parameter['symbol']}: {parameter['name']} ({parameter['unit']})"
                  for parameter in available["parameters"]]
        lines.extend(["", f"### P{number}, EnergyPlus {version}: designs by solver", "",
                      "| Solver | " + " | ".join(labels) + " |",
                      "|---|" + "---:|" * len(labels)])
        for row in selected:
            values = [f"{parameter['value']:.12g}" for parameter in row["winner"]["parameters"]] \
                     if row["winner"] else ["—"] * len(labels)
            lines.append("| " + row["solver"] + " | " + " | ".join(values) + " |")
    for row in report["best_across_methods"]:
        winner = row["winner"]
        lines.extend(["", f"## P{row['problem']}, EnergyPlus {row['version']}", ""])
        if winner is None:
            lines.append("No included completed run.")
            continue
        lines.extend([f"Variables: **n = {winner['dimension']}**. Best method: **{winner['solver']}**; objective: **{winner['best_f']:.12g} "
                      f"{winner['objective_unit']}**.", "",
                      f"Run `{winner['run_id']}`; actual manifest `{winner['manifest_id']}`; "
                      f"seed {winner['seed']}; calls {winner['evaluation_count']}/{winner['budget']}.", "",
                      "| Symbol | Parameter | Value | Unit |", "|---|---|---:|---|"])
        for parameter in winner["parameters"]:
            lines.append(f"| {parameter['symbol']} | {parameter['name']} | {parameter['value']:.12g} | "
                         f"{parameter['unit']} |")
        if winner["fixed_parameters"]:
            lines.extend(["", "Fixed parameters: `" + json.dumps(winner["fixed_parameters"]) + "`."])
    lines.extend(["", "## Best-objective changes between engines", "",
                  "Different winning designs can contribute to these changes.", "",
                  "| Problem | 26.2 − 8.5 | Change relative to 8.5 |", "|---|---:|---:|"])
    for row in report["engine_best_comparisons"]:
        percent = f"{row['percentage_change']:+.6g}%" if row["percentage_change"] is not None else "undefined"
        lines.append(f"| {row['problem']} | {row['signed_difference']:+.12g} | {percent} |")
    return "\n".join(lines) + "\n"


def write_review(dataset, output_dir, *, include_diagnostic_runs=False, plots=True):
    protected = list(dataset["source_roots"].values()) + dataset.get("protected_roots", [])
    output = validate_output_tree(output_dir, protected_roots=protected)
    output.mkdir(parents=True, exist_ok=True)
    report = build_review(dataset, include_diagnostic_runs=include_diagnostic_runs)
    label = "diagnostic" if include_diagnostic_runs else "strict"
    json_path, md_path = output / f"review-{label}.json", output / f"review-{label}.md"
    json_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    md_path.write_text(review_markdown(report), encoding="utf-8")
    result = {"json": str(json_path), "markdown": str(md_path)}
    if plots:
        result["figures"] = plot_replication(".", output_dir=output / f"plots-{label}", dataset=dataset,
                                            include_diagnostic_runs=include_diagnostic_runs)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", type=Path, required=True)
    parser.add_argument("--continuation", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--status-only", action="store_true")
    parser.add_argument("--include-diagnostic-runs", action="store_true")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args(argv)
    dataset = load_review(args.origin, args.continuation)
    if args.status_only:
        print(json.dumps(review_status(dataset), indent=2))
        return
    if args.output_dir is None:
        parser.error("--output-dir is required unless --status-only is selected")
    print(json.dumps(write_review(dataset, args.output_dir,
                                include_diagnostic_runs=args.include_diagnostic_runs,
                                plots=not args.no_plots), indent=2))


if __name__ == "__main__":
    main()
