"""Process-boundary tests use a tiny executable, never an EnergyPlus installation."""

import json
import os
import shlex
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bem_testproblems.energyplus import EnergyPlusError, EnergyPlusRunner, sha256_file


@pytest.fixture
def fake_engine(tmp_path):
    script = tmp_path / "fake_engine.py"
    script.write_text(textwrap.dedent('''\
        import json, os, pathlib, subprocess, sys, time
        if "--version" in sys.argv:
            print("EnergyPlus, Version 26.2.0-test")
            raise SystemExit(0)
        out = pathlib.Path(sys.argv[sys.argv.index("-d") + 1])
        inp = pathlib.Path(sys.argv[-1])
        settings = json.loads(inp.read_text()).get("test", {})
        print("stdout retained", flush=True)
        print("stderr retained", file=sys.stderr, flush=True)
        (out / "observed.json").write_text(json.dumps({"cwd": os.getcwd(), "argv": sys.argv}))
        if settings.get("child"):
            target = str(out / "orphan-marker")
            subprocess.Popen([sys.executable, "-c", "import time,pathlib;time.sleep(1.5);pathlib.Path(" + repr(target) + ").write_text('orphan')"])
            time.sleep(30)
        if settings.get("exit"):
            raise SystemExit(settings["exit"])
        (out / "eplusout.err").write_text("** Severe  ** bad model" if settings.get("severe") else "0 Warning; 0 Severe Errors")
        if not settings.get("incomplete"):
            (out / "eplusout.end").write_text("EnergyPlus Completed Successfully")
        (out / "eplusout.eso").write_text("End of Data Dictionary\\nEnd of Data\\n")
    '''))
    if os.name == "nt":
        executable = tmp_path / "fake_energyplus.cmd"
        executable.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        executable = tmp_path / "fake_energyplus"
        executable.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} "$@"\n')
        executable.chmod(0o755)
    return executable


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
