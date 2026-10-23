"""Reject coverage reports that leave an entire Python file unexercised."""

import argparse
import json
from pathlib import Path


def untested_files(report):
    files = report["files"]
    if not files:
        raise ValueError("The coverage report contains no Python files")
    return sorted(name for name, data in files.items()
                  if data["summary"]["num_statements"] > 0
                  and data["summary"]["covered_lines"] == 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    missing = untested_files(json.loads(args.report.read_text(encoding="utf-8")))
    if missing:
        print("Unexercised Python files: " + ", ".join(missing))
        return 1
    print("Every Python file with executable statements was exercised.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
