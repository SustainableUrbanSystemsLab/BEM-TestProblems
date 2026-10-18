# FOAM campaign: next-chat handoff

Work in `R:\BEM-TestProblems` on `codex/windows-continuation`.
The detailed private handoff is
`.validation-local/foam-six-corrected-20261018/TAKEOVER.md`, alongside
`takeover-state.json`. Read both before taking action.

This is the fresh, six-solver, **model-corrected** campaign, with 118 workers,
ten continuous problems and both EnergyPlus 8.5.0 and 26.2.0. Its numerical
source was frozen from commit `b09d3d41dcba9b30fcb580b53e310c57a3218032`.
Later documentation commits do not change that frozen source.

The goal is to compare boxplots with Waibel et al. (2019). These labelled
model corrections change the benchmark, particularly P4; their boxplots must
not be presented as exact replication of the original numerical results.
See [the correction evidence](replication-failures.md).

## Recover after signing in

Windows sign-out stops this ordinary-user background job. Completed runs and
saved evaluations stay on disk. Interrupted optimizations restart with their
original start, seed and full budget; optimizer internal state is not saved.

The private helper checks live process identities and campaign locks to prevent
duplicate launches. It uses the existing environment and supervisor, validates
the continuation plan, and creates new logs without replacing earlier logs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File R:\BEM-TestProblems\.validation-local\setup\resume-six-corrected.ps1 -Monitor
```

`-CheckOnly` inspects the running campaign or validates the dormant continuation
without launching it. `-Monitor` opens the read-only tqdm progress window.
The helper also starts or reuses the private 12-hour progress reporter.
The launching chat must verify the controller heartbeat and increasing
checkpoint evaluations after restarting. An alive PID with an unverified
identity requires inspection, since Windows can reuse PIDs.

## Twelve-hour reports

The user requested progress, failures and preliminary boxplots every half day.
The ordinary-user reporter saves an initial report, then reports every 12 hours,
and a final report after the pipeline review completes. Its heartbeat and next
deadline are in the campaign's `reports/reporter-status.json`; open
`reports/latest.md` for the latest summary. Timestamped report directories retain
earlier snapshots. Plots use strict finished trajectories and display sample
counts; incomplete distributions can be biased.

Reports are saved locally. No email or automatic chat delivery is configured.
Windows sign-out stops the reporter too; the recovery helper restores its saved
deadline and generates an overdue report after sign-in.

Whenever the user asks for a report, generate a fresh one and summarize it in
chat; do not wait for the next 12-hour deadline:

```powershell
.venv\Scripts\python.exe .validation-local\setup\report-six-corrected.py --once
```

This leaves the periodic deadline unchanged. The user currently plans to stay
signed in, so leave the campaign and reporter running.

## Rules for the next chat

- Use `.validation-local/foam-six-corrected-20261018/pipeline.json` explicitly.
  The default `replication/continuation.json` belongs to an older experiment.
- Keep DIRECT, CRS2, Sbplex, CMA-ES, PDFO BOBYQA and Py-BOBYQA; cap workers at 118.
- Preserve the frozen source, installed numerical environment, inputs, seeds,
  starts, budgets, solver settings, checkpoints and earlier results.
- Use the normal signed-in account. No administrator access or Task Scheduler.
- Keep private files outside Git. Do not run the fresh-campaign preparation
  scripts, reinstall dependencies, launch the stopped ten-solver cohort, or
  build the website.
- After recovery, use the existing `replication/pipeline.py run` workflow;
  its automatic review generates the final tables and boxplots in the private
  campaign's `review/` directory. Inspect failures before making claims.

Suggested prompt for a new chat:

> Read `docs/foam-takeover.md` and its private handoff in this checkout.
> Check whether the corrected six-solver campaign is alive. Resume the same
> campaign if needed using the provided helper, verify checkpoint growth,
> and continue monitoring and reviewing the boxplot experiment with 118 workers.
