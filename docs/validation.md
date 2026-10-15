# Validation evidence and coverage

The continuous scope is **1–6, 8–10 and 13**. Validation separates the published
specification, the executable C#/EnergyPlus-8.5 implementation and the modern
EnergyPlus-26.2 model. Agreement with one does not establish agreement with all
three.

See the [complete canonical-case table and warmup failure analysis](warmup-diagnostics.md)
for all 26 audited designs, the additional P1 trial and the separate diagnostic
experiments investigating the rejected evaluations.

## Published specification

The independent assertions in `tests/test_paper_specification.py` use
Waibel, Wortmann, Evins and Carmeliet
(2019), [doi:10.1016/j.enbuild.2019.01.048](https://doi.org/10.1016/j.enbuild.2019.01.048).
They compare published numerical bounds, constants, fixed settings and formula
structure against the Python definitions. Their algebra probes use explicitly
synthetic observables; they are not fabricated published simulation outcomes.

| Problems | Direct specification evidence | Pointwise published `x → f(x)` coverage |
| --- | --- | --- |
| 1–3 | Table 2: four coordinates; Table 3: order/bounds; §3.3.1: Seattle/Houston/Chicago TMY2 mapping; Eq. (5): efficiencies 0.44/0.77, electricity factor 3 and area normalization | No complete pair identified in the main paper |
| 4–6 | Table 2: 13 coordinates; Table 4: order/bounds; §3.3.2: climates; Eq. (6): electricity factor 3 and gas factor 1 | No complete pair identified in the main paper |
| 8 | Eleven free coordinates; original x11 fixed at 25°C, x13 at 12°C; Chicago; Table 4 and Eq. (6) | No complete pair identified in the main paper |
| 9–10 | 13 coordinates; Table 5: order/bounds; San Francisco; Eq. (7): factors 1.092/3.095 and multiplicative window penalties | No complete pair identified in the main paper |
| 13 | Ten coordinates; Table 7: insulation/radiator bounds; nine-zone school; Eq. (10): energy + insulation + radiator cost | No complete pair identified in the main paper; component formulas require the reference implementation/original study |

The preserved model/reference-code areas used in algebra checks are separate
model facts; they are not presented as numerical solution points printed in
the study's tables. Likewise, the detailed model's individual fan observations are
not specified by the paper's aggregate electricity symbol alone.

### Known paper/code differences

- **Problems 9–10, minimum window height:** Eq. (7) prints 0.55 m with a `>= 0`
  violation test. The original C# uses 0.5488 m. Compatibility mode preserves the
  C# threshold. Tests exercise values on both sides and in the intervening
  interval; they retain the paper value as separate metadata.
- **Problems 4–6 and 8, fan accounting:** Eq. (6) uses aggregate fan/lighting
  electricity. The C# implementation reads the same supply-fan ESO row twice
  instead of combining distinct supply/return observations. Compatibility mode
  preserves that mapping. A synthetic algebra probe makes the mapping difference
  visible; it is not a claimed reconstruction of the paper's physical fan total.
- **Problem 13:** Eq. (10) specifies additive cost categories, not all component
  constants or annualization assumptions. Detailed component checks identify the
  original C# as their source. The embedded Belgrade design day and the historical
  location discrepancy remain part of the preserved model definition.

These differences are not silently corrected to force an apparent match. A
scientifically revised definition would require a separately identified version.

### Numerical paper-result gap

**Complete pointwise result coverage for the 2019 study is currently 0/10.** The
numerical publication reference is Waibel, Wortmann, Evins and Carmeliet (2019),
using EnergyPlus 8.5.0. Earlier
studies remain cited for problem origins and formula attribution; their numerical
results are not validation targets for this project.

Figures 8–9 show distributions of final objective values, Figures 10–11 show
ranks, and later figures show normalized or aggregate metrics. The boxplots
support approximate visual context only. They do not provide full-precision
winning objective values together with the complete corresponding decision
vectors. The paper explicitly defers analysis in variable space to future work
(printed page 220). Approximate costs in prose cannot fill that gap.

The inspected [Supplement S1](https://ars.els-cdn.com/content/image/1-s2.0-S0378778818331682-mmc1.xml)
is a 927-byte XML metadata record identifying `BEOBenchmark_V1` and EnergyPlus
8.5.0. It links to the [GitHub implementation](https://github.com/christophwaibel/BEOBenchmark/tree/master/BEOBenchmark_V1),
and contains no winning objective values or decision vectors. The
[publisher](https://www.sciencedirect.com/science/article/pii/S0378778818331682)
labels the supplement CC BY 4.0; that label does not replace the repository's
code license or establish licenses for its external models/weather. Complete
winning numerical records remain an unresolved data requirement. No exact
`f_opt` or `x_opt` has been inferred from a plot or invented by a new run.

A numerical fixture from that study needs the complete vector and matching objective,
engine/build, model identity/modifications, weather hash or design-day definition,
variable mapping, full available precision and justified comparison tolerance.
The missing winning vectors currently block comparison of decision-variable
differences against the study's winning designs. New midpoint measurements or newly optimized
best-found designs would not establish the missing publication ground truth.

The paper's optimization protocol is also distinct from a single short solver
run: it uses 20 reruns, random initial solutions except DIRECT's domain-centre
start, and an evaluation budget of `100(n+1)` for the scoped problems. Those
conditions describe the study; they do not supply its unavailable winning
vectors. The implementation must not be advertised as numerically validated
against the study's pointwise results until the required evidence is obtained.

## Original reference implementation

The five relevant original C# components plus `Misc.cs`, and the nine original
IDF templates, are retrieved on demand from upstream commit
`54736a6b899a488222ad3184f306c1f401daf4f9` into the ignored reference cache.
`data/reference-assets.json` pins their URLs and checksums. The repository and
its packages contain the derived Python/modern models and full required notices,
not the original C#/IDF bodies. `tests/test_licenses.py` checks that boundary and
the recorded provenance; `tools/fetch_reference.py` verifies fetched bytes.

The oracle in `reference/Oracle/`, with the engine proxy in
`reference/EngineProxy/`, compiles/executes that source with lightweight host
stubs. It is a reference-code comparison, not a second Python implementation of
the same formulas. Each numerical parity result must identify its input vector,
engine build, model/weather identities and comparison tolerance. A compilation
success or passing formula test alone is not evidence that all ten simulations
matched.

The configured simulation-result acceptance policy is relative error `1e-6`
against the reference value, with absolute tolerance `1e-7` for values near zero.
It applies to objectives and simulator components. Input coordinates, weather
checksums, model schema and field identities remain strict checks; this numerical
policy does not authorize changing those inputs or widening tolerances until a
comparison passes. Published rounding and unmatched historical engine/model
conditions remain separately reported limitations of literature comparisons.

The executed [cache-based Windows reference comparison](https://github.com/SustainableUrbanSystemsLab/BEM-TestProblems/actions/runs/38670364758/job/116211825885)
passed all **26 synthetic-weather cases** at commit
`d4b2c5cfce3002de0fca15a77781310085a584af`. It fetched checksum-verified originals
into the ignored cache, then compared the unchanged C# objective,
generated IDF fields and fixed-row reference observations with the Python
objective and named observations using the same EnergyPlus-8.5 engine/weather.
The C# objective/component tolerance was relative `2e-12`, absolute `1e-9`;
numeric IDF fields used absolute `1e-11`. The workflow retained the numerical
comparison artifact. A [job-specific evidence record](validation-results/original-csharp-ci.json)
links its status, commit, timing and conditions. This establishes reference-code
parity for those cases at that commit, including reference acquisition, fixed-file
compilation and execution. The ledger also retains the earlier successful job
at commit `3bbd439`.

That historical artifact used the stricter tolerances stated above. The current
configured `1e-6`/`1e-7` policy is a later acceptance decision; the historical job
has not been relabeled as having run with the new settings.

A previous [workflow run](https://github.com/SustainableUrbanSystemsLab/BEM-TestProblems/actions/runs/38672334196)
passed all five jobs at commit `f08ce001fcbc8f94040b9a1e694f1595ca55b601`.
Its [C#/Python comparison](https://github.com/SustainableUrbanSystemsLab/BEM-TestProblems/actions/runs/38672334196/job/116218106526)
passed all 26 cases using the current relative `1e-6`, absolute `1e-7` policy.
The modern regression passed 26 cases and all 169 checked values; five repeated
cases reproduced all 39 checked values exactly. These checks cover their explicit
designs and synthetic weather, not entire continuous domains or published optima.

EnergyPlus version **8.5.0-c87e61b44b** was verified to load and run an untouched
official design-day example on the development Mac. That smoke test completed
without warnings or severe errors; it establishes environment feasibility, not
benchmark numerical equivalence with the original publication's Windows runs.

The local canonical-weather [version-8.5 audit ledger](validation-results/8.5.0-canonical-audit.json)
records all ten physical midpoints and sixteen additional boundary/penalty/embedded
cases, with explicit vectors and engine/model/weather hashes. All ten midpoints
completed; **25 of 26 cases** completed without severe/fatal diagnostics. The
unchanged problem-10 simultaneous-lower-bound case emitted seven warmup-convergence
severe diagnostics at its original 25-day cap. It remains a recorded source-model
failure. This ledger measures the Python runner with the historical engine; it
does not itself claim executable C# parity.

## Canonical and supplemental public-CI weather

The current workflow has separate canonical-weather checks for both engines.
Each retrieves the four exact US files into temporary runner storage using
`tools/fetch_weather.py`, verifies their checksums and exercises
`reference/canonical-cases.json`. That fixture contains the 26 audit designs and
the paired P1 orientation-90 trial. The 8.5 job also compiles and executes the
unchanged C# components; the 26.2 job compares with measured canonical references.

The checks compare both values and simulation outcomes. A successful case must
have no Severe/Fatal diagnostics and match the recorded objective/components at
relative `1e-6`, absolute `1e-7`. The two recorded 8.5 rejections (P10 lower and
P1 orientation90) and the recorded 26.2 rejection (P4 lower) must retain their
warmup-only diagnostic signatures. They have no accepted scalar objective in
the baselines. Unexpected failures, changed signatures and newly successful
previously rejected cases fail the check pending review. The job summary reports
successful and rejected counts explicitly; a passing outcome check does not mean
all 27 simulations succeeded.

P13's Python cases use no EPW. The unchanged C# caller requires a weather-path
argument; a verified Seattle file fills that unused argument, recorded separately.
Independent no-EPW measurements cover its lower, midpoint and upper designs,
and a C#-mode command check confirms the midpoint components/objective are
identical with no EPW and with Seattle. Its embedded design day remains the
physical climate input. Belgrade IWEC is not downloaded or redistributed.

Raw weather, source models and simulation directories are never uploaded.
Numerical JSON reports retain actual values, signed/absolute differences,
percentage changes, diagnostic outcomes and provenance. Canonical baselines
are frozen project measurements; they are not published optimum references.

Supplemental public-CI code parity uses **independently generated analytic weather**, produced
by:

```sh
python tools/synthetic_weather.py --output-dir /path/to/temporary/synthetic-weather
```

The generator writes 8,760-record files named `synthetic_seattle.epw`,
`synthetic_houston.epw`, `synthetic_chicago.epw` and
`synthetic_san_francisco.epw`. Their headers say **SYNTHETIC-CI**, identify the new
MIT authorship and state that they are not measured/canonical weather. The
standard-library generator reads no weather dataset. It prescribes seasonal and
diurnal temperatures and simplified analytic solar/humidity/wind quantities.
The output directory includes the complete `SYNTHETIC-CI-LICENSE.txt` notice.
Tests check record coverage, field counts, physical ranges, deterministic output
and unmistakable synthetic filenames.

The generated Seattle EPW was also accepted by a real annual EnergyPlus-8.5 run
of the untouched official `1ZoneUncontrolled.idf` example: exit 0, no severe/fatal
errors and no weather-format warnings. Its three location/pressure warnings were
caused by that stock Denver model being paired deliberately with synthetic
Seattle weather. This establishes EPW ingestion, not benchmark numerical parity.

The unchanged C# and Python evaluators must receive **the same synthetic file**
for a supplemental public-CI comparison. This tests executable equivalence under controlled
inputs; it does not reproduce a TMY-based published objective or certify canonical
benchmark climate performance. The problem objects keep their historical weather
filenames. Canonical local setup uses `python tools/fetch_weather.py`, which
retrieves the four original US files into `.cache/weather/` and verifies their
frozen hashes. Never rename synthetic files to historical weather filenames.

Problem 13 is a design-day case. Separate local checks with versions 8.5 and 26.2
found identical heating-energy/rate observables at the physical midpoint under
three invocations: no EPW, an unrelated Seattle EPW, and an explicit design-day
flag/no EPW. Each engine agreed exactly across its own three invocations; the
two engines produced different values. This supports a weather-free CI path for
that design. The [numeric ledger](validation-results/problem-13-weather-invariance.json)
retains the parameters, input/engine/weather hashes and observables. It is not a
proof of invariance for every parameter vector.

## Modern model checks

Modern epJSON models have conversion/provenance sidecars linking them to the
checksum-pinned external templates, transition steps and packaged license/model
notices. Sidecar `original_notice` paths preserve the historical derivation
layout; the named original is now resolved through the reference index/cache.
Typed parameter
bindings must cover the original placeholders and retain the same physical
coordinate meanings. Problem 8 shares the detailed Chicago model with its two
fixed settings.

Per-model sidecars also describe every manual compatibility change beyond the
official transition chain:

- Simple office models allow up to 100 warmup days instead of 25 after a measured
  version-26.2 convergence failure, preserving the original convergence tolerances.
- Detailed office models make an effective historical reciprocal surface reference
  explicit for stricter modern validation. Their original geometry is preserved,
  including the documented noncoincident surface/multiplier caveat.
- Problem 10 renames a duplicate setpoint manager with no name references before
  the version-24.2 transition.
- Problem 13 replaces an inactive autosized capacity field with an explicit zero;
  hard radiator UA and maximum water flow remain the runtime inputs. The sidecar
  cites the relevant old/new engine source paths.

These changes are part of the modern model identity and remain separate from the
immutable version-8.5 inputs. They do not silently redefine the legacy benchmark.

Modern tests require successful version-26.2 execution and named output extraction,
and report objective/component drift relative to version 8.5. A solver upgrade can
change physical results. Modern results must not be forced to equal old-engine
fixtures by widening tolerances or changing the historical objective silently.
Actual successful case counts belong in the generated validation reports; a
model-conversion or binding-coverage check alone is not a simulation pass.

The local canonical-weather [version-26.2 audit ledger](validation-results/26.2.0-canonical-audit.json)
records the same 26 explicit designs: **25 completed**, including all ten
midpoints. Problem 4 at simultaneous lower bounds emitted a South-zone warmup
severe diagnostic at the original 25-day cap. A scratch 100-day cap also failed;
the recorded model and convergence tolerances were retained. This is a different
failure from the version-8.5 problem-10 corner. Successful midpoint tests therefore
do not establish successful simulation of the full continuous domains.

The midpoint measurements below use identical canonical weather bytes across
versions and each version's recorded model identity. Units are kWh/(m² year) for
problems 1–8, MJ/m² for 9–10 and EUR for 13. Values are rounded for display; the
ledgers retain full precision. The baseline is version 8.5. The signed difference
is `modern - historical`; the percentage is `100 × (modern - historical) / |historical|`.

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

These are newly measured evaluator values, not published optima. In particular,
the detailed-office increases require visible component-level drift reporting;
a passing modern regression means stable modern results, not numerical equality
to the old engine.

## Real default-solver smoke

A [P1 BOBYQA integration record](validation-results/p1-bobyqa-smoke.json) uses
commit `f08ce001fcbc8f94040b9a1e694f1595ca55b601`, canonical Seattle weather,
physical midpoint `[0, 3, 3, 0.5]` and a 100-objective-call budget. EnergyPlus
26.2 completed after 84 calls, reducing the objective from `147.5659999247044`
to `133.33534913204608` kWh/(m² year): a decrease of **14.23065079
kWh/(m² year), or 9.6436%**, relative to the starting value. Its best design was
`[-1.1214112901192836, 4.856626576011762, 5.1732490024320175, 0.27307365349378676]`.
All 84 distinct simulations passed strict diagnostics; termination occurred at
BOBYQA's lower trust-region-radius bound. This demonstrates solver integration,
not a global optimum, agreement with the study's optimum or replication of its protocol.

EnergyPlus 8.5 stopped at its first new trial, `[90, 3, 3, 0.5]`: minimum-temperature
warmup change was `0.00647 K`, exceeding the `0.004 K` tolerance after 25 days.
The strict evaluator propagated the severe-diagnostic error instead of accepting
an objective or substituting a penalty. This is a source-model convergence
limitation surfaced by the deliberate acceptance policy; the unchanged C# did
not reject those diagnostics. The CI designs do not include this trial.

A scratch 100-day cap removed that severe diagnostic but changed the objective
by **+0.00093710 kWh/(m² year), or +0.000599%**, against the failed run's
diagnostic-only value (relative change approximately `5.99e-6`). This is a
diagnostic comparison, not a comparison of two accepted canonical evaluations.
That exceeds the configured `1e-6` comparison threshold and changes the input
identity. Neither the scratch variant nor the failed-run value is an accepted
historical optimization result. Original models and convergence tolerances remain
unchanged.

## Weather use and distribution boundary

No historical weather data is bundled or published in CI caches/artifacts. The
official [EnergyPlus weather documentation](https://energyplus.readthedocs.io/en/stable/auxiliary-programs/auxiliary-programs.html#tmy2-data-set-format)
describes TMY2's intended use in building-system simulation comparisons and its
download availability. Current [NLR Data and Software terms](https://www.nlr.gov/disclaimer)
grant use/copy of data on that server with notice retention and publication credit.
That server-specific grant does not by itself establish the exact terms of each
converted EPW hosted elsewhere, including embedded ASHRAE design conditions.

Local acquisition is implemented by `python tools/fetch_weather.py`: it downloads
the four frozen US files from the pinned fork into the ignored `.cache/weather/`
directory and verifies their hashes. This reproducibility mechanism does not
claim a blanket redistribution license for the converted EPWs. Canonical CI
fetches the same files temporarily, synthetic weather remains supplemental, and
raw canonical data is excluded from published caches/artifacts. Problem 13 uses the embedded winter design day without
an EPW; Belgrade IWEC remains outside the downloader. See
[licensing.md](licensing.md) and `assets/manifest.json` for source terms and scope.
