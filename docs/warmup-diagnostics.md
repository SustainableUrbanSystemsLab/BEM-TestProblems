# Warmup convergence

Before a sizing or weather simulation, EnergyPlus repeats the first day to
initialize the building's thermal history. It compares successive days' maximum
and minimum zone temperatures and peak heating and cooling loads. Warmup ends
when all checks pass or the maximum number of days is reached.

A convergence error means the repeated days still differ too much. It does not
necessarily mean that EnergyPlus crashed: it can continue into the annual
simulation and write outputs. The package rejects those outputs under its
normal strict policy.

## Thresholds

Temperature criteria use absolute differences in kelvin. Load criteria compare
relative changes in daily peaks, subject to the engine's low-load rules.
Representative benchmark thresholds are:

| Models | Temperature tolerance | Load tolerance |
| --- | ---: | ---: |
| P1 and detailed offices P4/P5/P6/P8 | 0.004 K | 4% |
| P10 | 0.2 K | 4% |

These are convergence criteria, not optimization stopping tolerances. A small
annual-objective difference does not establish that warmup passed. Increasing
the day allowance can help slow convergence, but cannot guarantee removal of a
persistent repeated-day cycle.

The version-specific definitions are in the EnergyPlus
[8.5 source](https://github.com/NatLabRockies/EnergyPlus/blob/v8.5.0/src/EnergyPlus/HeatBalanceManager.cc)
and [26.2 source](https://github.com/NatLabRockies/EnergyPlus/blob/v26.2.0/src/EnergyPlus/HeatBalanceManager.cc).

## Recorded canonical cases

The initial audit covered 26 designs plus a paired P1 trial, evaluated with both
engines: 51 accepted evaluations and three rejections. All ten midpoints passed
on both engines. These counts describe that audit, not a campaign failure rate.

| Case | Failed criterion | Interpretation |
| --- | --- | --- |
| P1, 8.5, `[90, 3, 3, 0.5]` | Minimum-temperature difference 0.00647 K versus 0.004 K | The original 25-day allowance was too short for this design. |
| P4, 26.2, simultaneous lower bounds | Maximum-temperature difference 0.0058081 K versus 0.004 K | The observed cycle also persisted with a 100-day allowance. |
| P10, 8.5, simultaneous lower bounds | Seven zone-load comparisons above 4% | Temperature checks passed; additional warmup days alone did not remove load cycling. |

The [audit data](validation-results/warmup-diagnostics.json) retain the complete
vectors, objective/component table, per-zone measurements, and diagnostic probes.
The original C# caller also encounters warmup diagnostics; this is not solely a
Python translation issue. Its use of completed annual outputs differs from the
package's strict acceptance policy.

## What to do

Read the retained `eplusout.err` to identify the engine, environment, zone, and
failed criterion. Distinguish sizing warmup from weather-run warmup: an annual
convergence report does not establish that sizing was valid.

For canonical-model comparisons, retain the rejection and report it. If the
study permits model corrections, select a fixed, labelled profile before
starting a separate experiment. The [model-variant guide](replication-failures.md)
describes the supported corrections and their measured effects. The version-3
profile passed all 23 retained version-2 failures; full-domain convergence
remains unproven.

## P1 extended-warmup variant

```python
from bem_testproblems import get_problem, make_objective

problem = get_problem(1, numerical_variant="warmup-100")
objective = make_objective(problem, energyplus_version="8.5.0")
```

This increases the historical maximum warmup allowance from 25 to 100 days,
keeping the original thresholds. The modern canonical P1 model already permits
100 days. The historical change has its own input identity and is not exact
canonical parity. Native CI checks it separately using the
[warmup cases](../reference/warmup-100-cases.json).

For a repeated experiment, `--p1-warmup-100` selects this option. Use a new output
directory; Severe and Fatal diagnostics still reject evaluations.
