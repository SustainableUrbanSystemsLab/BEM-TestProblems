# Failed replication runs

- **Coverage:** [replication-failure-cases.json](../reference/replication-failure-cases.json)
  freezes **24 distinct engine/design combinations from 34 failed run records**:
  16 pilot records and 18 extended-campaign records. The initial snapshot was
  captured on October 16, 2026, at 05:47 UTC, and extended through a bounded
  06:53 UTC audit and one later P6 sizing-period failure. Other later records
  are outside this cohort.
- **Observed outcome:** every recorded failure is a warmup-convergence **Severe**
  diagnostic after 25 days, with **zero Fatal errors**. Each process exited with
  code zero and wrote “Completed Successfully.” Those signals alone do not make
  its objective valid. All failed designs satisfy their box constraints.
- **Evidence:** the fixture records full vectors, original evaluation indices,
  successful prefixes, diagnostic excerpts, and input, weather, and engine hashes.
  These are new project measurements, rather than published reference values.

## Causes and numerical changes

| Problems | Recorded failure | Fixed recipe in `convergence-refined` |
| --- | --- | --- |
| P1, EnergyPlus 8.5 | Temperature history has not converged at the 25-day cap | Allow 100 warmup days, preserving both convergence tolerances |
| P4, both engines | Temperature differences, and sometimes peak-load differences, remain above tolerance | Warmup cap 100; HVAC iteration cap 100; 12 timesteps/hour and 12 sizing-average steps |
| P5, EnergyPlus 26.2 | Temperature differences remain above tolerance | Warmup cap 100; HVAC iteration cap 100; analytical zone-air integration; 12 timesteps/hour and 12 sizing-average steps |
| P6, both engines | Slow annual temperature convergence in 8.5; summer-sizing cooling-load nonconvergence in 26.2 | Warmup cap 100; 12 timesteps/hour and 12 sizing-average steps; original HVAC iteration cap and integration |
| P10, both engines | Daily peak heating or cooling loads fail convergence, while temperature checks pass | Warmup cap 100; 12 timesteps/hour; 12 sizing-average steps; analytical zone-air integration; original HVAC iteration cap 20 |

- The earlier [warmup analysis](warmup-diagnostics.md) distinguishes slow P1
  initialization from persistent P4/P10 cycling. Increasing warmup days alone did
  not remove the latter failures. Individual controllers have not been isolated
  as the sole cause of every new failure.
- The explicit recipes are defined in
  [numerical_controls.py](../src/bem_testproblems/numerical_controls.py).
  Each recipe is fixed for a problem and preserves the physical parameters,
  objective formula, and convergence tolerances. It defines a separate numerical
  function; historical equivalence is not claimed.
- All timestep changes preserve the original **60-minute sizing average**.
  Simply doubling the timestep count while retaining the old averaging-step
  count would also change the sizing calculation.
- Additional days alone did not repair every design. The new P4 case still
  failed with 100 warmup days and 100 HVAC iterations, including an analytical
  integration probe; the fixed timestep recipe passed after 13 days. One P10
  case still failed after 100 days at 12 timesteps/hour; analytical integration
  resolved that recorded failure after 11 days without increasing HVAC iterations.
- The broader audit found a P5 design that still failed four temperature checks
  after 100 days with analytical integration and 100 HVAC iterations. Its maximum
  temperature residuals were 0.044–0.051 K, against the unchanged 0.004 K limit;
  load checks passed. Adding the same 12/12 timestep and sizing settings resolved
  it after 13 days. Earlier P5 cases and both engine midpoint controls were
  remeasured under this fixed recipe. Their revised measurements supersede the
  earlier P5 profile; the baseline records its prior Git revision and provenance.
  This demonstrates sensitivity to numerical resolution, without establishing
  one controller as the unique cause.

Select a numerical variant explicitly:

```python
from bem_testproblems import get_problem, make_objective

problem = get_problem(4, numerical_variant="convergence-refined")
objective = make_objective(problem)
```

The ordinary `get_problem(4)` keeps the canonical definition. The variant is
available for P1, P4, P5, P6, and P10. A failed evaluation
raises an error; it does not receive a substitute objective or penalty. A running
canonical experiment is not silently switched to a numerical variant.

## Measured results

All 24 repaired inputs and nine midpoint controls completed with **zero Severe
or Fatal errors**, using the recorded canonical weather. These are evaluations
of fixed designs, not restarted optimization runs or claims of convergence
throughout the box. Full-precision vectors, components, terms, model identities,
and settings are in the reviewed
[8.5 baseline](../reference/baselines/8.5.0-replication-failures.json) and
[26.2 baseline](../reference/baselines/26.2.0-replication-failures.json).

| Recorded failed case | Repaired annual warmup days | Repaired objective |
| --- | ---: | ---: |
| `p01-8.5.0-bobyqa-r000-e0001` | 27 | 204.528660 |
| `p04-26.2.0-bobyqa-r000-e0001` | 23 | 170.826614 |
| `p04-8.5.0-pybobyqa-r000-e0005` | 21 | 150.950765 |
| `p05-26.2.0-pybobyqa-r000-e0033` | 14 | 214.334090 |
| `p04-26.2.0-bobyqa-r001-e0031` | 13 | 157.012973 |
| `p01-8.5.0-bobyqa-r002-e0001` | 29 | 173.619522 |
| `p01-8.5.0-pybobyqa-r001-e0002` | 28 | 155.697909 |
| `p10-26.2.0-bobyqa-r002-e0001` | 20 | 1641.855000 |
| `p10-26.2.0-pybobyqa-r000-e0010` | 13 | 2412.640000 |
| `p10-8.5.0-bobyqa-r001-e0001` | 14 | 1158.020000 |
| `p10-8.5.0-bobyqa-r002-e0003` | 19 | 1636.800000 |
| `p10-8.5.0-pybobyqa-r000-e0012` | 11 | 2386.420000 |
| `p10-8.5.0-pybobyqa-r002-e0015` | 19 | 1637.610000 |
| `p06-8.5.0-bobyqa-r001-e0001` | 23 | 338.310089 |
| `p01-8.5.0-bobyqa-r003-e0001` | 32 | 174.051459 |
| `p01-8.5.0-bobyqa-r004-e0002` | 28 | 158.663445 |
| `p04-26.2.0-bobyqa-r004-e0033` | 15 | 151.378973 |
| `p05-26.2.0-bobyqa-r001-e0065` | 11 | 202.019728 |
| `p05-26.2.0-bobyqa-r002-e0067` | 13 | 201.286392 |
| `p10-26.2.0-bobyqa-r001-e0091` | 9 | 1115.320000 |
| `p10-26.2.0-bobyqa-r003-e0003` | 14 | 1867.365000 |
| `p10-8.5.0-bobyqa-r000-e0089` | 13 | 2138.940000 |
| `p10-8.5.0-bobyqa-r003-e0033` | 14 | 1821.045000 |
| `p06-26.2.0-bobyqa-r006-e0025` | 16 | 200.675430 |

Objectives for P1, P4, P5, and P6 are in kWh/(m² year); P10 uses MJ/m².
Canonical failed evaluations have **no accepted objective**.

The midpoint controls quantify changes to previously valid evaluations:

| Problem | EnergyPlus | Canonical objective | Refined objective | Signed difference | Difference (%) |
| --- | --- | ---: | ---: | ---: | ---: |
| P1 | 8.5.0 | 153.181082 | 153.181082 | +0.000000 | +0.000000% |
| P4 | 8.5.0 | 147.638635 | 152.865617 | +5.226982 | +3.540389% |
| P5 | 8.5.0 | 214.609328 | 213.627610 | -0.981718 | -0.457444% |
| P6 | 8.5.0 | 179.577025 | 180.067794 | +0.490769 | +0.273292% |
| P10 | 8.5.0 | 1198.570000 | 1260.450000 | +61.880000 | +5.162819% |
| P4 | 26.2.0 | 172.688497 | 180.567867 | +7.879370 | +4.562765% |
| P5 | 26.2.0 | 241.746830 | 248.638758 | +6.891927 | +2.850886% |
| P6 | 26.2.0 | 201.960714 | 204.320870 | +2.360156 | +1.168621% |
| P10 | 26.2.0 | 1201.820000 | 1265.170000 | +63.350000 | +5.271172% |

Percentage differences use `100 × (refined − canonical) / |canonical|`.
The largest control change here is **+5.271172%**. The numerical variants
therefore require their own reference values and experiment labels; they are
not evidence that these objectives equal the historical C# benchmark.

The earlier P6 failure design also passed with the final EnergyPlus 26.2
profile after eight annual warmup days. The later P6 design exposes a separate
**summer-sizing** failure: its interior-zone cooling-load difference remained
**6.98086%** after 100 sizing warmup days, above the unchanged **4%** limit.
The annual run converged in 16 days even while sizing failed. The final timestep
recipe removed the sizing Severe error. Its annual warmup count remains 16;
the successful sizing-period day count is not reported.

`actual_warmup_days` in the measurements records the annual RunPeriod summary.
Failed sizing environments and their warmup caps are recorded separately.
Strict validation checks Severe/Fatal diagnostics from **every phase**.

## PDFO endpoint roundoff

- Three searches stopped when the adapter rejected a proposed point before
  submitting that point to EnergyPlus. PDFO's scaling
  mapped a lower-bound endpoint of `1.224` to `1.2239999999999998`, one adjacent
  binary64 float outside the box. This is a Python solver-adapter issue, separate
  from the warmup errors also seen through C#.
- Both PDFO entry points normalize only that immediately adjacent outside float to
  its endpoint. Larger violations, nonfinite values, and invalid dimensions still
  fail. Direct problem calls and other solver adapters retain strict bounds.
- Saved replay coordinates use relative and absolute tolerances of `1e-12` for
  differences between compiled PDFO builds. Windows CI observed a `2.586e-12`
  difference in an interior coordinate before reaching the failing endpoint.
  The endpoint must still equal `1.224` exactly; production bound guards and
  native objective-comparison tolerances are unchanged.
- [The recorded traces](../reference/pdfo-endpoint-cases.json) reproduce all three
  failures using existing objective values and the real PDFO solver. The
  [replication-adapter tests](../tests/test_replication_solvers.py) stop at the
  first unsaved evaluation, without inventing an objective or running EnergyPlus. They verify
  feasible recorded coordinates, rejection boundaries, and the evaluation budget.
  The [public solver tests](../tests/test_optimize.py) also cover its callback and
  the returned design vector.
- These fixes do not alter the source of an experiment already running. Its
  failed records remain failed, with their original diagnostic evidence.

### Cross-platform precision

- The same P4 start-0 model and weather produced **170.826614330621** on macOS
  and **170.827190446342** on Linux: **+0.000576115721 kWh/(m² year)**,
  or **+0.000337251735%**. Both simulations passed strict diagnostics.
- The largest measured component difference in the two affected P4 designs was
  **0.0012808956%**. These differences are below the native comparison target of
  **0.01%** (`rtol=1e-4`). Every actual value and signed difference remains in
  the CI report. Model and weather checksums must still match exactly.
- This tolerance concerns numerical comparisons between native builds. It does
  not change EnergyPlus's warmup tolerances, permit Severe/Fatal errors, or
  identify a numerical variant with the canonical benchmark.

## What the tests require

- These errors also occur through the original C# caller. The
  [canonical Windows comparison](https://github.com/SustainableUrbanSystemsLab/BEM-TestProblems/actions/runs/38855535049/job/116826022732)
  reproduced P1 orientation-90 and P10 lower-bound warmup errors. The expanded
  check additionally replays every recorded EnergyPlus 8.5 failure through the
  unchanged C# components, comparing generated model fields and failure
  signatures. Values returned by C# for these runs remain diagnostic only.

- [test_replication_failures.py](../tests/test_replication_failures.py) checks all
  recorded vectors and rendered input hashes, strict rejection despite successful
  process markers, retained valid prefixes, and continuation of other scheduled
  runs. Failed observations have no accepted objective. A valid prefix remains
  available for diagnosis, but its failed search is excluded from strict rankings.
- [test_numerical_controls.py](../tests/test_numerical_controls.py) checks that
  only the declared numerical fields change and that unexpected canonical fields
  cause an error.
- The [native validator](../tools/validate_replication_failures.py), exercised by
  [its tests](../tests/test_replication_failure_validation.py), requires canonical
  failures to retain their reviewed diagnostic signatures. Separately, each
  numerical variant must pass strict diagnostics and match reviewed objective,
  component, and additive-term values across native builds at `rtol=1e-4`
  (0.01%), with `atol=1e-7` near zero. Same-engine C#/Python parity in the
  [original-code checks](../tools/validate_cases.py) remains at `rtol=1e-6`.
- [GitHub Actions](../.github/workflows/validate.yml) performs these native checks
  with both EnergyPlus versions and canonical weather. The validator requires an
  existing reviewed baseline and cannot create or update it. An unexpected
  canonical success, changed failure signature, or failed numerical variant
  requires review.
- Public fixtures contain original numerical observations and sanitized
  diagnostics under the project's [licensing rules](licensing.md). Raw models,
  weather files, simulation folders, and literature transcriptions are excluded.
