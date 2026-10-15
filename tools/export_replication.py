# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Export an allowlist of computed results; keep raw/private evidence local."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

if __package__:
    from . import replay_replication as replay
else:
    import replay_replication as replay

NOTICE_FILES = ("BEOBenchmark-LICENSE.txt", "BEOBenchmark-MODEL-NOTICES.txt")
PREVIEW_STATUS = "UNVALIDATED PARTIAL PREVIEW"
COMPLETE_STATUS = "COMPLETE CAMPAIGN; AVAILABLE STRICT INCUMBENTS REPLAYED"
SELECTION = (
    "Only completed or budget-exhausted whole trajectories with explicit strict "
    "diagnostic evidence; failed and non-strict trajectories excluded."
)
LITERATURE = [
    {
        "authors": "Waibel, Wortmann, Evins, and Carmeliet",
        "year": 2019,
        "doi": "10.1016/j.enbuild.2019.01.048",
    }
]
LIMITATIONS = (
    "New seeded optimization experiment. Publication equivalence is not claimed. "
    "Failed or non-strict trajectories remain in the status denominators. "
    "Groups without strict completed runs have no reported incumbent."
)


def _token(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.+()-]+", value):
        raise ValueError("Unsafe public provenance token")
    return value


def _hash_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Invalid SHA-256 identity")
    return value


def _hashes(values):
    return {_token(name): _hash_value(value) for name, value in values.items()}


def _public_provenance(dataset):
    """Allowlist scientific identities; discard paths, hostnames, and raw messages."""
    result = []
    for identifier, manifest in sorted(dataset["manifests"].items()):
        dependencies = {}
        for name, value in manifest.get("dependency_provenance", {}).items():
            dependencies[_token(name)] = {
                key: _token(value[key]) if value.get(key) is not None else None
                for key in ("distribution_version", "runtime_version")
            }
        recorded_platform = manifest.get("platform", "")
        safe_platform = (
            recorded_platform
            if re.fullmatch(
                r"(?:Darwin|Windows|Linux)-(?:arm64|aarch64|AMD64|x86_64)", recorded_platform
            )
            else "unspecified"
        )
        runtime = manifest.get("execution_runtime")
        python = (
            None
            if runtime is None
            else {
                "version": _token(runtime["python_version"].split()[0]),
                "implementation": {"cpython": "CPython", "pypy": "PyPy"}.get(
                    runtime["python_implementation"], _token(runtime["python_implementation"])
                ),
                "executable_sha256": _hash_value(runtime["python_executable_sha256"]),
            }
        )
        result.append(
            {
                "manifest_id": _hash_value(identifier),
                "platform": safe_platform,
                "python": python,
                "engines": {
                    _token(version): {
                        "executable_sha256": _hash_value(value["executable_sha256"]),
                        "supporting_sha256": _hashes(value.get("supporting_sha256", {})),
                    }
                    for version, value in manifest["engines"].items()
                },
                "code_sha256": _hashes(manifest["code_sha256"]),
                "dependencies": dependencies,
                "problem_inputs": {
                    str(number): {
                        "models": {
                            _token(version): {
                                key: _hash_value(value)
                                for key, value in model.items()
                                if key.endswith("_sha256")
                            }
                            for version, model in definition.get("models", {}).items()
                        },
                        "weather_sha256": _hash_value(definition["weather"]["sha256"])
                        if definition.get("weather", {}).get("sha256")
                        else None,
                    }
                    for number, definition in manifest["problem_definitions"].items()
                },
            }
        )
    return result


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Nonfinite or invalid computed result")
    return value


def _public_best(row):
    from bem_testproblems import get_problem

    definition = get_problem(row["problem"])
    return {
        "problem": int(row["problem"]),
        "version": _token(row["version"]),
        "solver": _token(row["solver"]),
        "run_id": _token(row["run_id"]),
        "manifest_id": _hash_value(row["manifest_id"]),
        "x": [_number(x) for x in row["best_x"]],
        "f": _number(row["best_f"]),
        "seed": row["seed"],
        "budget": row["budget"],
        "repetition": row["repetition"],
        "evaluation_count": row["evaluation_count"],
        "x0": [_number(x) for x in row["x0"]],
        "dimension": definition.dimension,
        "objective_unit": definition.objective_unit,
        "parameter_names": [p.name for p in definition.parameters],
        "parameter_symbols": [p.paper_symbol for p in definition.parameters],
        "parameter_units": [p.unit for p in definition.parameters],
        "bounds": [list(pair) for pair in definition.bounds],
    }


def _solver_protocol(name):
    from bem_testproblems.replication_solvers import solver_metadata

    metadata = solver_metadata(name)
    return {key: metadata[key] for key in ("dependency", "settings", "paper_method", "implemented")}


def _public_experiment(dataset):
    """Keep the complete numerical experiment recipe while discarding local runtime paths."""
    manifest = dataset["origin_manifest"]
    solvers = {}
    for name, recorded in manifest["solvers"].items():
        expected = _solver_protocol(name)
        if any(recorded.get(key) != value for key, value in expected.items()):
            raise ValueError("Frozen solver settings differ from the authoritative adapter")
        solvers[name] = expected
    return {
        "protocol": manifest["protocol"],
        "master_seed": manifest["master_seed"],
        "requested_repetitions": manifest["requested_repetitions"],
        "budget_override": manifest["budget_override"],
        "budget_rule": "100*(dimension+1)",
        "diagnostics_policy": manifest["diagnostics_policy"],
        "schedule": manifest["schedule"],
        "start_policy": "paired-uniform-physical-box-direct-midpoint",
        "numerical_variants": {
            str(number): definition.get("numerical_variant")
            for number, definition in manifest["problem_definitions"].items()
        },
        "solvers": solvers,
        "runs": [
            {key: spec[key] for key in replay.continuation.SPEC_FIELDS} for spec in dataset["specs"]
        ],
    }


def _public_group(row):
    result = {
        "problem": int(row["problem"]),
        "version": _token(row["version"]),
        "winner": _public_best(row["winner"]) if row["winner"] is not None else None,
    }
    for name in ("solver",):
        if name in row:
            result[name] = _token(row[name])
    for name in ("requested", "included", "excluded_non_strict"):
        if name in row:
            result[name] = int(row[name])
    if "statuses" in row:
        result["statuses"] = {_token(name): int(value) for name, value in row["statuses"].items()}
    return result


def _plot_dataset(dataset, provenance):
    """Give the renderer only canonical labels and sanitized source labels."""
    from bem_testproblems import get_problem

    original = dataset["origin_manifest"]
    definitions = {}
    for number, identity in original["problem_definitions"].items():
        problem = get_problem(number, numerical_variant=identity.get("numerical_variant"))
        definitions[number] = {
            "name": problem.name,
            "dimension": problem.dimension,
            "objective_unit": problem.objective_unit,
        }
        if problem.numerical_variant:
            definitions[number]["numerical_variant"] = problem.numerical_variant
    if original["protocol"] not in {"pilot-overrides", "paper-start-and-budget-protocol"}:
        raise ValueError("Unknown public experiment protocol")
    if original["diagnostics_policy"] not in {"strict", "reference-warmup"}:
        raise ValueError("Unknown public diagnostic policy")
    manifest = {
        key: original[key]
        for key in (
            "manifest_id",
            "protocol",
            "diagnostics_policy",
            "requested_repetitions",
            "budget_override",
            "runs",
        )
    }
    manifest.update(
        problem_definitions=definitions,
        engines={_token(version): {} for version in original["engines"]},
        solvers={
            _token(name): {"implemented": bool(value["implemented"])}
            for name, value in original["solvers"].items()
        },
    )
    return {
        **dataset,
        "origin_manifest": manifest,
        "manifests": {item["manifest_id"]: {"platform": item["platform"]} for item in provenance},
    }


def validated_replay(dataset, replay_dir):
    """Recheck comparisons and retained diagnostic hashes for the current winners."""
    if replay_dir is None:
        raise ValueError("Validated export requires --replay-dir")
    directory = Path(replay_dir).expanduser().resolve()
    plan = replay.continuation._read(directory / "replay-plan.json")[0]
    summary = replay.continuation._read(directory / "replay-summary.json")[0]
    incumbents = replay.strict_incumbents(dataset)
    selection = replay.continuation._digest(incumbents)
    if (
        plan.get("plan_id")
        != replay.continuation._digest(
            {key: value for key, value in plan.items() if key != "plan_id"}
        )
        or plan.get("selection_digest") != selection
        or plan.get("incumbents") != incumbents
        or plan.get("origin_manifest_id") != dataset["origin_manifest"]["manifest_id"]
        or plan.get("source_manifest_ids") != sorted(dataset["manifests"])
        or plan.get("code_sha256") != dataset["origin_manifest"]["code_sha256"]
        or plan.get("problem_definitions") != dataset["origin_manifest"]["problem_definitions"]
        or summary.get("selection_digest") != selection
        or summary.get("plan_id") != plan["plan_id"]
        or summary.get("source_manifest_ids") != sorted(dataset["manifests"])
        or summary.get("complete") is not True
        or summary.get("passed") is not True
        or len(summary.get("items", [])) != len(incumbents)
    ):
        raise ValueError("Passing replay does not match the current full-precision incumbents")
    expected = {(item["problem"], item["version"]): item for item in incumbents}
    seen, public = set(), []
    for item in summary["items"]:
        key = (item["problem"], item["version"])
        if key not in expected or key in seen:
            raise ValueError("Replay contains an unknown or duplicate incumbent")
        seen.add(key)
        original = expected[key]
        if (
            item.get("passed") is not True
            or item.get("run_id") != original["run_id"]
            or item.get("manifest_id") != original["manifest_id"]
            or item.get("severe_count") != 0
            or item.get("fatal_count") != 0
            or item.get("completed_successfully") is not True
            or item.get("input_sha256") != original["input_sha256"]
            or not replay.compare_numbers(original["f"], item.get("actual_f"))["passed"]
            or set(item.get("actual_components", {})) != set(original["components"])
            or any(
                not replay.compare_numbers(value, item["actual_components"].get(name))["passed"]
                for name, value in original["components"].items()
            )
        ):
            raise ValueError("Replay is not a strict matching simulator evaluation")
        relative = Path(item["evidence_directory"])
        evidence = (directory / relative).resolve()
        if relative.is_absolute() or not evidence.is_relative_to(directory):
            raise ValueError("Replay evidence escapes the retained replay directory")
        for name in ("eplusout.err", "eplusout.end", "run.json"):
            if replay._hash(evidence / name) != item.get("diagnostic_sha256", {}).get(name):
                raise ValueError("Retained replay evidence changed")
        engine = plan["engines"][item["version"]]
        definition = plan["problem_definitions"][str(item["problem"])]
        metadata = replay.continuation._read(evidence / "run.json")[0]
        staged = evidence / ("input.idf" if item["version"] == "8.5.0" else "input.epJSON")
        version_match = re.search(
            r"\bVersion[\s,:]+(\d+\.\d+(?:\.\d+)?)",
            item.get("engine", {}).get("version_output", ""),
            re.I,
        )
        if (
            any(item.get("engine", {}).get(key) != value for key, value in engine.items())
            or metadata.get("status") != "success"
            or metadata.get("returncode") != 0
            or metadata.get("version") != item["version"]
            or not version_match
            or version_match[1] != item["version"]
            or metadata.get("version_output") != item["engine"]["version_output"]
            or metadata.get("executable") != engine["executable"]
            or metadata.get("executable_sha256") != engine["executable_sha256"]
            or metadata.get("input_sha256") != original["input_sha256"]
            or not staged.is_file()
            or replay._hash(staged) != original["input_sha256"]
            or metadata.get("weather_sha256") != definition["weather"]["sha256"]
            or ("-D" in metadata.get("command", []))
            != (definition["weather"]["mode"] == "embedded-design-day")
            or item.get("model") != definition["models"][item["version"]]
            or item.get("weather") != definition["weather"]
        ):
            raise ValueError("Replay execution/input provenance differs from the sealed plan")
        errors = (evidence / "eplusout.err").read_text(errors="replace")
        if re.search(
            r"\*\*\s*(Severe|Fatal)\s*\*\*", errors, re.I
        ) or "EnergyPlus Completed Successfully" not in (evidence / "eplusout.end").read_text(
            errors="replace"
        ):
            raise ValueError("Retained diagnostics do not establish strict success")
        public.append(
            {
                "problem": key[0],
                "version": key[1],
                "run_id": original["run_id"],
                "manifest_id": original["manifest_id"],
                "passed": True,
                "severe_count": 0,
                "fatal_count": 0,
                "completed_successfully": True,
                "input_sha256": _hash_value(item["input_sha256"]),
                "x": original["x"],
                "actual_f": _number(item["actual_f"]),
                "objective_comparison": replay.compare_numbers(original["f"], item["actual_f"]),
                "actual_components": {
                    _token(name): _number(value)
                    for name, value in item["actual_components"].items()
                },
                "expected_components": original["components"],
                "component_comparisons": {
                    name: replay.compare_numbers(value, item["actual_components"][name])
                    for name, value in original["components"].items()
                },
                "engine_executable_sha256": _hash_value(item["engine"]["executable_sha256"]),
                "source_engine_executable_sha256": _hash_value(original["source_engine_sha256"]),
                "replay_scope": "same-native-binary"
                if item["engine"]["executable_sha256"] == original["source_engine_sha256"]
                else "same-version-different-native-build",
                "diagnostic_sha256": _hashes(item["diagnostic_sha256"]),
            }
        )
    return {
        "plan_id": _hash_value(plan["plan_id"]),
        "selection_digest": selection,
        "rtol": replay.RTOL,
        "atol": replay.ATOL,
        "passed": True,
        "items": public,
    }


def export_results(
    dataset,
    *,
    origin,
    continuation_root=None,
    output_dir,
    replay_dir=None,
    partial_preview=False,
    frozen_source=None,
    project_root=None,
):
    """Create a fresh public result package without copying arbitrary source files."""
    review = replay._review_module().build_review(dataset)
    statuses = dataset["status_counts"]
    incomplete = any(statuses.get(name, 0) for name in ("pending", "running", "interrupted"))
    if incomplete and not partial_preview:
        raise ValueError("Campaign is incomplete; use --partial-preview for a labeled preview")
    validation = None if partial_preview else validated_replay(dataset, replay_dir)
    source_roots = list(dataset["source_roots"].values())
    destination = replay.safe_destination(
        output_dir,
        origin=origin,
        continuation_root=continuation_root,
        frozen_source=frozen_source,
        project_root=project_root or Path(__file__).resolve().parents[1],
        extra_inputs=source_roots
        + list(dataset.get("protected_roots", []))
        + ([replay_dir] if replay_dir else []),
    )
    public = {
        "schema_version": 1,
        "status": PREVIEW_STATUS if partial_preview else COMPLETE_STATUS,
        "partial_preview": bool(partial_preview),
        "campaign_complete": not incomplete,
        "planned_runs": len(dataset["specs"]),
        "status_counts": {_token(key): int(value) for key, value in statuses.items()},
        "origin_manifest_id": _hash_value(dataset["origin_manifest"]["manifest_id"]),
        "provenance": _public_provenance(dataset),
        "experiment": _public_experiment(dataset),
        "best_per_solver": [_public_group(row) for row in review["per_solver_best"]],
        "best_across_methods": [_public_group(row) for row in review["best_across_methods"]],
        "replay": validation,
        "selection": SELECTION,
        "literature": LITERATURE,
        "limitations": LIMITATIONS,
    }
    # Fail validation before creating output. No raw source manifest is serialized.
    json.dumps(public, allow_nan=False)
    _verify_public_schema(public)
    destination.mkdir(parents=True, exist_ok=False)
    replay._write(destination / "results.json", public)
    from bem_testproblems.replication_plots import plot_replication

    plotting = _plot_dataset(dataset, public["provenance"])
    plotting["publication_preview"] = bool(partial_preview)
    plot_replication(origin, output_dir=destination / "plots", dataset=plotting)
    # The plot summary is regenerated by our code, but may evolve independently.
    # Publish only the image formats, not an unconstrained summary structure.
    for path in (destination / "plots").iterdir():
        if path.suffix not in {".png", ".svg"}:
            path.unlink()
    repository = Path(__file__).resolve().parents[1]
    for filename in ("LICENSE", "THIRD_PARTY_NOTICES.md", "references.bib"):
        (destination / filename).write_bytes((repository / filename).read_bytes())
    (destination / "licenses").mkdir()
    for filename in NOTICE_FILES:
        (destination / "licenses" / filename).write_bytes(
            (repository / "src/bem_testproblems/data/licenses" / filename).read_bytes()
        )
    heading = "UNVALIDATED PARTIAL PREVIEW" if partial_preview else "Computed benchmark results"
    text = (
        f"# {heading}\n\n{public['status']}.\n\n"
        "- [Computed vectors, objective values, status counts, and identities](results.json).\n"
        "- [Generated boxplots](plots/). Only strict completed trajectories are included.\n"
        "- [License](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).\n"
        "- [Full upstream BSD license](licenses/BEOBenchmark-LICENSE.txt) and "
        "[model notices](licenses/BEOBenchmark-MODEL-NOTICES.txt).\n"
        "- [Bibliographic references](references.bib), including the originating studies.\n"
        "- [All exported file hashes](inventory.json).\n\n"
        "The experiment block in [results.json](results.json) records the protocol, solver settings, "
        "model variants, and every run's exact seed, initial vector, and evaluation budget. "
        "Winning runs also record their call counts.\n\n"
        "Vectors retain full numerical precision. Status denominators include failed, skipped, "
        "non-strict, and unfinished runs. Groups with no strict completed run have no winner.\n\n"
        "This export contains our computed results. Original models, weather, native engines, "
        "raw simulation outputs, private filesystem paths, publications, and transcribed "
        "literature solutions are retained separately and are not exported.\n\n"
        "Study: Waibel, Wortmann, Evins, and Carmeliet (2019), "
        "[Building energy optimization: An extensive benchmark of global search algorithms]"
        "(https://doi.org/10.1016/j.enbuild.2019.01.048). See the repository's "
        "[bibliographic references](references.bib) for the originating studies.\n"
    )
    if partial_preview:
        text += (
            "\n**UNVALIDATED:** this preview bypasses the campaign-completion and replay gates.\n"
        )
    (destination / "README.md").write_text(text, encoding="utf-8")
    hashes = {
        path.relative_to(destination).as_posix(): replay._hash(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    replay._write(destination / "inventory.json", {"schema_version": 1, "files": hashes})
    return {
        "output_directory": str(destination),
        "status": public["status"],
        "exported_files": len(hashes) + 1,
        "partial_preview": bool(partial_preview),
    }


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("Public JSON contains missing or unexpected fields")


def _counts(value):
    allowed = replay.continuation.STATUSES | {"pending"}
    if (
        not isinstance(value, dict)
        or set(value) - allowed
        or any(type(count) is not int or count < 0 for count in value.values())
    ):
        raise ValueError("Invalid public status counts")


def _verify_experiment(result):
    from bem_testproblems import get_problem
    from bem_testproblems.replication import _seed, paired_start

    experiment = result["experiment"]
    _keys(
        experiment,
        (
            "protocol",
            "master_seed",
            "requested_repetitions",
            "budget_override",
            "budget_rule",
            "diagnostics_policy",
            "schedule",
            "start_policy",
            "numerical_variants",
            "solvers",
            "runs",
        ),
    )
    repetitions, budget = experiment["requested_repetitions"], experiment["budget_override"]
    if (
        experiment["protocol"] not in {"pilot-overrides", "paper-start-and-budget-protocol"}
        or type(experiment["master_seed"]) is not int
        or type(repetitions) is not int
        or repetitions < 1
        or budget is not None
        and (type(budget) is not int or budget < 1)
        or experiment["budget_rule"] != "100*(dimension+1)"
        or experiment["diagnostics_policy"] not in {"strict", "reference-warmup"}
        or experiment["schedule"] not in {"balanced", "problem-first"}
        or experiment["start_policy"] != "paired-uniform-physical-box-direct-midpoint"
        or experiment["protocol"]
        != (
            "paper-start-and-budget-protocol"
            if repetitions == 20 and budget is None
            else "pilot-overrides"
        )
    ):
        raise ValueError("Invalid public experiment protocol")
    for name, metadata in experiment["solvers"].items():
        if metadata != _solver_protocol(name):
            raise ValueError("Public solver settings differ from the authoritative adapter")
    definitions = {
        int(number): get_problem(number, numerical_variant=variant)
        for number, variant in experiment["numerical_variants"].items()
    }
    versions = set().union(*(source["engines"] for source in result["provenance"]))
    specifications, combinations, groups = {}, set(), Counter()
    for spec in experiment["runs"]:
        _keys(spec, replay.continuation.SPEC_FIELDS)
        if (
            type(spec["problem"]) is not int
            or spec["problem"] not in definitions
            or spec["solver"] not in experiment["solvers"]
            or spec["version"] not in versions
            or any(
                type(spec[key]) is not int or spec[key] < 0
                for key in ("repetition", "seed", "budget")
            )
            or spec["repetition"] >= repetitions
            or spec["budget"] < 1
        ):
            raise ValueError("Invalid scheduled public run")
        _token(spec["id"])
        problem = definitions[spec["problem"]]
        problem.validate(spec["x0"])
        for x in spec["x0"]:
            _number(x)
        start = (
            problem.midpoint
            if spec["solver"] == "direct"
            else paired_start(problem, spec["repetition"], experiment["master_seed"])
        )
        if (
            spec["x0"] != list(start)
            or spec["seed"]
            != _seed(
                experiment["master_seed"], "solver", problem.id, spec["repetition"], spec["solver"]
            )
            or spec["budget"] != (budget if budget is not None else 100 * (problem.dimension + 1))
        ):
            raise ValueError("Scheduled seeds, starts, or budgets differ from the public protocol")
        key = (spec["problem"], spec["version"], spec["solver"], spec["repetition"])
        if spec["id"] in specifications or key in combinations:
            raise ValueError("Duplicate scheduled public run")
        specifications[spec["id"]] = spec
        combinations.add(key)
        groups[key[:3]] += 1
    expected = {
        (problem, version, solver, repetition)
        for problem in definitions
        for version in versions
        for solver in experiment["solvers"]
        for repetition in range(repetitions)
    }
    if combinations != expected or len(specifications) != result["planned_runs"]:
        raise ValueError("Public run schedule is incomplete or differs from the planned count")
    return specifications, groups


def _verify_public_schema(result):
    """Enforce the publication allowlist, canonical parameter metadata, and vector links."""
    from bem_testproblems import get_problem
    from bem_testproblems.replication_solvers import SOLVER_ORDER

    _keys(
        result,
        (
            "schema_version",
            "status",
            "partial_preview",
            "campaign_complete",
            "planned_runs",
            "status_counts",
            "origin_manifest_id",
            "provenance",
            "experiment",
            "best_per_solver",
            "best_across_methods",
            "replay",
            "selection",
            "literature",
            "limitations",
        ),
    )
    if (
        result["schema_version"] != 1
        or type(result["partial_preview"]) is not bool
        or type(result["campaign_complete"]) is not bool
        or type(result["planned_runs"]) is not int
        or result["planned_runs"] < 1
        or result["selection"] != SELECTION
        or result["literature"] != LITERATURE
        or result["limitations"] != LIMITATIONS
        or result["status"] != (PREVIEW_STATUS if result["partial_preview"] else COMPLETE_STATUS)
    ):
        raise ValueError("Invalid public result schema or labels")
    _counts(result["status_counts"])
    incomplete = any(
        result["status_counts"].get(name, 0) for name in ("pending", "running", "interrupted")
    )
    if sum(result["status_counts"].values()) != result["planned_runs"] or (
        result["campaign_complete"] == incomplete
    ):
        raise ValueError("Public completion label differs from status counts")
    identities = set()
    for source in result["provenance"]:
        _keys(
            source,
            (
                "manifest_id",
                "platform",
                "python",
                "engines",
                "code_sha256",
                "dependencies",
                "problem_inputs",
            ),
        )
        identifier = _hash_value(source["manifest_id"])
        if identifier in identities:
            raise ValueError("Duplicate public manifest identity")
        identities.add(identifier)
        if source["python"] is not None:
            _keys(source["python"], ("version", "implementation", "executable_sha256"))
            if not re.fullmatch(r"\d+\.\d+\.\d+", source["python"]["version"]) or source["python"][
                "implementation"
            ] not in {"CPython", "PyPy"}:
                raise ValueError("Unsafe Python runtime provenance")
            _hash_value(source["python"]["executable_sha256"])
        if source["platform"] != "unspecified" and not re.fullmatch(
            r"(?:Darwin|Windows|Linux)-(?:arm64|aarch64|AMD64|x86_64)", source["platform"]
        ):
            raise ValueError("Unsafe public platform label")
        for version, engine in source["engines"].items():
            if version not in {"8.5.0", "26.2.0"}:
                raise ValueError("Unknown public engine version")
            _keys(engine, ("executable_sha256", "supporting_sha256"))
            _hash_value(engine["executable_sha256"])
            _hashes(engine["supporting_sha256"])
        _hashes(source["code_sha256"])
        for name, versions in source["dependencies"].items():
            if name not in {"cma", "nlopt", "numpy", "pdfo", "pybobyqa", "scipy"}:
                raise ValueError("Unknown public dependency")
            _keys(versions, ("distribution_version", "runtime_version"))
            for version in versions.values():
                if version is not None and not re.fullmatch(
                    r"\d+(?:\.\d+)+(?:[A-Za-z0-9.+-]*)", version
                ):
                    raise ValueError("Unsafe dependency version label")
        for number, inputs in source["problem_inputs"].items():
            get_problem(number)
            _keys(inputs, ("models", "weather_sha256"))
            if inputs["weather_sha256"] is not None:
                _hash_value(inputs["weather_sha256"])
            for version, model in inputs["models"].items():
                if version not in source["engines"] or set(model) - {
                    "template_sha256",
                    "bindings_sha256",
                }:
                    raise ValueError("Unknown model hash field")
                _hashes(model)
    if _hash_value(result["origin_manifest_id"]) not in identities:
        raise ValueError("Origin is absent from public manifest lineage")
    specifications, planned_groups = _verify_experiment(result)

    def winner(value, group):
        if value is None:
            return
        _keys(
            value,
            (
                "problem",
                "version",
                "solver",
                "run_id",
                "manifest_id",
                "x",
                "f",
                "seed",
                "budget",
                "repetition",
                "evaluation_count",
                "x0",
                "dimension",
                "objective_unit",
                "parameter_names",
                "parameter_symbols",
                "parameter_units",
                "bounds",
            ),
        )
        if (
            type(value["problem"]) is not int
            or value["problem"] != group["problem"]
            or value["version"] != group["version"]
            or value["solver"] not in SOLVER_ORDER
            or value["manifest_id"] not in identities
            or group.get("solver", value["solver"]) != value["solver"]
        ):
            raise ValueError("Public winner identity differs from its group")
        problem = get_problem(value["problem"])
        problem.validate(value["x"])
        spec = specifications.get(value["run_id"])
        if (
            spec is None
            or any(type(value[key]) is not int for key in ("seed", "budget", "repetition"))
            or any(
                value[key] != spec[key]
                for key in ("problem", "version", "solver", "seed", "budget", "repetition", "x0")
            )
            or type(value["evaluation_count"]) is not int
            or not 1 <= value["evaluation_count"] <= spec["budget"]
        ):
            raise ValueError("Public winner search differs from its scheduled run")
        expected = _public_best({**value, "best_x": value["x"], "best_f": value["f"]})
        if value != expected:
            raise ValueError("Public vector or parameter metadata is not canonical")

    groups = {}
    for group in result["best_per_solver"]:
        _keys(
            group,
            (
                "problem",
                "version",
                "winner",
                "solver",
                "requested",
                "included",
                "excluded_non_strict",
                "statuses",
            ),
        )
        _counts(group["statuses"])
        if (
            group["solver"] not in SOLVER_ORDER
            or group["version"] not in {"8.5.0", "26.2.0"}
            or any(
                type(group[key]) is not int or group[key] < 0
                for key in ("requested", "included", "excluded_non_strict")
            )
            or sum(group["statuses"].values()) != group["requested"]
            or group["included"] + group["excluded_non_strict"]
            != sum(group["statuses"].get(name, 0) for name in ("completed", "budget_exhausted"))
            or (group["winner"] is None) != (group["included"] == 0)
        ):
            raise ValueError("Public solver denominators differ from status counts")
        winner(group["winner"], group)
        key = (group["problem"], group["version"], group["solver"])
        if group["requested"] != planned_groups.get(key):
            raise ValueError("Public solver denominator differs from its scheduled runs")
        if key in groups:
            raise ValueError("Duplicate public solver group")
        groups[key] = group
    if sum(group["requested"] for group in groups.values()) != result["planned_runs"]:
        raise ValueError("Public planned denominator differs from solver groups")
    best = {}
    for group in result["best_across_methods"]:
        _keys(group, ("problem", "version", "winner"))
        winner(group["winner"], group)
        key = (group["problem"], group["version"])
        if key in best:
            raise ValueError("Duplicate public best-across-methods group")
        candidates = [
            row["winner"]
            for row in groups.values()
            if row["problem"] == key[0] and row["version"] == key[1] and row["winner"] is not None
        ]
        expected = min(candidates, key=lambda row: (row["f"], row["run_id"]), default=None)
        if group["winner"] != expected:
            raise ValueError("Best-across-methods vector differs from per-solver winners")
        best[key] = group["winner"]
    if set(best) != {(key[0], key[1]) for key in groups}:
        raise ValueError("Missing public best-across-methods group")
    if result["replay"] is not None:
        validation = result["replay"]
        _keys(validation, ("plan_id", "selection_digest", "rtol", "atol", "passed", "items"))
        for item in validation["items"]:
            _keys(
                item,
                (
                    "problem",
                    "version",
                    "run_id",
                    "manifest_id",
                    "passed",
                    "severe_count",
                    "fatal_count",
                    "completed_successfully",
                    "input_sha256",
                    "x",
                    "actual_f",
                    "objective_comparison",
                    "actual_components",
                    "expected_components",
                    "component_comparisons",
                    "engine_executable_sha256",
                    "source_engine_executable_sha256",
                    "replay_scope",
                    "diagnostic_sha256",
                ),
            )
            for field in ("actual_components", "expected_components"):
                for name, value in item[field].items():
                    _token(name)
                    _number(value)
            comparisons = [item["objective_comparison"], *item["component_comparisons"].values()]
            for comparison in comparisons:
                _keys(comparison, ("passed", "signed_difference", "percentage_difference"))
                for name in ("signed_difference", "percentage_difference"):
                    if comparison[name] is not None:
                        _number(comparison[name])
            _keys(item["diagnostic_sha256"], ("eplusout.err", "eplusout.end", "run.json"))
    return best


def verify_export(directory, *, allow_partial_preview=False):
    """Check the public package's integrity and gates, without private raw inputs.

    This checks recorded evidence and detects changes. It does not rerun the
    simulator or independently establish scientific correctness.
    """
    directory = Path(directory).expanduser().resolve()
    inventory = replay.continuation._read(directory / "inventory.json")[0]
    _keys(inventory, ("schema_version", "files"))
    if inventory["schema_version"] != 1:
        raise ValueError("Unknown export inventory schema")
    files = inventory.get("files", {})
    required = {
        "README.md",
        "results.json",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "references.bib",
        *("licenses/" + filename for filename in NOTICE_FILES),
    }
    if not required <= files.keys() or not any(name.endswith(".svg") for name in files):
        raise ValueError("Export inventory is incomplete")
    for name, digest in files.items():
        allowed = name in required or re.fullmatch(
            r"plots/figure[89]-energyplus-(?:8\.5\.0|26\.2\.0)\.(?:png|svg)", name
        )
        path = directory / name
        if (
            not allowed
            or path.is_symlink()
            or not path.resolve().is_relative_to(directory)
            or replay._hash(path) != _hash_value(digest)
        ):
            raise ValueError("Export contains an unexpected or changed file")
    actual = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != set(files) | {"inventory.json"}:
        raise ValueError("Export contains unlisted files")
    result = replay.continuation._read(directory / "results.json")[0]
    _verify_public_schema(result)
    preview = result.get("partial_preview") is True
    if preview:
        if (
            result.get("status") != "UNVALIDATED PARTIAL PREVIEW"
            or result.get("replay") is not None
            or "UNVALIDATED PARTIAL PREVIEW" not in (directory / "README.md").read_text()
        ):
            raise ValueError("Preview is missing its unvalidated label")
        if not allow_partial_preview:
            raise ValueError(
                "Preview is unvalidated; explicitly allow a partial preview integrity check"
            )
    else:
        validation = result.get("replay") or {}
        statuses = result.get("status_counts", {})
        winners = {
            (row["problem"], row["version"]): row["winner"]
            for row in result.get("best_across_methods", [])
            if row.get("winner") is not None
        }
        if (
            result.get("campaign_complete") is not True
            or not winners
            or any(statuses.get(name, 0) for name in ("pending", "running", "interrupted"))
            or sum(statuses.values()) != result.get("planned_runs")
            or validation.get("passed") is not True
            or validation.get("rtol") != replay.RTOL
            or validation.get("atol") != replay.ATOL
            or len(validation.get("items", [])) != len(winners)
        ):
            raise ValueError("Export lacks a complete campaign and passing incumbent replay stamp")
        _hash_value(validation["plan_id"])
        _hash_value(validation["selection_digest"])
        seen = set()
        for item in validation["items"]:
            key = (item["problem"], item["version"])
            winner = winners.get(key)
            if (
                winner is None
                or key in seen
                or item.get("passed") is not True
                or item.get("run_id") != winner["run_id"]
                or item.get("manifest_id") != winner["manifest_id"]
                or item.get("x") != winner["x"]
                or item.get("severe_count") != 0
                or item.get("fatal_count") != 0
                or item.get("completed_successfully") is not True
                or not replay.compare_numbers(winner["f"], item.get("actual_f"))["passed"]
                or not item.get("expected_components")
                or set(item["expected_components"]) != set(item.get("actual_components", {}))
                or any(
                    not replay.compare_numbers(value, item["actual_components"][name])["passed"]
                    for name, value in item["expected_components"].items()
                )
                or item["objective_comparison"]
                != replay.compare_numbers(winner["f"], item["actual_f"])
                or item["component_comparisons"]
                != {
                    name: replay.compare_numbers(value, item["actual_components"][name])
                    for name, value in item["expected_components"].items()
                }
            ):
                raise ValueError("Export replay comparisons do not pass")
            seen.add(key)
            _hash_value(item["engine_executable_sha256"])
            _hash_value(item["source_engine_executable_sha256"])
            source = next(
                row for row in result["provenance"] if row["manifest_id"] == winner["manifest_id"]
            )
            if (
                item["source_engine_executable_sha256"]
                != source["engines"][winner["version"]]["executable_sha256"]
            ):
                raise ValueError("Export source native hash differs from factual manifest lineage")
            _hash_value(item["input_sha256"])
            scope = (
                "same-native-binary"
                if item["engine_executable_sha256"] == item["source_engine_executable_sha256"]
                else "same-version-different-native-build"
            )
            if item.get("replay_scope") != scope:
                raise ValueError("Export native replay scope differs from recorded hashes")
            _hashes(item["diagnostic_sha256"])
    return {
        "integrity_passed": True,
        "validated_result_stamp": not preview,
        "partial_preview": preview,
        "files_checked": len(files),
        "scope": "File integrity and recorded gates; no native simulations or private inputs used",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", type=Path)
    parser.add_argument("--continuation", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--replay-dir", type=Path)
    parser.add_argument("--frozen-source", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument(
        "--partial-preview",
        action="store_true",
        help="Explicitly export a conspicuously labeled unvalidated preview",
    )
    parser.add_argument(
        "--verify-export",
        type=Path,
        help="Verify an existing public package without private campaign inputs",
    )
    parser.add_argument(
        "--allow-partial-preview",
        action="store_true",
        help="Permit integrity checking a preview; it remains unvalidated",
    )
    args = parser.parse_args(argv)
    if args.verify_export:
        if any(
            (
                args.origin,
                args.continuation,
                args.output_dir,
                args.replay_dir,
                args.frozen_source,
                args.project_root,
                args.partial_preview,
            )
        ):
            parser.error("--verify-export cannot be combined with export inputs")
        print(
            json.dumps(
                verify_export(args.verify_export, allow_partial_preview=args.allow_partial_preview),
                indent=2,
            )
        )
        return 0
    if args.allow_partial_preview:
        parser.error("--allow-partial-preview requires --verify-export")
    if args.origin is None or args.output_dir is None:
        parser.error("--origin and --output-dir are required for export")
    dataset = replay._review_module().load_review(args.origin, args.continuation)
    result = export_results(
        dataset,
        origin=args.origin,
        continuation_root=args.continuation,
        output_dir=args.output_dir,
        replay_dir=args.replay_dir,
        partial_preview=args.partial_preview,
        frozen_source=args.frozen_source,
        project_root=args.project_root,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
