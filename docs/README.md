# Documentation

Start with the [installation and copyable optimization example](../README.md).
The package exposes ten building-energy problems with continuous variables and
box bounds. You can use any solver that accepts a scalar objective and bounds.

## Using the problems

| Task | Guide |
| --- | --- |
| Install and run on Windows | [Windows setup](windows-continuation.md) |
| Choose EnergyPlus 8.5 or 26.2 | [Engine versions](engine-versions.md) |
| Find variable meanings, units, and bounds | [Parameters and objectives](parameters.md) |
| Solve all ten problems locally with BOBYQA | [Python example](../examples/solve_all_bobyqa.py) |
| Use simulator outputs, objective terms, or derivatives | [Objective structure](objective-structure.md) |
| Diagnose a failed evaluation or choose a corrected model | [Simulation failures](replication-failures.md) |
| Understand warmup convergence | [Warmup diagnostics](warmup-diagnostics.md) |

Use Python 3.12 for the tested solver environment. The root
[dependencies-py312.txt](../dependencies-py312.txt) records Python package
versions; optimization bounds are defined separately by each problem.

## Comparing solvers

| Task | Guide |
| --- | --- |
| Run repeated experiments and generate boxplots | [Experiment protocol](optimization-replication.md) |
| Continue an existing campaign, replay winners, or export results | [Replication workflow](../replication/README.md) |
| Understand what has been validated | [Validation evidence](validation.md) |
| Compare with the dissertation's rounded designs | [Published solutions](published-solutions.md) |
| Compare P6/P8 across engine generations | [Historical HVAC compatibility](historical-hvac.md) |

The default models preserve the benchmark definitions. Corrected models are
explicit options and require separate experiment results. Agreement with the
original C# caller, agreement between engines, and agreement with published
boxplots are different checks.

## Developing and citing the package

| Task | Guide |
| --- | --- |
| Run tests and understand CI | [Testing](testing.md) |
| Reproduce the model conversion | [Model transition](model-transition.md) |
| Inspect numerical measurements | [Validation data](validation-results/README.md) |
| Cite the benchmark and solvers | [References](references.md) |
| Understand code, model, and weather licenses | [Licensing](licensing.md) |
| Check weather redistribution evidence | [Weather rights](weather-redistribution.md) |

Generated checkpoints, raw simulator outputs, and local session notes stay
outside Git. Reviewed public result packages belong in
[replication/results](../replication/results/README.md).
