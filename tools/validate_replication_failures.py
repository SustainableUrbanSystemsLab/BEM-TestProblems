"""Replay recorded replication failures, then verify their explicit numerical repair.

Canonical failures remain rejected. The separately named convergence-refined
models must complete without Severe/Fatal errors and match reviewed values.
This command never generates or updates its mandatory baseline.
"""

import argparse
import json
import math
import os
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
RTOL, ATOL = 1e-6, 1e-7


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
    if any(previous.get(key) != value for key, value in identity.items()):
        raise AssertionError("Reviewed repair design, model, weather, or numerical recipe changed")
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


def _compare(problem, x, run, previous):
    components = dict(extract_outputs(problem.family, run))
    terms = dict(problem.objective_terms(x, components))
    value = problem.outer_loss(x, components)
    actual = {"objective": value, "components": components, "terms": terms}
    comparisons = {}
    for group, values in actual.items():
        values = {"objective": values} if group == "objective" else values
        expected = {"objective": previous[group]} if group == "objective" else previous[group]
        if not values or values.keys() != expected.keys():
            raise AssertionError(f"Reviewed repair {group} schema changed")
        for key, number in values.items():
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise AssertionError(f"Nonfinite or nonnumeric repaired {group}.{key}")
            comparisons[f"{group}.{key}"] = reference_validation.numerical_difference(
                number, expected[key], problem.objective_unit if group == "objective" else "component",
                rtol=RTOL, atol=ATOL)
    return actual, comparisons


def _validate_case(args, runner, case, previous, item):
    canonical = get_problem(case["problem"])
    repaired = get_problem(case["problem"], numerical_variant=VARIANT)
    canonical.validate(case["x"])
    weather = (args.weather_dir / case["weather_file"]).resolve(strict=True)
    weather_hash = sha256_file(weather)
    if canonical.weather_filename != weather.name or weather_hash != case["weather_sha256"]:
        raise AssertionError("Recorded canonical weather selection or SHA256 changed")
    case_dir = args.work_dir / case["case_id"]
    case_dir.mkdir(parents=True, exist_ok=False)
    suffix = ".idf" if args.version == "8.5.0" else ".epJSON"
    def render(problem, name):
        method = problem.render_legacy if args.version == "8.5.0" else problem.render_modern
        return method(case["x"], case_dir / (name + suffix))
    original_model = render(canonical, "canonical")
    if sha256_file(original_model) != case["input_sha256"]:
        raise AssertionError("Recorded canonical input SHA256 changed")
    model = render(repaired, "repaired")
    model_hash = sha256_file(model)
    identity = _baseline_identity(case, previous, repaired, model_hash, weather_hash)
    item["refined"].update(identity)
    try:
        runner.run(original_model, weather, design_day=canonical.design_day)
    except EnergyPlusError as error:
        _same_inputs(original_model, weather, case["input_sha256"], weather_hash)
        diagnostic, elapsed = reference_validation.require_native_failure(
            error, runner, original_model, weather, case["expected_failure"])
        item["canonical"].update(failure_reference_matched=True, diagnostics=diagnostic,
                                 elapsed_seconds=elapsed)
    else:
        raise AssertionError("Recorded canonical failure became successful; explicit review required")
    if getattr(args, "oracle", None) is not None:
        reference_validation._compare_oracle(
            canonical, case["x"], weather, original_model, case_dir, args, runner,
            item["canonical"], expected_failure=case["expected_failure"])
        item["canonical"]["original_csharp_checked"] = True
    run = runner.run(model, weather, design_day=repaired.design_day)
    _same_inputs(model, weather, model_hash, weather_hash)
    diagnostic = _strict_success(run, runner, model_hash, weather_hash)
    actual, comparisons = _compare(repaired, case["x"], run, previous)
    item["refined"].update(actual, diagnostics=diagnostic, elapsed_seconds=run.elapsed,
                           comparison=comparisons)
    if not all(result["passed"] for result in comparisons.values()):
        raise AssertionError("Repaired objective, components, or terms differ from reviewed baseline")
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
                item["failure"] = {"type": type(error).__name__, "message": str(error)}
            report["cases"].append(item)
            print(f"{case['case_id']}: {'PASS' if item['passed'] else 'FAIL'}", flush=True)
        report["original_csharp_checked"] = oracle is not None and all(
            item["canonical"].get("original_csharp_checked", False) for item in report["cases"])
        if not all(item["passed"] for item in report["cases"]):
            raise AssertionError("Recorded replication failure/repair validation failed")
        report["passed"] = True
    except BaseException as error:
        report["failure"] = {"type": type(error).__name__, "message": str(error)}
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
