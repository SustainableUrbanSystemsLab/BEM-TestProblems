# BEM-TestProblems

Building energy optimization problems for testing your solver in Python. Choose
a problem, get its objective and bounds, and let the package handle EnergyPlus.

The ten continuous problems come from
[Waibel, Wortmann, Evins, and Carmeliet (2019)](https://doi.org/10.1016/j.enbuild.2019.01.048)
and the earlier studies listed in the [references](docs/references.md).

## Set up locally

Use Python 3.12. From the repository root on macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python tools/install_energyplus.py
.venv/bin/python tools/fetch_weather.py
```

On Windows, create the environment with `py -3.12 -m venv .venv` and use
`.venv\Scripts\python.exe` in place of `.venv/bin/python` in subsequent commands.

These commands install EnergyPlus and download the benchmark weather into this
project, with checksum verification. They leave the system PATH unchanged.
Once set up, evaluations run offline. The default engine is EnergyPlus 26.2;
the [engine guide](docs/engine-versions.md) explains how to use historical 8.5
models and a compatible local engine.

For the experiment pipeline, combined reports, native replay checks, and
reviewed GitHub results, start with the [replication workflow](replication/README.md).
The [Windows guide](docs/windows-continuation.md) covers installation and persistent jobs.

## Evaluate a problem with your own solver

```python
from bem_testproblems import get_problem, make_objective

problem = get_problem(1)
n = problem.dimension              # Number of free variables
bounds = problem.bounds             # (lower, upper) pairs in parameter order
x0 = problem.midpoint               # A feasible starting point
objective = make_objective(problem)

f0 = objective(x0)                  # Runs EnergyPlus and returns a float
print(n, bounds, x0, f0, problem.objective_unit)
```

Pass `objective`, `x0`, and `bounds` to your solver. It should minimize
`objective(x)`, where `x` contains the physical parameter values. Reuse the
callable throughout the run; repeated successful evaluations are cached.
For separate bound vectors, use `lower, upper = zip(*bounds)`.

Parameter names, paper symbols, units, and bounds are available through
`problem.parameters`. The midpoint is a convenient start; the study's original
starting vectors are unavailable. Use `problem.validate(your_start)` to check a
different start. Inspecting problem metadata does not require EnergyPlus.

Failed simulations raise errors and retain their diagnostics. Some designs
within the bounds fail warmup convergence; the [warmup guide](docs/warmup-diagnostics.md)
explains these cases and the separately validated P1 extended-warmup option.

## Solve with SciPy

After setup, install SciPy in the same virtual environment:

```sh
.venv/bin/python -m pip install -c constraints/replication-py312.txt scipy
```

This complete example uses problem 13, which needs no weather file, and
[SciPy's Powell method](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-powell.html),
which supports box bounds and needs only objective evaluations:

```python
from scipy.optimize import minimize

from bem_testproblems import get_problem, make_objective

problem = get_problem(13)
objective = make_objective(problem)
result = minimize(
    objective,
    x0=problem.midpoint,
    bounds=problem.bounds,
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

## Solve with BOBYQA

The optional default solver is PDFO BOBYQA. Install it in the same environment:

```sh
.venv/bin/python -m pip install -c constraints/replication-py312.txt -e '.[optimize]'
```

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

| Problems | Free variables | Building and climate | Objective |
|---|---:|---|---|
| 1, 2, 3 | 4 | Simple office: Seattle, Houston, Chicago | Primary energy, kWh/(m² year) |
| 4, 5, 6 | 13 | Detailed office: Seattle, Houston, Chicago | Primary energy, kWh/(m² year) |
| 8 | 11 | Detailed office: Chicago, two fixed parameters | Primary energy, kWh/(m² year) |
| 9, 10 | 13 | Small and large offices: San Francisco | Penalized source energy, MJ/m² |
| 13 | 10 | School: Belgrade winter design day | Energy, insulation, and radiator cost, EUR |

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
