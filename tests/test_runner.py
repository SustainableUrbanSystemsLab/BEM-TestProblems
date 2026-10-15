"""Process-boundary tests use a tiny executable, never an EnergyPlus installation."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bem_testproblems.energyplus import EnergyPlusError, EnergyPlusRunner, sha256_file


def model(tmp_path, **settings):
    path = tmp_path / "model.epJSON"
    path.write_text(json.dumps({"Version": {"v": {"version_identifier": "26.2"}}, "test": settings}))
    return path


def test_run_keeps_input_and_provenance_and_isolates_cwd(tmp_path, fake_engine):
    source = model(tmp_path)
    weather = tmp_path / "original.epw"
    weather.write_text("weather remains external")
    digest = sha256_file(source)
    runner = EnergyPlusRunner(fake_engine, output_root=tmp_path / "runs")
    result = runner.run(source, weather, design_day=True)
    observed = json.loads((result.directory / "observed.json").read_text())
    provenance = json.loads((result.directory / "run.json").read_text())
    assert Path(observed["cwd"]) == result.directory
    assert result.directory != source.parent
    assert result.input_file.read_bytes() == source.read_bytes()
    assert result.input_sha256 == digest == sha256_file(source)
    assert result.weather_sha256 == sha256_file(weather)
    assert result.executable_sha256 == sha256_file(fake_engine)
    assert "-D" in result.command
    assert str(weather.resolve()) in result.command
    assert provenance["status"] == "success"
    assert provenance["elapsed"] >= 0
    assert "stdout retained" in (result.directory / "stdout.log").read_text()
    assert "stderr retained" in (result.directory / "stderr.log").read_text()


def test_version_mismatch_is_rejected_before_simulation(tmp_path, fake_engine):
    with pytest.raises(EnergyPlusError, match="Expected EnergyPlus"):
        EnergyPlusRunner(fake_engine, expected_version="8.5")
    runner = EnergyPlusRunner(fake_engine)
    path = model(tmp_path)
    path.write_text('{"Version":{"v":{"version_identifier":"8.5"}}}')
    with pytest.raises(EnergyPlusError, match="does not match"):
        runner.run(path)


@pytest.mark.parametrize("settings,reason", [({"exit": 7}, "exit"), ({"severe": True}, "simulation"), ({"incomplete": True}, "incomplete")])
def test_failed_runs_are_visible_and_retained(tmp_path, fake_engine, settings, reason):
    runner = EnergyPlusRunner(fake_engine, output_root=tmp_path / "runs")
    source = model(tmp_path, **settings)
    with pytest.raises(EnergyPlusError) as caught:
        runner.run(source)
    error = caught.value
    assert error.reason == reason
    assert error.directory.is_dir()
    metadata = json.loads((error.directory / "run.json").read_text())
    assert metadata["status"] == "failed"
    assert metadata["failure_reason"] == reason
    with pytest.raises(EnergyPlusError) as second:
        runner.run(source)
    assert second.value.directory != error.directory  # failures are not cached


def test_timeout_cleans_child_process_tree(tmp_path, fake_engine):
    runner = EnergyPlusRunner(fake_engine, timeout=0.7, output_root=tmp_path / "runs")
    with pytest.raises(EnergyPlusError) as caught:
        runner.run(model(tmp_path, child=True))
    assert caught.value.reason == "timeout"
    time.sleep(1.6)
    assert not (caught.value.directory / "orphan-marker").exists()


def test_cache_is_exact_and_singleflight_and_can_be_disabled(tmp_path, fake_engine):
    runner = EnergyPlusRunner(fake_engine, output_root=tmp_path / "runs")
    source = model(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: runner.run(source), range(2)))
    assert results[0].directory == results[1].directory
    assert sorted(result.cache_hit for result in results) == [False, True]
    (results[0].directory / "eplusout.eso").unlink()
    fresh = runner.run(source)
    assert fresh.directory != results[0].directory
    # Even semantically equivalent byte changes must not be rounded/coalesced.
    source.write_text(source.read_text() + "\n")
    assert runner.run(source).directory != fresh.directory
    runner_no_cache = EnergyPlusRunner(fake_engine, cache=False)
    assert runner_no_cache.run(source).directory != runner_no_cache.run(source).directory


def test_cache_includes_weather_and_mode(tmp_path, fake_engine):
    runner = EnergyPlusRunner(fake_engine)
    source = model(tmp_path)
    weather = tmp_path / "weather.epw"
    weather.write_text("weather one")
    one = runner.run(source, weather)
    weather.write_text("weather two")
    two = runner.run(source, weather)
    three = runner.run(source, weather, design_day=True)
    assert len({one.directory, two.directory, three.directory}) == 3


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), -float("inf")])
def test_timeout_must_be_finite_and_positive(fake_engine, timeout):
    with pytest.raises(ValueError, match="timeout must be finite and positive"):
        EnergyPlusRunner(fake_engine, timeout=timeout)


@pytest.mark.parametrize("replacement", ["Not an EnergyPlus version", "EnergyPlus, Version 8.5.0-test"])
def test_unidentifiable_or_wrong_probe_version_never_starts_simulation(fake_engine, replacement):
    script = fake_engine.parent / "fake_engine.py"
    script.write_text(script.read_text().replace("EnergyPlus, Version 26.2.0-test", replacement))
    with pytest.raises(EnergyPlusError) as error:
        EnergyPlusRunner(fake_engine)
    assert error.value.reason == "version"
    assert error.value.directory is None


def test_failed_version_probe_reports_its_exit_status(fake_engine):
    script = fake_engine.parent / "fake_engine.py"
    script.write_text(script.read_text().replace("raise SystemExit(0)", "raise SystemExit(9)", 1))
    with pytest.raises(EnergyPlusError, match="version probe failed") as error:
        EnergyPlusRunner(fake_engine)
    assert error.value.reason == "version"
    assert error.value.returncode == 9


def test_version_probe_timeout_is_a_configuration_error(fake_engine):
    script = fake_engine.parent / "fake_engine.py"
    script.write_text(script.read_text().replace(
        'print("EnergyPlus, Version 26.2.0-test")',
        'time.sleep(5); print("EnergyPlus, Version 26.2.0-test")',
    ))
    with pytest.raises(EnergyPlusError, match="version probe timed out") as error:
        EnergyPlusRunner(fake_engine, timeout=0.5)
    assert error.value.reason == "version"


def test_executable_replacement_is_rejected_before_running(tmp_path, fake_engine):
    runner = EnergyPlusRunner(fake_engine, output_root=tmp_path / "runs")
    fake_engine.write_bytes(fake_engine.read_bytes() + b"\n")
    with pytest.raises(EnergyPlusError, match="executable changed") as error:
        runner.run(model(tmp_path))
    assert error.value.reason == "version"
    assert list(runner.output_root.iterdir()) == []


@pytest.mark.parametrize("changed_file,new_content", [
    ("eplusout.err", "** Fatal ** modified diagnostics"),
    ("eplusout.end", "EnergyPlus Terminated"),
    ("input.epJSON", "Replaced staged input"),
])
def test_cache_does_not_reuse_corrupted_inputs_or_completion_diagnostics(
    tmp_path, fake_engine, changed_file, new_content
):
    runner = EnergyPlusRunner(fake_engine, output_root=tmp_path / "runs")
    source = model(tmp_path)
    first = runner.run(source)
    (first.directory / changed_file).write_text(new_content)
    fresh = runner.run(source)
    assert not fresh.cache_hit
    assert fresh.directory != first.directory
    assert runner.run(source).cache_hit


@pytest.mark.parametrize("changed", ["input", "weather"])
def test_identity_change_between_cache_key_and_staging_is_not_cached(
    tmp_path, fake_engine, monkeypatch, changed
):
    runner = EnergyPlusRunner(fake_engine, output_root=tmp_path / "runs")
    source = model(tmp_path)
    weather = tmp_path / "weather.epw"
    weather.write_text("Initial weather")
    actual_run = runner._run_uncached

    def mutate_before_staging(*args, **kwargs):
        path = source if changed == "input" else weather
        path.write_text(path.read_text() + "\n")
        return actual_run(*args, **kwargs)

    monkeypatch.setattr(runner, "_run_uncached", mutate_before_staging)
    with pytest.raises(EnergyPlusError, match="changed during evaluation") as error:
        runner.run(source, weather)
    assert error.value.reason == "input_changed"
    assert error.value.directory.is_dir()
    monkeypatch.setattr(runner, "_run_uncached", actual_run)
    assert not runner.run(source, weather).cache_hit


@pytest.mark.parametrize("versions", [{}, {"a": {}, "b": {"version_identifier": "26.2"}}])
def test_missing_or_ambiguous_input_version_fails_before_process_launch(tmp_path, fake_engine, versions):
    source = model(tmp_path)
    source.write_text(json.dumps({"Version": versions}))
    runner = EnergyPlusRunner(fake_engine, output_root=tmp_path / "runs")
    with pytest.raises(EnergyPlusError) as error:
        runner.run(source)
    assert error.value.reason == "input_version"
    assert list(runner.output_root.iterdir()) == []


@pytest.mark.parametrize("cache", [True, False])
def test_invalid_input_suffix_and_weather_directory_are_rejected(tmp_path, fake_engine, cache):
    runner = EnergyPlusRunner(fake_engine, cache=cache, output_root=tmp_path / "runs")
    source = model(tmp_path)
    wrong_extension = source.with_suffix(".txt")
    wrong_extension.write_bytes(source.read_bytes())
    input_directory = tmp_path / "directory.idf"
    input_directory.mkdir()
    with pytest.raises(ValueError, match="input must be an .idf or .epJSON"):
        runner.run(wrong_extension)
    with pytest.raises(ValueError, match="input must be an .idf or .epJSON"):
        runner.run(input_directory)
    with pytest.raises(ValueError, match="weather_file must be an EPW file"):
        runner.run(source, tmp_path)
    assert list(runner.output_root.iterdir()) == []


@pytest.mark.parametrize("text,accepted", [
    ("! Version,8.5;\nBuilding,Example;\nvErSiOn,26.2; ! Current target", True),
    ("! Version,26.2;\nBuilding,Example;", False),
    ("Version,unknown;", False),
    ("Version,8.5;", False),
])
def test_idf_version_parser_distinguishes_comments_case_and_actual_version(
    tmp_path, fake_engine, text, accepted
):
    source = tmp_path / "input.idf"
    source.write_text(text)
    runner = EnergyPlusRunner(fake_engine)
    if accepted:
        runner._check_input_version(source)
    else:
        with pytest.raises(EnergyPlusError) as error:
            runner.run(source)
        assert error.value.reason == "input_version"
