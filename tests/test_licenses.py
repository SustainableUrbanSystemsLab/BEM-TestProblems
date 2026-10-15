# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Check retained notices, immutable upstream assets and distribution boundaries."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "assets/manifest.json").read_text(encoding="utf-8"))


def test_external_reference_pins_and_bundled_notice_coverage() -> None:
    assets = MANIFEST["bundled_assets"]
    assert len(assets) == 2
    for asset in assets:
        path = ROOT / asset["path"]
        assert path.is_file(), asset["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
        assert asset["license_expression"] == "BSD-3-Clause"
        assert MANIFEST["upstream"]["commit"] in asset["source_url"]

    index_record = MANIFEST["reference_assets_index"]
    raw = (ROOT / index_record["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == index_record["sha256"]
    index = json.loads(raw)
    assert index["source_commit"] == MANIFEST["upstream"]["commit"]
    assert len(index["files"]) == 16
    indexed = {asset["cache_path"]: asset for asset in index["files"]}
    originals = MANIFEST["external_reference_assets"]
    assert len([a for a in originals if a["kind"] == "legacy_model"]) == 9
    assert len([a for a in originals if a["kind"] == "legacy_source"]) == 6
    for asset in originals:
        pin = indexed[asset["cache_path"]]
        assert pin["sha256"] == asset["sha256"]
        assert pin["upstream_path"] == asset["upstream_path"]
        assert pin["url"] == asset["download_url"]
        assert index["source_commit"] in pin["url"]
        assert not (ROOT / asset["former_repository_path"]).exists()
        assert asset["license_expression"] == "BSD-3-Clause"

    notice_record = MANIFEST["packaged_model_notices"]
    assert hashlib.sha256((ROOT / notice_record["path"]).read_bytes()).hexdigest() == notice_record["sha256"]
    expected = {a["path"] for a in assets + MANIFEST["bundled_external_notices"]}
    expected.add(notice_record["path"])
    actual = {
        path.relative_to(ROOT).as_posix()
        for directory in (ROOT / "src/bem_testproblems/data/licenses", ROOT / "reference/licenses")
        for path in directory.rglob("*") if path.is_file()
    }
    assert actual == expected, "Every bundled notice needs provenance coverage"


def test_complete_upstream_license_is_retained_verbatim() -> None:
    copies = [a for a in MANIFEST["bundled_assets"] if a["kind"] == "license_copy"]
    assert len(copies) == 2
    for asset in copies:
        raw = (ROOT / asset["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == MANIFEST["upstream"]["license_sha256"]
        text = raw.decode("utf-8")
        assert "Copyright (c) 2018, Christoph Waibel" in text
        assert "Redistributions of source code" in text
        assert "Redistributions in binary form" in text
        assert "endorse or promote" in text
        assert "THIS SOFTWARE IS PROVIDED" in text


def test_external_reference_engine_notice_is_exact_and_separate() -> None:
    notices = MANIFEST["bundled_external_notices"]
    assert len(notices) == 1
    notice = notices[0]
    raw = (ROOT / notice["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == notice["sha256"]
    engine = next(a for a in MANIFEST["external_assets"] if a.get("version") == "8.5.0")
    assert notice["sha256"] == engine["audited_release_license_sha256"]
    text = raw.decode("utf-8")
    assert "Use of EnergyPlus(TM) Name" in text
    assert "EnergyPlus version X" in text
    assert "Redistributions in binary form" in text
    assert "LicenseRef-EnergyPlus-8.5.0" == notice["license_expression"]


def test_translated_modules_identify_bsd_coverage() -> None:
    expected = {"parameters.py", "problems.py", "losses.py", "models.py"}
    derived = MANIFEST["derived_files"]
    assert {Path(asset["path"]).name for asset in derived} == expected
    for asset in derived:
        text = (ROOT / asset["path"]).read_text(encoding="utf-8")
        assert "SPDX-License-Identifier: BSD-3-Clause" in text, asset["path"]
        assert "2018" in text and "Christoph Waibel" in text, asset["path"]
        assert "BEOBenchmark-LICENSE.txt" in text, asset["path"]
        assert (ROOT / asset["license_file"]).is_file()


def test_commentless_modern_models_retain_source_and_license_provenance() -> None:
    model_assets = {
        Path(asset["cache_path"]).name: asset
        for asset in MANIFEST["external_reference_assets"]
        if asset["kind"] == "legacy_model"
    }
    directory = ROOT / "src/bem_testproblems/data/modern"
    models = list(directory.glob("problem_*.epJSON"))
    assert models, "Modern models must ship with adjacent provenance records"
    for model in models:
        provenance = json.loads(model.with_suffix(".provenance.json").read_text())
        source = model_assets[provenance["source_template"]]
        assert provenance["license"] == "BSD-3-Clause"
        assert provenance["source_commit"] == MANIFEST["upstream"]["commit"]
        assert provenance["source_template_sha256"] == source["sha256"]
        assert provenance["output_sha256"] == hashlib.sha256(model.read_bytes()).hexdigest()
        assert (directory / provenance["license_notice"]).resolve().is_file()


def test_derived_asset_hashes_and_license_coverage() -> None:
    directory = ROOT / "src/bem_testproblems/data/modern"
    assets = MANIFEST["derived_assets"]
    recorded = {asset["path"] for asset in assets}
    actual = {path.relative_to(ROOT).as_posix() for path in directory.iterdir() if path.is_file()}
    assert actual == recorded, "Every transitioned model and mapping needs license/provenance coverage"
    assert len([asset for asset in assets if asset["kind"] == "modern_model"]) == 9
    for asset in assets:
        path = ROOT / asset["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"], asset["path"]
        assert asset["license_expression"] == "BSD-3-Clause"
        assert asset["source_commit"] == MANIFEST["upstream"]["commit"]
        assert (ROOT / asset["license_file"]).is_file()

    bindings = json.loads((directory / "parameter_bindings.json").read_text())
    assert bindings["license"] == "BSD-3-Clause"
    assert bindings["source_commit"] == MANIFEST["upstream"]["commit"]
    assert (directory / bindings["license_notice"]).resolve().is_file()
    for number in (9, 10):
        provenance = json.loads((directory / f"problem_{number}.provenance.json").read_text())
        assert provenance["additional_notices"]["publication_credit"] == ["DOE", "NREL", "PNNL", "LBNL"]
        assert "endorsement" in provenance["additional_notices"]["no_endorsement"]


def test_model_credit_and_complete_doe_notice_remain() -> None:
    text = (ROOT / MANIFEST["packaged_model_notices"]["path"]).read_text()
    assert "Michael Wetter, SRG-LBNL" in text
    assert "R. H. Henninger,  GARD Analytics, Inc." in text
    assert "credit DOE, NREL, PNNL, and LBNL" in text
    assert "advertising or publicity that implies endorsement" in text
    assert "any warranty, express or implied" in text
    assert "The views and" in text and "opinions of authors expressed herein" in text
    assert "Commercial Building Benchmarks. Washington, DC" in text


def test_external_weather_binaries_and_publications_are_not_packaged() -> None:
    prohibited = {
        ".epw", ".ddy", ".stat", ".exe", ".dll", ".dylib", ".so", ".dmg",
        ".zip", ".pdf", ".png", ".jpg", ".jpeg", ".gha", ".gh", ".idf",
    }
    for directory in (ROOT / "src/bem_testproblems/data", ROOT / "reference/legacy-source"):
        for path in directory.rglob("*"):
            if path.is_file():
                assert path.suffix.lower() not in prohibited, path.relative_to(ROOT)
    external = MANIFEST["external_assets"]
    assert len([a for a in external if a["kind"] == "weather"]) == 5
    assert {a["version"] for a in external if a["kind"] == "engine"} == {"8.5.0", "26.2.0"}
    for asset in external:
        assert "not bundled" in asset["distribution_policy"]
        assert asset["rights_status"]


def test_canonical_weather_fetch_metadata_has_exact_external_pins() -> None:
    record = MANIFEST["weather_assets_index"]
    raw = (ROOT / record["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == record["sha256"]
    index = json.loads(raw)
    assert index["source_commit"] == MANIFEST["upstream"]["commit"]
    assert len(index["files"]) == 4
    weather = {asset["filename"]: asset for asset in MANIFEST["external_assets"]
               if asset["kind"] == "weather"}
    for pin in index["files"]:
        assert pin["cache_path"].startswith("USA_")
        assert Path(pin["cache_path"]).name == pin["cache_path"]
        assert pin["sha256"] == weather[pin["cache_path"]]["historical_sha256"]
        assert index["source_commit"] in pin["url"]
        assert "milzj/BEOBenchmark" in pin["url"]
    assert "YUG_Belgrade_IWEC.epw" not in {pin["cache_path"] for pin in index["files"]}


def test_public_ci_uploads_only_explicit_numeric_report_files() -> None:
    """Ephemeral use of external inputs must not publish their raw/cache bodies."""
    workflow = (ROOT / ".github/workflows/validate.yml").read_text()
    steps = re.split(r"(?m)(?=^      - )", workflow)
    uploads = [step for step in steps if "uses: actions/upload-artifact@" in step]
    assert uploads, "Numerical CI evidence needs explicit artifact paths"
    for step in uploads:
        lines = step.splitlines()
        paths = []
        for number, line in enumerate(lines):
            match = re.fullmatch(r"( +)path: *(.*)", line)
            if match is None:
                continue
            value = match.group(2).strip()
            if value == "|":
                indentation = len(match.group(1))
                for continuation in lines[number + 1:]:
                    if not continuation.strip():
                        continue
                    if len(continuation) - len(continuation.lstrip()) <= indentation:
                        break
                    paths.append(continuation.strip())
            else:
                paths.append(value.strip("'\""))
        assert paths, "Every upload needs literal, reviewable report filenames"
        for path in paths:
            assert re.fullmatch(r"\.validation-local/reports/[A-Za-z0-9_.-]+\.json", path), (
                "Public artifacts may contain explicit numeric JSON reports only; "
                "never weather, reference caches, raw simulation outputs, directories or wildcards",
                path,
            )


def test_public_ci_checks_canonical_weather_and_keeps_synthetic_supplemental() -> None:
    workflow = (ROOT / ".github/workflows/validate.yml").read_text()
    for job, runner, baseline in (
        ("original-csharp", "windows-2022", "8.5.0-canonical.json"),
        ("modern-regression", "ubuntu-24.04", "26.2.0-canonical.json"),
    ):
        match = re.search(
            rf"(?ms)^  {job}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", workflow
        )
        assert match, f"Missing required public numerical job {job}"
        body = match.group(1)
        assert f"runs-on: {runner}" in body
        assert "weather_kind: canonical" in body
        assert "weather_kind: synthetic-ci" in body
        assert "cases: reference/canonical-cases.json" in body
        assert "cases: reference/cases.json" in body
        assert f"baseline: reference/baselines/{baseline}" in body
        assert "if: matrix.weather_kind == 'canonical'" in body
        assert "tools/fetch_weather.py --directory .validation-local/weather" in body
        assert "if: matrix.weather_kind == 'synthetic-ci'" in body
        assert "tools/synthetic_weather.py --output-dir .validation-local/weather" in body
        assert "--weather-kind ${{ matrix.weather_kind }}" in body
        assert "--cases ${{ matrix.cases }}" in body


def test_canonical_ci_fixtures_cover_pinned_inputs_and_explicit_rejections(tmp_path) -> None:
    from bem_testproblems import get_problem

    fixture_path = ROOT / "reference/canonical-cases.json"
    raw = fixture_path.read_bytes()
    specifications = {case["case_id"]: case for case in json.loads(raw)["cases"]}
    assert len(specifications) == 27
    weather_index = json.loads((ROOT / MANIFEST["weather_assets_index"]["path"]).read_bytes())
    weather_hashes = {item["cache_path"]: item["sha256"] for item in weather_index["files"]}
    expected_rejections = {
        "8.5.0": {"p01-orientation90": 1, "p10-lower": 7},
        "26.2.0": {"p04-lower": 1},
    }
    for version, failures in expected_rejections.items():
        baseline = json.loads((ROOT / f"reference/baselines/{version}-canonical.json").read_bytes())
        assert baseline["license"] == "MIT"
        assert baseline["engine_version"] == version
        assert re.fullmatch(r"[a-f0-9]{64}", baseline["engine_sha256"])
        assert baseline["upstream_commit"] == MANIFEST["upstream"]["commit"]
        assert baseline["weather_kind"] == "canonical"
        assert baseline["diagnostics_policy"] == "strict"
        assert baseline["case_fixture"] == {
            "path": "reference/canonical-cases.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        records = {case["case_id"]: case for case in baseline["cases"]}
        assert len(baseline["cases"]) == len(records) == len(specifications)
        assert set(records) == set(specifications)
        assert {key for key, row in records.items() if row["passed"] is False} == set(failures)
        for case_id, row in records.items():
            spec = specifications[case_id]
            assert all(row[key] == spec[key] for key in ("problem", "x", "purpose"))
            problem = get_problem(row["problem"])
            assert tuple(row["x"]) == problem.validate(row["x"])
            if problem.design_day:
                assert row["weather_file"] is None and row["weather_sha256"] is None
            else:
                assert row["weather_file"] == problem.weather_filename
                assert row["weather_sha256"] == weather_hashes[problem.weather_filename]

            suffix = "idf" if version == "8.5.0" else "epJSON"
            path = tmp_path / f"{version}-{case_id}.{suffix}"
            render = problem.render_legacy if version == "8.5.0" else problem.render_modern
            render(row["x"], path)
            rendered = path.read_bytes()
            assert hashlib.sha256(rendered).hexdigest() == row["input_sha256"]
            if "source_input_sha256" in row:
                assert "CRLF" in row["input_identity_normalization"]
                assert hashlib.sha256(rendered.replace(b"\n", b"\r\n")).hexdigest() == (
                    row["source_input_sha256"]
                )

            if case_id in failures:
                assert row["passed"] is False
                assert all(row[key] is None for key in ("objective", "components", "terms"))
                expected = row["expected_failure"]
                assert expected["stage"] == expected["reason"] == "simulation"
                assert expected["severe_count"] == failures[case_id]
                assert expected["fatal_count"] == 0
                assert len(expected["signatures"]) == failures[case_id]
                for signature in expected["signatures"]:
                    assert signature["kind"] == "CheckWarmupConvergence"
                    assert signature["zone"] and signature["environment"]
            else:
                assert row["passed"] is True
                assert math.isfinite(row["objective"])
                for values in (row["components"], row["terms"]):
                    assert values and all(math.isfinite(value) for value in values.values())


def test_warmup_variant_reference_has_separate_identity_and_only_strict_values(tmp_path):
    from bem_testproblems import get_problem

    fixture = ROOT / "reference/warmup-100-cases.json"
    cases = json.loads(fixture.read_text())["cases"]
    baseline = json.loads((ROOT / "reference/baselines/8.5.0-warmup-100-canonical.json").read_text())
    assert baseline["case_fixture"]["sha256"] == hashlib.sha256(fixture.read_bytes()).hexdigest()
    assert baseline["diagnostics_policy"] == "strict"
    assert baseline["license"] == "MIT"
    problem = get_problem(1, numerical_variant="warmup-100")
    assert baseline["numerical_variant"] == problem.provenance["numerical_variant"]
    records = {row["case_id"]: row for row in baseline["cases"]}
    assert len(records) == len(cases) == 5
    for case in cases:
        row = records[case["case_id"]]
        assert row["problem"] == case["problem"] == 1
        assert row["numerical_variant"] == case["numerical_variant"] == "warmup-100"
        assert row["x"] == case["x"]
        model = problem.render_legacy(row["x"], tmp_path / (case["case_id"] + ".idf"))
        assert hashlib.sha256(model.read_bytes()).hexdigest() == row["input_sha256"]
        assert row["passed"] is True and row["severe_count"] == row["fatal_count"] == 0
        assert problem.outer_loss(row["x"], row["components"]) == row["objective"]
        assert problem.objective_terms(row["x"], row["components"]) == row["terms"]


def test_publication_and_license_notices_are_present() -> None:
    assert "MIT License" in (ROOT / "LICENSE").read_text()
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    assert "BSD-3-Clause" in notices and "Christoph Waibel" in notices
    assert "DOE, NREL, PNNL and LBNL" in notices
    bib = (ROOT / "references.bib").read_text()
    for doi in (
        "10.1016/j.enbuild.2019.01.048",
        "10.1016/j.buildenv.2004.01.022",
        "10.1080/19401490903494597",
        "10.1016/j.enbuild.2006.08.009",
    ):
        assert doi in bib
    assert "10.1016/j.enbuild.2019.01.048" in (ROOT / "CITATION.cff").read_text()
