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

Use Python 3.12 and activate the project's virtual environment before installing
dependencies or running examples. From the repository root on macOS or Linux:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -c dependencies-py312.txt -e '.[optimize]'
python tools/install_energyplus.py
python tools/fetch_weather.py
```

On Windows, use PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -c dependencies-py312.txt -e '.[optimize]'
python tools/install_energyplus.py
python tools/fetch_weather.py
```

With [uv](https://docs.astral.sh/uv/) instead of `venv` and `pip` (any platform):

```sh
uv venv --python 3.12
uv pip install -c dependencies-py312.txt -e '.[optimize]'
uv run python tools/install_energyplus.py
uv run python tools/fetch_weather.py
```

`uv run python ...` uses `.venv` without activating it; prefix the commands below
the same way.

Activation makes `.venv` the default Python environment for the current terminal.
Activate it again in each new terminal with `source .venv/bin/activate` on
macOS/Linux or `.\.venv\Scripts\Activate.ps1` in PowerShell. Use `python` for all
commands below while the environment is active.

These commands install EnergyPlus and download the benchmark weather into this
project, with checksum verification. The `optimize` extra installs SciPy and
PDFO BOBYQA for the examples below.
Once set up, evaluations run offline. The default engine is EnergyPlus 26.2;
the [engine guide](docs/engine-versions.md) explains how to use historical 8.5
models and a compatible local engine.

The [Windows guide](docs/windows-continuation.md) provides PowerShell setup
commands. For repeated solver comparisons and boxplots, use the
[experiment guide](docs/optimization-replication.md).

## Solve with SciPy

After setup, run `python` in the activated terminal to start the Python console.
Paste the entire example below to run an optimization.

`get_problem(number)` defaults to the labelled profiles used for replication:
historical HVAC compatibility for P5/P6/P8, corrected v3 for P1/P3/P4/P9/P10,
and canonical models for P2/P13. Changing the number below to 5, 6 or 8 therefore
selects the HVAC compatibility profile automatically. These corrections support
comparisons with the paper; exact published results are not guaranteed.
Use `get_problem(number, numerical_variant="canonical")` for an uncorrected
model. The [model guide](docs/replication-failures.md#choose-a-model) describes
the changes and validation limits.

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

Failed simulations raise errors and retain their diagnostics. The corrected
defaults passed the recorded audits, but convergence across the entire design
domain is not established. The [simulation failure guide](docs/replication-failures.md)
explains how to inspect errors and identify the selected model.

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
python examples/solve_all_bobyqa.py
```

To run problems in parallel, leaving two logical CPUs available:

```sh
python examples/solve_all_bobyqa.py --workers auto
```

Or choose a limit with `--workers 4`. The default is one worker; at most ten
workers are used because there are ten problems. Each worker uses a separate
process and output directory. Final values are printed as problems finish.

Each invocation saves designs, objective values, termination messages, timings,
and native diagnostics in a fresh folder under `.validation-local/bobyqa/`.
After each problem, it prints the final and best observed objective values with units.
Failed problems are recorded and the script continues. The script uses the same
default profiles as `get_problem(number)`.
Add `--canonical-models` to use the original models for all ten problems.
Corrected profiles change the models; each problem prints and records its profile.
Each problem uses a function-evaluation budget of `100 * (n + 1)`, where `n` is
its number of optimization variables. The budget may be reached before convergence.

The optional [package adapter](src/bem_testproblems/optimize.py), `solve_bobyqa()`,
adds strict budget enforcement, endpoint-roundoff handling, and safe propagation
of simulation errors through PDFO's compiled callbacks.
For solvers that exploit objective structure, see the
[simulator outputs, additive terms, and known derivatives](docs/objective-structure.md).

## Tests and validation

```sh
python -m pip install -c dependencies-py312.txt -e '.[dev,optimize,replication]'
python tools/fetch_reference.py
python -m pytest -q -m 'not integration'
python -m ruff check src tests tools replication examples
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
