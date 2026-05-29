"""Shared redirect-chain resolution for the ZIM operations mixins.

libzim's ``Entry.get_item()`` silently follows a redirect chain and would
spin on a cycle, so every read path resolves the chain explicitly first.
This module holds the single *strict* resolver — the one that raises on a
cycle or an over-long chain — that the content / archive / resource read
paths share.

Three intentionally-different best-effort variants are NOT folded in here,
because they must never raise (a malformed redirect should degrade, not
fail the whole call):

* ``_ArchiveMixin._extract_zim_metadata`` — skips a bad chain and omits
  that metadata key.
* ``_NamespaceMixin._materialise_new_scheme_main_entry`` — returns the last
  good entry so main-page listing still works.
* ``_SearchMixin._follow_redirect_chain`` — returns the last good entry so
  speculative title matching always has something to name.
"""

from typing import Any

from ..defaults import CONTENT
from ..exceptions import OpenZimMcpArchiveError


def resolve_redirect_chain(entry: Any, *, context: str) -> Any:
    """Follow ``entry``'s redirect chain to its canonical (non-redirect) target.

    Bounded by ``CONTENT.MAX_REDIRECT_DEPTH`` with seen-path cycle
    detection. Raises :class:`OpenZimMcpArchiveError` on a cycle or a chain
    longer than the cap. ``context`` is appended to the depth-exceeded
    message so each caller keeps its site-specific wording (e.g.
    ``"starting at C/Foo"``, ``"in main-page lookup"``,
    ``"for: 'A/Bar'"``).

    Returns the resolved :class:`Entry` (the caller typically reads
    ``resolved.path`` back to reflect the entry actually served).
    """
    max_depth = CONTENT.MAX_REDIRECT_DEPTH
    seen: set[str] = set()
    for _ in range(max_depth):
        if not getattr(entry, "is_redirect", False):
            return entry
        if entry.path in seen:
            raise OpenZimMcpArchiveError(f"Redirect cycle detected at {entry.path}")
        seen.add(entry.path)
        entry = entry.get_redirect_entry()
    if getattr(entry, "is_redirect", False):
        raise OpenZimMcpArchiveError(
            f"Redirect chain too deep (>{max_depth}) {context}"
        )
    return entry
