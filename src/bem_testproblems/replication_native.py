# SPDX-License-Identifier: MIT
"""Opt-in transport for recovered BB-O and Galapagos binaries on Windows.

Search operators stay in external, hash-pinned libraries. The ordinary physical
benchmark API and its solver registry do not depend on these historical tools.
"""

import json
import math
import os
import subprocess
from pathlib import Path

from .energyplus import sha256_file
from .problems import PROBLEM_IDS, get_problem

BBO = ("sga", "sga_unt", "es", "es_unt", "pso", "pso_unt", "fips", "fips_unt")
METHODS = BBO + ("galapagos_ga", "galapagos_sa")
REQUIRED = {
    "bbo": {"SolverBridge.exe", "FrOG.dll", "MetaheuristicsLibrary.dll"},
    "galapagos": {"GalapagosBridge.exe", "Galapagos.dll"},
}


def verify_files(configuration):
    for backend in configuration["backends"].values():
        for filename, expected in backend["files"].items():
            if sha256_file(filename) != expected:
                raise ValueError(f"Historical solver input changed: {filename}")


def load_configuration(filename, methods):
    """Resolve a private configuration and validate every selected binary hash."""
    path = Path(filename).resolve()
    configuration = json.loads(path.read_text(encoding="utf-8"))
    if configuration.get("schema_version") != 1 or set(methods) - set(METHODS):
        raise ValueError("Native configuration supports only the ten recovered BB-O/Galapagos methods")
    backends = {}
    for name in {"bbo" if method in BBO else "galapagos" for method in methods}:
        backend = configuration["backends"][name]
        executable = (path.parent / backend["executable"]).resolve()
        files = {str((path.parent / p).resolve()): digest
                 for p, digest in backend["files"].items()}
        if {Path(p).name for p in files} != REQUIRED[name]:
            raise ValueError(f"Pin all required {name} binaries and no substitutes")
        expected_executable = "SolverBridge.exe" if name == "bbo" else "GalapagosBridge.exe"
        if str(executable) not in files or executable.name != expected_executable:
            raise ValueError("Historical executable must be one of the pinned inputs")
        if any(Path(p).parent != executable.parent for p in files):
            raise ValueError("Historical libraries must be beside their executable")
        backends[name] = dict(executable=str(executable), files=files, source=backend["source"])
    result = dict(config_path=str(path), config_sha256=sha256_file(path), backends=backends)
    verify_files(result)
    return result


def slider_profile(number):
    """Bounds and precision saved in the original benchmark GH definitions."""
    problem = get_problem(number)
    if problem.id not in PROBLEM_IDS:
        raise ValueError("Use an original continuous benchmark problem")
    if problem.id in (4, 5, 6, 8):
        tail = [(100, 600)] * 3 + ([(20, 25)] if problem.id == 8
                                  else [(20, 25), (20, 25), (12, 18)])
        bounds = [(0, 1)] * 7 + tail
        digits = [4] * 7 + [1, 1, 1, 2] if problem.id == 8 else [3] * 13
    else:
        bounds = problem.bounds
        digits = [2, 3, 3, 4] if problem.id in (1, 2, 3) else [
            6 if problem.id in (9, 10) else 3] * problem.dimension
    return dict(lower=[b[0] for b in bounds], upper=[b[1] for b in bounds], digits=digits)


def physical_design(number, slider):
    """Apply the saved GH expressions, retaining the ordinary physical bounds."""
    profile = slider_profile(number)
    if len(slider) != len(profile["lower"]) or any(
        not math.isfinite(x) or not a <= x <= b
        for x, a, b in zip(slider, profile["lower"], profile["upper"], strict=True)
    ):
        raise ValueError("Historical solver requested an invalid slider design")
    if number not in (4, 5, 6, 8):
        return list(slider)
    a = slider
    result = [1.224 + 4.608 * a[0], 7.344 + 18.324 * a[1],
              7.344 + 18.324 * a[3], 1.224 + 4.608 * a[5],
              0.05 + a[2], 0.05 + a[4], 0.05 + a[6], *a[7:]]
    # Binary64 affine endpoint rounding can exceed a physical bound by one ULP.
    # Only exact slider endpoints use their exact declared physical bounds.
    bounds = get_problem(number).bounds
    for coordinate, index in enumerate((0, 1, 3, 5, 2, 4, 6)):
        if a[index] in (0, 1):
            result[coordinate] = bounds[coordinate][int(a[index])]
    get_problem(number).validate(result)
    return result


def slider_start(number, x):
    if number not in (4, 5, 6, 8):
        return list(x)
    return [(x[0] - 1.224) / 4.608, (x[1] - 7.344) / 18.324,
            x[4] - 0.05, (x[2] - 7.344) / 18.324, x[5] - 0.05,
            (x[3] - 1.224) / 4.608, x[6] - 0.05, *x[7:]]


def solver_settings(method, dimension):
    if method not in BBO:
        return dict(initialization="recorded x0 as native founder/annealing hint",
                    seed_mapping="recorded signed 32-bit seed", galapagos_tick_precision_cap=5)
    family = dict(sga="SGA", es="ES", pso="PSO", fips="FIPSO")[method.removesuffix("_unt")]
    preset = ("SGA_WW" if family == "SGA" else family + "_unt") if method.endswith(
        "_unt") else f"{family}_n{dimension}_" + ("B" if family == "FIPSO" else "A")
    return dict(preset=preset, initialization="native seeded population; recorded x0 unused",
                seed_mapping="recorded seed modulo 32768 (original Int16 interface)")


def solve(spec, configuration, objective, protocol):
    """Run one original solver; objective exceptions stop its owned child process."""
    verify_files(configuration)
    method = spec["solver"]
    backend = configuration["backends"]["bbo" if method in BBO else "galapagos"]
    settings = solver_settings(method, len(spec["x0"]))
    request = dict(seed=spec["seed"] % 32768 if method in BBO else spec["seed"],
                   budget=spec["budget"] + 1, **slider_profile(spec["problem"]))
    if method in BBO:
        request["preset"] = settings["preset"]
    else:
        request.update(method=method, x0=slider_start(spec["problem"], spec["x0"]))
    protocol = Path(protocol)
    protocol.parent.mkdir(parents=True, exist_ok=True)
    with protocol.open("x", encoding="utf-8") as log, protocol.with_suffix(
        ".stderr").open("x+", encoding="utf-8") as errors:
        process = subprocess.Popen([backend["executable"]], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=errors, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            log.write(json.dumps(dict(request=request, settings=settings)) + "\n")
            log.flush()
            finished = None
            for line in process.stdout:
                message = json.loads(line)
                if message["type"] == "evaluation":
                    message["physical_x"] = physical_design(spec["problem"], message["x"])
                log.write(json.dumps(message, allow_nan=False) + "\n")
                log.flush()
                if message["type"] == "evaluation":
                    # The checkpointed evaluator owns the budget. A further
                    # request stops the child before another simulator call.
                    value = objective(message["physical_x"])
                    reply = json.dumps(dict(objective=value), allow_nan=False) + "\n"
                    log.write(reply)
                    log.flush()
                    process.stdin.write(reply)
                    process.stdin.flush()
                elif message["type"] == "finished":
                    finished = message
                elif message["type"] != "settings":
                    raise ValueError("Unknown historical solver protocol message")
            if process.wait(timeout=10) or not finished or not finished["success"]:
                errors.seek(0)
                raise RuntimeError("Historical solver failed: " + errors.read())
            return dict(status="completed", success=True, native_status=finished,
                        settings=settings, native_seed=request["seed"])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process.stdin.close()
            process.stdout.close()
