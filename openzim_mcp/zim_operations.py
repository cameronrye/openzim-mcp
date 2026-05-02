"""Backward-compat shim for ``openzim_mcp.zim_operations``.

The real implementation lives in :mod:`openzim_mcp.zim` (a small package
of mixins coordinated by :class:`openzim_mcp.zim.archive.ZimOperations`).
External callers that historically imported from this module continue to
work via the re-exports below — both for the public API
(``ZimOperations``, ``zim_archive``, ``PaginationCursor``) and for the
internal symbols that tests patch (``Archive``, ``Query``, ``Searcher``,
``SuggestionSearcher``, ``MAX_REDIRECT_DEPTH``).

The mixin modules look up these symbols on this module at *call time*
(via ``import openzim_mcp.zim_operations as ...``), so test patches like
``patch("openzim_mcp.zim_operations.zim_archive")`` keep working without
any test changes after the refactor.
"""

from openzim_mcp.zim.archive import (  # noqa: F401
    ARCHIVE_OPEN_TIMEOUT,
    MAX_REDIRECT_DEPTH,
    Archive,
    PaginationCursor,
    Query,
    Searcher,
    SuggestionSearcher,
    ZimOperations,
    zim_archive,
)

__all__ = [
    "ARCHIVE_OPEN_TIMEOUT",
    "Archive",
    "MAX_REDIRECT_DEPTH",
    "PaginationCursor",
    "Query",
    "Searcher",
    "SuggestionSearcher",
    "ZimOperations",
    "zim_archive",
]
