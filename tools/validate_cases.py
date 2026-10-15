"""Run explicit designs and compare them with C# or reviewed engine baselines.

Reports contain numerical results and provenance, not weather or model files.
This command never updates its --baseline input.
"""

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from bem_testproblems import get_problem
from bem_testproblems.energyplus import (
    EnergyPlusRunner,
    RunResult,
    _process_options,
    _terminate_tree,
)
from bem_testproblems.outputs import extract_outputs
from bem_testproblems.reference import legacy_template_path

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_WEATHER = {
    1: "seattle", 2: "houston", 3: "chicago", 4: "seattle", 5: "houston",
    6: "chicago", 8: "chicago", 9: "san_francisco", 10: "san_francisco", 13: "chicago",
}


def require_close(actual, expected, label, *, rtol=2e-12, atol=1e-9):
    if not math.isfinite(actual) or not math.isfinite(expected):
        raise AssertionError(f"Nonfinite {label}")
    if not math.isclose(actual, expected, rel_tol=rtol, abs_tol=atol):
        raise AssertionError(f"{label}: {actual:.17g} != {expected:.17g}")


def numerical_difference(actual, expected, unit, *, rtol, atol):
    if not math.isfinite(actual) or not math.isfinite(expected):
        raise AssertionError("Nonfinite regression value")
    delta = abs(actual - expected)
    scale = max(abs(actual), abs(expected))
    allowed = max(atol, rtol * scale)
    return {"actual": actual, "expected": expected, "absolute_difference": delta,
            "relative_difference": delta / scale if scale else 0.0,
            "allowed_difference": allowed, "unit": unit, "passed": delta <= allowed}


def compare_inputs(actual, expected):
    """Compare effective IDF fields, ignoring comments and number formatting."""
    def fields(path):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        uncommented = "\n".join(line.split("!", 1)[0] for line in text.splitlines())
        return [[" ".join(field.split()) for field in obj.split(",")]
                for obj in uncommented.split(";") if obj.strip()]

    left, right = fields(actual), fields(expected)
    if len(left) != len(right):
        raise AssertionError("Generated IDFs have different object counts")
    for index, (first_object, second_object) in enumerate(zip(left, right, strict=True)):
        if len(first_object) != len(second_object):
            raise AssertionError(f"IDF object {index} has different field counts")
        for field, (a, b) in enumerate(zip(first_object, second_object, strict=True)):
            label = f"IDF field {index}:{field}"
            try:
                first, second = float(a), float(b)
            except ValueError:
                if a != b:
                    raise AssertionError(f"{label}: {a!r} != {b!r}")
            else:
                require_close(first, second, label, atol=1e-11)


def require_successful_archive(directory):
    """Reject stale/partial C# outputs even when the original caller ignores errors."""
    status = directory / "engine-exit-code.txt"
    if not status.is_file() or status.read_text().strip() != "0":
        raise RuntimeError("Original EnergyPlus process did not return success")
    end = directory / "eplusout.end"
    diagnostics = directory / "eplusout.err"
    if not end.is_file() or "EnergyPlus Completed Successfully" not in end.read_text(errors="replace"):
        raise RuntimeError("Original EnergyPlus did not complete successfully")
    if not diagnostics.is_file():
        raise RuntimeError("Original EnergyPlus diagnostics are missing")
    if re.search(r"\*\*\s*(?:Severe|Fatal)\s*\*\*", diagnostics.read_text(errors="replace"), re.IGNORECASE):
        raise RuntimeError("Original EnergyPlus reported severe/fatal diagnostics")


def fixed_row_outputs(problem, directory):
    """Independent row selections copied from the unchanged C# source contract."""
    if problem.family == "office":
        lines = (directory / "eplustbl.csv").read_text().splitlines()
        return {"Y": float(lines[16].split(",")[4])}
    lines = (directory / "eplusout.eso").read_text().splitlines()

    def row(index, divisor=3.6e6):
        return float(lines[index].split(",")[1]) / divisor

    if problem.family == "simple":
        return {"E_L": row(12), "Q_h": row(13), "Q_c": row(14)}
    if problem.family == "school":
        return {"Q": row(55), "P": row(56, 1000)}
    result = {f"H_{i + 1}": row(28 + i) for i in range(6)}
    result.update({f"L_{name}": row(23 + i) for i, name in enumerate(("N", "W", "E", "S", "I"))})
    result.update(C=row(36), V_legacy=row(34))
    return result


def run_oracle(problem, x, weather, directory, oracle, proxy, runner, folder=731):
    if os.name != "nt":
        raise RuntimeError("The original C# oracle requires Windows")
    directory = directory.resolve(strict=True)
    oracle, proxy = oracle.resolve(strict=True), proxy.resolve(strict=True)
    incoming = Path(f"C:/eplus/EPOpti17/Input{folder}")
    outgoing = Path(f"C:/eplus/EPOpti17/Output{folder}")
    incoming.mkdir(parents=True, exist_ok=True)
    outgoing.mkdir(parents=True, exist_ok=True)
    engine_dir = incoming / "ep"
    (engine_dir / "WeatherData").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(proxy, engine_dir / "energyplus.exe")
    shutil.copyfile(runner.executable.parent / "Energy+.idd", engine_dir / "Energy+.idd")
    template = legacy_template_path(problem.template_filename)
    shutil.copyfile(template, incoming / template.name)
    shutil.copyfile(weather, engine_dir / "WeatherData" / weather.name)
    request = directory / "request.json"
    response = directory / "response.json"
    archive = directory / "original-output"
    request.write_text(json.dumps({"problem": problem.id, "x": list(x), "folder": folder,
                                   "template": template.stem, "weather": weather.stem}))
    environment = dict(os.environ, BEM_REFERENCE_ENERGYPLUS=str(runner.executable),
                       BEM_REFERENCE_ARCHIVE=str(archive))
    process = subprocess.Popen([str(oracle), str(request), str(response)], env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               **_process_options())
    try:
        stdout, stderr = process.communicate(timeout=runner.timeout)
    except subprocess.TimeoutExpired:
        _terminate_tree(process)
        raise RuntimeError("Original C# oracle timed out") from None
    (directory / "oracle-stdout.log").write_text(stdout)
    (directory / "oracle-stderr.log").write_text(stderr)
    if process.returncode or not response.is_file():
        raise RuntimeError(f"Original C# oracle failed: {stderr[-4000:]}")
    require_successful_archive(archive)
    value = json.loads(response.read_text())["objective"]
    return value, archive


def validate(args):
    args.work_dir = args.work_dir.resolve()
    runner = EnergyPlusRunner(args.engine, expected_version=args.version,
                              timeout=args.timeout, output_root=args.work_dir, cache=False)
    fixtures = json.loads(args.cases.read_text())
    known_cases = {case["case_id"] for case in fixtures["cases"]}
    if args.case_id and not set(args.case_id) <= known_cases:
        raise ValueError("Unknown validation case ID")
    expected = json.loads(args.baseline.read_text()) if args.baseline else None
    if args.oracle and (args.version != "8.5.0" or args.proxy is None):
        raise ValueError("The original C# comparison requires 8.5.0 and --proxy")
    if expected is not None:
        if expected["engine_version"] != args.version or expected["weather_kind"] != args.weather_kind:
            raise ValueError("Baseline engine/weather variant does not match this run")
        expected = {case["case_id"]: case for case in expected["cases"]}
    report = {"engine_version": runner.version, "engine_sha256": runner.executable_sha256,
              "upstream_commit": "54736a6b899a488222ad3184f306c1f401daf4f9",
              "platform": platform.system() + "-" + platform.machine(),
              "weather_kind": args.weather_kind, "comparison": "original-csharp" if args.oracle else "engine-regression" if expected else "measurement-only",
              "rtol": args.rtol, "atol": args.atol, "cases": [], "passed": False}
    args.work_dir.mkdir(parents=True, exist_ok=True)
    comparison_failures = []
    try:
        for case in fixtures["cases"]:
            if args.case_id and case["case_id"] not in args.case_id:
                continue
            problem, x = get_problem(case["problem"]), case["x"]
            problem.validate(x)
            case_dir = args.work_dir / case["case_id"]
            case_dir.mkdir(exist_ok=False)
            suffix = ".idf" if args.version == "8.5.0" else ".epJSON"
            render = problem.render_legacy if args.version == "8.5.0" else problem.render_modern
            model = render(x, case_dir / ("model" + suffix))
            weather_name = (f"synthetic_{SYNTHETIC_WEATHER[problem.id]}.epw"
                            if args.weather_kind == "synthetic-ci" else problem.weather_filename)
            weather = (args.weather_dir / weather_name).resolve(strict=True)
            run = runner.run(model, weather, design_day=problem.design_day)
            outputs = extract_outputs(problem.family, run)
            terms = problem.objective_terms(x, outputs)
            value = problem.outer_loss(x, outputs)
            item = {**case, "objective": value, "components": outputs, "terms": terms,
                    "input_sha256": run.input_sha256, "weather_file": weather_name,
                    "weather_sha256": run.weather_sha256, "elapsed_seconds": run.elapsed}
            if args.oracle:
                original, archive = run_oracle(problem, x, weather, case_dir, args.oracle,
                                                args.proxy, runner)
                require_close(value, original, "Original C# objective")
                compare_inputs(model, archive / "input.idf")
                raw = fixed_row_outputs(problem, archive)
                named = extract_outputs(problem.family, RunResult(directory=archive, version="8.5.0"))
                for key, number in raw.items():
                    require_close(named[key], number, "Reference output mapping " + key)
                    require_close(outputs[key], number, "Python/C# simulator output " + key)
                item["reference_objective"] = original
                item["reference_components"] = raw
            if expected is not None:
                previous = expected.pop(case["case_id"])
                if previous["x"] != x or previous["problem"] != problem.id:
                    raise AssertionError("Baseline design does not match the case")
                if previous["weather_sha256"] != run.weather_sha256:
                    raise AssertionError("Baseline weather bytes changed")
                if previous["input_sha256"] != run.input_sha256:
                    raise AssertionError("Baseline model input bytes changed")
                if previous["components"].keys() != outputs.keys():
                    raise AssertionError("Baseline output schema changed")
                comparisons = {}
                for key, number in {**previous["components"], "objective": previous["objective"]}.items():
                    actual = value if key == "objective" else outputs[key]
                    unit = problem.objective_unit if key == "objective" else "MJ/m2" if key == "Y" else "kW" if key == "P" else "kWh"
                    difference = numerical_difference(actual, number, unit,
                                                      rtol=args.rtol, atol=args.atol)
                    comparisons[key] = difference
                    if not difference["passed"]:
                        comparison_failures.append(
                            f"{case['case_id']} {key}: {actual:.17g} != {number:.17g} "
                            f"(abs={difference['absolute_difference']:.6g}, "
                            f"rel={difference['relative_difference']:.6g})")
                item["regression_comparison"] = comparisons
            report["cases"].append(item)
            print(f"{case['case_id']}: {value:.12g} {problem.objective_unit}", flush=True)
        if not report["cases"]:
            raise AssertionError("No validation cases were selected")
        if expected and not args.case_id:
            raise AssertionError("Baseline contains cases that were not exercised")
        if comparison_failures:
            report["comparison_failures"] = comparison_failures
            raise AssertionError("Regression differences:\n" + "\n".join(comparison_failures))
        report["passed"] = True
    except BaseException as error:
        report["failure"] = str(error)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            message = str(error).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print("::error::" + message, flush=True)
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--version", choices=("8.5.0", "26.2.0"), required=True)
    parser.add_argument("--weather-dir", type=Path, required=True)
    parser.add_argument("--weather-kind", choices=("synthetic-ci", "canonical"), required=True)
    parser.add_argument("--cases", type=Path, default=ROOT / "reference/cases.json")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--proxy", type=Path)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--rtol", type=float, default=1e-8)
    parser.add_argument("--atol", type=float, default=1e-7)
    validate(parser.parse_args())
