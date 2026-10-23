# Validation data

These JSON files contain project measurements and provenance. They are reference
checks for explicit designs, not the paper's original raw optimization results.
The [validation guide](../validation.md) explains what each comparison establishes.

| File | Contents |
| --- | --- |
| [8.5.0-canonical-audit.json](8.5.0-canonical-audit.json) | Historical-engine measurements for the original 26 canonical-weather designs |
| [26.2.0-canonical-audit.json](26.2.0-canonical-audit.json) | Modern-engine measurements for the same designs |
| [warmup-diagnostics.json](warmup-diagnostics.json) | Failed warmup criteria, full vectors, hashes, and diagnostic probes, including the additional P1 trial |
| [problem-13-weather-invariance.json](problem-13-weather-invariance.json) | Checks that P13 uses its embedded winter design day |
| [p1-bobyqa-smoke.json](p1-bobyqa-smoke.json) | A small solver-integration check, separate from the publication protocol |
| [original-csharp-ci.json](original-csharp-ci.json) | Recorded original-C# comparison jobs and their actual tolerances |
| [model-corrected-v3-audit.json](model-corrected-v3-audit.json) | Aggregate validation of the labelled warmup correction |
| [historical-hvac-audit.json](historical-hvac-audit.json) | Matched P6/P8 designs comparing historical, modern, and compatibility models |

The additional [native regression baselines](../../reference/baselines) and
[failure fixtures](../../reference/replication-failure-cases.json) retain numeric
expectations used by CI. Raw external models, weather, and publication files are
not distributed here.
