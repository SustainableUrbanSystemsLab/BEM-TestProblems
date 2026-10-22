# FOAM replication: next-session handoff

Updated **22 October 2026**. Work in `R:\BEM-TestProblems` on
`codex/windows-continuation`.

Read the detailed local note first:
**`.validation-local/SESSION-HANDOFF-20261022.txt`**. Its adjacent JSON records
completion and the process check at handoff. These private notes stay on FOAM.

## Current state

The **model-corrected-v2 campaign is finished**: 2,400 terminal attempts,
2,288 successful, 112 failed, zero remaining. It recorded 1,769,625 evaluations
using 118 workers. The last simulation finished on 22 October at 05:13 Eastern;
the automatic final review finished at 05:15. No EnergyPlus or project background
Python jobs were active at handoff, so logout will not interrupt an experiment.

The user's next requested step is to **look at the completed replication**.
Open the reports and plots before taking further action. There is nothing to
resume after login. Old recovery instructions describe historical running state;
some controller text still says `interrupted`, while `review/run-completion.json`
correctly records `finished-with-failures` and all 2,400 attempts are terminal.

## Results to review

Private root: `.validation-local/foam-six-corrected-v2-20261019/`.

- Final tables and discussion: `review/review-strict.md`.
- Full review data: `review/review-strict.json`.
- Boxplot values and sample counts: `review/plots-strict/boxplot-summary.json`.
- Figures 8 and 9 for each engine: `review/plots-strict/figure8-energyplus-8.5.0.png`,
  `figure9-energyplus-8.5.0.png`, `figure8-energyplus-26.2.0.png` and
  `figure9-energyplus-26.2.0.png`. Matching SVG files exist.
- Raw designs, evaluation traces and errors: `campaign/runs/*.json`.
- Failure details: `diagnostics/failure-details-20261021T201858Z/`.

The final review and plots were generated automatically and their hashes checked.
`replication/results/` is the public export destination; no public campaign package
has been published there. Private results are available without a public export.

## Repairs and scientific limits

The original 112 failed attempts comprise 88 storage errors, 23 warmup failures
and one bounds-adapter error. The bounds adapter was fixed in `5bf4cf1`.
The warmup correction was committed and pushed as **`e965a13`**, an explicit
**`model-corrected-v3`** option. All 23 retained failing designs pass its strict
native checks, but their optimizer trajectories have not been rerun.

Version 3 sets surface convection to 1 W/(m? K) during weather warmup only for
P4/P5/P10, releasing the overrides before measured simulation. It preserves
convergence thresholds and version-2 annual/sizing input fields. All 2,850 native
validation cases pass; sizing records match at 1,442 paired designs. Full pytest:
1,385 passed, 26 skipped. See [the repair evidence](replication-failures.md#weather-warmup-convection-correction-version-3)
and the private `.validation-local/warmup-repair-20261022/REPORT.txt`.

Current assessment: **partial reproduction** of the paper/dissertation. Eight of
ten best objectives from the overlapping solver families are within 0.12% of
rounded dissertation best values. P4 differs by -4.19% and P6 by +1.13%; material
model/numerical departures remain. Boxplot medians, quartiles and tails have not
been established as matching, and excluded failures can bias distributions.
The saved publication comparison is under `review/publication-comparison-20261022/`.
Use EnergyPlus 8.5 for historical comparisons; 26.2 is a separate engine experiment.

## Constraints for future work

- Retain the six selected methods: DIRECT, CRS2, Sbplex, CMA-ES, PDFO BOBYQA,
  Py-BOBYQA; ten continuous problems; both installed engines; at most 118 workers.
- Preserve the existing `.venv`, numerical dependencies, engines, weather,
  frozen sources, starts, seeds, budgets, solver settings, checkpoints and results.
- A version-3 optimizer comparison needs a separate frozen manifest and output
  root. Keep version-2 trajectories and version-3 measurements separate.
- The default `replication/continuation.json` belongs to an older experiment.
  Do not run old recovery/preparation helpers merely to resume this session.
- No administrator access, Windows Task Scheduler or website build. Keep private
  inputs, checkpoints and licensed documents outside Git. No automatic email/chat
  delivery is configured. The completed campaign's reporter has finished.
- Native result folders may require ordinary-user execution outside the tool
  sandbox; this does not require administrator privileges or ACL changes.

Suggested prompt after signing in:

> Read `docs/foam-takeover.md` and `.validation-local/SESSION-HANDOFF-20261022.txt`.
> I want to review the completed replication and boxplots first. Show me the
> results and explain what matches Waibel's paper/dissertation and what remains
> unresolved. Do not automatically restart or launch a campaign.
