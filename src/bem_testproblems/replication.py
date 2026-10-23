# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Seeded, isolated and resumable local optimization experiments.

Interrupted solvers restart from their recorded seed and initial point; this is
run-level resumption, not serialization of a solver's internal numerical state.
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import platform
import random
import re
import shutil
import socket
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from importlib import import_module, util
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from importlib.resources import files
from pathlib import Path

from .energyplus import EnergyPlusRunner, _version, sha256_file, supporting_file_hashes
from .evaluation import _default_project_root, make_objective
from .outputs import extract_outputs
from .problems import PROBLEM_IDS, get_problem
from .reference import legacy_template_path
from .replication_journal import TraceJournal, read_checkpoint
from .replication_solvers import SOLVER_ORDER, solve_solver, solver_metadata

TERMINAL_STATUSES = frozenset({"completed", "budget_exhausted", "failed", "skipped"})
PAPER_REPETITIONS = 20
WORKER_THREAD_VARIABLES = (
    "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS",
)


class EvaluationBudgetExceeded(RuntimeError):
    """The next objective call would exceed the complete run's hard budget."""


def _error_record(error):
    directory = getattr(error, "directory", None)
    record = {"type": type(error).__name__, "message": str(error),
              "reason": getattr(error, "reason", None),
              "directory": str(directory) if directory is not None else None}
    diagnostics = Path(directory) / "eplusout.err" if directory is not None else None
    if diagnostics is not None and diagnostics.is_file():
        text = diagnostics.read_text(errors="replace")
        record.update(severe_count=len(re.findall(r"\*\*\s*Severe\s*\*\*", text)),
                      fatal_count=len(re.findall(r"\*\*\s*Fatal\s*\*\*", text)),
                      diagnostic_sha256=sha256_file(diagnostics),
                      diagnostic_lines=[line.strip() for line in text.splitlines() if
                                        any(key in line for key in ("Severe", "Fatal", "Comparison", "Environment("))])
    return record


def _json_value(value):
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_value(value.tolist())
    if hasattr(value, "item"):
        return _json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _digest(value):
    return hashlib.sha256(json.dumps(_json_value(value), sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(_json_value(value), indent=2, allow_nan=False) + "\n",
                             encoding="utf-8")
        for attempt in range(6):
            try:
                temporary.replace(path)
                break
            except PermissionError as error:
                # Windows readers or scanners can briefly block atomic replacement.
                if getattr(error, "winerror", None) not in (5, 32) or attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def _seed(master, *parts):
    return int(_digest([master, *parts])[:15], 16) % (2**31 - 1)


def _positive_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def paired_start(problem, repetition, seed):
    """Uniform physical coordinates shared across solvers and engine versions."""
    generator = random.Random(_seed(seed, "start", problem.id, repetition))
    return tuple(generator.uniform(lower, upper) for lower, upper in problem.bounds)


def _model_identity(problem, version):
    if version == "8.5.0":
        identity = {"format": "IDF", "template_sha256": sha256_file(
            legacy_template_path(problem.template_filename))}
    else:
        data = files("bem_testproblems").joinpath("data", "modern")
        number = 6 if problem.id == 8 else problem.id
        identity = {"format": "epJSON", "template_sha256": hashlib.sha256(
            data.joinpath(f"problem_{number}.epJSON").read_bytes()).hexdigest(),
            "bindings_sha256": hashlib.sha256(data.joinpath(
                "parameter_bindings.json").read_bytes()).hexdigest()}
    if problem.numerical_variant is not None:
        identity["numerical_variant"] = problem.provenance["numerical_variant"]
    return identity


def _weather_identity(problem, directory):
    if problem.design_day:
        return {"filename": None, "sha256": None, "mode": "embedded-design-day"}
    path = directory / problem.weather_filename
    manifest = json.loads(files("bem_testproblems").joinpath(
        "data", "weather-assets.json").read_bytes())
    expected = next(item["sha256"] for item in manifest["files"]
                    if item["cache_path"] == problem.weather_filename)
    if not path.is_file():
        raise FileNotFoundError(f"Canonical weather missing: {path}; run tools/fetch_weather.py")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"Canonical weather checksum mismatch: {path}")
    return {"filename": path.name, "sha256": actual, "mode": "canonical-annual"}


def _dependency_identity(name):
    distribution = {"pybobyqa": "Py-BOBYQA"}.get(name, name)
    try:
        origin = util.find_spec(name)
    except (ImportError, ValueError):
        origin = None
    if origin is None:
        return {"available": False, "distribution_version": None, "runtime_version": None}
    try:
        installed = package_version(distribution)
    except PackageNotFoundError:
        installed = None
    module = import_module(name)
    runtime = getattr(module, "__version__", None)
    if name == "nlopt":
        runtime = ".".join(str(getattr(module, "version_" + part)())
                           for part in ("major", "minor", "bugfix"))
    path = Path(origin.origin) if origin.origin else None
    native = {}
    if path is not None and path.is_file():
        for candidate in path.parent.iterdir():
            if candidate.is_file() and candidate.suffix in {".so", ".pyd", ".dylib"}:
                native[candidate.name] = sha256_file(candidate)
    return {"available": True, "distribution_version": installed,
            "runtime_version": str(runtime) if runtime is not None else None,
            "entrypoint_sha256": sha256_file(path) if path is not None and path.is_file() else None,
            "native_sha256": native}


def prepare_manifest(*, problems=PROBLEM_IDS, solvers=None, versions=("8.5.0", "26.2.0"),
                     repetitions=20, budget=None, budget_multiplier=1, seed=2019, project_root=None,
                     executables=None, weather_dir=None, diagnostics_policy="strict",
                     schedule="balanced", p1_warmup_100=False, native_solvers=None,
                     numerical_variant=None):
    """Resolve all inputs and fixed random starts without running simulations."""
    repetitions = _positive_integer(repetitions, "repetitions")
    if budget is not None:
        _positive_integer(budget, "budget")
    _positive_integer(budget_multiplier, "budget_multiplier")
    if budget is not None and budget_multiplier != 1:
        raise ValueError("budget and budget_multiplier cannot both override the paper budget")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if diagnostics_policy not in {"strict", "reference-warmup"}:
        raise ValueError("diagnostics_policy must be strict or reference-warmup")
    if schedule not in {"balanced", "problem-first"}:
        raise ValueError("schedule must be balanced or problem-first")
    if not isinstance(p1_warmup_100, bool):
        raise ValueError("p1_warmup_100 must be a boolean")
    if numerical_variant not in (None, "convergence-refined", "convergence-repaired", "model-corrected", "model-corrected-v2", "model-corrected-v3", "historical-hvac"):
        raise ValueError("Unsupported replication numerical variant")
    if numerical_variant is not None and p1_warmup_100:
        raise ValueError("Select one numerical variant")
    definitions = [get_problem(number) for number in problems]
    if not definitions or len({p.id for p in definitions}) != len(definitions):
        raise ValueError("Select at least one problem, without duplicates")
    if numerical_variant is not None:
        from .historical_hvac import HISTORICAL_HVAC_PROBLEMS
        from .model_controls import CORRECTED_PROBLEM_IDS
        from .numerical_controls import REFINED_PROBLEM_IDS, REPAIRED_PROBLEM_IDS

        selected = {"convergence-repaired": REPAIRED_PROBLEM_IDS, "convergence-refined": REFINED_PROBLEM_IDS,
                    "model-corrected": CORRECTED_PROBLEM_IDS,
                    "model-corrected-v2": CORRECTED_PROBLEM_IDS,
                    "model-corrected-v3": CORRECTED_PROBLEM_IDS,
                    "historical-hvac": HISTORICAL_HVAC_PROBLEMS}[numerical_variant]
        definitions = [get_problem(p.id, numerical_variant=numerical_variant)
                       if p.id in selected else p for p in definitions]
    if p1_warmup_100:
        if not any(problem.id == 1 for problem in definitions):
            raise ValueError("p1_warmup_100 requires problem 1 to be selected")
        definitions = [get_problem(1, numerical_variant="warmup-100") if problem.id == 1
                       else problem for problem in definitions]
    selected_solvers = [solver_metadata(name)["name"] for name in (
        SOLVER_ORDER if solvers is None else solvers)]
    if not selected_solvers or len(set(selected_solvers)) != len(selected_solvers):
        raise ValueError("Select at least one solver, without duplicates")
    metadata = {name: solver_metadata(name) for name in selected_solvers}
    native = None
    if native_solvers is not None:
        from .replication_native import load_configuration, slider_profile, solver_settings

        native = load_configuration(native_solvers, selected_solvers)
        for name in selected_solvers:
            backend = native["backends"]["galapagos" if name.startswith("galapagos_") else "bbo"]
            metadata[name].update(implemented=True, available=True, skip_reason=None,
                source=backend["source"], dependency=None,
                settings_by_dimension={str(p.dimension): solver_settings(name, p.dimension)
                                       for p in definitions},
                fidelity="Recovered original binary and saved GH slider interface. "
                    "Source/paper preset conflicts and exact study build remain under review; "
                    "journal-equivalent results are not claimed.")
    selected_versions = [_version(str(version)) for version in versions]
    if not selected_versions or len(set(selected_versions)) != len(selected_versions):
        raise ValueError("Select supported engine versions, without duplicates")
    base = Path(project_root).expanduser().resolve() if project_root else _default_project_root()
    weather_directory = Path(weather_dir).expanduser().resolve() if weather_dir else base / ".cache/weather"
    paths = {_version(str(key)): Path(value).expanduser().resolve()
             for key, value in (executables or {}).items()}
    engines = {}
    for version in selected_versions:
        path = paths.get(version, base / ".tools/energyplus" / version / (
            "energyplus.exe" if os.name == "nt" else "energyplus"))
        runner = EnergyPlusRunner(path, expected_version=version, cache=False)
        supporting = supporting_file_hashes(path)
        engines[version] = {"executable": str(path), "executable_sha256": runner.executable_sha256,
                            "version_output": runner.version_output, "supporting_sha256": supporting}
    identities = {str(p.id): {"name": p.name, "dimension": p.dimension,
        "bounds": p.bounds, "parameter_names": [x.name for x in p.parameters],
        "objective_unit": p.objective_unit, "weather": _weather_identity(p, weather_directory),
        "models": {version: _model_identity(p, version) for version in selected_versions}}
        for p in definitions}
    for problem in definitions:
        if problem.numerical_variant is not None:
            identities[str(problem.id)]["numerical_variant"] = problem.numerical_variant
    source = Path(__file__).parent
    code_hashes = {name: sha256_file(source / name) for name in (
        "problems.py", "losses.py", "models.py", "numerical_controls.py", "model_controls.py", "outputs.py", "energyplus.py",
        "evaluation.py", "replication.py", "replication_solvers.py", "replication_diagnostics.py",
        "replication_journal.py")}
    specifications = []
    for repetition in range(repetitions):
        for p in definitions:
            random_start = paired_start(p, repetition, seed)
            for solver in selected_solvers:
                start = p.midpoint if solver == "direct" else random_start
                for version in selected_versions:
                    specifications.append({"id": f"p{p.id:02}-{version}-{solver}-r{repetition:03}",
                        "problem": p.id, "version": version, "solver": solver,
                        "repetition": repetition, "seed": _seed(seed, "solver", p.id, repetition, solver),
                        "x0": start, "budget": budget if budget is not None else
                        100 * (p.dimension + 1) * budget_multiplier})
    if schedule == "problem-first":
        problem_order = {problem.id: index for index, problem in enumerate(definitions)}
        solver_order = {name: index for index, name in enumerate(selected_solvers)}
        version_order = {version: index for index, version in enumerate(selected_versions)}
        specifications.sort(key=lambda run: (
            problem_order[run["problem"]], run["repetition"],
            solver_order[run["solver"]], version_order[run["version"]]))
    configuration = {"schema_version": 1, "protocol": "paper-start-and-budget-protocol"
        if repetitions == 20 and budget is None else "pilot-overrides",
        "paper_doi": "10.1016/j.enbuild.2019.01.048", "requested_repetitions": repetitions,
        "budget_override": budget, "paper_budget_rule": "100*(dimension+1)", "master_seed": seed,
        "start_policy": "Uniform physical-box starts, paired across engines/solvers; DIRECT uses midpoint",
        "resume_policy": "Restart interrupted solvers from fixed original start/seed; skip terminal runs",
        "publication_equivalence": "Not claimed; per-solver metadata records settings, differences and skips",
        "diagnostics_policy": diagnostics_policy,
        "diagnostics_policy_scope": "Strict is the ordinary benchmark API. Reference-warmup is an "
            "explicit experiment variant reflecting the original caller's handling of completed "
            "runs with warmup-only Severe diagnostics; Fatal and other Severe errors still reject.",
        "project_root": str(base), "weather_directory": str(weather_directory),
        "platform": platform.system() + "-" + platform.machine(), "engines": engines,
        "problem_definitions": identities, "solvers": metadata,
        "solver_order": list(SOLVER_ORDER), "solver_registry": solver_metadata(),
        "omitted_solvers": {name: solver_metadata(name) for name in SOLVER_ORDER
                            if name not in selected_solvers},
        "dependency_provenance": {name: _dependency_identity(name) for name in
            sorted({item["dependency"] for item in metadata.values() if item.get("dependency")}
                   | {"numpy", "scipy"})},
        "schedule": schedule,
        "schedule_order": "Repetition first, then selected problem, solver and engine order"
            if schedule == "balanced" else
            "Selected problem first, then repetition, solver and engine order",
        "code_sha256": code_hashes,
        "runs": specifications}
    if p1_warmup_100:
        configuration["p1_warmup_100"] = True
    if numerical_variant is not None:
        configuration["numerical_variant"] = numerical_variant
    if native is not None:
        configuration["native_solvers"] = native
        configuration["code_sha256"]["replication_native.py"] = sha256_file(
            source / "replication_native.py")
        configuration["start_policy"] += (
            "; native methods use the initialization recorded in settings_by_dimension")
        for problem in definitions:
            configuration["problem_definitions"][str(problem.id)]["slider_interface"] = slider_profile(
                problem.id)
        configuration["solver_registry"] = [metadata.get(name, solver_metadata(name))
                                             for name in SOLVER_ORDER]
    if budget_multiplier != 1:
        configuration.update(protocol="extended-budget-experiment",
                             budget_multiplier=budget_multiplier,
                             effective_budget_rule="100*(dimension+1)*budget_multiplier")
    configuration = _json_value(configuration)
    configuration["manifest_id"] = _digest(configuration)
    return configuration


def _pid_alive(pid):
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def _experiment_lock(root):
    path = root / "experiment.lock"
    owner = {"pid": os.getpid(), "host": socket.gethostname(), "token": uuid.uuid4().hex}
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            prior = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise RuntimeError(f"Experiment lock owner is unreadable: {path}") from error
        if prior.get("host") != owner["host"] or _pid_alive(prior["pid"]):
            raise RuntimeError(f"An experiment coordinator already holds {path}") from None
        path.unlink()
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(owner, stream)
        yield
    finally:
        if path.is_file() and json.loads(path.read_text()).get("token") == owner["token"]:
            path.unlink()


class _ObservedRunner:
    def __init__(self, runner):
        self.runner = runner
        self.version = runner.version
        self.last = None
        self.attempt = {}

    def run(self, input_file, weather_file=None, *, design_day=False):
        self.attempt = {"input_sha256": sha256_file(input_file), "design_day": design_day}
        self.last = self.runner.run(input_file, weather_file, design_day=design_day)
        self.attempt.update(input_sha256=self.last.input_sha256,
                            weather_sha256=self.last.weather_sha256,
                            simulation_elapsed_seconds=self.last.elapsed,
                            simulation_directory=str(self.last.directory))
        self.attempt["diagnostics"] = getattr(self.runner, "last_diagnostics", None)
        return self.last


def _compact_success(result, attempt_root, policy):
    if result is None or policy == "all":
        return
    directory = result.directory.resolve()
    if not directory.is_relative_to(attempt_root.resolve()):
        raise RuntimeError("Refusing to clean a simulator directory outside this run")
    if policy == "none":
        shutil.rmtree(directory)
    else:
        retained = {"eplusout.err", "eplusout.end", "run.json", "stdout.log", "stderr.log"}
        for path in directory.iterdir():
            if path.name not in retained:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()


def _run_one(spec, manifest, root, retain_success):
    root = Path(root)
    checkpoint = root / "runs" / (spec["id"] + ".json")
    previous = read_checkpoint(checkpoint) if checkpoint.is_file() else None
    attempt = previous.get("attempt", 0) + 1 if previous else 1
    if previous:
        _atomic_json(root / "history" / f"{spec['id']}-attempt{attempt-1}.json", previous)
    attempt_root = root / "simulations" / spec["id"] / f"attempt{attempt:03}"
    record = {**spec, "manifest_id": manifest["manifest_id"], "attempt": attempt,
              "status": "running", "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "evaluation_count": 0, "best_x": None, "best_f": None, "trace": [],
              "problem_provenance": manifest["problem_definitions"][str(spec["problem"])],
              "engine_provenance": manifest["engines"][spec["version"]],
              "solver_metadata": manifest["solvers"][spec["solver"]],
              "success_output_retention": retain_success,
              "diagnostics_policy": manifest["diagnostics_policy"],
              "strict_benchmark_evaluation": True, "warmup_severe_evaluations_used": 0}
    started = time.monotonic()
    journal = TraceJournal(checkpoint, attempt) if manifest.get("budget_multiplier", 1) > 1 else None
    if journal is not None:
        record["measured_objective_seconds"] = 0.0

    def save(*, final=False):
        record["elapsed_seconds"] = time.monotonic() - started
        _atomic_json(checkpoint, journal.snapshot(record) if journal is not None and not final else record)

    save()
    observed = None
    failure = None
    try:
        problem = get_problem(spec["problem"], numerical_variant=record[
            "problem_provenance"].get("numerical_variant"))
        runner = EnergyPlusRunner(manifest["engines"][spec["version"]]["executable"],
            expected_version=spec["version"], output_root=attempt_root, cache=False)
        if runner.executable_sha256 != record["engine_provenance"]["executable_sha256"]:
            raise ValueError("Engine executable changed after experiment manifest creation")
        supporting = supporting_file_hashes(manifest["engines"][spec["version"]]["executable"])
        if any(supporting.get(name) != digest for name, digest in
               record["engine_provenance"].get("supporting_sha256", {}).items()):
            raise ValueError("Engine supporting files changed after experiment manifest creation")
        if _model_identity(problem, spec["version"]) != record["problem_provenance"]["models"][spec["version"]]:
            raise ValueError("Model template or bindings changed after experiment manifest creation")
        if manifest["diagnostics_policy"] == "reference-warmup":
            from .replication_diagnostics import ReferenceWarmupRunner
            runner = ReferenceWarmupRunner(runner, family=problem.family)
        observed = _ObservedRunner(runner)
        evaluate = make_objective(problem, runner=observed,
                                  weather_dir=manifest["weather_directory"])

        def objective(x):
            nonlocal failure
            if failure is not None:
                raise failure
            if record["evaluation_count"] >= spec["budget"]:
                raise EvaluationBudgetExceeded("Complete objective-call budget exhausted")
            record["evaluation_count"] += 1
            item = {"evaluation": record["evaluation_count"], "x": _json_value(x),
                    "elapsed_start_seconds": time.monotonic() - started}
            observed.last = None
            observed.attempt = {}
            evaluation_started = time.monotonic()
            try:
                problem.validate(x)
                value = float(evaluate(x))
                if not math.isfinite(value):
                    raise ValueError("Nonfinite objective")
                item.update(status="success", f=value, **observed.attempt)
                if observed.last is not None:
                    item["components"] = extract_outputs(problem.family, observed.last)
                    item["diagnostic_sha256"] = {name: sha256_file(observed.last.directory / name)
                        for name in ("eplusout.err", "eplusout.end", "run.json")}
                    if item.get("diagnostics") is None:
                        text = (observed.last.directory / "eplusout.err").read_text(errors="replace")
                        final = re.search(r"Completed Successfully-- (\d+) Warning", text)
                        item["diagnostics"] = {"accepted_warmup_only": False,
                            "strict_benchmark_evaluation": True, "severe_count": 0, "fatal_count": 0,
                            "warning_count": int(final.group(1)) if final else len(
                                re.findall(r"\*\*\s*Warning\s*\*\*", text))}
                    item["strict_benchmark_evaluation"] = not item["diagnostics"].get(
                        "accepted_warmup_only", False)
                    if not item["strict_benchmark_evaluation"]:
                        record["strict_benchmark_evaluation"] = False
                        record["warmup_severe_evaluations_used"] += 1
                if record["best_f"] is None or value < record["best_f"]:
                    record["best_x"], record["best_f"] = _json_value(x), value
            except BaseException as error:
                failure = error
                item.update(status="failed", f=None, **observed.attempt,
                            error=_error_record(error))
                raise
            finally:
                item["evaluation_elapsed_seconds"] = time.monotonic() - evaluation_started
                record["trace"].append(item)
                if journal is not None:
                    record["measured_objective_seconds"] += item["evaluation_elapsed_seconds"]
                save()
            # Persist the value, components and hashes before removing large
            # outputs. The runner cache is disabled; no deleted output is reused.
            try:
                _compact_success(observed.last, attempt_root, "diagnostics" if not item.get(
                    "strict_benchmark_evaluation", True) and retain_success == "none" else retain_success)
            except OSError as error:
                item["cleanup_warning"] = str(error)
                if journal is not None:
                    journal.cleanup_warning(record["evaluation_count"], str(error))
                save()
            return value

        if "native_solvers" in manifest:
            from .replication_native import solve

            result = solve(spec, manifest["native_solvers"], objective,
                           attempt_root / "solver-protocol.jsonl")
        else:
            result = solve_solver(spec["solver"], objective, spec["x0"],
                                  problem.bounds, spec["budget"], spec["seed"])
        if failure is not None:
            raise failure
        record["solver_result"] = _json_value(result)
        status = result.get("status", "completed")
        if status == "skipped":
            record["status"] = "skipped"
        elif status in {"budget", "budget_exhausted"}:
            record["status"] = "budget_exhausted"
        else:
            record["status"] = "completed"
        record["message"] = str(result.get("message", ""))
        record["solver_termination"] = status
        record["solver_success"] = result.get("success")
        native = result.get("native_status")
        known = {"skipped", "budget", "budget_exhausted", "terminated", "roundoff", "completed"}
        if status not in known or (isinstance(native, int) and native < 0 and status != "roundoff"):
            record.update(status="failed", error={"type": "SolverTermination",
                          "reason": "solver", "message": record["message"]})
        record["optimizer_termination_warning"] = bool(record["status"] == "completed"
            and record["best_f"] is not None and result.get("success") is False)
        if record["status"] != "skipped" and record["best_f"] is None:
            raise RuntimeError("Solver terminated without a valid objective observation")
    except EvaluationBudgetExceeded as error:
        record.update(status="budget_exhausted", message=str(error),
                      solver_termination="outer-objective-budget", solver_success=False)
    except BaseException as error:
        record.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                      error=_error_record(error))
    finally:
        record["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        save(final=True)
    return record


def _run_one_checkpointed(*args):
    """Keep large traces on disk rather than pickling them into coordinator futures."""
    _run_one(*args)


def _summary(root, manifest, workers, *, cache=None):
    # This optional cache contains progress counters only. Scientific review
    # still validates every original checkpoint and its complete observations.
    cache = {} if cache is None else cache
    totals = dict.fromkeys((*sorted(TERMINAL_STATUSES), "running", "interrupted"), 0)
    evaluated = measured = elapsed = warmup = warnings = 0
    terminal_ids = set()
    for path in (root / "runs").glob("*.json"):
        stat = path.stat()
        # Atomic replacement can preserve both size and timestamp on Windows.
        # Its file ID still changes; without one, reread instead of caching.
        identity = stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size
        cached = cache.get(path)
        if not stat.st_ino or cached is None or cached[0] != identity:
            row = json.loads(path.read_text())
            measured_seconds = row.get("measured_objective_seconds")
            if measured_seconds is None:
                row = read_checkpoint(path, row)
                measured_seconds = sum(item["evaluation_elapsed_seconds"] for item in row["trace"])
            stats = {key: row[key] for key in ("id", "status", "evaluation_count", "elapsed_seconds")}
            stats.update(measured=measured_seconds,
                         warmup=row.get("warmup_severe_evaluations_used", 0),
                         warnings=row.get("optimizer_termination_warning", False))
            cache[path] = identity, stats
        else:
            stats = cached[1]
        totals[stats["status"]] += 1
        evaluated += stats["evaluation_count"]
        measured += stats["measured"]
        elapsed += stats["elapsed_seconds"]
        warmup += stats["warmup"]
        warnings += stats["warnings"]
        if stats["status"] in TERMINAL_STATUSES:
            terminal_ids.add(stats["id"])
    remaining_budget = sum(row["budget"] for row in manifest["runs"] if row["id"] not in terminal_ids)
    seconds_per_call = measured / evaluated if evaluated else None
    value = {"manifest_id": manifest["manifest_id"], "protocol": manifest["protocol"],
             "requested_runs": len(manifest["runs"]), "statuses": totals,
             "evaluation_count": evaluated, "worker_elapsed_seconds": elapsed,
             "measured_objective_seconds": measured,
             "mean_seconds_per_attempted_evaluation": seconds_per_call,
             "remaining_full_budget_ceiling": remaining_budget, "workers": workers,
             "diagnostics_policy": manifest["diagnostics_policy"],
             "warmup_severe_evaluations_used": warmup,
             "optimizer_termination_warning_runs": warnings,
             "requested_implemented_runs": sum(manifest["solvers"][row["solver"]].get(
                 "implemented", False) for row in manifest["runs"]),
             "estimated_remaining_seconds": remaining_budget * seconds_per_call / workers
                 if seconds_per_call is not None else None,
             "estimate_limits": "A throughput estimate, not an ETA: solver overhead, contention, "
                                "design-specific runtime and strict early failures affect completion."}
    _atomic_json(root / "summary.json", value)
    return value


def worker_pool_partition(specifications, workers):
    """Partition a large worker allocation into Windows-safe spawn pools.

    Each pool has at most 60 workers. For multiple pools, assign expensive
    budgets first to balance estimated work per worker without duplicating runs.
    A single pool retains the manifest's requested scheduling order.
    """
    _positive_integer(workers, "workers")
    count = (workers + 59) // 60
    sizes = [workers // count + (index < workers % count) for index in range(count)]
    if count == 1:
        return [(workers, list(specifications))]
    groups = [[] for _ in sizes]
    loads = [0] * count
    for spec in sorted(specifications, key=lambda row: (-row["budget"], row["id"])):
        index = min(range(count), key=lambda item: (loads[item] / sizes[item], item))
        groups[index].append(spec)
        loads[index] += spec["budget"]
    return list(zip(sizes, groups))


@contextmanager
def _worker_thread_environment():
    """Spawn one native numerical thread per worker, restoring the caller's env."""
    previous = {name: os.environ.get(name) for name in WORKER_THREAD_VARIABLES}
    try:
        os.environ.update(dict.fromkeys(WORKER_THREAD_VARIABLES, "1"))
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def run_replication(*, output_root=None, workers=8, retain_success="none", retry_failed=False,
                    budget_multiplier=1, **configuration):
    """Run isolated solver processes; checkpoint every successful or failed call."""
    _positive_integer(workers, "workers")
    if retain_success not in {"none", "diagnostics", "all"}:
        raise ValueError("retain_success must be none, diagnostics or all")
    manifest = prepare_manifest(budget_multiplier=budget_multiplier, **configuration)
    root = Path(output_root or Path(manifest["project_root"]) / ".validation-local/replication").expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _experiment_lock(root):
        prior_path = root / "manifest.json"
        if prior_path.is_file():
            prior = json.loads(prior_path.read_text())
            if prior["manifest_id"] != manifest["manifest_id"]:
                raise ValueError("Existing experiment manifest differs; use a separate output root")
        else:
            _atomic_json(prior_path, manifest)
        (root / "runs").mkdir(exist_ok=True)
        summary_cache = {}
        pending = []
        for spec in manifest["runs"]:
            path = root / "runs" / (spec["id"] + ".json")
            if path.is_file():
                prior = read_checkpoint(path)
                if prior["manifest_id"] != manifest["manifest_id"]:
                    raise ValueError(f"Run checkpoint provenance does not match: {path}")
                if prior["status"] in TERMINAL_STATUSES and not (
                        retry_failed and prior["status"] == "failed"):
                    continue
            pending.append(spec)
        if workers == 1:
            for spec in pending:
                _run_one(spec, manifest, root, retain_success)
                _summary(root, manifest, workers, cache=summary_cache)
        elif pending:
            with _worker_thread_environment(), ExitStack() as stack:
                jobs = {}
                for size, specs in worker_pool_partition(pending, workers):
                    if not specs:
                        continue
                    pool = stack.enter_context(ProcessPoolExecutor(
                        max_workers=size, mp_context=multiprocessing.get_context("spawn")))
                    for spec in specs:
                        jobs[pool.submit(_run_one_checkpointed, spec, manifest, str(root), retain_success)] = spec
                for future in as_completed(jobs):
                    try:
                        future.result()
                    except Exception as error:
                        spec = jobs[future]
                        path = root / "runs" / (spec["id"] + ".json")
                        row = read_checkpoint(path) if path.is_file() else {
                            **spec, "manifest_id": manifest["manifest_id"], "evaluation_count": 0,
                            "best_x": None, "best_f": None, "trace": [], "elapsed_seconds": 0,
                            "attempt": 0,
                            "problem_provenance": manifest["problem_definitions"][str(spec["problem"])],
                            "engine_provenance": manifest["engines"][spec["version"]],
                            "solver_metadata": manifest["solvers"][spec["solver"]],
                            "diagnostics_policy": manifest["diagnostics_policy"],
                            "strict_benchmark_evaluation": True, "warmup_severe_evaluations_used": 0}
                        row.update(status="interrupted", error={"type": type(error).__name__,
                                   "message": str(error), "reason": "worker-process-failure"})
                        _atomic_json(path, row)
                    _summary(root, manifest, workers, cache=summary_cache)
        return _summary(root, manifest, workers, cache=summary_cache)
