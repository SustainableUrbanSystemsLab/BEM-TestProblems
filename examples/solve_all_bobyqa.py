# SPDX-License-Identifier: MIT
"""Solve the ten continuous benchmarks locally with PDFO BOBYQA.

Run from the repository root after completing the README setup:
    python examples/solve_all_bobyqa.py
    python examples/solve_all_bobyqa.py --canonical-models

Corrected v3 models are the default where available. Use --canonical-models
to select the original benchmark models instead.
The function-evaluation budget is 100 * (n + 1), where n is the dimension.
Each invocation creates a fresh results directory. Simulation failures are
recorded with their diagnostics; the remaining problems are still attempted.
"""

import argparse
import json
import math
import traceback
from importlib.metadata import version
from pathlib import Path
from tempfile import mkdtemp
from time import perf_counter

from pdfo import pdfo

from bem_testproblems import get_problem, make_objective
from bem_testproblems.model_controls import CORRECTED_PROBLEM_IDS
from bem_testproblems.problems import PROBLEM_IDS


def solve_problem(problem_id, directory, corrected_models=True):
    """Attempt one bounded search and save its result, including any error."""
    variant = None
    if corrected_models and problem_id in CORRECTED_PROBLEM_IDS:
        variant = "model-corrected-v3"
    problem = get_problem(problem_id, numerical_variant=variant)
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


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--output", type=Path, default=Path(".validation-local/bobyqa"),
        help="Parent directory for a fresh run folder",
    )
    models = parser.add_mutually_exclusive_group()
    models.add_argument(
        "--canonical-models", dest="corrected_models", action="store_false",
        help="Use the original benchmark models",
    )
    models.add_argument(
        "--corrected-models", dest="corrected_models", action="store_true",
        help="Use corrected v3 models where available (default)",
    )
    parser.set_defaults(corrected_models=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    directory = Path(mkdtemp(prefix="run-", dir=args.output)).resolve()
    print(f"Results: {directory}", flush=True)
    profile = "corrected v3 where available" if args.corrected_models else "canonical"
    print(f"Models: {profile}", flush=True)
    failures = 0
    for index, number in enumerate(PROBLEM_IDS, start=1):
        print(f"[{index}/{len(PROBLEM_IDS)}] P{number}: starting", flush=True)
        result = solve_problem(number, directory / f"P{number}", args.corrected_models)
        failures += result["outcome"] == "failed"
        detail = result.get("message", result.get("error"))
        print(
            f"P{number}: {result['outcome']} in {result['elapsed_seconds']:.1f}s; {detail}",
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
