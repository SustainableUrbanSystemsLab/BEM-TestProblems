# Historical HVAC compatibility for P5, P6 and P8

The `historical-hvac` variant restores selected EnergyPlus 8.5 HVAC
algorithms under 26.2 for the Houston and Chicago office problems. It addresses the large
fan-energy shift measured in optimization experiments. Canonical models,
existing numerical variants, engine installations and recorded runs are preserved.
It is the default returned by `get_problem(5)`, `get_problem(6)` and `get_problem(8)`.
Select `numerical_variant="canonical"` to evaluate their uncorrected models.

## Diagnosis

The two versions interpret `CeilingDiffuser` differently at low airflow.
EnergyPlus 8.5 evaluates the original Fisher–Pedersen equations down to zero
air changes per hour (ACH), and forces ACH to zero during zone/system sizing.
EnergyPlus 26.2 blends to natural convection below 3 ACH, reaching a purely
natural-convection calculation below 0.5 ACH. Its sizing calculation consequently
produces different zone loads and larger fans for these models.

Sources: [8.5 implementation](https://github.com/NatLabRockies/EnergyPlus/blob/v8.5.0/src/EnergyPlus/ConvectionCoefficients.cc#L3941-L4030),
[8.5 equations](https://github.com/NatLabRockies/EnergyPlus/blob/v8.5.0/src/EnergyPlus/ConvectionCoefficients.cc#L7632-L7760),
[26.2 implementation](https://github.com/NatLabRockies/EnergyPlus/blob/v26.2.0/src/EnergyPlus/ConvectionCoefficients.cc#L4926-L5023),
and [26.2 engineering reference](https://energyplus.readthedocs.io/en/v26.2.0/guides/engineering-reference/3.6-inside-heat-balance.html).
These are versioned algorithm differences, not evidence that the modern
algorithm is defective.

There is a second sizing difference: 26.2 adjusts the system design flow using
the terminal maxima. The historical fan size uses the larger of the system
heating and cooling design flows. The
[8.5 system-sizing source](https://github.com/NatLabRockies/EnergyPlus/blob/v8.5.0/src/EnergyPlus/SimAirServingZones.cc#L5432)
records that rule. The modern compatibility variant applies it through the
documented fan autosizing actuator, without hard-coding a measured fan size.

## Implementation and scope

```python
from bem_testproblems import get_problem

problem = get_problem(8, numerical_variant="historical-hvac")
```

P5, P6 and P8 support this variant. For an experiment limited to those problems,
`tools/run_replication.py` accepts `--numerical-variant historical-hvac`.
It is not a replacement profile for the other seven problems; their existing
variant selections remain separate.

- **P5 base:** the version-3 numerical recipe, including its 1 W/(m² K) weather-warmup policy.
- **P6 base:** the version-3 numerical recipe, whose P6 inputs equal version 2.
- **P8 base:** the canonical reduced Chicago model, with its two fixed controls.
- **EnergyPlus 8.5:** input bytes are unchanged from the respective base.
- **EnergyPlus 26.2:** EMS evaluates the original coefficients
  `3.873 + 0.082*ACH**0.98` for floors, `2.234 + 4.099*ACH**0.503` for ceilings,
  and `1.208 + 1.012*ACH**0.604` for walls/windows. It preserves the original
  density calculation, zone multipliers, 0.01 kg/s flow threshold and 100 ACH
  cap. Sizing uses ACH = 0. P5 retains 1 W/(m² K) and P6 retains 2.5 W/(m² K)
  during weather warmup; measured days use the historical equations.
- **Fan sizing:** EMS uses `max(heating design flow, cooling design flow)` for
  each autosized fan. The values are calculated for each design.

The code requires the canonical two-design-day configuration and rejects foreign
EMS controls. It preserves non-EMS physical fields, weather, bounds, objective
equations, starts, seeds, budgets, solver settings and strict Severe/Fatal
rejection. The coefficients are taken from source code, not fitted to publication
values. This explicitly changes the modern model's operating and sizing behavior;
whole-engine historical equivalence is not claimed.

The canonical P4–P6 models share their building, HVAC system and variables;
their climate inputs differ. P8 is P6 with summer night cooling fixed at 25 °C
and cooling design supply air temperature fixed at 12 °C. P4's current v3 profile
also changes annual convection to TARP. That separate model change is outside
this compatibility audit; the canonical shared-family relationship remains tested.

## P5 validation

The [P5 audit](validation-results/p5-historical-hvac-audit.json) compares identical
designs using the 8.5 v3 base, unchanged 26.2 v3 base and 26.2 compatibility profile.
The partial 42-design audit contains **95 of 126 planned native evaluations,
with zero failures**. Thirty-one designs have complete three-way comparisons;
one more has two completed evaluations. The remaining 31 evaluations were not run.

The planned selection includes the midpoint, bounds corners, interpreted rounded
dissertation design, a retained warmup failure, five independently seeded random
designs, and best/middle/worst saved outcomes from six solvers on both engines.
The report lists the completed subset. Three additional convection-only
evaluations separate convection from fan sizing.

| P5 design | 8.5 v3 base | 26.2 v3 base | 26.2 historical HVAC |
| --- | ---: | ---: | ---: |
| Midpoint | 213.6446 | 248.5436 | 213.4836 |
| Interpreted dissertation design | 175.7289 | 182.9377 | 174.6575 |
| Retained warmup case | 382.4157 | 602.4206 | 382.6894 |

Values are objectives in kWh/(m² year). Across the 31 paired designs, the fan
difference from 8.5 changes from +12.59%–+80.66% to −0.7226%–+0.1726%.
Compatible total objectives differ by −1.5867%–+0.0716%. These differences describe
the measured subset; validation tolerances and strict diagnostics are unchanged.

All 42 legacy inputs are byte-identical to their v3 bases. All modern fields
outside EMS are preserved. All 63 available corresponding native-tested P5 inputs
match the production renderer exactly. The existing P6/P8 midpoint and corner
inputs remain byte-identical across both engines. These are model checks, not
new boxplots or a guarantee that a single BOBYQA start reaches the best-known design.

The Python suite passed 1,430 tests, with 26 skipped. The corrected-model native
CI regression passed all six cases on each engine, including the P5 midpoint.

## Original P6/P8 native validation, 23 October 2026

The [aggregate audit](validation-results/historical-hvac-audit.json) covers
80 distinct physical designs, 40 per problem. Selection includes best, middle
and worst saved outcomes from all six solver families and both engines,
deduplicated, plus midpoints, lower/upper corners and five independently seeded
random designs per problem. Each design was measured with 8.5, unchanged 26.2,
and compatible 26.2: **240 strict native passes, zero failures**.

Differences below compare identical physical designs and weather with the
respective 8.5 base. Percentages are observations, not relaxed acceptance limits.

| Problem | Original 26.2 fan difference | Compatible 26.2 fan difference | Compatible total objective difference |
| --- | ---: | ---: | ---: |
| P6 | +35.617% to +72.596% | −0.0442% to +0.0565% | −0.6275% to −0.0808% |
| P8 | +25.647% to +37.128% | +0.0018% to +0.6465% | −0.7566% to +0.0853% |

All 160 production inputs for the paired compatibility checks matched the
native-tested candidate inputs after normalizing line endings. Another
**80 native replays of the exact production modern inputs reproduced every
component and objective exactly**, bringing the native validation total to 320.
Engine and supporting-library hashes were fixed throughout. At that audit, the full Python suite passed **1,396 tests**,
with 26 skipped and 23 existing PDFO warnings. Tests verify unchanged legacy
inputs, preserved non-EMS fields and unchanged experiment specifications.

This is finite fixed-design validation. Other 26.2 physics and numerical
differences remain, and P6's earlier dissertation discrepancy is separate.
A solver comparison using this variant requires a new frozen manifest and
separate outputs. Its fixed-design audit alone does not establish agreement
between optimized distributions or with the dissertation's boxplots.
