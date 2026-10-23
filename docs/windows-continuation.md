# Windows setup and long experiments

Use PowerShell from the repository root. Python 3.12 is the tested environment
for the optional solvers. Keep the checkout on a disk with enough space for
retained simulation diagnostics and checkpoints.

## Install locally

```powershell
py -3.12 -m venv .venv
$python = (Resolve-Path .venv\Scripts\python.exe).Path
& $python -m pip install -c dependencies-py312.txt -e '.[optimize]'
& $python tools\install_energyplus.py
& $python tools\fetch_weather.py
```

These commands install EnergyPlus 26.2 and canonical weather below the project.
They do not change the system PATH. Start the Python console with `& $python`,
then paste the [complete SciPy example](../README.md#solve-with-scipy).

For historical comparisons, EnergyPlus 8.5 needs the Visual C++ 2013 x64 runtime.
Confirm that prerequisite is installed, then run:

```powershell
& $python tools\install_reference_engine.py
& $python tools\fetch_reference.py
```

A .NET SDK is needed only for the separate [original-C# checks](../reference/README.md).
See [engine versions](engine-versions.md) for custom executable and input paths.

## Test a small experiment

Install the experiment dependencies into the same environment before starting
any campaign:

```powershell
& $python -m pip install -c dependencies-py312.txt -e '.[dev,replication]'
& $python tools\fetch_reference.py
& $python -m pytest -q -m 'not integration'
& $python tools\run_replication.py --problems 13 --versions 26.2.0 --solvers bobyqa --workers 2 --repetitions 2 --budget 25 --output-root .validation-local\windows-smoke
```

This short P13 run is a pilot, not the publication experiment. For DIRECT, CRS2,
and Sbplex, also install `.[replication-nlopt]` using the same dependency file.
Follow the [experiment protocol](optimization-replication.md) for full budgets,
paired starts, worker selection, and plots. A new experiment needs no handoff.

## Transfer an existing campaign

Continuing another machine's campaign requires its original manifest,
checkpoints, and matching frozen numerical source. Copy a prepared archive and
its verification record into the ignored `.validation-local\transfer` directory.
Verify and extract into a new destination:

```powershell
$project = (Get-Location).Path
$transfer = Join-Path $project '.validation-local\transfer'
$archive = Join-Path $transfer 'benchmark-continuation.tar.gz'
$record = Get-Content -LiteralPath (Join-Path $transfer 'transfer-verification.json') -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $record.archive_sha256) {
    throw 'Archive checksum mismatch.'
}
$bundle = Join-Path $project '.validation-local\handoff'
if (Test-Path -LiteralPath $bundle) { throw 'Choose a new handoff directory.' }
New-Item -ItemType Directory -Path $bundle | Out-Null
tar -xzf $archive -C $bundle
if ($LASTEXITCODE -ne 0) { throw 'Archive extraction failed.' }
```

The continuation tool verifies origin records and numerical source hashes before
planning. Follow the [replication workflow](../replication/README.md) to configure
paths, run canonical preflight, measure a separate pilot, and inspect the plan.
Keep completed records and interrupted-attempt histories.

Use a permanent project path throughout planning and execution. For network
storage, use a UNC path for background jobs; mapped drive letters may be
unavailable. Changing the path after planning can invalidate the recorded identity.

## Background runs

An ordinary user process can run independently of the terminal. For an already
prepared continuation that has passed preflight and pilot checks:

```powershell
$project = (Get-Location).Path
$python = (Resolve-Path .venv\Scripts\python.exe).Path
$launch = Join-Path $project ('.validation-local\launch-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $launch | Out-Null
$process = Start-Process -FilePath $python -ArgumentList @(
    '-u', 'replication\pipeline.py', 'run',
    '--config', '.validation-local\my-continuation.json'
) -WorkingDirectory $project -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput (Join-Path $launch 'stdout.log') `
  -RedirectStandardError (Join-Path $launch 'stderr.log')
$process.Id
```

This detaches the controller from the terminal; it does not guarantee survival
of Windows sign-out or reboot. If a campaign must survive those events, use your
organization's supported batch service. No administrator rights or Task Scheduler
are required for the example above.

The controller lock prevents duplicate coordinators in the same output directory.
Read status and refresh reports through the configured
[workflow commands](../replication/README.md#review-and-export). After interruption,
restart the same configuration: finished records remain, and interrupted searches
restart from their recorded starts, seeds, and full budgets.

Keep the numerical source, environment, engines, and weather fixed until the
campaign finishes. Use separate source and result directories for a changed
experiment.
