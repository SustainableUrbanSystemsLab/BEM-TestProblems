# Original BB-O and Galapagos adapters

These small C# programs call external original libraries. They implement JSON
transport and the saved Grasshopper slider interface; search operators remain
in the original binaries. `replication_native.py` connects them to the existing
checkpointed evaluator through `--native-solvers private-config.json`.
The default Python solver registry is unchanged.

The BB-O adapter uses the author's
[2018 FrOG snapshot](https://github.com/christophwaibel/FrOG/tree/8e16536f63141a8e6145cca46ef48eeb93973359).
Compile `SolverBridge.cs` with .NET Framework's C# compiler, referencing
`System.Web.Extensions.dll` and the original `FrOG.gha` copied as `FrOG.dll`.
Keep its original `MetaheuristicsLibrary.dll` beside the executable.
Compile `GalapagosBridge.cs` against the `Galapagos.dll` in the Components folder
of the authorized [Grasshopper 0.9.76.0 archive](https://www.rhino3d.com/download/Grasshopper/1.0/wip/rc/).
Both programs require `System.Web.Extensions.dll`; Galapagos also uses LINQ.
No Rhino application, administrator rights or scheduled task is needed to run them.

The private JSON configuration has `schema_version: 1` and a `backends` object.
Its `bbo` and `galapagos` entries each contain `executable`, `source` and `files`.
`files` maps each executable/library path to its SHA-256. Paths resolve relative
to the configuration file. Required files are:

| Backend | Pinned files |
| --- | --- |
| `bbo` | `SolverBridge.exe`, `FrOG.dll`, `MetaheuristicsLibrary.dll` |
| `galapagos` | `GalapagosBridge.exe`, `Galapagos.dll` |

Only the ten recovered BB-O/Galapagos configurations can use this option.
The manifest records the native configuration, source hashes, slider bounds and
precision, presets and seed mapping. Each attempt also retains
`solver-protocol.jsonl` with native settings, raw slider requests, physical
designs and returned objectives. The existing evaluator checkpoints every
simulation and enforces its budget. Failed simulations propagate without a
penalty; their owned solver child is stopped.

Grasshopper rounds decimal half-values away from zero. Galapagos additionally
caps search ticks at five decimal places. BB-O uses its original Int16 seed
interface, so the adapter records the experiment seed modulo 32768. Its native
initial population uses that seed and does not use the paired physical `x0`.
Galapagos uses the recorded start as its native hint.

These adapters establish access to original implementations, not completed
replication. The recovered FrOG presets differ from the printed paper in several
places, including untuned SGA's hypercube extension (source `0.01`, paper `0.1`).
Exact study builds, seeds and raw trajectories were not published. Keep native
development pilots separate from final boxplots and resolve or explicitly
report these differences. Neither binaries nor private results belong in Git.
