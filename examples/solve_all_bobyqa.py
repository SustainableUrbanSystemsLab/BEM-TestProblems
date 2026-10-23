# SPDX-License-Identifier: MIT
"""Solve the ten continuous benchmarks locally with PDFO BOBYQA.

Run from the repository root after completing the README setup:
    python examples/solve_all_bobyqa.py
    python examples/solve_all_bobyqa.py --workers auto
    python examples/solve_all_bobyqa.py --workers 4
    python examples/solve_all_bobyqa.py --canonical-models

Problems run sequentially by default. --workers auto uses CPU count minus two,
with at least one worker and at most one worker per problem.
Defaults: historical HVAC compatibility for P6/P8, corrected v3 models for
P1/P3/P4/P5/P9/P10, and canonical models for P2/P13. Use --canonical-models
to select the original benchmark models for every problem.
The function-evaluation budget is 100 * (n + 1), where n is the dimension.
Each invocation creates a fresh results directory. Simulation failures are
recorded with their diagnostics; the remaining problems are still attempted.
"""

import argparse
import json
import math
import os
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from importlib.metadata import version
from multiprocessing import get_context
from pathlib import Path
from tempfile import mkdtemp
from time import perf_counter

from bem_testproblems import get_problem, make_objective
from bem_testproblems.problems import PROBLEM_IDS


def solve_problem(problem_id, directory, corrected_models=True):
    """Attempt one bounded search and save its result, including any error."""
    from pdfo import pdfo

    problem = get_problem(
        problem_id, numerical_variant="replication" if corrected_models else "canonical"
    )
    variant = problem.numerical_variant
    print(f"P{problem_id}: starting; model={variant or 'canonical'}; EnergyPlus 26.2.0", flush=True)
    max_evaluations = 100 * (problem.dimension + 1)
    options = {"maxfev": max_evaluations, "scale": True, "honour_x0": True}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    record = {
        "problem": problem.id,
        "model": variant or "canonical",
        "provenance": problem.provenance,
        "energyplus_version": "26.2.0",
        "solver": "PDFO BOBYQA",
        "pdfo_version": version("pdfo"),
        "max_evaluations": max_evaluations,
        "solver_options": options,
        "parameter_names": [parameter.name for parameter in problem.parameters],
        "bounds": problem.bounds,
        "starting_point": problem.midpoint,
        "objective_unit": problem.objective_unit,
        "objective": None,
        "best_objective": None,
    }
    started = perf_counter()
    try:
        objective = make_objective(
            problem, energyplus_version="26.2.0", output_root=directory / "native"
        )
        result = pdfo(
            objective,
            x0=problem.midpoint,
            bounds=problem.bounds,
            method="bobyqa",
            options=options,
        )
        parameters = problem.validate(result.x)
        if not math.isfinite(result.fun):
            raise ValueError("BOBYQA returned a nonfinite objective")
        record.update(
            outcome="completed",
            parameters=parameters,
            objective=float(result.fun),
            best_objective=float(min(result.fun_history)),
            evaluations=int(result.nfev),
            converged=bool(result.success),
            solver_status=int(result.status),
            message=str(result.message),
        )
    except Exception as error:
        record.update(outcome="failed", error=f"{type(error).__name__}: {error}")
        (directory / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
    record["elapsed_seconds"] = perf_counter() - started
    (directory / "result.json").write_text(
        json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return record


def worker_count(value):
    """Accept an explicit worker count or leave two logical CPUs available."""
    if value == "auto":
        return max(1, (os.cpu_count() or 1) - 2)
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Use a positive integer or 'auto'") from None
    if count < 1:
        raise argparse.ArgumentTypeError("Workers must be at least 1")
    return count


def limit_worker_threads():
    """Set thread limits before a spawned worker imports NumPy or PDFO."""
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"


def run_problems(directory, corrected_models, workers):
    """Yield each problem's result as it finishes, using isolated processes."""
    if workers == 1:
        for number in PROBLEM_IDS:
            yield solve_problem(number, directory / f"P{number}", corrected_models)
        return
    with ProcessPoolExecutor(
        max_workers=workers, mp_context=get_context("spawn"), initializer=limit_worker_threads,
    ) as pool:
        futures = [pool.submit(solve_problem, number, directory / f"P{number}", corrected_models)
                   for number in PROBLEM_IDS]
        for future in as_completed(futures):
            yield future.result()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".validation-local/bobyqa"),
        help="Parent directory for a fresh run folder",
    )
    parser.add_argument(
        "--workers", type=worker_count, default=1, metavar="N|auto",
        help="Parallel problems (default: 1); auto uses logical CPU count minus two, capped at ten",
    )
    models = parser.add_mutually_exclusive_group()
    models.add_argument(
        "--canonical-models", dest="corrected_models", action="store_false",
        help="Use the original benchmark models",
    )
    models.add_argument(
        "--corrected-models", dest="corrected_models", action="store_true",
        help="Use corrected models, including historical HVAC for P6/P8 (default)",
    )
    parser.set_defaults(corrected_models=True)
    args = parser.parse_args()
    workers = min(args.workers, len(PROBLEM_IDS))
    args.output.mkdir(parents=True, exist_ok=True)
    directory = Path(mkdtemp(prefix="run-", dir=args.output)).resolve()
    print(f"Results: {directory}", flush=True)
    profile = ("historical-hvac for P6/P8; corrected v3 for P1/P3/P4/P5/P9/P10; "
               "canonical for P2/P13") if args.corrected_models else "canonical"
    print(f"Models: {profile}", flush=True)
    print(f"Workers: {workers} for {len(PROBLEM_IDS)} problems", flush=True)
    failures = 0
    for index, result in enumerate(run_problems(directory, args.corrected_models, workers), start=1):
        number = result["problem"]
        failures += result["outcome"] == "failed"
        detail = result.get("message", result.get("error"))
        print(
            f"[{index}/{len(PROBLEM_IDS)}] P{number}: {result['outcome']} "
            f"in {result['elapsed_seconds']:.1f}s; {detail}",
            flush=True,
        )
        for label, key in (
            ("Final objective", "objective"),
            ("Best observed objective", "best_objective"),
        ):
            value = result[key]
            text = "unavailable" if value is None else f"{value:.12g} {result['objective_unit']}"
            print(f"  {label}: {text}", flush=True)
    print(f"Finished: {len(PROBLEM_IDS) - failures} completed, {failures} failed. {directory}")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
