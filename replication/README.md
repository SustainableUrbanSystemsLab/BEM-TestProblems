# Replication workflow

This folder is the entry point for continuing, reviewing, and publishing the
continuous-problem experiment. Run the long stages on the Windows workstation.
The code comes from GitHub; the preserved checkpoints come from the private
handoff. They are kept separate so that pulling code never overwrites results.

Start with the [Windows setup](../docs/windows-continuation.md), through extracting
the verified handoff. Use the local Python environment throughout. The commands
below assume its `$python` variable and `Invoke-Checked` helper are available.

## One configuration

[continuation.json](continuation.json) defines project-relative folders, the
worker allocation, and the small timing pilot. Edit it before launching if the
workstation needs a different allocation. Full-campaign starts, seeds, budgets, models, engine
versions, and solver choices come from the original manifest, rather than being
copied into another configuration.

| Location | Contents | GitHub |
|---|---|---|
| `.validation-local/handoff/` | Immutable origin checkpoints and frozen numerical source | Private |
| `.validation-local/windows-continuation/` | New Windows manifest, checkpoints, attempt histories, and controller log | Private |
| `.validation-local/windows-checks/` | Native preflight reports and receipt | Private |
| `.validation-local/replication-review/` | Combined tables and boxplots | Private |
| `.validation-local/replication-replay/` | Native winner replays and retained diagnostics | Private |
| `.validation-local/publication-preview/` | Explicitly unvalidated export preview | Private |
| [results/](results/README.md) | Reviewed, allowlisted result packages | Public |

The original and Windows records retain their actual manifest IDs and platforms.
Review joins them by the validated continuation relationship. It never creates
replacement checkpoints with invented provenance.

## Check, measure, and launch

```powershell
Invoke-Checked { & $python replication\pipeline.py status }
Invoke-Checked { & $python replication\pipeline.py preflight }
Invoke-Checked { & $python replication\pipeline.py pilot }
Invoke-Checked { & $python replication\pipeline.py plan }
```

- **Status** reads checkpoints without starting simulations.
- **Preflight** runs both installed engines on the canonical validation cases.
  It requires objective/component agreement at relative tolerance `1e-6`, with
  absolute tolerance `1e-7` near zero, and the documented rejected outcomes.
- **Pilot** runs the separate 48-run timing experiment. Inspect its timings,
  failures, memory use, and CPU use before choosing the full worker count.
  Its reduced budgets do not enter the full experiment's results.
- **Plan** checks frozen source, inputs, provenance, completed records, and the
  exact remaining run specifications without optimizing anything.

Append `--dry-run` to any stage to inspect its commands without launching a
process. The pipeline invokes numerical stages in fresh interpreters so that
the current analysis package cannot contaminate the frozen numerical source.

For the persistent job, use the [Task Scheduler settings](../docs/windows-continuation.md#6-run-independently-of-the-remote-desktop-window).
Set its program to the full path of the environment's Python executable, its
working directory to the checkout, and its arguments to the absolute path of
[pipeline.py](pipeline.py) followed by `run`. For the example checkout:

```text
"D:\benchmarks\BEM-TestProblems\replication\pipeline.py" run
```

The run stage checks the passing preflight receipt against the current
destination manifest and report hashes before starting. Changed inputs require
another preflight. Each preflight gets a fresh numbered attempt directory;
failed and earlier attempts remain available. With 120 workers, the controller
uses two 60-worker pools.
Rerun the same scheduled task after an interruption: finished destination runs
are skipped, and interrupted attempts restart from their original seed, start,
and full budget. Previous attempt histories remain available.

Keep the checkout, frozen source, engines, weather, and environment fixed during
the campaign. Pull updates before setup or after stopping the scheduled task,
never during a live campaign. Changes that alter its identity require a new
recorded experiment.

## Review simulations and solutions

```powershell
Invoke-Checked { & $python replication\pipeline.py status }
Invoke-Checked { & $python replication\pipeline.py review }
```

The status command accounts for every originally planned run. The review stage
writes Markdown tables, full-precision JSON, and Figure 8/9-style PNG/SVG plots.
The command prints the generated locations. Refresh it while the campaign runs;
partial reports stay labelled incomplete.

Review these items before drawing conclusions:

- Completed, failed, interrupted, and missing counts, with the full planned
  repetition denominators.
- Excluded non-strict searches. A valid final point does not make a search strict
  if it used warmup-error outputs earlier.
- Each solver's best full design vector and the best across methods, with
  parameter names, units, seeds, calls, and actual source manifest IDs.
- Objective differences and percentages between engines. Their winning designs
  can differ, so this comparison alone does not isolate the engine change.
- Retained failed-simulation diagnostics and their checkpoint error records.
  **Severe** indicates a serious simulation problem; **Fatal** terminates the
  simulation. Both reject ordinary benchmark evaluations.

For a separate compatibility view, use
[review_replication.py](../tools/review_replication.py) with
`--include-diagnostic-runs`; its output is explicitly labelled diagnostic.
The [diagnostic policy](../docs/optimization-replication.md#diagnostics-and-figures)
explains the distinction. Private dissertation comparisons and the ten-design
C# check retain their own instructions in the handoff; they are not public data.

## Replay and export

```powershell
Invoke-Checked { & $python replication\pipeline.py replay-plan }
Invoke-Checked { & $python replication\pipeline.py replay }
Invoke-Checked { & $python replication\pipeline.py export }
Invoke-Checked { & $python replication\pipeline.py check-export }
```

Replay checks the full-precision strict winner for each problem/engine using the
frozen numerical source and recorded engine/input identities. It retains native
diagnostics and compares objectives and components with the recorded incumbent.
Run this stage on the workstation after the campaign finishes.

Export requires a complete campaign and passing replays of the current strict
winners. It creates a fresh public package containing our computed results,
figures, sanitized provenance, replay comparisons, attribution, and checksums.
Raw checkpoints, local machine paths, native outputs, original models, weather,
engines, and thesis transcriptions are excluded.

For an early inspection only, `export-preview` writes to the private preview
folder and labels its contents **UNVALIDATED PARTIAL PREVIEW**. It bypasses the
completion/replay gates and cannot pass the public-package check.

Replay and export preserve existing output directories. After a failed replay,
inspect its diagnostics, correct the cause, and give `paths.replay` a new suffix
in [continuation.json](continuation.json) before retrying. For another preview or
export, similarly choose a fresh `paths.preview` or `paths.publication` directory.
Keep the earlier attempts. The review stage supports refreshing its own reports.

## Review and push a results branch

After the scheduled task has stopped, inspect the exported figures, vectors,
diagnostics summary, scope, and included files. Then create a dedicated branch:

For the first commit on this workstation, set your identity for this repository
using your actual name and GitHub-associated email, or GitHub's supplied
`noreply` address:

```powershell
Invoke-Checked { git config user.name 'Your name' }
Invoke-Checked { git config user.email 'Your commit email' }
```

These settings are local to the checkout; see
[GitHub's identity guidance](https://docs.github.com/en/get-started/git-basics/setting-your-username-in-git).
Git for Windows includes Git Credential Manager. Its browser sign-in handles
HTTPS push authentication; use your own account with repository write access.
See [GitHub's authentication guidance](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git).
Enter credentials only in that sign-in flow.

```powershell
Invoke-Checked { git switch -c codex/replication-results }
Invoke-Checked { & $python replication\pipeline.py check-export }
Invoke-Checked { git add -- replication/results/continuous-rerun }
Invoke-Checked { git diff --cached --stat }
Invoke-Checked { git diff --cached --check }
Invoke-Checked { git diff --cached }
```

Adjust the result directory to match [continuation.json](continuation.json).
Stage only that exported package. After inspecting the staged change:

```powershell
Invoke-Checked { git commit -m 'Add reviewed continuous-problem replication results' }
Invoke-Checked { git push -u origin codex/replication-results }
```

Open a pull request against the development branch and review CI before merging.
[CI](../.github/workflows/validate.yml) verifies public-package inventories and
recorded completion/replay gates on all three test platforms. Those checks
establish package integrity; native replay evidence and the numerical review
remain necessary for scientific conclusions. No full experiment runs in CI.

For a new experiment rather than this continuation, use the
[experiment protocol](../docs/optimization-replication.md#local-setup-and-execution)
with a new output directory. The review tool also accepts a single fresh
experiment as its origin.
