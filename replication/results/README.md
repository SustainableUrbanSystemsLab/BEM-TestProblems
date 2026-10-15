# Reviewed replication results

Generated result packages belong in one subdirectory per experiment. The
[replication workflow](../README.md) creates an allowlisted package after native
winner checks pass. Each package contains its own scope, source manifest IDs,
full-precision designs, plots, replay summary, attribution, and checksum inventory.

No full campaign has been published here yet. Raw checkpoints, machine paths,
licensed simulator inputs, and private literature comparisons stay outside Git.
CI verifies each added package through the
[pipeline](../pipeline.py); a checksum check alone does not establish scientific
correctness.
