# References

Please cite the benchmark paper and the originating studies corresponding to the
problems used. Machine-readable entries are in [references.bib](../references.bib);
[CITATION.cff](../CITATION.cff)
identifies the preferred benchmark citation.

| Problems used | Originating optimization study | BibTeX key |
| --- | --- | --- |
| 1–6 | Wetter and Wright (2004) | `WetterWright2004` |
| 8 | Wetter and Wright (2004); Wortmann, Waibel, Nannicini, Evins, Schroepfer, and Carmeliet (2017) for the reduction rationale | `WetterWright2004`, `Wortmann2017` |
| 9–10 | Kämpf, Wetter, and Robinson (2010) | `Kaempf2010` |
| 13 | Djuric, Novakovic, Holst, and Mitrovic (2007) | `Djuric2007` |

For each selected problem, cite Waibel, Wortmann, Evins, and Carmeliet (2019)
together with its originating study. These studies are also included in
the machine-readable `references` section of [CITATION.cff](../CITATION.cff).

- **All problems and their BEOBenchmark implementation:** Waibel, C., Wortmann,
  T., Evins, R., and Carmeliet, J. (2019). Building energy optimization: An
  extensive benchmark of global search algorithms. *Energy and Buildings*, 187,
  218–240. [doi:10.1016/j.enbuild.2019.01.048](https://doi.org/10.1016/j.enbuild.2019.01.048).
- **Original benchmark software:** Waibel, C. *BEOBenchmark: Building Energy
  Optimization problem test bed*. Original C# and Grasshopper implementation.
  [GitHub repository](https://github.com/christophwaibel/BEOBenchmark).
  BibTeX key: `WaibelBEOBenchmark`.
- **Rounded best-found designs:** Waibel, C. (2018). *Simulation-Based Optimization
  of Buildings and Multi-Energy Systems*. Doctoral thesis, ETH Zurich,
  dissertation No. 25399, Appendix C, Tables C.1–C.2, p. 298.
  [doi:10.3929/ethz-b-000307674](https://doi.org/10.3929/ethz-b-000307674).
  Cite this source when using its solution references; see
  [published-solutions.md](published-solutions.md) for the rounding, coordinate
  interpretation, benchmark differences, and reuse terms.
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
recorded in [manifest.json](../assets/manifest.json).
The cited [source revision](https://github.com/christophwaibel/BEOBenchmark/commit/54736a6b899a488222ad3184f306c1f401daf4f9)
is dated February 21, 2020; the source license retains its 2018 copyright year.

## Solver references

- **PDFO BOBYQA:** Ragonneau, T. M., and Zhang, Z. (2024). PDFO: a cross-platform
  package for Powell's derivative-free optimization solvers. *Mathematical
  Programming Computation*, 16(4), 535–559.
  [doi:10.1007/s12532-024-00257-9](https://doi.org/10.1007/s12532-024-00257-9).
- **Py-BOBYQA:** Cartis, C., Fiala, J., Marteau, B., and Roberts, L. (2019).
  Improving the Flexibility and Robustness of Model-Based Derivative-Free
  Optimization Solvers. *ACM Transactions on Mathematical Software*, 45(3),
  Article 32, 32:1–32:41.
  [doi:10.1145/3338517](https://doi.org/10.1145/3338517).

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
requires credit to **DOE, NREL, PNNL, and LBNL** in publications resulting from use
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

- The study by Waibel, Wortmann, Evins, and Carmeliet (2019), Tables 2–5 and 7
  and Eqs. (5)–(7) and (10), specifies the scoped dimensions, domains, and objectives. Its boxplots,
  ranks, and aggregate statistics are not complete pointwise `x → f(x)` records.
- Waibel (2018), Appendix C, adds rounded objectives and final design vectors for
  all ten continuous problems. They are best-found results from its 20-configuration
  benchmark, distinct from verified winning records for the 16-configuration
  journal benchmark. They do not supply full precision or historical starts.
- The [validation guide](validation.md) records the numerical evidence and the
  scope of the reference comparisons.

The originating studies remain cited for problem provenance and formula
attribution. Numerical literature comparisons target the EnergyPlus-8.5 benchmark
of Waibel, Wortmann, Evins, and Carmeliet (2019), with the thesis references
labelled separately. Values from the originating studies' earlier simulator/model
versions are not numerical fixtures for this project.

## Bibliographic checks

The eleven entries in [references.bib](../references.bib) were checked on
October 16, 2026 against publisher, DOI-registration, institutional, and pinned
source-project records. Author given names in that file and
[CITATION.cff](../CITATION.cff) follow the published metadata.

- The final Wortmann, Waibel, Nannicini, Evins, Schroepfer, and Carmeliet (2017)
  title uses **“for Building Energy Optimization.”** The proceedings page range
  is 51–58; the [publisher record](https://doi.org/10.22360/simaud.2017.simaud.006)
  also identifies the paper as Article 6, pages 1–8. Conflicting secondary page
  ranges and the DOI deposit's title variant are not substituted for the final paper.
- The 2007 DOE entry is retained from the required model notice. The current
  DOE page verifies the model-family name, but does not independently establish
  a standalone 2007 report.
