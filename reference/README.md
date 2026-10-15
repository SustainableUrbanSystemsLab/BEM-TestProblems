# Independent reference comparisons

The unchanged scoped components are fetched from the BEOBenchmark fork at commit
`54736a6b899a488222ad3184f306c1f401daf4f9`, with their full BSD license, into
the ignored `.reference-cache/beobenchmark/legacy-source` directory. The pinned
download index is `src/bem_testproblems/data/reference-assets.json`; every file's
SHA-256 is verified. Original source and historical IDFs are not included in the
repository or Python distribution.
The oracle compiles those components against test-only Grasshopper interfaces.
It exercises the published C# source, not the proprietary Grasshopper application
or the compiled `.gha` binary. Unused Rhino operations throw if reached.

## Original C# versus Python

The Windows job builds .NET Framework 4.8/x64 executables and sets `en-US` culture.
Using the Framework runtime preserves the historical floating-point-to-string
formatting more closely than rebuilding the source against modern .NET.

`Oracle.exe` supplies physical parameters to the original `SolveInstance` entry
point. `EngineProxy.exe` is staged at its hard-coded engine path, invokes the
genuine pinned 8.5 executable, and copies the input and outputs before the original
component deletes them. No source algorithm is replaced by a Python oracle.
The validator also requires the captured engine exit status, successful completion
marker and absence of severe/fatal diagnostics; the original caller alone does
not check the engine status.

From the repository root on a Windows runner with the official Visual C++ 2013
x64 runtime already installed:

```sh
python tools/fetch_reference.py
python tools/install_reference_engine.py
python tools/synthetic_weather.py --output-dir .validation-local/weather
dotnet build reference/Oracle/Oracle.csproj -c Release -o .tools/reference-bin/oracle
dotnet build reference/EngineProxy/EngineProxy.csproj -c Release -o .tools/reference-bin/proxy
python tools/validate_cases.py --engine .tools/energyplus/8.5.0/energyplus.exe --version 8.5.0 --weather-dir .validation-local/weather --weather-kind synthetic-ci --work-dir .validation-local/original-comparison --output .validation-local/reports/original-csharp.json --oracle .tools/reference-bin/oracle/Oracle.exe --proxy .tools/reference-bin/proxy/EngineProxy.exe
```

Use the project's `.venv` Python interpreter for these commands. The oracle uses
`C:\eplus\EPOpti17\Input731` and `Output731`; this is intended for an isolated CI
runner. Do not run concurrent oracle jobs against the same Windows filesystem.

The 26 explicit designs cover all ten nominal cases, representative family bounds,
both sides of the historical window-height penalty, and equivalent P6/P8 designs.
Generated IDFs are compared by effective fields, ignoring comment encoding and
decimal formatting. Original asset bytes remain hash checked. Semantic output
parsing is checked against the original fixed report selections. Final values are
compared with the actual original C# result, using relative tolerance `2e-12` and
absolute tolerance `1e-9`; field formatting differences use absolute `1e-11`.

## Modern regressions

Run the same explicit designs with the pinned 26.2 executable and compare with
`baselines/26.2.0-synthetic.json` using `--baseline`. The validator never changes
that file. Baseline changes must identify their input/model/weather provenance
and explain material differences. Modern-versus-legacy physics drift is a separate
comparison and is not tested as exact equality.

The initial cross-platform comparison tolerance is relative `1e-8` and absolute
`1e-7` in reported component units. Tabular office energy retains EnergyPlus's
displayed precision. These tolerances must be checked against repeat runs and
the Linux CI results before declaring the regression baseline validated.

## Paper and licensing coverage

Published parameter tables, constants and objective formulas have independent
checks. Complete published input/objective pairs are tested only with reproducible
simulation conditions. Missing numerical coverage is documented in
[the validation ledger](../docs/validation.md), not filled with invented values.

Synthetic test weather is independently generated and labelled. It is never
renamed to impersonate an original EPW. Canonical weather remains externally
provided under its own terms. Public CI uploads numerical reports only, not
weather records, source models, simulator binaries or publication files.
