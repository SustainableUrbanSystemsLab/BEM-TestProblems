# Validation evidence and coverage

- **Scope:** continuous problems **1–6, 8–10, and 13**.
- **Three separate comparisons:** the published specification, the original
  C#/EnergyPlus 8.5 implementation, and the modern EnergyPlus 26.2 models.
  Agreement with one does not establish agreement with all three.
- **Detailed diagnostics:** the [canonical-case table and warmup analysis](warmup-diagnostics.md)
  cover the 26 original audit designs, the additional P1 orientation-90 trial,
  and the diagnostic experiments for rejected evaluations.
- **Related guides:** [automated testing](testing.md),
  [optimization replication](optimization-replication.md), and
  [problem origins and references](references.md).

## What public CI checks

The [validation workflow](../.github/workflows/validate.yml) has seven jobs:

| Jobs | Inputs | What they check |
| --- | --- | --- |
| Three pytest jobs | Linux, Windows, and macOS | Python behavior, branch coverage, and lint; Linux also builds the distribution |
| Canonical C# versus Python | EnergyPlus 8.5; 27 canonical designs | Unchanged C# versus Python, generated model fields, and recorded successful/rejected outcomes |
| Canonical modern model | EnergyPlus 26.2; the same 27 designs | Objective/components and diagnostics against reviewed modern references; exact repeatability of five midpoints |
| Supplemental C# versus Python | EnergyPlus 8.5; 26 synthetic-weather designs | Executable parity with controlled analytic weather |
| Supplemental modern model | EnergyPlus 26.2; the same 26 synthetic-weather designs | Modern references and exact repeatability of five midpoints |

### Inputs and acceptance rules

- **Canonical inputs:** [canonical-cases.json](../reference/canonical-cases.json)
  contains the 26 audit designs plus the paired P1 orientation-90 trial.
  [fetch_weather.py](../tools/fetch_weather.py) retrieves the four exact US weather
  files into temporary storage and verifies their checksums.
- **Canonical references:**
  [8.5.0-canonical.json](../reference/baselines/8.5.0-canonical.json) and
  [26.2.0-canonical.json](../reference/baselines/26.2.0-canonical.json) record
  project measurements and diagnostic outcomes. They are not published optima.
- **Supplemental inputs:** [cases.json](../reference/cases.json) contains the 26
  synthetic-weather designs; [26.2.0-synthetic.json](../reference/baselines/26.2.0-synthetic.json)
  records their modern references.
- **Successful simulations:** no Severe/Fatal diagnostics; objective and simulator
  components must match at relative tolerance `1e-6`, with absolute tolerance
  `1e-7` near zero.
- **Strict input checks:** coordinates, weather checksums, model schema, and field
  identities must match. Modern generated model hashes must match the reviewed
  inputs. Numerical tolerances do not permit input changes.
- **Recorded rejections:** EnergyPlus 8.5 rejects P10 lower bounds and P1
  orientation 90; EnergyPlus 26.2 rejects P4 lower bounds. Their warmup-only
  diagnostic signatures must match, and they have no accepted scalar objective
  in the baselines.
- **Changes requiring review:** unexpected failures, changed diagnostic signatures,
  and newly successful previously rejected cases fail CI. A passing outcome
  check does not mean that all 27 simulations succeeded.
- **Reports:** numerical JSON reports include actual values, signed/absolute
  differences, percentage changes, diagnostic outcomes, and provenance. Job
  summaries distinguish successful and rejected cases. Raw weather, source
  models, and simulation directories are never uploaded.

### Problem 13's weather input

- Python uses the embedded design day without an EPW.
- The unchanged C# caller requires a weather-path argument. A verified Seattle
  file fills that unused argument and is recorded separately.
- Independent no-EPW measurements cover the lower, midpoint, and upper designs.
  A C#-mode command check confirms identical midpoint components/objective with
  no EPW and with Seattle.
- Belgrade IWEC is not downloaded or redistributed.

## Checks against the published specification

- [test_paper_specification.py](../tests/test_paper_specification.py) checks the
  bounds, constants, fixed settings, and formula structure in
  [Waibel, Wortmann, Evins, and Carmeliet (2019)](https://doi.org/10.1016/j.enbuild.2019.01.048).
- Algebra probes use explicitly synthetic observables. They are not published
  simulation results.
- Model/reference-code areas used in those probes are separate model facts.
  The paper's aggregate electricity symbol alone does not specify the detailed
  model's individual fan observations.

| Problems | Specification checked | Complete published `x → f(x)` pair available? |
| --- | --- | --- |
| 1–3 | Table 2: four coordinates; Table 3: order/bounds; §3.3.1: Seattle/Houston/Chicago TMY2 mapping; Eq. (5): efficiencies 0.44/0.77, electricity factor 3, and area normalization | No |
| 4–6 | Table 2: 13 coordinates; Table 4: order/bounds; §3.3.2: climates; Eq. (6): electricity factor 3 and gas factor 1 | No |
| 8 | Eleven free coordinates; original x11 fixed at 25°C and x13 at 12°C; Chicago; Table 4 and Eq. (6) | No |
| 9–10 | 13 coordinates; Table 5: order/bounds; San Francisco; Eq. (7): factors 1.092/3.095 and multiplicative window penalties | No |
| 13 | Ten coordinates; Table 7: insulation/radiator bounds; nine-zone school; Eq. (10): energy + insulation + radiator cost | No; detailed component formulas also require the reference implementation/original study |

### Known paper/code differences

- **Problems 9–10 — minimum window height:** Eq. (7) prints 0.55 m with a
  `>= 0` violation test; the C# code uses 0.5488 m. Compatibility mode preserves
  the C# threshold. Tests cover both sides and the intervening interval, with
  the paper value retained as separate metadata.
- **Problems 4–6 and 8 — fan accounting:** Eq. (6) uses aggregate fan/lighting
  electricity. The C# code reads the same supply-fan ESO row twice instead of
  combining distinct supply/return observations. Compatibility mode preserves
  that mapping. A synthetic algebra probe exposes the difference without
  claiming to reconstruct the paper's physical fan total.
- **Problem 13 — cost details:** Eq. (10) gives additive cost categories, but not
  every component constant or annualization assumption. Detailed checks identify
  the C# code as their source. The embedded Belgrade design day and historical
  location discrepancy remain part of the preserved model.
- **Versioning:** a scientifically revised definition would need a separately
  identified version. These differences are not silently corrected.

## Limits of comparison with the paper's results

**Complete pointwise result coverage for the 2019 study is currently 0/10.**

- **Numerical target:** Waibel, Wortmann, Evins, and Carmeliet (2019), using
  EnergyPlus 8.5.0. Earlier studies are cited for problem origins and formulas;
  their numerical results are not this project's validation targets.
- **Available results:** Figures 8–9 show final-objective distributions, Figures
  10–11 show ranks, and later figures show normalized or aggregate metrics.
  These provide approximate visual context.
- **Missing results:** full-precision winning objectives paired with complete
  decision vectors. The paper defers variable-space analysis to future work
  (printed page 220). Approximate prose values cannot supply those missing pairs.
- **Supplement:** [Supplement S1](https://ars.els-cdn.com/content/image/1-s2.0-S0378778818331682-mmc1.xml)
  is a 927-byte XML metadata record linking
  [BEOBenchmark_V1](https://github.com/christophwaibel/BEOBenchmark/tree/master/BEOBenchmark_V1)
  and identifying EnergyPlus 8.5.0. It contains no winning objectives or vectors.
  The [publisher's CC BY 4.0 label](https://www.sciencedirect.com/science/article/pii/S0378778818331682)
  for the supplement does not replace the code license or establish licenses
  for external models/weather.
- **No inferred ground truth:** no exact `f_opt` or `x_opt` is inferred from a
  plot or supplied by a new optimization run. Missing published vectors also
  prevent decision-variable difference comparisons against the winning designs.

A usable pointwise publication reference would need:

- The complete decision vector and matching objective, at full available precision.
- The engine/build, model identity/modifications, and weather hash or design-day
  definition.
- The variable mapping and a justified comparison tolerance.

The optimization protocol is a separate comparison:

- The paper uses **20 reruns**, random initial solutions except DIRECT's
  domain-centre start, and **`100(n+1)` objective evaluations**.
- A short solver smoke test does not reproduce that protocol.
- New midpoint or best-found values do not replace missing published solution
  records. Qualitative boxplot replication is described in the
  [optimization replication guide](optimization-replication.md).
- Pointwise numerical validation against the study remains unresolved until the
  required records are available.

## Original C# implementation

### Source and comparison method

- **Acquisition:** [fetch_reference.py](../tools/fetch_reference.py) retrieves the
  five relevant C# components, their shared helper, and nine IDF templates from
  commit `54736a6b899a488222ad3184f306c1f401daf4f9` into an ignored cache.
- **Identity:** [reference-assets.json](../src/bem_testproblems/data/reference-assets.json)
  pins the URLs and checksums. [test_licenses.py](../tests/test_licenses.py) checks
  provenance, required notices, and exclusion of the original C#/IDF bodies from
  the repository/packages.
- **Execution:** [Oracle.csproj](../reference/Oracle/Oracle.csproj) compiles the
  original code with lightweight host stubs;
  [EngineProxy.csproj](../reference/EngineProxy/EngineProxy.csproj) provides the
  engine proxy. This executes the reference C# rather than duplicating its
  formulas in Python.
- **Comparison:** unchanged C# and Python receive the same EnergyPlus 8.5
  engine/weather. Checks compare objectives, generated IDF fields, and fixed-row
  C# observations against named Python observations.
- **Evidence required:** each result identifies its vector, engine build,
  model/weather identities, and tolerances. Compilation or formula tests alone
  cannot establish simulation parity for all ten problems.

### Recorded runs

| Evidence | Result | Scope and limitations |
| --- | --- | --- |
| [Historical Windows comparison](https://github.com/SustainableUrbanSystemsLab/BEM-TestProblems/actions/runs/38670364758/job/116211825885) at `d4b2c5c` | All 26 synthetic-weather cases passed | Objective/components used relative `2e-12`, absolute `1e-9`; numeric IDF fields used absolute `1e-11` |
| [Later Windows comparison](https://github.com/SustainableUrbanSystemsLab/BEM-TestProblems/actions/runs/38672334196/job/116218106526) at `f08ce00` | All 26 synthetic-weather cases passed | Objective/components used the current relative `1e-6`, absolute `1e-7` policy |
| [Same five-job workflow](https://github.com/SustainableUrbanSystemsLab/BEM-TestProblems/actions/runs/38672334196) | All five jobs passed | Modern checks passed 26 cases/169 values; five repeats reproduced all 39 values exactly |
| [8.5.0-canonical-audit.json](validation-results/8.5.0-canonical-audit.json) | 25 of 26 canonical-weather cases passed strict diagnostics; all ten midpoints completed | Python with the historical engine; this ledger alone does not establish executable C# parity |

- [original-csharp-ci.json](validation-results/original-csharp-ci.json) retains
  job statuses, full commits, timing, conditions, and the earlier success at
  `3bbd439`. Historical jobs retain their actual tolerances.
- The 26-case canonical audit includes ten physical midpoints and sixteen
  boundary/penalty/embedded cases. P10 at simultaneous lower bounds emitted
  seven warmup-convergence Severe diagnostics at its original 25-day cap.
- EnergyPlus **8.5.0-c87e61b44b** also ran an untouched official design-day
  example on the development Mac without warnings or Severe errors. That
  establishes local feasibility, not numerical equivalence to the publication's
  Windows runs.
- These results cover explicit designs and conditions, not whole continuous
  domains or published optima. Rounding and unmatched historical engine/model
  conditions remain separate limitations for literature comparisons.

## Modern models and engine differences

### Model identity

- Modern models have provenance sidecars connecting them to checksum-pinned
  templates, transition steps, and required notices. See the
  [model transition guide](model-transition.md).
- Sidecar `original_notice` paths preserve the historical derivation layout;
  originals are resolved through the linked
  [reference-assets.json](../src/bem_testproblems/data/reference-assets.json)
  index/cache.
- [parameter_bindings.json](../src/bem_testproblems/data/modern/parameter_bindings.json)
  must cover the original placeholders and preserve their physical meanings.
  P8 shares the detailed Chicago model with its two fixed settings.
- Sidecars record every manual compatibility change beyond the official
  transition chain:

| Models | Recorded compatibility change |
| --- | --- |
| Simple offices | Up to 100 warmup days instead of 25 after a measured 26.2 convergence failure; original convergence tolerances retained |
| Detailed offices | An effective historical reciprocal surface reference made explicit for modern validation; original geometry and documented noncoincident surface/multiplier caveat retained |
| P10 | An unreferenced duplicate setpoint manager renamed before the 24.2 transition |
| P13 | An inactive autosized capacity replaced by explicit zero; hard radiator UA and maximum water flow retained as runtime inputs; sidecar cites old/new engine source paths |

- These changes define the modern model identity; historical 8.5 inputs remain
  immutable.
- Modern tests require successful 26.2 execution and named output extraction.
  Conversion and binding checks alone do not establish simulation success.
- Engine changes can alter physical results. Modern CI checks stable modern
  values against its own baseline. The midpoint table below reports drift from
  8.5; equality across engines is not required.

### Canonical midpoint results

- [26.2.0-canonical-audit.json](validation-results/26.2.0-canonical-audit.json)
  records the same 26 designs as the historical audit: **25 completed**, including
  all ten midpoints.
- P4 at simultaneous lower bounds emitted a South-zone warmup Severe diagnostic
  at the original 25-day cap. A scratch 100-day cap also failed; the recorded
  model and convergence tolerances were retained.
- This differs from the historical P10 failure. Successful midpoints do not
  establish successful simulation throughout the continuous domains.
- The table uses identical canonical weather bytes across engines and each
  engine's recorded model identity. Values are rounded; the ledgers retain full
  precision.
- Units: kWh/(m² year) for P1–8, MJ/m² for P9–10, and EUR for P13.
- **Baseline:** 8.5. Signed difference: `modern - historical`. Percentage:
  `100 × (modern - historical) / |historical|`.

| Problem | Version 8.5 | Version 26.2 | Δ objective | Δ (%) |
| --- | ---: | ---: | ---: | ---: |
| 1 | 153.181082 | 147.566000 | -5.615082 | -3.6656% |
| 2 | 194.745959 | 186.875943 | -7.870016 | -4.0412% |
| 3 | 173.274743 | 170.143885 | -3.130858 | -1.8069% |
| 4 | 147.638635 | 172.688497 | +25.049861 | +16.9670% |
| 5 | 214.609328 | 241.746830 | +27.137502 | +12.6451% |
| 6 | 179.577025 | 201.960714 | +22.383688 | +12.4647% |
| 8 | 173.938191 | 190.621682 | +16.683491 | +9.5916% |
| 9 | 843.380000 | 840.870000 | -2.510000 | -0.2976% |
| 10 | 1198.570000 | 1201.820000 | +3.250000 | +0.2712% |
| 13 | 1932.967349 | 1928.196660 | -4.770689 | -0.2468% |

- These are newly measured evaluator values, not published optima.
- The detailed-office increases require component-level drift reporting. Neither
  objective definitions nor tolerances are changed to force old/new agreement.

## Default-solver smoke test

The [p1-bobyqa-smoke.json](validation-results/p1-bobyqa-smoke.json) record uses
commit `f08ce001fcbc8f94040b9a1e694f1595ca55b601`, canonical Seattle weather,
the physical midpoint `[0, 3, 3, 0.5]`, and a 100-objective-call budget.

### EnergyPlus 26.2

- **Calls:** 84 distinct simulations, all passing strict diagnostics.
- **Objective:** `147.5659999247044 → 133.33534913204608` kWh/(m² year).
- **Improvement:** **14.23065079 kWh/(m² year), or 9.6436%**, relative to the
  starting value.
- **Best design:**
  `[-1.1214112901192836, 4.856626576011762, 5.1732490024320175, 0.27307365349378676]`.
- **Termination:** BOBYQA's lower trust-region-radius bound.
- **Meaning:** solver integration demonstrated; no claim of global optimality,
  agreement with the study's optimum, or replication of its protocol.

### EnergyPlus 8.5

- **Failure:** the first new trial, `[90, 3, 3, 0.5]`, exceeded the minimum-temperature
  warmup tolerance after 25 days: `0.00647 K` versus `0.004 K`.
- **Strict behavior:** the evaluator propagated the Severe-diagnostic error.
  It accepted neither an objective nor a substitute penalty. The unchanged C#
  caller did not reject those diagnostics.
- **Current coverage:** canonical CI now includes this orientation-90 trial as
  a recorded rejection.
- **Diagnostic experiment:** a scratch 100-day cap removed the Severe diagnostic
  but changed the objective by **+0.00093710 kWh/(m² year), or +0.000599%**,
  relative to the failed run's diagnostic-only value.
- **Interpretation:** that relative change (about `5.99e-6`) exceeds the `1e-6`
  threshold and changes input identity. Neither value is an accepted historical
  optimization result; original models and convergence tolerances remain unchanged.

## Supplemental synthetic weather

- **Purpose:** controlled inputs for additional C#/Python parity and modern-model
  checks. Canonical-weather checks remain separate.
- **Generator:** [synthetic_weather.py](../tools/synthetic_weather.py) uses only
  the standard library and reads no weather dataset.
- **Output:** four clearly synthetic EPWs with 8,760 records each, analytic
  seasonal/diurnal temperatures, and simplified solar/humidity/wind quantities.
  Headers identify **SYNTHETIC-CI**, new MIT authorship, and noncanonical weather.
  The output includes the complete generated-weather license notice.
- **Tests:** [test_weather_fixture.py](../tests/test_weather_fixture.py) checks
  coverage, field counts, physical ranges, determinism, and unmistakable filenames.
- **Parity rule:** the C# and Python evaluators receive the same synthetic file.
  Never rename synthetic files to historical weather filenames.
- **Ingestion smoke:** a real annual 8.5 run of an untouched official single-zone
  example accepted generated Seattle weather: exit 0, no Severe/Fatal errors,
  and no weather-format warnings. Three location/pressure warnings came from
  deliberately pairing the stock Denver model with Seattle weather. This checks
  EPW ingestion, not benchmark parity.
- **P13 invariance check:** [problem-13-weather-invariance.json](validation-results/problem-13-weather-invariance.json)
  records identical midpoint heating observables within each engine for no EPW,
  an unrelated Seattle EPW, and an explicit design-day flag/no EPW. The engines
  differed from each other. This supports that design's weather-free path, not
  invariance for every vector.

## Weather use and distribution

- **Acquisition:** [fetch_weather.py](../tools/fetch_weather.py) retrieves the four
  original US EPWs from the pinned fork into an ignored local cache and verifies
  their frozen hashes. Canonical CI retrieves the same bytes temporarily.
- **Distribution:** historical weather is excluded from the repository and
  published CI caches/artifacts. Acquisition does not establish blanket
  redistribution rights for converted EPWs.
- **Source terms:** the [EnergyPlus weather documentation](https://energyplus.readthedocs.io/en/stable/auxiliary-programs/auxiliary-programs.html#tmy2-data-set-format)
  describes TMY2 use and availability. [NLR's server terms](https://www.nlr.gov/disclaimer)
  allow use/copy of data on that server with notice retention and credit. That
  server-specific grant does not establish each externally hosted converted EPW's
  terms, including embedded ASHRAE design conditions.
- **P13:** uses its embedded winter design day; Belgrade IWEC remains outside the
  downloader.
- **Further details:** [licensing.md](licensing.md),
  [weather-redistribution.md](weather-redistribution.md), and
  [manifest.json](../assets/manifest.json).
