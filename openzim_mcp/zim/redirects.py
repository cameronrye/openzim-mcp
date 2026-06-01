"""Shared redirect-chain resolution for the ZIM operations mixins.

libzim's ``Entry.get_item()`` silently follows a redirect chain and would
spin on a cycle, so every read path resolves the chain explicitly first.
This module holds the single *strict* resolver — the one that raises on a
cycle or an over-long chain — that the content / archive / resource read
paths share.

This module also holds the *best-effort* resolver,
``best_effort_redirect_chain``, which NEVER raises and NEVER returns
``None``: on a cycle, an over-long chain, a ``None`` next-hop, or a raising
hop it returns the last good entry, so a malformed redirect degrades
instead of failing the whole call. It backs the speculative title-matching
path (``_SearchMixin._follow_redirect_chain``, now a thin wrapper) and the
synthetic main-page row (``_NamespaceMixin._materialise_new_scheme_main_entry``).

One best-effort variant stays intentionally separate because its failure
mode differs — it SKIPS-AND-OMITS rather than returning a last-good entry:

* ``_ArchiveMixin._read_old_scheme_metadata_value`` — on a cycle or an
  over-long chain it returns ``None`` so the caller OMITS that metadata key
  entirely, rather than rendering a stale redirect stub.
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


def best_effort_redirect_chain(entry: Any) -> Any:
    """Walk ``entry``'s ``is_redirect`` chain to its canonical target, best-effort.

    The forgiving sibling of :func:`resolve_redirect_chain`: it NEVER raises
    and NEVER returns ``None``. On a clean chain it returns the canonical
    (non-redirect) :class:`Entry`. On any failure — a hop that raises, a
    ``None`` next-hop, a missing/``None`` path, a cycle, or a chain longer
    than ``CONTENT.MAX_REDIRECT_DEPTH`` — it returns the last real entry it
    reached so the caller always has something to name (``.path`` /
    ``.title``).

    Used by speculative title-matching (search) and synthetic main-page
    rendering (namespace), where a malformed redirect should degrade
    gracefully rather than fail the whole call.
    """
    max_depth = CONTENT.MAX_REDIRECT_DEPTH
    target = entry
    last_good = entry
    seen: set = set()
    first_path = getattr(target, "path", None)
    if first_path is not None:
        seen.add(first_path)
    for _ in range(max_depth):
        if not getattr(target, "is_redirect", False):
            return target
        try:
            target = target.get_redirect_entry()
        except Exception:
            return last_good
        if target is None:
            return last_good
        tp = getattr(target, "path", None)
        if tp is None or tp in seen:
            return last_good
        seen.add(tp)
        last_good = target
    return target
