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
    EnergyPlusError,
    EnergyPlusRunner,
    RunResult,
    _process_options,
    _terminate_tree,
    sha256_file,
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
    if abs(actual - expected) > max(atol, rtol * abs(expected)):
        raise AssertionError(f"{label}: {actual:.17g} != {expected:.17g}")


def numerical_difference(actual, expected, unit, *, rtol, atol):
    if not math.isfinite(actual) or not math.isfinite(expected):
        raise AssertionError("Nonfinite regression value")
    signed = actual - expected
    delta = abs(signed)
    scale = abs(expected)
    allowed = max(atol, rtol * scale)
    return {"actual": actual, "expected": expected, "signed_difference": signed,
            "absolute_difference": delta,
            "relative_difference": delta / scale if scale else 0.0 if delta == 0 else None,
            "percentage_difference": 100 * signed / scale if scale else None,
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


def require_completed_archive(directory):
    """Completion is necessary even for a reference-checked rejected outcome."""
    status = directory / "engine-exit-code.txt"
    if not status.is_file() or status.read_text().strip() != "0":
        raise RuntimeError("Original EnergyPlus process did not return success")
    end = directory / "eplusout.end"
    diagnostics = directory / "eplusout.err"
    if not end.is_file() or "EnergyPlus Completed Successfully" not in end.read_text(errors="replace"):
        raise RuntimeError("Original EnergyPlus did not complete successfully")
    if not diagnostics.is_file():
        raise RuntimeError("Original EnergyPlus diagnostics are missing")


def require_successful_archive(directory):
    """Reject stale/partial C# outputs even when the original caller ignores errors."""
    require_completed_archive(directory)
    diagnostics = directory / "eplusout.err"
    if re.search(r"\*\*\s*(?:Severe|Fatal)\s*\*\*", diagnostics.read_text(errors="replace"), re.IGNORECASE):
        raise RuntimeError("Original EnergyPlus reported severe/fatal diagnostics")


def failure_diagnostics(directory):
    """Read each actual Severe line and its environment; never count summaries."""
    text = (directory / "eplusout.err").read_text(errors="replace")
    severity = re.compile(r"^\s*\*\*\s*(Severe|Fatal|Warning)\s*\*\*\s*(.*)$", re.I | re.M)
    entries = list(severity.finditer(text))
    signatures = []
    for index, entry in enumerate(entries):
        if entry.group(1).lower() != "severe":
            continue
        block = text[entry.start():entries[index + 1].start() if index + 1 < len(entries) else len(text)]
        zone = re.search(r'CheckWarmupConvergence:\s*Loads Initialization,\s*Zone="([^"]+)"',
                         entry.group(2), re.I)
        environment = re.search(r'Environment\([^)]*\)\s*=\s*"([^"]+)"', block, re.I)
        signatures.append({"kind": "CheckWarmupConvergence" if zone else "unrecognized-severe",
                           "zone": zone.group(1) if zone else None,
                           "environment": environment.group(1) if environment else None})
    return {"severe_count": len(signatures),
            "fatal_count": sum(entry.group(1).lower() == "fatal" for entry in entries),
            "warning_count": sum(entry.group(1).lower() == "warning" for entry in entries),
            "signatures": signatures}


def _normalized_signature(signature):
    def normalize(value):
        if not isinstance(value, str) or not value.strip():
            raise AssertionError("Warmup signature is missing its zone/environment")
        return " ".join(re.sub(r"^\s*RunPeriod:\s*", "", value, flags=re.I).split()).upper()
    if signature["kind"] != "CheckWarmupConvergence":
        raise AssertionError("A Severe diagnostic is not CheckWarmupConvergence")
    return (signature["kind"], normalize(signature["zone"]), normalize(signature["environment"]))


def require_failure_signature(actual, expected):
    if expected.get("stage") != "simulation" or expected.get("reason") != "simulation":
        raise AssertionError("Only reviewed simulation-stage warmup failures are supported")
    if (not actual["severe_count"] or actual["fatal_count"] != 0
            or actual["severe_count"] != expected["severe_count"]
            or expected["fatal_count"] != 0):
        raise AssertionError("Reference failure severe/fatal counts changed")
    observed = sorted(_normalized_signature(value) for value in actual["signatures"])
    reviewed = sorted(_normalized_signature(value) for value in expected["signatures"])
    if len(reviewed) != expected["severe_count"] or observed != reviewed:
        raise AssertionError("Reference warmup zone/environment signatures changed")


def require_expected_failure_archive(directory, expected):
    require_completed_archive(directory)
    diagnostic = failure_diagnostics(directory)
    require_failure_signature(diagnostic, expected)
    completion = re.search(r"EnergyPlus Completed Successfully--\s*\d+\s+Warnings?;\s*(\d+)\s+Severe Errors?",
                           (directory / "eplusout.end").read_text(errors="replace"), re.I)
    if completion is None or int(completion.group(1)) != diagnostic["severe_count"]:
        raise AssertionError("Reference failure completion/severe counts are inconsistent")
    return diagnostic


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


def run_oracle(problem, x, weather, directory, oracle, proxy, runner, folder=731,
               *, expected_failure=None):
    if os.name != "nt":
        raise RuntimeError("The original C# oracle requires Windows")
    directory = directory.resolve(strict=True)
    oracle, proxy = oracle.resolve(strict=True), proxy.resolve(strict=True)
    incoming = Path(f"C:/eplus/EPOpti17/Input{folder}")
    outgoing = Path(f"C:/eplus/EPOpti17/Output{folder}")
    incoming.mkdir(parents=True, exist_ok=True)
    # The historical caller uses a fixed folder number. Its prior reports must
    # never satisfy completion/signature checks for this new invocation.
    if outgoing.exists():
        shutil.rmtree(outgoing)
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
    if expected_failure is None:
        require_successful_archive(archive)
    else:
        require_expected_failure_archive(archive, expected_failure)
    value = json.loads(response.read_text())["objective"]
    if not math.isfinite(value):
        raise AssertionError("Original C# returned a nonfinite objective")
    return value, archive


def require_native_failure(error, runner, model, weather, expected):
    """Match a strict rejection without reading its reports as an objective."""
    if not isinstance(error, EnergyPlusError) or error.reason != "simulation" or error.directory is None:
        raise AssertionError("The reviewed simulation failure changed stage/reason")
    directory = Path(error.directory).resolve(strict=True)
    metadata = json.loads((directory / "run.json").read_text())
    if (metadata.get("status") != "failed" or metadata.get("failure_reason") != "simulation"
            or type(metadata.get("returncode")) is not int or metadata["returncode"] != 0
            or metadata.get("version") != runner.version
            or metadata.get("executable_sha256") != runner.executable_sha256
            or sha256_file(runner.executable) != runner.executable_sha256):
        raise AssertionError("Retained failure process/engine provenance changed")
    staged = Path(metadata["input_file"]).resolve(strict=True)
    if (staged.parent != directory or metadata["input_sha256"] != sha256_file(model)
            or sha256_file(staged) != metadata["input_sha256"]):
        raise AssertionError("Retained failure input bytes changed")
    weather_hash = sha256_file(weather) if weather else None
    if metadata["weather_sha256"] != weather_hash:
        raise AssertionError("Retained failure weather bytes changed")
    diagnostic = failure_diagnostics(directory)
    require_failure_signature(diagnostic, expected)
    completion = re.search(r"EnergyPlus Completed Successfully--\s*\d+\s+Warnings?;\s*(\d+)\s+Severe Errors?",
                           (directory / "eplusout.end").read_text(errors="replace"), re.I)
    if completion is None or int(completion.group(1)) != diagnostic["severe_count"]:
        raise AssertionError("Retained failure completion/severe counts are inconsistent")
    return diagnostic, metadata["elapsed"]


def _check_baseline_identity(previous, case, model_hash, weather_hash, weather_name):
    if previous["x"] != case["x"] or previous["problem"] != case["problem"]:
        raise AssertionError("Baseline design does not match the case")
    if previous["weather_sha256"] != weather_hash or previous.get("weather_file") != weather_name:
        raise AssertionError("Baseline weather bytes/selection changed")
    if previous["input_sha256"] != model_hash:
        raise AssertionError("Baseline model input bytes changed")
    if type(previous.get("passed", True)) is not bool:
        raise AssertionError("Baseline outcome is not Boolean")
    if previous.get("passed", True) is False and any(
            previous.get(key) is not None for key in ("objective", "components", "terms")):
        raise AssertionError("Rejected baseline must not contain accepted objective/components/terms")


def _compare_oracle(problem, x, weather, model, case_dir, args, runner, item, expected_failure=None):
    # The unchanged P13 C# caller requires -w even though SimulationControl
    # disables weather-file periods. Keep that command and identify its argument.
    oracle_weather = weather
    if oracle_weather is None:
        oracle_weather = (args.weather_dir / get_problem(1).weather_filename).resolve(strict=True)
        item["reference_auxiliary_weather"] = {
            "weather_file": oracle_weather.name, "weather_sha256": sha256_file(oracle_weather),
            "role": "original-caller CLI argument; embedded design-day climate is evaluated",
        }
    oracle_weather_hash = sha256_file(oracle_weather)
    options = {} if expected_failure is None else {"expected_failure": expected_failure}
    original, archive = run_oracle(problem, x, oracle_weather, case_dir, args.oracle,
                                   args.proxy, runner, **options)
    if sha256_file(oracle_weather) != oracle_weather_hash:
        raise AssertionError("Original C# weather bytes changed during execution")
    compare_inputs(model, archive / "input.idf")
    if expected_failure is not None:
        item["reference_failure"] = require_expected_failure_archive(archive, expected_failure)
        item["reference_diagnostic_objective"] = original
        item["reference_diagnostic_objective_accepted"] = False
        return
    outputs, value = item["components"], item["objective"]
    raw = fixed_row_outputs(problem, archive)
    named = extract_outputs(problem.family, RunResult(directory=archive, version="8.5.0"))
    for key, number in raw.items():
        require_close(named[key], number, "Reference output mapping " + key)
    item["reference_objective"] = original
    item["reference_components"] = raw
    item["reference_comparison"] = {
        key: numerical_difference(value if key == "objective" else outputs[key], number,
                                  problem.objective_unit if key == "objective" else
                                  "MJ/m2" if key == "Y" else "kW" if key == "P" else "kWh",
                                  rtol=args.rtol, atol=args.atol)
        for key, number in {**raw, "objective": original}.items()
    }
    changed = [key for key, difference in item["reference_comparison"].items()
               if not difference["passed"]]
    if changed:
        details = [f"{key} (abs={item['reference_comparison'][key]['absolute_difference']:.6g}, "
                   f"percentage={item['reference_comparison'][key]['percentage_difference']})"
                   for key in changed]
        raise AssertionError("Python/C# numerical comparison failed: " + "; ".join(details))


def _outcome_counts(report):
    report["accepted_simulations"] = sum(item["passed"] for item in report["cases"])
    report["reference_checked_rejections"] = sum(
        bool(item.get("failure_reference_matched") and item.get("validation_passed"))
        for item in report["cases"])


def github_summary(report, report_path):
    """Render accepted physics results separately from reference-check outcomes."""
    def cell(value):
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    def delta(item, key):
        if not item["passed"]:
            return "unavailable"
        difference = item.get(key, {}).get("objective")
        if difference is None:
            return "unavailable"
        percentage = difference["percentage_difference"]
        percent = "undefined" if percentage is None else f"{percentage:+.6g}%"
        return f"{difference['signed_difference']:+.6g} ({percent})"

    accepted = sum(item["passed"] for item in report["cases"])
    rejected = sum(bool(item.get("failure_reference_matched") and item.get("validation_passed"))
                   for item in report["cases"])
    lines = [f"### EnergyPlus {cell(report['engine_version'])} — {cell(report['weather_kind'])}", "",
             f"Validation: **{'PASS' if report['passed'] else 'FAIL'}**. "
             f"Accepted simulations: **{accepted}**. Reference-checked rejections: **{rejected}**.", "",
             "Rejected results have no accepted objective. Δ = actual − reference; "
             "Δ% = 100 × Δ / |reference| (undefined when the reference is zero).", "",
             "| Case | Simulation | Reference validation | Objective | Baseline Δ (Δ%) | C# Δ (Δ%) |",
             "| --- | --- | --- | ---: | ---: | ---: |"]
    for item in report["cases"]:
        matched = bool(item.get("failure_reference_matched") and item.get("validation_passed"))
        simulation = "Accepted" if item["passed"] else "Rejected warmup" if matched else "Rejected"
        check = ("PASS" if item.get("validation_passed") else "FAIL")
        if item.get("validation_error"):
            check += f" ({item['validation_error']['stage']})"
        if report.get("comparison") == "measurement-only" and item.get("validation_passed"):
            check = "Not compared"
        objective = f"{item['objective']:.12g}" if item["passed"] else "unavailable"
        lines.append("| " + " | ".join(cell(value) for value in
                     (item["case_id"], simulation, check, objective,
                      delta(item, "regression_comparison"), delta(item, "reference_comparison"))) + " |")
    lines.extend(["", "Full component comparisons and failure signatures are in the uploaded report.",
                  "Report JSON: " + cell(report_path), ""])
    return "\n".join(lines)


def write_github_summary(report, report_path):
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write(github_summary(report, report_path) + "\n")


def validate(args):
    if any(not math.isfinite(value) or value < 0 for value in (args.rtol, args.atol)):
        raise ValueError("Comparison tolerances must be finite and nonnegative")
    args.work_dir = args.work_dir.resolve()
    runner = EnergyPlusRunner(args.engine, expected_version=args.version,
                              timeout=args.timeout, output_root=args.work_dir, cache=False)
    fixtures = json.loads(args.cases.read_text())
    if getattr(args, "include_orientation90", False):
        if args.weather_kind != "canonical":
            raise ValueError("The orientation-90 failure check requires canonical weather")
        if not any(case["case_id"] == "p01-orientation90" for case in fixtures["cases"]):
            fixtures["cases"].append({"case_id": "p01-orientation90", "problem": 1,
                                      "x": [90, 3, 3, 0.5]})
    known_cases = {case["case_id"] for case in fixtures["cases"]}
    if len(known_cases) != len(fixtures["cases"]):
        raise ValueError("Validation fixture contains duplicate case IDs")
    if args.case_id and not set(args.case_id) <= known_cases:
        raise ValueError("Unknown validation case ID")
    expected = json.loads(args.baseline.read_text()) if args.baseline else None
    if args.oracle and (args.version != "8.5.0" or args.proxy is None):
        raise ValueError("The original C# comparison requires 8.5.0 and --proxy")
    if expected is not None:
        if expected["engine_version"] != args.version or expected["weather_kind"] != args.weather_kind:
            raise ValueError("Baseline engine/weather variant does not match this run")
        rows = expected["cases"]
        if args.weather_kind != "canonical" and any(row.get("passed", True) is False for row in rows):
            raise ValueError("Synthetic validation cannot accept expected failures")
        expected = {case["case_id"]: case for case in rows}
        if len(expected) != len(rows):
            raise ValueError("Baseline contains duplicate case IDs")
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
            item = {**case, "passed": False, "validation_passed": False,
                    "objective": None, "components": None, "terms": None}
            stage = "preparation"
            try:
                previous = expected.pop(case["case_id"]) if expected is not None else None
                problem, x = get_problem(case["problem"]), case["x"]
                problem.validate(x)
                case_dir = args.work_dir / case["case_id"]
                case_dir.mkdir(exist_ok=False)
                suffix = ".idf" if args.version == "8.5.0" else ".epJSON"
                render = problem.render_legacy if args.version == "8.5.0" else problem.render_modern
                model = render(x, case_dir / ("model" + suffix))
                weather_name = (f"synthetic_{SYNTHETIC_WEATHER[problem.id]}.epw"
                                if args.weather_kind == "synthetic-ci" else
                                None if problem.design_day else problem.weather_filename)
                weather = (args.weather_dir / weather_name).resolve(strict=True) if weather_name else None
                model_hash = sha256_file(model)
                weather_hash = sha256_file(weather) if weather else None
                item.update(input_sha256=model_hash, weather_file=weather_name,
                            weather_sha256=weather_hash)
                if previous is not None:
                    _check_baseline_identity(previous, case, model_hash, weather_hash, weather_name)
                reviewed_failure = (previous["expected_failure"] if previous is not None
                                    and previous.get("passed", True) is False else None)
                stage = "simulation"
                try:
                    run = runner.run(model, weather, design_day=problem.design_day)
                except EnergyPlusError as error:
                    item["failure"] = {"stage": stage, "reason": error.reason, "message": str(error)}
                    if error.directory is not None:
                        item["failure"]["directory"] = str(error.directory)
                        try:
                            item["failure"].update(failure_diagnostics(error.directory))
                        except (OSError, ValueError):
                            pass
                    if sha256_file(model) != model_hash or (sha256_file(weather) if weather else None) != weather_hash:
                        raise AssertionError("Simulation input/weather bytes changed during execution") from error
                    if reviewed_failure is None:
                        raise
                    diagnostic, elapsed = require_native_failure(error, runner, model, weather, reviewed_failure)
                    item.update(expected_failure=reviewed_failure, observed_failure=diagnostic,
                                elapsed_seconds=elapsed, failure_reference_matched=True)
                    if args.oracle:
                        stage = "original-csharp"
                        _compare_oracle(problem, x, weather, model, case_dir, args, runner, item,
                                        expected_failure=reviewed_failure)
                else:
                    if (run.input_sha256 != model_hash or run.weather_sha256 != weather_hash
                            or sha256_file(model) != model_hash
                            or (sha256_file(weather) if weather else None) != weather_hash):
                        raise AssertionError("Simulation input/weather bytes changed during execution")
                    if reviewed_failure is not None:
                        raise AssertionError("Reviewed failure became successful; review the baseline explicitly")
                    stage = "outputs"
                    outputs = extract_outputs(problem.family, run)
                    terms = problem.objective_terms(x, outputs)
                    value = problem.outer_loss(x, outputs)
                    if not math.isfinite(value):
                        raise AssertionError("Nonfinite objective")
                    item.update(passed=True, objective=value, components=outputs, terms=terms,
                                elapsed_seconds=run.elapsed)
                    if args.oracle:
                        stage = "original-csharp"
                        _compare_oracle(problem, x, weather, model, case_dir, args, runner, item)
                    if previous is not None:
                        stage = "regression-comparison"
                        if previous["components"].keys() != outputs.keys():
                            raise AssertionError("Baseline output schema changed")
                        comparisons = {}
                        for key, number in {**previous["components"], "objective": previous["objective"]}.items():
                            actual = value if key == "objective" else outputs[key]
                            unit = problem.objective_unit if key == "objective" else "MJ/m2" if key == "Y" else "kW" if key == "P" else "kWh"
                            difference = numerical_difference(actual, number, unit, rtol=args.rtol, atol=args.atol)
                            comparisons[key] = difference
                            if not difference["passed"]:
                                comparison_failures.append(f"{case['case_id']} {key}: {actual:.17g} != {number:.17g} "
                                                           f"(abs={difference['absolute_difference']:.6g}, rel={difference['relative_difference']}, "
                                                           f"percentage={difference['percentage_difference']})")
                        item["regression_comparison"] = comparisons
                        item["validation_passed"] = all(value["passed"] for value in comparisons.values())
                if "regression_comparison" not in item:
                    item["validation_passed"] = True
            except Exception as error:
                item["validation_error"] = {"stage": stage, "message": str(error), "type": type(error).__name__}
                comparison_failures.append(f"{case['case_id']} [{stage}]: {error}")
            report["cases"].append(item)
            description = (f"{item['objective']:.12g} {problem.objective_unit}" if item["passed"]
                           else "rejected simulation; failure reference matched"
                           if item.get("failure_reference_matched") and item.get("validation_passed")
                           else "validation failed")
            print(f"{case['case_id']}: {description}", flush=True)
            if os.environ.get("GITHUB_ACTIONS") == "true":
                annotation = ("warning" if item.get("failure_reference_matched")
                              and item.get("validation_passed") else "notice")
                print(f"::{annotation}::{case['case_id']}: {description}", flush=True)
        if not report["cases"]:
            comparison_failures.append("No validation cases were selected")
        if expected and not args.case_id:
            comparison_failures.append("Baseline contains cases that were not exercised: " + ", ".join(expected))
        summary = {}
        for item in report["cases"]:
            for key, difference in item.get("regression_comparison", {}).items():
                family = get_problem(item["problem"]).family
                stat = summary.setdefault(f"{family}:{key}", {"unit": difference["unit"],
                                                "max_absolute_difference": 0.0,
                                                "max_relative_difference": None,
                                                "max_absolute_percentage_difference": None,
                                                "undefined_relative_comparisons": 0})
                if difference["absolute_difference"] >= stat["max_absolute_difference"]:
                    stat.update(max_absolute_difference=difference["absolute_difference"],
                                max_absolute_case=item["case_id"])
                relative = difference["relative_difference"]
                if relative is None:
                    stat["undefined_relative_comparisons"] += 1
                elif stat["max_relative_difference"] is None or relative >= stat["max_relative_difference"]:
                    stat.update(max_relative_difference=relative, max_relative_case=item["case_id"])
                percentage = difference["percentage_difference"]
                if percentage is not None and (stat["max_absolute_percentage_difference"] is None
                                              or abs(percentage) >= stat["max_absolute_percentage_difference"]):
                    stat.update(max_absolute_percentage_difference=abs(percentage),
                                signed_percentage_at_maximum=percentage,
                                max_percentage_case=item["case_id"])
        if summary:
            report["regression_summary"] = summary
            if os.environ.get("GITHUB_ACTIONS") == "true":
                print("::notice::Regression difference summary: " + json.dumps(summary), flush=True)
        _outcome_counts(report)
        if comparison_failures:
            report["comparison_failures"] = comparison_failures
            raise AssertionError("Validation differences:\n" + "\n".join(comparison_failures))
        report["passed"] = True
    except BaseException as error:
        report["failure"] = str(error)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            message = str(error).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print("::error::" + message, flush=True)
        raise
    finally:
        _outcome_counts(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        write_github_summary(report, args.output)
    return report


def main(argv=None):
    """Parse the public validation CLI; importing this tool never runs an engine."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--version", choices=("8.5.0", "26.2.0"), required=True)
    parser.add_argument("--weather-dir", type=Path, required=True)
    parser.add_argument("--weather-kind", choices=("synthetic-ci", "canonical"), required=True)
    parser.add_argument("--cases", type=Path, default=ROOT / "reference/cases.json")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--include-orientation90", action="store_true",
                        help="Add the canonical P1 orientation-90 diagnostic reference case")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--proxy", type=Path)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--rtol", type=float, default=1e-6)
    parser.add_argument("--atol", type=float, default=1e-7)
    return validate(parser.parse_args(argv))


if __name__ == "__main__":
    main()
