"""Run a specifically selected EnergyPlus installation in isolated processes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

SUPPORTED_VERSIONS = ("8.5.0", "26.2.0")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version(value: str) -> str:
    parts = value.split(".")
    if len(parts) == 2:
        value += ".0"
    if value not in SUPPORTED_VERSIONS:
        raise ValueError(f"Supported EnergyPlus versions are {SUPPORTED_VERSIONS}, got {value!r}")
    return value


def _terminate_tree(process: subprocess.Popen) -> None:
    """Reap the process and its preprocessing/postprocessing children."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        # The leader may already have exited while a child ignored SIGTERM.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _process_options() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


@dataclass(frozen=True)
class RunResult:
    directory: Path
    version: str
    input_file: Path | None = None
    input_sha256: str | None = None
    weather_file: Path | None = None
    weather_sha256: str | None = None
    elapsed: float = 0.0
    executable: Path | None = None
    executable_sha256: str | None = None
    command: tuple[str, ...] = ()
    returncode: int = 0
    output_files: tuple[str, ...] = ()
    cache_hit: bool = False


class EnergyPlusError(RuntimeError):
    """A failed evaluation; its retained directory contains the diagnostics."""

    def __init__(self, message: str, *, directory: Path | None = None,
                 reason: str = "execution", returncode: int | None = None):
        super().__init__(message)
        self.directory = directory
        self.reason = reason
        self.returncode = returncode


class EnergyPlusRunner:
    """Use one immutable installation; every evaluation owns its working directory.

    Input files must refer to auxiliary files using absolute paths. Weather is
    supplied explicitly and is never downloaded or replaced by this runner.
    Disable caching for models that use mutable auxiliary files: the benchmark
    cache keys cover the model, EPW, executable and simulation mode.
    """

    def __init__(self, executable: str | Path, *, expected_version: str = "26.2.0",
                 timeout: float = 300.0, output_root: str | Path | None = None,
                 cache: bool = True):
        self.executable = Path(executable).expanduser().resolve(strict=True)
        if not self.executable.is_file():
            raise ValueError("The EnergyPlus executable must be a file")
        self.expected_version = _version(expected_version)
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = float(timeout)
        self.output_root = Path(output_root).expanduser().resolve() if output_root else None
        if self.output_root:
            self.output_root.mkdir(parents=True, exist_ok=True)
        self.version_output = self._probe_version()
        match = re.search(r"\bVersion[\s,:]+(\d+\.\d+(?:\.\d+)?)", self.version_output,
                          flags=re.IGNORECASE)
        if not match:
            raise EnergyPlusError(f"Cannot identify EnergyPlus version: {self.version_output!r}",
                                  reason="version")
        self.version = _version(match.group(1))
        if self.version != self.expected_version:
            raise EnergyPlusError(
                f"Expected EnergyPlus {self.expected_version}, executable reports {self.version}",
                reason="version",
            )
        self.executable_sha256 = sha256_file(self.executable)
        self.cache = bool(cache)
        self._cache: dict[str, RunResult] = {}
        self._inflight: dict[str, threading.Lock] = {}
        self._cache_lock = threading.Lock()

    def _probe_version(self) -> str:
        process = subprocess.Popen(
            [str(self.executable), "--version"], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, **_process_options(),
        )
        try:
            output, _ = process.communicate(timeout=min(self.timeout, 15.0))
        except subprocess.TimeoutExpired as error:
            _terminate_tree(process)
            raise EnergyPlusError("EnergyPlus version probe timed out", reason="version") from error
        if process.returncode:
            raise EnergyPlusError(f"EnergyPlus version probe failed: {output[-4000:]}",
                                  reason="version", returncode=process.returncode)
        return output.strip()

    def _check_input_version(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if path.suffix.lower() == ".epjson":
            model = json.loads(text)
            versions = model.get("Version", {})
            values = [obj.get("version_identifier") for obj in versions.values()]
            identifier = values[0] if len(values) == 1 else None
        else:
            uncommented = "\n".join(line.split("!", 1)[0] for line in text.splitlines())
            match = re.search(r"(?:^|;)\s*version\s*,\s*([^;,\s]+)", uncommented,
                              flags=re.IGNORECASE)
            identifier = match.group(1) if match else None
        try:
            matches = identifier is not None and _version(str(identifier)) == self.version
        except ValueError:
            matches = False
        if not matches:
            raise EnergyPlusError(
                f"Input Version {identifier!r} does not match EnergyPlus {self.version}",
                reason="input_version",
            )

    def run(self, input_file: str | Path, weather_file: str | Path | None = None,
            *, design_day: bool = False) -> RunResult:
        source = Path(input_file).expanduser().resolve(strict=True)
        weather = Path(weather_file).expanduser().resolve(strict=True) if weather_file else None
        if sha256_file(self.executable) != self.executable_sha256:
            raise EnergyPlusError("EnergyPlus executable changed after runner configuration", reason="version")
        if not self.cache:
            return self._run_uncached(source, weather, design_day=design_day)
        source_hash = sha256_file(source)
        weather_hash = sha256_file(weather) if weather else "no-weather"
        key = hashlib.sha256("\0".join((source_hash, weather_hash, self.executable_sha256,
                                         str(bool(design_day)))).encode()).hexdigest()
        with self._cache_lock:
            lock = self._inflight.setdefault(key, threading.Lock())
        with lock:
            result = self._cache.get(key)
            if result is not None and self._cached_files_exist(result):
                return replace(result, cache_hit=True)
            result = self._run_uncached(source, weather, design_day=design_day)
            if result.input_sha256 != source_hash:
                raise EnergyPlusError("Input changed during evaluation", directory=result.directory,
                                      reason="input_changed")
            if (result.weather_sha256 or "no-weather") != weather_hash:
                raise EnergyPlusError("Weather changed during evaluation", directory=result.directory,
                                      reason="input_changed")
            # Failed evaluations never reach this assignment.
            self._cache[key] = result
            return result

    @staticmethod
    def _cached_files_exist(result: RunResult) -> bool:
        if not result.output_files or not all((result.directory / name).is_file() for name in result.output_files):
            return False
        if result.input_file is None or sha256_file(result.input_file) != result.input_sha256:
            return False
        err = (result.directory / "eplusout.err").read_text(errors="replace")
        end = (result.directory / "eplusout.end").read_text(errors="replace")
        return ("EnergyPlus Completed Successfully" in end
                and re.search(r"\*\*\s*(?:Severe|Fatal)\s*\*\*", err, re.IGNORECASE) is None)

    def _run_uncached(self, input_file: str | Path, weather_file: str | Path | None = None,
                      *, design_day: bool = False) -> RunResult:
        source = Path(input_file).expanduser().resolve(strict=True)
        if source.suffix.lower() not in {".idf", ".epjson"}:
            raise ValueError("EnergyPlus input must be an .idf or .epJSON file")
        self._check_input_version(source)
        weather = Path(weather_file).expanduser().resolve(strict=True) if weather_file else None
        if weather is not None and not weather.is_file():
            raise ValueError("weather_file must be an EPW file")
        directory = Path(tempfile.mkdtemp(prefix="energyplus-", dir=self.output_root)).resolve()
        staged = directory / ("input" + source.suffix)
        shutil.copyfile(source, staged)
        command = [str(self.executable), "-d", str(directory), "-p", "eplus", "-s", "L"]
        idd = self.executable.parent / "Energy+.idd"
        if idd.is_file():
            command.extend(["-i", str(idd)])
        if weather:
            command.extend(["-w", str(weather)])
        if design_day:
            command.append("-D")
        # The bundled continuous models are already expanded. Invoke the
        # preprocessor only if an IDF actually contains its input objects.
        if staged.suffix.lower() == ".idf" and re.search(
            r"(?im)^\s*(?:HVACTemplate|GroundHeatTransfer):", staged.read_text(errors="replace")
        ):
            command.append("-x")
        command.append(str(staged))
        metadata = {
            "version": self.version, "version_output": self.version_output,
            "executable": str(self.executable), "executable_sha256": self.executable_sha256,
            "source_input": str(source), "input_file": str(staged),
            "input_sha256": sha256_file(staged),
            "weather_file": str(weather) if weather else None,
            "weather_sha256": sha256_file(weather) if weather else None,
            "command": command, "directory": str(directory),
            "started_at": datetime.now(timezone.utc).isoformat(), "status": "running",
        }
        manifest = directory / "run.json"
        manifest.write_text(json.dumps(metadata, indent=2) + "\n")
        started = time.monotonic()
        process = None
        try:
            with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
                process = subprocess.Popen(command, cwd=directory, stdout=stdout, stderr=stderr,
                                           **_process_options())
                try:
                    process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired as error:
                    _terminate_tree(process)
                    raise EnergyPlusError(f"EnergyPlus exceeded {self.timeout:g} seconds",
                                          directory=directory, reason="timeout") from error
            if process.returncode:
                raise EnergyPlusError(f"EnergyPlus exited with status {process.returncode}; see {directory}",
                                      directory=directory, reason="exit", returncode=process.returncode)
            err = directory / "eplusout.err"
            end = directory / "eplusout.end"
            if not err.is_file() or not end.is_file():
                raise EnergyPlusError("EnergyPlus did not produce completion diagnostics",
                                      directory=directory, reason="incomplete")
            diagnostics = err.read_text(errors="replace")
            if re.search(r"\*\*\s*(?:Severe|Fatal)\s*\*\*", diagnostics, re.IGNORECASE):
                raise EnergyPlusError(f"EnergyPlus reported a severe or fatal error; see {err}",
                                      directory=directory, reason="simulation")
            if "EnergyPlus Completed Successfully" not in end.read_text(errors="replace"):
                raise EnergyPlusError(f"EnergyPlus did not complete successfully; see {end}",
                                      directory=directory, reason="incomplete")
            metadata["status"] = "success"
            metadata["output_files"] = sorted(path.name for path in directory.iterdir() if path.is_file())
        except BaseException as error:
            if process is not None and process.poll() is None:
                _terminate_tree(process)
            metadata["status"] = "failed"
            metadata["failure"] = str(error)
            metadata["failure_reason"] = getattr(error, "reason", type(error).__name__)
            raise
        finally:
            metadata["elapsed"] = time.monotonic() - started
            metadata["returncode"] = process.returncode if process is not None else None
            manifest.write_text(json.dumps(metadata, indent=2) + "\n")
        return RunResult(
            directory=directory, version=self.version, input_file=staged,
            input_sha256=metadata["input_sha256"], weather_file=weather,
            weather_sha256=metadata["weather_sha256"], elapsed=metadata["elapsed"],
            executable=self.executable, executable_sha256=self.executable_sha256,
            command=tuple(command), returncode=process.returncode,
            output_files=tuple(metadata["output_files"]),
        )
