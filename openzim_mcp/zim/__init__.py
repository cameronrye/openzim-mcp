"""ZIM operations package.

Public API surface is preserved by re-exporting ``ZimOperations`` and the
module-level helpers/constants here. External callers should keep importing
from ``openzim_mcp.zim_operations`` (the backward-compat shim) — this
package's internal layout is an implementation detail.
"""

from openzim_mcp.zim.archive import (  # noqa: F401
    MAX_REDIRECT_DEPTH,
    PaginationCursor,
    ZimOperations,
    zim_archive,
)

__all__ = [
    "MAX_REDIRECT_DEPTH",
    "PaginationCursor",
    "ZimOperations",
    "zim_archive",
]
