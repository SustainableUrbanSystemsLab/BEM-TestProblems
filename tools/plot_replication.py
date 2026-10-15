# SPDX-License-Identifier: MIT
"""Create Figure8/9-style views from completed checkpointed experiments."""

import argparse
import json
from pathlib import Path

from bem_testproblems.replication_plots import plot_replication


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(plot_replication(args.experiment, output_dir=args.output_dir), indent=2))


if __name__ == "__main__":
    main()
