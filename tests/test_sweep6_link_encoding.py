"""Link targets must come back in the spelling the archive can serve.

ZIM stores entry paths as raw UTF-8 (``A/El_Niño``), but the ``<a href>`` inside
archived HTML is percent-encoded per RFC 3986 (``El_Ni%C3%B1o``).
``_resolve_link_to_entry_path`` normalises the href against the source
directory but never decodes it, so both consumers emitted a spelling libzim
cannot resolve:

* ``get_related_articles_data`` put it straight into ``results[].path``, and
  because the title lookup failed too, ``title`` stayed at its raw-path
  placeholder — so the wire payload read
  ``{"path": "A/El_Ni%C3%B1o", "title": "A/El_Ni%C3%B1o"}``. Feeding that
  ``path`` back into ``zim_get`` — the obvious next call — answers
  "Entry not found".
* ``_parse_internal_link_edges`` used it as the edge target, so the inbound
  link graph indexed articles under unfetchable keys.

The raw spelling is tried FIRST and only falls back to the decoded one,
because some archives really do store a literal ``%`` in a path (warc2zim
asset names like ``I/Al_Gore%2C_….webp``); decoding those unconditionally
would break the paths that currently work.
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

_SOURCE = "A/John_Michael_Wallace"


@pytest.fixture
def ops_and_zim(real_content_zim_files):
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("wikipedia climate corpus archive not available")
    config = OpenZimMcpConfig(allowed_directories=[str(zim.parent)])
    return OpenZimMcpServer(config).zim_operations, str(zim)


def test_related_paths_are_fetchable(ops_and_zim) -> None:
    """Every related path must resolve in the archive it came from."""
    ops, zim = ops_and_zim
    result = ops.get_related_articles_data(zim, _SOURCE, limit=10)
    paths = [row.get("path") for row in (result.get("results") or [])]
    assert paths, "no related articles to check"

    import libzim.reader as lr

    archive = lr.Archive(zim)
    unresolvable = []
    for path in paths:
        try:
            archive.get_entry_by_path(path)
        except Exception:
            unresolvable.append(path)
    assert (
        not unresolvable
    ), f"related targets not fetchable from their own archive: {unresolvable}"


def _served_path(zim: str, path: str) -> str:
    """The spelling the archive actually serves for ``path``.

    Related rows carry the canonical (post-redirect) path so they agree with
    the inbound link graph; in this corpus ``A/El_Niño`` is a redirect, so
    the row names its target. Resolve it here rather than hardcoding, so the
    test states the contract ("decoded, and fetchable as-is") not the data.
    """
    import libzim.reader as lr

    entry = lr.Archive(zim).get_entry_by_path(path)
    while entry.is_redirect:
        entry = entry.get_redirect_entry()
    return str(entry.path)


def test_non_ascii_target_is_decoded(ops_and_zim) -> None:
    """The concrete case: El Niño arrives decoded, not percent-encoded."""
    ops, zim = ops_and_zim
    result = ops.get_related_articles_data(zim, _SOURCE, limit=10)
    paths = [row.get("path") for row in (result.get("results") or [])]
    assert _served_path(zim, "A/El_Niño") in paths, paths
    assert not any("%C3%B1" in p for p in paths), paths


def test_decoded_target_carries_a_real_title(ops_and_zim) -> None:
    """Title resolution failed alongside the path, leaving a placeholder."""
    ops, zim = ops_and_zim
    result = ops.get_related_articles_data(zim, _SOURCE, limit=10)
    expected = _served_path(zim, "A/El_Niño")
    row = next(
        (r for r in (result.get("results") or []) if r.get("path") == expected),
        None,
    )
    assert row is not None
    # The placeholder is the path itself; a resolved title is anything else.
    assert row.get("title") not in (None, "", expected)


def test_related_path_round_trips_into_zim_get(ops_and_zim) -> None:
    """The obvious next call must succeed on what we just handed back."""
    ops, zim = ops_and_zim
    result = ops.get_related_articles_data(zim, _SOURCE, limit=10)
    paths = [row.get("path") for row in (result.get("results") or [])]
    target = next((p for p in paths if "%" in unquote(p) or "Ni" in p), paths[0])
    entry = ops.get_zim_entry_data(zim, target)
    assert not entry.get("error"), entry


def test_raw_spelling_wins_when_it_resolves() -> None:
    """A path that genuinely contains '%' must not be decoded away."""
    from openzim_mcp.zim.structure import _resolve_entry_spelling

    class _Archive:
        def get_entry_by_path(self, path):
            if path == "I/Al_Gore%2C_2007.webp":
                return object()
            raise KeyError(path)

    entry, spelling = _resolve_entry_spelling(_Archive(), "I/Al_Gore%2C_2007.webp")
    assert entry is not None
    assert spelling == "I/Al_Gore%2C_2007.webp"


def test_decoded_spelling_used_only_as_fallback() -> None:
    from openzim_mcp.zim.structure import _resolve_entry_spelling

    class _Archive:
        def get_entry_by_path(self, path):
            if path == "A/El_Niño":
                return object()
            raise KeyError(path)

    entry, spelling = _resolve_entry_spelling(_Archive(), "A/El_Ni%C3%B1o")
    assert entry is not None
    assert spelling == "A/El_Niño"


def test_unresolvable_path_is_returned_unchanged() -> None:
    """Best-effort: neither spelling resolving must not drop the edge."""
    from openzim_mcp.zim.structure import _resolve_entry_spelling

    class _Archive:
        def get_entry_by_path(self, path):
            raise KeyError(path)

    entry, spelling = _resolve_entry_spelling(_Archive(), "A/Missing%20Thing")
    assert entry is None
    assert spelling == "A/Missing%20Thing"
