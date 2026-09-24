#!/usr/bin/env python3
"""Entry point script for MikroTik OSPF Topology Visualizer."""

import sys
import argparse
from ospf_viz import __version__


def parse_args():
    parser = argparse.ArgumentParser(
        description="MikroTik RouterOS 7 OSPF Topology Visualizer",
        add_help=True,
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program version and exit."
    )
    args, _ = parser.parse_known_args()
    return args


if __name__ == "__main__":
    parse_args()
    from ospf_viz.gui import main
    main()
