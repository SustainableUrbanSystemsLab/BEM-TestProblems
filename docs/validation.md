# Validation evidence and coverage

The continuous scope is **1–6, 8–10 and 13**. Validation separates the published
specification, the executable C#/EnergyPlus-8.5 implementation and the modern
EnergyPlus-26.2 model. Agreement with one does not establish agreement with all
three.

## Published specification

The independent assertions in `tests/test_paper_specification.py` use Waibel et al.
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
Waibel's tables. Likewise, the detailed model's individual fan observations are
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

**Complete Waibel pointwise result coverage is currently 0/10.** Figures 8–9 are
boxplots, Figures 10–11 are ranks and later figures are normalized/aggregate
metrics. Approximate costs mentioned in prose do not identify complete input
vectors. They are unsuitable as exact evaluator fixtures.

Waibel et al. explicitly identify supplementary material associated with the DOI.
Its contents and applicable license must be inventoried before any numerical
fixture coverage is claimed. This is a known accepted validation gap, not a claim
that a supplement or reference dataset does not exist.

The originating papers provide additional candidates:

- Wetter and Wright (2004), Table 1, pairs base/best vectors with rounded results
  for six simple/detailed climate cases. These used **EnergyPlus 1.1.0** and a
  different normalized parameter convention for detailed geometry.
- Kämpf et al. (2010), Tables 5/9 and 10/11, give small/large-office candidate
  vectors and rounded San Francisco results from **EnergyPlus 2.2**. Some window
  columns contain heights rather than upper coordinates.
- Djuric et al. (2007) is the source to inspect for the school cost constants and
  any complete reference solution.

Those values are not unconditional expected outputs for modified version-8.5 or
version-26.2 models. A pointwise fixture must record the full vector, objective,
engine/build, model identity/modifications, weather hash or design-day definition,
variable mapping, printed precision and justified tolerance. The new implementation
must not be advertised as completely validated against published point values
until that evidence is available.

## Original reference implementation

`reference/legacy-source/` preserves the five relevant C# components plus `Misc.cs`
unchanged at upstream commit `54736a6b899a488222ad3184f306c1f401daf4f9`. Their
checksums, templates and notices are checked by `tests/test_licenses.py`.

The oracle in `reference/Oracle/`, with the engine proxy in
`reference/EngineProxy/`, compiles/executes that source with lightweight host
stubs. It is a reference-code comparison, not a second Python implementation of
the same formulas. Each numerical parity result must identify its input vector,
engine build, model/weather identities and comparison tolerance. A compilation
success or passing formula test alone is not evidence that all ten simulations
matched.

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

## Independent public-CI weather

Public-CI code parity uses **independently generated analytic weather**, produced
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
for a public-CI comparison. This tests executable equivalence under controlled
inputs; it does not reproduce a TMY-based published objective or certify canonical
benchmark climate performance. The problem objects keep their historical weather
filenames, and canonical checks use separately provided, authorized, hash-frozen
original weather. Never rename synthetic files to historical weather filenames.

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
unchanged templates, transition steps and license notices. Typed parameter
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
ledgers retain full precision. The change is `(modern / historical - 1) × 100%`.

| Problem | Version 8.5 | Version 26.2 | Change |
| --- | ---: | ---: | ---: |
| 1 | 153.181082 | 147.566000 | -3.67% |
| 2 | 194.745959 | 186.875943 | -4.04% |
| 3 | 173.274743 | 170.143885 | -1.81% |
| 4 | 147.638635 | 172.688497 | +16.97% |
| 5 | 214.609328 | 241.746830 | +12.65% |
| 6 | 179.577025 | 201.960714 | +12.46% |
| 8 | 173.938191 | 190.621682 | +9.59% |
| 9 | 843.380000 | 840.870000 | -0.30% |
| 10 | 1198.570000 | 1201.820000 | +0.27% |
| 13 | 1932.967349 | 1928.196660 | -0.25% |

These are newly measured evaluator values, not published optima. In particular,
the detailed-office increases require visible component-level drift reporting;
a passing modern regression means stable modern results, not numerical equality
to the old engine.

## Weather use and distribution boundary

No historical weather data is bundled or published in CI caches/artifacts. The
official [EnergyPlus weather documentation](https://energyplus.readthedocs.io/en/stable/auxiliary-programs/auxiliary-programs.html#tmy2-data-set-format)
describes TMY2's intended use in building-system simulation comparisons and its
download availability. Current [NLR Data and Software terms](https://www.nlr.gov/disclaimer)
grant use/copy of data on that server with notice retention and publication credit.
That server-specific grant does not by itself establish the exact terms of each
converted EPW hosted elsewhere, including embedded ASHRAE design conditions.

Accordingly, automatic acquisition rights for the **four exact historical US EPW
packages remain incompletely established** here. Public CI avoids that assumption
through independently generated weather. Belgrade IWEC has separate ASHRAE terms.
Canonical integration runs require authorized external paths, hashes and retained
source notices; publishing raw weather or source datasets requires a separate
distribution review. See [licensing.md](licensing.md) and `assets/manifest.json`.
