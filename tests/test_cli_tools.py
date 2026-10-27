# SPDX-License-Identifier: MIT
"""Offline acquisition, escaped CI annotations, and thin CLI dispatch."""

import hashlib
import json
import runpy
import sys
from pathlib import Path

import pytest

from tools import ci_failure_summary, fetch_reference, fetch_weather, run_replication


@pytest.fixture(params=[fetch_reference, fetch_weather], ids=["reference", "weather"])
def fetch_tool(request, tmp_path, monkeypatch):
    tool = request.param
    source = tmp_path / "source.bin"
    source.write_bytes(b"pinned fixture")
    entry = {"cache_path": "models/source.idf" if tool is fetch_reference else "USA_test.epw",
             "url": source.as_uri(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    manifest = {"source_commit": "test-pinned-commit", "files": [entry]}
    data = tmp_path / "resources/data"
    data.mkdir(parents=True)
    filename = "reference-assets.json" if tool is fetch_reference else "weather-assets.json"
    (data / filename).write_text(json.dumps(manifest))
    monkeypatch.setattr(tool, "files", lambda _: data.parent)
    monkeypatch.setattr(tool, "ROOT", tmp_path / "project")
    fetch = tool.fetch_reference if tool is fetch_reference else tool.fetch_weather
    return tool, fetch, manifest


def test_fetch_verifies_bytes_and_retains_provenance(fetch_tool, tmp_path):
    tool, fetch, manifest = fetch_tool
    target = fetch(tmp_path / "cache")
    assert target == (tmp_path / "cache").resolve()
    assert (target / manifest["files"][0]["cache_path"]).read_bytes() == b"pinned fixture"
    if tool is fetch_weather:
        assert json.loads((target / "weather-provenance.json").read_text()) == manifest


@pytest.mark.parametrize("path", ["../escape.bin", "/outside/cache.bin"])
def test_fetch_rejects_escaping_manifest_path_before_download(fetch_tool, tmp_path, monkeypatch, path):
    tool, fetch, manifest = fetch_tool
    manifest["files"][0]["cache_path"] = path
    filename = "reference-assets.json" if tool is fetch_reference else "weather-assets.json"
    resource = tool.files("unused").joinpath("data", filename)
    resource.write_text(json.dumps(manifest))
    monkeypatch.setattr(tool, "download", lambda *a: pytest.fail("Escaping path must not download"))
    with pytest.raises(ValueError, match="escapes the local cache"):
        fetch(tmp_path / "cache")


def test_default_fetch_paths_and_reference_environment_override(fetch_tool, tmp_path, monkeypatch):
    tool, fetch, _ = fetch_tool
    chosen = tmp_path / "external-cache"
    monkeypatch.setenv("BEM_REFERENCE_DIR", str(chosen))
    if tool is fetch_reference:
        assert fetch() == chosen.resolve()
        assert tool.os.environ["BEM_REFERENCE_DIR"] == str(chosen)
    else:
        assert fetch() == (tool.ROOT / ".cache/weather").resolve()


def test_annotations_escape_commands_and_limit_failure_payload(tmp_path, capsys):
    junit = tmp_path / "unit.xml"
    junit.write_text('''<testsuites><testsuite>
      <testcase name="first"><failure message="bad%&#10;::warning::inject&#13;" /></testcase>
      <testcase name="second"><error message="''' + "x" * 7000 + '''" /></testcase>
      <testcase name="passing" />
    </testsuite></testsuites>''')
    ci_failure_summary.annotate(junit)
    output = capsys.readouterr().out.splitlines()
    assert len(output) == 2
    assert output[0] == "::error::first: bad%25%0A::warning::inject%0D"
    assert len(output[1]) == len("::error::") + 6000
    ci_failure_summary.annotate(tmp_path / "missing.xml")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("extended_warmup", [False, True])
def test_replication_cli_dispatches_options_without_running_an_experiment(
        tmp_path, monkeypatch, capsys, extended_warmup):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"requested_runs": 2}

    monkeypatch.setattr(run_replication, "run_replication", fake_run)
    arguments = [
        "--problems", "1", "13", "--solvers", "direct", "pybobyqa",
        "--versions", "8.5.0", "--repetitions", "1", "--budget", "20",
        "--seed", "99", "--workers", "2", "--schedule", "problem-first",
        "--output-root", str(tmp_path / "run"), "--weather-dir", str(tmp_path / "weather"),
        "--executable-8-5", str(tmp_path / "engine"), "--retain-success", "diagnostics",
        "--diagnostics-policy", "reference-warmup", "--retry-failed",
    ]
    if extended_warmup:
        arguments.append("--p1-warmup-100")
    run_replication.main(arguments)
    assert captured["problems"] == ["1", "13"]
    assert captured["solvers"] == ["direct", "pybobyqa"]
    assert captured["executables"] == {"8.5.0": tmp_path / "engine"}
    assert captured["budget"] == 20 and captured["seed"] == 99
    assert captured["workers"] == 2 and captured["schedule"] == "problem-first"
    assert captured["diagnostics_policy"] == "reference-warmup"
    assert captured["p1_warmup_100"] is extended_warmup
    assert captured["retry_failed"] and captured["retain_success"] == "diagnostics"
    assert "executable_8_5" not in captured
    assert json.loads(capsys.readouterr().out) == {"requested_runs": 2}
    assert not (tmp_path / "run").exists()


def test_replication_cli_rejects_unknown_solver_before_dispatch(monkeypatch):
    monkeypatch.setattr(run_replication, "run_replication", lambda **k: pytest.fail("No dispatch"))
    with pytest.raises(SystemExit) as error:
        run_replication.main(["--solvers", "not-a-solver"])
    assert error.value.code == 2


def test_replication_cli_dispatches_the_explicit_mixed_profile(monkeypatch, capsys):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {"requested_runs": 2400}

    monkeypatch.setattr(run_replication, "run_replication", fake_run)
    run_replication.main(["--numerical-variant", "replication"])
    assert captured["numerical_variant"] == "replication"
    assert captured["diagnostics_policy"] == "strict"
    assert captured["repetitions"] == 20 and captured["budget"] is None
    assert json.loads(capsys.readouterr().out) == {"requested_runs": 2400}


@pytest.mark.parametrize("diagnostic", [False, True])
def test_plot_cli_dispatches_paths_and_prints_result(tmp_path, monkeypatch, capsys, diagnostic):
    from bem_testproblems import replication_plots

    captured = {}

    def fake_plot(root, *, output_dir, include_diagnostic_runs):
        captured.update(root=root, output_dir=output_dir,
                        include_diagnostic_runs=include_diagnostic_runs)
        return {"summary": "numeric-summary.json", "plots": []}

    monkeypatch.setattr(replication_plots, "plot_replication", fake_plot)
    arguments = ["plot_replication.py", str(tmp_path / "runs"),
                 "--output-dir", str(tmp_path / "plots")]
    if diagnostic:
        arguments.append("--include-diagnostic-runs")
    monkeypatch.setattr(sys, "argv", arguments)
    runpy.run_module("tools.plot_replication", run_name="__main__")
    assert captured == {"root": tmp_path / "runs", "output_dir": tmp_path / "plots",
                        "include_diagnostic_runs": diagnostic}
    assert json.loads(capsys.readouterr().out)["summary"] == "numeric-summary.json"


@pytest.mark.parametrize("script", ["fetch_reference", "fetch_weather"])
def test_fetch_cli_dispatches_explicit_directory_without_network(script, tmp_path, monkeypatch):
    from tools import install_energyplus

    captured = []
    monkeypatch.setattr(install_energyplus, "download", lambda url, path, checksum:
                        captured.append((Path(path), checksum)))
    directory = tmp_path / "cache"
    directory.mkdir()
    monkeypatch.setattr(sys, "argv", [script + ".py", "--directory", str(directory)])
    monkeypatch.delitem(sys.modules, "tools." + script)
    runpy.run_module("tools." + script, run_name="__main__")
    assert captured
    assert all(path.is_relative_to(directory) and len(checksum) == 64 for path, checksum in captured)


@pytest.mark.parametrize("script", ["install_energyplus", "install_reference_engine"])
def test_installer_cli_dispatches_destination_without_installation(script, tmp_path, monkeypatch):
    from tools import install_energyplus, install_reference_engine

    tool = install_energyplus if script == "install_energyplus" else install_reference_engine
    captured = []
    monkeypatch.setattr(tool, "install", lambda *args: captured.append(args))
    arguments = ["--destination", str(tmp_path / "engine")]
    if tool is install_energyplus:
        arguments += ["--platform", "linux-x86_64"]
    tool.main(arguments)
    expected = [("linux-x86_64", tmp_path / "engine")] if tool is install_energyplus else [
        (tmp_path / "engine",)]
    assert captured == expected
    assert not (tmp_path / "engine").exists()
