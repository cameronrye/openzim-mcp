"""Regression test for the post-a14 beta-test sweep: ``title_match_hit``
must report the canonical (post-redirect) path, not the redirect's own
path.

Motivating defect: the live-archive probe ``"famous people from big
rapids, michigan"`` resolved via the new tail-probe path. libzim has
``Big_Rapids_Michigan`` as a redirect that points at the canonical
``Big_Rapids,_Michigan`` entry. ``title_match_hit`` returned the
redirect's path (``Big_Rapids_Michigan``), so the synthesize ``cite_id``
became ``…/Big_Rapids_Michigan`` while a different query
(``"Big Rapids Michigan Notable people"``) that hit the same article
via BM25 yielded ``…/Big_Rapids,_Michigan``.

Multi-round agents using ``cite_id`` as a stable key would split the
same article into two entries.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


def _make_redirect_entry(path: str, target: Any) -> Any:
    entry = MagicMock()
    entry.path = path
    entry.title = path.replace("_", " ").split("/")[-1]
    entry.is_redirect = True
    entry.get_redirect_entry.return_value = target
    return entry


def _make_canonical_entry(path: str) -> Any:
    entry = MagicMock()
    entry.path = path
    entry.title = path.replace("_", " ").split("/")[-1]
    entry.is_redirect = False
    return entry


def test_title_match_hit_returns_canonical_path_not_redirect_path() -> None:
    """When the title-index fast path lands on a redirect entry, the
    returned hit must report the canonical (post-redirect) path. This
    keeps the synthesize ``cite_id`` stable across different query
    shapes that find the same article via different lookup variants."""
    from openzim_mcp.zim.search import _SearchMixin

    canonical = _make_canonical_entry("Big_Rapids,_Michigan")
    redirect = _make_redirect_entry("Big_Rapids_Michigan", canonical)

    archive = MagicMock()
    # Only the redirect path exists in the archive's title-index probe.
    # ``_find_entry_fast_path`` tries C/ then A/ prefixes for several
    # case variants, so make any prefix+variant on the redirect path
    # the resolver hits.

    def has_entry_by_path(full_path: str) -> bool:
        return full_path.endswith("Big_Rapids_Michigan")

    def get_entry_by_path(full_path: str) -> Any:
        if full_path.endswith("Big_Rapids_Michigan"):
            return redirect
        raise RuntimeError(f"no entry at {full_path!r}")

    archive.has_entry_by_path.side_effect = has_entry_by_path
    archive.get_entry_by_path.side_effect = get_entry_by_path

    # Bind ``title_match_hit`` from the mixin against a minimal
    # instance carrying just the snippet path stub. The function
    # is structurally simple and only depends on ``self._get_entry_snippet``.
    class _Stub(_SearchMixin):
        def _get_entry_snippet(self, _entry: Any, query: Any = None) -> str:
            return ""

    stub = _Stub.__new__(_Stub)
    hit = stub.title_match_hit(archive, "big rapids michigan")

    assert hit is not None, "Fast-path should resolve the redirect entry."
    assert hit["path"] == "Big_Rapids,_Michigan", (
        f"title_match_hit returned the redirect path {hit['path']!r} "
        f"instead of the canonical {canonical.path!r}. Multi-round "
        f"agents using cite_id as a stable key would now split the same "
        f"article across two cite_ids depending on which lookup variant "
        f"matched."
    )
