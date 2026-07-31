"""Regression tests for the query-understanding layer bug sweep.

Covers three confirmed defects in ``intent_parser`` / ``simple_tools``:

* the B4 "Search Terms Required" guard derived its tail from the ORIGINAL
  query while ``_extract_search`` saw the param-leak-stripped one, so
  ``search for query=biology`` searched the literal stop word ``for``;
* ``namespace`` is in ``_PARAM_LEAK_RE`` but is the OPERAND of browse /
  walk queries rather than a duplicate of a typed kwarg, so
  ``browse namespace=A`` was destroyed by the strip;
* a title-internal elision (``Rock 'n' Roll``) sits at exactly the M8
  quoted-value token boundaries, so ``get article Rock 'n' Roll`` returned
  the article for the letter ``N``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler


def _handler_single_archive() -> tuple[SimpleToolsHandler, MagicMock]:
    mock = MagicMock()
    mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
    return SimpleToolsHandler(mock), mock


# ===========================================================================
# B4 guard vs. the param-leak strip
# ===========================================================================


class TestSearchTermsRequiredAfterParamLeakStrip:
    """``search for query=biology`` stripped to ``search for``, leaving no
    terms — but the guard split its tail from the un-stripped query, saw
    ``query=biology`` (non-empty), stayed silent, and ``_extract_search``
    captured the verb-connector ``for`` as the search term.

    Any of the 14 ``_PARAM_LEAK_RE`` names triggers it, not just ``query=``.
    """

    @pytest.mark.parametrize(
        "query",
        [
            "search for query=biology",
            "search for limit=10",
            "search for offset=20",
            "search for compact_budget=2000",
            "search for limit=10 offset=20",
        ],
    )
    def test_leak_only_search_fires_terms_required(self, query: str) -> None:
        handler, mock = _handler_single_archive()
        result = handler.handle_zim_query(query=query, zim_file_path="/x.zim")
        assert "Search Terms Required" in str(result), (
            f"Expected the B4 guard to fire for {query!r}, got: " f"{str(result)[:300]}"
        )
        mock.search_zim_file_data.assert_not_called()
        mock.search_zim_file.assert_not_called()

    def test_real_terms_plus_leak_still_search(self) -> None:
        """The guard must not fire when real terms survive the strip."""
        handler, _mock = _handler_single_archive()
        _intent, params, _ = IntentParser.parse_intent("search for biology limit=10")
        assert params.get("query") == "biology"
        result = handler.handle_zim_query(
            query="search for biology limit=10", zim_file_path="/x.zim"
        )
        assert "Search Terms Required" not in str(result)

    @pytest.mark.parametrize(
        "query",
        [
            "search for query=biology",
            "search for limit=10",
        ],
    )
    def test_synthesize_path_fires_terms_required(self, query: str) -> None:
        """The synthesize dispatcher carries its own copy of the guard."""
        handler, mock = _handler_single_archive()
        result: Any = handler.handle_zim_query(
            query=query,
            zim_file_path="/x.zim",
            options={"synthesize": True},
        )
        assert "search_terms_required" in str(result), str(result)[:300]
        mock.search_zim_file_data.assert_not_called()


# ===========================================================================
# ``namespace=X`` is an operand, not a leaked kwarg
# ===========================================================================


class TestNamespaceOperandSurvivesParamLeakStrip:
    """``zim_query`` has no ``namespace`` parameter, so the query string is
    the only channel for it — stripping ``namespace=A`` left ``browse``
    alone, which fell through to a full-text search for the word "browse".
    """

    def test_browse_namespace_equals_form(self) -> None:
        intent, params, _ = IntentParser.parse_intent("browse namespace=A")
        assert intent == "browse"
        assert params.get("namespace") == "A"

    def test_walk_namespace_equals_form(self) -> None:
        intent, params, _ = IntentParser.parse_intent("walk namespace=C")
        assert intent == "walk_namespace"
        assert params.get("namespace") == "C"

    def test_quoted_operand_form(self) -> None:
        intent, params, _ = IntentParser.parse_intent("browse namespace='A'")
        assert intent == "browse"
        assert params.get("namespace") == "A"

    def test_filtered_search_namespace_equals_form(self) -> None:
        intent, params, _ = IntentParser.parse_intent("search foo in namespace=C")
        assert intent == "filtered_search"
        assert params.get("query") == "foo"
        assert params.get("namespace") == "C"

    def test_multi_char_namespace_still_falls_through(self) -> None:
        """The single-letter capture matches the strict namespace extractors,
        so ``namespace=AB`` keeps reaching the existing invalid-namespace
        guidance rather than being silently accepted."""
        _intent, params, _ = IntentParser.parse_intent("browse namespace=AB")
        assert params.get("namespace") is None

    @pytest.mark.parametrize(
        "query",
        [
            "tell me about Photosynthesis namespace=C",
            "tell me about Biology namespace=A limit=10",
        ],
    )
    def test_no_namespace_verb_still_strips(self, query: str) -> None:
        """Without a namespace verb the token is a genuine leak — the strip
        must still fire (post-a23 P1-D3 / post-a24)."""
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "tell_me_about"
        topic = params.get("topic") or ""
        assert "namespace" not in topic
        assert "=" not in topic


# ===========================================================================
# Title-internal elisions must not be read as quoted values
# ===========================================================================


class TestTitleInternalElisionNotTreatedAsQuotedValue:
    """``Rock 'n' Roll`` put an apostrophe pair at exactly the M8 token
    boundaries, so the quoted-value branch matched and returned ``n`` —
    the caller silently got the article for the letter N at cert 0.80.
    """

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("get article Rock 'n' Roll", "rock 'n' roll"),
            ("structure of Rock 'n' Roll", "rock 'n' roll"),
            ("links in Rock 'n' Roll", "rock 'n' roll"),
            ("summary of Fish 'n' Chips", "fish 'n' chips"),
        ],
    )
    def test_elision_kept_in_entry_path(self, query: str, expected: str) -> None:
        _intent, params, _ = IntentParser.parse_intent(query)
        assert params.get("entry_path") == expected

    @pytest.mark.parametrize(
        "query,expected",
        [
            ('get article "C/Biology"', "C/Biology"),
            ('get article "World War II"', "world war ii"),
            ('structure of "C/Photosynthesis"', "C/Photosynthesis"),
            ("get article 'World War II'", "world war ii"),
            # Trailing punctuation after the closer still peels.
            ('get article "World War II"?', "world war ii"),
        ],
    )
    def test_trailing_quoted_value_still_peels(self, query: str, expected: str) -> None:
        _intent, params, _ = IntentParser.parse_intent(query)
        assert params.get("entry_path") == expected

    @pytest.mark.parametrize(
        "query",
        ['get article ""', "get article '  '"],
    )
    def test_empty_quoted_value_still_drops(self, query: str) -> None:
        """The missing-arg guard must still be reachable."""
        _intent, params, _ = IntentParser.parse_intent(query)
        assert not params.get("entry_path")


# ===========================================================================
# Follow-up regressions found by the adversarial review of the fixes above
# ===========================================================================


class TestBatchEntriesKeepNamespaceCase:
    """``_restore_nonascii_case``'s namespace-prefix exemption originally
    lived behind a ``not isinstance(value, str) -> continue`` guard, so the
    LIST-valued ``entries`` param of ``get_zim_entries`` — the highest-volume
    consumer of the ``A/...`` paths this tool emits itself — was skipped
    wholesale and every batch fetch kept 404ing on ``a/climate_change``.
    """

    @pytest.mark.parametrize(
        "query,expected",
        [
            (
                "fetch entries A/Climate_change, A/Carbon_dioxide",
                ["A/Climate_change", "A/Carbon_dioxide"],
            ),
            ("fetch entries A/Foo and A/Bar", ["A/Foo", "A/Bar"]),
            # M7 anchoring is unaffected by the re-casing.
            ("get entries A/Foo and/or B/Bar", ["A/Foo", "B/Bar"]),
        ],
    )
    def test_list_param_paths_keep_typed_case(
        self, query: str, expected: list[str]
    ) -> None:
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "get_zim_entries"
        assert params.get("entries") == expected

    def test_scalar_sibling_unchanged(self) -> None:
        _intent, params, _ = IntentParser.parse_intent("get article A/Climate_change")
        assert params.get("entry_path") == "A/Climate_change"

    def test_rule_1_lowercasing_still_applies_to_plain_topics(self) -> None:
        """The exemption is narrow: a natural-language topic still obeys
        Tier-1 Rule 1."""
        _intent, params, _ = IntentParser.parse_intent("tell me about Biology")
        assert params.get("topic") == "biology"


class TestBatchEntriesResolveEndToEnd:
    """End-to-end, non-mocked: the mock-based batch coverage keyed on the
    lowercased path is exactly what let the 404 ship."""

    @pytest.fixture
    def climate_zim(self, real_content_zim_files: dict[str, Any]) -> Any:
        zim = real_content_zim_files.get("wikipedia_climate")
        if zim is None:
            pytest.skip("wikipedia_climate ZIM fixture not available")
        return zim

    @pytest.fixture
    def handler(self, climate_zim: Any) -> SimpleToolsHandler:
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.config import (
            CacheConfig,
            ContentConfig,
            LoggingConfig,
            OpenZimMcpConfig,
        )
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator
        from openzim_mcp.zim_operations import ZimOperations

        cfg = OpenZimMcpConfig(
            allowed_directories=[str(climate_zim.parent.parent)],
            cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
            content=ContentConfig(max_content_length=2000, snippet_length=100),
            logging=LoggingConfig(level="ERROR"),
        )
        ops = ZimOperations(
            cfg,
            PathValidator(cfg.allowed_directories),
            OpenZimMcpCache(cfg.cache),
            ContentProcessor(snippet_length=100),
        )
        return SimpleToolsHandler(ops)

    def test_batch_fetch_of_self_emitted_paths_succeeds(
        self, handler: SimpleToolsHandler, climate_zim: Any
    ) -> None:
        import json

        raw = handler.handle_zim_query(
            "fetch entries A/Climate_change, A/Carbon_dioxide", str(climate_zim)
        )
        # The response carries a trailing ``<!-- intent=... -->`` marker line.
        payload = json.loads(raw.split("\n<!--", 1)[0])
        results = payload["results"]
        assert len(results) == 2
        assert [r["entry_path"] for r in results] == [
            "A/Climate_change",
            "A/Carbon_dioxide",
        ]
        assert all(r["success"] for r in results), raw[:800]


class TestQuotedEntryPathWithTrailingTextStillPeels:
    """The elision fix first anchored the quoted CLOSER to end-of-query,
    which silently dropped any quoted title followed by a modifier clause.
    Control then fell through to the last-preposition branch, so the caller
    got a confident (0.85-0.95) lookup for the MODIFIER instead of the title
    they had explicitly disambiguated with quotes.

    The discriminator is the OPENER's context, not the closer's position: an
    elision apostrophe is always preceded by a title word, never by an anchor
    keyword.
    """

    @pytest.mark.parametrize(
        "query,expected",
        [
            ('structure of "Photosynthesis" in compact mode', "photosynthesis"),
            ('summary of "Climate change" in 3 sentences', "climate change"),
            ('toc for "War and Peace" chapter 3', "war and peace"),
            # A second quoted title must not win over the first.
            ('links in "Berlin" and "Paris"', "berlin"),
            ('get article "C/Biology" in compact mode', "C/Biology"),
        ],
    )
    def test_quoted_value_wins_over_trailing_modifier(
        self, query: str, expected: str
    ) -> None:
        _intent, params, _ = IntentParser.parse_intent(query)
        assert params.get("entry_path") == expected


class TestSearchQuotedTermDoesNotLeakQuoteChars:
    """``_extract_search`` captured the whole tail and peeled a quote pair
    afterwards, so a quoted term followed by prose shipped its literal quote
    chars (and the prose) to Xapian, and any query that merely BEGAN and
    ENDED with a quote char had its first and last characters deleted.
    """

    @pytest.mark.parametrize(
        "query,expected",
        [
            ('find "World War II" articles', "world war ii"),
            ('search for "photosynthesis" in wikipedia', "photosynthesis"),
            # Two quoted terms: the outer-pair peel used to yield the
            # unbalanced 'berlin" or "paris'.
            ('search for "Berlin" or "Paris"', "berlin"),
            ("find 'Paris' or 'London'", "paris"),
            ("search for “Berlin”, “Paris”", "berlin"),
            # Already-covered trailing-quote shapes stay correct.
            ('search for "quantum mechanics"', "quantum mechanics"),
            ("search for 'World War II'", "world war ii"),
        ],
    )
    def test_quoted_term_extracted_without_delimiters(
        self, query: str, expected: str
    ) -> None:
        _intent, params, _ = IntentParser.parse_intent(query)
        assert params.get("query") == expected

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("search for Murphy's law", "murphy's law"),
            ("search for O'Brien", "o'brien"),
            ("search for Earth's atmosphere", "earth's atmosphere"),
        ],
    )
    def test_possessive_apostrophe_is_not_a_delimiter(
        self, query: str, expected: str
    ) -> None:
        """The originally-reported truncation (``search for Murphy's law`` ->
        ``Murphy``) must stay fixed."""
        _intent, params, _ = IntentParser.parse_intent(query)
        assert params.get("query") == expected

    @pytest.mark.parametrize("query", ["search for ", "search for  "])
    def test_degenerate_tail_keeps_terms_required_guard_reachable(
        self, query: str
    ) -> None:
        _intent, params, _ = IntentParser.parse_intent(query)
        assert params.get("query") == "for"


class TestNamespaceCarveOutRequiresOperandContext:
    """The carve-out gated on a browse-family verb appearing ANYWHERE, so a
    genuine leak inside ordinary topical prose (``explore the history of X
    namespace=A``) was rewritten to prose that ``_PARAM_LEAK_RE`` can no
    longer see — re-opening the post-a23 P1-D3 pollution the strip exists to
    prevent. The verb must INTRODUCE the operand.
    """

    @pytest.mark.parametrize(
        "query,expected",
        [
            (
                "explore the history of Berlin namespace=A",
                "explore the history of Berlin",
            ),
            (
                "walk me through Photosynthesis namespace=C",
                "walk me through Photosynthesis",
            ),
            ("browse the archive of Rome namespace=A", "browse the archive of Rome"),
        ],
    )
    def test_prose_verb_does_not_shield_the_leak(
        self, query: str, expected: str
    ) -> None:
        assert IntentParser._strip_param_leaks(query) == expected

    def test_prose_verb_leak_does_not_pollute_the_parsed_query(self) -> None:
        _intent, params, _ = IntentParser.parse_intent(
            "explore the history of Berlin namespace=A"
        )
        text = " ".join(
            str(v) for k, v in params.items() if k in {"query", "topic", "entry_path"}
        )
        assert "namespace" not in text
        assert "=" not in text

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("browse namespace=A", "browse namespace A"),
            ("walk namespace=C", "walk namespace C"),
            ("browse namespace='A'", "browse namespace A"),
            ("search foo in namespace=C", "search foo in namespace C"),
            # The determiner/connector bridge keeps operand forms working.
            ("enumerate the namespace=M", "enumerate the namespace M"),
            ("dump entries in namespace=I", "dump entries in namespace I"),
        ],
    )
    def test_operand_forms_still_survive(self, query: str, expected: str) -> None:
        assert IntentParser._strip_param_leaks(query) == expected
