# Third-party notices

The root `LICENSE` applies to this project's new, independently authored code.
This distribution also contains material under BSD-3-Clause. The MIT license is
not a replacement for those terms or for the terms of external software/data.

## BEOBenchmark

Source: [Christoph Waibel's BEOBenchmark](https://github.com/christophwaibel/BEOBenchmark),
commit `54736a6b899a488222ad3184f306c1f401daf4f9`.

Copyright (c) 2018, Christoph Waibel. All rights reserved.

The following material is covered by the upstream BSD-3-Clause license:

- The pinned reference index in `src/bem_testproblems/data/reference-assets.json`.
- The derived models, bindings and provenance records in
  `src/bem_testproblems/data/modern/`.
- The translated benchmark specifications, parameter mappings and objective
  calculations in `src/bem_testproblems/parameters.py`, `problems.py`, `losses.py`
  and `models.py`.

The complete upstream license, including all three conditions and its warranty
and liability disclaimer, is reproduced verbatim in
`src/bem_testproblems/data/licenses/BEOBenchmark-LICENSE.txt` and
`reference/licenses/BEOBenchmark-LICENSE.txt`. Keep it with redistributed source and include
it in documentation/materials accompanying binary distributions. Neither the
copyright holder nor contributors may be used to endorse derived products
without prior written permission.

`assets/manifest.json` records original paths, immutable-source hashes, license
coverage and additional provenance. Generated or transitioned models remain
derivatives of the input models. Their original attribution and full DOE notice
are retained in `src/bem_testproblems/data/licenses/BEOBenchmark-MODEL-NOTICES.txt`,
which accompanies the commentless epJSON and full BSD text.

The nine original IDF templates and six original C# files are **not distributed**
in this repository or its packages. Optional reference checks retrieve checksum-
verified originals from the pinned fork into the ignored
`.reference-cache/beobenchmark/` directory. The fetched material remains under
the upstream terms; fetching does not change the license of the derived Python
modules or modern models.

## Model attribution

The derived simple and detailed office models for problems 1–6 and 8 retain their
Michael Wetter/LBNL attribution in the packaged model-notices file. The simple
models additionally credit BESTEST Case 930 by R. H. Henninger, GARD Analytics.
See Wetter and Wright (2004).

The complete DOE Commercial Building Benchmark notice for problems 9 and 10 is
reproduced verbatim in the packaged model-notices file. That notice requires credit to **DOE, NREL, PNNL and LBNL** in resulting
publications and prohibit publicity implying endorsement. Their reference is:
U.S. Department of Energy, Energy Efficiency and Renewable Energy, Office of
Building Technologies (2007), *Commercial Building Benchmarks*. See also Kämpf,
Wetter and Robinson (2010).

The problem 13 school model is attributed by the upstream benchmark to Djuric,
Novakovic, Holst and Mitrovic (2007). It includes an embedded Belgrade design day
and ground temperatures. This provenance is retained; it is not a new claim that
all underlying research-model grants or climate-data rights have been independently
verified. The upstream repository's BSD grant is the recorded basis for including
the derived benchmark models. No separate model-specific license file accompanied
the selected upstream templates.

Please cite Waibel, Wortmann, Evins and Carmeliet (2019) and the applicable
originating studies in
`references.bib` when publishing work using these problems.

## External engines, tools and weather

EnergyPlus, transition executables, Rhino/Grasshopper, compiled `.gha` files,
Windows runtimes, and EP-Compare libraries are not bundled. Install or provide
authorized copies separately. EnergyPlus has its own BSD-like agreement with
additional name/version and trademark conditions; retain the **exact release's**
agreement and any applicable dependency notices if redistributing it. Referring
to the simulator as "EnergyPlus version 8.5.0" or "EnergyPlus version 26.2.0"
does not imply endorsement.

No EPW, DDY or STAT weather files are distributed. `tools/fetch_weather.py`
retrieves the four historical US EPWs from the checksum-pinned fork into the
ignored `.cache/weather/` directory for local evaluation. The packaged weather
index records source identifiers and hashes; it is not a weather license or
redistribution grant. Raw weather stays out of Git, source archives, wheels and
published CI artifacts/caches. Canonical CI uses temporary checksum-verified
downloads; supplemental CI also uses independently generated weather.
Problem 13 needs no EPW because its winter design day is embedded in the model;
the downloader does not retrieve the separately licensed Belgrade IWEC package.
ASHRAE IWEC carries its own copyright and references additional license conditions.

The exact EnergyPlus version 8.5.0 release agreement is reproduced at
`reference/licenses/EnergyPlus-8.5-LICENSE.txt` to accompany the CI reference-engine
acquisition. No engine or runtime binaries are included in this repository.

`tools/synthetic_weather.py` independently generates new MIT-licensed analytic
weather fixtures labeled **SYNTHETIC-CI**. No historical weather records are read
or copied. These fixtures test same-input executable parity and modern-model
execution; they are not canonical benchmark or paper-reference weather. Generated
filenames have a `synthetic_` prefix and do not replace original weather metadata.

No publication PDFs, screenshots, figures or copied article text are bundled.
Small factual validation records must cite their source and distinguish printed,
rounded values from reconstructed outputs. A future supplementary dataset must
be reviewed under its own license before inclusion.

## Optional optimization experiment libraries

The new experiment adapters contain independently authored orchestration, with
no solver implementation source bundled. Optional dependencies are downloaded
separately into a local virtual environment and retain their own terms:

- [NLopt](https://nlopt.readthedocs.io/en/latest/NLopt_License_and_Copyright/):
  LGPL and algorithm-specific notices; retain the applicable build's complete notices.
- [pycma](https://github.com/CMA-ES/pycma/blob/development/LICENSE) and
  [PDFO](https://github.com/pdfo/pdfo/blob/main/LICENCE.txt): BSD-3-Clause.
- [Py-BOBYQA](https://github.com/numericalalgorithmsgroup/pybobyqa/blob/master/LICENSE.txt):
  GPL-3.0; its package is an optional external dependency and is not relicensed
  by this project's MIT/BSD notices.

No BB-O/FrOG/MetaheuristicsLibrary implementation is translated or bundled in the
experiment adapters. In particular, an MIT license on a repository stub does not
replace the GPL terms of the separately linked implementation.

The optional native transports in `tools/paper2019/` call separately supplied
FrOG/MetaheuristicsLibrary and Galapagos binaries. The recovered FrOG solver
wrappers declare GPL-3.0-or-later. Grasshopper/Galapagos retain McNeel's terms;
the user supplies an authorized archive. These binaries are not redistributed
or relicensed by this project. The transport sources implement no search
operators and include no copied third-party implementation source.

See `docs/licensing.md` for the asset and release checks. These notices do not
relicense any third-party material under MIT.
