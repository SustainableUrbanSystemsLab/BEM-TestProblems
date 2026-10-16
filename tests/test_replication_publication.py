# SPDX-License-Identifier: MIT
"""Retained replays gate public exports without native simulation in these tests."""

import copy
import hashlib
import json
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from bem_testproblems import get_problem
from bem_testproblems.replication import _seed, paired_start
from bem_testproblems.replication_solvers import solver_metadata
from tools import export_replication as export
from tools import replay_replication as replay
from tools.review_replication import load_review

STAGED_INPUT = b"fixture rendered input\n"
INPUT_SHA256 = hashlib.sha256(STAGED_INPUT).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    replay._write(path, value)


@pytest.fixture
def campaign(tmp_path):
    origin, project, frozen = (tmp_path / name for name in ("origin", "project", "frozen"))
    package = frozen / "src/bem_testproblems"
    package.mkdir(parents=True)
    (package / "replication.py").write_text("# frozen simulator fixture\n")
    problem = get_problem(13)
    specifications = [
        {
            "id": f"p13-{version}-bobyqa-r000",
            "problem": 13,
            "version": version,
            "solver": "bobyqa",
            "repetition": 0,
            "seed": _seed(2019, "solver", 13, 0, "bobyqa"),
            "x0": list(paired_start(problem, 0, 2019)),
            "budget": 1100,
        }
        for version in ("8.5.0", "26.2.0")
    ]
    engines = {}
    for version in ("8.5.0", "26.2.0"):
        engine = (
            project
            / ".tools/energyplus"
            / version
            / ("energyplus.exe" if sys.platform == "win32" else "energyplus")
        )
        engine.parent.mkdir(parents=True)
        engine.write_bytes(b"fake-native-engine-never-executed")
        (engine.parent / "Energy+.idd").write_bytes(b"fake-support")
        engines[version] = {"executable": str(engine), "executable_sha256": replay._hash(engine)}
    definition = {
        "name": problem.name,
        "dimension": problem.dimension,
        "bounds": [list(pair) for pair in problem.bounds],
        "parameter_names": [parameter.name for parameter in problem.parameters],
        "objective_unit": problem.objective_unit,
        "weather": {"mode": "embedded-design-day", "filename": None, "sha256": None},
        "models": {version: {"template_sha256": "a" * 64} for version in engines},
    }
    manifest = {
        "runs": specifications,
        "platform": "Windows-AMD64",
        "project_root": str(project),
        "weather_directory": str(project / ".cache/weather"),
        "protocol": "pilot-overrides",
        "requested_repetitions": 1,
        "budget_override": 1100,
        "master_seed": 2019,
        "diagnostics_policy": "strict",
        "solvers": {"bobyqa": solver_metadata("bobyqa")},
        "schedule": "balanced",
        "problem_definitions": {"13": definition},
        "engines": engines,
        "code_sha256": {"replication.py": replay._hash(package / "replication.py")},
        "dependency_provenance": {
            "numpy": {"distribution_version": "1.26.4", "runtime_version": "1.26.4"}
        },
        "host": "PRIVATE-HOST",
        "unrelated_private_text": "DO-NOT-PUBLISH",
    }
    manifest["manifest_id"] = replay.continuation._digest(manifest)
    write(origin / "manifest.json", manifest)
    for spec in specifications:
        item = {
            "evaluation": 1,
            "status": "success",
            "x": spec["x0"],
            "f": 10.0,
            "components": {"heating": 2.0, "cooling": 8.0},
            "input_sha256": INPUT_SHA256,
            "strict_benchmark_evaluation": True,
            "diagnostics": {"severe_count": 0, "fatal_count": 0},
        }
        record = {
            **spec,
            "manifest_id": manifest["manifest_id"],
            "status": "completed",
            "best_x": spec["x0"],
            "best_f": 10.0,
            "evaluation_count": 1,
            "strict_benchmark_evaluation": True,
            "warmup_severe_evaluations_used": 0,
            "trace": [item],
            "problem_provenance": definition,
            "engine_provenance": engines[spec["version"]],
            "solver_metadata": manifest["solvers"]["bobyqa"],
        }
        write(origin / "runs" / (spec["id"] + ".json"), record)
    return SimpleNamespace(
        origin=origin,
        project=project,
        frozen=frozen,
        manifest=manifest,
        dataset=load_review(origin),
        tmp=tmp_path,
    )


def plan(campaign, **kwargs):
    return replay.prepare_replay(
        campaign.dataset,
        origin=campaign.origin,
        frozen_source=campaign.frozen,
        project_root=campaign.project,
        output_dir=campaign.tmp / "replay",
        **kwargs,
    )


def fake_native(command, *, stdout, stderr, check):
    assert command[0] == sys.executable and command[1] == "-B" and command[-2] == "--worker"
    assert stderr == subprocess.STDOUT and not check
    request = json.loads(Path(command[-1]).read_text())
    incumbent, saved_plan = request["incumbent"], request["plan"]
    directory = Path(request["output_directory"]) / "simulations/fake"
    directory.mkdir(parents=True)
    for name, text in (
        ("eplusout.err", "EnergyPlus Completed Successfully-- 0 Warning\n"),
        ("eplusout.end", "EnergyPlus Completed Successfully\n"),
    ):
        (directory / name).write_text(text)
    engine = saved_plan["engines"][incumbent["version"]]
    version_output = "Version " + incumbent["version"]
    staged = directory / ("input.idf" if incumbent["version"] == "8.5.0" else "input.epJSON")
    staged.write_bytes(STAGED_INPUT)
    write(
        directory / "run.json",
        {
            "status": "success",
            "returncode": 0,
            "version": incumbent["version"],
            "version_output": version_output,
            "executable": engine["executable"],
            "executable_sha256": engine["executable_sha256"],
            "input_sha256": INPUT_SHA256,
            "input_file": str(staged),
            "weather_sha256": None,
            "command": [engine["executable"], "-D", str(staged)],
            "local_path": "PRIVATE-RAW-EVIDENCE",
        },
    )
    definition = saved_plan["problem_definitions"][str(incumbent["problem"])]
    result = {
        "passed": True,
        "actual_f": incumbent["f"],
        "actual_components": incumbent["components"],
        "severe_count": 0,
        "fatal_count": 0,
        "completed_successfully": True,
        "input_sha256": incumbent["input_sha256"],
        "simulation_directory": str(directory),
        "engine": {**engine, "version_output": version_output},
        "model": definition["models"][incumbent["version"]],
        "weather": definition["weather"],
        "diagnostic_sha256": {
            name: replay._hash(directory / name)
            for name in ("eplusout.err", "eplusout.end", "run.json")
        },
    }
    write(Path(request["output_directory"]) / "worker-result.json", result)
    return SimpleNamespace(returncode=0)


def toy_runtime(campaign, scenario="good"):
    """A dependency-free frozen simulator substitute, never an EnergyPlus executable."""
    body = textwrap.dedent("""\
        import hashlib
        import json
        from pathlib import Path
        from types import SimpleNamespace

        SCENARIO = SCENARIO_VALUE

        def get_problem(number, numerical_variant=None):
            return SimpleNamespace(family="fixture")

        def _model_identity(problem, version):
            return {"template_sha256": ("c" if SCENARIO == "model" else "a") * 64}

        def _weather_identity(problem, directory):
            return {"mode": "embedded-design-day", "filename": None, "sha256": None}

        class EnergyPlusRunner:
            def __init__(self, executable, *, expected_version, output_root, cache):
                assert cache is False
                self.output_root = Path(output_root)
                self.output_root.mkdir(parents=True)
                self.version_output = "Version " + expected_version
                self.executable, self.version = executable, expected_version

        class _ObservedRunner:
            def __init__(self, runner):
                self.runner, self.last = runner, None

        def make_objective(problem, *, runner, weather_dir):
            def objective(x):
                if SCENARIO == "missing-output":
                    return 10.0
                directory = runner.runner.output_root / "fake-native-evidence"
                directory.mkdir()
                (directory / "eplusout.err").write_text(
                    "** Severe ** fixture" if SCENARIO == "severe" else "no errors")
                (directory / "eplusout.end").write_text("EnergyPlus Completed Successfully")
                engine = runner.runner
                staged = directory / ("input.idf" if engine.version == "8.5.0" else "input.epJSON")
                staged.write_bytes(b"fixture rendered input\\n")
                input_hash = hashlib.sha256(staged.read_bytes()).hexdigest()
                (directory / "run.json").write_text(json.dumps({"status":"success", "returncode":0,
                    "version":engine.version,"version_output":engine.version_output,
                    "executable":engine.executable,"executable_sha256":hashlib.sha256(
                        Path(engine.executable).read_bytes()).hexdigest(),
                    "input_sha256":input_hash,"input_file":str(staged),"weather_sha256":None,
                    "command":[engine.executable,"-D",str(staged)]}))
                runner.last = SimpleNamespace(directory=directory,
                    input_sha256="c" * 64 if SCENARIO == "input" else input_hash)
                return 11.0 if SCENARIO == "objective" else 10.0
            return objective

        def extract_outputs(family, result):
            return {"heating": 3.0 if SCENARIO == "components" else 2.0, "cooling": 8.0}
        """).replace("SCENARIO_VALUE", repr(scenario))
    package = campaign.frozen / "src/bem_testproblems"
    (package / "__init__.py").write_text("")
    (package / "replication.py").write_text(body)
    manifest = campaign.manifest
    old_id = manifest.pop("manifest_id")
    manifest["code_sha256"]["replication.py"] = replay._hash(package / "replication.py")
    manifest["manifest_id"] = replay.continuation._digest(manifest)
    write(campaign.origin / "manifest.json", manifest)
    for path in (campaign.origin / "runs").glob("*.json"):
        row = json.loads(path.read_text())
        assert row["manifest_id"] == old_id
        row["manifest_id"] = manifest["manifest_id"]
        write(path, row)
    campaign.dataset = load_review(campaign.origin)
    module = types.ModuleType("frozen_fixture")
    exec(compile(body, str(package / "replication.py"), "exec"), module.__dict__)
    return module


def test_plan_checks_precise_incumbents_without_import_or_native_execution(campaign, monkeypatch):
    monkeypatch.setattr(replay.continuation, "_load_runtime", lambda *args: pytest.fail("imported"))
    before = {path: replay._hash(path) for path in campaign.origin.rglob("*.json")}
    result = plan(campaign)
    assert len(result["incumbents"]) == 2 and not result["simulation_started"]
    assert result["incumbents"][0]["components"] == {"heating": 2.0, "cooling": 8.0}
    assert result["incumbents"][0]["x"] == campaign.manifest["runs"][0]["x0"]
    assert result["source_manifest_ids"] == [campaign.manifest["manifest_id"]]
    assert not Path(result["output_directory"]).exists()
    assert before == {path: replay._hash(path) for path in campaign.origin.rglob("*.json")}


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "unsafe-source-name",
        "missing-components",
        "nonfinite-components",
        "severe",
        "missing-hash",
        "no-incumbent",
    ],
)
def test_invalid_source_or_incumbent_is_rejected(campaign, mutation):
    record = next(iter(campaign.dataset["records"].values()))
    if mutation == "source":
        (campaign.frozen / "src/bem_testproblems/replication.py").write_text("changed")
    elif mutation == "unsafe-source-name":
        campaign.dataset["origin_manifest"]["code_sha256"] = {"../replication.py": "bad"}
    elif mutation == "missing-components":
        record["trace"][0].pop("components")
    elif mutation == "nonfinite-components":
        record["trace"][0]["components"]["heating"] = float("inf")
    elif mutation == "severe":
        for row in campaign.dataset["records"].values():
            row["trace"][0]["diagnostics"]["severe_count"] = 1
    elif mutation == "missing-hash":
        record["trace"][0].pop("input_sha256")
    else:
        for row in campaign.dataset["records"].values():
            row["status"] = "failed"
    with pytest.raises(ValueError):
        plan(campaign)


@pytest.mark.parametrize("name", ["origin", "frozen", "src", "cache", "existing"])
def test_unsafe_or_existing_destinations_are_rejected(campaign, name):
    destination = {
        "origin": campaign.origin / "output",
        "frozen": campaign.frozen / "output",
        "src": campaign.project / "src/output",
        "cache": campaign.project / ".cache/output",
        "existing": campaign.project,
    }[name]
    with pytest.raises((ValueError, FileExistsError)):
        replay.prepare_replay(
            campaign.dataset,
            origin=campaign.origin,
            frozen_source=campaign.frozen,
            project_root=campaign.project,
            output_dir=destination,
        )


def test_continuation_complete_frozen_package_hash_is_checked(campaign):
    campaign.dataset["manifests"]["new"] = {"continuation": {"frozen_package_sha256": "wrong"}}
    with pytest.raises(ValueError, match="complete package hash"):
        plan(campaign)


def test_output_alias_is_rejected_without_changing_origin(campaign):
    alias = campaign.tmp / "output-alias"
    try:
        alias.symlink_to(campaign.origin, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    before = (campaign.origin / "manifest.json").read_bytes()
    with pytest.raises(ValueError):
        replay.safe_destination(alias, origin=campaign.origin)
    assert (campaign.origin / "manifest.json").read_bytes() == before


def test_replay_retains_portable_evidence_and_rejects_overwrite(campaign):
    configured = plan(campaign)
    result = replay.run_replay(configured, execute=fake_native)
    assert result["passed"] and result["complete"] and len(result["items"]) == 2
    for item in result["items"]:
        assert not Path(item["evidence_directory"]).is_absolute()
        assert (
            Path(configured["output_directory"]) / item["evidence_directory"] / "run.json"
        ).is_file()
    assert export.validated_replay(campaign.dataset, configured["output_directory"])["passed"]
    with pytest.raises(FileExistsError):
        replay.run_replay(configured, execute=fake_native)


def test_real_subprocess_imports_only_the_selected_frozen_fixture(campaign):
    toy_runtime(campaign)
    result = replay.run_replay(plan(campaign))
    assert result["passed"] and all(row["input_matches"] for row in result["items"])
    assert not list(campaign.frozen.rglob("*.pyc"))
    assert export.validated_replay(campaign.dataset, campaign.tmp / "replay")["passed"]


@pytest.mark.parametrize(
    "scenario",
    [
        "good",
        "model",
        "missing-output",
        "severe",
        "objective",
        "components",
        "input",
        "changed-engine",
        "changed-support",
    ],
)
def test_worker_applies_strict_input_component_and_engine_checks(campaign, scenario):
    runtime = toy_runtime(campaign, scenario)
    configured = plan(campaign)
    directory = Path(configured["output_directory"]) / "unit-worker"
    directory.mkdir(parents=True)
    request_path = directory / "request.json"
    write(
        request_path,
        {
            "plan": configured,
            "incumbent": configured["incumbents"][0],
            "output_directory": str(directory),
        },
    )
    engine = Path(configured["engines"][configured["incumbents"][0]["version"]]["executable"])
    if scenario == "changed-engine":
        engine.write_text("changed")
    elif scenario == "changed-support":
        (engine.parent / "Energy+.idd").write_text("changed")
    result = replay._worker(request_path, runtime=runtime)
    assert result["passed"] is (scenario == "good")
    assert (directory / "worker-result.json").is_file()
    with pytest.raises(ValueError, match="already executed"):
        replay._worker(request_path, runtime=runtime)


@pytest.mark.parametrize("failure", ["missing-result", "bad-exit", "os-error"])
def test_replay_records_worker_failures(campaign, failure):
    def execute(*args, **kwargs):
        if failure == "os-error":
            raise OSError("cannot start fixture")
        if failure == "bad-exit":
            fake_native(*args, **kwargs)
        return SimpleNamespace(returncode=3)

    result = replay.run_replay(plan(campaign), execute=execute)
    assert result["complete"] and not result["passed"]
    assert len(result["items"]) == 2 and all(not item["passed"] for item in result["items"])


def test_replay_refuses_modified_plan(campaign):
    configured = plan(campaign)
    configured["incumbents"][0]["x"][0] += 1
    with pytest.raises(ValueError, match="plan digest"):
        replay.run_replay(configured, execute=fake_native)


@pytest.mark.parametrize(
    ("actual", "passed", "percentage"),
    [
        (10.000009, True, 0.00009),
        (10.1, False, 1.0),
        (None, False, None),
        (float("nan"), False, None),
    ],
)
def test_reported_relative_tolerance_and_percentages(actual, passed, percentage):
    result = replay.compare_numbers(10.0, actual)
    assert result["passed"] is passed
    assert (
        result["percentage_difference"] == pytest.approx(percentage)
        if percentage is not None
        else (result["percentage_difference"] is None)
    )
    assert replay.compare_numbers(0.0, 5e-8)["passed"]
    assert replay.compare_numbers(0.0, 5e-8)["percentage_difference"] is None


def test_relative_tolerance_uses_absolute_fallback_instead_of_adding_allowances():
    assert not replay.compare_numbers(10.0, 10.00001005)["passed"]


def test_export_completion_and_replay_gates(campaign):
    with pytest.raises(ValueError, match="replay-dir"):
        export.export_results(
            campaign.dataset, origin=campaign.origin, output_dir=campaign.tmp / "public"
        )
    campaign.dataset["status_counts"]["pending"] = 1
    with pytest.raises(ValueError, match="incomplete"):
        export.export_results(
            campaign.dataset, origin=campaign.origin, output_dir=campaign.tmp / "public"
        )
    assert not (campaign.tmp / "public").exists()


def test_validated_export_is_allowlisted_and_hashed(campaign):
    pytest.importorskip("matplotlib")
    configured = plan(campaign)
    replay.run_replay(configured, execute=fake_native)
    output = campaign.project / "replication/results/test-campaign"
    result = export.export_results(
        campaign.dataset,
        origin=campaign.origin,
        output_dir=output,
        replay_dir=configured["output_directory"],
    )
    assert not result["partial_preview"]
    saved = json.loads((output / "results.json").read_text())
    assert saved["campaign_complete"] and saved["replay"]["passed"]
    experiment = saved["experiment"]
    assert experiment["runs"] == campaign.manifest["runs"]
    assert experiment["master_seed"] == 2019 and experiment["requested_repetitions"] == 1
    assert experiment["budget_override"] == 1100 and experiment["numerical_variants"] == {
        "13": None
    }
    assert experiment["solvers"]["bobyqa"]["settings"] == solver_metadata("bobyqa")["settings"]
    winner = saved["best_across_methods"][0]["winner"]
    specification = next(spec for spec in experiment["runs"] if spec["id"] == winner["run_id"])
    assert all(winner[key] == specification[key] for key in ("seed", "budget", "x0", "repetition"))
    assert winner["evaluation_count"] == 1
    assert saved["best_across_methods"][0]["winner"]["x"] == campaign.manifest["runs"][0]["x0"]
    assert (output / "plots/figure9-energyplus-8.5.0.svg").is_file()
    assert not list(output.rglob("*.idf")) and not list(output.rglob("*.epw"))
    for path in output.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".md", ".svg"}:
            text = path.read_text()
            for secret in (
                str(campaign.tmp),
                "PRIVATE-HOST",
                "DO-NOT-PUBLISH",
                "PRIVATE-RAW-EVIDENCE",
            ):
                assert secret not in text
    inventory = json.loads((output / "inventory.json").read_text())
    assert all(
        replay._hash(output / name) == expected for name, expected in inventory["files"].items()
    )
    verification = export.verify_export(output)
    assert verification["integrity_passed"] and verification["validated_result_stamp"]


def extend_campaign(campaign):
    manifest = campaign.manifest
    manifest.update(protocol="extended-budget-experiment", budget_override=None,
                    budget_multiplier=100,
                    effective_budget_rule="100*(dimension+1)*budget_multiplier")
    for spec in manifest["runs"]:
        spec["budget"] = 110_000
    del manifest["manifest_id"]
    manifest["manifest_id"] = replay.continuation._digest(manifest)
    write(campaign.origin / "manifest.json", manifest)
    for path in (campaign.origin / "runs").glob("*.json"):
        record = json.loads(path.read_text())
        record.update(manifest_id=manifest["manifest_id"], budget=110_000)
        write(path, record)
    campaign.dataset = load_review(campaign.origin)


def test_extended_budget_export_replays_and_verifies_the_full_recipe(campaign):
    pytest.importorskip("matplotlib")
    extend_campaign(campaign)
    configured = plan(campaign)
    replay.run_replay(configured, execute=fake_native)
    output = campaign.tmp / "public-extended"
    export.export_results(campaign.dataset, origin=campaign.origin, output_dir=output,
                          replay_dir=configured["output_directory"])
    result = json.loads((output / "results.json").read_text())
    experiment = result["experiment"]
    assert experiment["protocol"] == "extended-budget-experiment"
    assert experiment["budget_multiplier"] == 100 and experiment["budget_override"] is None
    assert experiment["budget_rule"] == "100*(dimension+1)*budget_multiplier"
    assert all(spec["budget"] == 110_000 for spec in experiment["runs"])
    svg = (output / "plots/figure9-energyplus-8.5.0.svg").read_text(encoding="utf-8")
    assert "EXTENDED BUDGET" in svg and "100 × 100(n+1)" in svg
    assert export.verify_export(output)["validated_result_stamp"]


@pytest.mark.parametrize("mutation", [
    "missing-multiplier", "bool-multiplier", "unit-multiplier", "changed-multiplier",
    "override", "rule", "budget", "paper-label",
])
def test_extended_budget_recipe_rejects_inconsistent_caps_and_labels(campaign, mutation):
    extend_campaign(campaign)
    experiment = export._public_experiment(campaign.dataset)
    result = {"experiment": experiment, "planned_runs": 2,
              "provenance": [{"engines": {"8.5.0": {}, "26.2.0": {}}}]}
    export._verify_experiment(result)
    if mutation == "missing-multiplier":
        del experiment["budget_multiplier"]
    elif mutation == "bool-multiplier":
        experiment["budget_multiplier"] = True
    elif mutation == "unit-multiplier":
        experiment["budget_multiplier"] = 1
    elif mutation == "changed-multiplier":
        experiment["budget_multiplier"] = 101
    elif mutation == "override":
        experiment["budget_override"] = 110_000
    elif mutation == "rule":
        experiment["budget_rule"] = "100*(dimension+1)"
    elif mutation == "budget":
        experiment["runs"][0]["budget"] -= 1
    else:
        experiment["protocol"] = "paper-start-and-budget-protocol"
    with pytest.raises(ValueError):
        export._verify_experiment(result)


def test_public_plots_use_canonical_labels_and_record_cross_build_scope(campaign):
    pytest.importorskip("matplotlib")
    original = campaign.dataset["origin_manifest"]
    original["platform"] = "PRIVATE-HOST"
    original["problem_definitions"]["13"]["name"] = "DO-NOT-PUBLISH"
    original["engines"]["26.2.0"]["executable_sha256"] = "d" * 64
    configured = plan(campaign)
    replay.run_replay(configured, execute=fake_native)
    output = campaign.tmp / "public"
    export.export_results(
        campaign.dataset,
        origin=campaign.origin,
        output_dir=output,
        replay_dir=configured["output_directory"],
    )
    saved = json.loads((output / "results.json").read_text())
    modern = next(item for item in saved["replay"]["items"] if item["version"] == "26.2.0")
    assert modern["replay_scope"] == "same-version-different-native-build"
    assert modern["source_engine_executable_sha256"] == "d" * 64
    for path in (output / "plots").glob("*.svg"):
        assert "PRIVATE-HOST" not in path.read_text() and "DO-NOT-PUBLISH" not in path.read_text()
    assert export.verify_export(output)["validated_result_stamp"]


def test_partial_preview_is_conspicuously_unvalidated(campaign):
    pytest.importorskip("matplotlib")
    campaign.dataset["records"].pop(next(iter(campaign.dataset["records"])))
    campaign.dataset["status_counts"] = {"completed": 1, "pending": 1}
    output = campaign.tmp / "preview"
    export.export_results(
        campaign.dataset,
        origin=campaign.origin,
        output_dir=output,
        partial_preview=True,
        frozen_source=campaign.frozen,
    )
    saved = json.loads((output / "results.json").read_text())
    assert saved["partial_preview"] and not saved["campaign_complete"] and saved["replay"] is None
    assert "UNVALIDATED PARTIAL PREVIEW" in (output / "README.md").read_text()
    assert "UNVALIDATED PARTIAL PREVIEW" in saved["status"]
    with pytest.raises(ValueError, match="Preview is unvalidated"):
        export.verify_export(output)
    assert not export.verify_export(output, allow_partial_preview=True)["validated_result_stamp"]


@pytest.mark.parametrize("mutation", ["extra-file", "changed-file", "gates", "comparisons"])
def test_public_integrity_check_rejects_file_and_recorded_gate_changes(campaign, mutation):
    pytest.importorskip("matplotlib")
    configured = plan(campaign)
    replay.run_replay(configured, execute=fake_native)
    output = campaign.tmp / "public"
    export.export_results(
        campaign.dataset,
        origin=campaign.origin,
        output_dir=output,
        replay_dir=configured["output_directory"],
    )
    if mutation == "extra-file":
        (output / "private-weather.epw").write_text("forbidden")
    elif mutation == "changed-file":
        (output / "README.md").write_text("changed")
    else:
        result = json.loads((output / "results.json").read_text())
        if mutation == "gates":
            result["campaign_complete"] = False
        else:
            result["replay"]["items"][0]["actual_f"] = 9999.0
        write(output / "results.json", result)
        inventory = json.loads((output / "inventory.json").read_text())
        inventory["files"]["results.json"] = replay._hash(output / "results.json")
        write(output / "inventory.json", inventory)
    with pytest.raises(ValueError):
        export.verify_export(output)


@pytest.mark.parametrize(
    "mutation",
    [
        "stale-winner",
        "summary-failed",
        "duplicate",
        "objective",
        "component",
        "severe",
        "input",
        "diagnostic",
        "escape",
    ],
)
def test_export_rejects_stale_or_changed_replay_evidence(campaign, mutation):
    configured = plan(campaign)
    replay.run_replay(configured, execute=fake_native)
    directory = Path(configured["output_directory"])
    summary_path = directory / "replay-summary.json"
    summary = json.loads(summary_path.read_text())
    item = summary["items"][0]
    if mutation == "stale-winner":
        row = next(iter(campaign.dataset["records"].values()))
        row["best_f"] = row["trace"][0]["f"] = 9.0
    elif mutation == "summary-failed":
        summary["passed"] = False
    elif mutation == "duplicate":
        summary["items"][1] = copy.deepcopy(item)
    elif mutation == "objective":
        item["actual_f"] = 50.0
    elif mutation == "component":
        item["actual_components"]["heating"] = 4.0
    elif mutation == "severe":
        item["severe_count"] = 1
    elif mutation == "input":
        item["input_sha256"] = "f" * 64
    elif mutation == "diagnostic":
        (directory / item["evidence_directory"] / "eplusout.err").write_text("changed")
    else:
        item["evidence_directory"] = "../../escape"
    write(summary_path, summary)
    with pytest.raises(ValueError):
        export.validated_replay(campaign.dataset, directory)


@pytest.mark.parametrize(
    "mutation",
    [
        "engine-hash",
        "supporting-hash",
        "model",
        "weather",
        "run-status",
        "run-returncode",
        "run-version",
        "run-engine",
        "run-weather",
        "run-unrelated",
        "staged-input",
        "plan-model",
    ],
)
def test_raw_replay_gate_binds_native_execution_and_staged_input(campaign, mutation):
    configured = plan(campaign)
    replay.run_replay(configured, execute=fake_native)
    directory = Path(configured["output_directory"])
    summary = json.loads((directory / "replay-summary.json").read_text())
    item = summary["items"][0]
    evidence = directory / item["evidence_directory"]
    metadata = json.loads((evidence / "run.json").read_text())
    if mutation == "engine-hash":
        item["engine"]["executable_sha256"] = "d" * 64
    elif mutation == "supporting-hash":
        item["engine"]["supporting_sha256"]["Energy+.idd"] = "d" * 64
    elif mutation == "model":
        item["model"]["template_sha256"] = "d" * 64
    elif mutation == "weather":
        item["weather"]["mode"] = "unrelated"
    elif mutation == "run-status":
        metadata["status"] = "failed"
    elif mutation == "run-returncode":
        metadata["returncode"] = 1
    elif mutation == "run-version":
        metadata["version"] = "1.0.0"
    elif mutation == "run-engine":
        metadata["executable_sha256"] = "d" * 64
    elif mutation == "run-weather":
        metadata["weather_sha256"] = "d" * 64
    elif mutation == "run-unrelated":
        metadata = {"fixture": True}
    elif mutation == "staged-input":
        (evidence / ("input.idf" if item["version"] == "8.5.0" else "input.epJSON")).write_text(
            "changed"
        )
    else:
        configured["problem_definitions"]["13"]["models"][item["version"]]["template_sha256"] = (
            "d" * 64
        )
        configured.pop("plan_id")
        configured["plan_id"] = replay.continuation._digest(configured)
        summary["plan_id"] = configured["plan_id"]
        write(directory / "replay-plan.json", configured)
    write(evidence / "run.json", metadata)
    item["diagnostic_sha256"]["run.json"] = replay._hash(evidence / "run.json")
    write(directory / "replay-summary.json", summary)
    with pytest.raises(ValueError):
        export.validated_replay(campaign.dataset, directory)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra-top",
        "extra-winner",
        "extra-provenance",
        "out-of-bounds-x",
        "changed-within-bounds-x",
        "per-solver-mismatch",
        "parameter-label",
        "comparison-percent",
    ],
)
def test_public_schema_and_vectors_remain_bound_after_inventory_update(campaign, mutation):
    pytest.importorskip("matplotlib")
    configured = plan(campaign)
    replay.run_replay(configured, execute=fake_native)
    output = campaign.tmp / "public"
    export.export_results(
        campaign.dataset,
        origin=campaign.origin,
        output_dir=output,
        replay_dir=configured["output_directory"],
    )
    result = json.loads((output / "results.json").read_text())
    winner = result["best_across_methods"][0]["winner"]
    if mutation == "extra-top":
        result["accidental_private_path"] = "/Users/PRIVATE_USER/private-weather.epw"
    elif mutation == "extra-winner":
        winner["private_note"] = "private text"
    elif mutation == "extra-provenance":
        result["provenance"][0]["python_executable"] = "/private/python"
    elif mutation == "out-of-bounds-x":
        winner["x"][0] = 1e100
    elif mutation == "changed-within-bounds-x":
        winner["x"][0] += 0.01
        result["best_per_solver"][0]["winner"]["x"][0] += 0.01
    elif mutation == "per-solver-mismatch":
        result["best_per_solver"][0]["winner"]["f"] = 9.0
    elif mutation == "parameter-label":
        winner["parameter_names"][0] = "/private/input"
    else:
        result["replay"]["items"][0]["objective_comparison"]["percentage_difference"] = 999.0
    write(output / "results.json", result)
    inventory = json.loads((output / "inventory.json").read_text())
    inventory["files"]["results.json"] = replay._hash(output / "results.json")
    write(output / "inventory.json", inventory)
    with pytest.raises(ValueError):
        export.verify_export(output)


def test_sanitized_python_provenance_omits_private_runtime_strings(campaign):
    campaign.dataset["origin_manifest"]["execution_runtime"] = {
        "python_version": "3.12.12 (PRIVATE-COMPILER-DETAILS)",
        "python_implementation": "cpython",
        "python_executable_sha256": "e" * 64,
        "os_identity": "PRIVATE-HOST",
    }
    source = export._public_provenance(campaign.dataset)[0]
    assert source["python"] == {
        "version": "3.12.12",
        "implementation": "CPython",
        "executable_sha256": "e" * 64,
    }
    assert "PRIVATE" not in json.dumps(source)


@pytest.mark.parametrize(
    "mutation",
    [
        "master-seed",
        "run-seed",
        "start",
        "budget",
        "solver-settings",
        "variant",
        "repetitions",
        "winner-seed",
        "winner-calls",
        "extra-spec-field",
        "duplicate-spec",
        "schedule",
    ],
)
def test_exported_experiment_recipe_rejects_inconsistent_protocol(campaign, mutation):
    pytest.importorskip("matplotlib")
    configured = plan(campaign)
    replay.run_replay(configured, execute=fake_native)
    output = campaign.tmp / "public"
    export.export_results(
        campaign.dataset,
        origin=campaign.origin,
        output_dir=output,
        replay_dir=configured["output_directory"],
    )
    result = json.loads((output / "results.json").read_text())
    experiment = result["experiment"]
    if mutation == "master-seed":
        experiment["master_seed"] += 1
    elif mutation == "run-seed":
        experiment["runs"][0]["seed"] += 1
    elif mutation == "start":
        experiment["runs"][0]["x0"][0] = 1e100
    elif mutation == "budget":
        experiment["runs"][0]["budget"] += 1
    elif mutation == "solver-settings":
        experiment["solvers"]["bobyqa"]["settings"]["quiet"] = False
    elif mutation == "variant":
        experiment["numerical_variants"]["13"] = "warmup-100"
    elif mutation == "repetitions":
        experiment["requested_repetitions"] += 1
    elif mutation == "winner-seed":
        result["best_across_methods"][0]["winner"]["seed"] += 1
    elif mutation == "winner-calls":
        result["best_across_methods"][0]["winner"]["evaluation_count"] = 1101
    elif mutation == "extra-spec-field":
        experiment["runs"][0]["private_path"] = "/Users/private"
    elif mutation == "duplicate-spec":
        experiment["runs"][1]["id"] = experiment["runs"][0]["id"]
    else:
        experiment["schedule"] = "unknown-policy"
    write(output / "results.json", result)
    inventory = json.loads((output / "inventory.json").read_text())
    inventory["files"]["results.json"] = replay._hash(output / "results.json")
    write(output / "inventory.json", inventory)
    with pytest.raises(ValueError):
        export.verify_export(output)


def test_export_refuses_changed_frozen_solver_settings(campaign):
    campaign.dataset["origin_manifest"]["solvers"]["bobyqa"]["settings"]["quiet"] = False
    with pytest.raises(ValueError, match="authoritative adapter"):
        export.export_results(
            campaign.dataset,
            origin=campaign.origin,
            output_dir=campaign.tmp / "public",
            partial_preview=True,
        )
    assert not (campaign.tmp / "public").exists()


@pytest.mark.parametrize("value", ["/private/path", "user@host", "bad value", None])
def test_public_tokens_cannot_smuggle_paths_or_identifiers(value):
    with pytest.raises(ValueError):
        export._token(value)


def test_cli_plan_and_export_arguments(campaign, monkeypatch, capsys):
    args = [
        "--origin",
        str(campaign.origin),
        "--frozen-source",
        str(campaign.frozen),
        "--project-root",
        str(campaign.project),
        "--output-dir",
        str(campaign.tmp / "cli-replay"),
    ]
    assert replay.main(args + ["--plan-only"]) == 0
    assert not json.loads(capsys.readouterr().out)["simulation_started"]
    monkeypatch.setattr(replay, "run_replay", lambda configured: {"passed": False})
    assert replay.main(args + ["--run"]) == 1
    capsys.readouterr()
    with pytest.raises(SystemExit):
        replay.main([])
    monkeypatch.setattr(
        export,
        "export_results",
        lambda *args, **kwargs: {"partial_preview": kwargs["partial_preview"]},
    )
    assert (
        export.main(
            [
                "--origin",
                str(campaign.origin),
                "--output-dir",
                str(campaign.tmp / "cli"),
                "--partial-preview",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["partial_preview"]
    monkeypatch.setattr(export, "verify_export", lambda *args, **kwargs: {"integrity_passed": True})
    assert export.main(["--verify-export", str(campaign.tmp / "cli")]) == 0
    assert json.loads(capsys.readouterr().out)["integrity_passed"]
    for invalid in ([], ["--allow-partial-preview"], ["--verify-export", "out", "--origin", "old"]):
        with pytest.raises(SystemExit):
            export.main(invalid)
