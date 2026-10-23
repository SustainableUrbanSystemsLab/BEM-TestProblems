#!/usr/bin/env python3
"""Rebuild audited original-IDF-token to modern-epJSON-field bindings.

This is a maintenance tool, never part of an objective evaluation. It requires
the original 8.5 IDD and the target EnergyPlus epJSON schema. Bindings follow
semantic IDD field labels, rather than relying on obsolete field positions.
Every destination must exist and reproduce the transitioned midpoint value.
"""

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))

from bem_testproblems.models import TOKEN_PATTERN, csharp_number, legacy_token_values  # noqa: E402
from bem_testproblems.problems import UPSTREAM_COMMIT, list_problems  # noqa: E402
from bem_testproblems.reference import legacy_template_path  # noqa: E402


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_template(path):
    raw = Path(path).read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def idf_objects(text):
    stripped = "\n".join(line.split("!", 1)[0] for line in text.splitlines())
    for object_text in stripped.split(";"):
        fields = [field.strip() for field in object_text.split(",")]
        if fields[0]:
            yield fields[0], fields[1:]


def idd_fields(path):
    result = {}
    current = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if re.match(r"^\w[^!\\]*[,;]\s*$", line):
            current = line.strip().rstrip(",;")
            result[current] = []
        match = re.match(r"\s*[AN]\d+\s*[,;]\s*\\field\s+(.+)", line)
        if match and current:
            result[current].append(match.group(1).strip())
    if not result:
        raise ValueError(f"No IDD field definitions found in {path}")
    return result


def normalized(label):
    return re.sub(r"[^a-z0-9]", "", label.lower())


def field_path(object_type, label, schema):
    definition = schema["properties"][object_type]["legacy_idd"]
    if object_type == "Shading:Zone:Detailed":
        vertex = re.fullmatch(r"Vertex (\d+) ([XYZ])-coordinate", label)
        if vertex:
            return ["vertices", int(vertex[1]) - 1, f"vertex_{vertex[2].lower()}_coordinate"]
    if object_type == "Schedule:Compact":
        field = re.fullmatch(r"Field (\d+)", label)
        if field:
            return ["data", int(field[1]) - 1, "field"]
    matches = [
        key
        for key, info in definition["field_info"].items()
        if normalized(info["field_name"]) == normalized(label)
    ]
    if len(matches) != 1:
        raise ValueError(f"Cannot uniquely map {object_type} field {label!r}: {matches}")
    return matches


def object_names(old_type, old_name, model, old_objects, fields, schema):
    modern_type = (
        "WindowShadingControl" if old_type == "WindowProperty:ShadingControl" else old_type
    )
    if modern_type not in model:
        raise ValueError(f"Transitioned model has no {modern_type}")
    exact = [key for key in model[modern_type] if key.casefold() == old_name.casefold()]
    first_field = schema["properties"][modern_type]["legacy_idd"]["fields"][0]
    if first_field != "name":
        # Nameless IDF objects use generated epJSON keys. Their first field is
        # a reference (for example Sizing:Zone.zone_or_zonelist_name), not a key.
        references = [
            key
            for key, value in model[modern_type].items()
            if str(value.get(first_field, "")).casefold() == old_name.casefold()
        ]
        if len(references) == 1:
            return modern_type, references
        raise ValueError(f"Cannot uniquely identify {old_type} by {first_field}={old_name!r}")
    if exact and modern_type != "WindowShadingControl":
        return modern_type, exact
    if modern_type == "WindowShadingControl":
        # The 9.2 transition splits controls by zone and may rename them. Trace
        # the original windows and their modern control membership explicitly.
        old_window_fields = fields["FenestrationSurface:Detailed"]
        index = old_window_fields.index("Shading Control Name")
        windows = {
            values[0].casefold()
            for typ, values in old_objects
            if typ == "FenestrationSurface:Detailed"
            and len(values) > index
            and values[index].casefold() == old_name.casefold()
        }
        matches = []
        covered = set()
        for name, control in model[modern_type].items():
            members = {
                item["fenestration_surface_name"].casefold()
                for item in control.get("fenestration_surfaces", [])
            }
            if members & windows:
                if not members <= windows:
                    raise ValueError(
                        f"Modern shading control {name} merges unexpected original windows"
                    )
                if members & covered:
                    raise ValueError("Original windows belong to multiple transitioned shading controls")
                matches.append(name)
                covered.update(members)
        if windows and covered == windows:
            return modern_type, matches
    raise ValueError(f"Cannot identify transitioned object {old_type}/{old_name}")


def at_path(document, path):
    for part in path:
        document = document[part]
    return document


def build_manifest(legacy_idd, modern_schema, modern_directory, problem_ids=None):
    fields = idd_fields(legacy_idd)
    schema = json.loads(Path(modern_schema).read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 1,
        "source_repository": "https://github.com/milzj/BEOBenchmark",
        "source_commit": UPSTREAM_COMMIT,
        "copyright": "Copyright (c) 2018, Christoph Waibel. All rights reserved.",
        "license": "BSD-3-Clause",
        "license_notice": "../licenses/BEOBenchmark-LICENSE.txt",
        "target_energyplus_version": "26.2",
        "legacy_idd_sha256": sha256(legacy_idd),
        "modern_schema_sha256": sha256(modern_schema),
        "method": "Original 8.5 IDD semantic field labels mapped to target epJSON schema; every midpoint value checked",
        "models": {},
    }
    for problem in list_problems():
        if problem.id == 8 or (problem_ids is not None and problem.id not in problem_ids):
            continue
        source = legacy_template_path(problem.template_filename)
        base = modern_directory / f"problem_{problem.id}.epJSON"
        model = json.loads(base.read_text(encoding="utf-8"))
        old_objects = list(idf_objects(read_template(source)))
        baseline = legacy_token_values(problem, problem.midpoint)
        bindings = []
        for old_type, values in old_objects:
            for index, value in enumerate(values):
                if not TOKEN_PATTERN.fullmatch(value):
                    if TOKEN_PATTERN.search(value):
                        raise ValueError(
                            f"Problem {problem.id}: token embedded in a nonnumeric field {value!r}"
                        )
                    continue
                label = fields[old_type][index]
                modern_type, names = object_names(
                    old_type, values[0], model, old_objects, fields, schema
                )
                suffix = field_path(modern_type, label, schema)
                for name in names:
                    path = [modern_type, name, *suffix]
                    actual = float(at_path(model, path))
                    expected = float(csharp_number(baseline[value]))
                    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
                        raise ValueError(
                            f"Problem {problem.id} midpoint mismatch at {path}: {actual} != {expected}"
                        )
                    bindings.append(
                        {
                            "token": value,
                            "path": path,
                            "source_object_type": old_type,
                            "source_object_name": values[0],
                            "source_field_index": index + 1,
                            "source_field_name": label,
                        }
                    )
        coverage = {binding["token"] for binding in bindings}
        if coverage != set(baseline):
            raise ValueError(
                f"Problem {problem.id} missing/extra token bindings: {coverage ^ set(baseline)}"
            )
        paths = [tuple(binding["path"]) for binding in bindings]
        if len(paths) != len(set(paths)):
            raise ValueError(f"Problem {problem.id} binds the same destination more than once")
        manifest["models"][str(problem.id)] = {
            "source_template": problem.template_filename,
            "source_template_sha256": sha256(source),
            "model_sha256": sha256(base),
            "baseline_x": list(problem.midpoint),
            "token_count": len(coverage),
            "binding_count": len(bindings),
            "bindings": bindings,
        }
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-idd", required=True, type=Path)
    parser.add_argument("--modern-schema", required=True, type=Path)
    parser.add_argument(
        "--modern-directory", type=Path, default=REPOSITORY / "src/bem_testproblems/data/modern"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.legacy_idd, args.modern_schema, args.modern_directory)
    output = args.output or args.modern_directory / "parameter_bindings.json"
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(record["binding_count"] for record in manifest["models"].values())
    print(
        f"Verified {total} physical field bindings across {len(manifest['models'])} models: {output}"
    )


if __name__ == "__main__":
    main()
