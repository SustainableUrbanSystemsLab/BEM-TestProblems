# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2018, Christoph Waibel. All rights reserved.
# Input transformations translated from BEOBenchmark, commit 54736a6b899a488222ad3184f306c1f401daf4f9.
# See data/licenses/BEOBenchmark-LICENSE.txt for the complete license.
"""Legacy input transformations and typed modern epJSON parameter bindings."""

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from .reference import legacy_template_path

if TYPE_CHECKING:
    from .problems import Problem

TOKEN_PATTERN = re.compile(r"%[A-Za-z0-9_]+%")


def csharp_number(value: float) -> str:
    """Classic .NET Framework's invariant general-15 formatting for finite doubles."""
    value = float(value)
    if value == 0.0:
        return "0"
    return format(value, ".15g").upper()


def legacy_token_values(problem: "Problem", x: Sequence[float]) -> dict[str, float]:
    """Return all original placeholders, including derived coordinates/constants."""
    vector = problem.expanded_vector(x)
    if problem.family == "simple":
        return dict(zip(("%azimuth%", "%w_we_win%", "%w_ea_win%", "%tau%"), vector))
    if problem.family == "detailed":
        wn, ww, we, ws, ow, oe, os, sw, se, ss, summer, winter, supply = vector
        result = {}
        for side, width, center in (
            ("Nor", wn, 3.0),
            ("Wes", ww, 12.0),
            ("Eas", we, 12.0),
            ("Sou", ws, 3.0),
        ):
            result[f"%x0Win{side}%"] = center - width / 2.0
            result[f"%x1Win{side}%"] = center + width / 2.0
            result[f"%y0Win{side}%"] = 0.6
            result[f"%x0Ove{side}%"] = center - width / 2.0 - 0.5
            result[f"%x1Ove{side}%"] = center + width / 2.0 + 0.5
        result.update(
            {
                "%yOveWes%": ow + 8.0,
                "%yOveEas%": oe + 8.0,
                "%yOveSou%": os + 8.0,
                "%shaWes%": sw,
                "%shaEas%": se,
                "%shaSou%": ss,
                "%TZonCooNigSum%": summer,
                "%TZonCooNigWin%": winter,
                "%CooDesSupTem%": supply,
            }
        )
        return result
    if problem.family == "office":
        result = {f"%{i}%": value for i, value in enumerate(vector)}
        if problem.id == 9:
            result["%13%"] = vector[8] * 0.0006875 - 0.00025
        else:
            for i in range(8):
                result[f"%{13 + i}%"] = vector[i] + 16.7683
                result[f"%{21 + i}%"] = vector[i] + 33.5366
            result["%29%"] = vector[8] * 0.0006875 - 0.00025
        return result
    if problem.family == "school":
        return {"%delta%": vector[0], **{f"%UA{i}%": vector[i] for i in range(1, 10)}}
    raise ValueError(f"Unknown model family {problem.family!r}")


def _data_resource(subdirectory: str, filename: str):
    return files("bem_testproblems").joinpath("data", subdirectory, filename)


def render_legacy(problem: "Problem", x: Sequence[float], path) -> Path:
    """Instantiate the original template, reproducing C# input transformations.

    Original CP1252 degree signs in template comments are decoded losslessly.
    Deterministic UTF-8/LF bytes make input hashes portable across platforms.
    """
    raw = legacy_template_path(problem.template_filename).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    replacements = legacy_token_values(problem, x)
    expected = set(TOKEN_PATTERN.findall(text))
    if expected != set(replacements):
        raise ValueError(
            f"Template/token mismatch for problem {problem.id}: missing={expected - set(replacements)}, unused={set(replacements) - expected}"
        )
    for token, value in replacements.items():
        text = text.replace(token, csharp_number(value))
    if TOKEN_PATTERN.search(text):
        raise ValueError("Unresolved placeholders in generated legacy IDF")
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(("\n".join(text.splitlines()) + "\n").encode("utf-8"))
    return destination


def _set_path(document, path, value):
    target = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


def render_modern(problem: "Problem", x: Sequence[float], path) -> Path:
    """Apply audited typed bindings to the transitioned EnergyPlus epJSON model.

    ``parameter_bindings.json`` records a JSON path for each original token.
    The base model and binding metadata are versioned together; no IDF
    transition or subprocess is performed during an objective evaluation.
    """
    values = legacy_token_values(problem, x)
    model_id = 6 if problem.id == 8 else problem.id
    model = json.loads(
        _data_resource("modern", f"problem_{model_id}.epJSON").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        _data_resource("modern", "parameter_bindings.json").read_text(encoding="utf-8")
    )
    record = manifest["models"][str(model_id)]
    bindings = record["bindings"]
    covered = {binding["token"] for binding in bindings}
    if covered != set(values):
        raise ValueError(
            f"Modern binding coverage differs for problem {problem.id}: {covered ^ set(values)}"
        )
    for binding in bindings:
        # Match the value actually emitted by classic C# rather than adding
        # higher precision to the modern model's physical parameters.
        _set_path(model, binding["path"], float(csharp_number(values[binding["token"]])))
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((json.dumps(model, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return destination
