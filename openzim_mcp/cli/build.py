"""`openzim-mcp build <artifact> ...` — offline build artifacts.

``build`` is a namespace so future artifacts (e.g. ``build embeddings`` under
sub-D-4) slot in beside ``link-graph``.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import List, Optional

from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.linkgraph.builder import build_link_graph
from openzim_mcp.linkgraph.reader import sidecar_path_for


def _link_graph(args: argparse.Namespace) -> int:
    """Run the link-graph build for one archive and print a summary.

    Exit codes: 0 success; 1 user-fixable precondition (archive not found /
    not a file / not a valid ZIM / sidecar exists without --force / cannot
    write the sidecar); 2 unexpected build failure.
    """

    def _progress(done: int, total: int) -> None:
        """Emit a one-line progress message to stderr."""
        if not args.quiet:
            print(f"  …walked {done}/{total} entries", file=sys.stderr)

    # Pre-flight separates "missing" from "exists-but-invalid" so each gets a
    # distinct, actionable message instead of surfacing from deep in the
    # libzim open path.
    if not os.path.exists(args.archive):
        print(f"error: archive not found: {args.archive}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.archive):
        print(f"error: not a file: {args.archive}", file=sys.stderr)
        return 1

    out = args.output or sidecar_path_for(args.archive)
    try:
        stats = build_link_graph(
            args.archive, args.output, force=args.force, progress=_progress
        )
    except FileExistsError:
        # FileExistsError is an OSError subclass, so it MUST precede the
        # (sqlite3.OperationalError, OSError) clause below. The CLI builds its
        # own --force message rather than echoing the builder's force=True text.
        print(
            f"error: sidecar already exists: {out}; pass --force to overwrite.",
            file=sys.stderr,
        )
        return 1
    except OpenZimMcpArchiveError:
        # The pre-flight confirmed the file exists, so an open failure here
        # means the file is not a valid ZIM archive.
        print(f"error: not a valid ZIM archive: {args.archive}", file=sys.stderr)
        return 1
    except (sqlite3.OperationalError, OSError) as e:
        print(f"error: cannot write sidecar to {out}: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — operator CLI: report + nonzero exit
        print(f"error: link-graph build failed: {e}", file=sys.stderr)
        return 2
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
