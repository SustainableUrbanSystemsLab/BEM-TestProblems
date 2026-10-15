# Third-party notices

The root `LICENSE` applies to this project's new, independently authored code.
This distribution also contains material under BSD-3-Clause. The MIT license is
not a replacement for those terms or for the terms of external software/data.

## BEOBenchmark

Source: [Christoph Waibel's BEOBenchmark](https://github.com/christophwaibel/BEOBenchmark),
commit `54736a6b899a488222ad3184f306c1f401daf4f9`.

Copyright (c) 2018, Christoph Waibel. All rights reserved.

The following material is covered by the upstream BSD-3-Clause license:

- The nine unchanged templates in `src/bem_testproblems/data/legacy/`.
- The six unchanged C# files in `reference/legacy-source/`.
- The translated benchmark specifications, parameter mappings and objective
  calculations in `src/bem_testproblems/parameters.py`, `problems.py`, `losses.py`
  and `models.py`.

The complete upstream license, including all three conditions and its warranty
and liability disclaimer, is reproduced verbatim in
`src/bem_testproblems/data/licenses/BEOBenchmark-LICENSE.txt` and
`reference/legacy-source/LICENSE`. Keep it with redistributed source and include
it in documentation/materials accompanying binary distributions. Neither the
copyright holder nor contributors may be used to endorse derived products
without prior written permission.

`assets/manifest.json` records original paths, immutable-source hashes, license
coverage and additional provenance. Generated or transitioned models remain
derivatives of the input models; retain their original comment headers and this
notice, even when a converter changes formatting.

## Model attribution

The simple and detailed office templates for problems 1–6 and 8 retain their
Michael Wetter/LBNL author comments. The simple office files additionally credit
BESTEST Case 930 by R. H. Henninger, GARD Analytics. See Wetter and Wright (2004).

The templates for problems 9 and 10 retain the DOE Commercial Building Benchmark
notices. Those notices require credit to **DOE, NREL, PNNL and LBNL** in resulting
publications and prohibit publicity implying endorsement. Their reference is:
U.S. Department of Energy, Energy Efficiency and Renewable Energy, Office of
Building Technologies (2007), *Commercial Building Benchmarks*. See also Kämpf,
Wetter and Robinson (2010).

The problem 13 school model is attributed by the upstream benchmark to Djuric,
Novakovic, Holst and Mitrovic (2007). It includes an embedded Belgrade design day
and ground temperatures. This provenance is retained; it is not a new claim that
all underlying research-model grants or climate-data rights have been independently
verified. The upstream repository's BSD grant is the recorded basis for including
these benchmark copies. No separate model-specific license file accompanied the
selected upstream templates.

Please cite Waibel et al. (2019) and the applicable originating studies in
`references.bib` when publishing work using these problems.

## External engines, tools and weather

EnergyPlus, transition executables, Rhino/Grasshopper, compiled `.gha` files,
Windows runtimes, and EP-Compare libraries are not bundled. Install or provide
authorized copies separately. EnergyPlus has its own BSD-like agreement with
additional name/version and trademark conditions; retain the **exact release's**
agreement and any applicable dependency notices if redistributing it. Referring
to the simulator as "EnergyPlus version 8.5.0" or "EnergyPlus version 26.2.0"
does not imply endorsement.

No EPW, DDY or STAT weather files are distributed. The manifest identifies the
historical files for reproducibility, not a redistribution grant. ASHRAE IWEC
weather carries its own copyright and references additional license conditions.
An official source making data available to its users does not itself establish
that this project may rehost it. Obtain and use a file under its applicable terms;
keep external weather out of source archives, wheels, CI caches and published
artifacts unless its redistribution rights have been established.

No publication PDFs, screenshots, figures or copied article text are bundled.
Small factual validation records must cite their source and distinguish printed,
rounded values from reconstructed outputs. A future supplementary dataset must
be reviewed under its own license before inclusion.

See `docs/licensing.md` for the asset and release checks. These notices do not
relicense any third-party material under MIT.
