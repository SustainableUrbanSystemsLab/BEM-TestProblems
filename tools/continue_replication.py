# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Plan or explicitly run a provenance-linked continuation on another computer."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import multiprocessing
import os
import platform
import re
import socket
import sys
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

TERMINAL = {"completed", "budget_exhausted", "failed", "skipped"}
STATUSES = TERMINAL | {"running", "interrupted"}
SPEC_FIELDS = ("id", "problem", "version", "solver", "repetition", "seed", "x0", "budget")
THREAD_VARIABLES = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _runtime_identity():
    """Bind destination results to the actual interpreter and operating system."""
    return {
        "python_version": sys.version,
        "python_implementation": sys.implementation.name,
        "python_executable_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def _read(path):
    raw = Path(path).read_bytes()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Nonfinite JSON number in {path}: {value}")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    digest = hashlib.sha256(raw)
    if isinstance(value, dict) and "trace_storage" in value:
        from bem_testproblems.replication_journal import read_checkpoint
        value = read_checkpoint(path, value)
        # Compact-file bytes alone do not identify the committed observations.
        # Include their materialized meaning; uncommitted tails remain excluded.
        digest.update(b"\0" + json.dumps(value, sort_keys=True, allow_nan=False).encode())

    # Exponents such as 1e999 also decode to infinity without parse_constant.
    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError(f"Nonfinite number in {path}")
        if isinstance(item, dict):
            for child in item.values():
                finite(child)
        elif isinstance(item, list):
            for child in item:
                finite(child)

    finite(value)
    return value, digest.hexdigest()


def _specs(manifest):
    specs = {}
    for row in manifest["runs"]:
        identifier = row["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[\w.-]+", identifier):
            raise ValueError("Unsafe run ID")
        if identifier in specs:
            raise ValueError(f"Duplicate scheduled run ID: {identifier}")
        if any(key not in row for key in SPEC_FIELDS):
            raise ValueError(f"Incomplete run specification: {identifier}")
        if (
            any(
                type(row[k]) is not int or row[k] < 0
                for k in ("problem", "repetition", "seed", "budget")
            )
            or row["problem"] == 0
            or row["budget"] == 0
            or not isinstance(row["x0"], list)
            or any(type(x) not in (int, float) for x in row["x0"])
        ):
            raise ValueError(f"Invalid run specification: {identifier}")
        specs[identifier] = row
    return specs


def _check_record(record, spec, manifest, path):
    if any(record.get(key) != spec[key] for key in SPEC_FIELDS):
        raise ValueError(f"Checkpoint specification differs: {path}")
    if record.get("manifest_id") != manifest["manifest_id"]:
        raise ValueError(f"Checkpoint manifest differs: {path}")
    if record.get("status") not in STATUSES:
        raise ValueError(f"Invalid checkpoint status: {path}")
    for key, expected in (
        ("problem_provenance", manifest["problem_definitions"][str(spec["problem"])]),
        ("engine_provenance", manifest["engines"][spec["version"]]),
        ("solver_metadata", manifest["solvers"][spec["solver"]]),
    ):
        if record.get(key) != expected:
            raise ValueError(f"Checkpoint {key} differs: {path}")
    count = record.get("evaluation_count")
    trace = record.get("trace")
    if (
        type(count) is not int
        or count < 0
        or count > spec["budget"]
        or not isinstance(trace, list)
        or len(trace) != count
    ):
        raise ValueError(f"Invalid checkpoint evaluation count: {path}")
    best = record.get("best_f")
    point = record.get("best_x")
    if (best is None) != (point is None):
        raise ValueError(f"Incomplete checkpoint incumbent: {path}")
    if best is not None and (
        type(best) not in (int, float)
        or not isinstance(point, list)
        or len(point) != len(spec["x0"])
        or any(type(x) not in (int, float) for x in point)
    ):
        raise ValueError(f"Invalid checkpoint incumbent: {path}")
    if record["status"] in {"completed", "budget_exhausted"} and best is None:
        raise ValueError(f"Successful checkpoint has no objective: {path}")
    successes = []
    for index, item in enumerate(trace, 1):
        if (
            item.get("evaluation") != index
            or item.get("status") not in {"success", "failed"}
            or not isinstance(item.get("x"), list)
            or len(item["x"]) != len(spec["x0"])
            or any(type(x) not in (int, float) for x in item["x"])
        ):
            raise ValueError(f"Invalid checkpoint trace: {path}")
        if item["status"] == "success":
            if type(item.get("f")) not in (int, float):
                raise ValueError(f"Successful observation has no objective: {path}")
            successes.append(item)
        elif item.get("f") is not None:
            raise ValueError(f"Failed observation has an objective: {path}")
    if successes:
        minimum = min(item["f"] for item in successes)
        if best != minimum or not any(
            item["f"] == best and item["x"] == point for item in successes
        ):
            raise ValueError(f"Checkpoint incumbent differs from its observations: {path}")
    elif best is not None:
        raise ValueError(f"Checkpoint incumbent has no observation: {path}")


def read_origin(directory, *, retain_traces=True):
    """Validate source records and return their exact byte identities.

    Reviews can discard all but the winning observation after validating each
    complete trace. These in-memory summaries retain whole-trajectory strictness
    and the original evaluation count; they are not replacement checkpoints.
    """
    directory = Path(directory).resolve()
    manifest, manifest_hash = _read(directory / "manifest.json")
    if manifest.get("manifest_id") != _digest(
        {k: v for k, v in manifest.items() if k != "manifest_id"}
    ):
        raise ValueError("Origin manifest digest does not match its contents")
    specs = _specs(manifest)
    records, hashes = {}, {}
    for path in sorted((directory / "runs").glob("*.json")):
        record, digest = _read(path)
        identifier = record.get("id")
        if identifier not in specs or path.stem != identifier or identifier in records:
            raise ValueError(f"Unknown, duplicate, or misnamed checkpoint: {path}")
        _check_record(record, specs[identifier], manifest, path)
        if not retain_traces:
            from bem_testproblems.replication_plots import strict_trajectory

            trace = record["trace"]
            record["strict_benchmark_evaluation"] = strict_trajectory(record)
            winner = next((item for item in trace
                           if item["status"] == "success" and item["f"] == record["best_f"]
                           and item["x"] == record["best_x"]), None)
            record["trace"] = [winner] if winner is not None else []
            record["trace_summary"] = {
                "validated_observations": len(trace),
                "retained_observations": len(record["trace"]),
                "strict_whole_trajectory": record["strict_benchmark_evaluation"],
            }
            del trace
        records[identifier], hashes[path.name] = record, digest
    return (
        manifest,
        records,
        {"manifest_sha256": manifest_hash, "checkpoint_digest": _digest(hashes)},
    )


def _load_runtime(project_root, frozen_source):
    # Set these before importing any numerical package, including in spawned children.
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in THREAD_VARIABLES:
        os.environ[name] = "1"
    os.environ.setdefault("MPLCONFIGDIR", str(Path(project_root).resolve() / ".cache/matplotlib"))
    source = Path(frozen_source or project_root).resolve() / "src"
    package = source / "bem_testproblems"
    if not (package / "replication.py").is_file():
        raise FileNotFoundError(f"Python benchmark source missing: {package}")
    loaded = sys.modules.get("bem_testproblems")
    if loaded is not None and Path(loaded.__file__).resolve().parent != package:
        raise ValueError(
            "Another benchmark package is loaded; launch this driver in a fresh Python"
        )
    sys.path.insert(0, str(source))
    os.environ["PYTHONPATH"] = str(source)
    os.environ["BEM_REFERENCE_DIR"] = str(
        Path(project_root).resolve() / ".reference-cache/beobenchmark"
    )
    runtime = importlib.import_module("bem_testproblems.replication")
    if Path(runtime.__file__).resolve().parent != package:
        raise ValueError("The loaded benchmark package is not the selected source")
    return runtime


def _source_identity(runtime, origin):
    package = Path(runtime.__file__).resolve().parent
    for name, expected in origin["code_sha256"].items():
        if Path(name).name != name:
            raise ValueError("Unsafe source path in origin manifest")
        if hashlib.sha256((package / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen source differs from origin: {name}")
    hashes = {
        str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(package.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    return _digest(hashes)


def pool_partition(specs, workers):
    """Balance deterministic budget costs across pools; no pool exceeds 60 workers."""
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    count = (workers + 59) // 60
    sizes = [workers // count + (i < workers % count) for i in range(count)]
    groups = [[] for _ in sizes]
    loads = [0] * count
    for spec in sorted(specs, key=lambda row: (-row["budget"], row["id"])):
        index = min(range(count), key=lambda i: (loads[i] / sizes[i], i))
        groups[index].append(spec)
        loads[index] += spec["budget"]
    return list(zip(sizes, groups))


def _pending(manifest, output_root):
    pending = []
    for spec in manifest["runs"]:
        path = output_root / "runs" / (spec["id"] + ".json")
        if path.exists():
            row = _read(path)[0]
            _check_record(row, spec, manifest, path)
            if row["status"] in TERMINAL:
                continue
        pending.append(spec)
    if (output_root / "runs").is_dir():
        expected = {row["id"] for row in manifest["runs"]}
        if any(path.stem not in expected for path in (output_root / "runs").glob("*.json")):
            raise ValueError("Continuation contains unexpected checkpoint files")
    return pending


def _log(path, event):
    if path is not None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"time_utc": datetime.now(timezone.utc).isoformat(), **event}, allow_nan=False
                )
                + "\n"
            )


def _validate_paths(origin, project_root, output_root, frozen_source=None, log_file=None):
    """Keep generated results and the optional independent log away from input evidence."""
    origin, project, output = (Path(p).resolve() for p in (origin, project_root, output_root))
    protected = [
        origin,
        project / "src",
        project / ".tools",
        project / ".cache",
        project / ".reference-cache",
    ]
    if frozen_source is not None:
        protected.append(Path(frozen_source).resolve())
    protected = [path.resolve() for path in protected]
    if any(output.is_relative_to(path) or path.is_relative_to(output) for path in protected):
        raise ValueError(
            "Continuation output must be separate from origin, source and input folders"
        )
    if log_file is not None:
        log = Path(log_file).resolve()
        if (
            log.parent != output
            or log.suffix.lower() not in {".log", ".jsonl"}
            or (log.exists() and (not log.is_file() or log.stat().st_nlink > 1))
        ):
            raise ValueError(
                "--log-file must be an independent .log or .jsonl file directly inside output-root"
            )


def prepare_continuation(origin, project_root, output_root, *, workers=48, frozen_source=None):
    """Resolve target inputs and native version probes, but never run a simulation."""
    _validate_paths(origin, project_root, output_root, frozen_source)
    original, records, identity = read_origin(origin)
    project_root, output_root = Path(project_root).resolve(), Path(output_root).resolve()
    runtime = _load_runtime(project_root, frozen_source)
    source_hash = _source_identity(runtime, original)
    target = runtime.prepare_manifest(
        problems=list(original["problem_definitions"]),
        solvers=list(original["solvers"]),
        versions=list(original["engines"]),
        repetitions=original["requested_repetitions"],
        budget=original["budget_override"],
        seed=original["master_seed"],
        project_root=project_root,
        diagnostics_policy=original["diagnostics_policy"],
        schedule=original["schedule"],
        **({"budget_multiplier": original["budget_multiplier"]}
           if "budget_multiplier" in original else {}),
    )
    for key in ("problem_definitions", "solvers", "runs", "diagnostics_policy"):
        if target[key] != original[key]:
            raise ValueError(f"Target {key} differs from the frozen origin")
    terminal = {name for name, row in records.items() if row["status"] in TERMINAL}
    target["runs"] = [row for row in target["runs"] if row["id"] not in terminal]
    target["execution_runtime"] = _runtime_identity()
    target["continuation"] = {
        "origin_manifest_id": original["manifest_id"],
        **identity,
        "origin_statuses": dict(Counter(row["status"] for row in records.values())),
        "retained_terminal_runs": len(terminal),
        "frozen_package_sha256": source_hash,
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "execution_policy": "Deterministic budget-balanced spawn pools, each at most 60 workers; "
        "resource counts are outside numerical manifest identity",
        "resume_policy": "Original terminal records remain external; interrupted runs restart "
        "from their original seed, start and full budget; native state is not restored",
    }
    target.pop("manifest_id", None)
    target["manifest_id"] = _digest(target)
    existing = output_root / "manifest.json"
    if existing.is_file() and _read(existing)[0] != target:
        raise ValueError("Existing continuation manifest differs; use a new output root")
    pending = _pending(target, output_root)
    partitions = pool_partition(pending, workers)
    report = {
        "mode": "plan-only",
        "manifest_id": target["manifest_id"],
        "origin_manifest_id": original["manifest_id"],
        "origin_scheduled": len(original["runs"]),
        "retained_origin_terminal": len(terminal),
        "continuation_scheduled": len(target["runs"]),
        "retained_origin_statuses": target["continuation"]["origin_statuses"],
        "remaining_runs": len(pending),
        "workers": workers,
        "pool_sizes": [size for size, _ in partitions],
        "output_root": str(output_root),
    }
    return runtime, target, partitions, report


def continue_replication(
    origin, project_root, output_root, *, workers=48, frozen_source=None, run=False, log_file=None
):
    _validate_paths(origin, project_root, output_root, frozen_source, log_file)
    runtime, manifest, partitions, report = prepare_continuation(
        origin, project_root, output_root, workers=workers, frozen_source=frozen_source
    )
    if not run:
        _log(log_file, report)
        return report
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    summary_options = {"cache": {}} if hasattr(runtime, "_run_one_checkpointed") else {}
    with runtime._experiment_lock(root):
        # Recheck after acquiring the lock: another controller may have initialized it.
        path = root / "manifest.json"
        if path.exists() and _read(path)[0] != manifest:
            raise ValueError("Continuation changed before the coordinator lock was acquired")
        runtime._atomic_json(path, manifest)
        partitions = pool_partition(_pending(manifest, root), workers)
        state_path = root / "continuation-status.json"
        state = {
            "manifest_id": manifest["manifest_id"],
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "status": "running",
            "workers": workers,
            "pool_sizes": [size for size, _ in partitions],
        }
        runtime._atomic_json(state_path, state)
        _log(log_file, state)
        try:
            with ExitStack() as stack:
                futures = {}
                for size, specs in partitions:
                    if not specs:
                        continue
                    pool = stack.enter_context(
                        ProcessPoolExecutor(
                            max_workers=size, mp_context=multiprocessing.get_context("spawn")
                        )
                    )
                    for spec in specs:
                        worker = getattr(runtime, "_run_one_checkpointed", runtime._run_one)
                        future = pool.submit(worker, spec, manifest, str(root), "none")
                        futures[future] = spec
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as error:
                        spec = futures[future]
                        checkpoint = root / "runs" / (spec["id"] + ".json")
                        row = (
                            _read(checkpoint)[0]
                            if checkpoint.exists()
                            else {
                                **spec,
                                "manifest_id": manifest["manifest_id"],
                                "attempt": 0,
                                "evaluation_count": 0,
                                "best_x": None,
                                "best_f": None,
                                "trace": [],
                                "elapsed_seconds": 0,
                                "problem_provenance": manifest["problem_definitions"][
                                    str(spec["problem"])
                                ],
                                "engine_provenance": manifest["engines"][spec["version"]],
                                "solver_metadata": manifest["solvers"][spec["solver"]],
                            }
                        )
                        row.update(
                            status="interrupted",
                            error={
                                "type": type(error).__name__,
                                "message": str(error),
                                "reason": "worker-process-failure",
                            },
                        )
                        runtime._atomic_json(checkpoint, row)
                    summary = runtime._summary(root, manifest, workers, **summary_options)
                    _log(
                        log_file, {"run_id": futures[future]["id"], "statuses": summary["statuses"]}
                    )
            summary = runtime._summary(root, manifest, workers, **summary_options)
            counts = summary["statuses"]
            state["status"] = (
                "interrupted"
                if (
                    counts.get("interrupted", 0)
                    or counts.get("running", 0)
                    or sum(counts.values()) != len(manifest["runs"])
                )
                else "finished-with-failures"
                if counts.get("failed", 0) or counts.get("skipped", 0)
                else "finished"
            )
            return {**report, "mode": "run", "summary": summary}
        except BaseException:
            state["status"] = "interrupted"
            raise
        finally:
            runtime._summary(root, manifest, workers, **summary_options)
            runtime._atomic_json(state_path, state)
            _log(log_file, state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--frozen-source", type=Path)
    parser.add_argument("--workers", type=int, default=48)
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Append events/errors to an independent .log/.jsonl file directly inside output-root",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--plan-only", action="store_true", help="Default; resolve inputs without simulations"
    )
    mode.add_argument(
        "--run", action="store_true", help="Explicitly execute the planned continuation"
    )
    args = vars(parser.parse_args(argv))
    args.pop("plan_only")
    try:
        _validate_paths(
            args["origin"],
            args["project_root"],
            args["output_root"],
            args["frozen_source"],
            args["log_file"],
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    try:
        result = continue_replication(**args)
        print(json.dumps(result, indent=2))
        if result["mode"] == "run":
            counts = result["summary"]["statuses"]
            successes = counts.get("completed", 0) + counts.get("budget_exhausted", 0)
            origin = result["retained_origin_statuses"]
            if (
                successes != result["continuation_scheduled"]
                or origin.get("failed", 0)
                or origin.get("skipped", 0)
            ):
                return 1
        return 0
    except BaseException as error:
        _log(
            args["log_file"],
            {
                "status": "error",
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
