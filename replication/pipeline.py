# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Run explicit replication stages from one project-local configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGES = (
    "status",
    "preflight",
    "pilot",
    "plan",
    "run",
    "review",
    "replay-plan",
    "replay",
    "export-preview",
    "export",
    "check-export",
)
PRIVATE = (
    "origin",
    "frozen_source",
    "continuation",
    "preflight",
    "pilot",
    "review",
    "replay",
    "preview",
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_config(path, project_root):
    project = Path(project_root).resolve()
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported pipeline configuration")
    for value in (
        config["workers"],
        config["pilot"]["workers"],
        config["pilot"]["repetitions"],
        config["pilot"]["budget"],
    ):
        if type(value) is not int or value < 1:
            raise ValueError("Worker counts, repetitions, and budgets must be positive integers")
    paths = {key: (project / value).resolve() for key, value in config["paths"].items()}
    if set(paths) != {*PRIVATE, "publication"}:
        raise ValueError("Pipeline paths must contain exactly the documented entries")
    private_root = project / ".validation-local"
    if any(
        not paths[key].is_relative_to(private_root) or paths[key] == private_root for key in PRIVATE
    ):
        raise ValueError("Private workflow folders must be inside .validation-local")
    if not paths["publication"].is_relative_to(project / "replication/results"):
        raise ValueError("Publication must be inside replication/results")
    for index, key in enumerate(PRIVATE):
        if any(
            paths[key].is_relative_to(paths[other]) or paths[other].is_relative_to(paths[key])
            for other in PRIVATE[index + 1 :]
        ):
            raise ValueError("Private input and output folders must be separate")
    manifest = json.loads((paths["origin"] / "manifest.json").read_text(encoding="utf-8"))
    if any(not re.fullmatch(r"\d+\.\d+\.\d+", version) for version in manifest["engines"]):
        raise ValueError("Invalid engine version in origin manifest")
    return config, paths, manifest


def environment():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
    for key in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        env[key] = "1"
    return env


def commands(stage, config, paths, manifest, project):
    """Build argument lists; shell parsing is never used."""

    def tool(name, *args):
        return [sys.executable, str(ROOT / "tools" / name), *map(str, args)]

    joined = ["--origin", paths["origin"]]
    if (paths["continuation"] / "manifest.json").exists():
        joined += ["--continuation", paths["continuation"]]
    continuation = [
        "--origin",
        paths["origin"],
        "--frozen-source",
        paths["frozen_source"],
        "--project-root",
        project,
        "--output-root",
        paths["continuation"],
        "--workers",
        config["workers"],
    ]
    if stage in {"plan", "run"}:
        return [
            tool(
                "continue_replication.py",
                *continuation,
                *(
                    ["--run", "--log-file", paths["continuation"] / "controller.log"]
                    if stage == "run"
                    else ["--plan-only"]
                ),
            )
        ]
    if stage == "preflight":
        executable = "energyplus.exe" if os.name == "nt" else "energyplus"
        attempt = 1
        while (paths["preflight"] / f"attempt-{attempt:04}").exists():
            attempt += 1
        attempt_root = paths["preflight"] / f"attempt-{attempt:04}"
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
                attempt_root / version / "cases",
                "--output",
                attempt_root / f"{version}.json",
            )
            for version in manifest["engines"]
        ]
    if stage == "pilot":
        pilot = config["pilot"]
        return [
            tool(
                "run_replication.py",
                "--project-root",
                project,
                "--output-root",
                paths["pilot"],
                "--problems",
                *pilot["problems"],
                "--solvers",
                *manifest["solvers"],
                "--versions",
                *manifest["engines"],
                "--seed",
                manifest["master_seed"],
                "--workers",
                pilot["workers"],
                "--repetitions",
                pilot["repetitions"],
                "--budget",
                pilot["budget"],
                "--diagnostics-policy",
                "reference-warmup",
            )
        ]
    if stage in {"status", "review"}:
        return [
            tool(
                "review_replication.py",
                *joined,
                *(["--status-only"] if stage == "status" else ["--output-dir", paths["review"]]),
            )
        ]
    if stage in {"replay", "replay-plan"}:
        return [
            tool(
                "replay_replication.py",
                *joined,
                "--frozen-source",
                paths["frozen_source"],
                "--project-root",
                project,
                "--output-dir",
                paths["replay"],
                "--run" if stage == "replay" else "--plan-only",
            )
        ]
    if stage in {"export", "export-preview"}:
        return [
            tool(
                "export_replication.py",
                *joined,
                "--output-dir",
                paths["preview"] if stage == "export-preview" else paths["publication"],
                "--frozen-source",
                paths["frozen_source"],
                "--project-root",
                project,
                *(
                    ["--partial-preview"]
                    if stage == "export-preview"
                    else ["--replay-dir", paths["replay"]]
                ),
            )
        ]
    raise ValueError(f"Unknown stage: {stage}")


def run_command(command, *, capture=False):
    try:
        result = subprocess.run(
            command, check=True, cwd=ROOT, env=environment(), text=True, capture_output=capture
        )
    except subprocess.CalledProcessError as error:
        if capture and error.stderr:
            print(error.stderr, file=sys.stderr)
        raise
    return json.loads(result.stdout) if capture else None


def preflight_identity(plan, paths, manifest):
    inputs = [ROOT / "tools/validate_cases.py", ROOT / "reference/canonical-cases.json"]
    inputs += [
        ROOT / f"reference/baselines/{version}-canonical.json" for version in manifest["engines"]
    ]
    return {
        "destination_manifest_id": plan["manifest_id"],
        "continuation": str(paths["continuation"]),
        "validator_inputs": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
    }


def run_stage(stage, config, paths, manifest, project, *, dry_run=False):
    selected = commands(stage, config, paths, manifest, project)
    if dry_run:
        return {"stage": stage, "dry_run": True, "commands": selected}
    receipt = paths["preflight"] / "preflight-receipt.json"
    if stage in {"preflight", "run"}:
        plan = run_command(commands("plan", config, paths, manifest, project)[0], capture=True)
        identity = preflight_identity(plan, paths, manifest)
        if stage == "run":
            if not receipt.is_file():
                raise ValueError("Run the pipeline preflight before starting the continuation")
            prior = json.loads(receipt.read_text(encoding="utf-8"))
            reports = prior.get("reports", {})
            attempt = prior.get("attempt", "")
            expected = {f"{attempt}/{version}.json" for version in manifest["engines"]}
            if (
                not re.fullmatch(r"attempt-\d{4,}", attempt)
                or prior.get("identity") != identity
                or set(reports) != expected
                or any(
                    not (receipt.parent / name).is_file() or digest(receipt.parent / name) != value
                    for name, value in reports.items()
                )
            ):
                raise ValueError("Preflight evidence changed; run preflight again")
        elif receipt.is_file():
            receipt.unlink()
    for command in selected:
        run_command(command)
    if stage == "preflight":
        report_paths = [Path(command[command.index("--output") + 1]) for command in selected]
        reports = {
            path.relative_to(paths["preflight"]).as_posix(): digest(path) for path in report_paths
        }
        if any(
            json.loads((paths["preflight"] / name).read_text(encoding="utf-8")).get("passed")
            is not True
            for name in reports
        ):
            raise ValueError("A native preflight report did not pass")
        with tempfile.NamedTemporaryFile(
            mode="w", dir=receipt.parent, encoding="utf-8", delete=False
        ) as temporary:
            json.dump(
                {"identity": identity, "attempt": report_paths[0].parent.name, "reports": reports},
                temporary,
                indent=2,
            )
            temporary.write("\n")
        Path(temporary.name).replace(receipt)
    return {"stage": stage, "completed": True}


def check_exports(project, *, dry_run=False):
    """Check only public result packages; no private campaign files are needed."""
    selected = []
    for path in sorted((project / "replication/results").iterdir()):
        if path.name == "README.md" and path.is_file() and not path.is_symlink():
            continue
        if not path.is_dir() or path.is_symlink():
            raise ValueError(f"Unexpected publication entry: {path.name}")
        selected.append(
            [
                sys.executable,
                str(ROOT / "tools/export_replication.py"),
                "--verify-export",
                str(path),
            ]
        )
    if not dry_run:
        for command in selected:
            run_command(command)
    return {
        "stage": "check-export",
        "packages": len(selected),
        "dry_run": dry_run,
        "commands": selected,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=STAGES, nargs="?", default="status")
    parser.add_argument("--config", type=Path, default=ROOT / "replication/continuation.json")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without launching any process"
    )
    args = parser.parse_args(argv)
    if args.stage == "check-export":
        result = check_exports(args.project_root.resolve(), dry_run=args.dry_run)
    else:
        config, paths, manifest = load_config(args.config, args.project_root)
        result = run_stage(
            args.stage, config, paths, manifest, args.project_root.resolve(), dry_run=args.dry_run
        )
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
