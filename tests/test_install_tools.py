"""Checksum and path-boundary checks for the local tool installers."""

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

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


def test_download_replaces_corrupt_cache_only_after_verifying_replacement(tmp_path):
    target = tmp_path / "cached"
    target.write_bytes(b"old corrupt cache")
    source = tmp_path / "replacement"
    source.write_bytes(b"verified replacement")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    assert download(source.as_uri(), target, checksum) == target
    assert target.read_bytes() == b"verified replacement"
    assert not target.with_suffix(".part").exists()


def test_interrupted_download_preserves_existing_file_and_removes_partial(tmp_path, monkeypatch):
    from tools import install_energyplus as tool

    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError("interrupted transfer")
            return super().read(3)

    monkeypatch.setattr(tool.urllib.request, "urlopen", lambda *a, **k: Interrupted(b"payload"))
    target = tmp_path / "download"
    target.write_bytes(b"previous")
    with pytest.raises(OSError, match="interrupted"):
        download("https://example.invalid", target, "0" * 64)
    assert target.read_bytes() == b"previous"
    assert not target.with_name("download.part").exists()


def test_tar_extraction_rejects_symlink_escape(tmp_path):
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w") as bundle:
        link = tarfile.TarInfo("escaping-link")
        link.type, link.linkname = tarfile.SYMTYPE, "../outside"
        bundle.addfile(link)
    with pytest.raises(tarfile.FilterError):
        extract(archive, tmp_path / "installation")
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize("system,machine,expected", [
    ("Darwin", "arm64", "macos-arm64"), ("Linux", "aarch64", "linux-arm64"),
    ("Windows", "AMD64", "windows-x86_64"), ("Linux", "x86_64", "linux-x86_64"),
])
def test_installer_maps_supported_host_platforms(system, machine, expected, monkeypatch):
    from tools import install_energyplus as tool

    monkeypatch.setattr(tool.platform, "system", lambda: system)
    monkeypatch.setattr(tool.platform, "machine", lambda: machine)
    assert tool.platform_key() == expected


def test_unknown_platform_requires_an_explicit_choice(monkeypatch):
    from tools import install_energyplus as tool

    monkeypatch.setattr(tool.platform, "system", lambda: "unsupported")
    with pytest.raises(ValueError, match="Unsupported platform"):
        tool.platform_key()


@pytest.mark.parametrize("version", ["26.2.0", "99.3.1"])
@pytest.mark.parametrize("custom_destination", [False, True])
def test_modern_install_uses_manifest_version_and_refuses_unstamped_directory(
        tmp_path, monkeypatch, version, custom_destination):
    from tools import install_energyplus as tool

    metadata = {"version": version, "build": "test", "archives": {
        "windows-x86_64": ["Windows.zip", "1" * 64]}}
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "energyplus-downloads.json").write_text(json.dumps(metadata))
    bundle_path = tmp_path / "official.zip"
    with zipfile.ZipFile(bundle_path, "w") as bundle:
        bundle.writestr("installation/energyplus.exe", b"mock executable, never launched")
        bundle.writestr("installation/Energy+.idd", "mock dictionary")
    calls = []

    def fake_download(url, target, expected):
        calls.append((url, target, expected))
        return bundle_path

    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "download", fake_download)
    default_destination = tmp_path / ".tools/energyplus" / version
    destination = tmp_path / "installed" if custom_destination else default_destination
    requested_destination = destination if custom_destination else None
    executable = tool.install("windows-x86_64", requested_destination)
    assert executable == destination / "energyplus.exe"
    assert executable.read_bytes() == b"mock executable, never launched"
    archive_name = f"EnergyPlus-{version}-test-Windows.zip"
    assert calls == [(
        f"https://github.com/NatLabRockies/EnergyPlus/releases/download/v{version}/{archive_name}",
        tmp_path / ".tools/downloads" / archive_name,
        "1" * 64,
    )]
    stamp = json.loads((destination / "bem-install.json").read_text())
    assert stamp["archive_sha256"] == "1" * 64 and stamp["platform"] == "windows-x86_64"
    assert stamp["version"] == version and stamp["archive"] == archive_name
    assert tool.install("windows-x86_64", requested_destination) == executable
    assert len(calls) == 1
    unverified = tmp_path / "unverified"
    unverified.mkdir()
    with pytest.raises(FileExistsError, match="not a verified installation"):
        tool.install("windows-x86_64", unverified)


@pytest.mark.parametrize("count", [0, 2])
def test_modern_install_rejects_ambiguous_executable_layout(tmp_path, monkeypatch, count):
    from tools import install_energyplus as tool

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/energyplus-downloads.json").write_text(json.dumps({
        "version": "26.2.0", "build": "test", "archives": {"windows-x86_64": ["Windows.zip", "0" * 64]}}))
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for index in range(count):
            bundle.writestr(f"copy{index}/energyplus.exe", "mock")
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "download", lambda *args: archive)
    with pytest.raises(ValueError, match="Expected one"):
        tool.install("windows-x86_64", tmp_path / "installed")
    assert not (tmp_path / "installed").exists()


def test_legacy_installer_checks_platform_and_runtime_before_downloads(tmp_path, monkeypatch):
    from tools import install_reference_engine as tool

    monkeypatch.setattr(tool, "download", lambda *a: pytest.fail("No download before preflight"))
    monkeypatch.setattr(tool, "os", SimpleNamespace(name="posix"))
    with pytest.raises(RuntimeError, match="requires Windows"):
        tool.install(tmp_path / "engine")
    monkeypatch.setattr(tool, "os", SimpleNamespace(name="nt"))

    def missing_runtime(_):
        raise OSError("missing runtime")

    monkeypatch.setattr(tool, "ctypes", SimpleNamespace(WinDLL=missing_runtime))
    with pytest.raises(RuntimeError, match="Visual C"):
        tool.install(tmp_path / "engine")
    assert not (tmp_path / "engine").exists()


@pytest.mark.parametrize("member", ["energyplusapi.dll", "../energyplusapi.dll"])
def test_legacy_install_extracts_only_pinned_core_and_retains_notice(tmp_path, monkeypatch, member):
    from tools import install_reference_engine as tool

    (tmp_path / "reference/licenses").mkdir(parents=True)
    (tmp_path / "reference/licenses/EnergyPlus-8.5-LICENSE.txt").write_text("full notice")
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(tool, "ctypes", SimpleNamespace(WinDLL=lambda _: None))
    calls = []

    def fake_download(url, path, checksum):
        calls.append((url, Path(path).name, checksum))
        if path.suffix == ".zip":
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(member, "mock API, never loaded")
        else:
            path.write_bytes(b"mock core, never launched")

    monkeypatch.setattr(tool, "download", fake_download)
    destination = tmp_path / "engine"
    if member.startswith("../"):
        with pytest.raises(ValueError, match="Unexpected legacy API"):
            tool.install(destination)
        assert not (tmp_path / "energyplusapi.dll").exists()
    else:
        assert tool.install(destination) == destination / "energyplus.exe"
        assert (destination / "License.txt").read_text() == "full notice"
        assert (destination / "energyplusapi.dll").read_text() == "mock API, never loaded"
    assert {name: checksum for _, name, checksum in calls} == tool.FILES
