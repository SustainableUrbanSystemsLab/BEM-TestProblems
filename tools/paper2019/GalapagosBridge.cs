// SPDX-License-Identifier: MIT
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Web.Script.Serialization;
using Galapagos;
using Galapagos.Solvers;

// Calls the original solver DLL. The adapter mirrors its historical slider
// tick mapping and founder-population setup; it implements no search operators.
class GalapagosBridge
{
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static int calls;

    static int Main()
    {
        CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
        try
        {
            var request = Json.Deserialize<Dictionary<string, object>>(Console.ReadLine());
            string method = (string)request["method"];
            int seed = Convert.ToInt32(request["seed"]);
            int budget = Convert.ToInt32(request["budget"]);
            var lower = Json.ConvertToType<double[]>(request["lower"]);
            var upper = Json.ConvertToType<double[]>(request["upper"]);
            var initial = Json.ConvertToType<double[]>(request["x0"]);
            var digits = Json.ConvertToType<int[]>(request["digits"]);
            var ticks = lower.Select((v, i) => Math.Min(1000000000,
                Convert.ToInt32((upper[i] - v) * Math.Pow(10, Math.Min(5, digits[i]))))).ToArray();
            var hint = new GP_Genome(lower.Select((v, i) =>
            {
                decimal start = Math.Round(Convert.ToDecimal(initial[i]), digits[i],
                    MidpointRounding.AwayFromZero);
                double fraction = Convert.ToDouble((start - Convert.ToDecimal(v)) /
                    (Convert.ToDecimal(upper[i]) - Convert.ToDecimal(v)));
                return new GP_Gene(Convert.ToInt32(fraction * ticks[i]), 0, ticks[i]);
            }).ToArray());
            GP_Galapagos.SetSeed(seed);
            var settings = new GP_SolverSettings { Target = double.NegativeInfinity, UseRuntimeLimit = false };
            Write(new { type = "settings", method, seed, budget, ticks,
                settings.GA_InitialSize, settings.GA_InitialBoost, settings.GA_MinimumSize,
                settings.GA_FruitlessLimit, settings.GA_MaintainPercentage, settings.GA_InbreedingFactor,
                settings.SA_InitialEnergy, settings.SA_EnergyDecay, settings.SA_DriftRate });
            GP_FitnessDelegate evaluate = genome =>
            {
                var x = genome.Select((gene, i) => (double)Math.Round(
                    Convert.ToDecimal(lower[i]) + Convert.ToDecimal((double)gene.Value / ticks[i]) *
                    (Convert.ToDecimal(upper[i]) - Convert.ToDecimal(lower[i])),
                    digits[i], MidpointRounding.AwayFromZero)).ToArray();
                Write(new { type = "evaluation", x });
                var reply = Json.Deserialize<Dictionary<string, object>>(Console.ReadLine());
                double value = Convert.ToDouble(reply["objective"], CultureInfo.InvariantCulture);
                if (double.IsNaN(value) || double.IsInfinity(value))
                    throw new ArgumentException("Objective must be finite");
                genome.Fitness = value;
                calls++;
            };
            GP_AbortDelegate abort = () => calls >= budget;
            string termination;
            if (method == "galapagos_ga")
            {
                var species = new Galapagos.Solvers.Evolution.GP_Species();
                species.CreateFounderPopulation(hint, settings.GA_InitialSize * settings.GA_InitialBoost, 1.0);
                species.Populations.MostRecent.ComputeFitness(evaluate, abort, settings);
                var solver = new Galapagos.Solvers.Evolution.GP_Solver {
                    Species = species, Settings = settings, FitnessDelegate = evaluate, AbortDelegate = abort };
                GP_SolverInstruction instruction = GP_SolverInstruction.@continue;
                while (calls < budget && instruction == GP_SolverInstruction.@continue)
                    instruction = solver.Evolve(0.0);
                termination = instruction.ToString();
            }
            else if (method == "galapagos_sa")
            {
                var solver = new Galapagos.Solvers.Annealing.GP_Solver {
                    Settings = settings, FitnessDelegate = evaluate, AbortDelegate = abort };
                GP_SolverInstruction instruction = GP_SolverInstruction.@continue;
                while (calls < budget && instruction == GP_SolverInstruction.@continue)
                {
                    instruction = solver.Anneal(hint);
                    hint = null;
                }
                termination = instruction.ToString();
            }
            else throw new ArgumentException("Unknown original Galapagos method");
            Write(new { type = "finished", success = true, calls, termination });
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 2;
        }
    }

    static void Write(object value)
    {
        Console.WriteLine(Json.Serialize(value));
        Console.Out.Flush();
    }
}
