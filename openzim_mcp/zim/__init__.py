"""ZIM operations package.

The package layout is an implementation detail; external callers should
keep importing from ``openzim_mcp.zim_operations`` (the backward-compat
shim). The shim re-exports everything below.
"""

from openzim_mcp.zim.archive import (  # noqa: F401
    ARCHIVE_OPEN_TIMEOUT,
    MAX_REDIRECT_DEPTH,
    PaginationCursor,
    ZimOperations,
    zim_archive,
)

__all__ = [
    "ARCHIVE_OPEN_TIMEOUT",
    "MAX_REDIRECT_DEPTH",
    "PaginationCursor",
    "ZimOperations",
    "zim_archive",
]
