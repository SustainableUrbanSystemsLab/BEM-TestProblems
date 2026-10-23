# Simulation failures and model variants

A design can satisfy every box bound and still fail EnergyPlus convergence.
The default evaluator raises an error for Severe or Fatal diagnostics, even if
EnergyPlus exits successfully and writes annual outputs. It does not substitute
a penalty or accept an unconverged result.

## Diagnose an evaluation

An `EnergyPlusError` exposes `reason` and, when a simulation directory exists,
`directory`. Inspect `eplusout.err` there; the retained `run.json` records the
command, input identities, and failure reason. The objective factory normally
places these directories below `.runs/<engine-version>/`.

| Symptom | Meaning and next step |
| --- | --- |
| Warmup convergence error | Repeated initialization days did not meet the temperature or load criteria. Read the [warmup guide](warmup-diagnostics.md), then decide whether the study should use a labelled model variant. |
| Cooling sizing error | A valid control setting can lie on an equipment-sizing threshold. The corrected profiles apply explicit sizing margins; these change the model and must be recorded. |
| Version probe failure or timeout | The engine was not verified. Check its path, prerequisite runtime, and startup load before attributing this to a building design. |
| No space left on device | Check the simulation-output drive and the directories selected by `TEMP` and `TMP`. Preserve checkpoints and failure evidence; choose adequate storage before a new run. |
| Bound violation | Inspect the proposed coordinate. Solver adapters normalize at most two adjacent binary64 values outside an endpoint; larger violations remain errors. Direct problem calls use strict bounds. |

A warmup failure is a simulation acceptance failure, not necessarily a process
crash. The failed optimization retains its earlier observations but is excluded
from completed-run boxplots. Other scheduled searches can continue.

## Choose a model

`get_problem(number)` selects the validated replication profile for that problem.
The selected profile is recorded in `problem.numerical_variant` and
`problem.provenance`; the canonical model remains available explicitly.

| Selection | Problems | Purpose |
| --- | --- | --- |
| Default (`replication`) | All ten | Historical HVAC for P6/P8, corrected v3 for P1/P3/P4/P5/P9/P10, canonical for P2/P13 |
| `canonical` or explicit `None` | All ten | Preserve the uncorrected model for the selected engine |
| `warmup-100` | 1 | Increase the historical warmup allowance without changing convergence thresholds |
| `model-corrected-v3` | 1, 3, 4, 5, 6, 9, 10 | Use the validated correction profile, including sizing and warmup controls |
| `historical-hvac` | 6, 8 | Restore selected historical convection and fan-sizing behavior in 26.2 |

For example, the default P8 model includes historical HVAC compatibility:

```python
from bem_testproblems import get_problem, make_objective

problem = get_problem(8)
print(problem.numerical_variant)  # historical-hvac
objective = make_objective(problem)
value = objective(problem.midpoint)
print(value, problem.objective_unit)
```

Use the same variant for the entire experiment and a new result directory.
Changing a running campaign's model would change the function being optimized.
Existing manifests and validation fixtures retain their explicit model selections;
the API default does not override them. These profiles support publication
comparisons without establishing exact historical equivalence or global optima.
The historical profiles `convergence-refined`, `convergence-repaired`,
`model-corrected`, and `model-corrected-v2` remain available to replay older
experiments. Their exact recipes are recorded in
[numerical_controls.py](../src/bem_testproblems/numerical_controls.py) and
[model_controls.py](../src/bem_testproblems/model_controls.py).

## Weather-warmup convection correction, version 3

The version-3 profile extends version 2 with a fixed interior-surface convection
coefficient of **1 W/(m2 K)** during weather-run warmup for P4, P5, and P10.
Every actuator is released after warmup. The two design-day sizing environments
retain their previous treatment. P10 also retains its warmup air-loop control.
P6 keeps version 2's 2.5 W/(m2 K) warmup setting and its numerical controls.

The profile inherits earlier model changes: P4 uses TARP indoor convection and
a 0.1 K cooling-sizing margin; P5/P6 use a 0.01 K sizing margin; P6 uses analytical
zone-air integration and 100 maximum HVAC iterations. P1, P3, and P9 retain their
previous numerical recipes. These are declared model and initialization changes,
not exact historical equivalence.

The [native audit](validation-results/model-corrected-v3-audit.json) found:

- All 23 retained version-2 warmup failures passed with the original thresholds,
  completing warmup in 6-21 days.
- All 2,850 audited engine/design combinations passed strict diagnostics;
  1,776 were new native simulations and 1,074 reused byte-identical inputs.
- Sizing records were unchanged across 1,442 version-2/version-3 pairs. The
  largest measured annual-objective change from accepted version-2 outputs
  was 0.05564%; this is not a bound on changes from the canonical models.
- Instrumented runs confirmed the surface actuators were inactive throughout
  measured annual simulation.

This is finite validation. It does not prove convergence for every point in the
continuous domain or reproduce the publication's objective distributions.
Earlier P4 corrections also changed annual convection: selected 26.2 annual
outputs changed by up to 23.12% from the canonical outputs. Some canonical
comparison outputs contained warmup diagnostics and remain unaccepted. Small
version-2/version-3 differences therefore do not imply canonical equivalence.
See [historical HVAC compatibility](historical-hvac.md) for P6/P8's separate
cross-engine correction.

## Solver bounds and failure records

Both PDFO BOBYQA entry points and the Py-BOBYQA callback handle endpoint roundoff.
For example, `5.832000000000002` is two adjacent binary64 values above the
upper bound `5.832`. The adapter uses the exact endpoint for the simulation and
returned design. It rejects three-step overshoots, nonfinite coordinates, and
wrong dimensions. This narrow allowance is recorded in solver metadata; it does
not widen the physical design bounds.

The [recorded endpoint cases](../reference/pdfo-endpoint-cases.json) exercise the
real solver against saved objective observations. The
[simulation failure fixtures](../reference/replication-failure-cases.json) and
[native baselines](../reference/baselines) independently check model inputs,
strict diagnostics, and accepted values. Existing failed records retain their
original status; a repaired adapter or model does not retroactively validate them.
