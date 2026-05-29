"""Regression tests for the post-v2.0.5 beta-test sweep.

Six follow-on defects surfaced by a live two-archive verification
sweep against v2.0.5 (``zim.owl-atlas.ts.net``,
``wikipedia_en_all_maxi_2026-02`` + ``superuser.com_en_all_2026-02``)
after PR #219 shipped. First three (D-K / D-L / D-M) caught on the
initial sweep; second pass against the now-clean compact-search path
surfaced D-N / D-O as sibling-of-D-L widenings on the other compact
no-results renderers; third pass surfaced D-P as a sibling-of-D-N
widening on the shared ``Article not found`` recovery envelopes.
All six are sibling widenings of pre-existing narrow fixes — same
"narrow-scope sibling" pattern as PR #219 itself
(``IntentParser`` lowercases all entry_paths via Rule 1, the post-a11
E1 title-index probe only fired on multi-word tails, and the simple-
tools no-results recovery diverged from the non-compact formatter).

* D-K — ``_handle_get_article`` single-token title-index probe gate.
  The post-a11 E1 probe at ``simple_tools.py:3667`` ran only when
  ``" " in entry_path and "/" not in entry_path``, so single-token
  tails like ``get article Biology`` (lowercased to ``biology`` by
  the parser's Rule 1) skipped the probe and fell through to the
  backend's direct path lookup, which failed for any article whose
  ZIM archive didn't ship a lowercase redirect. Sibling handlers
  (structure / summary / get_section / links) already probe
  unconditionally — drop the gate to restore parity.

* D-L — compact-mode ``search`` no-results recovery missed the
  cross-intent ``tell me about X`` escape hatch. The compact path
  at ``simple_tools.py:3769`` carried only backend-derived
  ``_meta.suggestions`` (Xapian typo machinery) into the footer.
  When the backend produced none — the typical case for a junk
  query — ``format_footer`` fell through to the terse one-liner
  ``> No results. Try a shorter or differently-spelled query.``
  with no pointer to the structured-topic-lookup path. The
  non-compact ``_format_search_text`` body emits a
  ``tell me about X`` bullet (``zim/search.py:779``) but the
  compact path bypasses that formatter. Fix injects a
  ``cross_intent_tell_me_about`` suggestion at the handler edge
  and teaches ``format_footer`` to render it as
  `` `tell me about X` `` — keeps the compact-mode
  footer-driven (no prose block) contract intact while restoring
  cross-intent parity.

* D-M — ``**No ZIM File Specified**`` envelope at
  ``simple_tools.py:933`` listed available files but didn't hint
  at the cross-intent escape routes (``search all files for X``,
  ``zim_file_path=`` arg, ``synthesize=True``). A caller hitting
  the ambiguous-archive gate had to guess which alternative to
  try. Add a "Try one of these to recover:" block matching the
  shape used elsewhere.

* D-N — ``render_find_by_title`` no-results body
  (``compact_renderers.py:172-177``) suggested only
  ``suggestions for X`` and ``search for X``. The
  ``tell me about X`` cross-intent path (fuzzy title-index + RAG
  fallback) is exactly what a missed `find article titled X`
  caller would benefit from next, and it was absent.

* D-O — ``render_search_all`` no-results body
  (``compact_renderers.py:404-407``) suggested ``suggestions for
  X``, broadening, and ``list_zim_files``. The ``tell me about
  X`` cross-intent path (synthesize-mode auto-opens every loaded
  archive) is the natural cross-archive structured-lookup escape
  hatch and was missing.

* D-P — shared ``Article not found`` recovery envelopes
  (``_render_not_found_recovery`` at ``simple_tools.py:3050``,
  ``_handle_related`` inline wrap at ``simple_tools.py:5431``,
  ``render_related`` outbound_error block at
  ``compact_renderers.py:258``) had three recovery options
  (``suggestions for X`` / ``find article titled X`` /
  ``search for X``) but skipped ``tell me about X``. That bullet
  adds RAG fallback on top of the pure title-index lookup —
  distinct signal from ``find article titled X`` — and it's the
  one recovery most likely to handle paraphrased queries.
"""

from unittest.mock import MagicMock, Mock

import pytest

from openzim_mcp import simple_tools as simple_tools_module
from openzim_mcp.simple_tools import SimpleToolsHandler

# ===========================================================================
# D-K — ``_handle_get_article`` single-token title-index probe gate widening
# ===========================================================================


class TestGetArticleSingleTokenRoutesThroughTitleIndexProbe:
    """Pre-fix, ``get article Biology`` (parser lowercases to
    ``entry_path="biology"``) skipped the title-index probe because
    the gate required ``" " in entry_path``. Backend direct-path
    lookup then failed for ``biology`` (no lowercase redirect in
    ``wikipedia_en_all_maxi_2026-02``), and the handler surfaced
    ``Article not found: biology`` to the caller — even though the
    title index resolves ``biology`` → ``Biology`` at score 1.00.

    Sibling handlers (structure / summary / get_section / links)
    already call ``_resolve_natural_language_path`` unconditionally;
    this fix drops the gate on ``_handle_get_article`` to restore
    parity.
    """

    @pytest.fixture
    def mock_zim_operations(self) -> Mock:
        mock = Mock()
        mock.list_zim_files.return_value = (
            '[{"path": "/test/file.zim", "name": "file.zim"}]'
        )

        # Backend lookup succeeds ONLY for the canonical
        # capitalized form. Lowercase lookups raise to mimic the
        # live wikipedia_en_all_maxi_2026-02 behavior where most
        # articles ship without a lowercase redirect.
        def get_entry(_path: str, entry_path: str, *_a, **_kw) -> str:
            if entry_path == "Biology":
                return "Article content"
            raise ValueError(f"Entry not found: '{entry_path}'")

        mock.get_zim_entry.side_effect = get_entry
        return mock

    @pytest.fixture
    def handler(self, mock_zim_operations: Mock) -> SimpleToolsHandler:
        return SimpleToolsHandler(mock_zim_operations)

    def test_single_token_unquoted_resolves_via_title_index(
        self,
        handler: SimpleToolsHandler,
        mock_zim_operations: Mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``get article Biology`` (lowercased to ``biology`` by the
        parser) must route through the title-index probe and reach
        the backend with the canonical ``Biology`` path. Pre-fix,
        the single-token tail skipped the probe and the backend
        lookup failed on the lowercased path."""

        def fake_find_title_match(_ops, _path, query: str, **_kw):
            if query.lower() == "biology":
                return {"path": "Biology", "title": "Biology", "score": 1.0}
            return None

        monkeypatch.setattr(
            simple_tools_module, "find_title_match", fake_find_title_match
        )

        result = handler.handle_zim_query("get article Biology", "/test/file.zim")
        assert "Article not found" not in result, (
            f"Single-token tail must route through the title-index "
            f"probe. Got: {result!r}"
        )
        # Confirm the resolved canonical path reached the backend.
        called_entry_paths = [
            call.args[1] for call in mock_zim_operations.get_zim_entry.call_args_list
        ]
        assert "Biology" in called_entry_paths, (
            f"Resolved canonical path 'Biology' must reach get_zim_entry. "
            f"Called paths: {called_entry_paths}"
        )

    def test_single_token_quoted_also_resolves_via_title_index(
        self,
        handler: SimpleToolsHandler,
        mock_zim_operations: Mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``get article "Biology"`` (also lowercased to
        ``biology`` post-strip) must reach the backend with the
        canonical capitalized path via the same probe."""

        def fake_find_title_match(_ops, _path, query: str, **_kw):
            if query.lower() == "biology":
                return {"path": "Biology", "title": "Biology", "score": 1.0}
            return None

        monkeypatch.setattr(
            simple_tools_module, "find_title_match", fake_find_title_match
        )

        result = handler.handle_zim_query('get article "Biology"', "/test/file.zim")
        assert "Article not found" not in result
        called_entry_paths = [
            call.args[1] for call in mock_zim_operations.get_zim_entry.call_args_list
        ]
        assert "Biology" in called_entry_paths

    def test_canonical_namespace_prefixed_path_unchanged_when_title_index_no_match(
        self,
        handler: SimpleToolsHandler,
        mock_zim_operations: Mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: ``get article A/Biology`` (a namespace-prefixed
        canonical path) reaches the backend unchanged when the title
        index has no fuzzy hit. The post-a11 E1 probe falls through to
        the literal entry_path on a miss, so namespace paths still
        route directly to ``get_zim_entry`` even after the gate is
        widened."""

        # Title-index returns None for namespace-shaped paths.
        monkeypatch.setattr(
            simple_tools_module,
            "find_title_match",
            lambda *_a, **_kw: None,
        )

        # Backend succeeds for the namespace-prefixed path (parser
        # lowercases everything, slash and all — Rule 1 is global).
        def get_entry(_path: str, entry_path: str, *_a, **_kw) -> str:
            if entry_path == "a/biology":
                return "Article content"
            raise ValueError(f"Entry not found: '{entry_path}'")

        mock_zim_operations.get_zim_entry.side_effect = get_entry

        result = handler.handle_zim_query("get article A/Biology", "/test/file.zim")
        assert "Article not found" not in result, (
            f"Canonical namespace path must still reach backend "
            f"unchanged. Got: {result!r}"
        )
        called_entry_paths = [
            call.args[1] for call in mock_zim_operations.get_zim_entry.call_args_list
        ]
        assert "a/biology" in called_entry_paths

    def test_multi_word_natural_language_path_still_resolves(
        self,
        handler: SimpleToolsHandler,
        mock_zim_operations: Mock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: the post-a11 E1 use case (multi-word free-form
        titles like ``get article World War II``) must continue to
        resolve via the title-index probe. The gate widening can't
        break multi-word coverage. (``World War II`` is picked
        instead of ``List of common misconceptions`` because the
        keyword extractor anchors on the LAST keyword — ``of`` —
        and would truncate the latter to ``common misconceptions``;
        ``World War II`` has no inner keyword so the full tail
        survives.)"""

        def fake_find_title_match(_ops, _path, query: str, **_kw):
            if "world war ii" in query.lower():
                return {
                    "path": "World_War_II",
                    "title": "World War II",
                    "score": 1.0,
                }
            return None

        monkeypatch.setattr(
            simple_tools_module, "find_title_match", fake_find_title_match
        )

        # Backend succeeds for the underscored canonical path.
        def get_entry(_path: str, entry_path: str, *_a, **_kw) -> str:
            if entry_path == "World_War_II":
                return "Article content"
            raise ValueError(f"Entry not found: '{entry_path}'")

        mock_zim_operations.get_zim_entry.side_effect = get_entry

        result = handler.handle_zim_query("get article World War II", "/test/file.zim")
        assert "Article not found" not in result
        called_entry_paths = [
            call.args[1] for call in mock_zim_operations.get_zim_entry.call_args_list
        ]
        assert "World_War_II" in called_entry_paths

    def test_empty_quoted_input_still_drops_to_missing_arg_guard(
        self,
        handler: SimpleToolsHandler,
        mock_zim_operations: Mock,
    ) -> None:
        """Regression guard for the post-v2.0.4 D-E sibling fix:
        the empty-quoted missing-arg envelope must fire BEFORE the
        title-index probe runs (so the probe never sees an empty
        input)."""

        result = handler.handle_zim_query('get article ""', "/test/file.zim")
        assert "Missing Article Path" in result
        mock_zim_operations.get_zim_entry.assert_not_called()


# ===========================================================================
# D-L — simple-tools compact ``search`` no-results body parity with
# ``_format_search_text`` (cross-intent ``tell me about`` bullet)
# ===========================================================================


class TestSearchNoResultsCompactFooterCrossIntentSuggestion:
    """Pre-fix, the compact-mode no-results path at
    ``simple_tools.py:3769`` returned only backend-derived suggestions
    (``alt_spelling`` / ``alt_archive`` from Xapian's typo machinery)
    in the footer. When the backend produced none — the typical case
    for a junk query like ``nonexistentxyzqwer123`` —
    ``format_footer`` fell through to the terse one-liner
    ``> No results. Try a shorter or differently-spelled query.``
    with no cross-intent pointer. Meanwhile the non-compact
    ``_format_search_text`` body (``zim/search.py:779``) emits a
    ``tell me about X`` cross-intent bullet that's the most useful
    escape hatch.

    Fix injects a ``cross_intent_tell_me_about`` suggestion at the
    simple-mode handler edge and teaches ``format_footer`` to render
    it as `` `tell me about X` ``. Compact callers now see the
    same escape route the non-compact body advertises, without
    violating the compact-mode "footer-driven, no prose block"
    contract pinned by ``test_compact_empty_search_uses_footer_not
    _legacy_prose``.
    """

    @pytest.fixture
    def mock_zim_operations(self) -> MagicMock:
        mock = MagicMock()
        mock.list_zim_files.return_value = (
            '[{"path": "/test/file.zim", "name": "file.zim"}]'
        )
        # Compact search returns a structured payload; we synthesize
        # a zero-total response that exercises the empty-result
        # branch at simple_tools.py:3737-3772.
        mock.search_zim_file_data.return_value = {
            "query": "nonexistentxyzqwer123",
            "total": 0,
            "page_info": {"offset": 0, "limit": 10},
            "results": [],
            "done": True,
            "next_cursor": None,
            "_meta": {"reason": "0_hits"},
        }
        # Footer ON so the suggestion bullets actually render.
        mock.config.meta.footer_enabled = True
        # Disable rerank so ``_maybe_rerank_compact`` is a no-op
        # (otherwise ``config.ml.reranker`` Mock chain trips an
        # arithmetic op inside the rerank load path).
        mock.config.ml.reranker.enabled = False
        return mock

    @pytest.fixture
    def handler(self, mock_zim_operations: MagicMock) -> SimpleToolsHandler:
        return SimpleToolsHandler(mock_zim_operations)

    def test_compact_no_results_footer_includes_tell_me_about_suggestion(
        self,
        handler: SimpleToolsHandler,
    ) -> None:
        """The compact no-results footer must include a
        `` `tell me about X` `` cross-intent suggestion so the
        caller has an explicit pointer to the structured-topic-
        lookup escape hatch."""
        result = handler.handle_zim_query(
            "search for nonexistentxyzqwer123",
            "/test/file.zim",
            options={"compact": True},
        )
        assert (
            "tell me about nonexistentxyzqwer123" in result
        ), f"Cross-intent `tell me about X` suggestion missing. Got:\n{result}"

    def test_compact_no_results_renders_structured_footer_not_terse_oneliner(
        self,
        handler: SimpleToolsHandler,
    ) -> None:
        """The footer must render the structured
        ``> No results. Try: ...`` form (bullets) instead of the
        terse one-liner ``> No results. Try a shorter or
        differently-spelled query.``. Pre-fix, with no
        backend-derived suggestions, the footer fell through to
        the terse form."""
        result = handler.handle_zim_query(
            "search for nonexistentxyzqwer123",
            "/test/file.zim",
            options={"compact": True},
        )
        # The structured form starts with "Try: " (note the colon);
        # the terse form is "Try a shorter ...". Assert on the
        # former and absence of the latter.
        assert (
            "> No results. Try:" in result
        ), f"Structured footer 'Try:' form expected. Got:\n{result}"
        assert (
            "differently-spelled" not in result
        ), f"Terse fallback should not fire when cross-intent suggestion is injected. Got:\n{result}"

    def test_compact_no_results_preserves_compact_mode_no_prose_block_contract(
        self,
        handler: SimpleToolsHandler,
    ) -> None:
        """Regression guard: the existing
        ``test_compact_empty_search_uses_footer_not_legacy_prose``
        contract pins that compact mode does NOT render the
        ``**Try one of these:**`` prose block. The D-L fix must
        respect this — it lives in the footer, not in the body."""
        result = handler.handle_zim_query(
            "search for nonexistentxyzqwer123",
            "/test/file.zim",
            options={"compact": True},
        )
        assert (
            "**Try one of these:**" not in result
        ), f"Compact mode must stay footer-only — no prose block. Got:\n{result}"

    def test_compact_no_results_preserves_backend_suggestions_first(
        self,
        handler: SimpleToolsHandler,
        mock_zim_operations: MagicMock,
    ) -> None:
        """Regression: when the backend supplied its own suggestions
        (e.g. ``alt_spelling`` from the typo machinery), the
        cross-intent suggestion must be APPENDED, not prepended —
        the typo recovery is a stronger signal than the generic
        cross-intent hint."""
        mock_zim_operations.search_zim_file_data.return_value = {
            "query": "photosynthsis",
            "total": 0,
            "page_info": {"offset": 0, "limit": 10},
            "results": [],
            "done": True,
            "next_cursor": None,
            "_meta": {
                "reason": "0_hits",
                "suggestions": [
                    {"type": "alt_spelling", "value": "photosynthesis"},
                ],
            },
        }
        result = handler.handle_zim_query(
            "search for photosynthsis",
            "/test/file.zim",
            options={"compact": True},
        )
        # Both should be present in the footer.
        assert "suggestions for photosynthesis" in result
        assert "tell me about photosynthsis" in result
        # alt_spelling appears first (stronger signal); cross-intent
        # follows.
        idx_alt = result.find("suggestions for photosynthesis")
        idx_xi = result.find("tell me about photosynthsis")
        assert idx_alt < idx_xi, (
            f"Backend alt_spelling suggestion must precede the appended "
            f"cross-intent suggestion. Got order: alt_spelling at {idx_alt}, "
            f"cross_intent at {idx_xi}.\nFull:\n{result}"
        )

    def test_compact_no_results_body_still_terse_echoes_display_query(
        self,
        handler: SimpleToolsHandler,
    ) -> None:
        """Regression: the body itself stays terse
        (``No results for "X".``) — the cross-intent hint lives in
        the footer, not the body."""
        result = handler.handle_zim_query(
            "search for nonexistentxyzqwer123",
            "/test/file.zim",
            options={"compact": True},
        )
        assert 'No results for "nonexistentxyzqwer123".' in result


# ===========================================================================
# D-L sibling — `render_find_by_title` no-results body cross-intent bullet.
# Same defect class as D-L (compact-mode search no-results), confirmed live
# on v2.0.5: `find article titled nonexistentxyzqwer123` suggests
# `suggestions for X` and `search for X` but NOT `tell me about X`
# (which is the natural next step — fuzzy title-index + RAG fallback).
# ===========================================================================


class TestFindByTitleNoResultsIncludesTellMeAboutBullet:
    """Pre-fix, ``render_find_by_title``'s no-results body
    (``compact_renderers.py:172-177``) suggested only
    ``suggestions for X`` and ``search for X``. The
    ``tell me about X`` cross-intent path — fuzzy title-index +
    RAG fallback — is the most natural next step for a caller who
    tried ``find article titled X`` and missed; add it to the
    recovery options."""

    def test_no_results_body_includes_tell_me_about_bullet(self) -> None:
        from openzim_mcp.compact_renderers import render_find_by_title

        out = render_find_by_title({"results": []}, "nonexistentxyzqwer123")
        assert (
            "tell me about nonexistentxyzqwer123" in out
        ), f"Cross-intent `tell me about X` recovery missing. Got:\n{out}"

    def test_no_results_body_still_includes_suggestions_and_search_recoveries(
        self,
    ) -> None:
        """Regression: the existing recovery options must stay."""
        from openzim_mcp.compact_renderers import render_find_by_title

        out = render_find_by_title({"results": []}, "nonexistentxyzqwer123")
        assert "suggestions for nonexistentxyzqwer123" in out
        assert "search for nonexistentxyzqwer123" in out

    def test_results_present_does_not_render_recovery_block(self) -> None:
        """Regression: when the title-index returns hits, the
        recovery block must not appear (results take priority)."""
        from openzim_mcp.compact_renderers import render_find_by_title

        out = render_find_by_title(
            {
                "results": [
                    {
                        "title": "Photosynthesis",
                        "path": "Photosynthesis",
                        "score": 1.0,
                    }
                ]
            },
            "photosynthesis",
        )
        assert "tell me about photosynthesis" not in out
        assert "No article found" not in out


# ===========================================================================
# D-L sibling — `render_search_all` no-results body cross-intent bullet.
# Same defect class, confirmed live: `search all files for X` →
# `No results in any archive. Try \`suggestions for X\`, broaden the terms,
# or check \`list_zim_files\`.` — missing the cross-intent path.
# ===========================================================================


class TestSearchAllNoResultsIncludesTellMeAboutBullet:
    """Pre-fix, ``render_search_all``'s no-results body
    (``compact_renderers.py:404-407``) suggested ``suggestions for X``,
    broadening, and ``list_zim_files`` — no cross-intent path. Add
    ``tell me about X`` (synthesize-mode auto-opens every loaded
    archive) since it's the natural cross-archive structured-lookup
    escape hatch.
    """

    def test_no_results_body_includes_tell_me_about_bullet(self) -> None:
        from openzim_mcp.compact_renderers import render_search_all

        out = render_search_all(
            {"results": [], "files_searched": 2, "files_failed": 0},
            "nonexistentxyzqwer123",
        )
        assert (
            "tell me about nonexistentxyzqwer123" in out
        ), f"Cross-intent `tell me about X` recovery missing. Got:\n{out}"

    def test_no_results_body_preserves_existing_recoveries(self) -> None:
        """Regression: existing suggestions remain — `suggestions
        for X` alt_spelling pointer and `list_zim_files` hint."""
        from openzim_mcp.compact_renderers import render_search_all

        out = render_search_all(
            {"results": [], "files_searched": 2, "files_failed": 0},
            "nonexistentxyzqwer123",
        )
        assert "suggestions for nonexistentxyzqwer123" in out
        assert "list_zim_files" in out

    def test_all_archives_failed_path_unchanged(self) -> None:
        """Regression: the all-archives-failed branch
        (``files_failed >= files_searched``) emits a structural
        error message — ``tell me about X`` is irrelevant when
        archives themselves are unreachable, so the cross-intent
        bullet must NOT appear in this branch."""
        from openzim_mcp.compact_renderers import render_search_all

        out = render_search_all(
            {"results": [], "files_searched": 2, "files_failed": 2},
            "anything",
        )
        # Structural error message should fire instead.
        assert "returned errors before search" in out
        # No cross-intent bullet here — the issue isn't the query.
        assert "tell me about anything" not in out


# ===========================================================================
# D-M — ``**No ZIM File Specified**`` envelope cross-intent guidance
# ===========================================================================


class TestNoZimFileSpecifiedEnvelopeIncludesCrossIntentHints:
    """Pre-fix, callers hitting the ambiguous-archive gate (multiple
    ZIMs loaded, no ``zim_file_path`` arg, query intent doesn't
    auto-select an archive) saw only "Please specify a ZIM file
    path, or ensure there is exactly one ZIM file available." with
    a raw file listing — no hint that ``search all files for X`` or
    ``synthesize=True`` would route across all archives without
    needing an explicit path.

    Fix adds a "Try one of these to recover:" block mirroring the
    shape used by ``_render_not_found_recovery`` and the missing-
    arg envelopes.
    """

    @pytest.fixture
    def mock_zim_operations(self) -> Mock:
        mock = Mock()
        # Simulate 2+ archives loaded so auto-select fails and the
        # gate fires.
        mock.list_zim_files.return_value = (
            "[\n"
            '  {"path": "/data/a.zim", "name": "a.zim"},\n'
            '  {"path": "/data/b.zim", "name": "b.zim"}\n'
            "]"
        )
        return mock

    @pytest.fixture
    def handler(self, mock_zim_operations: Mock) -> SimpleToolsHandler:
        # No zim_file_path passed; auto-select returns None on 2+
        # archives → gate fires.
        h = SimpleToolsHandler(mock_zim_operations)
        # Force the auto-select to return None to deterministically
        # trip the gate even if test discovery picks up other ZIMs.
        h._auto_select_zim_file = lambda: None  # type: ignore[method-assign]
        return h

    def _trip_gate(self, handler: SimpleToolsHandler) -> str:
        # ``search for X`` requires a zim_file_path when 2+ archives
        # are loaded; with auto-select forced to None, this trips
        # the no_zim_file_specified gate.
        return handler.handle_zim_query("search for photosynthesis")

    def test_envelope_includes_search_all_files_hint(
        self,
        handler: SimpleToolsHandler,
    ) -> None:
        """The envelope must point callers at ``search all files for
        X`` as the cross-archive escape route."""
        result = self._trip_gate(handler)
        assert "No ZIM File Specified" in result
        assert "search all files" in result, (
            f"Envelope must hint at `search all files for X` for "
            f"cross-archive routing. Got:\n{result}"
        )

    def test_envelope_includes_zim_file_path_hint(
        self,
        handler: SimpleToolsHandler,
    ) -> None:
        """The envelope must point callers at the ``zim_file_path``
        argument as the explicit-target escape route."""
        result = self._trip_gate(handler)
        assert "zim_file_path" in result, (
            f"Envelope must hint at the `zim_file_path` argument. " f"Got:\n{result}"
        )

    def test_envelope_still_lists_available_files(
        self,
        handler: SimpleToolsHandler,
    ) -> None:
        """Regression: the envelope still embeds the available-files
        listing so the caller can see which archives are loaded."""
        result = self._trip_gate(handler)
        assert "Available files" in result
        assert "/data/a.zim" in result
        assert "/data/b.zim" in result

    def test_envelope_preserves_no_zim_file_specified_intent_footer(
        self,
        handler: SimpleToolsHandler,
    ) -> None:
        """Regression: the ``intent=no_zim_file_specified cert=1.00``
        telemetry footer must stay (parser/dispatcher rely on this
        signal for telemetry counters)."""
        result = self._trip_gate(handler)
        assert "intent=no_zim_file_specified" in result
        assert "cert=1.00" in result


# ===========================================================================
# D-P — ``Article not found`` recovery envelopes missing the ``tell me about
# X`` cross-intent path. Three sites share the same shape:
#
#   1. ``_render_not_found_recovery`` (``simple_tools.py:3050``) — fires on
#      ``_handle_get_article`` / ``_handle_structure`` / ``_handle_summary``
#      / ``_handle_links`` / ``_handle_get_section`` not-found.
#   2. ``_handle_related`` inline wrap (``simple_tools.py:5431``) — fires
#      when the related-articles backend raises ``Cannot find entry``.
#   3. ``render_related`` outbound_error block
#      (``compact_renderers.py:258``) — fires when the compact-mode
#      related-articles call returns a serialised ``outbound_error``.
#
# All three already include ``suggestions for X`` + ``find article titled
# X`` + ``search for X``. Add ``tell me about X`` as a fourth option —
# fuzzy title-index + RAG fallback gives a different signal than the
# pure title-index ``find article titled X`` recovery (title-lookup +
# auto-RAG when no exact title hits). Same defect-class widening as D-N
# (which added ``tell me about`` to ``render_find_by_title`` no-results).
# ===========================================================================


class TestNotFoundRecoveryIncludesTellMeAboutBullet:
    """Pre-fix, the three shared not-found envelopes (one library
    helper, two inline wraps) suggested three recoveries but skipped
    ``tell me about X`` — even though that's the most powerful
    single-step recovery (title-index fuzzy + auto-RAG)."""

    def test_render_not_found_recovery_includes_tell_me_about(
        self,
    ) -> None:
        """``SimpleToolsHandler._render_not_found_recovery`` is the
        shared library helper for get_article / structure / summary /
        links / get_section not-found responses. Add `tell me about
        X` as the fourth recovery bullet."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        handler = SimpleToolsHandler(MagicMock())
        out = handler._render_not_found_recovery(
            "Photosynthsis", ValueError("Entry not found"), "get article"
        )
        assert (
            "tell me about Photosynthsis" in out
        ), f"Cross-intent `tell me about X` recovery missing. Got:\n{out}"

    def test_render_not_found_recovery_preserves_existing_recoveries(
        self,
    ) -> None:
        """Regression: the existing 3 recoveries
        (``suggestions for`` / ``find article titled`` / ``search
        for``) must stay."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        handler = SimpleToolsHandler(MagicMock())
        out = handler._render_not_found_recovery(
            "Photosynthsis", ValueError("Entry not found"), "get article"
        )
        assert "suggestions for Photosynthsis" in out
        assert "find article titled Photosynthsis" in out
        assert "search for Photosynthsis" in out

    def test_render_not_found_recovery_preserves_envelope_header(
        self,
    ) -> None:
        """Regression: the ``**Article not found: `X`**`` header and
        the ``op_label`` echo must stay so callers can identify
        which operation failed and on what path."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        handler = SimpleToolsHandler(MagicMock())
        out = handler._render_not_found_recovery(
            "Photosynthsis", ValueError("Entry not found"), "structure of"
        )
        assert "**Article not found: `Photosynthsis`**" in out
        assert "structure of Photosynthsis" in out

    def test_related_inline_not_found_wrap_includes_tell_me_about(
        self,
    ) -> None:
        """``_handle_related``'s inline error wrap at
        ``simple_tools.py:5431`` fires when ``get_related_articles``
        raises ``Cannot find entry``. Same recovery shape as
        ``_render_not_found_recovery`` — must include the cross-
        intent bullet."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files.return_value = '[{"path": "/x.zim"}]'
        mock.config.meta.footer_enabled = False
        # Force the related-articles backend to raise so the inline
        # not-found wrap fires.
        mock.get_related_articles.side_effect = ValueError(
            "Cannot find entry NotARealArticle"
        )
        mock.get_related_articles_data.side_effect = ValueError(
            "Cannot find entry NotARealArticle"
        )
        # Bypass the title-index promotion so the wrap actually fires.
        import pytest as _pytest

        from openzim_mcp import simple_tools as simple_tools_module

        monkeypatch = _pytest.MonkeyPatch()
        monkeypatch.setattr(
            simple_tools_module, "find_title_match", lambda *_a, **_kw: None
        )
        try:
            handler = SimpleToolsHandler(mock)
            out = handler.handle_zim_query(
                "articles related to NotARealArticle", "/x.zim"
            )
        finally:
            monkeypatch.undo()
        # The parser lowercases entry_path (Rule 1) so the recovery
        # bullets echo the lowercased form.
        assert "tell me about notarealarticle" in out, (
            f"Cross-intent recovery missing in related-not-found " f"wrap. Got:\n{out}"
        )
        # Regression guard: existing 3 recoveries still present.
        assert "suggestions for notarealarticle" in out
        assert "find article titled notarealarticle" in out

    def test_render_related_outbound_error_includes_tell_me_about(
        self,
    ) -> None:
        """``render_related``'s ``outbound_error`` recovery block
        (``compact_renderers.py:258``) — same shape as
        ``_render_not_found_recovery`` but on the compact-mode
        renderer surface. Must include the cross-intent bullet."""
        from openzim_mcp.compact_renderers import render_related

        out = render_related(
            {"outbound_error": "Cannot find entry NotARealArticle"},
            "NotARealArticle",
        )
        assert (
            "tell me about NotARealArticle" in out
        ), f"Cross-intent recovery missing in outbound_error. Got:\n{out}"
        # Regression guard: existing recoveries still present.
        assert "suggestions for NotARealArticle" in out
        assert "find article titled NotARealArticle" in out
        assert "search for NotARealArticle" in out
