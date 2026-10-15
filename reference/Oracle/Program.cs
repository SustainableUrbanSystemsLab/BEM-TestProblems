using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Web.Script.Serialization;
using GHEnergyPlus;
using Grasshopper.Kernel;

internal sealed class DataAccess : IGH_DataAccess
{
    internal readonly Dictionary<int, object> Inputs = new Dictionary<int, object>();
    internal readonly Dictionary<int, object> Outputs = new Dictionary<int, object>();
    public bool GetData<T>(int index, ref T value)
    {
        object item;
        if (!Inputs.TryGetValue(index, out item)) return false;
        value = (T)Convert.ChangeType(item, typeof(T), CultureInfo.InvariantCulture);
        return true;
    }
    public void SetData(int index, object value) { Outputs[index] = value; }
}

internal static class Program
{
    private static GH_Component Component(int problem)
    {
        if (problem >= 1 && problem <= 3) return new GHEPlusRunParametric1to3();
        if ((problem >= 4 && problem <= 6) || problem == 8) return new GHEPlusRunParametric4to8();
        if (problem == 9) return new GHEPlusRunParametric9();
        if (problem == 10) return new GHEPlusRunParametric10();
        if (problem == 13) return new GHEPlusRunParametric13();
        throw new ArgumentException("Only problems 1–6, 8–10 and 13 are continuous");
    }

    private static int Main(string[] args)
    {
        CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("en-US");
        CultureInfo.CurrentUICulture = CultureInfo.GetCultureInfo("en-US");
        if (args.Length == 1 && args[0] == "--check-stubs")
        {
            foreach (var componentId in new[] { 1, 4, 9, 10, 13 }) Console.WriteLine(Component(componentId).ComponentGuid);
            return 0;
        }
        if (args.Length != 2) throw new ArgumentException("Usage: Oracle.exe request.json response.json");
        if (Environment.OSVersion.Platform != PlatformID.Win32NT) throw new PlatformNotSupportedException("The unchanged C# oracle uses Windows paths");
        var json = new JavaScriptSerializer();
        var request = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(args[0]));
        int id = Convert.ToInt32(request["problem"]);
        var x = new List<double>();
        foreach (object value in (IEnumerable)request["x"]) x.Add(Convert.ToDouble(value, CultureInfo.InvariantCulture));
        int expected = id <= 3 ? 4 : id == 8 ? 11 : id == 13 ? 10 : 13;
        if (x.Count != expected) throw new ArgumentException("Incorrect parameter count");
        if (id == 8) { x.Insert(10, 25.0); x.Add(12.0); }
        var data = new DataAccess();
        data.Inputs[0] = (string)request["template"];
        data.Inputs[1] = (string)request["weather"];
        data.Inputs[2] = true;
        int offset = 6;
        if (id <= 3) { offset = 3; data.Inputs[8] = 0; data.Inputs[9] = request["folder"]; }
        else if (id <= 6 || id == 8) { offset = 3; data.Inputs[17] = 0; data.Inputs[18] = request["folder"]; }
        else { data.Inputs[3] = 0; data.Inputs[4] = request["folder"]; }
        for (int i = 0; i < x.Count; ++i) data.Inputs[offset + i] = x[i];
        Component(id).Evaluate(data);
        if (!data.Outputs.ContainsKey(0)) throw new InvalidOperationException("Original component returned no objective");
        double objective = Convert.ToDouble(data.Outputs[0]);
        if (double.IsNaN(objective) || double.IsInfinity(objective)) throw new InvalidOperationException("Nonfinite reference objective");
        File.WriteAllText(args[1], json.Serialize(new { problem = id, objective = objective, runtime = Environment.Version.ToString() }));
        return 0;
    }
}
