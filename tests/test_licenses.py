# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sustainable Urban Systems Lab
"""Check retained notices, immutable upstream assets and distribution boundaries."""

from __future__ import annotations

import hashlib
import json
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
