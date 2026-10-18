# SPDX-License-Identifier: MIT
"""Cross-platform continuation preserves origin evidence and original run specifications."""

import copy
import json
import platform
import subprocess
import sys
import textwrap
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

from bem_testproblems import replication
from bem_testproblems.energyplus import sha256_file
from tools import continue_replication as continuation


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


def record(spec, manifest, status="completed"):
    x = spec["x0"]
    return {
        **spec,
        "manifest_id": manifest["manifest_id"],
        "status": status,
        "attempt": 1,
        "elapsed_seconds": 0,
        "evaluation_count": 1,
        "best_x": x,
        "best_f": sum(x),
        "trace": [
            {
                "evaluation": 1,
                "status": "success",
                "x": x,
                "f": sum(x),
                "evaluation_elapsed_seconds": 0,
            }
        ],
        "problem_provenance": manifest["problem_definitions"][str(spec["problem"])],
        "engine_provenance": manifest["engines"][spec["version"]],
        "solver_metadata": manifest["solvers"][spec["solver"]],
    }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    origin, project, output = (tmp_path / name for name in ("origin", "project", "continuation"))
    source = tmp_path / "source/src/bem_testproblems"
    source.mkdir(parents=True)
    (source / "replication.py").write_bytes(b"frozen source fixture\n")
    engine = project / ".tools/energyplus/26.2.0/energyplus"
    engine.parent.mkdir(parents=True)
    engine.write_bytes(b"fake native engine")
    specs = [
        {
            "id": f"p01-26.2.0-bobyqa-r{i:03}",
            "problem": 1,
            "version": "26.2.0",
            "solver": "bobyqa",
            "repetition": i,
            "seed": 100 + i,
            "x0": [float(i), 3.0, 3.0, 0.5],
            "budget": 10,
        }
        for i in range(4)
    ]
    original = {
        "schema_version": 1,
        "protocol": "pilot-overrides",
        "runs": specs,
        "requested_repetitions": 4,
        "budget_override": 10,
        "master_seed": 2019,
        "diagnostics_policy": "strict",
        "schedule": "problem-first",
        "problem_definitions": {
            "1": {
                "name": "fixture",
                "dimension": 4,
                "models": {"26.2.0": {"template_sha256": "fixture"}},
            }
        },
        "engines": {"26.2.0": {"executable": "/old/engine", "executable_sha256": "old"}},
        "solvers": {"bobyqa": {"available": True}},
        "code_sha256": {"replication.py": sha256_file(source / "replication.py")},
        "platform": "original-platform",
    }
    original["manifest_id"] = continuation._digest(original)
    write(origin / "manifest.json", original)
    write(origin / "runs" / (specs[0]["id"] + ".json"), record(specs[0], original))
    write(origin / "runs" / (specs[1]["id"] + ".json"), record(specs[1], original, "running"))
    (origin / "experiment.lock").write_text('{"host":"old-host","pid":123}')
    target = copy.deepcopy(original)
    target.update(
        platform="Windows-AMD64",
        project_root=str(project),
        weather_directory=str(project / ".cache/weather"),
    )
    target["engines"] = {
        "26.2.0": {"executable": str(engine), "executable_sha256": sha256_file(engine)}
    }
    calls, pools = [], []

    class Runner:
        def __init__(self, path, *, expected_version, output_root=None, cache=False):
            assert cache is False
            self.version = expected_version
            self.executable_sha256 = sha256_file(path)

    def objective(problem, **kwargs):
        def evaluate(x):
            calls.append(tuple(x))
            return sum(x)

        return evaluate

    def solve(name, evaluate, x0, bounds, budget, seed):
        return {"status": "terminated", "success": True, "fun": evaluate(x0), "x": x0}

    class Executor:
        def __init__(self, *, max_workers, mp_context):
            assert mp_context.get_start_method() == "spawn"
            self.size = max_workers
            self.specs = []
            pools.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, function, spec, *args):
            self.specs.append(copy.deepcopy(spec))
            future = Future()
            try:
                future.set_result(function(spec, *args))
            except BaseException as error:
                future.set_exception(error)
            return future

    runtime = SimpleNamespace(
        __file__=str(source / "replication.py"),
        prepare_manifest=lambda **kwargs: copy.deepcopy(target),
        _experiment_lock=replication._experiment_lock,
        _atomic_json=replication._atomic_json,
        _summary=replication._summary,
        _run_one=replication._run_one,
    )
    monkeypatch.setattr(continuation, "_load_runtime", lambda *args: runtime)
    monkeypatch.setattr(continuation, "ProcessPoolExecutor", Executor)
    monkeypatch.setattr(replication, "EnergyPlusRunner", Runner)
    monkeypatch.setattr(
        replication, "_model_identity", lambda *args: {"template_sha256": "fixture"}
    )
    monkeypatch.setattr(replication, "make_objective", objective)
    monkeypatch.setattr(replication, "solve_solver", solve)
    return SimpleNamespace(
        origin=origin,
        project=project,
        output=output,
        source=source,
        original=original,
        target=target,
        runtime=runtime,
        specs=specs,
        calls=calls,
        pools=pools,
    )


def execute(setup, **kwargs):
    return continuation.continue_replication(setup.origin, setup.project, setup.output, **kwargs)


def test_default_plan_is_read_only_and_has_exact_remaining_specs(setup):
    before = {
        p.relative_to(setup.origin): p.read_bytes() for p in setup.origin.rglob("*") if p.is_file()
    }
    result = execute(setup)
    assert result["mode"] == "plan-only" and result["pool_sizes"] == [48]
    assert result["retained_origin_terminal"] == 1 and result["remaining_runs"] == 3
    assert setup.calls == setup.pools == [] and not setup.output.exists()
    assert before == {
        p.relative_to(setup.origin): p.read_bytes() for p in setup.origin.rglob("*") if p.is_file()
    }
    _, manifest, partitions, _ = continuation.prepare_continuation(
        setup.origin, setup.project, setup.output
    )
    assert manifest["runs"] == setup.specs[1:]
    assert partitions[0][1] == setup.specs[1:]
    assert manifest["manifest_id"] != setup.original["manifest_id"]
    assert manifest["continuation"]["origin_manifest_id"] == setup.original["manifest_id"]
    assert "origin" not in manifest["engines"]["26.2.0"]["executable"]


def test_continuation_preserves_native_hashes_and_rejects_changed_configuration(setup, monkeypatch):
    pinned = {"config_path": "private-native.json", "config_sha256": "original"}
    setup.original["native_solvers"] = pinned
    setup.original["manifest_id"] = continuation._digest({
        key: value for key, value in setup.original.items() if key != "manifest_id"})
    write(setup.origin / "manifest.json", setup.original)
    for index, status in ((0, "completed"), (1, "running")):
        write(setup.origin / "runs" / (setup.specs[index]["id"] + ".json"),
              record(setup.specs[index], setup.original, status))
    setup.target["native_solvers"] = copy.deepcopy(pinned)
    received = []

    def prepare(**kwargs):
        received.append(kwargs)
        return copy.deepcopy(setup.target)

    monkeypatch.setattr(setup.runtime, "prepare_manifest", prepare)
    continuation.prepare_continuation(setup.origin, setup.project, setup.output)
    assert received[0]["native_solvers"] == "private-native.json"
    setup.target["native_solvers"]["config_sha256"] = "changed"
    with pytest.raises(ValueError, match="native_solvers differs"):
        continuation.prepare_continuation(setup.origin, setup.project, setup.output)


def test_extended_budget_handoff_preserves_multiplier_and_every_original_cap(setup, monkeypatch):
    for manifest in (setup.original, setup.target):
        manifest.update(protocol="extended-budget-experiment", budget_override=None,
                        budget_multiplier=100,
                        effective_budget_rule="100*(dimension+1)*budget_multiplier")
        for spec in manifest["runs"]:
            spec["budget"] = 50000
    setup.original.pop("manifest_id")
    setup.original["manifest_id"] = continuation._digest(setup.original)
    write(setup.origin / "manifest.json", setup.original)
    for index, status in ((0, "completed"), (1, "running")):
        write(setup.origin / "runs" / (setup.specs[index]["id"] + ".json"),
              record(setup.specs[index], setup.original, status))

    def resolve(**kwargs):
        assert kwargs["budget"] is None
        assert kwargs["budget_multiplier"] == 100
        return copy.deepcopy(setup.target)

    monkeypatch.setattr(setup.runtime, "prepare_manifest", resolve)
    _, manifest, _, _ = continuation.prepare_continuation(
        setup.origin, setup.project, setup.output)
    assert manifest["budget_multiplier"] == 100
    assert len(manifest["runs"]) == 3
    assert all(spec["budget"] == 50000 for spec in manifest["runs"])


def test_120_workers_use_two_safe_pools_and_submit_union_once(setup):
    result = execute(setup, run=True, workers=120)
    assert [p.size for p in setup.pools] == [60, 60]
    submitted = [row for pool in setup.pools for row in pool.specs]
    assert {r["id"] for r in submitted} == {r["id"] for r in setup.specs[1:]}
    assert len(submitted) == len({r["id"] for r in submitted}) == 3
    assert sorted(submitted, key=lambda r: r["id"]) == setup.specs[1:]
    assert result["summary"]["statuses"]["completed"] == 3
    assert len(setup.calls) == 3
    assert not (setup.output / "experiment.lock").exists()
    assert (
        json.loads((setup.output / "continuation-status.json").read_text())["status"] == "finished"
    )


def test_resume_retains_terminal_and_resource_change_does_not_change_identity(setup):
    execute(setup, run=True, workers=48)
    before = (setup.output / "manifest.json").read_bytes()
    setup.calls.clear()
    result = execute(setup, run=True, workers=120)
    assert result["remaining_runs"] == 0 and not setup.calls
    assert (setup.output / "manifest.json").read_bytes() == before


def test_destination_records_the_actual_python_runtime(setup):
    _, manifest, _, _ = continuation.prepare_continuation(
        setup.origin, setup.project, setup.output
    )
    assert manifest["execution_runtime"] == {
        "python_version": sys.version,
        "python_implementation": sys.implementation.name,
        "python_executable_sha256": sha256_file(Path(sys.executable)),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }
    assert "execution_runtime" not in setup.original


@pytest.mark.parametrize("field", [
    "python_version", "python_implementation", "python_executable_sha256", "platform", "machine",
])
def test_runtime_change_rejects_resume_before_any_new_evaluation(setup, monkeypatch, field):
    execute(setup, run=True)
    before = {path: path.read_bytes() for path in setup.output.rglob("*.json")}
    identity = continuation._runtime_identity()
    identity[field] = "f" * 64 if field.endswith("sha256") else "changed-runtime"
    monkeypatch.setattr(continuation, "_runtime_identity", lambda: identity)
    setup.calls.clear()
    with pytest.raises(ValueError, match="Existing continuation manifest differs"):
        execute(setup, run=True)
    assert not setup.calls
    assert before == {path: path.read_bytes() for path in setup.output.rglob("*.json")}


def test_own_interrupted_attempt_is_archived_by_existing_worker(setup):
    execute(setup, run=True)
    identifier = setup.specs[1]["id"]
    path = setup.output / "runs" / (identifier + ".json")
    previous = json.loads(path.read_text())
    previous["status"] = "running"
    write(path, previous)
    setup.calls.clear()
    execute(setup, run=True)
    assert len(setup.calls) == 1
    assert (
        json.loads((setup.output / "history" / (identifier + "-attempt1.json")).read_text())
        == previous
    )
    assert json.loads(path.read_text())["attempt"] == 2
    assert (
        json.loads((setup.origin / "runs" / (identifier + ".json")).read_text())["status"]
        == "running"
    )


def test_original_failure_is_terminal_and_not_relabelled(setup):
    path = setup.origin / "runs" / (setup.specs[0]["id"] + ".json")
    row = json.loads(path.read_text())
    row["status"] = "failed"
    write(path, row)
    result = execute(setup)
    assert result["retained_origin_statuses"]["failed"] == 1
    assert result["remaining_runs"] == 3


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda r: r.update(seed=42), "specification"),
        (lambda r: r.update(manifest_id="wrong"), "manifest"),
        (lambda r: r.update(status="invented"), "status"),
        (lambda r: r.update(engine_provenance={}), "engine_provenance"),
        (lambda r: r.update(problem_provenance={}), "problem_provenance"),
        (lambda r: r.update(solver_metadata={}), "solver_metadata"),
        (lambda r: r.update(evaluation_count=2), "count"),
        (lambda r: r.update(best_f=None), "incumbent"),
        (lambda r: r.update(best_f=-1), "observations"),
        (lambda r: r["trace"][0].update(status="failed"), "Failed observation"),
        (lambda r: r["trace"][0].update(evaluation=2), "trace"),
    ],
)
def test_corrupt_origin_checkpoint_is_rejected_before_execution(setup, change, match):
    path = setup.origin / "runs" / (setup.specs[0]["id"] + ".json")
    row = json.loads(path.read_text())
    change(row)
    write(path, row)
    with pytest.raises(ValueError, match=match):
        execute(setup, run=True)
    assert not setup.calls and not setup.output.exists()


@pytest.mark.parametrize(
    "raw", ['{"bad":NaN}', '{"bad":Infinity}', '{"bad":1e999}', '{"id":1,"id":2}']
)
def test_nonfinite_and_duplicate_json_are_rejected(tmp_path, raw):
    path = tmp_path / "invalid.json"
    path.write_text(raw)
    with pytest.raises(ValueError):
        continuation._read(path)


def test_changed_origin_checkpoint_bytes_prevent_existing_continuation_resume(setup):
    execute(setup, run=True)
    path = setup.origin / "runs" / (setup.specs[1]["id"] + ".json")
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="Existing continuation manifest differs"):
        execute(setup, run=True)


def test_origin_manifest_tamper_duplicate_specs_and_unknown_records(setup):
    path = setup.origin / "manifest.json"
    raw = json.loads(path.read_text())
    raw["master_seed"] = 42
    write(path, raw)
    with pytest.raises(ValueError, match="digest"):
        execute(setup)
    raw = copy.deepcopy(setup.original)
    raw["runs"].append(raw["runs"][0])
    raw.pop("manifest_id")
    raw["manifest_id"] = continuation._digest(raw)
    write(path, raw)
    with pytest.raises(ValueError, match="Duplicate scheduled"):
        execute(setup)
    write(path, setup.original)
    write(setup.origin / "runs/extra.json", {"id": "extra"})
    with pytest.raises(ValueError, match="Unknown"):
        execute(setup)


def test_changed_source_or_target_model_cannot_continue(setup):
    path = setup.source / "replication.py"
    previous = path.read_bytes()
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Frozen source"):
        execute(setup)
    path.write_bytes(previous)
    setup.target["problem_definitions"]["1"]["dimension"] = 99
    with pytest.raises(ValueError, match="Target problem_definitions"):
        execute(setup)


def test_changed_nonmodule_frozen_asset_changes_continuation_identity(setup):
    execute(setup, run=True)
    (setup.source / "data.json").write_text("{}")
    with pytest.raises(ValueError, match="Existing continuation manifest differs"):
        execute(setup)


def test_origin_is_never_used_as_output_and_foreign_lock_is_not_copied(setup):
    with pytest.raises(ValueError, match="separate"):
        continuation.continue_replication(setup.origin, setup.project, setup.origin)
    execute(setup, run=True)
    assert (setup.origin / "experiment.lock").exists()
    assert not (setup.output / "experiment.lock").exists()


def test_duplicate_controller_lock_blocks_work(setup):
    setup.output.mkdir()
    with replication._experiment_lock(setup.output):
        with pytest.raises(RuntimeError, match="already holds"):
            execute(setup, run=True)
    assert not setup.calls


def test_worker_crash_is_recorded_and_leaves_resumable_interrupted_status(setup):
    def broken(*args):
        raise RuntimeError("worker disappeared")

    setup.runtime._run_one = broken
    result = execute(setup, run=True)
    assert result["summary"]["statuses"]["interrupted"] == 3
    assert (
        json.loads((setup.output / "continuation-status.json").read_text())["status"]
        == "interrupted"
    )
    rows = [json.loads(p.read_text()) for p in (setup.output / "runs").glob("*.json")]
    assert all(r["error"]["reason"] == "worker-process-failure" for r in rows)
    assert execute(setup)["remaining_runs"] == 3


@pytest.mark.parametrize("workers", [0, -1, True, 1.5])
def test_invalid_worker_count_never_submits_work(setup, workers):
    with pytest.raises(ValueError, match="workers"):
        execute(setup, workers=workers)
    assert not setup.calls


def test_partition_load_balance_and_determinism():
    specs = [{"id": str(i), "budget": 1100 if i < 30 else 500} for i in range(120)]
    partitions = continuation.pool_partition(specs, 120)
    assert partitions == continuation.pool_partition(list(reversed(specs)), 120)
    assert [size for size, _ in partitions] == [60, 60]
    assert (
        abs(sum(x["budget"] for x in partitions[0][1]) - sum(x["budget"] for x in partitions[1][1]))
        <= 1100
    )


def test_cli_defaults_to_plan_and_append_log_captures_errors(setup, capsys):
    log = setup.output / "coordinator.jsonl"
    argv = [
        "--origin",
        str(setup.origin),
        "--project-root",
        str(setup.project),
        "--output-root",
        str(setup.output),
        "--log-file",
        str(log),
    ]
    assert continuation.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "plan-only"
    assert not setup.calls
    assert continuation.main([*argv, "--run"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "run"
    assert len(log.read_text().splitlines()) >= 4
    with pytest.raises(ValueError):
        continuation.main([*argv, "--workers", "0"])
    last = json.loads(log.read_text().splitlines()[-1])
    assert last["status"] == "error" and last["type"] == "ValueError"


def test_cli_reports_nonzero_for_interrupted_or_failed_work(setup, capsys):
    def broken(*args):
        raise RuntimeError("worker failed")

    setup.runtime._run_one = broken
    argv = [
        "--origin",
        str(setup.origin),
        "--project-root",
        str(setup.project),
        "--output-root",
        str(setup.output),
        "--run",
    ]
    assert continuation.main(argv) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["summary"]["statuses"]["interrupted"] == 3


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_terminal_failures_exit_nonzero_and_are_not_retried(setup, status, capsys):
    def reject(spec, manifest, root, retain):
        write(Path(root) / "runs" / (spec["id"] + ".json"), record(spec, manifest, status))

    setup.runtime._run_one = reject
    argv = [
        "--origin",
        str(setup.origin),
        "--project-root",
        str(setup.project),
        "--output-root",
        str(setup.output),
        "--run",
    ]
    assert continuation.main(argv) == 1
    assert json.loads(capsys.readouterr().out)["summary"]["statuses"][status] == 3
    assert (
        json.loads((setup.output / "continuation-status.json").read_text())["status"]
        == "finished-with-failures"
    )
    setup.pools.clear()
    assert continuation.main(argv) == 1
    assert not setup.pools


def test_missing_worker_records_are_incomplete_not_finished(setup, capsys):
    setup.runtime._run_one = lambda *args: None
    argv = [
        "--origin",
        str(setup.origin),
        "--project-root",
        str(setup.project),
        "--output-root",
        str(setup.output),
        "--run",
    ]
    assert continuation.main(argv) == 1
    assert json.loads(capsys.readouterr().out)["mode"] == "run"
    assert (
        json.loads((setup.output / "continuation-status.json").read_text())["status"]
        == "interrupted"
    )


def test_log_cannot_modify_origin_even_when_cli_fails(setup):
    path = setup.origin / "manifest.json"
    before = path.read_bytes()
    argv = [
        "--origin",
        str(setup.origin),
        "--project-root",
        str(setup.project),
        "--output-root",
        str(setup.output),
        "--log-file",
        str(path),
    ]
    with pytest.raises(SystemExit) as error:
        continuation.main(argv)
    assert error.value.code == 2 and path.read_bytes() == before


@pytest.mark.parametrize("kind", ["source", "model", "manifest", "checkpoint", "summary", "lock"])
def test_log_collisions_are_rejected_without_changing_evidence(setup, kind):
    execute(setup, run=True)
    model = setup.source / "data/model.epJSON"
    model.parent.mkdir()
    model.write_text('{"model":"immutable"}')
    paths = {
        "source": setup.source / "replication.py",
        "model": model,
        "manifest": setup.output / "manifest.json",
        "checkpoint": setup.output / "runs" / (setup.specs[1]["id"] + ".json"),
        "summary": setup.output / "summary.json",
        "lock": setup.output / "experiment.lock",
    }
    path = paths[kind]
    if kind == "lock":
        path.write_text('{"owner":"immutable"}')
    before = {p: p.read_bytes() for p in paths.values() if p.exists()}
    setup.calls.clear()
    with pytest.raises(ValueError, match="independent .log"):
        execute(setup, run=True, log_file=path)
    argv = [
        "--origin",
        str(setup.origin),
        "--project-root",
        str(setup.project),
        "--output-root",
        str(setup.output),
        "--log-file",
        str(path),
        "--run",
    ]
    with pytest.raises(SystemExit) as error:
        continuation.main(argv)
    assert error.value.code == 2
    assert not setup.calls
    assert all(p.read_bytes() == raw for p, raw in before.items())


@pytest.mark.parametrize(
    "folder", ["origin", "frozen", "src", ".cache", ".tools", ".reference-cache"]
)
def test_output_cannot_be_nested_in_source_or_input_folders(setup, folder):
    frozen = setup.source.parents[1]
    parent = {"origin": setup.origin, "frozen": frozen}.get(folder, setup.project / folder)
    output = parent / "new-results"
    with pytest.raises(ValueError, match="separate"):
        continuation.continue_replication(
            setup.origin, setup.project, output, frozen_source=frozen, run=True
        )
    assert not output.exists() and not setup.calls


def test_log_hardlink_cannot_overwrite_source(setup):
    setup.output.mkdir()
    source = setup.source / "replication.py"
    log = setup.output / "controller.log"
    before = source.read_bytes()
    try:
        continuation.os.link(source, log)
    except OSError:
        pytest.skip("Filesystem does not support hard links")
    with pytest.raises(ValueError, match="independent .log"):
        execute(setup, log_file=log)
    assert source.read_bytes() == before


def test_fresh_interpreter_spawns_only_selected_frozen_package(setup, tmp_path):
    # The toy runtime uses only Python and JSON, never a native EnergyPlus process.
    package = setup.source
    (package / "__init__.py").write_text("")
    (package / "replication.py").write_text(
        textwrap.dedent("""\
        import json, os
        from pathlib import Path
        from collections import Counter
        from contextlib import contextmanager
        def prepare_manifest(**configuration):
            return json.loads((configuration['project_root'] / 'target.json').read_text())
        def _atomic_json(path, value):
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
        @contextmanager
        def _experiment_lock(root):
            yield
        def _run_one(spec, manifest, root, retain):
            point = spec['x0']
            row = dict(spec, manifest_id=manifest['manifest_id'], status='completed', attempt=1,
                       evaluation_count=1, best_x=point, best_f=sum(point), elapsed_seconds=0,
                       trace=[dict(evaluation=1, status='success', x=point, f=sum(point))],
                       problem_provenance=manifest['problem_definitions'][str(spec['problem'])],
                       engine_provenance=manifest['engines'][spec['version']],
                       solver_metadata=manifest['solvers'][spec['solver']],
                       loaded_source=__file__, worker_pid=os.getpid(),
                       thread_settings={k:os.environ[k] for k in
                                        ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS']})
            _atomic_json(Path(root) / 'runs' / (spec['id']+'.json'), row)
        def _summary(root, manifest, workers):
            rows=[json.loads(p.read_text()) for p in (Path(root)/'runs').glob('*.json')]
            result=dict(statuses=dict(Counter(r['status'] for r in rows)))
            _atomic_json(Path(root)/'summary.json', result)
            return result
    """)
    )
    original = setup.original
    original["code_sha256"] = {"replication.py": sha256_file(package / "replication.py")}
    original.pop("manifest_id")
    original["manifest_id"] = continuation._digest(original)
    write(setup.origin / "manifest.json", original)
    for i, status in [(0, "completed"), (1, "interrupted")]:
        write(
            setup.origin / "runs" / (setup.specs[i]["id"] + ".json"),
            record(setup.specs[i], original, status),
        )
    target = copy.deepcopy(setup.target)
    target["code_sha256"] = original["code_sha256"]
    write(setup.project / "target.json", target)
    output = tmp_path / "real-spawn-output"
    command = [
        sys.executable,
        str(continuation.__file__),
        "--origin",
        str(setup.origin),
        "--project-root",
        str(setup.project),
        "--output-root",
        str(output),
        "--frozen-source",
        str(package.parents[1]),
        "--workers",
        "2",
        "--run",
    ]
    before = {p.relative_to(package): p.read_bytes() for p in package.rglob("*") if p.is_file()}
    environment = dict(continuation.os.environ)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    result = subprocess.run(command, text=True, capture_output=True, timeout=30, env=environment)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["summary"]["statuses"] == {"completed": 3}
    rows = [json.loads(p.read_text()) for p in (output / "runs").glob("*.json")]
    assert all(Path(r["loaded_source"]).resolve() == package / "replication.py" for r in rows)
    coordinator = json.loads((output / "continuation-status.json").read_text())["pid"]
    assert all(r["worker_pid"] != coordinator for r in rows)
    assert all(set(r["thread_settings"].values()) == {"1"} for r in rows)
    assert before == {
        p.relative_to(package): p.read_bytes() for p in package.rglob("*") if p.is_file()
    }
    assert not list(package.rglob("__pycache__"))


def test_runtime_bootstrap_sets_threads_before_import_and_selects_source(tmp_path, monkeypatch):
    source = tmp_path / "frozen/src/bem_testproblems"
    source.mkdir(parents=True)
    (source / "replication.py").write_text("# frozen")
    monkeypatch.delitem(sys.modules, "bem_testproblems")
    runtime = SimpleNamespace(__file__=str(source / "replication.py"))

    def load(name):
        assert all(continuation.os.environ[k] == "1" for k in continuation.THREAD_VARIABLES)
        assert sys.dont_write_bytecode is True
        assert continuation.os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
        return runtime

    monkeypatch.setattr(continuation.importlib, "import_module", load)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "explicit-matplotlib"))
    for key in (
        *continuation.THREAD_VARIABLES,
        "PYTHONPATH",
        "BEM_REFERENCE_DIR",
        "PYTHONDONTWRITEBYTECODE",
    ):
        monkeypatch.setenv(key, "previous")
    assert continuation._load_runtime(tmp_path / "project", tmp_path / "frozen") is runtime
    assert continuation.os.environ["BEM_REFERENCE_DIR"] == str(
        tmp_path / "project/.reference-cache/beobenchmark"
    )
    assert sys.path[0] == str(source.parent)
    assert continuation.os.environ["MPLCONFIGDIR"] == str(tmp_path / "explicit-matplotlib")


def test_bootstrap_rejects_wrong_loaded_package_and_missing_source(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    for key in (*continuation.THREAD_VARIABLES, "PYTHONDONTWRITEBYTECODE", "MPLCONFIGDIR"):
        monkeypatch.setenv(key, continuation.os.environ.get(key, ""))
    with pytest.raises(FileNotFoundError):
        continuation._load_runtime(tmp_path, None)
    source = tmp_path / "src/bem_testproblems"
    source.mkdir(parents=True)
    (source / "replication.py").write_text("# isolated")
    with pytest.raises(ValueError, match="Another benchmark package"):
        continuation._load_runtime(tmp_path, None)
