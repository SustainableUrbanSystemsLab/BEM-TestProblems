# Tests and readable code

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
| Solver adapters | Real bounded analytic problems, hard budgets, seeded trajectories, observed incumbents and unchanged propagation of simulator failures |
| Replication orchestration and diagnostics | Paired starts, paper budgets, spawned workers, checkpoint/resume rules, coordinator locks and narrow warmup recovery with explicit diagnostics |
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
