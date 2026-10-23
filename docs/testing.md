# Testing

## Run locally

From the repository root, use the Python 3.12 environment created during
[setup](../README.md#set-up-locally):

```sh
.venv/bin/python -m pip install -c dependencies-py312.txt -e '.[dev,optimize,replication]'
.venv/bin/python tools/fetch_reference.py
.venv/bin/python -m pytest -q -m 'not integration'
.venv/bin/python -m ruff check src tests tools replication
```

On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe`.
Install `.[replication-nlopt]` with the same dependency file to exercise the
optional NLopt adapters. Tests for unavailable optional solvers are skipped.
The native C#/EnergyPlus comparisons need additional tools; see the
[reference checks](../reference/README.md).

## What the tests check

For a native BOBYQA search on every problem from its midpoint, run:

```sh
.venv/bin/python -m pytest -q tests/test_bobyqa_integration.py
```

This parametrized integration test uses PDFO directly with EnergyPlus 26.2,
canonical weather, and up to 100 solver evaluations per problem. It requires
the installed engine, weather, and `optimize` extra. It checks feasible, finite
results no worse than the midpoint; the budget does not guarantee optimizer
convergence. Simulation errors fail the case. The ordinary `not integration`
selection excludes these long native runs.

Tests protect behavior that a solver user or maintainer relies on. Expected
values come from hand calculations, independent output fixtures, the documented
paper definitions, or measured native reference runs. Calculating an expected
value with the function under test would not provide an independent check.

| Code | Meaningful checks |
| --- | --- |
| Public API, parameters, problems and losses | All ten continuous problem definitions, bounds, units, paper parameter names, objective terms and derivatives; unsupported problems and invalid designs |
| Model rendering and reference lookup | Parameter effects in both formats, unchanged source files, deterministic rendering, checksum and binding failures |
| Output parsing | Named variables, units and reporting frequencies; missing, ambiguous, truncated and nonfinite outputs; independent fixed-row selections for the C# comparison |
| EnergyPlus runner and objective factory | Isolated subprocesses, timeout and child-process cleanup, severe/fatal rejection, cache identity, retained provenance, invalid configuration and scalar objective use |
| Solver adapters | Real bounded analytic problems, hard budgets, preserved supplied starts, seeded trajectories, observed incumbents, and unchanged propagation of simulator failures |
| Replication orchestration and diagnostics | Paired starts, paper budgets, spawned workers, checkpoint/resume rules, coordinator locks and narrow warmup recovery with explicit diagnostics |
| Review and publication | Validated origin/continuation joins, complete denominators, full design vectors, strict winner replay, allowlisted exports, altered-file rejection, and preflight gates |
| Cross-platform continuation | Immutable origin records, exact remaining starts/seeds/budgets, destination provenance, changed-input rejection, interruption history, and disjoint Windows worker pools |
| Plotting | Failed/incomplete results excluded and counted, provenance checks, independently calculated quartiles, engine differences and percentage denominators |
| Download, transition and maintenance tools | Offline fixtures exercise acquisition checksums, safe extraction, model conversion and repair invariants, source preservation and CLI dispatch |
| C# oracle, compilation shims and engine proxy | Windows CI compiles the unchanged upstream components, checks component construction, and runs the original caller against Python on canonical and supplemental fixtures |
| Packaged assets, licenses and workflows | Pinned provenance, complete notices, exclusion of raw external assets and explicit JSON-only artifact uploads |

Python coverage reports include every package module and tool, with branches.
CI rejects entirely unexercised files and enforces an 85% combined floor.
Platform-specific process handling and the
native C# caller also have Windows CI evidence. No Python file is omitted to
inflate coverage. The report lists remaining lines so gaps can be reviewed.
Coverage alone cannot establish numerical correctness or the absence of bugs.

[test_optimize.py](../tests/test_optimize.py) checks the default BOBYQA adapter at
its minimum legal budgets in dimensions 2, 4, and 13 and verifies that a supplied
start near a bound is the first point evaluated. A separate guard test checks
that even an overrequesting solver cannot launch extra objective evaluations.

Keep tests short and focused on one behavior. Parameterize genuinely parallel
cases and share setup fixtures when that makes the scenario easier to read.
Assert an internal detail only when it is part of a required contract, such as
not launching a process for invalid input, counting every objective call, or
preserving a checkpoint after a write failure. Prefer simple code and named
intermediate values to nested conditional expressions or unnecessary abstractions.

Canonical native checks evaluate 27 explicit designs per engine. They compare
accepted objectives/components using the documented tolerances and verify the
known strict warmup rejections separately. These checks complement the offline
pytest suite; changing a reference requires reviewing the measured evidence.

Canonical-weather CI also runs five explicitly corrected designs per engine:
one retained warmup failure each for P4/P5/P10 using `model-corrected-v3`, and
P6/P8 midpoints using `historical-hvac`. Their references come from the audited
native runs, with exact input hashes and retained-output revalidation. These
checks compare objectives and components at the existing corrected-model
cross-platform tolerances (`rtol=1e-4`, `atol=1e-7`), with strict Severe/Fatal
rejection. Canonical C#/Python checks retain their separate tighter tolerances.
The cases do not reproduce full optimizer trajectories or publication boxplots.
