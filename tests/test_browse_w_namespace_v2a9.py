"""Tests for the v2.0.0a9 D2 fix: ``browse_namespace W`` now uses the
SAME probes ``list_namespaces`` uses (``has_main_entry`` /
``has_illustration()``) instead of ``has_entry_by_path("W/mainPage")``.

The original D3 fix in v2.0.0a7 worked against synthetic mocks but
returned 0 entries on real Wikipedia maxi ZIMs because the main-page
entry lives in C with a redirect from a well-known alias — not as a
literal ``W/mainPage`` path. ``list_namespaces`` reported W=2 (via
``archive.has_main_entry`` + ``archive.has_illustration()``) while
``browse_namespace W`` reported empty, with no way for a small model
to reconcile the two responses.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from openzim_mcp.zim.namespace import _NamespaceMixin


def _make_mixin():
    """Build a minimal ``_NamespaceMixin`` instance with mocked deps.

    The mixin reaches for ``self.content_processor`` and ``self.cache``
    in some paths; ``_browse_new_scheme_w_paginated`` and its
    materialisers don't, so a bare ``object`` subclass suffices for
    this unit test.
    """

    class _Stub(_NamespaceMixin):
        def __init__(self):
            self.content_processor = MagicMock()
            self.cache = MagicMock()
            self.cache.get = lambda k: None
            self.cache.set = lambda k, v: None

    return _Stub()


def _wikipedia_like_archive():
    """Mock archive matching the real Wikipedia maxi shape.

    * ``has_main_entry`` is True — the well-known main entry resolves
      via ``archive.main_entry`` (which here points at a synthetic
      User-namespace C-landing page, as real Wikipedia exports do).
    * ``has_illustration()`` is True — the favicon exists, reachable
      via ``get_illustration_item``.
    * ``has_entry_by_path("W/mainPage")`` is False — the literal
      ``W/`` path does NOT exist on this archive flavour.
    """
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.has_main_entry = True
    archive.has_illustration.return_value = True
    archive.has_entry_by_path.return_value = False

    # main_entry is a redirect to the landing page (real Wikipedia
    # exports do this — the resolved title lands in C).
    landing = MagicMock()
    landing.path = "C/User:Landing"
    landing.title = "Wikipedia Landing"
    landing.is_redirect = False
    main_entry = MagicMock()
    main_entry.path = "W/mainPage"
    main_entry.title = "mainPage"
    main_entry.is_redirect = True
    main_entry.get_redirect_entry.return_value = landing
    archive.main_entry = main_entry

    favicon = MagicMock()
    favicon.mimetype = "image/png"
    favicon.content = b"\x89PNG..."
    archive.get_illustration_item.return_value = favicon
    return archive


def test_browse_w_recovers_main_page_via_has_main_entry():
    """The synthetic ``W/mainPage`` row is materialised through
    ``archive.main_entry`` rather than ``has_entry_by_path``.

    Counter-test for D2: on the original a7 implementation, this
    archive's ``has_entry_by_path("W/mainPage")`` is False and the
    method returned an empty result. The a9 fix asks
    ``has_main_entry`` instead, matching what ``list_namespaces`` does.
    """
    mixin = _make_mixin()
    archive = _wikipedia_like_archive()

    result = mixin._browse_new_scheme_w_paginated(
        archive, namespace="W", limit=10, offset=0
    )
    paths = [row["path"] for row in result["entries"]]
    assert "W/mainPage" in paths, (
        f"D2: W/mainPage must appear when has_main_entry is True even "
        f"if has_entry_by_path('W/mainPage') returns False. Got: {paths}"
    )


def test_browse_w_recovers_favicon_via_has_illustration():
    """The synthetic ``W/favicon`` row is materialised through
    ``archive.has_illustration()`` rather than ``has_entry_by_path``."""
    mixin = _make_mixin()
    archive = _wikipedia_like_archive()

    result = mixin._browse_new_scheme_w_paginated(
        archive, namespace="W", limit=10, offset=0
    )
    paths = [row["path"] for row in result["entries"]]
    assert (
        "W/favicon" in paths
    ), "D2: W/favicon must appear when has_illustration() is True."


def test_browse_w_total_matches_list_namespaces_count():
    """The W-browse total must match the W count ``list_namespaces``
    would report for the same archive. Bridges the inconsistency
    surfaced in v2.0.0a8 live testing.
    """
    mixin = _make_mixin()
    archive = _wikipedia_like_archive()

    result = mixin._browse_new_scheme_w_paginated(
        archive, namespace="W", limit=10, offset=0
    )
    # has_main_entry + has_illustration = 2, mirroring
    # _add_new_scheme_well_known_namespace's count.
    assert result["total_in_namespace"] == 2


def test_browse_w_empty_when_archive_lacks_well_known_entries():
    """When the archive reports no main entry and no illustration,
    the W namespace genuinely is empty — no synthetic rows."""
    mixin = _make_mixin()
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.has_main_entry = False
    archive.has_illustration.return_value = False
    archive.has_entry_by_path.return_value = False

    result = mixin._browse_new_scheme_w_paginated(
        archive, namespace="W", limit=10, offset=0
    )
    assert result["total_in_namespace"] == 0
    assert result["entries"] == []


def test_browse_w_picks_up_auxiliary_paths_when_present():
    """Aux well-known paths (W/index, W/robots.txt, ...) still get
    the ``has_entry_by_path`` probe — they DO exist as literal entries
    on archive flavours that carry them."""
    mixin = _make_mixin()
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.has_main_entry = False
    archive.has_illustration.return_value = False
    # Only W/robots.txt is a literal entry.
    archive.has_entry_by_path.side_effect = lambda p: p == "W/robots.txt"
    aux_entry = MagicMock()
    aux_entry.path = "W/robots.txt"
    aux_entry.title = "robots.txt"
    aux_entry.is_redirect = False
    aux_entry.get_item.return_value.mimetype = "text/plain"
    aux_entry.get_item.return_value.content = b"User-agent: *"
    archive.get_entry_by_path.return_value = aux_entry

    result = mixin._browse_new_scheme_w_paginated(
        archive, namespace="W", limit=10, offset=0
    )
    paths = [row["path"] for row in result["entries"]]
    assert "W/robots.txt" in paths
