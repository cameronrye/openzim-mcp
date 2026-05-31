"""Characterization tests for ``find_entry_by_title_data``.

These pin the OUTPUT of ``find_entry_by_title_data`` across each of its
internal phases so the Tier 3.2 decomposition (extracting the post-loop
assembly + per-file row builders into helpers) can be proven
behavior-preserving. They drive the method through fully-mocked archives
(modeled on ``tests/test_find_entry_by_title_redirect_dedup.py``) so the
assertions are deterministic and don't depend on a real ZIM fixture being
present.

Phases exercised:
  (a) fast-path exact hit            -> score 1.0, match_type, fast_path_hit
  (b) suggestion-search result set   -> rank-decayed scores
  (c) typo-fallback hit              -> fuzzy_path_hit + alt_spelling suggestions
  (d) cross_file=True dedup          -> dedup by (zim_file, path)
  (e) zero hits                      -> reason="0_hits" + recovery suggestions
"""

from __future__ import annotations

from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


def _ctx(value: Any):
    """Minimal context manager wrapping ``value`` for ``zim_archive``."""

    class _C:
        def __enter__(self) -> Any:
            return value

        def __exit__(self, *a: Any) -> bool:
            return False

    return _C()


def _entry(path: str, title: str, *, is_redirect: bool = False, target: Any = None):
    """Build a MagicMock libzim Entry."""
    e = MagicMock()
    e.path = path
    e.title = title
    e.is_redirect = is_redirect
    if target is not None:
        e.get_redirect_entry.return_value = target
    return e


def _suggester(paths: List[str]):
    """Build a MagicMock SuggestionSearcher returning ``paths``."""
    sugg = MagicMock()
    sugg.getEstimatedMatches.return_value = len(paths)
    sugg.getResults.return_value = list(paths)
    searcher = MagicMock()
    searcher.suggest.return_value = sugg
    return searcher


def _make_server(test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
    """Build a server with a path validator stubbed to a fixed path."""
    server = OpenZimMcpServer(test_config)
    server.zim_operations.path_validator = MagicMock()
    server.zim_operations.path_validator.validate_path.return_value = "/zim/test.zim"
    server.zim_operations.path_validator.validate_zim_file.return_value = (
        "/zim/test.zim"
    )
    return server


def _patch_archive(
    monkeypatch,
    archive: Any,
    searcher: Optional[Any] = None,
) -> None:
    """Patch ``zim_archive`` (and optionally ``SuggestionSearcher``)."""
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive",
        lambda *a, **kw: _ctx(archive),
    )
    if searcher is not None:
        monkeypatch.setattr(
            "openzim_mcp.zim_operations.SuggestionSearcher",
            lambda _archive: searcher,
        )


# ---------------------------------------------------------------------------
# (a) Fast-path exact hit.
# ---------------------------------------------------------------------------


def test_fast_path_exact_hit(test_config: OpenZimMcpConfig, monkeypatch) -> None:
    """A direct path probe must score 1.0, set fast_path_hit, and stop."""
    server = _make_server(test_config)
    entry = _entry("C/Climate_change", "Climate change")

    archive = MagicMock()
    # ``_find_entry_fast_path`` hits on the native title probe first.
    archive.has_entry_by_title.return_value = True
    archive.get_entry_by_title.return_value = entry

    _patch_archive(monkeypatch, archive)

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "climate change", cross_file=False, limit=10
    )

    assert out["fast_path_hit"] is True
    assert out["fuzzy_path_hit"] is False
    assert out["total"] == 1
    assert out["done"] is True
    assert out["next_cursor"] is None
    assert out["files_searched"] == 1
    top = out["results"][0]
    assert top["path"] == "C/Climate_change"
    assert top["title"] == "Climate change"
    assert top["score"] == 1.0
    assert top["match_type"] == "direct"
    assert top["zim_file"] == "/zim/test.zim"
    assert top["pre_redirect_path"] == "C/Climate_change"
    # No suggestions surface on a confident non-fuzzy hit.
    assert out["_meta"].get("suggestions") is None
    assert out["_meta"].get("reason") is None


def test_fast_path_redirect_walk_sets_match_type(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """A fast-path hit that walks a redirect reports match_type=redirect."""
    server = _make_server(test_config)
    canonical = _entry("Big_Rapids,_Michigan", "Big Rapids, Michigan")
    redirect = _entry(
        "Big_Rapids_Michigan",
        "Big Rapids Michigan",
        is_redirect=True,
        target=canonical,
    )

    archive = MagicMock()
    archive.has_entry_by_title.return_value = True
    archive.get_entry_by_title.return_value = redirect

    _patch_archive(monkeypatch, archive)

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "Big Rapids Michigan", cross_file=False, limit=10
    )

    top = out["results"][0]
    assert top["path"] == "Big_Rapids,_Michigan"
    assert top["match_type"] == "redirect"
    assert top["pre_redirect_path"] == "Big_Rapids_Michigan"
    assert top["score"] == 1.0
    assert out["fast_path_hit"] is True


# ---------------------------------------------------------------------------
# (b) Suggestion-search result set (rank-decayed scores).
# ---------------------------------------------------------------------------


def test_suggestion_search_rank_decayed_scores(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """Suggestion rows carry linearly-decaying rank scores in (0, 0.95]."""
    server = _make_server(test_config)
    e0 = _entry("Climate", "Climate")
    e1 = _entry("Climatology", "Climatology")
    e2 = _entry("Climate_model", "Climate model")

    archive = MagicMock()
    # Fast path misses entirely (no exact title, no path variant).
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False

    def get_entry_by_path(path: str):
        return {"Climate": e0, "Climatology": e1, "Climate_model": e2}[path]

    archive.get_entry_by_path.side_effect = get_entry_by_path

    searcher = _suggester(["Climate", "Climatology", "Climate_model"])
    _patch_archive(monkeypatch, archive, searcher)

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "climat", cross_file=False, limit=10
    )

    scores = [r["score"] for r in out["results"]]
    # n=3 -> 0.95*(1-0/3), 0.95*(1-1/3), 0.95*(1-2/3) rounded to 4dp.
    assert scores == [0.95, 0.6333, 0.3167]
    # Rank-monotonic, non-increasing, all distinct from the legacy 0.8.
    assert all(a >= b for a, b in zip(scores, scores[1:]))
    assert all(s != 0.8 for s in scores)
    assert all(r["match_type"] == "fuzzy_suggest" for r in out["results"])
    assert out["fast_path_hit"] is False
    assert out["fuzzy_path_hit"] is False
    assert out["_meta"].get("reason") is None


def test_suggestion_exact_ci_match_promoted_to_1(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """An exact case-insensitive suggestion title is promoted to 1.0."""
    server = _make_server(test_config)
    # The user typed "evolution"; the canonical title is "Evolution".
    entry = _entry("Evolution", "Evolution")

    archive = MagicMock()
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False
    archive.get_entry_by_path.return_value = entry

    searcher = _suggester(["Evolution"])
    _patch_archive(monkeypatch, archive, searcher)

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "evolution", cross_file=False, limit=10
    )

    top = out["results"][0]
    assert top["score"] == 1.0
    assert top["match_type"] == "direct"
    # The exact-CI suggestion promotion also flips fast_path_hit.
    assert out["fast_path_hit"] is True


def test_suggestion_read_failure_skips_row(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """A suggestion whose entry read raises is skipped, not fatal."""
    server = _make_server(test_config)
    good = _entry("Climate", "Climate")

    archive = MagicMock()
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False

    def get_entry_by_path(path: str):
        if path == "Broken":
            raise RuntimeError("read failed")
        return good

    archive.get_entry_by_path.side_effect = get_entry_by_path

    searcher = _suggester(["Broken", "Climate"])
    _patch_archive(monkeypatch, archive, searcher)

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "climat", cross_file=False, limit=10
    )

    # Only the readable suggestion survives.
    paths = [r["path"] for r in out["results"]]
    assert paths == ["Climate"]


def test_suggestion_exception_cross_file_logged_not_raised(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """In cross_file mode, a suggester failure is logged and the file skipped."""
    server = _make_server(test_config)

    archive = MagicMock()
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False

    # SuggestionSearcher itself raises when constructed.
    def raising_searcher(_archive):
        raise RuntimeError("no title index")

    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive",
        lambda *a, **kw: _ctx(archive),
    )
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.SuggestionSearcher",
        raising_searcher,
    )
    monkeypatch.setattr(
        server.zim_operations,
        "list_zim_files_data",
        lambda *a, **kw: [{"path": "/zim/a.zim"}],
    )
    monkeypatch.setattr(
        server.zim_operations,
        "_find_entry_typo_fallback_with_suggestions",
        lambda archive, title, *, suggestion_limit: (None, []),
    )

    # Must not raise — cross_file mode swallows per-file suggester failures.
    out = server.zim_operations.find_entry_by_title_data(
        "/zim/a.zim", "climat", cross_file=True, limit=10
    )
    assert out["results"] == []
    assert out["_meta"]["reason"] == "0_hits"


def test_suggestion_exception_single_file_raises(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """In single-file mode, a suggester failure propagates."""
    server = _make_server(test_config)

    archive = MagicMock()
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False

    def raising_searcher(_archive):
        raise RuntimeError("no title index")

    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive",
        lambda *a, **kw: _ctx(archive),
    )
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.SuggestionSearcher",
        raising_searcher,
    )

    with pytest.raises(RuntimeError, match="no title index"):
        server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "climat", cross_file=False, limit=10
        )


def test_suggestion_redirect_branch_surfaces_match_type_redirect(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """A suggestion entry that walks a redirect surfaces match_type=redirect.

    Pins the OUTPUT of the redirect-walked suggestion branch (not just
    that it runs): the reported path is the canonical post-redirect path,
    ``pre_redirect_path`` is the original suggestion path, and the
    non-exact-CI score stays in the rank-decayed band.
    """
    server = _make_server(test_config)
    # The suggestion index emits the redirect path "Color"; it walks to
    # the canonical "Colour" whose title differs from the query, so the
    # row is a redirect-walked suggestion (NOT an exact-CI promotion).
    canonical = _entry("Colour", "Colour")
    redirect = _entry("Color", "Color", is_redirect=True, target=canonical)

    archive = MagicMock()
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False
    archive.get_entry_by_path.return_value = redirect

    searcher = _suggester(["Color"])
    _patch_archive(monkeypatch, archive, searcher)

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "colorr", cross_file=False, limit=10
    )

    top = out["results"][0]
    assert top["path"] == "Colour"
    assert top["match_type"] == "redirect"
    assert top["pre_redirect_path"] == "Color"
    # n=1, idx=0 -> 0.95*(1-0/1) rounded; redirect-walked, not exact-CI.
    assert top["score"] == 0.95
    assert out["fast_path_hit"] is False
    assert out["fuzzy_path_hit"] is False


# ---------------------------------------------------------------------------
# (b') Cross-file partial-row survival on a mid-loop raise.
#
# REGRESSION GUARD for the Tier 3 ``_suggestion_rows`` divergence: the
# extracted helper built a LOCAL rows list and only ``extend``-ed it onto
# ``aggregate_results`` after the whole loop completed, so a mid-loop raise
# (e.g. ``_follow_redirect_chain`` throwing on the SECOND path) discarded
# the already-built first row AND the inline ``fast_path_hit`` flip. The
# original inlined code appends to the shared list incrementally and sets
# ``fast_path_hit`` inline, so the partial first row survives the raise
# (caught by the cross_file suggestion ``except`` that logs + continues).
# ---------------------------------------------------------------------------


def test_cross_file_suggestion_partial_row_survives_midloop_raise(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """First suggestion row survives a raise while building the second.

    SuggestionSearcher returns two paths; ``get_entry_by_path`` succeeds
    for both, but ``_follow_redirect_chain`` raises on the SECOND call
    (after the first, exact-CI row was already appended). In cross_file
    mode the outer suggestion ``except`` logs + continues, so the first
    row MUST survive and ``fast_path_hit`` MUST stay True.
    """
    server = _make_server(test_config)
    # First suggestion is an exact case-insensitive title match -> score
    # 1.0 + fast_path_hit flip happen INLINE before the second iteration.
    good = _entry("C/Good", "Good")
    second = _entry("C/Second", "Second")

    archive = MagicMock()
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False

    def get_entry_by_path(path: str):
        return {"C/Good": good, "C/Second": second}[path]

    archive.get_entry_by_path.side_effect = get_entry_by_path

    searcher = _suggester(["C/Good", "C/Second"])
    _patch_archive(monkeypatch, archive, searcher)
    monkeypatch.setattr(
        server.zim_operations,
        "list_zim_files_data",
        lambda *a, **kw: [{"path": "/zim/test.zim"}],
    )

    # ``_follow_redirect_chain`` succeeds (identity) on the first entry,
    # raises on the second -- AFTER the first row was appended.
    real_chain = server.zim_operations._follow_redirect_chain

    def flaky_chain(entry):
        if entry is second:
            raise RuntimeError("redirect chain blew up mid-loop")
        return real_chain(entry)

    monkeypatch.setattr(server.zim_operations, "_follow_redirect_chain", flaky_chain)
    # Typo fallback won't run (fast_path_hit gates it), but stub it so the
    # test never reaches a real archive in any branch.
    monkeypatch.setattr(
        server.zim_operations,
        "_find_entry_typo_fallback_with_suggestions",
        lambda archive, title, *, suggestion_limit: (None, []),
    )

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "good", cross_file=True, limit=10
    )

    # The partial first row survives the mid-loop raise.
    paths = [r["path"] for r in out["results"]]
    assert paths == ["C/Good"]
    # The inline exact-CI promotion + fast_path_hit flip also survive.
    assert out["results"][0]["score"] == 1.0
    assert out["results"][0]["match_type"] == "direct"
    assert out["fast_path_hit"] is True


# ---------------------------------------------------------------------------
# (c) Typo-fallback hit (fuzzy_path_hit + alt_spelling suggestions).
# ---------------------------------------------------------------------------


def test_typo_fallback_hit(test_config: OpenZimMcpConfig, monkeypatch) -> None:
    """A typo-corrected hit sets fuzzy_path_hit and surfaces alt spellings."""
    server = _make_server(test_config)
    corrected = _entry("Einstein", "Einstein")

    archive = MagicMock()
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False

    # Suggestion search comes up empty so the typo fallback runs.
    searcher = _suggester([])
    _patch_archive(monkeypatch, archive, searcher)

    # Stub the typo probe directly: return a corrected entry + alt spellings.
    monkeypatch.setattr(
        server.zim_operations,
        "_find_entry_typo_fallback_with_suggestions",
        lambda archive, title, *, suggestion_limit: (
            corrected,
            ["Einstein", "Einsteinium"],
        ),
    )

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "Einstien", cross_file=False, limit=10
    )

    assert out["fuzzy_path_hit"] is True
    assert out["fast_path_hit"] is False
    top = out["results"][0]
    assert top["path"] == "Einstein"
    assert top["match_type"] == "typo_corrected"
    assert top["score"] == test_config.search.fuzzy_title_score_penalty
    # Alt-spelling suggestions surface even when a fuzzy hit is returned.
    suggestions = out["_meta"]["suggestions"]
    assert {"type": "alt_spelling", "value": "Einstein"} in suggestions
    assert {"type": "alt_spelling", "value": "Einsteinium"} in suggestions


# ---------------------------------------------------------------------------
# (d) cross_file=True dedup by (zim_file, path).
# ---------------------------------------------------------------------------


def test_cross_file_dedup_by_zim_file_and_path(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """Cross-file search dedupes per (zim_file, path); distinct files stay."""
    server = _make_server(test_config)

    entry_a = _entry("Biology", "Biology")
    entry_b = _entry("Biology", "Biology")

    archive_a = MagicMock()
    archive_a.has_entry_by_title.return_value = True
    archive_a.get_entry_by_title.return_value = entry_a

    archive_b = MagicMock()
    archive_b.has_entry_by_title.return_value = True
    archive_b.get_entry_by_title.return_value = entry_b

    archives = {"/zim/a.zim": archive_a, "/zim/b.zim": archive_b}

    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive",
        lambda path, *a, **kw: _ctx(archives[path]),
    )
    monkeypatch.setattr(
        server.zim_operations,
        "list_zim_files_data",
        lambda *a, **kw: [{"path": "/zim/a.zim"}, {"path": "/zim/b.zim"}],
    )

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/a.zim", "biology", cross_file=True, limit=10
    )

    assert out["files_searched"] == 2
    # Both archives have a "Biology" entry but at DIFFERENT zim_file keys,
    # so both rows survive dedup (dedup key is (zim_file, path)).
    keys = {(r["zim_file"], r["path"]) for r in out["results"]}
    assert keys == {("/zim/a.zim", "Biology"), ("/zim/b.zim", "Biology")}
    assert len(out["results"]) == 2


def test_cross_file_dedup_collapses_same_file_same_path(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """Two suggestions collapsing to the same (zim_file, path) yield one row."""
    server = _make_server(test_config)

    canonical = _entry("Biology", "Biology")
    redirect = _entry("Bilogy", "Bilogy", is_redirect=True, target=canonical)

    archive = MagicMock()
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False

    def get_entry_by_path(path: str):
        return {"Bilogy": redirect, "Biology": canonical}[path]

    archive.get_entry_by_path.side_effect = get_entry_by_path

    searcher = _suggester(["Bilogy", "Biology"])
    _patch_archive(monkeypatch, archive, searcher)

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "biology", cross_file=False, limit=10
    )

    paths = [r["path"] for r in out["results"]]
    assert paths.count("Biology") == 1


# ---------------------------------------------------------------------------
# (e) Zero hits -> reason="0_hits" + recovery suggestions.
# ---------------------------------------------------------------------------


def test_zero_hits_reason_and_suggestions(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """No results anywhere yields reason="0_hits" with recovery hints."""
    server = _make_server(test_config)

    archive = MagicMock()
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False

    searcher = _suggester([])
    _patch_archive(monkeypatch, archive, searcher)

    # Typo fallback finds no entry but surfaces verified alt spellings.
    monkeypatch.setattr(
        server.zim_operations,
        "_find_entry_typo_fallback_with_suggestions",
        lambda archive, title, *, suggestion_limit: (None, ["Quokka"]),
    )

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "Quokkaa", cross_file=False, limit=10
    )

    assert out["results"] == []
    assert out["total"] == 0
    assert out["fast_path_hit"] is False
    assert out["fuzzy_path_hit"] is False
    assert out["_meta"]["reason"] == "0_hits"
    assert out["_meta"]["suggestions"] == [{"type": "alt_spelling", "value": "Quokka"}]


def test_zero_hits_no_suggestions_when_pool_empty(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """Zero hits with no verified variants yields reason but no suggestions."""
    server = _make_server(test_config)

    archive = MagicMock()
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False

    searcher = _suggester([])
    _patch_archive(monkeypatch, archive, searcher)

    monkeypatch.setattr(
        server.zim_operations,
        "_find_entry_typo_fallback_with_suggestions",
        lambda archive, title, *, suggestion_limit: (None, []),
    )

    out = server.zim_operations.find_entry_by_title_data(
        "/zim/test.zim", "Zzzxqq", cross_file=False, limit=10
    )

    assert out["results"] == []
    assert out["_meta"]["reason"] == "0_hits"
    assert out["_meta"].get("suggestions") is None


# ---------------------------------------------------------------------------
# Validation guards (cheap to pin; protects the early-return contract).
# ---------------------------------------------------------------------------


def test_blank_title_raises(test_config: OpenZimMcpConfig) -> None:
    server = _make_server(test_config)
    from openzim_mcp.exceptions import OpenZimMcpValidationError

    with pytest.raises(OpenZimMcpValidationError):
        server.zim_operations.find_entry_by_title_data("/zim/test.zim", "   ")


def test_out_of_range_limit_raises(test_config: OpenZimMcpConfig) -> None:
    server = _make_server(test_config)
    from openzim_mcp.exceptions import OpenZimMcpValidationError

    with pytest.raises(OpenZimMcpValidationError):
        server.zim_operations.find_entry_by_title_data("/zim/test.zim", "x", limit=51)
