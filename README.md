# BEM-TestProblems

Building energy optimization problems for testing your solver in Python. Choose
a problem, get its objective and bounds, and let the package handle EnergyPlus.

This package implements ten problems with continuous variables selected from the
benchmark in
[Waibel, Wortmann, Evins, and Carmeliet (2019)](https://doi.org/10.1016/j.enbuild.2019.01.048)
and Christoph Waibel's ETH Zurich dissertation,
[*Simulation-Based Optimization of Buildings and Multi-Energy Systems* (2018)](https://doi.org/10.3929/ethz-b-000307674).
Problem numbers follow the original study. The [references](docs/references.md)
also credit the earlier studies on which these benchmarks build.

All ten use box constraints: each optimization variable has a lower and an upper
bound.

| Problem number | Optimization variables | Box constraints |
|---|---:|---|
| 1 | 4 | Yes |
| 2 | 4 | Yes |
| 3 | 4 | Yes |
| 4 | 13 | Yes |
| 5 | 13 | Yes |
| 6 | 13 | Yes |
| 8 | 11 | Yes |
| 9 | 13 | Yes |
| 10 | 13 | Yes |
| 13 | 10 | Yes |

For the FOAM experiments, report and boxplot locations, and next-session
instructions, read [the FOAM handoff](docs/foam-takeover.md). Detailed session
notes are saved on FOAM at `.validation-local/SESSION-HANDOFF-20261023-RERUN.txt`
and remain outside Git.

## Set up locally

Use Python 3.12. From the repository root on macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -c constraints/replication-py312.txt -e '.[optimize]'
.venv/bin/python tools/install_energyplus.py
.venv/bin/python tools/fetch_weather.py
```

On Windows, create the environment with `py -3.12 -m venv .venv` and use
`.venv\Scripts\python.exe` in place of `.venv/bin/python` in subsequent commands.

These commands install EnergyPlus and download the benchmark weather into this
project, with checksum verification. The `optimize` extra installs SciPy and
PDFO BOBYQA for the examples below. These commands leave the system PATH unchanged.
Once set up, evaluations run offline. The default engine is EnergyPlus 26.2;
the [engine guide](docs/engine-versions.md) explains how to use historical 8.5
models and a compatible local engine.

For the experiment pipeline, combined reports, native replay checks, and
reviewed GitHub results, start with the [replication workflow](replication/README.md).
The [Windows guide](docs/windows-continuation.md) covers installation and persistent jobs.

## Solve with SciPy

After setup, start the virtual environment's Python console with `.venv/bin/python`
on macOS/Linux or `.venv\Scripts\python.exe` on Windows. Paste the entire example
below to run an optimization.

This complete example uses problem 13, which needs no weather file, and
[SciPy's Powell method](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-powell.html),
which supports box bounds and needs only objective evaluations:

```python
from scipy.optimize import minimize

from bem_testproblems import get_problem, make_objective

problem = get_problem(13)
objective = make_objective(problem)
x0 = problem.midpoint  # A feasible starting point
bounds = problem.bounds  # (lower, upper) pairs in parameter order
result = minimize(
    objective,
    x0=x0,
    bounds=bounds,
    method="Powell",
    options={"maxfev": 100},
)

print("Parameters:", result.x)
print("Objective:", result.fun, problem.objective_unit)
print("Evaluations:", result.nfev)
print("Converged:", result.success, result.message)
```

The package handles EnergyPlus for each objective evaluation. The 100-call
budget is illustrative and may be reached before convergence; increase
`maxfev` for a longer search, and inspect the termination message.

To use your own solver, pass it `objective`, `x0`, and `bounds`. It should minimize
`objective(x)`, where `x` contains the physical parameter values. Reuse the
callable throughout the run; repeated successful evaluations are cached.
For separate bound vectors, use `lower, upper = zip(*bounds)`.

The number of optimization variables is `problem.dimension`. Parameter names,
paper symbols, units, and bounds are available through `problem.parameters`;
the [parameter guide](docs/parameters.md) explains their physical meaning.
The midpoint is a convenient start; the study's original starting vectors are
unavailable. Use `problem.validate(your_start)` to check a different start.
Inspecting problem metadata does not require EnergyPlus.

Failed simulations raise errors and retain their diagnostics. Some designs
within the bounds fail warmup convergence; the [warmup guide](docs/warmup-diagnostics.md)
explains these cases and the separately validated P1 extended-warmup option.
The [replication failure tests](docs/replication-failures.md) cover failures found
during optimization and the separately validated numerical variants.

## Solve with BOBYQA

The `optimize` extra installed above also provides PDFO BOBYQA, the package's
default optional solver:

```python
from bem_testproblems import get_problem, solve

problem = get_problem(1)
result = solve(problem, x0=problem.midpoint, max_evaluations=100)
print(result.x, result.fun)
```

The budget counts objective calls and must be at least `problem.dimension + 3`.
For solvers that exploit objective structure, see the
[simulator outputs, additive terms, and known derivatives](docs/objective-structure.md).

## Available problems

| Problems | Building and climate | Objective |
|---|---|---|
| 1, 2, 3 | Simple office: Seattle, Houston, Chicago | Primary energy, kWh/(m² year) |
| 4, 5, 6 | Detailed office: Seattle, Houston, Chicago | Primary energy, kWh/(m² year) |
| 8 | Detailed office: Chicago, two fixed parameters | Primary energy, kWh/(m² year) |
| 9, 10 | Small and large offices: San Francisco | Penalized source energy, MJ/m² |
| 13 | School: Belgrade winter design day | Energy, insulation, and radiator cost, EUR |

Problem 8 fixes the paper's `x11 = 25 °C` and `x13 = 12 °C`; its input vector
contains the eleven free parameters in their original order. Problem 13 includes
its design-day conditions and needs no weather file.

## Tests and validation

```sh
.venv/bin/python -m pip install -c constraints/replication-py312.txt -e '.[dev,optimize,replication]'
.venv/bin/python tools/fetch_reference.py
.venv/bin/python -m pytest -q -m 'not integration'
.venv/bin/python -m ruff check src tests tools
```

GitHub Actions runs tests on Linux, Windows, and macOS. It also compares Python
with the original C# implementation using EnergyPlus 8.5 and checks EnergyPlus
26.2 against measured references, using the benchmark weather. See the
[testing guide](docs/testing.md) and [reference checks](reference/README.md).

Agreement with the original code and agreement with published results are
checked separately. Some published-result discrepancies remain unresolved;
the [validation record](docs/validation.md) and
[published-design comparison](docs/published-solutions.md) explain the evidence
and its limits.

For repeated optimization runs and Figure 8/9-style boxplots, follow the
[experiment guide](docs/optimization-replication.md). It records seeds, starts,
budgets, engine versions, and failures, and distinguishes partial runs from
completed experiments. The [model transition guide](docs/model-transition.md)
documents the EnergyPlus upgrade.

## License and credit

New independent code is MIT licensed. Upstream code, translated benchmark logic,
and model assets retain BSD-3-Clause coverage and applicable acknowledgments.
See the [third-party notices](THIRD_PARTY_NOTICES.md) and
[licensing guide](docs/licensing.md). The software licenses do not grant
redistribution rights for weather files. Weather files and original reference
files are downloaded into local caches; they are excluded from this repository
and package distributions.
