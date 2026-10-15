# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Plot completed canonical-weather experiments with explicit failure denominators."""

import json
import math
from collections import Counter
from pathlib import Path

from .replication_solvers import SOLVER_ORDER

LABELS = {
    "direct": "DIRECT", "crs2": "CRS2", "sbplex": "Sbplex", "cma_es": "CMA-ES",
    "bobyqa": "PDFO BOBYQA", "pybobyqa": "Py-BOBYQA",
}
ACCEPTED = {"completed", "budget_exhausted"}
GROUPS = {"figure8": (1, 2, 3, 4, 5, 6, 8), "figure9": (9, 10, 13)}


def validate_output_tree(output_dir, *, protected_roots=()):
    """Reject input overlap and filesystem aliases before refreshing generated files."""
    requested = Path(output_dir).absolute()
    if requested.is_symlink():
        raise ValueError("Output directory must not be a symlink")
    output = requested.resolve()
    for protected in protected_roots:
        source = Path(protected).resolve()
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError("Output directory overlaps a protected source experiment or input")
    if output.exists():
        if not output.is_dir():
            raise ValueError("Output directory is not a directory")
        for path in output.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"Output tree contains a symlink: {path.name}")
            if path.is_file() and path.stat().st_nlink > 1:
                raise ValueError(f"Output tree contains a hard-linked file: {path.name}")
    return output


def strict_trajectory(row):
    """Require explicit trajectory evidence and reject contradictory call diagnostics."""
    return (row.get("strict_benchmark_evaluation") is True
            and row.get("warmup_severe_evaluations_used", 0) == 0
            and not any(item.get("strict_benchmark_evaluation") is False
                        or item.get("diagnostics", {}).get("accepted_warmup_only", False)
                        or item.get("diagnostics", {}).get("severe_count", 0)
                        or item.get("diagnostics", {}).get("fatal_count", 0)
                        for item in row.get("trace", [])))


def collect_boxplot_data(root, *, include_diagnostic_runs=False):
    """Select strict completed trajectories, or explicitly requested diagnostics.

    A valid winning point does not make a trajectory strict if earlier calls
    used warmup-error outputs. Missing strictness evidence is excluded too.
    """
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    specs = {row["id"]: row for row in manifest["runs"]}
    if len(specs) != len(manifest["runs"]):
        raise ValueError("Duplicate run IDs in the manifest")
    records = {}
    for path in (root / "runs").glob("*.json"):
        row = json.loads(path.read_text())
        if row.get("manifest_id") != manifest["manifest_id"] or row["id"] not in specs:
            raise ValueError(f"Run provenance does not match the experiment: {path.name}")
        spec = specs[row["id"]]
        if row["id"] in records or any(row.get(key) != value for key, value in spec.items()):
            raise ValueError(f"Run specification does not match the experiment: {path.name}")
        # Plotting needs completed-run summaries, not millions of call records.
        row["strict_benchmark_evaluation"] = strict_trajectory(row)
        for key in ("trace", "problem_provenance", "engine_provenance", "solver_metadata"):
            row.pop(key, None)
        records[row["id"]] = row
    return manifest, group_records(manifest, records, include_diagnostic_runs=include_diagnostic_runs)


def group_records(manifest, records, *, include_diagnostic_runs=False):
    """Group validated records against the complete planned experiment."""
    solvers = [name for name in SOLVER_ORDER if name in manifest["solvers"]
               and manifest["solvers"][name]["implemented"]]
    groups = []
    for number, problem in manifest["problem_definitions"].items():
        for version in manifest["engines"]:
            for solver in solvers:
                selected = [row for row in manifest["runs"] if row["problem"] == int(number)
                            and row["version"] == version and row["solver"] == solver]
                values, designs, statuses, terminations = [], [], Counter(), Counter()
                warmup_runs, warmup_evaluations = 0, 0
                excluded_non_strict, strict_completed = 0, 0
                for spec in selected:
                    row = records.get(spec["id"])
                    status = row["status"] if row else "pending"
                    statuses[status] += 1
                    if status in ACCEPTED:
                        used = row.get("warmup_severe_evaluations_used", 0)
                        strict = strict_trajectory(row)
                        strict_completed += strict
                        if not strict and not include_diagnostic_runs:
                            excluded_non_strict += 1
                            continue
                        if row.get("best_f") is None or not math.isfinite(row["best_f"]):
                            raise ValueError(f"Accepted run has no finite best objective: {spec['id']}")
                        values.append(row["best_f"])
                        designs.append(row["best_x"])
                        terminations[row.get("solver_result", {}).get("status", "unknown")] += 1
                        warmup_evaluations += used
                        warmup_runs += bool(used)
                groups.append({"problem": int(number), "version": version, "solver": solver,
                               "numerical_variant": problem.get("numerical_variant"),
                               "unit": problem["objective_unit"], "values": values,
                               "best_designs": designs, "accepted": len(values),
                               "requested": len(selected), "statuses": dict(statuses),
                               "strict_completed_runs": strict_completed,
                               "excluded_non_strict_completed_runs": excluded_non_strict,
                               "solver_terminations": dict(terminations),
                               "runs_using_warmup_severe_outputs": warmup_runs,
                               "warmup_severe_evaluations_used": warmup_evaluations})
    return groups


def plot_replication(root, *, output_dir=None, include_diagnostic_runs=False, dataset=None):
    """Write four Figure8/9-style views, uncapped, plus numerical summaries.

    Quartiles use NumPy's linear interpolation and whiskers1.5IQR. These are
    explicit plotting conventions; the study does not specify those details.
    Matching engine panels use the same objective range for each problem.
    """
    root = Path(root)
    destination = Path(output_dir) if output_dir else root / (
        "plots-diagnostic" if include_diagnostic_runs else "plots")
    protected = list(dataset["source_roots"].values()) if dataset is not None else [
        root / "manifest.json", root / "runs"]
    if dataset is not None:
        protected.extend(dataset.get("protected_roots", []))
    destination = validate_output_tree(destination, protected_roots=protected)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    destination.mkdir(parents=True, exist_ok=True)
    if dataset is None:
        manifest, groups = collect_boxplot_data(root, include_diagnostic_runs=include_diagnostic_runs)
    else:
        manifest = dataset["origin_manifest"]
        groups = group_records(manifest, dataset["records"],
                               include_diagnostic_runs=include_diagnostic_runs)
    solvers = [name for name in SOLVER_ORDER if name in manifest["solvers"]
               and manifest["solvers"][name]["implemented"]]
    lookup = {(row["problem"], row["version"], row["solver"]): row for row in groups}
    summaries = []
    for group in groups:
        stats = dict(group)
        stats.pop("best_designs")
        if group["values"]:
            quantiles = np.percentile(group["values"], [0, 25, 50, 75, 100])
            stats["statistics"] = dict(zip(("minimum", "q1", "median", "q3", "maximum"),
                                           map(float, quantiles), strict=True))
        else:
            stats["statistics"] = None
        summaries.append(stats)
    is_partial = any(row["statuses"].get(status, 0) for row in groups
                     for status in ("pending", "running", "interrupted"))
    scope = "PILOT" if manifest["protocol"] == "pilot-overrides" else "PAPER BUDGET"
    if is_partial:
        scope += " / INCOMPLETE"
    if dataset is not None and dataset.get("publication_preview"):
        scope += " / UNVALIDATED PREVIEW"
    policy = manifest.get("diagnostics_policy", "strict")
    selection = "diagnostic-completed-trajectories" if include_diagnostic_runs else "strict-completed-trajectories"
    selection_title = ("DIAGNOSTIC VIEW: warmup-error outputs may be used; NOT STRICT"
                       if include_diagnostic_runs else "STRICT VIEW: no warmup-error outputs used")
    budget_text = (f"{manifest['budget_override']} calls/run" if manifest.get("budget_override")
                   else "100(n+1) calls/run")
    outputs = []
    for group_name, numbers in GROUPS.items():
        numbers = [number for number in numbers if str(number) in manifest["problem_definitions"]]
        if not numbers:
            continue
        for version in manifest["engines"]:
            rows = math.ceil(len(numbers) / 2)
            figure, axes = plt.subplots(rows, 2, figsize=(14, 4.6 * rows), squeeze=False)
            for axis, number in zip(axes.flat, numbers):
                problem = manifest["problem_definitions"][str(number)]
                for position, solver in enumerate(solvers, 1):
                    data = lookup[(number, version, solver)]
                    if data["values"]:
                        artist = axis.boxplot([data["values"]], positions=[position], widths=0.55,
                            whis=1.5, patch_artist=True,
                            boxprops={"facecolor": "#8dbce6" if solver not in {"bobyqa", "pybobyqa"}
                                      else "#f4bb72", "edgecolor": "#2c3e50"},
                            medianprops={"color": "#b32d2e", "linewidth": 1.6},
                            whiskerprops={"linestyle": "--", "color": "#2c3e50"},
                            capprops={"color": "#2c3e50"},
                            flierprops={"marker": "+", "markeredgecolor": "#b32d2e"})
                        del artist
                all_values = [value for row in groups if row["problem"] == number
                              for value in row["values"]]
                visible_values = [value for row in groups if row["problem"] == number
                                  and row["version"] == version for value in row["values"]]
                if all_values:
                    lower, upper = min(all_values), max(all_values)
                    pad = max((upper - lower) * 0.1, abs(lower) * 0.002, 1e-6)
                    axis.set_ylim(lower - pad, upper + pad)
                else:
                    axis.set_yticks([])
                if not visible_values:
                    axis.text(0.5, 0.45, "No accepted completed runs yet",
                              transform=axis.transAxes, ha="center", color="#666666")
                labels = []
                for solver in solvers:
                    data = lookup[(number, version, solver)]
                    failed = data["statuses"].get("failed", 0)
                    labels.append(f"{LABELS.get(solver, solver)}\nruns: {data['accepted']}/{data['requested']}"
                                  + (f"; failed runs: {failed}" if failed else "")
                                  + (f"\nwarmup errors used: {data['runs_using_warmup_severe_outputs']} runs"
                                     if data['runs_using_warmup_severe_outputs'] else "")
                                  + (f"\nexcluded non-strict runs: {data['excluded_non_strict_completed_runs']}"
                                     if data['excluded_non_strict_completed_runs'] else ""))
                axis.set_xticks(range(1, len(solvers) + 1), labels, rotation=40, ha="right")
                axis.set_xlim(0.4, len(solvers) + 0.6)
                axis.tick_params(axis="x", labelsize=8)
                title = f"P{number}: {problem['name']} (n={problem['dimension']})"
                if problem.get("numerical_variant"):
                    title += f"\nNumerical variant: {problem['numerical_variant']}"
                axis.set_title(title, fontsize=11)
                axis.set_ylabel(problem["objective_unit"])
                axis.grid(axis="y", alpha=0.22)
            for axis in list(axes.flat)[len(numbers):]:
                axis.set_visible(False)
            lineage = ""
            if dataset is not None:
                lineage = "Sources: " + "; ".join(
                    f"{item.get('platform', 'unknown platform')} [{key[:12]}]"
                    for key, item in dataset["manifests"].items()) + "\n"
            figure.suptitle(f"EnergyPlus {version}: new seeded rerun (DIRECT uses midpoint)\n"
                            f"{lineage}"
                            f"{scope} - {manifest['requested_repetitions']} runs/solver; {budget_text}\n"
                            f"{selection_title}\nExperiment policy: {policy}",
                            fontsize=14)
            footer = ("Runs: included/planned repetitions; n: decision variables. Failures excluded. "
                      "Blue: study methods; orange: added methods.\n"
                      "Canonical benchmark weather. Completed-trajectory selection can bias distributions. "
                      "Boxes Q1-Q3, red median, whiskers 1.5 IQR.\n"
                      "Study: Waibel, Wortmann, Evins, and Carmeliet (2019).")
            figure.text(0.5, 0.015, footer, ha="center", fontsize=8)
            figure.tight_layout(rect=(0, 0.055, 1, 0.94))
            for suffix in ("png", "svg"):
                path = destination / f"{group_name}-energyplus-{version}.{suffix}"
                figure.savefig(path, dpi=180)
                outputs.append(str(path))
            plt.close(figure)
    registry = manifest.get("solver_registry", list(manifest["solvers"].values()))
    report = {"schema_version": 1, "manifest_id": manifest["manifest_id"],
              "protocol": manifest["protocol"], "partial": is_partial,
              "diagnostics_policy": policy,
              "result_selection": selection,
              "baseline_for_engine_percentage": "8.5.0", "groups": summaries,
              "skipped_original_methods": [metadata for metadata in registry
                                           if not metadata["implemented"]],
              "engine_median_comparisons": []}
    summary_lookup = {(row["problem"], row["version"], row["solver"]): row for row in summaries}
    if {"8.5.0", "26.2.0"} <= set(manifest["engines"]):
        for number in map(int, manifest["problem_definitions"]):
            for solver in solvers:
                old = summary_lookup[(number, "8.5.0", solver)]
                new = summary_lookup[(number, "26.2.0", solver)]
                a = old["statistics"]["median"] if old["statistics"] else None
                b = new["statistics"]["median"] if new["statistics"] else None
                delta = b - a if a is not None and b is not None else None
                report["engine_median_comparisons"].append({"problem": number, "solver": solver,
                    "median_8.5": a, "median_26.2": b, "signed_difference": delta,
                    "percentage_change": 100 * delta / abs(a) if delta is not None and a else None,
                    "accepted_8.5": old["accepted"], "accepted_26.2": new["accepted"],
                    "caution": "Descriptive completed-run medians; failures can cause survivor bias."})
    if dataset is not None:
        report["source_manifests"] = {key: {"platform": value.get("platform")}
                                      for key, value in dataset["manifests"].items()}
    path = destination / "boxplot-summary.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return {"plots": outputs, "summary": str(path), "scope": scope}
