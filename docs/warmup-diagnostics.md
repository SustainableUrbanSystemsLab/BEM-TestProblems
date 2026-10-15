# Canonical-weather results and warmup failure analysis

This report covers the **26 recorded canonical validation cases plus one paired
P1 trial**: 54 engine/design combinations, 51 accepted evaluations and three
rejected evaluations. Every recorded failure is a warmup-convergence severe
diagnostic; these cases contain no fatal errors. All ten problem midpoints passed
with both engines. This is coverage of the listed designs, not every point in
their boxes or the published winning designs.

The [numeric evidence](validation-results/warmup-diagnostics.json) preserves full
decision vectors, parameter order, input/weather/engine hashes, per-zone
convergence metrics and separate scratch-probe results. The first 26 rows come
from the [8.5 audit](validation-results/8.5.0-canonical-audit.json) and
[26.2 audit](validation-results/26.2.0-canonical-audit.json).
These are new project measurements; no numerical paper result is substituted.

## Complete canonical case table

An objective below means the engine run passed strict diagnostics. **Rejected**
means no objective was accepted. Displayed numbers are rounded to six decimals;
the JSON records retain full available precision. Values from different engine
versions are not expected to coincide.

| Case | EnergyPlus 8.5 objective | EnergyPlus 26.2 objective | Units |
| --- | ---: | ---: | --- |
| p01-midpoint | 153.181082 | 147.566000 | kWh/(m2 year) |
| p02-midpoint | 194.745959 | 186.875943 | kWh/(m2 year) |
| p03-midpoint | 173.274743 | 170.143885 | kWh/(m2 year) |
| p04-midpoint | 147.638635 | 172.688497 | kWh/(m2 year) |
| p05-midpoint | 214.609328 | 241.746830 | kWh/(m2 year) |
| p06-midpoint | 179.577025 | 201.960714 | kWh/(m2 year) |
| p08-midpoint | 173.938191 | 190.621682 | kWh/(m2 year) |
| p09-midpoint | 843.380000 | 840.870000 | MJ/m2 |
| p10-midpoint | 1198.570000 | 1201.820000 | MJ/m2 |
| p13-midpoint | 1932.967349 | 1928.196660 | EUR |
| p01-lower | 237.042291 | 233.781187 | kWh/(m2 year) |
| p01-upper | 148.337251 | 145.932647 | kWh/(m2 year) |
| p04-lower | 202.643114 | **Rejected** | kWh/(m2 year) |
| p04-upper | 147.725439 | 163.447883 | kWh/(m2 year) |
| p09-lower | 830.190000 | 828.530000 | MJ/m2 |
| p09-upper | 909.470000 | 907.110000 | MJ/m2 |
| p10-lower | **Rejected** | 1095.630000 | MJ/m2 |
| p10-upper | 1646.560000 | 2330.740000 | MJ/m2 |
| p13-lower | 1983.035176 | 1978.814154 | EUR |
| p13-upper | 2212.926716 | 2206.941898 | EUR |
| p09-penalty-below | 1262.055000 | 1258.380000 | MJ/m2 |
| p09-penalty-above | 841.370000 | 838.920000 | MJ/m2 |
| p10-penalty-below | 1801.200000 | 1805.745000 | MJ/m2 |
| p10-penalty-above | 1200.790000 | 1203.830000 | MJ/m2 |
| p06-embedded-p08 | 173.938191 | 190.621682 | kWh/(m2 year) |
| p08-embedded-check | 173.938191 | 190.621682 | kWh/(m2 year) |
| p01-orientation90 | **Rejected** | 152.729368 | kWh/(m2 year) |

`lower` and `upper` set every free variable to its corresponding box endpoint.
The embedded P6/P8 rows test the reduced problem's fixed-coordinate mapping; they
are deliberately related designs. Penalty rows are the two recorded sides of the
window-height boundary. Exact vectors for every row are in the numeric evidence.

## Complete failure summary

| Problem and engine | Design | Affected zones | Severe / Fatal | Failure |
| --- | --- | --- | ---: | --- |
| P1, EnergyPlus 8.5 | `[90, 3, 3, 0.5]` | ZONE ONE | 1 / 0 | Minimum daily temperature changes by 0.00647 K; limit is approximately 0.004 K |
| P4, EnergyPlus 26.2 | All free variables at lower bounds | ZONE SOUTH | 1 / 0 | Maximum daily temperature changes by 0.0058081 K; limit is 0.004 K |
| P10, EnergyPlus 8.5 | All free variables at lower bounds | Seven perimeter zones below | 7 / 0 | Heating or cooling daily-peak load changes exceed 4% |

The failing corner vectors, in the same free-parameter order as `get_problem`, are:

- **P4:** `[1.224, 7.344, 7.344, 1.224, 0.05, 0.05, 0.05, 100, 100, 100, 20, 20, 12]`.
- **P10:** `[0.8, 1.35, 0.8, 1.35, 0.8, 1.35, 0.8, 1.35, 12, 13, 13, 24, 24]`.

For P1 and P4, only the stated temperature criterion fails; their other three
warmup checks pass. For P10, all temperature checks pass with its 0.2 K tolerance.
Its seven original failed load checks are listed below. The limit is **4%** in
every row.

| Zone | Failed load criterion | At 25 days | At 100 days |
| --- | --- | ---: | ---: |
| PERIMETER_BOT_ZN_3 | Cooling peak | 4.9607% | 4.7140% |
| PERIMETER_BOT_ZN_2 | Cooling peak | 11.0700% | 9.9559% |
| PERIMETER_BOT_ZN_1 | Cooling peak | 10.1700% | 9.2213% |
| PERIMETER_MID_ZN_2 | Cooling peak | 26.0700% | 21.1300% |
| PERIMETER_MID_ZN_1 | Cooling peak | 12.8300% | 11.3300% |
| PERIMETER_TOP_ZN_3 | Heating peak | 4.8326% | 4.6107% |
| PERIMETER_TOP_ZN_4 | Heating peak | 4.2746% | 4.0999% |

The scratch 100-day P10 run also adds a cooling-load failure in
`PERIMETER_TOP_ZN_1`, reported as **100%**. This eighth error belongs to the
modified-cap diagnostic run; the unchanged 25-day benchmark has seven.

## What warmup is checking

EnergyPlus repeats the first day of each environment to initialize thermal
history. It compares successive days' maximum and minimum zone temperatures and
peak heating and cooling loads, and requires all four checks to pass in every
zone. A maximum-day cap can end warmup before that occurs.
[Engineering reference](https://energyplus.readthedocs.io/en/stable/guides/engineering-reference/1.5-warmup-convergence.html).

Temperature comparisons are absolute differences; the load diagnostics here are
relative daily-peak differences. The version-specific source determines the
100 W low-load handling.
[8.5 implementation](https://github.com/NatLabRockies/EnergyPlus/blob/v8.5.0/src/EnergyPlus/HeatBalanceManager.cc),
[26.2 implementation](https://github.com/NatLabRockies/EnergyPlus/blob/v26.2.0/src/EnergyPlus/HeatBalanceManager.cc).

These warmup thresholds are separate from the project's relative `1e-6`
objective-comparison tolerance. Passing a numerical comparison of a reported
objective does not override a failed simulation diagnostic.

### P1: insufficient warmup allowance at this design

The original model stops after 25 days with a minimum-temperature change of
0.00647 K, above its approximately 0.004 K limit. A scratch copy with a 100-day cap
passes after **28 days**, without changing either convergence tolerance. The
current modern model, already configured with a 100-day cap, passes the same
vector after **34 days**.

The model derives from a high-mass BESTEST case and contains 200 mm concrete-block
walls, 180 mm plus 50 mm concrete floor/ceiling layers and brick internal mass.
Slow initialization of stored heat is consistent with the observed need for
additional days. Thermal mass was not isolated by changing the constructions, so
it is a supported contributor rather than a proven sole cause.

| P1 condition | Actual warmup days | Severe / Fatal | Objective status |
| --- | ---: | ---: | --- |
| Original 8.5, cap 25 | 25 | 1 / 0 | Rejected |
| Scratch 8.5, cap 100 | 28 | 0 / 0 | Diagnostic variant: 156.46031464 |
| Current 26.2, cap 100 | 34 | 0 / 0 | Accepted: 152.72936839 |

The failed 8.5 run still writes a diagnostic-only value, 156.45937753. Changing
the warmup cap changes that value by approximately `5.99e-6` relatively. Neither
the failed-run value nor the scratch-cap variant is an unchanged historical
benchmark observation.

### P4: a persistent two-day numerical cycle

At a 100-day cap, the south zone's late daily maximum alternates between
**24.8310816691°C** and **24.8253485019°C**. Their difference, **0.0057331672 K**,
still exceeds 0.004 K. This cycle is stable across the final 20 days, so increasing
the cap alone does not remove it.

At the lower bounds, heating and night-cooling setpoints coincide at 20°C during
the 07–08 morning overlap, while the main cooling coil is unavailable. Heating
is 18°C during the other night hours. This is relevant control context, but no
individual controller was isolated as the cause.
Sensitivity tests support an interaction with the coupled numerical solution:

| P4 scratch condition | Actual warmup days | Severe / Fatal | Diagnostic-only objective |
| --- | ---: | ---: | ---: |
| Unchanged model, cap 25 | 25 | 1 / 0 | Rejected |
| Cap 100, otherwise unchanged numerical settings | 100 | 1 / 0 | Rejected |
| HVAC iteration limit increased from 20 to 100; cap 25 | 16 | 0 / 0 | 232.841307 |
| Analytical zone-air integration; cap 25 | 17 | 0 / 0 | 229.858837 |
| Valid 12 timesteps/hour; 12-step sizing window preserves 60 minutes; cap 100 | 14 | 0 / 0 | 238.772703 |

All convergence tolerances and physical decision coordinates were preserved in
these probes. The changes are numerical-control variants, not established
benchmark repairs. Annual HVAC iteration warnings still occur in some passing
variants; passing warmup alone does not establish their overall physical accuracy.

An earlier timestep request of 8/hour was invalid. EnergyPlus normalized it to
10/hour and the unchanged four-step sizing window became 24 minutes. Its pass
and objective are retained in the JSON with that confound; the valid 12/hour
test above corrects the experiment by preserving the 60-minute window.

### P10: load cycling, low-load test behavior and numerical resolution

At the original ten-minute timestep, late warmup daily-peak loads alternate
between two phases. The temperature checks pass, but seven peak-load comparisons
remain above 4% after 100 days. Examples are `PERIMETER_MID_ZN_2` cooling peaks
of approximately **241.70 W** and **306.45 W**, and
`PERIMETER_TOP_ZN_3` heating peaks of approximately **5677.11 W** and **5951.52 W**.

The added top-zone-1 error has a separate low-load effect: cooling alternates
between **0 W** and **37.1888 W**. EnergyPlus 8.5 floors the positive current peak
to 100 W while the stored previous zero remains zero; its comparison becomes
`abs(100 - 0) / 100 = 1`. Version 26.2 floors both sides of that positive-load
comparison. This explains the reported 100% small-load artifact, not the other
zones' larger-load oscillations.

The model repeats January 1 as a holiday during these probes. Fans are scheduled
off while night-cycle control can enable them. Those switching controls and the
autosized VAV system are plausible contributors; individual control changes
were not isolated.

| P10 scratch condition | Actual warmup days | Severe / Fatal | Objective status |
| --- | ---: | ---: | --- |
| Original ten-minute timestep, cap 25 | 25 | 7 / 0 | Rejected |
| Same timestep, cap 100 | 100 | 8 / 0 | Rejected |
| Five-minute timestep, sizing window inadvertently shortened to 30 minutes, cap 100 | 100 | 3 / 0 | Rejected; confounded diagnostic |
| Five-minute timestep, 12-step sizing window preserves 60 minutes, cap 100 | 17 | 0 / 0 | Diagnostic variant: 1096.91 |

The corrected refinement passes all four checks in all 16 zones. Its largest
reconstructed active heating and cooling residuals are approximately 0.00138
and 0.03750, below 0.04. This supports numerical-resolution/sizing sensitivity;
it does not isolate one controller or prove equivalence to the original model.

## Consequences for evaluation and validation

EnergyPlus can exit with code zero and print “Completed Successfully” while
also reporting severe warmup errors. The original C# caller does not reject
those diagnostics. The Python evaluator does: rejected results cannot become
accepted objective values or a passing reference comparison.

There are promising numerical settings for revised variants, but each changes
the input/model identity and may change objectives at other designs. A proposed
repair needs canonical-weather comparison across the validation cases, visible
objective/component changes and separately reviewed references before it becomes
a benchmark definition. Exact historical compatibility and a revised numerical
variant must remain distinguishable.

The [current code CI](https://github.com/SustainableUrbanSystemsLab/BEM-TestProblems/actions/runs/38674953272)
passed all five jobs, including both 26-case engine comparisons. Those public
simulation checks use independently generated synthetic weather; they do not
erase the canonical failures above. No benchmark asset, warmup tolerance or
simulation acceptance policy was changed by this analysis.
