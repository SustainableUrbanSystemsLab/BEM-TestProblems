"""Process-boundary tests use a tiny executable, never an EnergyPlus installation."""

import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from bem_testproblems import energyplus
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group ownership")
def test_process_group_is_signalled_before_its_leader_can_be_reaped(monkeypatch):
    events = []
    process = SimpleNamespace(pid=43210, returncode=None)

    def wait(*, timeout):
        events.append("wait")
        process.returncode = -signal.SIGTERM

    def kill_group(pid, sig):
        # Reproduce the old race: after wait(), this PID could identify a group
        # owned by somebody else, making the final killpg fail with EPERM.
        if process.returncode is not None:
            raise PermissionError("The old process-group ID was reused")
        assert pid == process.pid
        events.append(sig)

    process.wait = wait
    monkeypatch.setattr(energyplus.os, "killpg", kill_group)
    monkeypatch.setattr(energyplus.time, "sleep", lambda delay: events.append(("grace", delay)))
    energyplus._terminate_tree(process)
    assert events == [signal.SIGTERM, ("grace", 1), signal.SIGKILL, "wait"]
    assert process.returncode is not None


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group ownership")
def test_cleanup_never_signals_a_process_group_after_the_leader_was_reaped(monkeypatch):
    process = SimpleNamespace(pid=43210, returncode=0)
    monkeypatch.setattr(energyplus.os, "killpg", lambda *args:
                        pytest.fail("An already reaped PID must not be signalled"))
    energyplus._terminate_tree(process)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group ownership")
def test_owned_group_permission_errors_are_not_hidden(monkeypatch):
    process = SimpleNamespace(pid=43210, returncode=None)

    def denied(*args):
        raise PermissionError("Owned process-group signalling was denied")

    monkeypatch.setattr(energyplus.os, "killpg", denied)
    monkeypatch.setattr(energyplus, "_group_has_no_live_members", lambda group: False)
    with pytest.raises(PermissionError, match="signalling was denied"):
        energyplus._terminate_tree(process)


def _process_identity(pid):
    """Read identity and state; a denied query must fail instead of implying exit."""
    observed = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "pid=,stat=,command="],
                              capture_output=True, text=True, check=False)
    assert observed.returncode in (0, 1), observed.stderr
    assert not observed.stderr.strip(), observed.stderr
    if not observed.stdout.strip():
        assert observed.returncode == 1, observed.stderr
        return None
    assert observed.returncode == 0, observed.stderr
    identifier, state, command = observed.stdout.strip().split(None, 2)
    assert int(identifier) == pid
    return state, command


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group ownership")
def test_cleanup_kills_a_real_child_that_ignores_term_after_its_leader_exits(tmp_path):
    child = tmp_path / "term-resistant-child.py"
    ready = tmp_path / "child-ready"
    child.write_text(
        "import os, pathlib, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n", encoding="utf-8")
    # The leader terminates normally on SIGTERM, while its child ignores it.
    leader = subprocess.Popen([sys.executable, "-c",
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]]); time.sleep(30)",
        str(child), str(ready)], **energyplus._process_options())
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "The child never installed its SIGTERM handler"
        child_pid = int(ready.read_text(encoding="utf-8"))
        identity = _process_identity(child_pid)
        assert identity is not None and str(child) in identity[1]
        assert not identity[0].startswith("Z")
        energyplus._terminate_tree(leader)
        assert leader.returncode is not None
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = _process_identity(child_pid)
            if current is None or current[0].startswith("Z") or str(child) not in current[1]:
                break
            time.sleep(0.02)
        else:
            pytest.fail("The same child is still alive after process-group cleanup")
    finally:
        if leader.returncode is None:
            energyplus._terminate_tree(leader)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group ownership")
@pytest.mark.parametrize("group_listing,stderr,returncode,accepted", [
    ("43210 Z\n43210 Z+\n123 S\n", "", 0, True),
    ("123 S\n", "", 0, True),
    ("43210 S\n", "", 0, False),
    ("43210 Z\n43210 R\n", "", 0, False),
    ("", "Operation not permitted", 1, False),
    ("43210 Z\n", "Permission denied", 0, False),
    ("malformed process listing\n", "", 0, False),
    ("not-a-group Z\n", "", 0, False),
    ("", "", 0, False),
])
def test_final_permission_error_requires_verified_termination_of_every_group_member(
    monkeypatch, group_listing, stderr, returncode, accepted
):
    process = SimpleNamespace(pid=43210, returncode=None)
    denied = PermissionError("Final group signal was denied")

    def kill_group(pid, sig):
        assert process.returncode is None
        if sig == signal.SIGKILL:
            raise denied

    def wait(*, timeout):
        process.returncode = -signal.SIGTERM

    def query(command, **kwargs):
        assert command == ["ps", "-e", "-o", "pgid=", "-o", "stat="]
        assert process.returncode is None  # Identity stays reserved during verification.
        return SimpleNamespace(stdout=group_listing, stderr=stderr, returncode=returncode)

    process.wait = wait
    monkeypatch.setattr(energyplus.os, "killpg", kill_group)
    monkeypatch.setattr(energyplus.time, "sleep", lambda delay: None)
    monkeypatch.setattr(energyplus.subprocess, "run", query)
    if accepted:
        energyplus._terminate_tree(process)
        assert process.returncode is not None
    else:
        with pytest.raises(PermissionError) as error:
            energyplus._terminate_tree(process)
        assert error.value is denied
        assert process.returncode is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group ownership")
@pytest.mark.parametrize("query_error", [PermissionError("query denied"),
                                       subprocess.TimeoutExpired("ps", 5)])
def test_group_verification_failure_preserves_the_original_permission_error(monkeypatch, query_error):
    process = SimpleNamespace(pid=43210, returncode=None)
    denied = PermissionError("Final group signal was denied")

    def kill_group(pid, sig):
        if sig == signal.SIGKILL:
            raise denied

    def query(*args, **kwargs):
        raise query_error

    monkeypatch.setattr(energyplus.os, "killpg", kill_group)
    monkeypatch.setattr(energyplus.time, "sleep", lambda delay: None)
    monkeypatch.setattr(energyplus.subprocess, "run", query)
    with pytest.raises(PermissionError) as error:
        energyplus._terminate_tree(process)
    assert error.value is denied


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group ownership")
def test_leader_exiting_just_before_first_signal_is_verified_before_reaping(monkeypatch):
    process = SimpleNamespace(pid=43210, returncode=None)
    events = []

    def kill_group(pid, sig):
        assert sig == signal.SIGTERM
        events.append("term")
        raise PermissionError("The process group already contains only zombies")

    def query(*args, **kwargs):
        assert process.returncode is None
        events.append("verify")
        return SimpleNamespace(returncode=0, stdout="43210 Z\n123 S\n", stderr="")

    def wait(*, timeout):
        events.append("reap")
        process.returncode = 0

    process.wait = wait
    monkeypatch.setattr(energyplus.os, "killpg", kill_group)
    monkeypatch.setattr(energyplus.subprocess, "run", query)
    energyplus._terminate_tree(process)
    assert events == ["term", "verify", "reap"]
