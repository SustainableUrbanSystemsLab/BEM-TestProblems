"""Download a pinned official archive into this project's ignored .tools folder."""

import argparse
import hashlib
import json
import platform
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def download(url, path, expected):
    """Verify bytes before making them available to extraction or execution."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and digest(path) == expected:
        return path
    temporary = path.with_name(path.name + ".part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "BEM-TestProblems/0.1"})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as out:
            shutil.copyfileobj(response, out)
        if digest(temporary) != expected:
            raise ValueError(f"Checksum mismatch for {url}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def platform_key():
    system = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(platform.system())
    machine = {"AMD64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine())
    if system is None or machine is None:
        raise ValueError("Unsupported platform; specify a supported --platform explicitly")
    return f"{system}-{machine}"


def extract(archive, directory):
    directory = Path(directory).resolve()
    if str(archive).endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                if not (directory / member.filename).resolve().is_relative_to(directory):
                    raise ValueError("Unsafe archive path")
            bundle.extractall(directory)
    else:
        with tarfile.open(archive) as bundle:
            bundle.extractall(directory, filter="data")


def install(key=None, destination=None):
    metadata = json.loads((ROOT / "assets/energyplus-downloads.json").read_text())
    version = metadata["version"]
    key = key or platform_key()
    suffix, checksum = metadata["archives"][key]
    name = f"EnergyPlus-{version}-{metadata['build']}-{suffix}"
    destination = Path(destination or ROOT / ".tools/energyplus" / version).resolve()
    executable = destination / ("energyplus.exe" if key.startswith("windows") else "energyplus")
    stamp = destination / "bem-install.json"
    if stamp.is_file():
        prior = json.loads(stamp.read_text())
        if prior.get("archive_sha256") == checksum and executable.is_file():
            print(executable)
            return executable
    if destination.exists():
        raise FileExistsError(f"Destination is not a verified installation: {destination}")
    archive = download(
        f"https://github.com/NatLabRockies/EnergyPlus/releases/download/v{version}/{name}",
        ROOT / ".tools/downloads" / name, checksum,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="extract-", dir=destination.parent) as temporary:
        extract(archive, temporary)
        candidates = list(Path(temporary).rglob(executable.name))
        candidates = [p for p in candidates if p.is_file()]
        if len(candidates) != 1:
            raise ValueError(f"Expected one EnergyPlus executable, found {len(candidates)}")
        shutil.move(str(candidates[0].parent), str(destination))
    stamp.write_text(json.dumps({"version": version, "platform": key,
                                 "archive": name, "archive_sha256": checksum}, indent=2) + "\n")
    print(executable)
    return executable


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform")
    parser.add_argument("--destination", type=Path)
    options = parser.parse_args(argv)
    install(options.platform, options.destination)


if __name__ == "__main__":
    main()
