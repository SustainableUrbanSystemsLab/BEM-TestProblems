# Optimization experiments following the 2019 study

The experiment follows the random-start and evaluation-budget protocol of
[Waibel, Wortmann, Evins, and Carmeliet (2019)](https://doi.org/10.1016/j.enbuild.2019.01.048).
Its aim is a qualitative comparison with Figures 8 and 9 for the ten continuous
problems, using both EnergyPlus 8.5 and 26.2. Exact historical seeds, starting
vectors, and raw optimizer trajectories are unavailable. Fresh recorded seeds
make this rerun reproducible without claiming the original trajectories.
[Waibel's 2018 thesis Appendix C](published-solutions.md) supplies rounded final
designs for a separate literature comparison. Those are neither starting points
nor verified full-precision winning records from the journal study.

## Protocol and solver coverage

Each problem/solver/engine combination requests **20 runs**. Each run has a hard
objective-call limit of **100 × (n + 1)**, including initialization and repeated
points. Starts are uniformly sampled in physical box coordinates. DIRECT uses
the box midpoint. The same recorded starts are paired across the other solvers
and both engines; this pairing is our explicit experimental choice because the
study does not specify shared starts. All coordinates and solver seeds are saved
before simulations begin. Canonical benchmark weather is checksum-verified.

| Problem | Variables | Maximum calls per run |
| --- | ---: | ---: |
| 1, 2, 3 | 4 | 500 |
| 4, 5, 6, 9, 10 | 13 | 1400 |
| 8 | 11 | 1200 |
| 13 | 10 | 1100 |

Available study methods retain their Figure 8/9 order; additions follow them:

| Display order | Implementation | Setting differences and limitations |
| --- | --- | --- |
| DIRECT | NLopt `GN_DIRECT` | Same algorithm family; exact historical Goat version/defaults are unverified |
| CRS2 | NLopt `GN_CRS2_LM` | Seeded randomized search; same historical-default limitation |
| Sbplex | NLopt `LN_SBPLX` | Random physical initial point; same historical-default limitation |
| CMA-ES | Author's `cma` Python package | Initial mean is the recorded random start; unit-box scaling and initial step size 0.3 are explicit rerun settings |
| PDFO BOBYQA | `pdfo`, method `bobyqa` | Added method; bounded scaling, recorded start preserved |
| Py-BOBYQA | `pybobyqa` | Added method; bounded scaling, deterministic local mode, no global-restart heuristic |

The eight BB-O tuned/untuned SGA, ES, PSO and FIPS methods are skipped because
their original operators/tuned implementation have not been ported and validated.
Silvereye and Galapagos GA/SA have no validated Python adapter here. RBFOpt is
skipped because its historical configuration and external optimization
dependencies have not been provisioned. Generic substitutes are not relabeled
as those implementations. The manifest retains the full original solver order,
metadata and omission reasons.

With these six methods, the full experiment requests **2,400 optimization runs**
and at most **2,592,000 objective calls**. Early termination can reduce the total.

## Local setup and execution

Use the existing project virtual environment and the local engine/weather setup
in the [engine guide](engine-versions.md). The tested numerical and plotting
versions are recorded in [replication-py312.txt](../constraints/replication-py312.txt).
Install optional experiment dependencies with those constraints:

```sh
.venv/bin/python -m pip install -c constraints/replication-py312.txt -e '.[replication]'
```

On Windows or Linux with a compatible NLopt wheel, also install:

```sh
.venv/bin/python -m pip install -c constraints/replication-py312.txt -e '.[replication-nlopt]'
```

NLopt 2.7.1 is pinned to keep NumPy 1 compatibility with PDFO 2.2. On Apple Silicon
it requires a local source build; an uninstalled dependency is reported as
unavailable rather than silently replaced. All optional libraries remain outside
the repository and package distributions. Their licenses are listed in
[third-party notices](../THIRD_PARTY_NOTICES.md).

The Apple Silicon build used for this experiment stays entirely in `.tools` and
`.venv`. These commands use the official tag (source commit
`09b3c2a6da71cabcb98d2c8facc6b83d2321ed71`):

```sh
.venv/bin/python -m pip install 'cmake==3.31.10' 'swig==4.5.1'
nlopt_version='2.7.1'
nlopt_source=".tools/nlopt-source-$nlopt_version"
nlopt_build=".tools/nlopt-build-$nlopt_version"
git clone --branch "v$nlopt_version" --depth 1 https://github.com/stevengj/nlopt.git "$nlopt_source"
.venv/bin/cmake -S "$nlopt_source" -B "$nlopt_build" \
  -DCMAKE_POLICY_DEFAULT_CMP0148=OLD \
  -DCMAKE_INSTALL_PREFIX="$PWD/.tools/nlopt/$nlopt_version" \
  -DPYTHON_EXECUTABLE="$PWD/.venv/bin/python" \
  -DINSTALL_PYTHON_DIR="$PWD/.venv/lib/python3.12/site-packages" \
  -DSWIG_EXECUTABLE="$PWD/.venv/bin/swig" \
  '-DCMAKE_CXX_FLAGS=-DPyString_Check=PyUnicode_Check -DPyInt_Check=PyLong_Check' \
  -DNLOPT_PYTHON=ON -DNLOPT_OCTAVE=OFF -DNLOPT_MATLAB=OFF \
  -DNLOPT_GUILE=OFF -DNLOPT_TESTS=OFF -DCMAKE_BUILD_TYPE=Release
.venv/bin/cmake --build "$nlopt_build" --parallel 8
.venv/bin/cmake --install "$nlopt_build"
```

The two preprocessor aliases bridge old Python names in the binding generator
to Python 3 names; they do not alter the optimization algorithms. The source and
installed libraries retain their licenses. Runtime versions and binary hashes
are recorded even when a source build has no Python distribution metadata.

From a checkout with both engines in `.tools/energyplus/<version>/`:

```sh
.venv/bin/python tools/run_replication.py \
  --solvers direct crs2 sbplex cma_es bobyqa pybobyqa \
  --workers 8 --seed 2019 \
  --problems 1 13 2 3 4 5 6 8 9 10 --schedule problem-first \
  --diagnostics-policy strict \
  --output-root .validation-local/replication-strict
```

The defaults are all ten continuous problems, both engines, 20 repetitions and
the paper's budget. Use `--executable-8-5` or `--executable-26-2` for other local
engine locations. No experiment command downloads or installs anything.
The example completes P1 first, then P13, so each figure group has a populated
panel early. `--schedule balanced` instead interleaves problems by repetition.
Only execution order changes; starts, seeds and per-run budgets stay identical.
Each worker is a separate process to isolate optimizer random states. Successful
raw simulator outputs are removed after numerical/provenance checkpoints are
saved; failure diagnostics are retained. `--retain-success diagnostics` keeps
successful diagnostic files as well. No raw weather is published.

Repeat the same command to resume. Terminal runs are retained; an interrupted
solver restarts from its original recorded start and seed. Changed inputs,
software, settings or model/weather hashes require a separate output directory.
This is a restart of an interrupted run, not recovery of its optimizer state.

A smoke experiment can explicitly use `--repetitions 2 --budget 25` and its own
output directory. Such overrides label the result **PILOT**, and cannot be
presented as the paper-budget experiment.

## Reproducibility scope

- The experiment manifest records starts, seeds, budgets, solver settings,
  exact numerical package versions, and input/engine hashes. Reusing a result
  directory with changed recorded inputs or software is rejected.
- [replication-py312.txt](../constraints/replication-py312.txt) constrains the
  tested numerical and plotting Python versions. It does not install unused
  optional methods, freeze development tools, or lock native binary contents.
- An exact optimizer replay also depends on the interpreter, operating system,
  and native libraries. Source-built NLopt links a separate algorithm library;
  retain that library's hash together with the Python extension hash and the
  compiler/build information. Matching only a package version is insufficient
  for a claim of identical trajectories across machines.
- The running campaign retains its frozen source and original manifest.
  Supplementary local environment records capture Python/OS versions, native
  NLopt library hashes, and complete frozen Python-source hashes without changing
  the campaign identity.
- [Objective repeatability checks](validation.md#reproducibility) are complete.
  The full optimization campaign is still running; exact full-campaign replay
  and historical-study replication have not been demonstrated.

## Diagnostics and figures

The default policy is strict: Severe/Fatal diagnostics reject an evaluation,
stop that optimization run and retain the best prior valid observation
separately. Those partial incumbents do not enter completed-run boxplots.

The original C# caller can return annual objectives despite warmup-convergence
Severe messages. A separate `--diagnostics-policy reference-warmup` experiment
can mirror that behavior for completed runs whose only Severe diagnostics are
warmup convergence. Fatal errors, other Severe diagnostics, incomplete output
and unsuccessful process termination remain failures. Every included warmup
diagnostic is recorded. These experimental values are not accepted strict
benchmark evaluations; neither the models nor the normal objective API changes.
The study does not explicitly state its simulator-diagnostic policy, so matching
the supplied C# behavior is distinct from proving that every study run had that
condition.

### P1 extended-warmup comparison

The explicit P1 `warmup-100` model extends the legacy maximum warmup allowance
from 25 to 100 days while retaining the original tolerances. The modern model
already uses 100 days, so its rendered input is unchanged. The variant has its
own provenance and manifest identity; it is not exact historical model parity.
See the [native validation](warmup-diagnostics.md#p1-extended-warmup-variant).

Add `--p1-warmup-100` to a strict replication command and use a new output
directory. Starts, seeds, solver settings, and budgets stay paired with the
canonical experiment. Severe/Fatal diagnostics still reject evaluations; this
option does not recover their objective outputs or invent penalty values.

Generate or refresh plots from the saved experiment, including while it runs:

```sh
.venv/bin/python tools/plot_replication.py .validation-local/replication-strict
```

PNG and SVG files are generated for the Figure 8 continuous subset (P1–6, P8)
and Figure 9 continuous subset (P9, P10, P13), separately for each engine. The
figures show raw physical objectives, quartile boxes, red medians and outliers,
and 1.5-IQR whiskers. Exact quartile/whisker rules were not specified by the study;
NumPy linear quartiles are our documented convention. Matching engine panels
share objective-axis limits. Axes are uncapped so poor outcomes remain visible.

The default figures include only completed trajectories with explicit evidence
that no warmup-Severe outputs were used anywhere in the search. A strict winning
point alone is insufficient. Labels show the included/requested counts, failed
attempts, and excluded non-strict trajectories. Missing strictness evidence is
also excluded. Selecting only successful trajectories can bias distributions;
these figures do not turn a permissive campaign into a strict-policy rerun.

For a separately recorded `reference-warmup` experiment, explicitly request its
diagnostic figures with `--include-diagnostic-runs`. They are labelled **NOT
STRICT** and saved to a different default directory, so they cannot overwrite
the strict figures. The numerical summary records the selection policy and
warmup-error usage. These figures describe compatibility with the original
caller, rather than establishing simulation correctness.

Pending/running runs are not values. Partial campaigns are labeled
**INCOMPLETE**; failed attempts are never replaced by penalties or silently
counted as successful. Numerical summaries retain distributions, best designs,
failure counts and engine-median differences with percentages against 8.5.
Different failure rates can bias a comparison of completed-run medians.

The qualitative patterns to assess are: DIRECT/CMA-ES usually have low medians
and spread for P1–6/P8; CRS2/Sbplex are often competitive with occasional
outliers. For P9, DIRECT is strong and Sbplex performs poorly. For P10, DIRECT
and CMA-ES are strong while Sbplex has a low median with a large spread. For
P13, CRS2 has a larger spread than DIRECT/CMA-ES/Sbplex. These are descriptive
patterns reported in the study, not acceptance thresholds or predicted results
for the newer engine or a different diagnostic policy.

Please also cite [Ragonneau and Zhang (2023)](https://doi.org/10.48550/arXiv.2302.13246)
for PDFO and [Cartis, Fiala, Marteau and Roberts (2019)](https://doi.org/10.1145/3338517)
for Py-BOBYQA. Full bibliography entries are in [references.bib](../references.bib).
