# References

Please cite the benchmark paper and the originating studies corresponding to the
problems used. Machine-readable entries are in `references.bib`; `CITATION.cff`
identifies the preferred benchmark citation.

- **All problems and their BEOBenchmark implementation:** Waibel, C., Wortmann,
  T., Evins, R., and Carmeliet, J. (2019). Building energy optimization: An
  extensive benchmark of global search algorithms. *Energy and Buildings*, 187,
  218–240. [doi:10.1016/j.enbuild.2019.01.048](https://doi.org/10.1016/j.enbuild.2019.01.048).
- **Problems 1–6 and 8:** Wetter, M., and Wright, J. (2004). A comparison of
  deterministic and probabilistic optimization algorithms for nonsmooth
  simulation-based optimization. *Building and Environment*, 39(8), 989–999.
  [doi:10.1016/j.buildenv.2004.01.022](https://doi.org/10.1016/j.buildenv.2004.01.022).
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

For problems 9 and 10, the embedded DOE Commercial Building Benchmark notice also
requires credit to **DOE, NREL, PNNL and LBNL** in publications resulting from use
of those models. The notice identifies: U.S. Department of Energy, Energy
Efficiency and Renewable Energy, Office of Building Technologies (2007),
*Commercial Building Benchmarks*. No endorsement by these organizations is
implied.

## Numerical interpretation

Waibel et al. Tables 2–5 and 7 and Eqs. (5)–(7) and (10) specify the scoped problem
dimensions, domains and objectives. The main paper's boxplots, ranks and aggregate
statistics are not complete pointwise `x → f(x)` records. Its supplementary
material must be inventoried separately before its numerical coverage is claimed.

The originating studies remain cited for problem provenance and formula
attribution. Numerical publication validation targets only Waibel et al. (2019)
and its EnergyPlus-8.5 benchmark; values from earlier simulator/model versions
are not numerical fixtures for this project.
