"""Fetch checksum-pinned originals from the fork into an ignored local cache."""

import argparse
import json
import os
from importlib.resources import files
from pathlib import Path

if __package__:
    from .install_energyplus import ROOT, download
else:
    from install_energyplus import ROOT, download


def fetch_reference(directory=None):
    manifest = json.loads(files("bem_testproblems").joinpath("data/reference-assets.json").read_text())
    directory = Path(directory or os.environ.get("BEM_REFERENCE_DIR")
                     or ROOT / ".reference-cache/beobenchmark").expanduser().resolve()
    for entry in manifest["files"]:
        destination = (directory / entry["cache_path"]).resolve()
        if not destination.is_relative_to(directory):
            raise ValueError("Reference path escapes the local cache")
        download(entry["url"], destination, entry["sha256"])
    print(f"Verified {len(manifest['files'])} files at {manifest['source_commit']} in {directory}")
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    fetch_reference(parser.parse_args().directory)
