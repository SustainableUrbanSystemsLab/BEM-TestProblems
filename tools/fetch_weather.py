"""Retrieve the exact four annual benchmark EPWs into a project-local cache."""

import argparse
import json
from importlib.resources import files
from pathlib import Path

if __package__:
    from .install_energyplus import ROOT, download
else:
    from install_energyplus import ROOT, download


def fetch_weather(directory=None):
    manifest = json.loads(files("bem_testproblems").joinpath("data/weather-assets.json").read_text())
    directory = Path(directory or ROOT / ".cache/weather").expanduser().resolve()
    for entry in manifest["files"]:
        destination = (directory / entry["cache_path"]).resolve()
        if not destination.is_relative_to(directory):
            raise ValueError("Weather path escapes the local cache")
        download(entry["url"], destination, entry["sha256"])
    (directory / "weather-provenance.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Verified {len(manifest['files'])} historical EPWs in {directory}")
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    fetch_weather(parser.parse_args().directory)
