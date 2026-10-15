# Licensing and provenance

The repository contains new MIT-licensed orchestration and BSD-3-Clause benchmark
material. Preserve both grants and their respective file coverage. The root MIT
license does not apply automatically to imported templates, translated legacy
logic, external engines, weather or publications.

## Included material

`assets/manifest.json` is the inventory of selected upstream originals and external
reproducibility dependencies. Every included original has its upstream path,
commit, source URL, SHA-256, license and relevant notices recorded. Hashes describe
the original bytes, including CRLF line endings and source headers.

| Material | Coverage and obligations |
| --- | --- |
| New orchestration, CLI, optimizer integration and independently written tests | Root MIT license. Preserve its copyright and permission notice. |
| `parameters.py`, `problems.py`, `losses.py`, `models.py` | BSD-derived benchmark translation/specification. Preserve Christoph Waibel's 2018 copyright, the full BSD conditions/disclaimer and the upstream attribution. |
| `data/legacy/*.idf` | Unchanged copies from the pinned BSD-licensed upstream repository. Preserve all original model comments and additional notices. |
| `reference/legacy-source/*.cs` | Unchanged reference material under BSD-3-Clause, with adjacent full `LICENSE`. |
| Generated/transitioned benchmark IDFs | Derivatives of the corresponding templates. Keep original notices and record the source hash and conversion version/steps. They are not independently MIT-licensed assets. |
| Original numerical fixtures created by this project | Record exactly how they were calculated, including input/model/weather hashes and engine build. Do not relabel published values or external datasets as independently generated. |

The selected templates came with the upstream root BSD license, but no separate
model-specific grant documents. Their original research provenance and the limits
of this evidence are recorded in the manifest and third-party notices. In
particular, preserve the DOE publication-credit/no-endorsement notices in problems
9 and 10. Unresolved provenance must remain visible rather than being described as
independently cleared.

BSD-3-Clause permits modification and redistribution subject to notice retention
and the no-endorsement condition. Source distributions must retain the original
notice, conditions and disclaimer. Binary distributions must reproduce them in
accompanying documentation or materials. The full original text is packaged at
`src/bem_testproblems/data/licenses/BEOBenchmark-LICENSE.txt`.

## External material

The project does not bundle weather, EnergyPlus or transition binaries, their
runtime dependencies, Rhino/Grasshopper components, publication files or figures.

Use external engines and data only under their applicable terms. A local path or
an upstream download URL is an identifier, not proof of redistribution permission.
Private development does not trigger BSD redistribution requirements; external
software/data use conditions still apply. CI is also a use of those assets, and
publishing a CI cache or artifact is an additional distribution to assess.

EnergyPlus version 8.5.0 and version 26.2.0 have release-specific BSD-like license
agreements, including an additional condition on the EnergyPlus name/version and
trademarks. These are not the ordinary three-clause BSD text. If an engine,
transition tool, IDD or dependency is redistributed in the future, inventory that
exact artifact and preserve all applicable license/notice files supplied with it,
including notices under bundled Python packages. The external entries in the
manifest identify the audited releases; they do not grant additional rights.

The historical US EPWs are identified as TMY2/TMY3 sources. The Belgrade EPW
identifies ASHRAE IWEC copyright and additional conditions. Neither the fork's BSD
license nor this repository's MIT license establishes weather redistribution
rights. Keep weather externally supplied until its exact package terms support
the intended use/distribution. Problem 13 contains a design day in its IDF; that
does not establish a grant to redistribute its separate EPW, DDY or STAT files.

## Paper-derived fixtures

Short factual transcriptions and independently implemented mathematical methods
are different from reproducing a publication's prose, images or a dataset. U.S.
Copyright Office guidance distinguishes facts/methods from their expression; it
does not settle every applicable contract, database right or third-party license.
See the [Copyright Office's explanation](https://www.copyright.gov/help/faq/faq-protect.html).

For a small factual fixture, record the DOI, page/table/equation, printed precision,
variable ordering, any transcription or unit transformation, and the applicable
source terms. Retain enough provenance to distinguish a published number from a
new simulation result. Do not copy PDFs, figures, extensive table content or
supplementary datasets under the root MIT license. Review any supplement's own
grant and notices before including its contents.

A paper pointwise assertion requires the full parameter vector, corresponding
objective, and sufficient engine/model/weather conditions. Missing information is
a validation gap, not permission to invent a fixture. Paper-specification checks,
original-C#/8.5 equivalence and version-26.2 regression checks have separate labels.
Record paper/code discrepancies explicitly, including 0.55 m in Waibel Eq. (7)
versus 0.5488 m in the reference C# penalty.

## Distribution checks

Before distributing a source archive, wheel, model collection or CI artifact:

1. Include the root MIT license, `THIRD_PARTY_NOTICES.md`, the full upstream BSD
   text and the applicable per-file notices. Check the built distribution, not only
   the checkout.
2. Check the original-asset hashes and coverage with `tests/test_licenses.py`.
   Add provenance for every new imported asset; do not silently normalize or edit
   the legacy originals.
3. Confirm generated models retain source attribution and conversion provenance.
4. Exclude unapproved external weather/engine/runtime/publication files from
   archives, wheels, caches and downloadable outputs. A newly included external
   asset needs its own license review and notices.
5. Report unresolved rights or numerical-validation coverage accurately. Passing
   the automated checks confirms the recorded file/notice checks, not blanket
   legal clearance of an asset's entire history.

Normal research citations are listed in [references.md](references.md). Publication
credit and license compliance are separate obligations.
