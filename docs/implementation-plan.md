# Continuous benchmark implementation

Development branch: `codex/beobenchmark-python-continuous`.
Scope: problems 1–6, 8–10 and 13, retaining the published numbering.

## Scientific contract

Historical reference-code behavior is the default. The repeated fan selection
in the detailed problems and the 0.5488 m window-height penalty in problems 9–10
must be recorded explicitly, rather than silently corrected. Paper definitions
and reference-code behavior are independently checked.

All ten problems require empirical comparison with the original C# components
using EnergyPlus 8.5. Comparisons with paired published inputs and results are
added where reproducible cases can be established. Missing numerical paper
coverage is reported explicitly and must not be described as complete paper
validation. EnergyPlus 26.2 results have separate, reviewed regression baselines.

## Implementation sequence

1. Record provenance and licenses; retain the upstream BSD notice and model credits.
2. Build the minimal Python package and original C# reference harness.
3. Demonstrate one complete historical reference comparison.
4. Implement all ten parameter maps and objective decompositions.
5. Transition models once using official tools and validate native epJSON bindings.
6. Complete automated tests, GitHub Actions, local setup and validation reports.

The shared runner uses isolated external EnergyPlus processes and project-local
tools. Python dependencies are installed only in `.venv`. PDFO BOBYQA is the
default optional optimizer. No least-squares residuals are manufactured from
energy or cost terms.

## Webpage approval gate

**No webpage design or implementation is authorized yet.** First implement and
empirically validate the problems, present the results, and obtain the user's
separate, explicit green light before any webpage work.

## Evidence and release gates

Tests must distinguish paper specification checks, numerical paper comparisons,
original-code comparisons on 8.5, and current-engine regression checks. Missing
dependencies fail required integration jobs visibly. Baseline updates are
reviewed changes, never an automatic response to failing tests.

Models, weather, source code, binaries and datasets each require an asset-level
license record. Assets without verified redistribution permission must not enter
public packages or CI artifacts. Publication files, figures and bulk tables are
not distributed.
