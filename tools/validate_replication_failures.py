"""Replay recorded replication failures, then verify their explicit numerical repair.

Canonical failures remain rejected. The separately named convergence-refined
models must complete without Severe/Fatal errors and match reviewed values.
This command never generates or updates its mandatory baseline.
"""

import argparse
import json
import math
import os
import platform
import re
from pathlib import Path

from bem_testproblems import get_problem
from bem_testproblems.energyplus import EnergyPlusError, EnergyPlusRunner, sha256_file
from bem_testproblems.outputs import extract_outputs

if __package__:
    from . import validate_cases as reference_validation
else:
    import validate_cases as reference_validation

ROOT = Path(__file__).resolve().parents[1]
VARIANT = "convergence-refined"
RTOL, ATOL = 1e-4, 1e-7


def _diagnostic_context(directory):
    details = {"directory": str(directory)}
    try:
        details["diagnostics"] = reference_validation.failure_diagnostics(directory)
        lines = (Path(directory) / "eplusout.err").read_text(errors="replace").splitlines()
        blocks = ["\n".join(lines[index:index + 7]) for index, line in enumerate(lines)
                  if re.match(r"\s*\*\*\s*(?:Severe|Fatal)\s*\*\*", line, re.I)]
        details["diagnostic_excerpt"] = "\n".join(blocks)[:8000]
    except (OSError, ValueError) as diagnostic_error:
        details["diagnostics_unavailable"] = str(diagnostic_error)
    try:
        details["completion"] = (Path(directory) / "eplusout.end").read_text(errors="replace").strip()
    except OSError as completion_error:
        details["completion_unavailable"] = str(completion_error)
    return details


def _native_failure(error):
    details = {"reason": error.reason, "message": str(error), "returncode": error.returncode}
    if error.directory is not None:
        details.update(_diagnostic_context(error.directory))
        try:
            metadata = json.loads((Path(error.directory) / "run.json").read_text(encoding="utf-8"))
            details["returncode"] = metadata.get("returncode", error.returncode)
        except (OSError, ValueError) as metadata_error:
            details["process_metadata_unavailable"] = str(metadata_error)
    return details


def _github_command(kind, title, message):
    if os.environ.get("GITHUB_ACTIONS") == "true":
        escaped = str(message).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::{kind} title={title}::" + escaped, flush=True)


def _github_error(message):
    _github_command("error", "Recorded failure regression", message)


def _publish_measurement(args, runner, case, identity, actual, diagnostic):
    """Expose strict measurements for review without paths, raw logs, or baseline edits."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    payload = {"case_id": case["case_id"], "engine_version": runner.version,
               "engine_sha256": runner.executable_sha256,
               "platform": platform.system() + "-" + platform.machine(),
               "case_fixture_sha256": sha256_file(args.cases),
               "identity": {key: identity[key] for key in
                            ("problem", "x", "canonical_input_sha256", "input_sha256",
                             "weather_file", "weather_sha256", "numerical_recipe")},
               "objective": actual["objective"], "components": actual["components"],
               "terms": actual["terms"], "severe_count": diagnostic["severe_count"],
               "fatal_count": diagnostic["fatal_count"]}
    _github_command("notice", "Strict repaired measurement",
                    json.dumps(payload, allow_nan=False, separators=(",", ":")))


def _failure_message(item):
    failure = item["failure"]
    message = f"{item['case_id']} [{failure['stage']}]: {failure['message']}"
    original = failure["stage"] == "original-csharp"
    stage = "canonical" if original or failure["stage"].startswith("canonical") else "refined"
    native = item[stage].get("original_csharp_failure" if original else "failure")
    if native:
        message += ("; original C#" if original else
                    f"; native reason={native['reason']}, returncode={native['returncode']}")
        if native.get("diagnostics"):
            message += "; diagnostics=" + json.dumps(native["diagnostics"], ensure_ascii=False)
        if stage == "canonical":
            message += "; reviewed failure=" + json.dumps(item[stage]["expected_failure"], ensure_ascii=False)
        if native.get("diagnostic_excerpt"):
            message += "\n" + native["diagnostic_excerpt"]
        if native.get("completion"):
            message += "\ncompletion=" + native["completion"]
    return message


def _read_cases(args):
    fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    identifiers = [case["case_id"] for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Failure fixture contains duplicate case IDs")
    if any(case["version"] not in {"8.5.0", "26.2.0"} for case in cases):
        raise ValueError("Failure fixture contains an unsupported engine version")
    selected = [case for case in cases if case["version"] == args.version]
    if not selected:
        raise ValueError("Failure fixture contains no cases for this engine")
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    if (baseline.get("engine_version") != args.version
            or baseline.get("weather_kind") != "canonical"
            or baseline.get("diagnostics_policy") != "strict"
            or baseline.get("numerical_variant") != VARIANT):
        raise ValueError("Baseline engine, weather, diagnostics, or numerical variant changed")
    if baseline.get("case_fixture", {}).get("sha256") != sha256_file(args.cases):
        raise ValueError("Baseline failure-fixture SHA256 changed")
    rows = {row["case_id"]: row for row in baseline["cases"]}
    if len(rows) != len(baseline["cases"]) or set(rows) != {c["case_id"] for c in selected}:
        raise ValueError("Baseline must contain exactly every failure case for this engine")
    return selected, rows


def _same_inputs(model, weather, model_hash, weather_hash):
    if sha256_file(model) != model_hash or sha256_file(weather) != weather_hash:
        raise AssertionError("Simulation input/weather bytes changed during execution")


def _baseline_identity(case, previous, problem, model_hash, weather_hash):
    identity = {"problem": case["problem"], "x": case["x"],
                "canonical_input_sha256": case["input_sha256"],
                "input_sha256": model_hash, "weather_file": case["weather_file"],
                "weather_sha256": weather_hash,
                "numerical_recipe": problem.provenance["numerical_variant"]}
    changed = [f"{key}: actual={value!r}, expected={previous.get(key)!r}"
               for key, value in identity.items() if previous.get(key) != value]
    if changed:
        raise AssertionError("Reviewed repair identity changed: " + "; ".join(changed))
    if (previous.get("passed") is not True or previous.get("severe_count") != 0
            or previous.get("fatal_count") != 0):
        raise AssertionError("Reviewed repair baseline is not a strict successful simulation")
    return identity


def _strict_success(run, runner, model_hash, weather_hash):
    diagnostic = reference_validation.failure_diagnostics(run.directory)
    if diagnostic["severe_count"] or diagnostic["fatal_count"]:
        raise AssertionError("Repaired simulation contains Severe/Fatal diagnostics")
    completion = (run.directory / "eplusout.end").read_text(errors="replace")
    summary = re.search(r"EnergyPlus Completed Successfully--\s*\d+\s+Warnings?;\s*(\d+)\s+Severe Errors?",
                        completion, re.I)
    if (run.returncode != 0 or summary is None or int(summary.group(1)) != 0
            or run.version != runner.version or run.executable_sha256 != runner.executable_sha256
            or run.input_sha256 != model_hash or run.weather_sha256 != weather_hash):
        raise AssertionError("Repaired simulation completion or provenance changed")
    metadata = json.loads((run.directory / "run.json").read_text(encoding="utf-8"))
    staged = Path(metadata["input_file"]).resolve(strict=True)
    expected = {"status": "success", "returncode": 0, "version": runner.version,
                "input_sha256": model_hash, "weather_sha256": weather_hash,
                "executable_sha256": runner.executable_sha256}
    if (any(metadata.get(key) != value for key, value in expected.items())
            or staged.parent != run.directory.resolve() or sha256_file(staged) != model_hash
            or sha256_file(runner.executable) != runner.executable_sha256):
        raise AssertionError("Retained repaired simulation input/engine provenance changed")
    return diagnostic


def _actual_values(problem, x, run):
    components = dict(extract_outputs(problem.family, run))
    terms = dict(problem.objective_terms(x, components))
    value = problem.outer_loss(x, components)
    actual = {"objective": value, "components": components, "terms": terms}
    for group, values in actual.items():
        values = {"objective": values} if group == "objective" else values
        if not values:
            raise AssertionError(f"Missing repaired {group} values")
        for key, number in values.items():
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise AssertionError(f"Nonfinite or nonnumeric repaired {group}.{key}")
    return actual


def _compare(problem, actual, previous):
    comparisons = {}
    for group, values in actual.items():
        values = {"objective": values} if group == "objective" else values
        expected = {"objective": previous[group]} if group == "objective" else previous[group]
        if values.keys() != expected.keys():
            raise AssertionError(f"Reviewed repair {group} schema changed")
        for key, number in values.items():
            comparisons[f"{group}.{key}"] = reference_validation.numerical_difference(
                number, expected[key], problem.objective_unit if group == "objective" else "component",
                rtol=RTOL, atol=ATOL)
    return comparisons


def _validate_case(args, runner, case, previous, item):
    item["stage"] = "preparation"
    canonical = get_problem(case["problem"], numerical_variant=None)
    repaired = get_problem(case["problem"], numerical_variant=VARIANT)
    canonical.validate(case["x"])
    weather = (args.weather_dir / case["weather_file"]).resolve(strict=True)
    weather_hash = sha256_file(weather)
    if canonical.weather_filename != weather.name or weather_hash != case["weather_sha256"]:
        raise AssertionError(f"Recorded canonical weather changed: actual={weather.name}/{weather_hash}, "
                             f"expected={canonical.weather_filename}/{case['weather_sha256']}")
    case_dir = args.work_dir / case["case_id"]
    case_dir.mkdir(parents=True, exist_ok=False)
    suffix = ".idf" if args.version == "8.5.0" else ".epJSON"
    def render(problem, name):
        method = problem.render_legacy if args.version == "8.5.0" else problem.render_modern
        return method(case["x"], case_dir / (name + suffix))
    original_model = render(canonical, "canonical")
    original_hash = sha256_file(original_model)
    if original_hash != case["input_sha256"]:
        raise AssertionError(f"Recorded canonical input SHA256 changed: actual={original_hash}, "
                             f"expected={case['input_sha256']}")
    model = render(repaired, "repaired")
    model_hash = sha256_file(model)
    identity = _baseline_identity(case, previous, repaired, model_hash, weather_hash)
    item["refined"].update(identity)
    item["stage"] = "canonical-simulation"
    item["canonical"]["expected_failure"] = case["expected_failure"]
    try:
        runner.run(original_model, weather, design_day=canonical.design_day)
    except EnergyPlusError as error:
        item["canonical"]["failure"] = _native_failure(error)
        _same_inputs(original_model, weather, case["input_sha256"], weather_hash)
        diagnostic, elapsed = reference_validation.require_native_failure(
            error, runner, original_model, weather, case["expected_failure"])
        item["canonical"].update(failure_reference_matched=True, diagnostics=diagnostic,
                                 elapsed_seconds=elapsed)
    else:
        raise AssertionError("Recorded canonical failure became successful; explicit review required")
    if getattr(args, "oracle", None) is not None:
        item["stage"] = "original-csharp"
        try:
            reference_validation._compare_oracle(
                canonical, case["x"], weather, original_model, case_dir, args, runner,
                item["canonical"], expected_failure=case["expected_failure"])
        except Exception as error:
            archive = case_dir / "original-output"
            context = {"type": type(error).__name__, "message": str(error),
                       "archive_available": archive.is_dir()}
            if context["archive_available"]:
                context.update(_diagnostic_context(archive))
            item["canonical"]["original_csharp_failure"] = context
            raise
        item["canonical"]["original_csharp_checked"] = True
    item["stage"] = "refined-simulation"
    try:
        run = runner.run(model, weather, design_day=repaired.design_day)
    except EnergyPlusError as error:
        item["refined"]["failure"] = _native_failure(error)
        raise
    _same_inputs(model, weather, model_hash, weather_hash)
    item["stage"] = "refined-diagnostics"
    diagnostic = _strict_success(run, runner, model_hash, weather_hash)
    item["stage"] = "refined-values"
    actual = _actual_values(repaired, case["x"], run)
    item["refined"].update(actual, diagnostics=diagnostic, elapsed_seconds=run.elapsed)
    _publish_measurement(args, runner, case, identity, actual, diagnostic)
    comparisons = _compare(repaired, actual, previous)
    item["refined"]["comparison"] = comparisons
    differences = []
    for key, result in comparisons.items():
        if not result["passed"]:
            percentage = result["percentage_difference"]
            percentage = f"{percentage:+.9g}%" if percentage is not None else "undefined"
            differences.append(f"{key}: actual={result['actual']:.17g}, expected={result['expected']:.17g}, "
                               f"signed difference={result['signed_difference']:+.17g}, "
                               f"percentage={percentage}, allowed difference={result['allowed_difference']:.9g}")
    if differences:
        raise AssertionError("Repaired values differ from reviewed baseline: " + "; ".join(differences))
    item["passed"] = True


def validate(args):
    """Write an auditable report even when preparation or a native replay fails."""
    report = {"schema_version": 1, "engine_version": args.version, "weather_kind": "canonical",
              "numerical_variant": VARIANT, "diagnostics_policy": "strict",
              "rtol": RTOL, "atol": ATOL, "cases": [], "passed": False}
    try:
        oracle, proxy = getattr(args, "oracle", None), getattr(args, "proxy", None)
        if bool(oracle) != bool(proxy) or (oracle is not None and args.version != "8.5.0"):
            raise ValueError("The C# comparison requires both --oracle and --proxy, and EnergyPlus 8.5.0")
        cases, baseline = _read_cases(args)
        args.work_dir = args.work_dir.resolve()
        runner = EnergyPlusRunner(args.engine, expected_version=args.version, timeout=args.timeout,
                                  output_root=args.work_dir, cache=False)
        report.update(engine_sha256=runner.executable_sha256, case_fixture_sha256=sha256_file(args.cases),
                      baseline_sha256=sha256_file(args.baseline),
                      original_csharp_requested=oracle is not None, original_csharp_checked=False)
        for case in cases:
            item = {"case_id": case["case_id"], "problem": case["problem"], "x": case["x"],
                    "passed": False, "canonical": {"objective": None, "components": None,
                                                   "terms": None, "failure_reference_matched": False},
                    "refined": {"objective": None, "components": None, "terms": None}}
            try:
                _validate_case(args, runner, case, baseline[case["case_id"]], item)
            except Exception as error:
                item["failure"] = {"type": type(error).__name__, "message": str(error),
                                   "stage": item.get("stage", "preparation")}
                _github_error(_failure_message(item))
            report["cases"].append(item)
            print(f"{case['case_id']}: {'PASS' if item['passed'] else 'FAIL'}", flush=True)
        report["original_csharp_checked"] = oracle is not None and all(
            item["canonical"].get("original_csharp_checked", False) for item in report["cases"])
        if not all(item["passed"] for item in report["cases"]):
            raise AssertionError("Recorded replication failure/repair validation failed")
        report["passed"] = True
    except BaseException as error:
        report["failure"] = {"type": type(error).__name__, "message": str(error)}
        if not report["cases"]:
            _github_error(f"Preparation failed: {error}")
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as handle:
                handle.write(f"### Recorded replication failures — EnergyPlus {args.version}\n\n"
                             f"**{'PASS' if report['passed'] else 'FAIL'}**: "
                             f"{sum(row['passed'] for row in report['cases'])}/{len(report['cases'])} "
                             "canonical failure signatures and strict numerical repairs verified.\n\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--version", choices=("8.5.0", "26.2.0"), required=True)
    parser.add_argument("--weather-dir", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=ROOT / "reference/replication-failure-cases.json")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, help="Unchanged original C# launcher (8.5 only)")
    parser.add_argument("--proxy", type=Path, help="Retain the C# native diagnostics and generated input")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300)
    return validate(parser.parse_args(argv))


if __name__ == "__main__":
    main()
