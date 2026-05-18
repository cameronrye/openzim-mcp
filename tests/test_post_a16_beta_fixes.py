"""Regression tests for the post-a16 beta-test sweep (a17 fixes).

The post-a16 live sweep against the 118 GB Wikipedia ZIM surfaced
ten user-facing defects:

- D1: ``tell me about Berlin and Paris`` silently dropped "Berlin"
  and returned the Paris article — connectors ``and`` / ``or`` /
  ``also`` / ``&`` / ``plus`` / period / ``->`` were absent from
  ``_CHAINED_INTENT_CONNECTORS``, so the chain detector never fired
  and the fuzzy ranker promoted whichever side won title-token
  match. Fix extends the connector list (soft connectors) and adds
  a right-promote branch that prepends the left's verb to a bare
  topic-shaped right half.

- D2: ``tell me about Apollo 11 also`` returned the unrelated
  ``Also`` disambig article. Trailing dangling connector ``also``
  was left in the topic, where it out-token-matched the full
  phrase. Fix strips orphan trailing connectors (``and``, ``or``,
  ``also``, ``plus``, ``then``, ``,``, ``&``) from the topic.

- D3: ``tell me about M/Title`` silently dropped the namespace
  prefix and returned the canonical ``Title`` article. Fix mirrors
  ``_handle_find_by_title``'s namespace-path detection guard in
  ``_handle_tell_me_about``.

- D4: ``tell me about Sun`` / ``Apollo 11`` / ``Java`` showed
  ``May also refer to: <sibling>`` instead of the proper
  ``Note: this topic also has a disambiguation page —
  see get article <X>_(disambiguation)`` footer, because the
  fuzzy title-search didn't rank ``<X>_(disambiguation)`` into
  the top hits when prefix-sibling sub-articles outranked it.
  Fix probes ``<canonical>_(disambiguation)`` explicitly via the
  title index as a fallback when the search-driven scan misses
  the twin.

- D5: ``browse namespace c`` (lowercase) succeeded but the error
  message for ``browse namespace AB`` claimed "needs a single
  uppercase namespace letter". Fix updates the wording in both
  ``browse_namespace`` and ``walk_namespace`` to "needs a single
  namespace letter ... case-insensitive".

- D6: ``search Photosynthesis in namespace AB`` / ``... 1`` /
  ``... _`` silently returned 0 results — the filtered_search
  namespace extractor accepted any ``[A-Za-z0-9_.-]+`` argument
  without validation. Fix tightens the regex and adds a handler-
  side validation guard that surfaces the same "Missing or
  Invalid Namespace" error the ``browse`` / ``walk`` siblings use.

- D7: ``find article titled m/Title`` (lowercase namespace prefix)
  bypassed the D6 redirect because the guard required
  ``title[0].isupper()``. Fix adds a post-lookup check in the
  compact path: when the title index returns zero hits AND the
  title matches ``<lowercase-alpha>/<rest>``, surface the same
  redirect with the suggestion path normalised to uppercase.

- D8: ``tell me about Berlin (disambiguation)`` returned the
  unrelated ``Word-sense_disambiguation`` article. Fix probes the
  exact ``<X>_(disambiguation)`` path before the fuzzy search.

- D9: ``tell me about Sun_(disambiguation)`` (underscore form)
  returned no results because the title index is whitespace-
  tokenised. Fix normalises underscores to spaces in the topic
  before search.

- D10: ``list namespaces`` reported ``(per-namespace sum: N)``
  without explaining why the sum differs from the header total.
  Fix adds an inline note about the delta (``+13 well-knowns/
  redirects``).

Each test pins one defect; failures here mean a regression on the
specific bug.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler


# ---------------------------------------------------------------------------
# D1: soft chain connectors
# ---------------------------------------------------------------------------


class TestD1SoftChainConnectors:
    """D1: ``and`` / ``or`` / ``also`` / ``&`` / ``plus`` / period /
    ``->`` weren't in ``_CHAINED_INTENT_CONNECTORS``. Fix extends the
    list and right-promotes a bare topic-shaped right half so the
    chain detector fires uniformly.
    """

    @pytest.fixture
    def handler(self) -> SimpleToolsHandler:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        # Chain detection fires before parse_intent → backends untouched.
        mock.search_zim_file_data.side_effect = AssertionError(
            "search should not run for chained queries"
        )
        return SimpleToolsHandler(mock)

    @pytest.mark.parametrize(
        "query",
        [
            "tell me about Berlin and Paris",
            "tell me about Berlin or Paris",
            "tell me about Berlin also Paris",
            "tell me about Berlin & Paris",
            "tell me about Berlin plus Paris",
            "tell me about Berlin -> Paris",
            "tell me about Berlin. Then Paris",
            "tell me about Apollo 11 also Apollo 12",
            "tell me about Apollo 11 and Apollo 12",
            "describe Berlin AND Paris",
            "explain Berlin or Paris",
        ],
    )
    def test_soft_connector_fires_chain_warning(
        self, handler: SimpleToolsHandler, query: str
    ) -> None:
        out = handler.handle_zim_query(
            query, zim_file_path="/x.zim", options={"compact": False}
        )
        assert "Chained Operations Detected" in out
        assert "chained_intent_rejected" in out

    def test_real_topic_with_inline_or_unaffected(self) -> None:
        # ``the capital of Germany`` after "and" doesn't start with a
        # capital → right-promote heuristic skips → falls through to
        # normal intent parsing. Sanity guard against over-aggressive
        # firing.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.return_value = {
            "results": [{"path": "Berlin", "title": "Berlin"}],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "stub-body"
        mock.find_entry_by_title_data.return_value = {"results": [], "total": 0}
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "tell me about Berlin and the capital of Germany",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Chained Operations Detected" not in out

    def test_period_connector_strips_leading_adverbial(self) -> None:
        # ``... . Then Paris`` should project as ``tell me about Paris``,
        # not ``tell me about Then Paris``.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "tell me about Berlin. Then Paris",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Chained Operations Detected" in out
        # Right half rendered as ``tell me about Paris`` (verb projected,
        # adverbial ``Then`` stripped).
        assert "tell me about Paris" in out


# ---------------------------------------------------------------------------
# D2: orphan trailing connector strip
# ---------------------------------------------------------------------------


class TestD2OrphanTrailingConnector:
    """D2: ``tell me about Apollo 11 also`` left ``also`` in the topic
    and the fuzzy ranker promoted the unrelated ``Also`` article. Fix
    strips orphan trailing connector tokens in ``_extract_tell_me_about``.
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("tell me about Apollo 11 also", "Apollo 11"),
            ("tell me about Berlin and", "Berlin"),
            ("tell me about Photosynthesis or", "Photosynthesis"),
            ("tell me about Mars plus", "Mars"),
            ("tell me about Sun then", "Sun"),
            ("tell me about Berlin,", "Berlin"),
            ("tell me about Berlin &", "Berlin"),
            ("tell me about Berlin and also", "Berlin"),
            # Real "and" inside topic stays put: only trailing strips.
            ("tell me about Romeo and Juliet", "Romeo and Juliet"),
        ],
    )
    def test_orphan_trailing_stripped(self, raw: str, expected: str) -> None:
        intent, params, _ = IntentParser.parse_intent(raw)
        assert intent == "tell_me_about"
        assert params["topic"] == expected


# ---------------------------------------------------------------------------
# D3: tell_me_about namespace-path redirect
# ---------------------------------------------------------------------------


class TestD3TellMeAboutNamespacePathRedirect:
    """D3: ``tell me about M/Title`` silently dropped the namespace
    prefix and returned the canonical ``Title`` article. Fix mirrors
    ``_handle_find_by_title``'s namespace-path detection guard.
    """

    @pytest.fixture
    def handler(self) -> SimpleToolsHandler:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        # The redirect fires upfront — no search should run.
        mock.search_zim_file_data.side_effect = AssertionError(
            "search should not be called for namespace paths"
        )
        return SimpleToolsHandler(mock)

    @pytest.mark.parametrize(
        "topic",
        [
            "M/Title",
            "M/Counter",
            "c/Berlin",  # lowercase namespace letter
            "w/mainPage",
            "A/Photosynthesis",
            "m/Title",
        ],
    )
    def test_namespace_path_returns_redirect(
        self, handler: SimpleToolsHandler, topic: str
    ) -> None:
        out = handler.handle_zim_query(
            f"tell me about {topic}",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Namespace Path, Not a Topic" in out
        # Suggests get_article with the uppercase-normalised path.
        normalized = topic[0].upper() + topic[1:]
        assert f"get article {normalized}" in out
        # Also suggests bare-name title search.
        assert f"tell me about {topic[2:].strip()}" in out

    def test_real_topic_unaffected(self) -> None:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.return_value = {
            "results": [{"path": "Photosynthesis", "title": "Photosynthesis"}],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "stub-body"
        mock.find_entry_by_title_data.return_value = {"results": [], "total": 0}
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "tell me about Photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Namespace Path, Not a Topic" not in out


# ---------------------------------------------------------------------------
# D4: disambig twin explicit probe
# ---------------------------------------------------------------------------


class TestD4DisambigTwinExplicitProbe:
    """D4: when the canonical's prefix-sibling sub-articles outrank
    the ``<X>_(disambiguation)`` twin in the search, the footer fell
    through to ``May also refer to: <sub-article>`` wording instead
    of the correct ``Note: this topic also has a disambiguation page``
    hint. Fix probes the title index explicitly for the twin.
    """

    def test_probe_finds_twin_when_search_misses_it(self) -> None:
        mock = MagicMock()
        # Title-index probe for ``Sun (disambiguation)`` returns the
        # exact path (in real-world archives, the search-engine
        # top-hits don't always include this twin).
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {"path": "Sun_(disambiguation)", "title": "Sun (disambiguation)"}
            ],
            "total": 1,
        }
        handler = SimpleToolsHandler(mock)
        twin = handler._probe_disambig_twin("/x.zim", "Sun")
        assert twin == "Sun_(disambiguation)"

    def test_probe_rejects_unrelated_disambig_match(self) -> None:
        # An archive that returns ``Word-sense_disambiguation`` for a
        # ``X (disambiguation)`` lookup must NOT be promoted — the
        # path doesn't start with ``Sun_`` and ends with the right
        # suffix only by accident of token-matching.
        mock = MagicMock()
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {
                    "path": "Word-sense_disambiguation",
                    "title": "Word-sense disambiguation",
                }
            ],
            "total": 1,
        }
        handler = SimpleToolsHandler(mock)
        twin = handler._probe_disambig_twin("/x.zim", "Sun")
        assert twin is None

    def test_probe_accepts_url_encoded_form(self) -> None:
        # Some archives store the disambig suffix URL-encoded.
        mock = MagicMock()
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {
                    "path": "Sun_%28disambiguation%29",
                    "title": "Sun (disambiguation)",
                }
            ],
            "total": 1,
        }
        handler = SimpleToolsHandler(mock)
        twin = handler._probe_disambig_twin("/x.zim", "Sun")
        assert twin == "Sun_%28disambiguation%29"

    def test_probe_returns_none_when_archive_lookup_fails(self) -> None:
        mock = MagicMock()
        mock.find_entry_by_title_data.side_effect = RuntimeError("boom")
        handler = SimpleToolsHandler(mock)
        twin = handler._probe_disambig_twin("/x.zim", "Sun")
        assert twin is None


# ---------------------------------------------------------------------------
# D5: drop "uppercase" wording from browse/walk error messages
# ---------------------------------------------------------------------------


class TestD5LowercaseNamespaceWording:
    """D5: error messages told the caller "needs a single uppercase
    namespace letter", but the implementation silently upcases
    lowercase input (intentional per ``namespace.py:487``). Fix
    drops the "uppercase" wording.
    """

    def test_browse_namespace_error_drops_uppercase_wording(self) -> None:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "browse namespace AB",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Missing or Invalid Namespace" in out
        assert "uppercase" not in out.lower()
        assert "case-insensitive" in out

    def test_walk_namespace_error_drops_uppercase_wording(self) -> None:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "walk namespace 1",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Missing or Invalid Namespace" in out
        assert "uppercase" not in out.lower()
        assert "case-insensitive" in out


# ---------------------------------------------------------------------------
# D6: filtered_search namespace validation parity
# ---------------------------------------------------------------------------


class TestD6FilteredSearchValidationParity:
    """D6: ``search ... in namespace AB`` / ``... 1`` / ``... _``
    silently returned 0 hits because the extractor accepted multi-
    char / digit / special-char arguments. Fix tightens the regex
    and adds a handler-side validation guard.
    """

    @pytest.fixture
    def handler(self) -> SimpleToolsHandler:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        # Backend must NOT be reached for invalid namespace inputs.
        mock.search_with_filters_with_canonical_splice.side_effect = AssertionError(
            "backend should not be called for invalid namespace"
        )
        return SimpleToolsHandler(mock)

    @pytest.mark.parametrize(
        "query",
        [
            "search Photosynthesis in namespace AB",
            "search Photosynthesis in namespace 1",
            "search Photosynthesis in namespace _",
            "search Photosynthesis in namespace 99",
            "search Photosynthesis in namespace AAA",
        ],
    )
    def test_invalid_namespace_returns_error(
        self, handler: SimpleToolsHandler, query: str
    ) -> None:
        out = handler.handle_zim_query(
            query, zim_file_path="/x.zim", options={"compact": False}
        )
        assert "Missing or Invalid Namespace" in out

    def test_valid_namespace_passes_through(self) -> None:
        # Single letter (case-insensitive) reaches the backend.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_with_filters_with_canonical_splice.return_value = "hits"
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "search Photosynthesis in namespace c",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Missing or Invalid Namespace" not in out
        # Confirm uppercase normalisation reached the backend.
        call = mock.search_with_filters_with_canonical_splice.call_args
        # 3rd positional arg is namespace; signature:
        # (zim_file, query, namespace, content_type, limit, offset)
        assert call.args[2] == "C"

    def test_intent_parser_extracts_uppercase_single_letter(self) -> None:
        intent, params, _ = IntentParser.parse_intent(
            "search Photosynthesis in namespace c"
        )
        assert intent == "filtered_search"
        assert params["namespace"] == "C"

    def test_intent_parser_skips_multi_char_namespace(self) -> None:
        intent, params, _ = IntentParser.parse_intent(
            "search Photosynthesis in namespace AB"
        )
        # No namespace param extracted → handler's guard surfaces the
        # missing-namespace error.
        assert params.get("namespace") is None


# ---------------------------------------------------------------------------
# D7: find_by_title lowercase namespace-path redirect (post-lookup)
# ---------------------------------------------------------------------------


class TestD7FindByTitleLowercaseNamespaceRedirect:
    """D7: ``find article titled m/Title`` (lowercase namespace) bypassed
    the upfront redirect because the guard required ``isupper()``. Fix
    adds a post-lookup check: when the title index returns zero hits
    AND the title matches ``<lowercase-alpha>/<rest>``, surface the
    same redirect with the suggestion path normalised to uppercase.
    """

    @pytest.fixture
    def handler(self) -> SimpleToolsHandler:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        # Zero hits triggers the post-lookup redirect for lowercase
        # paths.
        mock.find_entry_by_title_data.return_value = {"results": [], "total": 0}
        return SimpleToolsHandler(mock)

    @pytest.mark.parametrize(
        "title",
        ["m/Title", "c/Berlin", "w/mainPage"],
    )
    def test_lowercase_namespace_path_redirected_on_zero_hits(
        self, handler: SimpleToolsHandler, title: str
    ) -> None:
        out = handler.handle_zim_query(
            f"find article titled {title}",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        assert "Namespace Path, Not a Title" in out
        normalized = title[0].upper() + title[1:]
        assert f"get article {normalized}" in out

    def test_real_lowercase_title_returned_when_index_hits(self) -> None:
        # ``a/b`` is a real Wikipedia article (A/B testing). When the
        # title index returns a hit, the redirect must NOT fire.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.find_entry_by_title_data.return_value = {
            "results": [{"path": "A/B", "title": "A/B", "score": 1.0}],
            "total": 1,
        }
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "find article titled a/b",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        assert "Namespace Path, Not a Title" not in out
        assert "A/B" in out


# ---------------------------------------------------------------------------
# D8: tell_me_about disambig exact-path probe
# ---------------------------------------------------------------------------


class TestD8DisambigExactPathProbe:
    """D8: ``tell me about Berlin (disambiguation)`` returned the
    unrelated ``Word-sense_disambiguation`` article because the
    fuzzy ranker ranked it above the requested ``Berlin_(disambiguation)``.
    Fix probes the exact ``<X>_(disambiguation)`` path before the
    fuzzy search.
    """

    def test_disambig_topic_resolves_to_exact_twin(self) -> None:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        # The exact-path probe returns the disambig twin.
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {
                    "path": "Berlin_(disambiguation)",
                    "title": "Berlin (disambiguation)",
                }
            ],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "<body>"
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "tell me about Berlin (disambiguation)",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Berlin_(disambiguation)" in out
        # The fuzzy search must NOT have been called — the exact probe
        # short-circuits.
        mock.search_zim_file_data.assert_not_called()


# ---------------------------------------------------------------------------
# D9: tell_me_about underscore normalisation
# ---------------------------------------------------------------------------


class TestD9UnderscoreNormalisation:
    """D9: ``tell me about Sun_(disambiguation)`` (underscored path
    form) returned no results because the title index is whitespace-
    tokenised. Fix normalises underscores to spaces in the topic.
    """

    def test_underscored_disambig_resolves_via_d8_probe(self) -> None:
        # Combined D8 + D9 test: underscored input goes through D9
        # normalisation then hits the D8 exact-path probe.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {"path": "Sun_(disambiguation)", "title": "Sun (disambiguation)"}
            ],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "<body>"
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "tell me about Sun_(disambiguation)",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        # Resolved via the D8 probe (D9 normalised first).
        assert "Sun_(disambiguation)" in out
        mock.search_zim_file_data.assert_not_called()


# ---------------------------------------------------------------------------
# D10: list_namespaces per-namespace-sum annotation
# ---------------------------------------------------------------------------


class TestD10NamespaceSumAnnotation:
    """D10: ``list namespaces`` previously showed
    ``(per-namespace sum: N)`` with no explanation. Fix annotates the
    delta inline.
    """

    def test_per_namespace_sum_diff_annotated(self) -> None:
        from openzim_mcp.compact_renderers import render_namespaces

        data: dict[str, Any] = {
            "total_entries": 27_199_904,
            "is_total_authoritative": False,
            "discovery_method": "sampling",
            "namespaces": {
                "C": {"total": 27_199_903, "description": "User content"},
                "M": {"total": 12, "description": "Metadata"},
                "W": {"total": 2, "description": "Well-known"},
            },
        }
        out = render_namespaces(data)
        assert "per-namespace sum: 27,199,917" in out
        # Inline diff annotation explaining the +13.
        assert "+13" in out
        assert "well-knowns" in out

    def test_matching_sum_drops_annotation(self) -> None:
        # When sum equals header total, no annotation noise.
        from openzim_mcp.compact_renderers import render_namespaces

        data: dict[str, Any] = {
            "total_entries": 100,
            "is_total_authoritative": True,
            "discovery_method": "full_iteration",
            "namespaces": {"C": {"total": 100, "description": "User content"}},
        }
        out = render_namespaces(data)
        assert "per-namespace sum" not in out
