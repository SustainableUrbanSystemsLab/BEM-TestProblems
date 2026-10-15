"""Obtain only pinned 8.5 Windows core files for the independent CI oracle.

No weather, GUI utilities, Microsoft runtime DLLs or Rhino binaries are fetched.
The Windows runner must already have the official Visual C++ 2013 runtime.
"""

import argparse
import ctypes
import os
import shutil
import zipfile
from pathlib import Path

if __package__:
    from .install_energyplus import ROOT, download
else:
    from install_energyplus import ROOT, download

FILES = {
    "energyplus.exe": "50115bd8bacc102bf793caa7bbb33f19508b8cbf28b7c20169e301c9b32d3d98",
    "energyplusapi.zip": "d4cbe44ae4dc5f54269e0598b2979eadf4b2568b9c72ff6f77b42f38959fc7d2",
    "Energy+.idd": "701e070690ae3cc7dbb213830e2495852a7a22055cd951307e686a4845041fd1",
    "ExpandObjects.exe": "ea94b36833070467d6cea2d12913b787ee9bba4115b5acce9f84ac4801410253",
}
BASE = "https://raw.githubusercontent.com/milzj/BEOBenchmark/54736a6b899a488222ad3184f306c1f401daf4f9/BEOBenchmark_V1/Input/ep/"


def install(destination=None):
    if os.name != "nt":
        raise RuntimeError("The historical C# reference job requires Windows")
    for library in ("msvcp120.dll", "msvcr120.dll"):
        try:
            ctypes.WinDLL(library)
        except OSError as error:
            raise RuntimeError("Install the official Visual C++ 2013 x64 runtime first") from error
    destination = Path(destination or ROOT / ".tools/energyplus/8.5.0").resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for name, checksum in FILES.items():
        download(BASE + name, destination / name, checksum)
    with zipfile.ZipFile(destination / "energyplusapi.zip") as archive:
        if archive.namelist() != ["energyplusapi.dll"]:
            raise ValueError("Unexpected legacy API archive contents")
        archive.extractall(destination)
    shutil.copyfile(ROOT / "reference/licenses/EnergyPlus-8.5-LICENSE.txt", destination / "License.txt")
    print(destination / "energyplus.exe")
    return destination / "energyplus.exe"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path)
    install(parser.parse_args(argv).destination)


if __name__ == "__main__":
    main()
