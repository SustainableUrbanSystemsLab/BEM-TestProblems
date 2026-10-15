# Choose an EnergyPlus version

The same `Problem` and physical design vector can run with EnergyPlus **8.5.0**
or **26.2.0**. Select the executable and its expected version explicitly.
`Problem.evaluate` renders the original IDF for 8.5 and the packaged native
epJSON model for 26.2. Other versions are rejected. Each evaluation retains its
input, diagnostics and engine/weather hashes.

## EnergyPlus 26.2

From an installed development checkout, download the pinned official engine and
the canonical US weather files explicitly:

```sh
.venv/bin/python tools/install_energyplus.py
.venv/bin/python tools/fetch_weather.py
```

On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe`.
The engine stays in this project's ignored `.tools/energyplus/26.2.0` directory;
weather stays in `.cache/weather`. Neither importing the package nor evaluating a
problem downloads files. Modern evaluations do not need the original-source cache.

```python
import os
from pathlib import Path
from bem_testproblems import EnergyPlusRunner, get_problem

problem = get_problem(1)
executable_name = 'energyplus.exe' if os.name == 'nt' else 'energyplus'
modern = EnergyPlusRunner(
    Path('.tools/energyplus/26.2.0') / executable_name,
    expected_version='26.2.0',
    output_root='.runs/26.2',
)
weather = Path('.cache/weather') / problem.weather_filename
value_26_2 = problem.evaluate(problem.midpoint, runner=modern, weather=weather)
```

Problem 13 uses its embedded Belgrade winter design day and can omit `weather`.
Its EPW is not among the four downloaded US files.

## EnergyPlus 8.5

Fetch the checksum-pinned historical templates separately:

```sh
.venv/bin/python tools/fetch_reference.py
```

They remain outside the package in `.reference-cache/beobenchmark`. A source
checkout resolves this cache from its repository root. For an installed package
without the checkout, the default is relative to the current working directory;
set `BEM_REFERENCE_DIR` to use a cache elsewhere. Every original template is
checked against the package's pinned manifest before use.

On Windows x64, the historical reference installer retrieves the original pinned
8.5 core into this project; it requires the official Visual C++ 2013 x64 runtime:

```powershell
.venv\Scripts\python.exe tools/install_reference_engine.py
```

For macOS or Linux, supply your own compatible EnergyPlus 8.5 installation and
point `EnergyPlusRunner` at its executable. This project does not provide an
automatic old-engine installer for those platforms or guarantee that historical
binaries run on every current operating system.

With the Windows installer above, evaluate the same design and weather as follows:

```python
historical = EnergyPlusRunner(
    Path('.tools/energyplus/8.5.0/energyplus.exe'),
    expected_version='8.5.0',
    output_root='.runs/8.5',
)
value_8_5 = problem.evaluate(problem.midpoint, runner=historical, weather=weather)
```

On another platform, replace the executable path with your supplied 8.5 path.
The constructor probes the executable and rejects a version mismatch before any
benchmark simulation.

## Interpret the comparison

EnergyPlus 8.5 reproduces the engine generation used by BEOBenchmark. It does not
recreate the older EnergyPlus 1.1 or 2.2 studies cited by the benchmark paper.
EnergyPlus 26.2 includes documented model compatibility adjustments and engine
changes, so equality between versions is not an acceptance requirement. See the
[validation record](validation.md) for measured comparisons and known failures,
and the [transition record](model-transition.md) for model adjustments.

For a reproducible comparison, retain the same design, canonical EPW bytes and
objective definition, and record the engine build/hash, platform, model hash and
reported output precision. In particular, the office objectives preserve the
historical report's rounded source-energy quantity. Engine-version parity tests
and original C# versus Python tests answer different questions; the latter uses
the same 8.5 engine and inputs on both sides.
