# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Plan or explicitly replay full-precision strict incumbents using frozen source."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

if __package__:
    from . import continue_replication as continuation
else:
    import continue_replication as continuation

RTOL, ATOL = 1e-6, 1e-7


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _review_module():
    if __package__:
        from . import review_replication
    else:
        import review_replication
    return review_replication


def strict_incumbents(dataset):
    """Keep exact winning observations, including their recorded output components."""
    report = _review_module().build_review(dataset)
    selected = []
    for group in report["best_across_methods"]:
        winner = group["winner"]
        if winner is None:
            continue
        record = dataset["records"][winner["run_id"]]
        observations = [
            item
            for item in record["trace"]
            if item["status"] == "success"
            and item["x"] == winner["best_x"]
            and item["f"] == winner["best_f"]
        ]
        if not observations:
            raise ValueError("Incumbent has no matching full-precision observation")
        item = observations[0]
        diagnostics = item.get("diagnostics", {})
        if (
            item.get("strict_benchmark_evaluation") is not True
            or diagnostics.get("severe_count") != 0
            or diagnostics.get("fatal_count") != 0
        ):
            raise ValueError("Strict incumbent lacks zero-severe/fatal diagnostic evidence")
        components = item.get("components")
        if (
            not isinstance(components, dict)
            or not components
            or any(
                not isinstance(name, str)
                or type(value) not in (int, float)
                or not math.isfinite(value)
                for name, value in components.items()
            )
        ):
            raise ValueError("Incumbent lacks finite component observations")
        if not isinstance(item.get("input_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", item["input_sha256"]
        ):
            raise ValueError("Incumbent lacks its rendered input SHA-256")
        selected.append(
            {
                "problem": winner["problem"],
                "version": winner["version"],
                "solver": winner["solver"],
                "run_id": winner["run_id"],
                "manifest_id": winner["manifest_id"],
                "x": winner["best_x"],
                "f": winner["best_f"],
                "components": components,
                "source_engine_sha256": dataset["manifests"][winner["manifest_id"]]["engines"][
                    winner["version"]
                ]["executable_sha256"],
                "input_sha256": item.get("input_sha256"),
            }
        )
    return sorted(selected, key=lambda row: (row["problem"], row["version"]))


def safe_destination(
    destination,
    *,
    origin,
    continuation_root=None,
    frozen_source=None,
    project_root=None,
    extra_inputs=(),
):
    """Never overwrite evidence or put generated output inside immutable inputs."""
    destination = Path(destination).expanduser()
    if destination.is_symlink():
        raise ValueError("Output directory cannot be a symbolic link")
    destination = destination.resolve()
    protected = [Path(origin).resolve()]
    protected.append(Path(__file__).resolve().parents[1] / "src")
    protected.append(Path(__file__).resolve().parent)
    protected.extend(Path(path).resolve() for path in (continuation_root, frozen_source) if path)
    if project_root:
        protected.extend(
            Path(project_root).resolve() / name
            for name in ("src", ".tools", ".cache", ".reference-cache")
        )
    protected.extend(Path(path).resolve() for path in extra_inputs)
    if any(destination == path or destination.is_relative_to(path) for path in protected):
        raise ValueError("Output destination is inside protected evidence or inputs")
    if destination.exists():
        raise FileExistsError(f"Use a fresh output directory: {destination}")
    return destination


def _source_identity(frozen_source, manifest):
    package = Path(frozen_source).resolve() / "src/bem_testproblems"
    for name, expected in manifest["code_sha256"].items():
        if Path(name).name != name or not (package / name).is_file():
            raise ValueError("Frozen source file is missing or unsafe")
        if _hash(package / name) != expected:
            raise ValueError(f"Frozen numerical source differs: {name}")
    hashes = {
        str(path.relative_to(package)): _hash(path)
        for path in sorted(package.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    return continuation._digest(hashes)


def prepare_replay(
    dataset,
    *,
    origin,
    continuation_root=None,
    frozen_source,
    project_root,
    output_dir,
    weather_dir=None,
    executables=None,
):
    """Check source and byte identities without probing or running EnergyPlus."""
    destination = safe_destination(
        output_dir,
        origin=origin,
        continuation_root=continuation_root,
        frozen_source=frozen_source,
        project_root=project_root,
        extra_inputs=[Path(path).parent for path in (executables or {}).values()]
        + ([weather_dir] if weather_dir else [])
        + list(dataset.get("protected_roots", [])),
    )
    source_hash = _source_identity(frozen_source, dataset["origin_manifest"])
    expected_hashes = {
        manifest["continuation"]["frozen_package_sha256"]
        for manifest in dataset["manifests"].values()
        if "continuation" in manifest
    }
    if expected_hashes and expected_hashes != {source_hash}:
        raise ValueError("Frozen package differs from the continuation's complete package hash")
    incumbents = strict_incumbents(dataset)
    if not incumbents:
        raise ValueError("There are no completed strict incumbents to replay")
    project = Path(project_root).expanduser().resolve()
    engines = {}
    for version in sorted({item["version"] for item in incumbents}):
        path = Path(
            (executables or {}).get(
                version,
                project
                / ".tools/energyplus"
                / version
                / ("energyplus.exe" if os.name == "nt" else "energyplus"),
            )
        )
        path = path.expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError("EnergyPlus executable must be a file")
        supporting = {
            p.name: _hash(p)
            for p in path.parent.iterdir()
            if p.is_file()
            and (
                p.name == "Energy+.idd"
                or p.name.startswith(("libenergyplusapi", "energyplusapi.dll"))
            )
        }
        engines[version] = {
            "executable": str(path),
            "executable_sha256": _hash(path),
            "supporting_sha256": supporting,
        }
    plan = {
        "schema_version": 1,
        "operation": "strict-incumbent-replay",
        "origin_manifest_id": dataset["origin_manifest"]["manifest_id"],
        "source_manifest_ids": sorted(dataset["manifests"]),
        "selection_digest": continuation._digest(incumbents),
        "incumbents": incumbents,
        "frozen_source": str(Path(frozen_source).resolve()),
        "origin_directory": str(Path(origin).resolve()),
        "continuation_directory": str(Path(continuation_root).resolve())
        if continuation_root
        else None,
        "protected_roots": list(dataset.get("protected_roots", []))
        + ([str(Path(weather_dir).resolve())] if weather_dir else []),
        "frozen_package_sha256": source_hash,
        "project_root": str(project),
        "weather_directory": str(
            Path(weather_dir).expanduser().resolve() if weather_dir else project / ".cache/weather"
        ),
        "engines": engines,
        "problem_definitions": dataset["origin_manifest"]["problem_definitions"],
        "code_sha256": dataset["origin_manifest"]["code_sha256"],
        "output_directory": str(destination),
        "rtol": RTOL,
        "atol": ATOL,
        "simulation_started": False,
        "comparison_scope": "Same frozen source, model, weather, and engine version; "
        "native executable hashes and platform are recorded for this replay.",
    }
    plan["plan_id"] = continuation._digest(plan)
    # Keep the sealed plan independent of the caller's mutable review dictionaries.
    return json.loads(json.dumps(plan, allow_nan=False))


def compare_numbers(expected, actual):
    """Report signed and percentage differences with a near-zero absolute tolerance."""
    if type(actual) not in (int, float) or not math.isfinite(actual):
        return {"passed": False, "signed_difference": None, "percentage_difference": None}
    delta = actual - expected
    return {
        "passed": abs(delta) <= max(ATOL, RTOL * abs(expected)),
        "signed_difference": delta,
        "percentage_difference": 100 * delta / abs(expected) if expected else None,
    }


def _worker(request_path, *, runtime=None):
    """Run in a fresh Python process; import only the historical simulator package."""
    request = continuation._read(request_path)[0]
    plan, item = request["plan"], request["incumbent"]
    output = Path(request["output_directory"])
    result_path = output / "worker-result.json"
    if (
        plan.get("plan_id")
        != continuation._digest({key: value for key, value in plan.items() if key != "plan_id"})
        or item not in plan["incumbents"]
        or result_path.exists()
        or not output.resolve().is_relative_to(Path(plan["output_directory"]).resolve())
    ):
        raise ValueError("Unsafe, stale, or already executed replay request")
    try:
        if _source_identity(plan["frozen_source"], plan) != plan["frozen_package_sha256"]:
            raise ValueError("Frozen package changed after replay planning")
        runtime = runtime or continuation._load_runtime(plan["project_root"], plan["frozen_source"])
        problem_identity = plan["problem_definitions"][str(item["problem"])]
        problem = runtime.get_problem(
            item["problem"], numerical_variant=problem_identity.get("numerical_variant")
        )
        engine = plan["engines"][item["version"]]
        if _hash(engine["executable"]) != engine["executable_sha256"] or any(
            _hash(Path(engine["executable"]).parent / name) != value
            for name, value in engine["supporting_sha256"].items()
        ):
            raise ValueError("Native replay installation changed after planning")
        model = runtime._model_identity(problem, item["version"])
        weather = runtime._weather_identity(problem, Path(plan["weather_directory"]))
        if (
            model != problem_identity["models"][item["version"]]
            or weather != problem_identity["weather"]
        ):
            raise ValueError("Replay model or canonical weather differs from the experiment")
        runner = runtime.EnergyPlusRunner(
            engine["executable"],
            expected_version=item["version"],
            output_root=output / "simulations",
            cache=False,
        )
        observed = runtime._ObservedRunner(runner)
        objective = runtime.make_objective(
            problem, runner=observed, weather_dir=plan["weather_directory"]
        )
        actual_f = float(objective(item["x"]))
        if observed.last is None:
            raise ValueError("Replay objective produced no simulator evidence")
        actual_components = runtime.extract_outputs(problem.family, observed.last)
        directory = observed.last.directory
        diagnostic_text = (directory / "eplusout.err").read_text(errors="replace")
        severe = len(re.findall(r"\*\*\s*Severe\s*\*\*", diagnostic_text, re.I))
        fatal = len(re.findall(r"\*\*\s*Fatal\s*\*\*", diagnostic_text, re.I))
        completed = "EnergyPlus Completed Successfully" in (directory / "eplusout.end").read_text(
            errors="replace"
        )
        comparisons = {"objective": compare_numbers(item["f"], actual_f)}
        comparisons["components"] = {
            name: compare_numbers(value, actual_components.get(name))
            for name, value in item["components"].items()
        }
        input_matches = (
            item["input_sha256"] is not None and observed.last.input_sha256 == item["input_sha256"]
        )
        passed = (
            completed
            and severe == fatal == 0
            and input_matches
            and set(actual_components) == set(item["components"])
            and comparisons["objective"]["passed"]
            and all(row["passed"] for row in comparisons["components"].values())
        )
        result = {
            "passed": passed,
            "actual_f": actual_f,
            "actual_components": actual_components,
            "comparisons": comparisons,
            "severe_count": severe,
            "fatal_count": fatal,
            "completed_successfully": completed,
            "input_matches": input_matches,
            "input_sha256": observed.last.input_sha256,
            "model": model,
            "weather": weather,
            "engine": {**engine, "version_output": runner.version_output},
            "native_binary_matches_source": engine["executable_sha256"]
            == item["source_engine_sha256"],
            "replay_scope": "same-native-binary"
            if engine["executable_sha256"] == item["source_engine_sha256"]
            else "same-version-different-native-build",
            "platform": platform.system() + "-" + platform.machine(),
            "simulation_directory": str(directory),
            "diagnostic_sha256": {
                name: _hash(directory / name)
                for name in ("eplusout.err", "eplusout.end", "run.json")
            },
        }
    except Exception as error:
        result = {"passed": False, "error_type": type(error).__name__, "error": str(error)}
    _write(result_path, result)
    return result


def run_replay(plan, *, execute=subprocess.run):
    """Run one retained replay per incumbent; preserve failed runs for inspection."""
    if plan.get("plan_id") != continuation._digest(
        {k: v for k, v in plan.items() if k != "plan_id"}
    ):
        raise ValueError("Replay plan digest differs")
    destination = safe_destination(
        plan["output_directory"],
        origin=plan["origin_directory"],
        continuation_root=plan["continuation_directory"],
        frozen_source=plan["frozen_source"],
        project_root=plan["project_root"],
        extra_inputs=[Path(engine["executable"]).parent for engine in plan["engines"].values()]
        + plan["protected_roots"],
    )
    destination.mkdir(parents=True, exist_ok=False)
    _write(destination / "replay-plan.json", plan)
    items = []
    for item in plan["incumbents"]:
        directory = destination / f"p{item['problem']:02}-{item['version']}"
        directory.mkdir()
        request = {"plan": plan, "incumbent": item, "output_directory": str(directory)}
        request_path = directory / "request.json"
        _write(request_path, request)
        with (directory / "worker.log").open("wb") as log:
            try:
                completed = execute(
                    [
                        sys.executable,
                        "-B",
                        str(Path(__file__).resolve()),
                        "--worker",
                        str(request_path),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                result_path = directory / "worker-result.json"
                result = (
                    continuation._read(result_path)[0]
                    if result_path.is_file()
                    else {
                        "passed": False,
                        "error_type": "WorkerFailure",
                        "error": f"Worker returned {completed.returncode} without a result",
                    }
                )
                if completed.returncode:
                    result["passed"] = False
                    result["worker_returncode"] = completed.returncode
                if result.get("simulation_directory"):
                    evidence = Path(result["simulation_directory"]).resolve()
                    result["evidence_directory"] = evidence.relative_to(destination).as_posix()
            except (OSError, ValueError) as error:
                result = {"passed": False, "error_type": type(error).__name__, "error": str(error)}
        items.append(
            {
                "problem": item["problem"],
                "version": item["version"],
                "run_id": item["run_id"],
                "manifest_id": item["manifest_id"],
                **result,
            }
        )
        _write(
            destination / "replay-summary.json",
            {
                "schema_version": 1,
                "plan_id": plan["plan_id"],
                "selection_digest": plan["selection_digest"],
                "source_manifest_ids": plan["source_manifest_ids"],
                "rtol": RTOL,
                "atol": ATOL,
                "complete": len(items) == len(plan["incumbents"]),
                "passed": len(items) == len(plan["incumbents"])
                and all(row["passed"] for row in items),
                "items": items,
            },
        )
    return continuation._read(destination / "replay-summary.json")[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", type=Path)
    parser.add_argument("--continuation", type=Path)
    parser.add_argument("--frozen-source", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--weather-dir", type=Path)
    parser.add_argument("--executable-8-5", type=Path)
    parser.add_argument("--executable-26-2", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan-only", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return 0 if _worker(args.worker)["passed"] else 1
    for name in ("origin", "frozen_source", "project_root", "output_dir"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required")
    dataset = _review_module().load_review(args.origin, args.continuation)
    plan = prepare_replay(
        dataset,
        origin=args.origin,
        continuation_root=args.continuation,
        frozen_source=args.frozen_source,
        project_root=args.project_root,
        output_dir=args.output_dir,
        weather_dir=args.weather_dir,
        executables={
            version: path
            for version, path in (("8.5.0", args.executable_8_5), ("26.2.0", args.executable_26_2))
            if path
        },
    )
    report = run_replay(plan) if args.run else plan
    print(json.dumps(report, indent=2))
    return int(args.run and not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
