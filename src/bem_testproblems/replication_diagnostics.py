# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Explicit replication-only recovery of completed warmup-diagnostic runs.

This policy approximates the original caller's willingness to read completed
simulation reports despite warmup convergence errors. Recovered values are not
accepted strict benchmark evaluations. The native runner and its retained files
remain unchanged; all other simulator and report failures still propagate.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .energyplus import EnergyPlusError, RunResult, sha256_file
from .outputs import extract_outputs

_SEVERE = re.compile(r"^\s*\*\*\s*Severe\s*\*\*\s*(.*)$", re.I | re.M)
_FATAL = re.compile(r"\*\*\s*Fatal\s*\*\*", re.I)
_WARNING = re.compile(r"^\s*\*\*\s*Warning\s*\*\*", re.I | re.M)
_WARMUP = re.compile(r"^CheckWarmupConvergence:\s*Loads Initialization,\s*Zone=", re.I)
_COMPLETION = re.compile(
    r"EnergyPlus Completed Successfully--\s*(\d+)\s+Warnings?;\s*(\d+)\s+Severe Errors?",
    re.I,
)


def _diagnostics(directory: Path) -> dict:
    text = (directory / "eplusout.err").read_text(errors="replace")
    messages = _SEVERE.findall(text)
    eio = directory / "eplusout.eio"
    lines = eio.read_text(errors="replace").splitlines() if eio.is_file() else []
    return {
        "policy": "reference-warmup",
        "accepted_warmup_only": False,
        "strict_benchmark_evaluation": False,
        "severe_count": len(messages),
        "warmup_severe_count": sum(bool(_WARMUP.match(message)) for message in messages),
        "fatal_count": len(_FATAL.findall(text)),
        "warning_count": len(_WARNING.findall(text)),
        "severe_messages": messages,
        "warmup_eio_rows": [
            line.strip() for line in lines
            if line.strip().startswith("Warmup Convergence Information,")
        ],
        "actual_warmup_days": [
            int(match.group(1)) for line in lines
            if (match := re.match(r"\s*Environment:WarmupDays,\s*(\d+)\s*$", line))
        ],
    }


class ReferenceWarmupRunner:
    """Wrap a strict runner for an explicitly selected replication experiment.

    ``family`` identifies the required benchmark observables. Recovery requires
    valid family-specific reports, matching recorded file hashes, process exit
    zero, a successful completion marker, and only CheckWarmupConvergence Severe
    messages. Fatal errors and any other failure are never recovered.

    ``last_diagnostics`` exposes the most recent classification; ``recovered_runs``
    retains recovery records with paths and hashes for the experiment's ledger.
    These records are not written into, or substituted for, native ``run.json``.
    """

    def __init__(self, runner, *, family: str):
        if family not in {"simple", "detailed", "office", "school"}:
            raise ValueError(f"Unknown benchmark output family {family!r}")
        self.runner = runner
        self.family = family
        self.last_diagnostics: dict | None = None
        self.recovered_runs: list[dict] = []

    def __getattr__(self, name):
        return getattr(self.runner, name)

    def run(self, input_file, weather_file=None, *, design_day=False) -> RunResult:
        self.last_diagnostics = None
        try:
            result = self.runner.run(input_file, weather_file, design_day=design_day)
        except EnergyPlusError as error:
            if error.reason != "simulation" or error.directory is None:
                raise
            result = self._recover(error, input_file, weather_file, design_day)
            if result is None:
                raise
            return result
        self.last_diagnostics = _diagnostics(result.directory)
        self.last_diagnostics["strict_benchmark_evaluation"] = True
        return result

    def _recover(self, error, input_file, weather_file, design_day) -> RunResult | None:
        directory = Path(error.directory).resolve()
        if error.returncode is not None and error.returncode != 0:
            return None
        try:
            diagnostic = _diagnostics(directory)
            self.last_diagnostics = diagnostic
            if (not diagnostic["severe_count"] or diagnostic["fatal_count"]
                    or diagnostic["warmup_severe_count"] != diagnostic["severe_count"]):
                return None
            end = (directory / "eplusout.end").read_text(errors="replace")
            completion = _COMPLETION.search(end)
            if completion is None or int(completion.group(2)) != diagnostic["severe_count"]:
                return None
            metadata = json.loads((directory / "run.json").read_text())
            if (metadata["status"] != "failed" or metadata["failure_reason"] != "simulation"
                    or type(metadata["returncode"]) is not int or metadata["returncode"] != 0
                    or metadata["version"] != self.runner.version
                    or Path(metadata["directory"]).resolve() != directory):
                return None
            staged = Path(metadata["input_file"]).resolve(strict=True)
            if (staged.parent != directory or not staged.is_file()
                    or sha256_file(staged) != metadata["input_sha256"]
                    or sha256_file(input_file) != metadata["input_sha256"]):
                return None
            executable = Path(metadata["executable"]).resolve(strict=True)
            if (executable != Path(self.runner.executable).resolve()
                    or metadata["executable_sha256"] != self.runner.executable_sha256
                    or sha256_file(executable) != metadata["executable_sha256"]):
                return None
            weather = Path(weather_file).expanduser().resolve(strict=True) if weather_file else None
            recorded_weather = metadata["weather_file"]
            if weather is None:
                if recorded_weather is not None or metadata["weather_sha256"] is not None:
                    return None
            elif (recorded_weather is None or Path(recorded_weather).resolve() != weather
                    or not weather.is_file() or sha256_file(weather) != metadata["weather_sha256"]):
                return None
            command = metadata["command"]
            if (not isinstance(command, list) or not command
                    or not all(isinstance(value, str) for value in command)
                    or Path(command[0]).resolve() != executable
                    or Path(command[-1]).resolve() != staged
                    or ("-D" in command) != bool(design_day)):
                return None
            elapsed = float(metadata["elapsed"])
            if not math.isfinite(elapsed) or elapsed < 0:
                return None
            result = RunResult(
                directory=directory, version=metadata["version"], input_file=staged,
                input_sha256=metadata["input_sha256"], weather_file=weather,
                weather_sha256=metadata["weather_sha256"], elapsed=elapsed,
                executable=executable, executable_sha256=metadata["executable_sha256"],
                command=tuple(command), returncode=0,
                output_files=tuple(sorted(path.name for path in directory.iterdir() if path.is_file())),
            )
            # Validate actual required observables, including completeness,
            # uniqueness, units and finite values, before recovering the run.
            extract_outputs(self.family, result)
        except (OSError, ValueError, KeyError, TypeError):
            return None
        diagnostic["accepted_warmup_only"] = True
        self.recovered_runs.append({
            **diagnostic,
            "directory": str(directory),
            "input_sha256": result.input_sha256,
            "weather_sha256": result.weather_sha256,
            "executable_sha256": result.executable_sha256,
        })
        return result
