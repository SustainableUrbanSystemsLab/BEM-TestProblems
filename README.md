# BEM-TestProblems

This repository provides Python implementations of ten building energy
optimization benchmark problems, including objective functions, variable bounds,
[EnergyPlus](https://energyplus.net/) simulation interfaces, and tools for comparing
optimization solvers.

This package implements ten problems with continuous variables selected from the
benchmark in
[Waibel, Wortmann, Evins, and Carmeliet (2019)](https://doi.org/10.1016/j.enbuild.2019.01.048)
and Christoph Waibel's ETH Zurich dissertation,
[*Simulation-Based Optimization of Buildings and Multi-Energy Systems* (2018)](https://doi.org/10.3929/ethz-b-000307674).
The original C# and Grasshopper implementation is available in
[Christoph Waibel's BEOBenchmark repository](https://github.com/christophwaibel/BEOBenchmark).
Problem numbers follow the original study. The [references](docs/references.md)
also credit the earlier studies on which these benchmarks build.

## Available problems

| Problem number | Optimization variables | Box constraints | Building and climate | Objective |
|---|---:|---|---|---|
| 1 | 4 | Yes | Simple office: Seattle | Primary energy, kWh/(m² year) |
| 2 | 4 | Yes | Simple office: Houston | Primary energy, kWh/(m² year) |
| 3 | 4 | Yes | Simple office: Chicago | Primary energy, kWh/(m² year) |
| 4 | 13 | Yes | Detailed office: Seattle | Primary energy, kWh/(m² year) |
| 5 | 13 | Yes | Detailed office: Houston | Primary energy, kWh/(m² year) |
| 6 | 13 | Yes | Detailed office: Chicago | Primary energy, kWh/(m² year) |
| 8 | 11 | Yes | Detailed office: Chicago, two fixed parameters | Primary energy, kWh/(m² year) |
| 9 | 13 | Yes | Small office: San Francisco | Penalized source energy, MJ/m² |
| 10 | 13 | Yes | Large office: San Francisco | Penalized source energy, MJ/m² |
| 13 | 10 | Yes | School: Belgrade winter design day | Energy, insulation, and radiator cost, EUR |

Problem 8 fixes the paper's `x11 = 25 °C` and `x13 = 12 °C`; its input vector
contains the eleven free parameters in their original order. Problem 13 includes
its design-day conditions and needs no weather file.

See the [documentation guide](docs/README.md) for setup, problem definitions,
simulation failures, and solver experiments.

## Set up locally

Use Python 3.12. From the repository root on macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -c dependencies-py312.txt -e '.[optimize]'
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

The [Windows guide](docs/windows-continuation.md) provides PowerShell setup
commands. For repeated solver comparisons and boxplots, use the
[experiment guide](docs/optimization-replication.md).

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
    options={"maxfev": 300},
)

print("Parameters:", result.x)
print("Objective:", result.fun, problem.objective_unit)
print("Evaluations:", result.nfev)
print("Converged:", result.success, result.message)
```

The package handles EnergyPlus for each objective evaluation. This example
allows 300 evaluations and uses Powell's default stopping tolerances. Reaching
the budget before convergence sets `result.success` to `False`; inspect the
termination message.

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

Failed simulations raise errors and retain their diagnostics. Canonical models
can fail convergence at designs within the bounds. The
[simulation failure guide](docs/replication-failures.md) explains how to inspect
errors and select a separately labelled corrected model.

## Solve with BOBYQA

The `optimize` extra installed above also provides PDFO. Call it directly with
`method="bobyqa"`, passing the objective and bounds:

```python
from pdfo import pdfo

from bem_testproblems import get_problem, make_objective

problem = get_problem(13)
objective = make_objective(problem)
result = pdfo(
    objective,
    x0=problem.midpoint,
    bounds=problem.bounds,
    method="bobyqa",
    options={
        "maxfev": 100 * (problem.dimension + 1),
        "scale": True,
        "honour_x0": True,
    },
)
print("Parameters:", result.x)
print("Objective:", result.fun, problem.objective_unit)
```

`scale=True` scales the solver's internal coordinates using the bounds, which
matters when variables have different units and ranges. The objective and
`result.x` still use physical units. `honour_x0=True` preserves the supplied
start. These options match the PDFO comparison settings; this example uses
the midpoint rather than the experiment's twenty paired starting points.

To solve all ten problems locally from their midpoints, run
[solve_all_bobyqa.py](examples/solve_all_bobyqa.py) after setup:

```sh
.venv/bin/python examples/solve_all_bobyqa.py
```

Each invocation saves designs, objective values, termination messages, timings,
and native diagnostics in a fresh folder under `.validation-local/bobyqa/`.
Failed problems are recorded and the script continues. The script defaults to
labelled `model-corrected-v3` variants for P1/P3/P4/P5/P6/P9/P10; P2/P8/P13 retain
their canonical models. Add `--canonical-models` to use the original models for
all ten problems. Corrected profiles change the models; each result records the
profile used.
Each problem uses a function-evaluation budget of `100 * (n + 1)`, where `n` is
its number of optimization variables. The budget may be reached before convergence.

The optional [package adapter](src/bem_testproblems/optimize.py), `solve_bobyqa()`,
adds strict budget enforcement, endpoint-roundoff handling, and safe propagation
of simulation errors through PDFO's compiled callbacks.
For solvers that exploit objective structure, see the
[simulator outputs, additive terms, and known derivatives](docs/objective-structure.md).

## Tests and validation

```sh
.venv/bin/python -m pip install -c dependencies-py312.txt -e '.[dev,optimize,replication]'
.venv/bin/python tools/fetch_reference.py
.venv/bin/python -m pytest -q -m 'not integration'
.venv/bin/python -m ruff check src tests tools replication examples
```

CI covers Linux, Windows, macOS, and both EnergyPlus versions. Native checks
evaluate every problem at its midpoint; full optimization searches run manually.
See [testing](docs/testing.md) for check details and [validation](docs/validation.md)
for numerical evidence and remaining discrepancies.

## Acknowledgments

OpenAI Codex (GPT-6) assisted with implementation, debugging, testing, and
documentation.

## License and credit

New independent code is MIT licensed. Upstream code, translated benchmark logic,
and model assets retain BSD-3-Clause coverage and applicable acknowledgments.
See the [third-party notices](THIRD_PARTY_NOTICES.md) and
[licensing guide](docs/licensing.md). The software licenses do not grant
redistribution rights for weather files. Weather files and original reference
files are downloaded into local caches; they are excluded from this repository
and package distributions.
