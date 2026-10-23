# Reviewed replication results

This directory holds one public result package per experiment. No full campaign
has been published here yet.

Raw campaign data are written to the experiment's chosen output directory,
usually under `.validation-local/`. For the configurable pipeline, `paths.review`
contains the generated tables and PNG/SVG boxplots; `run-completion.json` lists
their locations and checksums. These local reports are available before public
export. See the [workflow](../README.md#review-and-export) to generate or refresh
them.

A public package contains computed results, full-precision best designs,
experiment scope, plots, sanitized provenance, replay comparisons, attribution,
and checksums. Export requires a complete campaign and passing native winner
replays. Raw checkpoints, machine paths, licensed simulator inputs, and private
literature comparisons remain outside Git.

CI verifies each package through [pipeline.py](../pipeline.py). Package integrity
does not by itself establish agreement with the publication; see the
[validation evidence](../../docs/validation.md).
