# Failed replication runs

- **Coverage:** [replication-failure-cases.json](../reference/replication-failure-cases.json)
  freezes **13 distinct engine/design combinations from 23 failed run records**:
  16 pilot records and seven extended-campaign records. The snapshot was captured
  on October 16, 2026, at 05:47 UTC. Later failures are outside this snapshot.
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
| P5, EnergyPlus 26.2 | Temperature differences remain above tolerance | Warmup cap 100; HVAC iteration cap 100; analytical zone-air integration |
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
- Both timestep changes preserve the original **60-minute sizing average**.
  Simply doubling the timestep count while retaining the old averaging-step
  count would also change the sizing calculation.
- Additional days alone did not repair every design. The new P4 case still
  failed with 100 warmup days and 100 HVAC iterations, including an analytical
  integration probe; the fixed timestep recipe passed after 13 days. One P10
  case still failed after 100 days at 12 timesteps/hour; analytical integration
  resolved that recorded failure after 11 days without increasing HVAC iterations.

Select a numerical variant explicitly:

```python
from bem_testproblems import get_problem, make_objective

problem = get_problem(4, numerical_variant="convergence-refined")
objective = make_objective(problem)
```

The ordinary `get_problem(4)` keeps the canonical definition. The variant is
available for P1, P4, P5, and P10. A failed evaluation
raises an error; it does not receive a substitute objective or penalty. A running
canonical experiment is not silently switched to a numerical variant.

## Measured results

All 13 repaired inputs and six midpoint controls completed with **zero Severe
or Fatal errors**, using the recorded canonical weather. These are evaluations
of fixed designs, not restarted optimization runs or claims of convergence
throughout the box. Full-precision vectors, components, terms, model identities,
and settings are in the reviewed
[8.5 baseline](../reference/baselines/8.5.0-replication-failures.json) and
[26.2 baseline](../reference/baselines/26.2.0-replication-failures.json).

| Recorded failed case | Repaired warmup days | Repaired objective |
| --- | ---: | ---: |
| `p01-8.5.0-bobyqa-r000-e0001` | 27 | 204.528660 |
| `p04-8.5.0-pybobyqa-r000-e0005` | 21 | 150.950765 |
| `p01-8.5.0-bobyqa-r002-e0001` | 29 | 173.619522 |
| `p01-8.5.0-pybobyqa-r001-e0002` | 28 | 155.697909 |
| `p10-8.5.0-bobyqa-r001-e0001` | 14 | 1158.020000 |
| `p10-8.5.0-bobyqa-r002-e0003` | 19 | 1636.800000 |
| `p10-8.5.0-pybobyqa-r000-e0012` | 11 | 2386.420000 |
| `p10-8.5.0-pybobyqa-r002-e0015` | 19 | 1637.610000 |
| `p04-26.2.0-bobyqa-r000-e0001` | 23 | 170.826614 |
| `p05-26.2.0-pybobyqa-r000-e0033` | 13 | 214.707996 |
| `p04-26.2.0-bobyqa-r001-e0031` | 13 | 157.012973 |
| `p10-26.2.0-bobyqa-r002-e0001` | 20 | 1641.855000 |
| `p10-26.2.0-pybobyqa-r000-e0010` | 13 | 2412.640000 |

Objectives for P1, P4, and P5 are in kWh/(m² year); P10 uses MJ/m².
Canonical failed evaluations have **no accepted objective**.

The midpoint controls quantify changes to previously valid evaluations:

| Problem | EnergyPlus | Canonical objective | Refined objective | Signed difference | Difference (%) |
| --- | --- | ---: | ---: | ---: | ---: |
| P1 | 8.5.0 | 153.181082 | 153.181082 | +0.000000 | +0.000000% |
| P4 | 8.5.0 | 147.638635 | 152.865617 | +5.226982 | +3.540389% |
| P10 | 8.5.0 | 1198.570000 | 1260.450000 | +61.880000 | +5.162819% |
| P4 | 26.2.0 | 172.688497 | 180.567867 | +7.879370 | +4.562765% |
| P5 | 26.2.0 | 241.746830 | 242.291175 | +0.544344 | +0.225171% |
| P10 | 26.2.0 | 1201.820000 | 1265.170000 | +63.350000 | +5.271172% |

Percentage differences use `100 × (refined − canonical) / |canonical|`.
The largest control change here is **+5.271172%**. The numerical variants
therefore require their own reference values and experiment labels; they are
not evidence that these objectives equal the historical C# benchmark.

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
