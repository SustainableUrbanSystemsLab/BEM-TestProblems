# References

Please cite the benchmark paper and the originating studies corresponding to the
problems used. Machine-readable entries are in `references.bib`; `CITATION.cff`
identifies the preferred benchmark citation.

| Problems used | Originating optimization study | BibTeX key |
| --- | --- | --- |
| 1–6 | Wetter and Wright (2004) | `WetterWright2004` |
| 8 | Wetter and Wright (2004); Wortmann, Waibel, Nannicini, Evins, Schroepfer and Carmeliet (2017) for the reduction rationale | `WetterWright2004`, `Wortmann2017` |
| 9–10 | Kämpf, Wetter and Robinson (2010) | `Kaempf2010` |
| 13 | Djuric, Novakovic, Holst and Mitrovic (2007) | `Djuric2007` |

For each selected problem, cite Waibel, Wortmann, Evins and Carmeliet (2019)
together with its originating study. These studies are also included in
the machine-readable `references` section of `CITATION.cff`.

- **All problems and their BEOBenchmark implementation:** Waibel, C., Wortmann,
  T., Evins, R., and Carmeliet, J. (2019). Building energy optimization: An
  extensive benchmark of global search algorithms. *Energy and Buildings*, 187,
  218–240. [doi:10.1016/j.enbuild.2019.01.048](https://doi.org/10.1016/j.enbuild.2019.01.048).
- **Problems 1–6 and 8:** Wetter, M., and Wright, J. (2004). A comparison of
  deterministic and probabilistic optimization algorithms for nonsmooth
  simulation-based optimization. *Building and Environment*, 39(8), 989–999.
  [doi:10.1016/j.buildenv.2004.01.022](https://doi.org/10.1016/j.buildenv.2004.01.022).
- **Problem 8's reduction rationale:** Wortmann, T., Waibel, C., Nannicini, G.,
  Evins, R., Schroepfer, T., and Carmeliet, J. (2017). Are Genetic Algorithms
  Really the Best Choice for Building Energy Optimization? *Proceedings of the
  Symposium on Simulation for Architecture and Urban Design*, Toronto, Canada,
  51–58. [doi:10.22360/simaud.2017.simaud.006](https://doi.org/10.22360/simaud.2017.simaud.006).
  This preliminary sensitivity study motivates fixing the summer night-cooling
  setpoint and cooling supply temperature; the 2019 benchmark specifies the
  resulting 11-variable problem.
- **Problems 9–10:** Kämpf, J. H., Wetter, M., and Robinson, D. (2010). A comparison
  of global optimization algorithms with standard benchmark functions and
  real-world applications using EnergyPlus. *Journal of Building Performance
  Simulation*, 3(2), 103–120.
  [doi:10.1080/19401490903494597](https://doi.org/10.1080/19401490903494597).
- **Problem 13:** Djuric, N., Novakovic, V., Holst, J., and Mitrovic, Z. (2007).
  Optimization of energy consumption in buildings with hydronic heating systems
  considering thermal comfort by use of computer-based tools. *Energy and
  Buildings*, 39(4), 471–477.
  [doi:10.1016/j.enbuild.2006.08.009](https://doi.org/10.1016/j.enbuild.2006.08.009).

The source implementation is [BEOBenchmark V1](https://github.com/christophwaibel/BEOBenchmark/tree/54736a6b899a488222ad3184f306c1f401daf4f9),
copyright 2018 Christoph Waibel, BSD-3-Clause. Its original file provenance is
recorded in `assets/manifest.json`.

## Model ancestry and required credit

The simple-office templates for **problems 1–3** identify BESTEST high-mass
**Case 930**, Michael Wetter as model author, and R. H. Henninger of GARD Analytics
as the source of the input case. Acknowledge that model ancestry with Judkoff, R.,
and Neymark, J. (1995), *International Energy Agency Building Energy Simulation
Test (BESTEST) and Diagnostic Method*, NREL/TP-472-6231,
[doi:10.2172/90674](https://doi.org/10.2172/90674),
BibTeX key `JudkoffNeymark1995`. The laboratory's
[publication record](https://research-hub.nlr.gov/en/publications/international-energy-agency-building-energy-simulation-test-beste/)
identifies the report and both authors. The optimization definitions and variants
remain those attributed above.

For **problems 9–10**, the retained DOE Commercial Building Benchmark notice
requires credit to **DOE, NREL, PNNL and LBNL** in publications resulting from use
of those models. Cite the notice's historical reference: U.S. Department of
Energy, Energy Efficiency and Renewable Energy, Office of Building Technologies
(2007), *Commercial Building Benchmarks*, Washington, DC; BibTeX key
`DOECommercialBuildingBenchmarks2007`. The
[current DOE program page](https://www.energy.gov/cmei/buildings/commercial-reference-buildings)
documents this model family under its newer name, commercial reference buildings.
That URL is a model-family reference, while the 2007 citation comes from the
[retained source-model notice](../src/bem_testproblems/data/licenses/BEOBenchmark-MODEL-NOTICES.txt).
No endorsement by these organizations is implied.

## Numerical interpretation

Tables 2–5 and 7 and Eqs. (5)–(7) and (10) in Waibel, Wortmann, Evins and Carmeliet
(2019) specify the scoped problem dimensions, domains and objectives. The main
paper's boxplots, ranks and aggregate statistics are not complete pointwise
`x → f(x)` records. The [validation guide](validation.md) records the available
numerical evidence and the scope of the reference comparisons.

The originating studies remain cited for problem provenance and formula
attribution. Numerical publication validation targets only
Waibel, Wortmann, Evins and Carmeliet (2019)
and its EnergyPlus-8.5 benchmark; values from earlier simulator/model versions
are not numerical fixtures for this project.
