"""Shared executable fixture for process and spawned-worker tests."""

import os
import shlex
import sys
import textwrap

import pytest


@pytest.fixture
def fake_engine(tmp_path):
    script = tmp_path / "fake_engine.py"
    script.write_text(textwrap.dedent('''\
        import json, os, pathlib, subprocess, sys, time
        if "--version" in sys.argv:
            print("EnergyPlus, Version 26.2.0-test")
            raise SystemExit(0)
        out = pathlib.Path(sys.argv[sys.argv.index("-d") + 1])
        inp = pathlib.Path(sys.argv[-1])
        settings = json.loads(inp.read_text()).get("test", {})
        print("stdout retained", flush=True)
        print("stderr retained", file=sys.stderr, flush=True)
        (out / "observed.json").write_text(json.dumps({"cwd": os.getcwd(), "argv": sys.argv}))
        if settings.get("child"):
            target = str(out / "orphan-marker")
            subprocess.Popen([sys.executable, "-c", "import time,pathlib;time.sleep(1.5);pathlib.Path(" + repr(target) + ").write_text('orphan')"])
            time.sleep(30)
        if settings.get("exit"):
            raise SystemExit(settings["exit"])
        (out / "eplusout.err").write_text("** Severe  ** bad model" if settings.get("severe") else "0 Warning; 0 Severe Errors")
        if not settings.get("incomplete"):
            (out / "eplusout.end").write_text("EnergyPlus Completed Successfully")
        (out / "eplusout.eso").write_text("End of Data Dictionary\\nEnd of Data\\n")
    '''))
    if os.name == "nt":
        executable = tmp_path / "fake_energyplus.cmd"
        executable.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        executable = tmp_path / "fake_energyplus"
        executable.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} "$@"\n')
        executable.chmod(0o755)
    return executable

