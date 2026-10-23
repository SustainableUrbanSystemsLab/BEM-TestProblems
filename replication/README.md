# Run, review, and publish solver experiments

For a new experiment, start with the [experiment guide](../docs/optimization-replication.md).
It explains solver selection, paired starts, evaluation budgets, and boxplots.
A fresh experiment does not require a private handoff.

This directory provides additional workflows for continuing an existing campaign
and running an explicitly extended-budget experiment. Both preserve checkpoints,
record provenance, and produce reports. Use Python 3.12 and the
[local setup](../README.md#set-up-locally); Windows users can follow the
[PowerShell guide](../docs/windows-continuation.md).

## Continue an existing campaign

A continuation requires the original manifest, checkpoints, and frozen numerical
source. Completed results retain their provenance. Only unfinished
specifications enter the continuation; interrupted optimizers restart from their
recorded starts, seeds, and full budgets. Internal optimizer state is not saved.

Copy [continuation.json](continuation.json) to an ignored configuration such as
`.validation-local/my-continuation.json`. Set its paths and worker count before
planning. Paths are relative to the project root unless absolute.

| Configuration entry | Contents |
| --- | --- |
| `paths.origin` | Original manifest and checkpoints |
| `paths.frozen_source` | Source snapshot matching the original numerical hashes |
| `paths.continuation` | New manifest, checkpoints, attempt histories, and controller log |
| `paths.preflight` | Canonical native checks and passing receipt |
| `paths.pilot` | Separate short timing experiment |
| `paths.review` | Tables, best designs, boxplots, and completion record |
| `paths.replay` | Independent native winner checks |
| `paths.publication` | Reviewed public result package |

The supplied 118-worker setting is an example for a large workstation. Choose an
allocation for your hardware, leaving room for other users. Its 48-run pilot has
reduced budgets and contributes no values to full-experiment boxplots.

From the repository root, run these stages separately and inspect each result:

```sh
.venv/bin/python replication/pipeline.py status --config .validation-local/my-continuation.json
.venv/bin/python replication/pipeline.py preflight --config .validation-local/my-continuation.json
.venv/bin/python replication/pipeline.py pilot --config .validation-local/my-continuation.json
.venv/bin/python replication/pipeline.py plan --config .validation-local/my-continuation.json
```

On Windows, use `.venv\Scripts\python.exe` instead of `.venv/bin/python`.

| Stage | What to check |
| --- | --- |
| `status` | All planned runs are accounted for; a controller is not already running |
| `preflight` | Both engines match canonical references and documented rejected outcomes |
| `pilot` | Timing, failures, peak memory, CPU use, and disk activity support the allocation |
| `plan` | Frozen source and input identities match; remaining starts, seeds, and budgets are unchanged |

Then start the campaign:

```sh
.venv/bin/python replication/pipeline.py run --config .validation-local/my-continuation.json
```

The controller lock prevents two coordinators using the same output directory.
The run stage requires the passing preflight receipt and verifies its identities
and report hashes. Changed inputs require a new preflight. Append `--dry-run` to
inspect a stage's commands without launching its processes.

Keep the numerical source, engines, inputs, and environment fixed throughout the
campaign. Resume with the same configuration; completed terminal records remain
preserved, and interrupted attempts retain their histories. For background use,
see [Windows process lifetime](../docs/windows-continuation.md#background-runs).

## Review and export

After the controller exits, `run` automatically generates strict tables and
Figure 8/9-style PNG/SVG boxplots in `paths.review`. It also reports failed or
interrupted campaigns. Refresh a review explicitly with:

```sh
.venv/bin/python replication/pipeline.py review --config .validation-local/my-continuation.json
```

`paths.review/run-completion.json` lists counts, output locations, and artifact
checksums. `completed: true` means every run is terminal and reporting succeeded;
it does not mean all optimizations succeeded. `finished-with-failures` retains
those failures. Failed and non-strict trajectories are excluded from strict
boxplots; partial figures are labelled incomplete.

For a fresh experiment run outside this pipeline, generate equivalent review
outputs directly:

```sh
.venv/bin/python tools/review_replication.py --origin .validation-local/my-experiment --output-dir .validation-local/my-review
```

Before publishing a configured continuation, replay its strict winners and export:

```sh
.venv/bin/python replication/pipeline.py replay-plan --config .validation-local/my-continuation.json
.venv/bin/python replication/pipeline.py replay --config .validation-local/my-continuation.json
.venv/bin/python replication/pipeline.py export --config .validation-local/my-continuation.json
.venv/bin/python replication/pipeline.py check-export
```

Export requires a complete campaign and passing native replays of the current
strict winners. It includes computed results, designs, figures, sanitized
provenance, attribution, and checksums. Raw checkpoints, machine paths, native
outputs, original models, weather, engines, and literature transcriptions are
excluded. See [public results](results/README.md).

Replay and export preserve existing output directories. Choose a new replay or
publication path for a new attempt. `export-preview` instead writes an explicitly
unvalidated private preview; it cannot pass the public export checks.

## Extended-budget experiment

[extended_budget.py](extended_budget.py) provides a fresh experiment without a
handoff. Copy [extended-budget.json](extended-budget.json) to a private
configuration and choose its workers, solvers, and result paths before planning.
The supplied configuration uses PDFO BOBYQA, all ten problems, both engines,
20 repetitions, and 100 times the paper's evaluation allowance.

| Problems | Paper-budget calls | Extended maximum calls per run |
| --- | ---: | ---: |
| 1, 2, 3 | 500 | 50,000 |
| 4, 5, 6, 9, 10 | 1,400 | 140,000 |
| 8 | 1,200 | 120,000 |
| 13 | 1,100 | 110,000 |

The default experiment has 400 searches and at most 43.2 million objective calls.
Solvers can stop earlier; the increased cap does not force extra evaluations.
This is a different protocol from the publication comparison.

```sh
.venv/bin/python replication/extended_budget.py plan --config .validation-local/my-extended.json
.venv/bin/python replication/extended_budget.py preflight --config .validation-local/my-extended.json
.venv/bin/python replication/extended_budget.py pilot --config .validation-local/my-extended.json
.venv/bin/python replication/extended_budget.py run --config .validation-local/my-extended.json
```

The plan freezes the source and experiment identity. Run requires passing
preflight and completed pilot evidence. The default pilot contains 48 short
searches, separate from full results. Use the same configuration for `status`,
`review`, `replay-plan`, `replay`, and `export`; `check-export` verifies published
packages. Changed settings after planning require a new experiment directory.
