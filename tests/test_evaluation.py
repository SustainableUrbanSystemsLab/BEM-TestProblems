"""Bind ordinary solver callables without launching or installing a simulator."""

import hashlib
import json
import os
from functools import partial
from importlib.resources import files
from pathlib import Path

import pytest

import bem_testproblems.evaluation as evaluation
from bem_testproblems import get_problem, make_objective
from bem_testproblems.energyplus import EnergyPlusError
from bem_testproblems.problems import Problem


class FakeRunner:
    def __init__(self, version="26.2.0"):
        self.version = version
        self.calls = []

    def run(self, input_file, weather_file=None, *, design_day=False):
        self.calls.append((Path(input_file).read_bytes(), weather_file, design_day))
        pytest.fail("Binding an objective must not launch an EnergyPlus simulation")


@pytest.mark.parametrize("number", [6, 8])
def test_number_selects_historical_hvac_and_explicit_problem_keeps_its_model(number, tmp_path):
    weather = tmp_path / "weather.epw"
    weather.write_text("Explicit weather fixture")
    runner = FakeRunner()
    default = make_objective(number, runner=runner, weather=weather)
    assert default.func.__self__ is get_problem(number, numerical_variant="historical-hvac")
    canonical = get_problem(number, numerical_variant="canonical")
    explicit = make_objective(canonical, runner=runner, weather=weather)
    assert explicit.func.__self__ is canonical
    assert runner.calls == []


@pytest.mark.parametrize("selection", [1, "p1", get_problem(1)])
def test_plain_scalar_callable_forwards_physical_vectors_and_explicit_weather(
    selection, tmp_path, monkeypatch
):
    runner = FakeRunner()
    weather = tmp_path / "explicit-climate-variant.epw"
    weather.write_text("Independent test data, not canonical benchmark weather")
    calls = []

    def evaluate(problem, x, *, runner, weather):
        calls.append((problem, x, runner, weather))
        return sum(x)

    monkeypatch.setattr(Problem, "evaluate", evaluate)
    objective = make_objective(selection, runner=runner, weather=weather)
    assert isinstance(objective, partial)
    assert runner.calls == []
    problem = get_problem(1)
    assert problem.dimension == len(problem.bounds) == len(problem.midpoint) == 4
    # A solver sees the published physical coordinates, rather than a hidden
    # normalization or an EnergyPlus-specific function signature.
    vectors = [[45.0, 2.5, 4.5, 0.3], list(problem.midpoint)]
    assert [objective(x) for x in vectors] == [sum(x) for x in vectors]
    assert [item[1] for item in calls] == vectors
    assert calls[0][1] is vectors[0]
    assert all(item[0] is problem and item[2] is runner for item in calls)
    assert all(item[3] == weather.resolve() for item in calls)


def test_design_day_needs_neither_weather_cache_nor_simulation_at_bind(tmp_path):
    runner = FakeRunner()
    objective = make_objective(13, project_root=tmp_path, runner=runner)
    assert objective.keywords == {"runner": runner, "weather": None}
    assert runner.calls == []
    assert list(tmp_path.iterdir()) == []


def test_simulation_failure_remains_the_original_diagnostic_error(tmp_path):
    expected = EnergyPlusError("Warmup did not converge", reason="simulation", directory=tmp_path)

    class BrokenRunner(FakeRunner):
        def run(self, input_file, weather_file=None, *, design_day=False):
            assert Path(input_file).is_file()
            assert weather_file is None
            assert design_day
            raise expected

    objective = make_objective(13, runner=BrokenRunner())
    with pytest.raises(EnergyPlusError) as error:
        objective(get_problem(13).midpoint)
    assert error.value is expected
    assert error.value.directory == tmp_path


def test_defaults_follow_source_checkout_even_when_working_directory_changes(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout with spaces"
    package = checkout / "src" / "bem_testproblems"
    package.mkdir(parents=True)
    module = package / "evaluation.py"
    module.write_text("# Source-checkout marker\n")
    (checkout / "pyproject.toml").write_text('[project]\nname = "bem-testproblems"\n')
    executable = checkout / ".tools" / "energyplus" / "26.2.0" / (
        "energyplus.exe" if os.name == "nt" else "energyplus"
    )
    executable.parent.mkdir(parents=True)
    executable.write_text("Fake executable: constructor below does not invoke it")
    weather = checkout / ".cache" / "weather" / get_problem(1).weather_filename
    weather.parent.mkdir(parents=True)
    weather.write_text("Tiny path-discovery fixture")
    manifest = json.loads(files("bem_testproblems").joinpath("data/weather-assets.json").read_text())
    expected_hash = next(
        item["sha256"] for item in manifest["files"] if item["cache_path"] == weather.name
    )
    created = []

    def construct(path, **kwargs):
        created.append((Path(path), kwargs))
        return FakeRunner(kwargs["expected_version"])

    elsewhere = tmp_path / "unrelated notebook directory"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(evaluation, "__file__", str(module))
    monkeypatch.setattr(evaluation, "EnergyPlusRunner", construct)
    # This test isolates path discovery. The mismatch test below exercises the
    # real checksum validation without replacing its hash implementation.
    monkeypatch.setattr(evaluation, "sha256_file", lambda path: expected_hash)
    objective = make_objective(1)
    assert created[0][0] == executable.resolve()
    assert created[0][1]["expected_version"] == "26.2.0"
    assert Path(created[0][1]["output_root"]).is_relative_to(checkout)
    assert objective.keywords["weather"] == weather.resolve()


def test_missing_default_engine_gives_an_actionable_setup_error(tmp_path):
    with pytest.raises(FileNotFoundError) as error:
        make_objective(13, project_root=tmp_path)
    message = str(error.value)
    assert str(tmp_path) in message
    assert "install_energyplus.py" in message


def test_missing_default_weather_gives_an_actionable_setup_error(tmp_path):
    with pytest.raises(FileNotFoundError) as error:
        make_objective(1, project_root=tmp_path, runner=FakeRunner())
    message = str(error.value)
    assert get_problem(1).weather_filename in message
    assert "fetch_weather.py" in message


def test_changed_canonical_weather_is_rejected_before_simulation(tmp_path):
    weather = tmp_path / ".cache" / "weather" / get_problem(1).weather_filename
    weather.parent.mkdir(parents=True)
    weather.write_bytes(b"Changed benchmark weather bytes\n")
    runner = FakeRunner()
    with pytest.raises(ValueError, match="(?i)checksum"):
        make_objective(1, project_root=tmp_path, runner=runner)
    assert runner.calls == []


def test_custom_weather_directory_still_checks_canonical_identity(tmp_path, monkeypatch):
    weather = tmp_path / get_problem(1).weather_filename
    weather.write_bytes(b"Small trusted weather fixture\n")
    trusted = tmp_path / "weather-manifest.json"
    trusted.write_text(json.dumps({"files": [{
        "cache_path": weather.name,
        "sha256": hashlib.sha256(weather.read_bytes()).hexdigest(),
    }]}))
    real_resources = files("bem_testproblems")

    class TestResources:
        def joinpath(self, *parts):
            if "/".join(parts) == "data/weather-assets.json":
                return trusted
            return real_resources.joinpath(*parts)

    monkeypatch.setattr(evaluation, "files", lambda package: TestResources())
    objective = make_objective(1, runner=FakeRunner(), weather_dir=tmp_path)
    assert objective.keywords["weather"] == weather.resolve()


def test_canonical_weather_mutation_is_rejected_before_next_evaluation(tmp_path, monkeypatch):
    weather = tmp_path / get_problem(1).weather_filename
    weather.write_bytes(b"Trusted canonical fixture\n")
    manifest = tmp_path / "weather-manifest.json"
    manifest.write_text(json.dumps({"files": [{
        "cache_path": weather.name,
        "sha256": hashlib.sha256(weather.read_bytes()).hexdigest(),
    }]}))
    real_resources = files("bem_testproblems")

    class TestResources:
        def joinpath(self, *parts):
            if "/".join(parts) == "data/weather-assets.json":
                return manifest
            return real_resources.joinpath(*parts)

    calls = []

    def evaluate(problem, x, **kwargs):
        calls.append(tuple(x))
        return 123.0

    monkeypatch.setattr(evaluation, "files", lambda package: TestResources())
    monkeypatch.setattr(Problem, "evaluate", evaluate)
    problem = get_problem(1)
    objective = make_objective(problem, runner=FakeRunner(), weather_dir=tmp_path)
    assert objective(problem.midpoint) == 123.0
    weather.write_bytes(b"Replaced after the first simulation\n")
    with pytest.raises(ValueError, match="(?i)checksum"):
        objective(problem.midpoint)
    assert calls == [problem.midpoint]


def test_explicit_engine_version_must_agree_with_supplied_runner():
    with pytest.raises(ValueError, match="(?i)version|8.5|26.2"):
        make_objective(13, runner=FakeRunner("8.5.0"), energyplus_version="26.2.0")


def test_legacy_runner_is_inferred_and_missing_original_template_fails_at_bind(monkeypatch):
    expected = FileNotFoundError("Original reference template is not cached; run fetch_reference.py")
    looked_up = []

    def missing(filename):
        looked_up.append(filename)
        raise expected

    monkeypatch.setattr(evaluation, "legacy_template_path", missing)
    runner = FakeRunner("8.5.0")
    with pytest.raises(FileNotFoundError) as error:
        make_objective(13, runner=runner)
    assert error.value is expected
    assert looked_up == [get_problem(13).template_filename]
    assert runner.calls == []


@pytest.mark.parametrize("options", [
    {"runner": FakeRunner(), "executable": "energyplus"},
    {"runner": FakeRunner(), "output_root": "runs"},
    {"weather": "selected.epw", "weather_dir": "climate-cache"},
])
def test_conflicting_configuration_fails_before_launch(options):
    with pytest.raises(ValueError):
        make_objective(13, **options)


def test_installed_package_defaults_and_explicit_paths_follow_callers_directory(tmp_path, monkeypatch):
    module = tmp_path / "installation" / "bem_testproblems" / "evaluation.py"
    monkeypatch.setattr(evaluation, "__file__", str(module))
    monkeypatch.chdir(tmp_path)
    executable = tmp_path / "chosen-engine"
    weather = tmp_path / "variant.epw"
    executable.write_text("An executable checked only by the fake constructor")
    weather.write_text("Independent weather variant")
    created = []

    def construct(path, **kwargs):
        created.append((path, kwargs))
        return FakeRunner(kwargs["expected_version"])

    monkeypatch.setattr(evaluation, "EnergyPlusRunner", construct)
    objective = make_objective(13, executable="chosen-engine", weather="variant.epw", output_root="runs")
    assert created == [(executable, {"expected_version": "26.2.0", "output_root": tmp_path / "runs"})]
    assert objective.keywords["weather"] == weather
    assert evaluation._default_project_root() == tmp_path


@pytest.mark.parametrize("setting", ["executable", "weather"])
def test_explicit_directory_cannot_replace_required_file(tmp_path, setting):
    options = {setting: tmp_path}
    if setting == "weather":
        options["runner"] = FakeRunner()
    with pytest.raises(ValueError, match="must be a file"):
        make_objective(13, **options)


def test_explicit_missing_weather_has_a_specific_setup_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Explicit weather file is missing"):
        make_objective(13, runner=FakeRunner(), weather=tmp_path / "missing.epw")


@pytest.mark.parametrize("version", ["8.5.1", "26.2.1", "unknown"])
def test_factory_rejects_unsupported_runner_version_before_setup(tmp_path, version):
    with pytest.raises(ValueError, match="Supported EnergyPlus versions"):
        make_objective(13, project_root=tmp_path, runner=FakeRunner(version))
    assert list(tmp_path.iterdir()) == []


def test_explicit_legacy_version_is_normalized_and_binds_existing_reference(tmp_path, monkeypatch):
    looked_up = []
    monkeypatch.setattr(evaluation, "legacy_template_path", lambda filename: looked_up.append(filename))
    runner = FakeRunner("8.5")
    objective = make_objective(13, runner=runner, energyplus_version="8.5.0")
    assert objective.keywords == {"runner": runner, "weather": None}
    assert looked_up == [get_problem(13).template_filename]


@pytest.mark.parametrize("record_count", [0, 2])
def test_canonical_weather_needs_one_unambiguous_package_pin(tmp_path, monkeypatch, record_count):
    package = tmp_path / "package"
    (package / "data").mkdir(parents=True)
    record = {"cache_path": get_problem(1).weather_filename, "sha256": "not-used"}
    (package / "data" / "weather-assets.json").write_text(json.dumps({"files": [record] * record_count}))
    monkeypatch.setattr(evaluation, "files", lambda package_name: package)
    with pytest.raises(ValueError, match="No canonical weather checksum"):
        make_objective(1, runner=FakeRunner(), weather_dir=tmp_path)
