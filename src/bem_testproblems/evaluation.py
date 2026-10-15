# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Bind local simulation inputs once to expose a scalar solver objective."""

from __future__ import annotations

import json
import os
from functools import partial
from importlib.resources import files
from pathlib import Path

from .energyplus import EnergyPlusRunner, _version, sha256_file
from .problems import Problem, get_problem
from .reference import legacy_template_path

_WEATHER_SETUP = (
    "Run tools/fetch_weather.py with your project Python "
    "(use --directory for a custom weather directory), or pass weather= explicitly"
)


def _default_project_root() -> Path:
    """Use this source checkout when present, otherwise the caller's directory."""
    package = Path(__file__).resolve().parent
    checkout = package.parents[1]
    if ((checkout / "pyproject.toml").is_file()
            and (checkout / "src" / "bem_testproblems").resolve() == package):
        return checkout
    return Path.cwd().resolve()


def _explicit_path(value: str | Path) -> Path:
    """Resolve explicit paths against the caller's current directory."""
    return Path(value).expanduser().resolve()


def _require_file(path: Path, description: str, instruction: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{description} is missing: {path}. {instruction}")
    if not path.is_file():
        raise ValueError(f"{description} must be a file: {path}")
    return path


def _check_canonical_weather(path: Path, expected: str) -> None:
    """Keep a canonical objective fixed even if its weather file is replaced."""
    _require_file(path, "Canonical weather file", _WEATHER_SETUP)
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(
            f"Canonical weather checksum mismatch for {path}: expected {expected}, got {actual}. "
            f"{_WEATHER_SETUP}"
        )


def _canonical_weather_file(problem: Problem, directory: Path) -> tuple[Path, str]:
    """Check the trusted packaged index, including for a custom cache directory."""
    manifest = json.loads(
        files("bem_testproblems").joinpath("data", "weather-assets.json").read_bytes()
    )
    matches = [
        entry for entry in manifest["files"]
        if entry["cache_path"] == problem.weather_filename
    ]
    if len(matches) != 1:
        raise ValueError(
            f"No canonical weather checksum is available for {problem.weather_filename!r}; "
            "pass weather= explicitly to select a weather variant"
        )
    path = directory / problem.weather_filename
    expected = matches[0]["sha256"]
    _check_canonical_weather(path, expected)
    return path, expected


def _evaluate_canonical_weather(
    x, *, definition: Problem, runner: EnergyPlusRunner, weather: Path,
    expected_weather_sha256: str,
) -> float:
    _check_canonical_weather(weather, expected_weather_sha256)
    return definition.evaluate(x, runner=runner, weather=weather)


def make_objective(
    problem: Problem | int | str,
    *,
    project_root: str | Path | None = None,
    energyplus_version: str | None = None,
    executable: str | Path | None = None,
    runner: EnergyPlusRunner | None = None,
    weather: str | Path | None = None,
    weather_dir: str | Path | None = None,
    output_root: str | Path | None = None,
) -> partial:
    """Return ``objective(x)`` with its local runner and weather already bound.

    Obtain dimension, physical bounds and any chosen initial vector from
    ``get_problem``. This factory performs no simulation, download, installation
    or PATH search. It checks required files and, when constructing a runner,
    probes its executable version once. Evaluation retains the runner's strict
    failure policy and exact-input cache.

    Default paths are below ``project_root``: the executable is in
    ``.tools/energyplus/<version>``, weather in ``.cache/weather``, and outputs in
    ``.runs/<version>``. Without an explicit root, a source checkout uses its own
    root and an installed package uses the current working directory. Explicit
    paths are resolved relative to the caller's current working directory.

    The default engine is 26.2.0. A supplied runner determines the version unless
    ``energyplus_version`` explicitly requests one; conflicting settings fail.
    ``runner`` cannot be combined with ``executable`` or ``output_root``.

    Default weather, including files selected through ``weather_dir``, must match
    the packaged canonical checksum at binding and before every objective call;
    replacing it between evaluations raises an error before simulation. An
    explicit ``weather`` file permits an identified variant without this pinned
    checksum guard and cannot be combined with ``weather_dir``. Problem 13
    needs no EPW and does not inspect the weather cache unless given ``weather``.
    Version 8.5 templates follow the existing reference-cache/BEM_REFERENCE_DIR
    lookup; this factory does not change that environment setting.
    """
    if runner is not None and executable is not None:
        raise ValueError("Pass runner or executable, not both")
    if runner is not None and output_root is not None:
        raise ValueError("A supplied runner already owns output_root")
    if weather is not None and weather_dir is not None:
        raise ValueError("Pass weather or weather_dir, not both")

    definition = problem if isinstance(problem, Problem) else get_problem(problem)
    base = _explicit_path(project_root) if project_root is not None else _default_project_root()
    requested = None if energyplus_version is None else _version(str(energyplus_version))
    if runner is not None:
        version = _version(str(runner.version))
        if requested is not None and requested != version:
            raise ValueError(
                f"Requested EnergyPlus {requested}, but supplied runner uses {version}"
            )
    else:
        version = requested or "26.2.0"

    expected_weather_sha256 = None
    if weather is not None:
        bound_weather = _require_file(
            _explicit_path(weather), "Explicit weather file", "Supply an existing weather path"
        )
    elif definition.design_day:
        bound_weather = None
    else:
        directory = (
            _explicit_path(weather_dir) if weather_dir is not None else base / ".cache" / "weather"
        )
        bound_weather, expected_weather_sha256 = _canonical_weather_file(definition, directory)

    if version == "8.5.0":
        legacy_template_path(definition.template_filename)

    if runner is None:
        engine_name = "energyplus.exe" if os.name == "nt" else "energyplus"
        engine_path = (
            _explicit_path(executable) if executable is not None
            else base / ".tools" / "energyplus" / version / engine_name
        )
        instruction = (
            "Run tools/install_energyplus.py with your project Python"
            if version == "26.2.0" else
            "On Windows run tools/install_reference_engine.py with your project Python; "
            "on other platforms supply executable= for a compatible EnergyPlus 8.5 installation"
        )
        _require_file(engine_path, "EnergyPlus executable", instruction)
        directory = (
            _explicit_path(output_root) if output_root is not None
            else base / ".runs" / version
        )
        runner = EnergyPlusRunner(engine_path, expected_version=version, output_root=directory)

    if expected_weather_sha256 is not None:
        return partial(
            _evaluate_canonical_weather, definition=definition, runner=runner,
            weather=bound_weather, expected_weather_sha256=expected_weather_sha256,
        )
    return partial(definition.evaluate, runner=runner, weather=bound_weather)
