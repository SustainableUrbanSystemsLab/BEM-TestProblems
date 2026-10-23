"""Only the packaged pins may authorize an optional original model cache."""

import hashlib
import json

import pytest

import bem_testproblems.reference as reference


@pytest.fixture
def pinned_template(tmp_path, monkeypatch):
    package = tmp_path / "package"
    cache = tmp_path / "cache"
    (package / "data").mkdir(parents=True)
    (cache / "models").mkdir(parents=True)
    body = b"! Independent test fixture\r\nVersion,8.5;\r\n"
    filename = "fixture.idf"
    template = cache / "models" / filename
    template.write_bytes(body)
    record = {"cache_path": f"models/{filename}", "sha256": hashlib.sha256(body).hexdigest()}
    (package / "data" / "reference-assets.json").write_text(json.dumps({"files": [record]}))
    monkeypatch.setattr(reference, "files", lambda package_name: package)
    monkeypatch.setenv("BEM_REFERENCE_DIR", str(cache))
    return template


def test_packaged_pin_is_checked_even_when_cache_claims_different_identity(pinned_template):
    assert reference.legacy_template_path(pinned_template.name) == pinned_template
    pinned_template.write_bytes(b"Replaced model bytes")
    # An untrusted cache-local manifest must never override the package pin.
    (pinned_template.parent.parent / "reference-assets.json").write_text(json.dumps({
        "files": [{
            "cache_path": f"models/{pinned_template.name}",
            "sha256": hashlib.sha256(pinned_template.read_bytes()).hexdigest(),
        }],
    }))
    with pytest.raises(ValueError, match="checksum mismatch"):
        reference.legacy_template_path(pinned_template.name)


@pytest.mark.parametrize("filename", [None, "", ".", "../fixture.idf", "models/fixture.idf"])
def test_only_plain_known_filenames_are_accepted(pinned_template, filename):
    with pytest.raises(ValueError):
        reference.legacy_template_path(filename)


def test_unknown_or_missing_template_never_creates_cache_files(pinned_template):
    with pytest.raises(ValueError, match="Unknown original"):
        reference.legacy_template_path("unlisted.idf")
    pinned_template.unlink()
    with pytest.raises(FileNotFoundError, match="fetch_reference.py"):
        reference.legacy_template_path(pinned_template.name)
    assert list(pinned_template.parent.iterdir()) == []


def test_installed_package_uses_callers_cache_not_installation_directory(tmp_path, monkeypatch):
    module = tmp_path / "installation" / "site-packages" / "bem_testproblems" / "reference.py"
    monkeypatch.setattr(reference, "__file__", str(module))
    monkeypatch.delenv("BEM_REFERENCE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert reference.reference_root() == tmp_path / ".reference-cache" / "beobenchmark"


def test_relative_reference_override_is_resolved_from_caller(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BEM_REFERENCE_DIR", "custom-reference")
    assert reference.reference_root() == tmp_path / "custom-reference"

