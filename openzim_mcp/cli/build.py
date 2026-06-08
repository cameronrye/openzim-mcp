"""`openzim-mcp build <artifact> ...` — offline build artifacts.

``build`` is a namespace so future artifacts (e.g. ``build embeddings`` under
sub-D-4) slot in beside ``link-graph``.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from openzim_mcp.linkgraph.builder import build_link_graph


def _link_graph(args: argparse.Namespace) -> int:
    """Run the link-graph build for one archive and print a summary."""

    def _progress(done: int, total: int) -> None:
        """Emit a one-line progress message to stderr."""
        if not args.quiet:
            print(f"  …walked {done}/{total} entries", file=sys.stderr)

    try:
        stats = build_link_graph(
            args.archive, args.output, force=args.force, progress=_progress
        )
    except FileExistsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — operator CLI: report + nonzero exit
        print(f"error: link-graph build failed: {e}", file=sys.stderr)
        return 2
    out = args.output or f"{args.archive}.linkgraph.sqlite"
    print(
        f"built {out}: {stats.node_count} nodes, {stats.edge_count} edges, "
        f"{stats.bytes_written} bytes"
    )
    return 0


def build_main(argv: Optional[List[str]] = None) -> int:
    """Entry point for ``openzim-mcp build ...``. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="openzim-mcp build")
    sub = parser.add_subparsers(dest="artifact", required=True)
    lg = sub.add_parser("link-graph", help="Build the inbound link-graph sidecar.")
    lg.add_argument("archive", help="Path to the .zim archive.")
    lg.add_argument("--output", default=None, help="Sidecar output path.")
    lg.add_argument(
        "--force", action="store_true", help="Overwrite an existing sidecar."
    )
    lg.add_argument("--quiet", action="store_true", help="Suppress progress output.")
    lg.set_defaults(func=_link_graph)
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # unknown artifact / bad args -> nonzero, no traceback
        return int(e.code or 2)
    return int(args.func(args))
