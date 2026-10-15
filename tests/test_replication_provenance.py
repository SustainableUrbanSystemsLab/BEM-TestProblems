"""Protect experiment identity, atomic checkpoints and process isolation."""

import hashlib
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from bem_testproblems import get_problem, replication
from bem_testproblems.energyplus import sha256_file


def test_weather_identity_requires_the_pinned_bytes_and_design_days_need_no_file(
        tmp_path, monkeypatch):
    problem = get_problem(1)
    weather = tmp_path / problem.weather_filename
    data = tmp_path / "data"
    data.mkdir()
    weather.write_bytes(b"independent unit-test fixture")
    digest = sha256_file(weather)
    (data / "weather-assets.json").write_text(json.dumps({"files": [
        {"cache_path": weather.name, "sha256": digest}]}))
    monkeypatch.setattr(replication, "files", lambda _: tmp_path)
    assert replication._weather_identity(problem, tmp_path)["sha256"] == digest
    weather.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="checksum mismatch"):
        replication._weather_identity(problem, tmp_path)
    weather.unlink()
    with pytest.raises(FileNotFoundError, match="fetch_weather"):
        replication._weather_identity(problem, tmp_path)
    assert replication._weather_identity(get_problem(13), tmp_path)["mode"] == "embedded-design-day"


def test_model_identity_tracks_fixture_bytes_and_the_shared_p6_p8_template(tmp_path, monkeypatch):
    legacy = tmp_path / "template.idf"
    legacy.write_bytes(b"Version,8.5;\n")
    data = tmp_path / "data/modern"
    data.mkdir(parents=True)
    for name in ("problem_1.epJSON", "problem_6.epJSON", "parameter_bindings.json"):
        (data / name).write_bytes(b"{}\n")
    monkeypatch.setattr(replication, "legacy_template_path", lambda _: legacy)
    monkeypatch.setattr(replication, "files", lambda _: tmp_path)
    old = replication._model_identity(get_problem(1), "8.5.0")
    modern = replication._model_identity(get_problem(1), "26.2.0")
    assert old == {"format": "IDF", "template_sha256": hashlib.sha256(b"Version,8.5;\n").hexdigest()}
    digest = hashlib.sha256(b"{}\n").hexdigest()
    assert modern == {"format": "epJSON", "template_sha256": digest, "bindings_sha256": digest}
    (data / "problem_1.epJSON").write_bytes(b"{}\n\n")
    changed = replication._model_identity(get_problem(1), "26.2.0")
    assert changed["template_sha256"] == hashlib.sha256(b"{}\n\n").hexdigest()
    assert changed["template_sha256"] != modern["template_sha256"]
    assert changed["bindings_sha256"] == modern["bindings_sha256"]
    assert replication._model_identity(get_problem(6), "26.2.0") == replication._model_identity(
        get_problem(8), "26.2.0")


@pytest.mark.parametrize("version", ["8.5.0", "26.2.0"])
def test_p1_variant_model_identity_names_the_adjustment_even_for_modern_noop(version):
    canonical = replication._model_identity(get_problem(1), version)
    variant = replication._model_identity(get_problem(1, numerical_variant="warmup-100"), version)
    assert "numerical_variant" not in canonical
    assert variant.pop("numerical_variant") == get_problem(
        1, numerical_variant="warmup-100"
    ).provenance["numerical_variant"]
    assert variant == canonical


def test_dependency_identity_records_native_bytes_even_without_distribution_metadata(
        tmp_path, monkeypatch):
    entry = tmp_path / "__init__.py"
    native = tmp_path / "_nlopt.so"
    entry.write_text("# independent fixture\n")
    native.write_bytes(b"native fixture, never loaded")
    module = SimpleNamespace(version_major=lambda: 2, version_minor=lambda: 7,
                             version_bugfix=lambda: 1)
    monkeypatch.setattr(replication.util, "find_spec", lambda _: SimpleNamespace(origin=str(entry)))
    monkeypatch.setattr(replication, "import_module", lambda _: module)

    def absent_distribution(_):
        raise replication.PackageNotFoundError

    monkeypatch.setattr(replication, "package_version", absent_distribution)
    identity = replication._dependency_identity("nlopt")
    assert identity["available"] and identity["runtime_version"] == "2.7.1"
    assert identity["distribution_version"] is None
    assert identity["entrypoint_sha256"] == sha256_file(entry)
    assert identity["native_sha256"] == {native.name: sha256_file(native)}
    monkeypatch.setattr(replication.util, "find_spec", lambda _: None)
    assert not replication._dependency_identity("nlopt")["available"]


def test_failed_atomic_replacement_preserves_checkpoint_and_removes_partial_file(
        tmp_path, monkeypatch):
    checkpoint = tmp_path / "run.json"
    checkpoint.write_text('{"status":"completed"}')
    original = checkpoint.read_bytes()

    def blocked_replace(*_):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(Path, "replace", blocked_replace)
    with pytest.raises(OSError, match="filesystem failure"):
        replication._atomic_json(checkpoint, {"status": "running"})
    assert checkpoint.read_bytes() == original
    assert list(tmp_path.iterdir()) == [checkpoint]


def test_numpy_values_are_saved_as_json_numbers_and_arrays(tmp_path):
    np = pytest.importorskip("numpy")
    checkpoint = tmp_path / "run.json"
    replication._atomic_json(checkpoint, {"x": np.array([1.0, 2.0]), "count": np.int64(3),
                                         "diagnostic": float("nan")})
    assert json.loads(checkpoint.read_text()) == {"x": [1.0, 2.0], "count": 3, "diagnostic": None}


@pytest.mark.parametrize("host,pid,can_recover", [
    (socket.gethostname(), 2**31 - 1, True),
    ("independent-other-host", 2**31 - 1, False),
    (socket.gethostname(), os.getpid(), False),
])
def test_stale_local_locks_are_recovered_but_live_or_foreign_locks_are_preserved(
        tmp_path, host, pid, can_recover):
    lock = tmp_path / "experiment.lock"
    lock.write_text(json.dumps({"host": host, "pid": pid, "token": "prior-owner"}))
    if can_recover:
        with replication._experiment_lock(tmp_path):
            assert json.loads(lock.read_text())["pid"] == os.getpid()
        assert not lock.exists()
    else:
        original = lock.read_bytes()
        with pytest.raises(RuntimeError, match="already holds"):
            with replication._experiment_lock(tmp_path):
                pytest.fail("A coordinator must not steal an active or foreign lock")
        assert lock.read_bytes() == original


def test_spawned_workers_write_separate_checkpoints_and_resume_skipped_runs(
        tmp_path, fake_engine):
    configuration = dict(problems=[13], solvers=["pso", "sga"], versions=["26.2.0"],
                         repetitions=1, budget=2, project_root=tmp_path,
                         executables={"26.2.0": fake_engine})
    root = tmp_path / "experiment"
    summary = replication.run_replication(output_root=root, workers=2, **configuration)
    checkpoints = {path.name: path.read_bytes() for path in (root / "runs").glob("*.json")}
    assert summary["statuses"]["skipped"] == len(checkpoints) == 2
    assert summary["evaluation_count"] == 0
    assert not (root / "experiment.lock").exists()
    replication.run_replication(output_root=root, workers=2, **configuration)
    assert checkpoints == {path.name: path.read_bytes() for path in (root / "runs").glob("*.json")}
