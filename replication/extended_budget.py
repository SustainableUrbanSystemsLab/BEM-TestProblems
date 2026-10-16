# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Plan, validate, and run a separate experiment with larger evaluation budgets."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGES = (
    "plan",
    "preflight",
    "pilot",
    "run",
    "status",
    "review",
    "replay-plan",
    "replay",
    "export-preview",
    "export",
    "check-export",
)
PRIVATE = ("source", "plan", "campaign", "preflight", "pilot", "review", "replay", "preview")
PROBLEMS = (1, 2, 3, 4, 5, 6, 8, 9, 10, 13)
VERSIONS = ("8.5.0", "26.2.0")
SOLVERS = ("direct", "crs2", "sbplex", "cma_es", "bobyqa", "pybobyqa")
THREADS = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, encoding="utf-8", delete=False
    ) as temporary:
        json.dump(value, temporary, indent=2, allow_nan=False)
        temporary.write("\n")
    Path(temporary.name).replace(path)


def load_config(path, project):
    project = Path(project).resolve()
    config = read(path)
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported extended-budget configuration")
    for number in (
        config["workers"],
        config["repetitions"],
        config["budget_multiplier"],
        config["seed"],
        config["pilot"]["workers"],
        config["pilot"]["repetitions"],
        config["pilot"]["budget"],
    ):
        if type(number) is not int or number < 1:
            raise ValueError(
                "Worker counts, seeds, repetitions, and budgets must be positive integers"
            )
    if config["budget_multiplier"] < 100:
        raise ValueError("The extended experiment requires at least 100 times the paper budgets")
    if config["problems"] != list(PROBLEMS) or config["versions"] != list(VERSIONS):
        raise ValueError("The extended experiment must include all ten problems and both engines")
    if (
        not config["solvers"]
        or len(set(config["solvers"])) != len(config["solvers"])
        or not set(config["solvers"]) <= set(SOLVERS)
    ):
        raise ValueError("Select distinct implemented solvers")
    pilot = config["pilot"]
    if (
        not pilot["problems"]
        or len(set(pilot["problems"])) != len(pilot["problems"])
        or not set(pilot["problems"]) <= set(PROBLEMS)
    ):
        raise ValueError("Select distinct pilot problems from the ten continuous problems")
    paths = {name: (project / value).resolve() for name, value in config["paths"].items()}
    if set(paths) != {*PRIVATE, "publication"}:
        raise ValueError("Workflow paths must contain exactly the documented entries")
    private = project / ".validation-local"
    if any(not paths[name].is_relative_to(private) or paths[name] == private for name in PRIVATE):
        raise ValueError("Private workflow folders must be inside .validation-local")
    if (
        not paths["publication"].is_relative_to(project / "replication/results")
        or paths["publication"] == project / "replication/results"
    ):
        raise ValueError("Publication must be inside replication/results")
    for index, name in enumerate(PRIVATE):
        if any(
            paths[name].is_relative_to(paths[other]) or paths[other].is_relative_to(paths[name])
            for other in PRIVATE[index + 1 :]
        ):
            raise ValueError("Private source and output folders must be separate")
    return config, paths


def environment(project, source):
    env = os.environ.copy()
    env.update(dict.fromkeys(THREADS, "1"))
    env.update(
        PYTHONPATH=str(source / "src"),
        PYTHONDONTWRITEBYTECODE="1",
        BEM_REFERENCE_DIR=str(project / ".reference-cache/beobenchmark"),
    )
    env.setdefault("MPLCONFIGDIR", str(project / ".cache/matplotlib"))
    return env


def source_identity(source):
    if not (source / "src/bem_testproblems/replication.py").is_file():
        raise ValueError("Source snapshot is incomplete")
    for path in (source / "src").rglob("*"):
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError("Source snapshots cannot contain symbolic links or external files")
    return {
        path.relative_to(source).as_posix(): file_digest(path)
        for path in sorted((source / "src").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def snapshot_source(source):
    if source.exists():
        if not (source / "src/bem_testproblems/replication.py").is_file():
            raise ValueError("Source snapshot is incomplete; use a separate experiment folder")
        if source_identity(source) != source_identity(ROOT):
            raise ValueError(
                "Unplanned source snapshot differs from this checkout; use a new folder"
            )
        return
    source.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="source-", dir=source.parent))
    try:
        source_identity(ROOT)
        shutil.copytree(
            ROOT / "src", temporary / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        temporary.rename(source)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def manifest(config, paths, project):
    """Probe installed versions and bind native inputs; this does not optimize."""
    os.environ.update(environment(project, paths["source"]))
    sys.dont_write_bytecode = True
    package = paths["source"] / "src/bem_testproblems"
    loaded = sys.modules.get("bem_testproblems")
    if loaded is not None and Path(loaded.__file__).resolve().parent != package:
        raise ValueError("Use a fresh interpreter for the frozen extended experiment")
    sys.path.insert(0, str(paths["source"] / "src"))
    runtime = importlib.import_module("bem_testproblems.replication")
    if Path(runtime.__file__).resolve().parent != package:
        raise ValueError("Loaded source differs from the extended experiment snapshot")
    return runtime.prepare_manifest(
        problems=config["problems"],
        solvers=config["solvers"],
        versions=config["versions"],
        repetitions=config["repetitions"],
        budget_multiplier=config["budget_multiplier"],
        seed=config["seed"],
        project_root=project,
        diagnostics_policy="strict",
        schedule="balanced",
    )


def identity(config, paths, project):
    validators = [
        ROOT / "tools/validate_cases.py",
        ROOT / "tools/run_replication.py",
        Path(__file__).resolve(),
        ROOT / "reference/canonical-cases.json",
    ]
    validators += [
        ROOT / f"reference/baselines/{version}-canonical.json" for version in config["versions"]
    ]
    return {
        "configuration": config,
        "project_root": str(project),
        "source_sha256": source_identity(paths["source"]),
        "driver_inputs": {
            path.relative_to(ROOT).as_posix(): file_digest(path) for path in validators
        },
        "runtime": {
            "host": socket.gethostname(),
            "python": sys.version,
            "platform": platform.platform(),
            "executable_sha256": file_digest(sys.executable),
        },
    }


def plan(config, paths, project):
    target = paths["plan"] / "plan.json"
    if not target.exists():
        if paths["campaign"].exists() and any(paths["campaign"].iterdir()):
            raise ValueError("Campaign data exists without its immutable plan")
        snapshot_source(paths["source"])
        value = {
            "identity": identity(config, paths, project),
            "manifest": manifest(config, paths, project),
        }
        write(target, value)
    else:
        value = read(target)
        if value["identity"] != identity(config, paths, project) or value["manifest"] != manifest(
            config, paths, project
        ):
            raise ValueError(
                "Extended experiment identity changed; preserve it and use a new folder"
            )
    return value


def tool(name, *args):
    return [sys.executable, str(ROOT / "tools" / name), *map(str, args)]


def commands(stage, config, paths, project):
    if stage in {"run", "pilot"}:
        pilot = config["pilot"]
        return [
            tool(
                "run_replication.py",
                "--project-root",
                project,
                "--output-root",
                paths["pilot"] if stage == "pilot" else paths["campaign"],
                "--problems",
                *(pilot["problems"] if stage == "pilot" else config["problems"]),
                "--solvers",
                *config["solvers"],
                "--versions",
                *config["versions"],
                "--seed",
                config["seed"],
                "--workers",
                pilot["workers"] if stage == "pilot" else config["workers"],
                "--repetitions",
                pilot["repetitions"] if stage == "pilot" else config["repetitions"],
                *(
                    ["--budget", pilot["budget"]]
                    if stage == "pilot"
                    else ["--budget-multiplier", config["budget_multiplier"]]
                ),
                "--diagnostics-policy",
                "strict",
                "--schedule",
                "balanced",
            )
        ]
    if stage == "preflight":
        executable = "energyplus.exe" if os.name == "nt" else "energyplus"
        attempt = 1
        while (paths["preflight"] / f"attempt-{attempt:04}").exists():
            attempt += 1
        root = paths["preflight"] / f"attempt-{attempt:04}"
        return [
            tool(
                "validate_cases.py",
                "--engine",
                project / ".tools/energyplus" / version / executable,
                "--version",
                version,
                "--weather-dir",
                project / ".cache/weather",
                "--weather-kind",
                "canonical",
                "--cases",
                ROOT / "reference/canonical-cases.json",
                "--baseline",
                ROOT / f"reference/baselines/{version}-canonical.json",
                "--work-dir",
                root / version / "cases",
                "--output",
                root / f"{version}.json",
            )
            for version in config["versions"]
        ]
    if stage in {"status", "review"}:
        return [
            tool(
                "review_replication.py",
                "--origin",
                paths["campaign"],
                *(["--status-only"] if stage == "status" else ["--output-dir", paths["review"]]),
            )
        ]
    if stage in {"replay-plan", "replay"}:
        return [
            tool(
                "replay_replication.py",
                "--origin",
                paths["campaign"],
                "--frozen-source",
                paths["source"],
                "--project-root",
                project,
                "--output-dir",
                paths["replay"],
                "--run" if stage == "replay" else "--plan-only",
            )
        ]
    if stage in {"export-preview", "export"}:
        return [
            tool(
                "export_replication.py",
                "--origin",
                paths["campaign"],
                "--frozen-source",
                paths["source"],
                "--project-root",
                project,
                "--output-dir",
                paths["preview"] if stage == "export-preview" else paths["publication"],
                *(
                    ["--partial-preview"]
                    if stage == "export-preview"
                    else ["--replay-dir", paths["replay"]]
                ),
            )
        ]
    if stage == "check-export":
        return [tool("export_replication.py", "--verify-export", paths["publication"])]
    if stage == "plan":
        return []
    raise ValueError(f"Unknown stage: {stage}")


def run_command(command, project, source, *, capture=False, log=None):
    options = {"cwd": ROOT, "env": environment(project, source), "check": True, "text": True}
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, **options)
        return None
    result = subprocess.run(command, capture_output=capture, **options)
    return json.loads(result.stdout) if capture else None


def receipt(path, binding, files):
    write(
        path,
        {
            "plan_sha256": digest(binding),
            "files": {str(file.relative_to(path.parent)): file_digest(file) for file in files},
        },
    )


def require_receipt(path, binding):
    if not path.is_file():
        raise ValueError(f"Complete the {path.parent.name} stage before running")
    value = read(path)
    files = value.get("files", {})
    if (
        value.get("plan_sha256") != digest(binding)
        or not files
        or any(
            Path(name).is_absolute()
            or not (path.parent / name).resolve().is_relative_to(path.parent.resolve())
            or not (path.parent / name).is_file()
            or file_digest(path.parent / name) != expected
            for name, expected in files.items()
        )
    ):
        raise ValueError(f"{path.parent.name} evidence changed; repeat that stage")


def run_stage(stage, config, paths, project, *, dry_run=False):
    selected = commands(stage, config, paths, project)
    if dry_run:
        return {
            "stage": stage,
            "dry_run": True,
            "commands": selected,
            "budget_rule": f"100*(dimension+1)*{config['budget_multiplier']}",
        }
    if stage in {
        "status",
        "review",
        "replay-plan",
        "replay",
        "export-preview",
        "export",
        "check-export",
    }:
        if stage == "status" and not (paths["campaign"] / "manifest.json").exists():
            return {
                "stage": stage,
                "started": False,
                "plan_exists": (paths["plan"] / "plan.json").is_file(),
            }
        for command in selected:
            run_command(command, project, paths["source"])
        return {"stage": stage, "completed": True}
    binding = plan(config, paths, project)
    if stage == "plan":
        runs = binding["manifest"]["runs"]
        return {
            "stage": stage,
            "manifest_id": binding["manifest"]["manifest_id"],
            "planned_runs": len(runs),
            "evaluation_ceiling": sum(row["budget"] for row in runs),
            "plan": str(paths["plan"] / "plan.json"),
        }
    preflight = paths["preflight"] / "receipt.json"
    pilot_receipt = paths["pilot"] / "receipt.json"
    if stage in {"pilot", "run"}:
        require_receipt(preflight, binding)
    if stage == "run":
        require_receipt(pilot_receipt, binding)
        existing = paths["campaign"] / "manifest.json"
        if existing.exists() and read(existing) != binding["manifest"]:
            raise ValueError("Existing campaign differs from its immutable extended plan")
    invalidated = preflight if stage == "preflight" else pilot_receipt if stage == "pilot" else None
    if invalidated and invalidated.exists():
        invalidated.unlink()
    for command in selected:
        run_command(
            command,
            project,
            paths["source"],
            log=paths["campaign"] / "controller.log" if stage == "run" else None,
        )
    if stage == "preflight":
        reports = [Path(command[command.index("--output") + 1]) for command in selected]
        if any(read(path).get("passed") is not True for path in reports):
            raise ValueError("A canonical native preflight did not pass")
        receipt(preflight, binding, reports)
    elif stage == "pilot":
        status = run_command(
            tool("review_replication.py", "--origin", paths["pilot"], "--status-only"),
            project,
            paths["source"],
            capture=True,
        )
        expected = (
            len(config["pilot"]["problems"])
            * len(config["solvers"])
            * len(config["versions"])
            * config["pilot"]["repetitions"]
        )
        if status["planned"] != expected or status["terminal"] != expected:
            raise ValueError("The timing pilot is incomplete; inspect its checkpoints")
        records = [read(path) for path in (paths["pilot"] / "runs").glob("*.json")]
        for version in config["versions"]:
            if not any(
                row["version"] == version
                and row["status"] in {"completed", "budget_exhausted"}
                and row.get("strict_benchmark_evaluation") is True
                and row.get("warmup_severe_evaluations_used", 0) == 0
                for row in records
            ):
                raise ValueError(f"No strict timing-pilot trajectory succeeded for {version}")
        receipt(
            pilot_receipt,
            binding,
            [
                paths["pilot"] / "manifest.json",
                paths["pilot"] / "summary.json",
                *sorted((paths["pilot"] / "runs").glob("*.json")),
            ],
        )
    elif stage == "run":
        if read(paths["campaign"] / "manifest.json") != binding["manifest"]:
            raise ValueError("Campaign manifest differs from its immutable extended plan")
        status = run_command(
            tool("review_replication.py", "--origin", paths["campaign"], "--status-only"),
            project,
            paths["source"],
            capture=True,
        )
        if status["terminal"] != len(binding["manifest"]["runs"]):
            raise ValueError(
                "The extended campaign is interrupted; inspect its controller log and status"
            )
        return {"stage": stage, "completed": True, "status": status}
    return {"stage": stage, "completed": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=STAGES, nargs="?", default="status")
    parser.add_argument("--config", type=Path, default=ROOT / "replication/extended-budget.json")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    project = args.project_root.resolve()
    config, paths = load_config(args.config, project)
    result = run_stage(args.stage, config, paths, project, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
