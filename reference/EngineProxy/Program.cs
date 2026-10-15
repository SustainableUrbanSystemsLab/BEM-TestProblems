// MIT. Run the genuine engine and capture evidence before legacy cleanup.
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;

internal static class Program
{
    private static int Main(string[] args)
    {
        string engine = Environment.GetEnvironmentVariable("BEM_REFERENCE_ENERGYPLUS");
        string archive = Environment.GetEnvironmentVariable("BEM_REFERENCE_ARCHIVE");
        if (string.IsNullOrEmpty(engine) || string.IsNullOrEmpty(archive)) throw new ArgumentException("Reference engine and archive are required");
        Directory.CreateDirectory(archive);
        string input = args.Last();
        int outputIndex = Array.IndexOf(args, "-d");
        if (outputIndex < 0 || outputIndex + 1 >= args.Length) throw new ArgumentException("Missing output directory");
        string output = args[outputIndex + 1];
        if (args.Any(a => a.Any(char.IsWhiteSpace) || a.Contains("\"")))
            throw new ArgumentException("The legacy components require whitespace-free fixed input/output paths");
        File.Copy(input, Path.Combine(archive, "input.idf"), true);
        var info = new ProcessStartInfo(engine)
        {
            // The original components use fixed, whitespace-free Windows paths.
            Arguments = string.Join(" ", args),
            WorkingDirectory = Environment.CurrentDirectory,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        using (var process = Process.Start(info))
        {
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            process.WaitForExit();
            Task.WaitAll(stdout, stderr);
            File.WriteAllText(Path.Combine(archive, "stdout.txt"), stdout.Result);
            File.WriteAllText(Path.Combine(archive, "stderr.txt"), stderr.Result);
            File.WriteAllText(Path.Combine(archive, "engine-exit-code.txt"), process.ExitCode.ToString(System.Globalization.CultureInfo.InvariantCulture));
            if (Directory.Exists(output))
                foreach (var file in Directory.GetFiles(output))
                    File.Copy(file, Path.Combine(archive, Path.GetFileName(file)), true);
            return process.ExitCode;
        }
    }
}
