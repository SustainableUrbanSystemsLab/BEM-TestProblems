# Reproducing the model transition

The packaged modern models were derived from checksum-pinned EnergyPlus 8.5 IDFs
using **21 official Transition programs**, followed by the official 26.2
`ConvertInputFormat` utility. Transition is a maintainer operation performed once
per template. Evaluations edit the resulting epJSON through audited parameter
bindings; they do not run this chain again. Nine distinct templates serve the ten
continuous problems because problem 8 shares problem 6's model.

## Official tools and their roles

EnergyPlus's **IDFVersionUpdater** is a graphical front end for the individual
version-to-version Transition programs. This project invokes those console
programs directly so each stage, diagnostic and tool hash can be recorded; the
GUI was not used to generate the packaged models. The official documentation
describes both approaches in
[Using Older Version Input Files — Transition](https://energyplus.readthedocs.io/en/v26.2.0/auxiliary-programs/auxiliary-programs.html#using-older-version-input-files-transition).

| Tool | Operation used here |
| --- | --- |
| `Transition-V8-5-0-to-V8-6-0`, and the corresponding program for every later step | Change the IDF objects and fields for the next EnergyPlus release |
| `ConvertInputFormat` from EnergyPlus 26.2 | Convert the already transitioned 26.2 IDF into epJSON |
| `tools/transition_models.py` | Sequence those external tools on scratch copies and write provenance |

`ConvertInputFormat` changes the serialization format; it does not replace the
historical version transitions. Its version-specific behavior and flags are
documented in the official
[IDF/epJSON conversion guide](https://energyplus.readthedocs.io/en/v26.2.0/essentials/essentials.html#converting-between-idf-and-epjson).
The invocation used by this project is:

```text
ConvertInputFormat -f epJSON -o OUTPUT_DIRECTORY INPUT_26_2.idf
```

The exact chain is:

```text
8.5 → 8.6 → 8.7 → 8.8 → 8.9 → 9.0
    → 9.1 → 9.2 → 9.3 → 9.4 → 9.5 → 9.6
    → 22.1 → 22.2 → 23.1 → 23.2 → 24.1 → 24.2
    → 25.1 → 25.2 → 26.1 → 26.2
```

The jump from 9.6 to 22.1 follows EnergyPlus's version numbering. Every version
in the tool's `VERSIONS` sequence has a patch component of `.0`.

## Project-local prerequisites

Install the pinned current release with the normal project-local installer:

```sh
.venv/bin/python tools/install_energyplus.py
```

Fetch the original reference files explicitly before rendering a legacy input:

```sh
.venv/bin/python tools/fetch_reference.py
```

This verifies the pinned originals into the ignored
`.reference-cache/beobenchmark/` directory. Templates are under its `models/`
subdirectory; original C# sources are under `legacy-source/`. These originals
are external reference material and are excluded from the source distribution
and wheel. `BEM_REFERENCE_DIR` can select an alternative cache root; pass its
matching template path to `--source-template` below. Normal modern evaluations
use packaged epJSON and do not need this fetch.

Its resulting `.tools/energyplus/26.2.0` directory must contain
`ConvertInputFormat` and `PreProcess/IDFVersionUpdater`. The audited 26.2 package
supplied the sixteen transitions from 9.0 through 26.2, with their versioned
IDDs. The installer checks the release archive against
[the pinned download manifest](../assets/energyplus-downloads.json).

Obtain the five earlier transitions, from 8.5 through 9.0, from the official
[EnergyPlus Support transition downloads](https://energyplushelp.freshdesk.com/support/solutions/folders/67000579810).
Choose the **8.4–9.0 archive for the host platform**, read its supplied instructions
and retain the applicable notices. Extract the required programs and their
supporting files into an ignored project-local directory such as
`.tools/transition-tools/8.4-to-9.0`. The project installer does not download this
historical archive. Our wrapper accepts its separate location through
`--historical-dir`; merging it into the current installation is unnecessary.

That directory must directly contain the five `Transition-V…-to-V…` executables,
the `V8-5-0-Energy+.idd` through `V9-0-0-Energy+.idd` files, and the supplied
`Report Variables … to ….csv` files. Keep the extracted supporting files together.
On Windows the executable filenames end in `.exe`; the wrapper accepts that
suffix automatically. Check the selected binaries' host architecture and runtime
requirements before using them.

The development audit used the support site's
[Mac 8.4–9.0 archive](https://energyplushelp.freshdesk.com/support/solutions/articles/67000728573-mac-programs-for-converting-v8-4-0-to-v9-0-0-idf-files),
[attachment 67089987420](https://energyplushelp.freshdesk.com/helpdesk/attachments/67089987420),
whose downloaded SHA-256 was
`45dbb9ec6654a8b0359511e98d5e4528a249a5e4d8475c42b5dfa6ffaa74c932`.
The inspected transition binaries ran natively on the development ARM Mac.
That checksum identifies this audited Mac archive, not the Windows/Linux downloads
or a future replacement of the attachment. No transition binaries or IDDs are
redistributed in this repository.

## Scratch example

From the repository root on macOS or Linux, the following creates a rendered
problem-1 midpoint and a converted model in a new temporary directory after the
explicit fetch above. It leaves cached originals and packaged modern models
untouched. No weather or simulation is
needed for the conversion. On Windows, use the project's
`.venv\Scripts\python.exe` and equivalent shell path syntax.

```sh
transition_scratch="$(mktemp -d "${TMPDIR:-/tmp}/bem-transition.XXXXXX")"

.venv/bin/python - "$transition_scratch/problem_1.idf" <<'PY'
import json
import sys
from pathlib import Path
from bem_testproblems import get_problem

problem = get_problem(1)
input_path = problem.render_legacy(problem.midpoint, Path(sys.argv[1]))
parameters = dict(zip((item.name for item in problem.parameters), problem.midpoint))
input_path.with_suffix(".parameters.json").write_text(json.dumps(parameters, indent=2) + "\n")
print(input_path)
PY

.venv/bin/python tools/transition_models.py \
  "$transition_scratch/problem_1.idf" \
  "$transition_scratch/problem_1.epJSON" \
  --energyplus-root .tools/energyplus/26.2.0 \
  --historical-dir .tools/transition-tools/8.4-to-9.0 \
  --source-template .reference-cache/beobenchmark/models/simple_seattle_template.idf \
  --audit-directory "$transition_scratch/audit" \
  --minimum-max-warmup-days 100
```

The input must already have numeric parameter values: unresolved `%…%` tokens
are rejected. The CLI records the rendered input hash; the example saves the
physical vector beside it. Callers using the Python `transition_model()` function
can additionally provide `parameters=…` to include that vector directly in the
provenance sidecar. `--timeout` defaults to 60 seconds **per external tool**;
`--minimum-max-warmup-days` is optional and makes a separately recorded numerical
adjustment, rather than an implicit conversion default.

Each transition gets its own working directory and copies of its old/new IDDs and
report-variable rules. This isolation matters because historical programs write
fixed scratch filenames such as `audit.out`. The wrapper keeps intermediate IDFs,
`.VCpErr` diagnostics and launch logs, checks the new Version object, and rejects
fatal diagnostics even when a tool returns zero. Inspect those diagnostics before
treating the chain as successful.

## Conversion boundaries and reviewed adjustments

Mechanical conversion required two narrowly scoped normalizations in the wrapper:

- It removes only standalone legacy section markers `End Lead Input;`,
  `Simulation Data;` and `End Simulation Data;` before epJSON conversion. These are
  bookkeeping delimiters rather than current simulation objects.
- Before the 24.1→24.2 step it handles the old P10 duplicate name shared by a
  Scheduled and MixedAir setpoint manager. Only the unreferenced MixedAir
  identifier gains `__MixedAir`; fields and controlled nodes are preserved.
  Ambiguous duplicate/reference cases require manual review.

The final packaged models also include reviewed changes outside the official
transition rules. They are identified in the individual provenance sidecars:

| Models | Reviewed adjustment and limit |
| --- | --- |
| P1–P3 | Raise the maximum warmup-day cap from 25 to 100 after a measured P1 convergence failure. Convergence tolerances remain unchanged; this does not guarantee convergence at every design. |
| P4–P6, also used by P8 | Make the historical reciprocal surface reference explicit. Original geometry and zone multipliers remain, including their documented modeling caveats. |
| P13 | Set an inactive radiator capacity-sizing field to zero while preserving hard-sized UA and water flow. Source review and numerical probes support this narrowly defined no-zone-sizing configuration. |

`tools/repair_modern_models.py` implements the detailed-office and school repairs;
it is separate from `transition_models.py`. The scratch P1 example does not
require those family-specific repairs. Rebuilding the full packaged model set
also requires rebuilding and reviewing the typed parameter bindings using
`tools/build_parameter_bindings.py`, then updating the derived-asset and
transition manifests. A new conversion alone is not a complete asset update.

## Preservation and validation

Original IDFs are fetched into `.reference-cache/beobenchmark/models` and verified
against the pinned upstream hashes. Their headers, BSD conditions and additional
notices remain in that external cache; original models and C# files are not
packaged. epJSON cannot retain IDF comments, so the package independently retains
the full required license/model notice text, adjacent `problem_*.provenance.json`
and [third-party notices](../THIRD_PARTY_NOTICES.md). P9/P10 retain the DOE/NREL/PNNL/LBNL
publication-credit and no-endorsement obligations. See
[licensing and provenance](licensing.md) before redistributing derived assets or
external tools. Existing immutable sidecars' `../legacy/…` labels describe the
source layout at conversion time; resolve those named templates through the
pinned reference cache/index. Newly generated sidecars identify the external
cache and upstream commit instead of implying a packaged original.

The sidecars identify the source commit/template hash, rendered input, each tool
and IDD hash, intermediate outputs, converter, normalizations and final model
hash. Reviewed compatibility changes and numerical adjustments are recorded
separately. Keep those records with any derived model; scratch output by itself
is not a distributable replacement for the packaged notice structure.

A successful transition establishes that the files can be converted. It does
not establish equal physics or objectives across EnergyPlus releases. Validation
therefore separates C# versus Python on the same 8.5 engine from 8.5 versus 26.2
model/engine drift, using fixed vectors and identified weather. Synthetic CI
weather is a distinct test variant; historical EPWs remain external inputs and
are not rewritten by this workflow. The
[validation record](validation.md) includes measured results and version-specific
warmup failures that remain visible rather than being hidden by relaxed checks.
