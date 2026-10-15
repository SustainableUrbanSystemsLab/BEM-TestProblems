#!/usr/bin/env python3
"""Transition rendered 8.5 models once, retaining an auditable official-tool chain.

This is a maintainer tool, not part of an objective evaluation. Obtain the old
8.4--9.0 transitions from the official EnergyPlus helpdesk and the remaining
transitions plus ConvertInputFormat from the pinned 26.2 installation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

VERSIONS = (
    "8-5-0", "8-6-0", "8-7-0", "8-8-0", "8-9-0", "9-0-0",
    "9-1-0", "9-2-0", "9-3-0", "9-4-0", "9-5-0", "9-6-0",
    "22-1-0", "22-2-0", "23-1-0", "23-2-0", "24-1-0", "24-2-0",
    "25-1-0", "25-2-0", "26-1-0", "26-2-0",
)
UPSTREAM_COMMIT = "54736a6b899a488222ad3184f306c1f401daf4f9"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def idf_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    text = "\n".join(line.split("!", 1)[0] for line in text.splitlines())
    match = re.search(r"(?:^|;)\s*version\s*,\s*([^;,\s]+)", text, re.IGNORECASE)
    if not match:
        raise ValueError(f"No Version object in {path}")
    fields = match.group(1).split(".")
    return "-".join(fields + ["0"] * (3 - len(fields)))


def executable(directory: Path, name: str) -> Path:
    for suffix in ("", ".exe"):
        candidate = directory / (name + suffix)
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Missing official tool {name} in {directory}")


def normalize_setpoint_manager_names(text: str) -> tuple[str, list[dict]]:
    """Resolve old cross-type names rejected by the 24.2 global-name check.

    Only an unreferenced MixedAir name shared with a Scheduled manager is
    safe to rename automatically. Object fields and control nodes stay intact.
    """
    pattern = re.compile(
        r"(?im)^[ \t]*(SetpointManager:[A-Za-z]+)[ \t]*,[ \t]*(?:![^\r\n]*)?\r?\n"
        r"[ \t]*([^!,\r\n]+)"
    )
    matches = list(pattern.finditer(text))
    groups: dict[str, list] = {}
    for match in matches:
        groups.setdefault(match.group(2).strip().casefold(), []).append(match)
    uncommented = "\n".join(line.split("!", 1)[0] for line in text.splitlines())
    fields = [field.strip().casefold() for field in re.split("[,;]", uncommented)]
    replacements = []
    adjustments = []
    for name, duplicates in groups.items():
        if len(duplicates) < 2:
            continue
        kinds = {match.group(1).casefold() for match in duplicates}
        if len(duplicates) != 2 or kinds != {
            "setpointmanager:scheduled", "setpointmanager:mixedair"
        } or fields.count(name) != 2:
            raise ValueError(f"Duplicate SetpointManager name needs manual review: {name}")
        mixed = next(match for match in duplicates if match.group(1).casefold().endswith(":mixedair"))
        old = mixed.group(2).strip()
        new = old + "__MixedAir"
        if new.casefold() in groups or new.casefold() in fields:
            raise ValueError(f"SetpointManager replacement name already exists: {new}")
        start, end = mixed.span(2)
        trailing = mixed.group(2)[len(mixed.group(2).rstrip()):]
        replacements.append((start, end, new + trailing))
        adjustments.append({
            "object_type": "SetpointManager:MixedAir", "old_name": old, "new_name": new,
            "reason": "EnergyPlus 24.2 requires unique names across SetpointManager types; no name references exist",
        })
    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text, adjustments


def _call(command: list[str], cwd: Path, log: Path, timeout: float) -> float:
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as error:
        log.write_text(f"Tool timed out after {timeout:g} seconds\n")
        raise RuntimeError(f"Transition tool timed out; see {log}") from error
    log.write_text(result.stdout + "\nSTDERR\n" + result.stderr)
    if result.returncode:
        raise RuntimeError(f"Official tool exited {result.returncode}; see {log}")
    return time.monotonic() - started


def transition_model(input_idf: str | Path, output_epjson: str | Path, *,
                     energyplus_root: str | Path, historical_dir: str | Path,
                     source_template: str | Path | None = None,
                     parameters: dict | None = None, timeout: float = 60.0,
                     audit_directory: str | Path | None = None,
                     minimum_max_warmup_days: int | None = None) -> dict:
    """Create one 26.2 epJSON and provenance sidecar; preserve all input files."""
    source = Path(input_idf).resolve(strict=True)
    target = Path(output_epjson).resolve()
    if target.suffix.lower() != ".epjson":
        raise ValueError("output_epjson must have .epJSON extension")
    text = source.read_text(encoding="utf-8-sig", errors="replace")
    uncommented = "\n".join(line.split("!", 1)[0] for line in text.splitlines())
    if re.search(r"%[A-Za-z0-9_]+%", uncommented):
        raise ValueError("Render placeholder values before transitioning an IDF")
    start_version = idf_version(source)
    if start_version not in VERSIONS:
        raise ValueError(f"Unsupported source Version {start_version}")
    engine = Path(energyplus_root).resolve(strict=True)
    historical = Path(historical_dir).resolve(strict=True)
    current = engine / "PreProcess" / "IDFVersionUpdater"
    audit = Path(audit_directory).resolve() if audit_directory else Path(tempfile.mkdtemp(prefix="bem-transition-"))
    audit.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    source_hash = sha256(source)
    previous = source
    steps = []
    input_normalizations = []
    first = VERSIONS.index(start_version)
    for number in range(first, len(VERSIONS) - 1):
        old, new = VERSIONS[number:number + 2]
        tool_dir = historical if number < 5 else current
        tool = executable(tool_dir, f"Transition-V{old}-to-V{new}")
        stage = audit / f"{number + 1:02d}-{old}-to-{new}"
        stage.mkdir(exist_ok=True)
        model = stage / "model.idf"
        shutil.copyfile(previous, model)
        if old == "24-1-0":
            original_hash = sha256(model)
            normalized_text, changes = normalize_setpoint_manager_names(model.read_text())
            if changes:
                model.write_text(normalized_text)
                input_normalizations.append({
                    "before_transition": "24.1.0 to 24.2.0",
                    "input_sha256": original_hash, "normalized_sha256": sha256(model),
                    "changes": changes,
                })
        old_idd = tool_dir / f"V{old}-Energy+.idd"
        new_idd = tool_dir / f"V{new}-Energy+.idd"
        # Historical helpers write fixed-name audit.out scratch files in cwd.
        # Each invocation therefore needs its own cwd as well as its own IDF.
        shutil.copyfile(old_idd, stage / old_idd.name)
        shutil.copyfile(new_idd, stage / new_idd.name)
        report_rules = tool_dir / f"Report Variables {old} to {new}.csv"
        if report_rules.is_file():
            shutil.copyfile(report_rules, stage / report_rules.name)
        elapsed = _call([str(tool), str(model)], stage, stage / "launch.log", timeout)
        if idf_version(model) != new or not model.with_suffix(".idfnew").is_file():
            raise RuntimeError(f"Transition did not produce Version {new}; see {stage}")
        error_files = list(stage.glob("*.VCpErr"))
        if any("fatal" in path.read_text(errors="replace").lower() for path in error_files):
            raise RuntimeError(f"Fatal transition diagnostic; see {stage}")
        steps.append({
            "from": old.replace("-", "."), "to": new.replace("-", "."),
            "tool": tool.name, "tool_sha256": sha256(tool),
            "old_idd_sha256": sha256(old_idd), "new_idd_sha256": sha256(new_idd),
            "output_idf_sha256": sha256(model), "elapsed_seconds": round(elapsed, 6),
        })
        previous = model
    converted = audit / "converted"
    converted.mkdir(exist_ok=True)
    # Older EnergyPlus accepted these section delimiters as bookkeeping. They
    # survive the transition chain but are not simulation objects in epJSON.
    marker = re.compile(r"^[ \t]*(End Lead Input|Simulation Data|End Simulation Data)[ \t]*;[ \t]*(?:!.*)?$",
                        re.IGNORECASE | re.MULTILINE)
    text = previous.read_text(encoding="utf-8-sig", errors="replace")
    removed_markers = [match.group(1) for match in marker.finditer(text)]
    normalized = converted / "model.idf"
    normalized.write_text(marker.sub("", text))
    converter = executable(engine, "ConvertInputFormat")
    _call([str(converter), "-f", "epJSON", "-o", str(converted), str(normalized)],
          converted, converted / "launch.log", timeout)
    candidates = [path for path in converted.iterdir() if path.suffix.lower() == ".epjson"]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one converted epJSON; see {converted}")
    model = json.loads(candidates[0].read_text())
    identifiers = [obj.get("version_identifier") for obj in model.get("Version", {}).values()]
    if len(identifiers) != 1 or str(identifiers[0]) not in {"26.2", "26.2.0"}:
        raise RuntimeError("Converted epJSON does not declare Version 26.2")
    adjustments = []
    if minimum_max_warmup_days is not None:
        if minimum_max_warmup_days <= 0:
            raise ValueError("minimum_max_warmup_days must be positive")
        for name, building in model.get("Building", {}).items():
            old = building.get("maximum_number_of_warmup_days", 25)
            if old < minimum_max_warmup_days:
                building["maximum_number_of_warmup_days"] = minimum_max_warmup_days
                adjustments.append({"object_type": "Building", "object_name": name,
                                    "field": "maximum_number_of_warmup_days", "old": old,
                                    "new": minimum_max_warmup_days,
                                    "reason": "Allow 26.2 warmup to converge without relaxing convergence tolerances"})
    if adjustments:
        target.write_text(json.dumps(model, indent=2) + "\n")
    else:
        shutil.copyfile(candidates[0], target)
    if sha256(source) != source_hash:
        raise RuntimeError("Source input changed during transition")
    template = Path(source_template).resolve(strict=True) if source_template else source
    notices = {
        "path": "../../../../THIRD_PARTY_NOTICES.md",
        "original_notice": "Full original IDF header in the verified external reference cache: models/" + template.name,
        "source_commit_url": "https://github.com/milzj/BEOBenchmark/tree/" + UPSTREAM_COMMIT,
        "reference_cache": ".reference-cache/beobenchmark or BEM_REFERENCE_DIR; original templates are not packaged",
    }
    if "DOE Commercial Building Benchmark" in template.read_text(errors="replace"):
        notices.update({
            "notice": "DOE Commercial Building Benchmark notice",
            "publication_credit": ["DOE", "NREL", "PNNL", "LBNL"],
            "no_endorsement": "Names may not be used in advertising or publicity implying endorsement or promotion of products, services or commercial entities.",
        })
    provenance = {
        "source_repository": "https://github.com/milzj/BEOBenchmark",
        "source_commit": UPSTREAM_COMMIT,
        "copyright": "Copyright (c) 2018, Christoph Waibel. All rights reserved.",
        "license": "BSD-3-Clause", "license_notice": "../licenses/BEOBenchmark-LICENSE.txt",
        "source_template": template.name, "source_template_sha256": sha256(template),
        "rendered_source_sha256": source_hash, "baseline_parameters": parameters,
        "source_version": start_version.replace("-", "."), "target_version": "26.2.0",
        "transition_steps": steps, "format_converter": converter.name,
        "transition_input_normalizations": input_normalizations,
        "format_converter_sha256": sha256(converter),
        "format_converter_output_sha256": sha256(candidates[0]),
        "removed_obsolete_section_markers": removed_markers,
        "normalized_idf_sha256": sha256(normalized),
        "modern_numerical_adjustments": adjustments,
        "output_epjson": target.name, "output_sha256": sha256(target),
        "additional_notices": notices,
        "official_transition_archive": "https://energyplushelp.freshdesk.com/helpdesk/attachments/67089987420",
        "official_engine_release": "https://github.com/NatLabRockies/EnergyPlus/releases/tag/v26.2.0",
    }
    target.with_suffix(".provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_idf", type=Path)
    parser.add_argument("output_epjson", type=Path)
    parser.add_argument("--energyplus-root", required=True, type=Path)
    parser.add_argument("--historical-dir", required=True, type=Path)
    parser.add_argument("--source-template", type=Path)
    parser.add_argument("--audit-directory", type=Path)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--minimum-max-warmup-days", type=int)
    args = parser.parse_args()
    result = transition_model(**vars(args))
    print(json.dumps({"output": result["output_epjson"], "sha256": result["output_sha256"],
                      "steps": len(result["transition_steps"])}, indent=2))


if __name__ == "__main__":
    main()
