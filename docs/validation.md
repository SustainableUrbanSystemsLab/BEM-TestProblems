# Validation evidence

The package checks ten continuous-variable problems: 1-6, 8-10, and 13.
Three questions must be assessed separately:

| Question | Evidence | What it does not establish |
| --- | --- | --- |
| Does Python implement the stated problem? | Independent checks of bounds, parameter order, units, objective equations, and derivatives | Agreement with any particular simulation result |
| Does it match the original implementation? | Unchanged C# and Python evaluated with the same EnergyPlus 8.5 engine, designs, and weather | Agreement between engine generations or with every published optimizer run |
| Does the modern model behave as recorded? | EnergyPlus 26.2 compared with its own reviewed native baselines | Equality with EnergyPlus 8.5 |

A valid ordinary evaluation needs successful process/completion markers, finite
required outputs, and no Severe or Fatal diagnostics. A successful exit code
alone is insufficient. [Failure handling](replication-failures.md) and
[warmup analysis](warmup-diagnostics.md) explain recorded exceptions and labelled
model alternatives.

## What public CI checks

The [workflow](../.github/workflows/validate.yml) has seven jobs:

| Jobs | Checks |
| --- | --- |
| Three Python test jobs | Behavior, branch coverage, and lint on Linux, Windows, and macOS; source/wheel builds on Linux |
| Two C#/Python jobs | EnergyPlus 8.5 comparisons using canonical weather and separate supplemental synthetic weather |
| Two modern-engine jobs | EnergyPlus 26.2 regression checks using canonical and supplemental weather |

Canonical native checks use 27 explicit designs per engine, including known
strict rejections. Supplemental checks use 26 designs. Canonical jobs also check
P1's extended-warmup model, retained failure cases, and six corrected-model
regressions per engine. The corrected cases cover P4/P5/P10 with
`model-corrected-v3` and P5/P6/P8 with `historical-hvac`.

Canonical objective/component comparisons use relative tolerance `1e-6` and
absolute tolerance `1e-7` near zero. Separately labelled corrected-model native
comparisons use `rtol=1e-4`, `atol=1e-7` across builds. Neither policy relaxes
EnergyPlus convergence thresholds or permits Severe/Fatal diagnostics.

See [testing](testing.md) for local commands and test scope. Numeric expectations
are in [reference/baselines](../reference/baselines); additional measured audits
are indexed in [validation data](validation-results/README.md).

## Checks against the published specification

Independent [specification tests](../tests/test_paper_specification.py) check the
problem selection, dimensions, physical bounds, climate assignment, fixed P8
coordinates, and objective formulas against the paper. The
[parameter guide](parameters.md) and [objective structure](objective-structure.md)
document the public interface.

Known paper/code differences remain explicit. Examples include the repeated
fan selection in the detailed-office objective and the original code's 0.5488 m
window-height penalty boundary for P9/P10. Historical code behavior is preserved
rather than silently changed to match rounded paper descriptions. Consult the
[references](references.md#numerical-interpretation) for their interpretation.

## Reproducibility

The experiment manifest records physical starts, seeds, budgets, solver settings,
model/weather identities, engine and supporting-library hashes, and numerical
package versions. [dependencies-py312.txt](../dependencies-py312.txt) pins the
tested Python environment. Matching package version numbers alone does not
ensure identical native libraries or trajectories across operating systems.

On the recorded machine, replaying all ten dissertation-design candidates with
both engines reproduced all 158 checked objective/component values exactly.
That establishes repeatability of those evaluations, not global optimality or
recovery of the publication's missing original trajectories.

Freeze the numerical source and environment for a campaign. Changed models,
inputs, or solver settings require separate results. The
[experiment guide](optimization-replication.md#reproducibility-scope) describes
checkpoint and replay limits.

## Modern models and engine differences

The modern models have provenance sidecars connecting them to the original
IDFs and official conversion chain. Explicit compatibility adjustments include
extended P1 warmup, reciprocal surface references, a duplicate P10 setpoint-manager
name, and P13's inactive autosized capacity. See the
[model transition](model-transition.md) for exact changes.

Engine generations can produce different objectives. In the original canonical
midpoint audit, modern changes included +12.4647% for P6 and +9.5916% for P8.
These are fixed-design comparisons, not optimized results. The
[historical HVAC variant](historical-hvac.md) addresses selected convection and
fan-sizing differences for these two problems; it does not reproduce the entire
historical engine. Corrected-model evidence remains separate from canonical
baselines.

The [canonical audit files](validation-results/README.md) retain full available
precision, units, component outputs, and input identities. They are project
measurements, not published optima.

## Limits of comparison with the paper's results

Waibel's [dissertation Appendix C](published-solutions.md) supplies rounded final
objectives and designs for all ten problems. Six use direct physical coordinates;
four require a candidate interpretation of Grasshopper slider coordinates.
The dissertation used 20 optimizer configurations; the journal paper used 16.
Their winning runs must not be treated as interchangeable.

All ten candidate designs passed strict checks on both engines. Eight historical
objectives were within 0.12% of the rounded dissertation values. P2 and P6 differed
by +2.2398% and +1.2056%, respectively; these gaps also occurred with the original
C# caller and remain unresolved. They describe evaluation of rounded designs,
not a comparison of complete optimizer distributions.

The paper's original seeds, starting vectors, raw trajectories, and full-precision
winning records are unavailable. New runs can compare distributions and algorithm
behavior using the stated protocol, but exact numerical reproduction of the
published boxplots has not been established. Report failures, omitted methods,
model variants, engine versions, and incomplete repetitions alongside plots.
