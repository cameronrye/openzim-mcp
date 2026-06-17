#!/usr/bin/env python3
"""Entry-point shim for the OpenZIM MCP MCPB bundle.

The bundle launches the server with ``uvx openzim-mcp@<version>`` (see
``server.mcp_config.command`` in ``manifest.json``), which resolves the
published PyPI package and its native ``libzim`` wheel for the host's platform
at run time. This avoids vendoring a platform-specific virtualenv (which would
be locked to one OS/arch and blow the registry's bundle-size limit).

This file exists to satisfy the MCPB manifest's required ``entry_point`` and as
a direct fallback: if invoked with the ``openzim_mcp`` package already
importable, it delegates to the package's CLI.
"""

from openzim_mcp.main import main

if __name__ == "__main__":
    main()
