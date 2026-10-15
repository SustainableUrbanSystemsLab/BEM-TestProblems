# Published best-found designs

## Source and scope

- **Source:** Waibel, Christoph (2018), *Simulation-Based Optimization of Buildings
  and Multi-Energy Systems*, ETH dissertation No. 25399.
  [DOI: 10.3929/ethz-b-000307674](https://doi.org/10.3929/ethz-b-000307674).
- **Solution tables:** Tables C.1–C.2 in Appendix C, printed page 298, contain
  objectives and complete printed vectors for all ten continuous problems.
  The captions specify rounding to two decimal places.
- **Meaning of “optimal”:** §6.3, printed page 191, identifies these as the best
  solutions across the Chapter 5 optimization runs, used as estimates of global
  optima. They are not proofs of global optimality.
- **Benchmark conditions:** §5.5.1–5.5.2, printed pages 147 and 157, specifies
  EnergyPlus 8.5.0, 20 reruns, and `100(n+1)` evaluations for the scoped problems.
- **Relation to the journal paper:** the thesis has 20 optimizer configurations;
  Waibel, Wortmann, Evins, and Carmeliet (2019) has 16. The thesis supplies
  additional reference designs for the same problem family, but its best-found
  results must not be relabelled as the journal paper's exact winning runs.
- **Starting points:** these are final designs. They do not supply the missing
  historical starting vectors, seeds, or raw optimizer trajectories.

The citation is recorded in [references.bib](../references.bib) and
[CITATION.cff](../CITATION.cff). See the [validation guide](validation.md) for the
separate code-parity, modern-baseline, and publication comparisons.

## Coordinate interpretation

| Problems | Printed coordinates | Interpretation before evaluation |
| --- | ---: | --- |
| 1–3 | 4 | Direct physical coordinates in the published order |
| 4–6 | 13 | Candidate Grasshopper-slider interpretation below; Appendix C does not explain the conversion |
| 8 | 11 | Same candidate slider interpretation, with two fixed physical parameters |
| 9–10 | 13 | Direct physical coordinates; rounding near window-height penalty thresholds needs particular care |
| 13 | 10 | Direct physical coordinates in the published order |

The first coordinates for P4–6 and P8 cannot be passed directly to the physical
API: their printed values fall outside the width bounds. The pinned
[Problem4-6_continuous.gh](https://github.com/milzj/BEOBenchmark/blob/54736a6b899a488222ad3184f306c1f401daf4f9/BEOBenchmark_V1/Grasshopper/Problem4-6_continuous.gh)
and [Problem8_reduced.gh](https://github.com/milzj/BEOBenchmark/blob/54736a6b899a488222ad3184f306c1f401daf4f9/BEOBenchmark_V1/Grasshopper/Problem8_reduced.gh)
definitions reveal slider expressions and wiring consistent with the following
interpretation. Here, `a_i` denotes the Appendix C entry, while `x_i` denotes the
physical parameter in [parameters.py](../src/bem_testproblems/parameters.py).

| Physical parameter | Candidate conversion from Appendix C |
| --- | --- |
| `x1`: north window width | `1.224 + 4.608*a1` m |
| `x2`: west window width | `7.344 + 18.324*a2` m |
| `x3`: east window width | `7.344 + 18.324*a4` m |
| `x4`: south window width | `1.224 + 4.608*a6` m |
| `x5`: west overhang depth | `0.05 + a3` m |
| `x6`: east overhang depth | `0.05 + a5` m |
| `x7`: south overhang depth | `0.05 + a7` m |

- **P4–6:** the remaining shading and temperature parameters retain their order:
  `x8` through `x13` correspond to `a8` through `a13`.
- **P8:** `a8` through `a10` are the shading setpoints; `a11` maps to physical
  `x12`, the winter night-cooling setpoint. Physical `x11 = 25°C` and
  `x13 = 12°C` remain fixed.
- **Evidence limit:** the Grasshopper wiring is verified; Appendix C's use of
  that slider order is inferred. These four designs remain candidate mappings
  until numerical comparison supports the interpretation. Do not clamp invalid
  printed coordinates or silently treat the entire vector as normalized.

## How to compare the results

- Evaluate each rounded physical design using the unchanged C# and Python
  implementations with the same 8.5 engine and canonical weather. Their mutual
  agreement still uses relative tolerance `1e-6`, with absolute tolerance `1e-7`
  near zero.
- Compare those measured objectives with the thesis values separately. Report
  the signed difference and `100*(measured - published)/abs(published)`.
- Repeat the same physical designs with 26.2 and report both the thesis-relative
  difference and the change from the measured 8.5 result.
- Compare newly optimized designs with the interpreted thesis designs coordinate
  by coordinate. Include physical differences and differences as a percentage
  of each parameter's box width; state that the reference coordinates are rounded.
- Preserve rejected outcomes explicitly. The separate
  [reference-warmup policy](optimization-replication.md#diagnostics-and-figures)
  does not turn those values into strict accepted evaluations.
- Keep this literature comparison separate from the frozen CI baselines. No
  objective has yet been empirically validated against these newly identified
  thesis designs.

## Precision and reuse limits

- A printed two-decimal objective can differ from its unrounded value by about
  `0.005`, even before accounting for rounded coordinates. That does not justify
  a `1e-6` publication-agreement assertion.
- Rounding also changes the evaluated design. Under the candidate slider mapping,
  a `0.005` rounding error becomes up to `0.02304` m in north/south width and
  `0.09162` m in west/east width. P9–10 can cross discontinuous window penalties.
  An arbitrary wider tolerance cannot establish the missing full-precision pair.
- [ETH's record](https://www.research-collection.ethz.ch/entities/publication/5c6510c6-64a7-49e9-a872-134d4bbc704b)
  identifies the thesis as
  [In Copyright – Non-Commercial Use Permitted](https://rightsstatements.org/page/InC-NC/1.0/).
  These terms are distinct from the code's MIT/BSD licenses.
- The thesis PDF, page images, and numerical table transcription are not bundled
  in the repository or distributions. Numerical research notes remain local;
  this guide records the citation, interpretation, and limitations.
