# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Run or resume paired local experiments; no simulator or weather downloads."""

import argparse
import json
from pathlib import Path

from bem_testproblems.problems import PROBLEM_IDS
from bem_testproblems.replication import run_replication
from bem_testproblems.replication_solvers import SOLVER_ORDER


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problems", nargs="+", default=list(PROBLEM_IDS))
    parser.add_argument("--solvers", nargs="+", choices=SOLVER_ORDER)
    parser.add_argument("--versions", nargs="+", choices=("8.5.0", "26.2.0"),
                        default=["8.5.0", "26.2.0"])
    parser.add_argument("--repetitions", type=int, default=20)
    budgets = parser.add_mutually_exclusive_group()
    budgets.add_argument("--budget", type=int,
                         help="Override 100*(n+1); labels the experiment as a pilot")
    budgets.add_argument("--budget-multiplier", type=int, default=1,
                         help="Multiply 100*(n+1); values above 1 label an extended-budget experiment")
    parser.add_argument("--seed", type=int, default=2019)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--schedule", choices=("balanced", "problem-first"), default="balanced")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--weather-dir", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--executable-8-5", type=Path)
    parser.add_argument("--executable-26-2", type=Path)
    parser.add_argument("--retain-success", choices=("none", "diagnostics", "all"), default="none")
    parser.add_argument("--diagnostics-policy", choices=("strict", "reference-warmup"), default="strict")
    parser.add_argument("--native-solvers", type=Path,
                        help="Opt into a private hash-pinned original BB-O/Galapagos configuration")
    parser.add_argument("--numerical-variant", choices=("convergence-refined", "convergence-repaired", "model-corrected", "model-corrected-v2", "model-corrected-v3"),
                        help="Explicit numerical or labelled model correction profile for affected problems")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--p1-warmup-100", action="store_true",
                        help="Use the explicit P1 warmup-100 numerical model variant")
    args = vars(parser.parse_args(argv))
    args["executables"] = {version: path for version, path in (
        ("8.5.0", args.pop("executable_8_5")), ("26.2.0", args.pop("executable_26_2"))) if path}
    print(json.dumps(run_replication(**args), indent=2))


if __name__ == "__main__":
    main()
