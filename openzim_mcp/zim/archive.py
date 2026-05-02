"""Skeleton archive module.

Initial step of the ``zim_operations`` -> ``zim/`` package refactor: this
module just re-exports the existing implementations from
``openzim_mcp.zim_operations`` so the new package layout is wired up
without any code movement. Subsequent commits move methods into mixins
under this package and reduce ``zim_operations.py`` to a pure shim.
"""

from openzim_mcp.zim_operations import (  # noqa: F401
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
