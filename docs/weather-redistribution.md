# Redistribution evidence for the historical weather files

The project can retrieve its four frozen US EPWs with
`python tools/fetch_weather.py`. They remain in the ignored `.cache/weather/`
directory. The audit below concerns publishing those exact files on GitHub or
inside a package; local acquisition and distribution have separate evidence.

## Evidence found

The EnergyPlus Team's [2002 LBNL publication](https://simulationresearch.lbl.gov/dirpubs/un_articleEP02.pdf#page=7),
printed page 7, identifies US TMY2 data as public domain. This is affirmative
evidence about the underlying TMY2 dataset. The Seattle, Houston and Chicago
EPWs also contain a design-conditions record attributed to the **2009 ASHRAE
Handbook**. That additional record is outside what the 2002 statement establishes.

NLR's [Weather Data for Buildings Energy Simulations](https://data.nlr.gov/submissions/128)
has a [dataset-specific license](https://data.nlr.gov/node/128/license). It grants
no-fee use/copy of data made available on that server, subject to retaining the
entire notice, DOE/NREL/ALLIANCE publication credit and no endorsement. It also
contains indemnity, disclaimer and other conditions; it is not the project's MIT
or upstream BSD license.

The official NLR San Francisco TMY3 file was checked in three archives from that
dataset: `USA-TMY3-EPW.zip`, `openstudio-eri-tmy3s.zip` and
`openstudio-eri-tmy3s-cache.zip`. Bounded range reads retrieved their ZIP
directories and the selected member rather than the complete datasets. All three
returned the same official member bytes, which differ from the benchmark file:

| File identity | SHA-256 | ASHRAE design record |
| --- | --- | --- |
| Benchmark `USA_CA_San.Francisco.Intl.AP_TMY3.epw` | `4cac90a2374cd850a70a787afc4dd5517e1ac2c9c2ef47388d7c001c870500d7` | 2005 |
| NLR `USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw` | `7d4d35cd413bbac64ddb87150996a7ac3b9fcff4b21a8160925de225467e4def` | 2009 |

Differences include design conditions and hourly illuminance, minute and other
fields. The official file is therefore not an interchangeable, checksum-matched
permission source for the historical benchmark file.

ASHRAE's [primary permissions page](https://www.ashrae.org/permissions/permissions-and-licensing)
offers a license for incorporating its climatic design data into derivative
works. No downstream grant covering the embedded 2005/2009 design records in
these exact four EPWs was identified in this audit. The source-code BSD license,
an available download or a filename containing `TMY2` does not establish that
missing grant.

## Current conclusion

Affirmative evidence exists for the underlying US TMY2 dataset and an explicit
conditional copying grant exists for NLR's served dataset. **Redistribution of
the four exact benchmark EPWs remains unresolved**, specifically because of the
embedded ASHRAE records and the unmatched San Francisco package. This is not a
finding that publishing the files is categorically prohibited.

The current distribution therefore includes the four pinned URLs/checksums and a
working acquisition command, while raw EPWs remain outside Git, wheels, source
archives and published CI artifacts. A distribution decision for the exact files
needs a grant or other established basis that covers the additional records; a
different weather package would also need its own identity and numerical checks.

Belgrade IWEC is excluded from the downloader and this proposed bundle. Problem
13 evaluates an embedded winter design day without an EPW. The official
[EnergyPlus IWEC description](https://energyplus.readthedocs.io/en/stable/auxiliary-programs/auxiliary-programs.html#international-weather-for-energy-calculations-iwec)
describes DOE's specific ASHRAE distribution arrangement; it does not establish
an unrestricted rehosting grant for this repository.
