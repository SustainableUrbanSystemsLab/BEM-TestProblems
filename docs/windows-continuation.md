# Continue an experiment on Windows

This guide moves unfinished runs to a Windows x64 workstation. Completed results
keep their original provenance. The continuation gets its own manifest because
its operating system, executable hashes, native libraries, and paths differ.
It preserves the remaining starts, seeds, solvers, and evaluation budgets.

## 1. Create a local checkout and environment

Use a local disk with room for simulation outputs, outside a live sync folder.
Connect through your institution's documented remote-access service with your
own account. The commands below run **on the Windows workstation**, in PowerShell.
Install [Git for Windows](https://git-scm.com/install/windows) and 64-bit
Python 3.12 through the [official Python installation guidance](https://docs.python.org/3/using/windows.html)
if they are missing. The commands assume `git` and `py -3.12` are available.

```powershell
$ErrorActionPreference = 'Stop'
function Invoke-Checked([scriptblock] $Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE." }
}
$project = 'D:\benchmarks\BEM-TestProblems'
Invoke-Checked { git clone --branch codex/windows-continuation --single-branch https://github.com/SustainableUrbanSystemsLab/BEM-TestProblems.git $project }
Set-Location $project
Invoke-Checked { py -3.12 -m venv .venv }
$python = Join-Path $project '.venv\Scripts\python.exe'
$env:PIP_CACHE_DIR = Join-Path $project '.cache\pip'
Invoke-Checked { & $python -m pip install -c constraints\replication-py312.txt -e '.[dev,replication,replication-nlopt]' }
```

The small helper stops setup when a native command fails; PowerShell otherwise
allows later commands to continue. Using the environment's executable directly
avoids activation and changes to PowerShell's execution policy. The numerical constraints are in
[replication-py312.txt](../constraints/replication-py312.txt).

## 2. Install both engines and fetch the inputs

EnergyPlus 8.5 needs the separate **Visual C++ 2013 x64 runtime**. Check the
[official Microsoft download guidance](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170)
if the historical installer reports missing runtime DLLs. A newer Visual C++
runtime does not replace the 2013 runtime. Follow any reboot request from its
installer; this project does not redistribute Microsoft DLLs.

```powershell
Invoke-Checked { & $python tools\fetch_reference.py }
Invoke-Checked { & $python tools\install_reference_engine.py }
Invoke-Checked { & $python tools\install_energyplus.py --platform windows-x86_64 }
Invoke-Checked { & $python tools\fetch_weather.py }
$env:BEM_REFERENCE_DIR = Join-Path $project '.reference-cache\beobenchmark'
```

The installers verify pinned downloads and keep the engines under the project.
The original models and four canonical weather files stay in local caches.
Rhino and a .NET SDK are unnecessary for the Python campaign. A .NET SDK is
needed only for the separate [unchanged-C# checks](../reference/README.md).

## 3. Copy and verify the private handoff

Copy the prepared continuation archive and its checksum verification record to
the project's ignored `.validation-local\transfer` folder through your approved
file-transfer method. Keep them private.
The archive contains the frozen numerical source, original manifest/checkpoints,
and interruption records. It excludes raw weather, original IDFs, papers,
engine binaries, and the Python environment.

```powershell
$transfer = Join-Path $project '.validation-local\transfer'
$archive = Join-Path $transfer 'benchmark-continuation.tar.gz'
$verification = Get-Content (Join-Path $transfer 'transfer-verification.json') -Raw | ConvertFrom-Json
if ((Get-FileHash $archive -Algorithm SHA256).Hash -ne $verification.archive_sha256) {
    throw 'The transferred archive checksum does not match.'
}
$bundle = Join-Path $project '.validation-local\handoff'
if (Test-Path $bundle) { throw 'Choose a new handoff directory; do not merge old files.' }
New-Item -ItemType Directory $bundle | Out-Null
Invoke-Checked { tar -xzf $archive -C $bundle }
```

Extract into a new directory. The inventory inside the archive identifies every
member by size and SHA-256. The continuation tool also verifies the origin
records and frozen numerical source before preparing the destination manifest.
Do not copy an old experiment lock into the destination output directory.

## 4. Check the installation before the long run

```powershell
Invoke-Checked { & $python -m pytest -q -m 'not integration' }
Invoke-Checked { & $python replication\pipeline.py preflight }
Invoke-Checked { & $python replication\pipeline.py pilot }
```

Preflight compares objective/components with both installed engines at relative
tolerance `1e-6`, with an absolute fallback of `1e-7`, and checks known rejected
outcomes separately. It writes a passing receipt tied to the destination
manifest. Inspect the reports before launching; a passing check does not mean
every design converged. See the [validation record](validation.md).

The separate pilot has 48 short runs over four representative problems, six
solvers, and both engines, with 25 calls per run. Inspect timings, CPU use,
memory, and disk activity before selecting the full worker count. Its values
do not enter the full-budget comparison. The settings and folder layout are in
[continuation.json](../replication/continuation.json).

The private handoff may also contain a ten-design literature fixture. Its
separate instructions run the original C# caller at the rounded dissertation
designs. Keep those inputs and results outside version control.

## 5. Prepare the continuation

Use the [pipeline](../replication/pipeline.py), which invokes the tested
[continuation tool](../tools/continue_replication.py) in a fresh interpreter:

```powershell
Invoke-Checked { & $python replication\pipeline.py plan }
```

Planning does not start optimization. Review the parent manifest ID, completed
and remaining counts, destination identities, and worker allocation. Only
unfinished origin runs enter the continuation. Interrupted optimizers restart
from their original starts and full budgets; their saved histories remain
available. The optimizer's internal state is not serialized.

The original laptop campaign stopped with 358 finished runs and 2,042 remaining
runs, including eight interrupted attempts. Those are handoff counts, not a
claim that the full experiment has completed.

## 6. Run independently of the remote desktop window

Use Windows **Task Scheduler → Create Task** for the long campaign:

- Run under your own account and select **Run whether user is logged on or not**.
  Enter any requested credentials in Windows, never in a script or repository.
- Program: the full path to the project's `.venv\Scripts\python.exe`.
- Start in: the project directory.
- Arguments: the continuation command below, with full paths.
- Disable **Stop the task if it runs longer than**. Task Scheduler otherwise
  [defaults to a three-day limit](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-executiontimelimit).
- Select **Do not start a new instance** if the task is already running.
- A short retry after an unexpected process failure can replay unfinished runs.
  The controller lock prevents duplicate coordinators in the same output folder.

The equivalent command for a first supervised launch is:

```powershell
Invoke-Checked { & $python replication\pipeline.py run }
```

The run stage verifies the current preflight receipt before starting. Append
`--dry-run` to inspect any stage's command without launching a process.

Use literal absolute paths in the scheduled task; PowerShell variables from this
terminal are not available there. For the example directory above, the Action
fields are:

**Program/script**

```text
D:\benchmarks\BEM-TestProblems\.venv\Scripts\python.exe
```

**Add arguments** (one line)

```text
"D:\benchmarks\BEM-TestProblems\replication\pipeline.py" run
```

**Start in**

```text
D:\benchmarks\BEM-TestProblems
```

Task Scheduler's
[account and logon rules](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks)
still apply. Once the scheduled task is running, disconnecting RDP or closing
the laptop does not end the task.

After the 48-worker pilot, use the measured load to select the final worker
count. The configuration uses 120 workers for a dedicated 120-core workstation;
choose less in [continuation.json](../replication/continuation.json) if memory or
disk throughput is limiting. The continuation tool
divides work among separate process pools because
[Python 3.12 limits each Windows pool to 61 workers](https://docs.python.org/3.12/library/concurrent.futures.html#concurrent.futures.ProcessPoolExecutor).
The worker count is the total across pools. Numerical-library threads are
limited to one per worker to avoid nested parallelism. Change the worker count
only between coordinator launches; the recorded numerical experiment stays
identified separately from its resource allocation.

Record the workstation's Windows version and processor counts:

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
```

On Windows 11 and Windows Server 2022 or newer, default processor affinity spans
processor groups. Older releases have different defaults; check actual CPU use
before assuming all cores are available. See Microsoft's
[processor-group documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/processor-groups).

Keep the workstation awake and leave its local input files available. Estimate
completion from its measured throughput; laptop timings do not establish the
workstation's runtime.

## 7. Monitor, review, and publish

```powershell
Invoke-Checked { & $python replication\pipeline.py status }
Invoke-Checked { & $python replication\pipeline.py review }
```

These commands combine the preserved laptop records with the Windows
continuation, retaining every run's actual manifest and the complete planned
repetition counts. The generated tables include every design coordinate, each
solver's best result, and the best across methods. Partial plots remain labelled
incomplete; non-strict trajectories are excluded from strict comparisons.

- Restart the same scheduled task to resume; interrupted attempts restart from
  their original seed, start, and full budget. Completed records are retained.
- Keep the checkout, frozen source, installed dependencies, engines, and inputs
  fixed while running. Do not pull software updates during a live campaign.
- Follow the [replication workflow](../replication/README.md) for native winner
  replays, safe exports, staged-file review, and pushing a separate results
  branch to GitHub. The export gates require completion and passing replays.
- Keep the origin and continuation directories together when copying results
  back. Raw simulation files and private literature comparisons remain private.
- Website work still requires separate approval.
