"""Checksum and path-boundary checks for the local tool installers."""

import hashlib
import zipfile

import pytest

from tools.install_energyplus import download, extract
from tools.validate_cases import compare_inputs, numerical_difference, require_successful_archive


def test_download_rejects_changed_bytes_before_installation(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"unexpected bytes")
    target = tmp_path / "cache" / "download"
    with pytest.raises(ValueError, match="Checksum mismatch"):
        download(source.as_uri(), target, "0" * 64)
    assert not target.exists()
    assert not target.with_name("download.part").exists()


def test_valid_cached_download_requires_no_source_access(tmp_path):
    target = tmp_path / "verified"
    target.write_bytes(b"verified")
    checksum = hashlib.sha256(b"verified").hexdigest()
    assert download("https://invalid.example/not-contacted", target, checksum) == target


def test_zip_cannot_escape_local_extraction_directory(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside", "not an installation file")
    with pytest.raises(ValueError, match="Unsafe archive path"):
        extract(archive, tmp_path / "installation")
    assert not (tmp_path / "outside").exists()


def test_reference_input_comparison_ignores_comments_but_checks_values(tmp_path):
    original, port = tmp_path / "original.idf", tmp_path / "python.idf"
    original.write_text("Material, Wall, 0.100000000000000; ! degrees\ufffd\n", encoding="utf-8")
    port.write_text("Material,Wall, .1; ! degrees °\n", encoding="utf-8")
    compare_inputs(original, port)
    port.write_text("Material,Wall,.2;\n")
    with pytest.raises(AssertionError, match="IDF field"):
        compare_inputs(original, port)


@pytest.mark.parametrize("changed", ["Obj,name,1,;", "Obj,name;Other,,1;"])
def test_reference_input_comparison_preserves_blanks_and_object_boundaries(tmp_path, changed):
    original, port = tmp_path / "original.idf", tmp_path / "python.idf"
    original.write_text("Obj,name,,1;")
    port.write_text(changed)
    with pytest.raises(AssertionError, match="IDF|object"):
        compare_inputs(original, port)


@pytest.mark.parametrize("code,end,diagnostics", [
    ("1", "EnergyPlus Completed Successfully", ""),
    ("0", "EnergyPlus Terminated", ""),
    ("0", "EnergyPlus Completed Successfully", " ** Severe ** warmup failed"),
])
def test_original_archive_cannot_accept_failed_or_partial_outputs(tmp_path, code, end, diagnostics):
    (tmp_path / "engine-exit-code.txt").write_text(code)
    (tmp_path / "eplusout.end").write_text(end)
    (tmp_path / "eplusout.err").write_text(diagnostics)
    with pytest.raises(RuntimeError, match="Original EnergyPlus"):
        require_successful_archive(tmp_path)


def test_original_archive_requires_complete_evidence(tmp_path):
    with pytest.raises(RuntimeError):
        require_successful_archive(tmp_path)
    (tmp_path / "engine-exit-code.txt").write_text("0\n")
    (tmp_path / "eplusout.end").write_text("EnergyPlus Completed Successfully")
    with pytest.raises(RuntimeError, match="diagnostics are missing"):
        require_successful_archive(tmp_path)
    (tmp_path / "eplusout.err").write_text(" ** Warning ** harmless warning")
    require_successful_archive(tmp_path)


def test_regression_differences_record_units_precision_and_zero_scale():
    result = numerical_difference(10.001, 10, "kWh", rtol=1e-6, atol=1e-7)
    assert not result["passed"]
    assert result["absolute_difference"] == pytest.approx(.001)
    assert result["allowed_difference"] == pytest.approx(10e-6)
    assert result["relative_difference"] == pytest.approx(.001 / 10)
    assert result["unit"] == "kWh"
    zero = numerical_difference(0, 0, "kW", rtol=1e-8, atol=1e-7)
    assert zero["passed"] and zero["relative_difference"] == 0


def test_function_value_tolerance_uses_the_reference_and_absolute_zero_fallback():
    assert numerical_difference(1000.0005, 1000, "EUR", rtol=1e-6, atol=1e-7)["passed"]
    assert not numerical_difference(1000.002, 1000, "EUR", rtol=1e-6, atol=1e-7)["passed"]
    small = numerical_difference(1e-8, 0, "kWh", rtol=1e-6, atol=1e-7)
    assert small["passed"] and small["relative_difference"] is None
