"""Shared libzim mock builders for the ``ZimOperations`` regression suites.

Several regression modules drive ``ZimOperations`` against a fully mocked
libzim layer using the same handful of stubs. They live here so the suites
share one definition rather than drifting copies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List, Optional
from unittest.mock import MagicMock

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig, ContentConfig, OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations

# Distinguishes "caller did not ask for is_redirect" from "caller asked for
# False" — the two are not equivalent on a MagicMock. See ``make_entry``.
_UNSET: Any = object()


def make_ops(tmp_path: Path) -> ZimOperations:
    """A cache-disabled ``ZimOperations`` rooted at ``tmp_path``."""
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
    )
    return ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=200),
    )


def make_entry(
    eid: str, *, is_redirect: Any = _UNSET, with_item: bool = True
) -> MagicMock:
    """A mock entry whose path is ``eid`` and title the last path segment.

    ``is_redirect`` defaults to unset rather than ``False``: production code
    reads it as ``getattr(entry, "is_redirect", False)``, and on a bare
    ``MagicMock`` the attribute auto-creates as a *truthy* mock. Pinning it
    to ``False`` therefore flips which branch a suite exercises, so callers
    that care must say so explicitly.

    ``with_item=False`` leaves ``get_item`` unconfigured, for suites that
    never materialise content and would otherwise assert against a mimetype
    they did not choose.
    """
    e = MagicMock()
    e.path = eid
    e.title = eid.rsplit("/", 1)[-1]
    if is_redirect is not _UNSET:
        e.is_redirect = is_redirect
    if with_item:
        item = MagicMock()
        item.mimetype = "text/html"
        item.content = b"<p>body text</p>"
        e.get_item.return_value = item
    return e


def make_search_stub(
    entry_ids: List[str], estimated: Optional[int] = None
) -> MagicMock:
    """A Xapian search stub over ``entry_ids``.

    ``estimated`` overrides ``getEstimatedMatches`` so suites can model the
    real index's over- and under-estimates independently of page contents.
    """
    search = MagicMock()
    search.getEstimatedMatches.return_value = (
        len(entry_ids) if estimated is None else estimated
    )
    search.getResults.side_effect = lambda start, count: entry_ids[
        start : start + count
    ]
    return search


def make_archive_stub(get_entry: Callable[[str], Any] = make_entry) -> MagicMock:
    """An old-namespace-scheme archive stub with a full-text index."""
    archive = MagicMock()
    archive.has_new_namespace_scheme = False
    archive.has_fulltext_index = True
    archive.get_entry_by_path.side_effect = get_entry
    return archive
