# BEM-TestProblems

Continuous building energy optimization benchmarks with separate problem
definitions, EnergyPlus models, objective terms and optimization adapters.

This implementation follows [Waibel et al. (2019)](https://doi.org/10.1016/j.enbuild.2019.01.048)
and the original problem literature listed in [references](docs/references.md).
Historical calculation behavior is the default. See the
[validation record](docs/validation.md) for the evidence, known discrepancies,
and numerical paper references that remain unavailable.

| Problems | Variables | Building and climate | Objective |
|---|---:|---|---|
| 1, 2, 3 | 4 | Simple office: Seattle, Houston, Chicago | Primary energy, kWh/(m² year) |
| 4, 5, 6 | 13 | Detailed office: Seattle, Houston, Chicago | Primary energy, kWh/(m² year) |
| 8 | 11 | Detailed office: Chicago, two fixed parameters | Primary energy, kWh/(m² year) |
| 9, 10 | 13 | Small and large offices: San Francisco | Penalized source energy, MJ/m² |
| 13 | 10 | School: Belgrade winter design day | Energy, insulation and radiator cost, EUR |

## Local installation

Use Python 3.12. From the repository root on macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,optimize]'
.venv/bin/python tools/install_energyplus.py
.venv/bin/python tools/fetch_weather.py
```

On Windows, use `py -3.12 -m venv .venv` and replace `.venv/bin/python` with
`.venv\Scripts\python.exe` in subsequent commands. Activation is optional.

The installer verifies the official EnergyPlus 26.2 archive's SHA-256 and extracts
it into `.tools/energyplus/26.2.0`. It does not change the system PATH. Downloaded
tools and raw simulation directories stay local; fixed numerical test fixtures
and their provenance are versioned.

The [model transition guide](docs/model-transition.md) documents the official
21-step IDF transition chain, the separate epJSON converter, and a scratch-only
reproduction workflow with provenance and compatibility adjustments.

The [engine version guide](docs/engine-versions.md) shows how to choose EnergyPlus
8.5 or 26.2 through the same evaluation interface and compare their results.

The weather command retrieves the four exact annual benchmark EPWs from the
pinned fork into `.cache/weather` and verifies their SHA-256 hashes. This covers
problems 1–6 and 8–10; problem 13 contains its design-day conditions and needs no
EPW. See [licensing](docs/licensing.md) for weather provenance and applicable
terms; the software license does not grant weather redistribution rights.

## Evaluate a problem

```python
import os
from pathlib import Path
from bem_testproblems import EnergyPlusRunner, get_problem

problem = get_problem(1)
engine_name = 'energyplus.exe' if os.name == 'nt' else 'energyplus'
runner = EnergyPlusRunner(
    Path('.tools/energyplus/26.2.0') / engine_name,
    expected_version='26.2.0',
    output_root='.runs',
)
weather = Path('.cache/weather') / problem.weather_filename
x = problem.midpoint

# Inspect the same parameter numbering used in the publication.
for parameter, value in zip(problem.parameters, x):
    print(parameter.paper_symbol, parameter.name, value, parameter.unit)

# One simulation supplies both the individual terms and the complete objective.
outputs = problem.simulate_outputs(x, runner=runner, weather=weather)
print(problem.objective_terms(x, outputs))
print(problem.outer_loss(x, outputs), problem.objective_unit)

# Convenient scalar interface, using the shared runner's exact-input cache:
value = problem.evaluate(x, runner=runner, weather=weather)
```

Decision vectors use physical coordinates and units. Problem 8 keeps the original
parameter numbering: `x11=25 °C` and `x13=12 °C` are fixed, with eleven free entries.
Problem 13 runs a winter design day and can run without an EPW.

The runner retains the generated input, engine/weather hashes and diagnostics in
each run directory. Timeouts, failed simulations, missing outputs and severe or
fatal diagnostics raise explicit errors. They do not become numerical objectives.

## Default optimizer

```python
from bem_testproblems import solve

result = solve(problem, runner=runner, weather=weather, max_evaluations=100)
print(result.x, result.fun)
```

The adapter calls PDFO with `method='bobyqa'`, bounded-variable scaling and a
midpoint start unless `x0` is supplied. The evaluation budget is explicit. Problems
9–10 contain discontinuous penalties; BOBYQA's performance is separate from the
correctness of the evaluator. Simulator components and known outer derivatives
remain available for other optimization methods. None of the ten objectives is
naturally a least-squares objective.

The [objective structure and derivative interface](docs/objective-structure.md)
documents all four outer functions, named simulator outputs, additive terms and
known partial derivatives for structured optimization methods.

## Tests and numerical comparisons

```sh
.venv/bin/python tools/fetch_reference.py
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests tools
```

GitHub Actions checks Python on Linux, Windows and macOS; compares unchanged
original C# components with Python using the same EnergyPlus 8.5 engine; and
checks modern results against separately reviewed EnergyPlus 26.2 references.
The [reference harness](reference/README.md) documents the numerical comparisons.

| Check | Comparison | Purpose |
| --- | --- | --- |
| C# versus Python, EnergyPlus 8.5 | Two implementations, identical engine and test weather | Check that the Python translation preserves reference behavior |
| EnergyPlus 26.2 reference values | Current Python results versus a previous measured run | Catch future changes; these expected values are not independent paper results |
| Published specification and literature points | Bounds/formulas versus publications; numerical comparisons with version conditions recorded | Check the mathematical definitions and expose remaining reproduction gaps |

Public CI uses independently generated **synthetic test weather**. This is an
explicit test variant, not the canonical benchmark climate or published results.
Canonical weather checks are recorded separately. Reference updates are reviewed
changes, never an automatic response to a failed test.

Original C# files and historical IDFs are fetched from the fork at a fixed commit,
verified by SHA-256, and kept in `.reference-cache/beobenchmark`. They are excluded
from the repository and Python distributions. Normal modern-model evaluations
do not require this reference cache or a network connection.

## Attribution and development

New independent code is MIT licensed. Upstream source, translated benchmark logic
and model assets retain BSD-3-Clause coverage and applicable model acknowledgments.
Read [third-party notices](THIRD_PARTY_NOTICES.md) and the
[asset manifest](assets/manifest.json) before redistributing assets.

Development takes place on `codex/beobenchmark-python-continuous`. Webpage design
and development require separate explicit approval after empirical validation.
