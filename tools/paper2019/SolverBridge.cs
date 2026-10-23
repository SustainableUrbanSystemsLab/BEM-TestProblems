// SPDX-License-Identifier: MIT
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Web.Script.Serialization;
using FrOG;
using FrOG.Solvers;

// Only transport: all search logic and presets remain in the upstream DLLs.
class SolverBridge
{
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    static int calls;

    static void Main()
    {
        CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
        CultureInfo.DefaultThreadCurrentUICulture = CultureInfo.InvariantCulture;
        try
        {
            var request = Json.Deserialize<Dictionary<string, object>>(Console.ReadLine());
            string preset = (string)request["preset"];
            int seed = Convert.ToInt16(request["seed"]);
            int budget = Convert.ToInt32(request["budget"]);
            var lower = Json.ConvertToType<double[]>(request["lower"]);
            var upper = Json.ConvertToType<double[]>(request["upper"]);
            var digits = request.ContainsKey("digits")
                ? Json.ConvertToType<int[]>(request["digits"]) : null;
            var variables = lower.Select((v, i) => new Variable(
                Convert.ToDecimal(v), Convert.ToDecimal(upper[i]), false)).ToList();
            object solver = preset.StartsWith("SGA") ? (object)new I_simpleGA()
                : preset.StartsWith("ES") ? (object)new I_simpleES() : new I_PSO();
            var presets = solver.GetType().GetField("_presets", BindingFlags.Instance | BindingFlags.NonPublic);
            var settings = (Dictionary<string, Dictionary<string, double>>)presets.GetValue(solver);
            Write(new { type = "settings", preset, settings = settings[preset], seed, budget });
            Func<IList<decimal>, double> evaluate = x =>
            {
                if (x == null || calls >= budget) return double.NaN;
                Write(new { type = "evaluation", raw_x = x.Select(v => (double)v).ToArray(),
                    x = x.Select((v, i) => (double)(digits == null ? v :
                        Math.Round(v, digits[i], MidpointRounding.AwayFromZero))).ToArray() });
                var reply = Json.Deserialize<Dictionary<string, object>>(Console.ReadLine());
                double value = Convert.ToDouble(reply["objective"], CultureInfo.InvariantCulture);
                if (double.IsNaN(value) || double.IsInfinity(value))
                    throw new ArgumentException("Objective must be finite");
                calls++;
                return value;
            };
            var run = solver.GetType().GetMethod("RunSolver");
            bool success = (bool)run.Invoke(solver, new object[] {
                variables, evaluate, preset, "seed=" + seed, "", "" });
            Write(new { type = "finished", success, calls });
            Environment.ExitCode = success ? 0 : 1;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            Environment.ExitCode = 2;
        }
    }

    static void Write(object value)
    {
        Console.WriteLine(Json.Serialize(value));
        Console.Out.Flush();
    }
}
