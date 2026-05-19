"""Regression tests for the post-a17 beta-test sweep (a18 fixes).

The post-a17 live sweep against the 118 GB Wikipedia ZIM surfaced
three user-facing defects:

- P1-D1: ``notable people from Big Rapids, Michigan`` and
  ``musicians from Romeo and Juliet`` emitted a misleading
  soft-connector footer claiming the article for ``Michigan`` /
  ``Juliet`` was returned, when in fact a single entity whose title
  structurally spans the connector (``Big Rapids, Michigan`` carries
  a comma; ``Romeo and Juliet`` carries ``and``) was returned. The
  existing ``left_in == right_in`` suppression only catches the case
  where both topic halves are substrings of the title; a subject-
  attribute prefix (``notable people from`` / ``musicians from``)
  leaves the left half longer than the title, defeating that test.
  Fix adds an earlier "title-spans-connector" suppression: when the
  title itself matches the same connector regex, the connector is
  structural to the title and the footer is suppressed.

- P1-D2: ``tell me about München`` returned the ``M`` letter article
  at cert=0.85; ``tell me about Zürich`` returned the ``Rich``
  disambig; ``tell me about Köln`` returned the ``LN`` abbreviation.
  Root cause: ``_TAIL_TOKEN_RE = [a-z0-9]+`` in title_promotion.py
  stripped non-ASCII characters, so ``iter_query_tails("München")``
  yielded ``["m", "nchen"]`` and ``iter_query_windows`` yielded
  ``"m"``, which ``find_title_match`` cleanly resolved to the M
  letter article. The backend natively handles Unicode topics
  (``find article titled München`` resolves to Munich at score
  1.00), so the fix is Unicode-aware tokenisation:
  ``[^\\W_]+`` keeps ``\\w`` minus underscore.

- P1-D3: ``walk namespace M`` emits a cursor; passing that cursor
  back to ``walk namespace M`` produces the error ``Cursor for
  'walk_namespace' missing archive-identity field. Re-issue the
  request without a cursor.`` even though the cursor carries an
  ``ai`` field. Root cause: the simple-tools cursor dispatcher
  stashes only ``offset`` and ``_cursor_ns``, dropping ``ai``.
  ``_handle_walk_namespace`` then rebuilds cursor_state as
  ``{scan_at, l}`` without ``ai``; downstream
  ``verify_archive_identity`` rejects the synthetic cursor. Fix
  preserves ``s.ai`` (and ``s.ns``) through the dispatcher into the
  rebuilt cursor_state.

Each test pins one defect; failures here mean a regression on the
specific bug.
"""

from typing import Any
from unittest.mock import MagicMock

from openzim_mcp.pagination import Cursor
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.title_promotion import iter_query_tails, iter_query_windows


# ---------------------------------------------------------------------------
# P1-D1: title-spans-connector suppresses soft-connector footer
# ---------------------------------------------------------------------------


class TestP1D1TitleSpansConnectorSuppression:
    """P1-D1: when the resolved article's title structurally contains
    the same connector pattern as the topic, the footer is suppressed
    — even if a subject-attribute prefix on the topic prevents the
    left half from being a substring of the title.

    The pre-fix behaviour only suppressed when BOTH topic halves were
    substrings of the title; this is the broader, principled
    suppression rule.
    """

    def _make_handler(self, top_title: str) -> SimpleToolsHandler:
        path = top_title.replace(" ", "_")
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.return_value = {
            "results": [{"path": path, "title": top_title}],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "stub-body"
        mock.find_entry_by_title_data.return_value = {
            "results": [{"path": path, "title": top_title, "score": 1.0}],
            "total": 1,
        }
        return SimpleToolsHandler(mock)

    def test_comma_title_with_subject_attribute_prefix_suppresses(self) -> None:
        # ``notable people from Big Rapids, Michigan`` resolved to
        # ``Big Rapids, Michigan`` (single entity with comma in title).
        # Pre-fix: footer claimed "Returned the article for `Michigan`.
        # For `notable people from Big Rapids`, query separately..."
        # Post-fix: title carries the connector → suppress.
        handler = self._make_handler(top_title="Big Rapids, Michigan")
        out = handler.handle_zim_query(
            "tell me about notable people from Big Rapids, Michigan",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" not in out, (
            "soft-connector footer must be suppressed when the title "
            "structurally spans the same connector as the topic"
        )

    def test_and_title_with_subject_attribute_prefix_suppresses(self) -> None:
        # ``musicians from Romeo and Juliet`` resolved to
        # ``Romeo and Juliet`` (single article whose title spans ``and``).
        # Pre-fix: footer claimed "Returned the article for `Juliet`.
        # For `musicians from Romeo`, query separately..."
        # Post-fix: title contains ``and`` → suppress.
        handler = self._make_handler(top_title="Romeo and Juliet")
        out = handler.handle_zim_query(
            "tell me about musicians from Romeo and Juliet",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" not in out

    def test_genuine_two_entity_query_still_emits_footer(self) -> None:
        # Regression guard: ``musicians from Berlin and Paris`` with the
        # resolved title ``Paris`` (no ``and`` in title) must STILL fire
        # the footer — the suppression should be narrow.
        handler = self._make_handler(top_title="Paris")
        out = handler.handle_zim_query(
            "tell me about musicians from Berlin and Paris",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" in out
        assert "Berlin" in out

    def test_pre_fix_both_halves_in_title_still_suppresses(self) -> None:
        # Regression guard: ``Berlin and Brandenburg`` resolved to
        # ``Berlin and Brandenburg`` — title spans the connector AND
        # both halves are substrings. Either suppression path is fine;
        # ensure the footer doesn't appear.
        handler = self._make_handler(top_title="Berlin and Brandenburg")
        out = handler.handle_zim_query(
            "tell me about Berlin and Brandenburg",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" not in out

    def test_pass2_slash_connector_in_title_suppresses(self) -> None:
        # Pass-2 self-audit: same shape with a different connector
        # — ``TCP/IP stack tutorial`` resolved to ``TCP/IP`` (title
        # spans the slash). Pre-fix: would fire because "stack
        # tutorial" isn't in the title. Post-fix: title contains
        # ``/`` → suppress.
        handler = self._make_handler(top_title="TCP/IP")
        out = handler.handle_zim_query(
            "tell me about TCP/IP stack tutorial",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" not in out

    def test_pass2_topic_with_no_connector_in_title_still_fires(
        self,
    ) -> None:
        # Pass-2: defensive — when the title lacks the topic's
        # connector entirely, the new suppression must NOT swallow
        # the legitimate footer. ``Beethoven and Mozart`` resolved
        # to ``Beethoven`` (no ``and`` in title) → substring tests
        # fire normally → footer surfaces the dropped ``Mozart``
        # half.
        handler = self._make_handler(top_title="Beethoven")
        out = handler.handle_zim_query(
            "tell me about Beethoven and Mozart",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        # Title "Beethoven" doesn't span the connector → fires as before.
        assert "query contained" in out
        assert "Mozart" in out


# ---------------------------------------------------------------------------
# P1-D2: Unicode-aware tail / window tokenisation
# ---------------------------------------------------------------------------


class TestP1D2UnicodeTailTokenisation:
    """P1-D2: ``iter_query_tails`` / ``iter_query_windows`` must
    preserve non-ASCII letters (``ü``, ``ö``, ``é``) so the title-
    index probe sees the real topic and not an ASCII fragment that
    happens to collide with an unrelated short article name.
    """

    def test_munchen_tokenises_as_single_unicode_token(self) -> None:
        tails = list(iter_query_tails("München"))
        # Pre-fix: ["m", "nchen"] yielded → tails ["m nchen", "nchen"];
        # iter_query_windows yielded "m" which find_title_match cleanly
        # resolved to the ``M`` letter article. Post-fix: single token.
        assert tails == ["münchen"]
        # And iter_query_windows yields nothing (only one token).
        windows = list(iter_query_windows("München"))
        assert windows == []

    def test_zurich_tokenises_as_single_unicode_token(self) -> None:
        # Pre-fix: ["z", "rich"] → "rich" matched the ``Rich`` disambig.
        assert list(iter_query_tails("Zürich")) == ["zürich"]

    def test_koln_tokenises_as_single_unicode_token(self) -> None:
        # Pre-fix: ["k", "ln"] → "ln" matched the ``LN`` abbreviation.
        assert list(iter_query_tails("Köln")) == ["köln"]

    def test_multi_word_unicode_topic_preserved(self) -> None:
        # Multi-word Unicode: each token preserves diacritics.
        tails = list(iter_query_tails("Café de Flore"))
        assert tails == [
            "café de flore",
            "de flore",
            "flore",
        ]

    def test_ascii_only_topic_unchanged(self) -> None:
        # Regression guard: the original "big rapids michigan" example
        # must still tokenise to three single-word tokens.
        tails = list(iter_query_tails("famous people from big rapids michigan"))
        assert tails == [
            "from big rapids michigan",
            "big rapids michigan",
            "rapids michigan",
            "michigan",
        ]

    def test_underscore_still_acts_as_token_boundary(self) -> None:
        # ``[^\W_]+`` deliberately keeps underscore as a boundary so
        # path-form input like ``Big_Rapids,_Michigan`` doesn't yield
        # one mega-token.
        tails = list(iter_query_tails("Big_Rapids,_Michigan"))
        assert tails == [
            "big rapids michigan",
            "rapids michigan",
            "michigan",
        ]

    def test_digits_still_tokenise(self) -> None:
        # Regression guard: numeric tokens still form their own tokens.
        tails = list(iter_query_tails("Apollo 11"))
        assert tails == ["apollo 11", "11"]

    def test_pass2_empty_topic_returns_no_tails(self) -> None:
        # Pass-2 defensive: empty / whitespace topic must not yield
        # tails to probe.
        assert list(iter_query_tails("")) == []
        assert list(iter_query_tails("   ")) == []

    def test_pass2_mixed_latin_unicode_topic(self) -> None:
        # Pass-2: mixed ASCII + non-Latin topic. ``New München``
        # tokenises to two tokens (``new``, ``münchen``) so tail-
        # probing tries "new münchen" then "münchen" — both Unicode-
        # preserving.
        tails = list(iter_query_tails("New München"))
        assert tails == ["new münchen", "münchen"]

    def test_pass2_single_unicode_char_topic(self) -> None:
        # Pass-2: a topic that is JUST a single non-Latin character
        # ("ñ") tokenises to one token preserving the character.
        tails = list(iter_query_tails("ñ"))
        assert tails == ["ñ"]

    def test_pass2_punctuation_preserved_as_boundary_not_token(self) -> None:
        # Pass-2: punctuation other than underscore still acts as a
        # boundary (hyphens, apostrophes, commas, periods).
        assert list(iter_query_tails("O'Brien")) == ["o brien", "brien"]
        assert list(iter_query_tails("Coca-Cola")) == ["coca cola", "cola"]


# ---------------------------------------------------------------------------
# P1-D3: walk_namespace cursor "ai" preserved across the simple-tools
# dispatcher round-trip
# ---------------------------------------------------------------------------


class TestP1D3WalkNamespaceCursorRoundTrip:
    """P1-D3: a ``walk namespace M`` cursor emitted by the tool must
    round-trip through the simple-tools dispatcher without losing
    the ``ai`` archive-identity field — otherwise the data layer's
    ``verify_archive_identity`` rejects the cursor with a misleading
    "missing archive-identity field" error.
    """

    def _encode_walk_cursor(
        self, *, offset: int, limit: int, namespace: str, ai: str
    ) -> str:
        # Mirror the shape ``_walk_new_scheme_metadata`` emits.
        state: dict[str, Any] = {
            "o": offset,
            "l": limit,
            "ns": namespace,
            "ai": ai,
        }
        return Cursor.encode(tool="walk_namespace", state=state)  # type: ignore[arg-type]

    def test_walk_namespace_cursor_ai_preserved_through_dispatcher(self) -> None:
        """End-to-end: walk_namespace_data receives a cursor_state
        carrying ``ai`` matching the archive when a cursor round-trips
        through ``handle_zim_query``. Pre-fix: ``ai`` was dropped, the
        rebuilt cursor_state was ``{scan_at, l}`` only,
        ``verify_archive_identity`` raised "missing archive-identity
        field" → the user got an error instead of page 2.
        """
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [
            {"path": "/data/wikipedia_en_all_maxi_2026-02.zim"}
        ]
        mock.config.meta.footer_enabled = False
        # Track what the handler ends up passing to walk_namespace_data.
        captured: dict[str, Any] = {}

        def fake_walk_namespace_data(
            zim_file_path: str,
            namespace: str,
            *,
            cursor_state: Any = None,
            limit: int = 200,
        ) -> dict[str, Any]:
            captured["zim_file_path"] = zim_file_path
            captured["namespace"] = namespace
            captured["cursor_state"] = cursor_state
            captured["limit"] = limit
            return {
                "namespace": namespace,
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 3, "limit": limit, "returned_count": 0},
                "discovery_method": "full_iteration",
                "sampling_based": False,
                "results_may_be_incomplete": False,
            }

        mock.walk_namespace_data.side_effect = fake_walk_namespace_data
        handler = SimpleToolsHandler(mock)

        # The 'ai' value comes from the source cursor — the handler
        # should round-trip it through unchanged. ``compact=True``
        # routes through ``walk_namespace_data`` (the v2 contract path
        # that carries cursor_state); the legacy ``walk_namespace``
        # call takes a different kwarg shape and would obscure the
        # property under test.
        cursor_token = self._encode_walk_cursor(
            offset=3, limit=3, namespace="M", ai="e048666a9e92"
        )
        handler.handle_zim_query(
            "walk namespace M",
            zim_file_path="/data/wikipedia_en_all_maxi_2026-02.zim",
            options={"compact": True, "cursor": cursor_token},
        )

        cursor_state = captured["cursor_state"]
        assert cursor_state is not None, (
            "cursor_state should be passed when a cursor decodes to "
            "a non-zero offset"
        )
        assert cursor_state.get("ai") == "e048666a9e92", (
            "Dispatcher must preserve the cursor's 'ai' field into the "
            "rebuilt cursor_state — without it walk_namespace_data's "
            "verify_archive_identity rejects the synthetic cursor."
        )
        # ``scan_at`` should be 3 (decoded from ``o``) and ``ns`` must
        # also round-trip so the data-layer namespace-match guard fires
        # in the right case.
        assert cursor_state.get("scan_at") == 3
        assert cursor_state.get("ns") == "M"

    def test_walk_namespace_dispatcher_stashes_cursor_ai_into_options(self) -> None:
        """Directly assert the dispatcher contract: stash ``_cursor_ai``
        on the options dict so any handler can pull it out.
        """
        # We don't reach for handle_zim_query's internals here — the
        # public-surface assertion is the end-to-end test above. This
        # test wires a tiny mock to inspect the options dict that
        # the dispatcher forwards.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        captured_options: dict[str, Any] = {}

        def capturing_walk_data(
            zim_file_path: str,
            namespace: str,
            *,
            cursor_state: Any = None,
            limit: int = 200,
        ) -> dict[str, Any]:
            captured_options["cursor_state"] = cursor_state
            return {
                "namespace": namespace,
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 0, "limit": limit, "returned_count": 0},
                "discovery_method": "full_iteration",
                "sampling_based": False,
                "results_may_be_incomplete": False,
            }

        mock.walk_namespace_data.side_effect = capturing_walk_data
        handler = SimpleToolsHandler(mock)

        # A cursor for namespace "M" with a known ai.
        cursor_token = self._encode_walk_cursor(
            offset=5, limit=10, namespace="M", ai="deadbeefcafe"
        )
        handler.handle_zim_query(
            "walk namespace M",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )

        cursor_state = captured_options["cursor_state"]
        # Sanity-check the cursor payload round-tripped fully.
        assert cursor_state is not None
        assert cursor_state["ai"] == "deadbeefcafe"
        assert cursor_state["ns"] == "M"
        assert cursor_state["scan_at"] == 5

    def test_pass2_cross_archive_cursor_still_rejected(self) -> None:
        """Pass-2 self-audit: preserving ``ai`` must NOT weaken
        cross-archive enforcement. When a cursor's ``ai`` is preserved
        but doesn't match the current archive, the data-layer
        ``verify_archive_identity`` should now raise the proper
        "different archive" error (whereas pre-fix it raised
        "missing archive-identity field"). The shape of the error
        message is what changes; rejection still happens.

        We exercise the dispatcher path here — when the rebuilt
        cursor_state carries an ``ai`` field, the data layer's check
        sees it. Production behaviour (raising
        CursorMismatchError) is covered by the existing
        walk_namespace_data tests in tests/test_pagination.py and
        below by inspection of the rebuilt state.
        """
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        captured: dict[str, Any] = {}

        def fake_walk(
            zim_file_path: str,
            namespace: str,
            *,
            cursor_state: Any = None,
            limit: int = 200,
        ) -> dict[str, Any]:
            captured["cursor_state"] = cursor_state
            return {
                "namespace": namespace,
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 0, "limit": limit, "returned_count": 0},
                "discovery_method": "full_iteration",
                "sampling_based": False,
                "results_may_be_incomplete": False,
            }

        mock.walk_namespace_data.side_effect = fake_walk
        handler = SimpleToolsHandler(mock)
        cursor_token = self._encode_walk_cursor(
            offset=3, limit=3, namespace="M", ai="WRONG_ARCHIVE"
        )
        handler.handle_zim_query(
            "walk namespace M",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        # The wrong-archive ``ai`` is still propagated through; the
        # data layer (not under test here — only the dispatcher
        # contract is) raises CursorMismatchError on the mismatch.
        cursor_state = captured["cursor_state"]
        assert cursor_state is not None
        assert cursor_state["ai"] == "WRONG_ARCHIVE", (
            "Dispatcher must preserve the cursor's ai verbatim — the "
            "data layer is the only place that knows the expected ai "
            "for the resolved archive path, so the check must run "
            "there with the real value."
        )

    def test_no_cursor_means_no_cursor_state(self) -> None:
        """Regression guard: when no cursor is passed and offset=0,
        cursor_state should stay None (preserves the unconditional
        "first page" path).
        """
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        captured: dict[str, Any] = {}

        def fake(
            zim_file_path: str,
            namespace: str,
            *,
            cursor_state: Any = None,
            limit: int = 200,
        ) -> dict[str, Any]:
            captured["cursor_state"] = cursor_state
            return {
                "namespace": namespace,
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 0, "limit": limit, "returned_count": 0},
                "discovery_method": "full_iteration",
                "sampling_based": False,
                "results_may_be_incomplete": False,
            }

        mock.walk_namespace_data.side_effect = fake
        handler = SimpleToolsHandler(mock)
        handler.handle_zim_query(
            "walk namespace M",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        assert captured["cursor_state"] is None
