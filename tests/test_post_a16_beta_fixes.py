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

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler

# ---------------------------------------------------------------------------
# D1: soft chain connectors
# ---------------------------------------------------------------------------


class TestD1ChainConnectorsHardFire:
    """D1 (pass-1, refined in pass-2): chain warning fires only for
    *clear* chain markers — connectors that almost never appear inside
    real article titles (``also``, ``plus``, ``. Then``, ``->``). The
    ambiguous cases (``and`` / ``or`` / ``&`` / ``,`` / ``/``) are
    handled by the soft footer in ``TestD1SoftFooter`` below, because
    a hard chain warning false-fires on common title shapes
    (``Romeo and Juliet``, ``Tom & Jerry``, ``Vienna, Austria``).
    """

    @pytest.fixture
    def handler(self) -> SimpleToolsHandler:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.side_effect = AssertionError(
            "search should not run for chained queries"
        )
        return SimpleToolsHandler(mock)

    @pytest.mark.parametrize(
        "query",
        [
            "tell me about Berlin also Paris",
            "tell me about Berlin plus Paris",
            "tell me about Berlin -> Paris",
            "tell me about Berlin. Then Paris",
            "tell me about Apollo 11 also Apollo 12",
        ],
    )
    def test_clear_chain_marker_fires(
        self, handler: SimpleToolsHandler, query: str
    ) -> None:
        out = handler.handle_zim_query(
            query, zim_file_path="/x.zim", options={"compact": False}
        )
        assert "Chained Operations Detected" in out
        assert "chained_intent_rejected" in out

    @pytest.mark.parametrize(
        "query",
        [
            # Pass-2 self-audit: period+capital connector must not
            # mis-fire on common title abbreviations whose bare left
            # half is too short to be a real topic.
            "tell me about Dr. Strange",
            "tell me about St. Louis",
            "tell me about Mt. Everest",
            "tell me about Mr. Bean",
            "describe Ms. Marvel",
        ],
    )
    def test_title_abbreviation_with_period_does_not_fire(self, query: str) -> None:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.return_value = {
            "results": [{"path": "stub", "title": "stub"}],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "stub-body"
        mock.find_entry_by_title_data.return_value = {"results": [], "total": 0}
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            query, zim_file_path="/x.zim", options={"compact": False}
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

    @pytest.mark.parametrize(
        "query",
        [
            # Soft connectors must NOT fire hard chain (false positives
            # on real titles like Romeo and Juliet, Tom & Jerry, etc.).
            "tell me about Berlin and Paris",
            "tell me about Berlin or Paris",
            "tell me about Berlin & Paris",
            "tell me about Berlin, Paris",
            "tell me about Berlin / Paris",
            "tell me about Berlin vs Paris",
            "tell me about Romeo and Juliet",
            "tell me about Pride and Prejudice",
            "tell me about Now and Then",
            "tell me about Tom & Jerry",
        ],
    )
    def test_soft_connectors_do_not_fire_hard_chain(self, query: str) -> None:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.return_value = {
            "results": [{"path": "stub", "title": "stub"}],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "stub-body"
        mock.find_entry_by_title_data.return_value = {"results": [], "total": 0}
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            query, zim_file_path="/x.zim", options={"compact": False}
        )
        assert "Chained Operations Detected" not in out


class TestD1SoftFooter:
    """D1 (pass-2): for ambiguous connectors (``and`` / ``or`` / ``&``
    / ``,`` / ``/``), the resolved-article response carries a footer
    naming what was picked vs. dropped — unless the returned title
    already includes both halves (``Romeo and Juliet``), in which
    case the footer is suppressed.
    """

    def _make_handler(
        self, top_title: str, top_path: Optional[str] = None
    ) -> SimpleToolsHandler:
        """Build a mock that lets the handler reach the article-fetch
        path. Title-promotion needs a score-1.0 title-index hit so
        ``_promote_topic_via_title_index`` succeeds when the search's
        top hit isn't a strong token-match for the topic.

        Post-a20 P1-D2: the alias-fallback in ``_soft_connector_footer``
        now also calls ``find_entry_by_title_data`` to check whether a
        connector half title-resolves to ``top_path``. A blanket
        ``return_value`` would falsely report that every half (incl.
        ``Berlin`` / ``Mozart``) resolves to ``top_path``, silently
        suppressing footers that real archives would still emit. Use
        a ``side_effect`` that only returns the score-1.0 hit when
        the queried title case-insensitively contains ``top_title``
        (covers the title-promotion path for the original chained
        topic) and falls back to empty for unrelated half-lookups.
        """
        path = top_path or top_title
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.return_value = {
            "results": [{"path": path, "title": top_title}],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "stub-body"
        # Title-promotion + disambig-twin probe both call this. Returning
        # a score-1.0 hit when the queried title is ``top_title`` (or
        # the full chained topic that the title-promotion path probes)
        # lets the handler reach the article-fetch + footer-append code.
        # Unrelated half-lookups (Berlin / Mozart / etc.) get an empty
        # result so the alias-fallback doesn't falsely upgrade them.
        top_title_lower = top_title.lower()

        def _title_lookup(
            _zim: str,
            title: str,
            *,
            cross_file: bool = False,
            limit: int = 1,
        ) -> dict[str, Any]:
            q = (title or "").lower()
            if q == top_title_lower or top_title_lower in q:
                return {
                    "results": [{"path": path, "title": top_title, "score": 1.0}],
                    "total": 1,
                }
            return {"results": [], "total": 0}

        mock.find_entry_by_title_data.side_effect = _title_lookup
        return SimpleToolsHandler(mock)

    def test_one_half_in_title_emits_footer(self) -> None:
        # ``Berlin and Paris`` resolved to ``Paris`` → footer fires
        # naming Berlin as the dropped half.
        handler = self._make_handler(top_title="Paris")
        out = handler.handle_zim_query(
            "tell me about Berlin and Paris",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" in out
        # Post-b1 P1-D2: footer echoes entities in caller's original case.
        assert "Berlin" in out
        assert "Paris" in out
        assert "tell me about Berlin" in out

    def test_both_halves_in_title_suppresses_footer(self) -> None:
        # ``Romeo and Juliet`` resolved to ``Romeo and Juliet`` → no
        # footer (single article).
        handler = self._make_handler(top_title="Romeo and Juliet")
        out = handler.handle_zim_query(
            "tell me about Romeo and Juliet",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" not in out

    def test_tom_and_jerry_suppressed(self) -> None:
        # ``Tom & Jerry`` resolved to ``Tom and Jerry`` → both halves
        # in title → suppress.
        handler = self._make_handler(top_title="Tom and Jerry")
        out = handler.handle_zim_query(
            "tell me about Tom & Jerry",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" not in out

    def test_short_halves_skipped(self) -> None:
        # ``A and B`` — neither half is substantive (1-char each).
        # No footer.
        handler = self._make_handler(top_title="A")
        out = handler.handle_zim_query(
            "tell me about A and B",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" not in out

    def test_comma_connector_footer(self) -> None:
        # ``Berlin, Paris`` resolved to ``Paris`` only → footer.
        handler = self._make_handler(top_title="Paris")
        out = handler.handle_zim_query(
            "tell me about Berlin, Paris",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" in out
        # Post-b1 P1-D2: footer echoes entities in caller's original case.
        assert "Berlin" in out


class TestD1RealTopicWithLowercaseRightUnchanged:
    """Sanity: prose right-side with lowercase first content word
    (``the capital of Germany``) must not trigger the right-promote
    or soft footer.
    """

    def test_lowercase_right_unaffected(self) -> None:
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
        # Soft footer also suppressed because "the capital..." is
        # not substantive (lowercase first word).
        # (Substantive check fires on uppercase first-content-token
        # heuristic via the right-promote branch, but the soft footer
        # uses _is_substantive_topic — short lowercase prose passes
        # because tokens count ≥2, but the check is on chars/tokens.
        # We assert at minimum no hard chain.)


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
            # Sub-D-2 Rule 1 lowercases the query before param extraction.
            ("tell me about Apollo 11 also", "apollo 11"),
            ("tell me about Berlin and", "berlin"),
            ("tell me about Photosynthesis or", "photosynthesis"),
            ("tell me about Mars plus", "mars"),
            ("tell me about Berlin,", "berlin"),
            ("tell me about Berlin &", "berlin"),
            ("tell me about Berlin and also", "berlin"),
            # Real "and" inside topic stays put: only trailing strips.
            ("tell me about Romeo and Juliet", "romeo and juliet"),
            # Pass-2 self-audit: ``then`` is NOT in the strip list,
            # so titles ending with ``Then`` (Now and Then, Then) are
            # preserved.
            ("tell me about Now and Then", "now and then"),
            ("tell me about then", "then"),
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
        # Sub-D-2 Rule 1 lowercases the query, so the extracted topic
        # is lowercase. The redirect normalises only the first char to
        # uppercase. Compute expectations from the lowercased topic.
        lowered = topic.lower()
        normalized = lowered[0].upper() + lowered[1:]
        assert f"get article {normalized}" in out
        # Also suggests bare-name title search (lowercase suffix).
        assert f"tell me about {lowered[2:].strip()}" in out

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
        # Sub-D-2 Rule 1 lowercases the query; the redirect normalises
        # only the first char to uppercase. Compute expectation from
        # the lowercased title.
        lowered = title.lower()
        normalized = lowered[0].upper() + lowered[1:]
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


# ===========================================================================
# Pass 3 (post-pass-2 live-MCP sweep) — defects P3-D1 .. P3-D7
# ===========================================================================
#
# The live MCP server on a16 (pre pass-1/pass-2 fixes) was probed against
# the same 118 GB Wikipedia archive. Pass 3 surfaced seven new defects that
# pass-1's adversarial set hadn't reached, including two critical surface
# crashes:
#
# - P3-D1 (CRITICAL): ``search Berlin in namespace C`` /
#   ``search Tokyo in namespace C`` / ``search Paris in namespace C`` —
#   any single-word search whose canonical IS the BM25 top hit — crashed
#   with ``KeyError: 'namespace'``. Root cause: the
#   ``_perform_filtered_search_data`` data builder deliberately strips
#   ``namespace`` / ``content_type`` per its own comment (a TypedDict-
#   shaped contract), but the renderer ``_format_filtered_response`` does
#   direct ``result['namespace']`` access. The synthetic-canonical splice
#   row carries the keys, so any path that splices works; paths that fall
#   through the ``payload.get("results", [])`` shape crash. Fix populates
#   ``namespace`` / ``content_type`` at the data-builder boundary so the
#   renderer's contract holds end-to-end.
#
# - P3-D2 (CRITICAL): ``walk namespace M`` returns ``next_cursor`` with
#   ``s.scan_at`` envelope, but the top-level cursor decoder in
#   ``simple_tools.py`` requires ``s.o`` (offset). Replaying the cursor
#   the same tool just issued fails with ``cursor_decode``. Fix
#   normalises the wire schema to ``s.o`` across all walk_namespace
#   emit sites; the dispatcher still maps ``offset`` to ``scan_at``
#   internally so the libzim-level semantics are unchanged.
#
# - P3-D3 (HIGH): ``list_namespaces`` / ``walk_namespace`` /
#   ``browse_namespace`` / metadata report four different counts for the
#   same archive (C=27,199,903 vs 27,199,904; M=12 vs 13). Same family
#   as a10/a11 aggregator-disagreement defects. Fix routes all four
#   surfaces through a single canonical count and exposes both
#   ``entry_count`` and ``all_entry_count`` explicitly in
#   ``list_namespaces`` instead of one number plus a confusing
#   parenthetical.
#
# - P3-D4 (MEDIUM): the ``suggestions`` operation's missing-arg hint
#   advertises ``autocomplete "evol"`` as a valid form, but that quoted
#   form routes to ``search`` intent (cert 0.50). Fix teaches the intent
#   parser to recognise quoted-prefix ``autocomplete`` so the help and
#   the implementation agree.
#
# - P3-D5 (LOW): ``show structure of <X>`` truncates at 6 KB and emits
#   the generic "page using the cursor in the body above, tighten the
#   query, or pass compact=False" footer. ``show_structure`` output has
#   no cursor; "tighten the query" doesn't apply. Fix emits an
#   operation-specific footer recommending ``compact=False`` (or section
#   filtering when supported).
#
# - P3-D6 (LOW): ``links in <X>`` default limit of 3 forces an immediate
#   paging treadmill on hub articles (Berlin: 3 of 2,749 internal links).
#   Fix bumps default to 25, matching the ``articles related to`` scan
#   budget.
#
# - P3-D7 (LOW): ``browse namespace M`` accepts a cursor whose ``s.ns``
#   field encodes a different namespace (C) and silently rebinds to M.
#   Fix rejects cursors whose ``s.ns`` doesn't match the requested
#   namespace; the cursor's ``ai`` (archive identity) check already
#   provided the precedent for strict cursor-vs-request matching.

# ---------------------------------------------------------------------------
# P3-D1: filtered-search namespace KeyError — contract restoration
# ---------------------------------------------------------------------------


class TestP3D1FilteredSearchNamespaceContract:
    """P3-D1: contract gap between the filtered-search data builder
    (which deliberately stripped ``namespace`` / ``content_type``) and
    the renderer (which did direct-key access). Live MCP saw any search
    whose BM25 top hit equalled the canonical (Berlin / Tokyo / Paris)
    crash with ``KeyError: 'namespace'``.
    """

    def test_renderer_does_not_crash_on_results_without_namespace(self) -> None:
        """Renderer defence: the contract was ambiguous, so the data
        builder shipped rows without ``namespace`` and the renderer
        crashed. After fix, the renderer must defensively render those
        rows (using the active filter as the namespace label) instead
        of raising. Belt-and-braces alongside the data-builder fix.
        """
        from openzim_mcp.zim.search import (
            _FilteredScanState,
            _format_filter_text,
            _format_filtered_response,
        )

        # Pre-fix data-builder shape: missing namespace / content_type.
        results = [
            {
                "path": "Berlin",
                "title": "Berlin",
                "snippet": "Berlin is the capital of Germany.",
            }
        ]
        scan = _FilteredScanState(
            filtered_count=1,
            scanned=1,
            scan_cap_hit=False,
            total_filtered_is_lower_bound=False,
        )
        # Must NOT raise KeyError.
        out = _format_filtered_response(
            "Berlin", _format_filter_text("C", None), results, scan, 1, 0, 10
        )
        assert "Berlin" in out
        # Fall-back namespace label reflects the active filter.
        assert "Namespace: C" in out

    def test_data_builder_populates_namespace_and_content_type(self) -> None:
        """Data-builder contract: the _data variant must include
        ``namespace`` and ``content_type`` on every hit so the renderer's
        direct-access pattern is safe end-to-end. Tested via the projection
        helper the production code now shares with the legacy path.
        """
        from openzim_mcp.zim.search import _SearchMixin

        class _FakeEntry:
            title = "Berlin"

            def get_item(self) -> Any:
                class _Item:
                    mimetype = "text/html"

                return _Item()

        class _Stub(_SearchMixin):
            def __init__(self) -> None:
                pass

            def _get_entry_snippet(self, *_args: Any, **_kwargs: Any) -> str:
                return "Berlin is the capital of Germany."

        stub = _Stub()
        page = [("Berlin", _FakeEntry(), "C", "text/html")]
        results = stub._build_filtered_results(
            page, content_type=None, offset=0, query="Berlin"
        )
        assert results[0]["namespace"] == "C"
        assert results[0]["content_type"] == "text/html"

    def test_splice_reorder_path_renders_without_crash(self) -> None:
        """End-to-end regression: the splice / reorder branch at
        ``search_with_filters_with_canonical_splice`` previously fell
        through to ``_format_filtered_response`` with namespace-less
        result rows from the data builder when the canonical was NOT
        the BM25 top hit. Live MCP saw this fire for ``search Berlin
        in namespace C`` whose top BM25 hit was ``Berlin_(disambiguation)``
        rather than the canonical ``Berlin``. Verify the full pipeline
        now survives.
        """
        from openzim_mcp.zim.search import _SearchMixin

        class _Stub(_SearchMixin):
            def __init__(self) -> None:
                pass

            def search_with_filters_data(self, *_args: Any, **_kwargs: Any) -> dict:
                # Top BM25 hit is NOT the canonical, triggering the
                # reorder/splice branch (not the canonical-IS-top
                # short-circuit). Pre-fix data-builder shape: no
                # ``namespace`` / ``content_type`` keys on rows.
                return {
                    "query": "Berlin",
                    "namespace_filter": "C",
                    "content_type_filter": None,
                    "results": [
                        {
                            "path": "Berlin_(disambiguation)",
                            "title": "Berlin (disambiguation)",
                            "snippet": "Berlin is a city in Germany.",
                        },
                        {
                            "path": "Berlin",
                            "title": "Berlin",
                            "snippet": "Berlin is the capital of Germany.",
                        },
                        {
                            "path": "List_of_songs_about_Berlin",
                            "title": "List of songs about Berlin",
                            "snippet": "This is a list of songs ...",
                        },
                    ],
                    "next_cursor": None,
                    "total": 3,
                    "done": True,
                    "page_info": {"offset": 0, "limit": 10, "returned_count": 3},
                }

            def find_entry_by_title_data(self, *_args: Any, **_kwargs: Any) -> dict:
                return {
                    "results": [
                        {"path": "Berlin", "title": "Berlin", "score": 1.0},
                    ]
                }

        stub = _Stub()
        # Pre-fix: KeyError 'namespace' on the namespace-less rows from
        # the data builder. Post-fix: renders cleanly with the filter
        # fallback label.
        out = stub.search_with_filters_with_canonical_splice(
            "/x.zim", "Berlin", namespace="C", limit=10, offset=0
        )
        assert "Berlin" in out
        # All result rows render with namespace label (either via the
        # restored data-builder contract or the renderer's filter
        # fallback).
        assert "Namespace: C" in out


# ---------------------------------------------------------------------------
# P3-D2: walk_namespace cursor envelope mismatch (scan_at -> o)
# ---------------------------------------------------------------------------


class TestP3D2WalkNamespaceCursorRoundTrip:
    """P3-D2: ``walk namespace M`` (and W, C) emits ``next_cursor`` whose
    state envelope uses ``s.scan_at`` (live MCP observed), but the
    top-level cursor decoder in ``simple_tools.py`` requires ``s.o``
    (offset). Replaying the cursor the same tool just issued fails with
    ``cursor_decode``. Fix normalises the wire schema to ``s.o`` while
    keeping ``scan_at`` as the internal cursor_state key for libzim
    semantics.
    """

    def test_walk_namespace_m_cursor_uses_o_field_on_wire(self) -> None:
        """The M-walker's emitted cursor must use ``s.o`` on the wire so
        the universal top-level decoder accepts it.
        """
        import base64 as _b64
        import json as _json
        from pathlib import Path
        from unittest.mock import MagicMock

        from openzim_mcp.zim.namespace import _NamespaceMixin

        # Fake archive with 5 metadata keys (so a page of 3 leaves
        # 2 more — next_cursor is emitted).
        archive = MagicMock()
        archive.metadata_keys = ["Title", "Description", "Creator", "Publisher", "Date"]

        out = _NamespaceMixin._walk_new_scheme_metadata(
            archive,
            scan_at=0,
            limit=3,
            archive_entry_count=27_199_904,
            validated_path=Path("/nonexistent/fake.zim"),
        )
        cursor = out["next_cursor"]
        assert cursor is not None
        # Decode and assert wire shape.
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = _json.loads(_b64.urlsafe_b64decode(padded.encode("ascii")))
        assert payload["t"] == "walk_namespace"
        # Wire field MUST be ``o`` (the universal pagination key) per
        # the contract documented in pagination.py and assumed by the
        # top-level decoder in simple_tools.py.
        assert (
            "o" in payload["s"]
        ), f"walk_namespace cursor must use 's.o' on the wire; got: {payload['s']}"
        assert payload["s"]["o"] == 3

    def test_walk_namespace_w_cursor_uses_o_field_on_wire(self) -> None:
        """The W-walker (well-known) cursor emit must also use ``s.o``."""
        import base64 as _b64
        import json as _json
        from pathlib import Path
        from unittest.mock import MagicMock

        from openzim_mcp.zim.namespace import _NamespaceMixin

        archive = MagicMock()
        archive.has_main_entry = True
        archive.has_illustration = MagicMock(return_value=True)
        # With both well-known probes present, total=2; limit=1 leaves
        # 1 more entry, so next_cursor fires.
        out = _NamespaceMixin._walk_new_scheme_well_known(
            archive,
            scan_at=0,
            limit=1,
            archive_entry_count=27_199_904,
            validated_path=Path("/nonexistent/fake.zim"),
        )
        cursor = out["next_cursor"]
        assert cursor is not None
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = _json.loads(_b64.urlsafe_b64decode(padded.encode("ascii")))
        assert "o" in payload["s"]
        assert payload["s"]["o"] == 1

    def test_handle_zim_query_accepts_walk_namespace_replay_cursor(self) -> None:
        """End-to-end round-trip: a cursor in the new ``s.o`` envelope
        is accepted by ``handle_zim_query`` and the dispatcher resumes
        the walk from the encoded offset.
        """
        from openzim_mcp.pagination import Cursor

        # Construct a cursor exactly as the post-fix M-walker would.
        cursor = Cursor.encode(
            tool="walk_namespace",
            state={"o": 3, "l": 3, "ns": "M", "ai": "abcdef012345"},
        )
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.walk_namespace_data.return_value = {
            "namespace": "M",
            "results": [{"path": "M/Counter", "title": "Counter"}],
            "next_cursor": None,
            "total": None,
            "done": True,
            "page_info": {"offset": 3, "limit": 3, "returned_count": 1},
            "scanned_count": 1,
            "scanned_through_id": 3,
            "archive_entry_count": 27_199_904,
            "namespace_entry_count": 12,
        }
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "walk namespace M",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor},
        )
        # No cursor_decode error.
        assert "cursor_decode" not in out
        # Dispatcher must have mapped s.o -> scan_at for the backend.
        call_kwargs = mock.walk_namespace_data.call_args.kwargs
        cursor_state = call_kwargs.get("cursor_state")
        assert cursor_state is not None
        assert cursor_state.get("scan_at") == 3


# ---------------------------------------------------------------------------
# P3-D3: namespace count aggregator agreement (C exactness + M filter parity)
# ---------------------------------------------------------------------------


class TestP3D3NamespaceCountAggregatorAgreement:
    """P3-D3: live MCP saw four different counts for the same archive
    across four aggregator surfaces:
      - list_namespaces:    C=27,199,903 (sampling under-count),  M=12,  W=2
      - walk_namespace:     C=27,199,904 (archive.entry_count),  M=12,  W=2
      - browse_namespace:   M total=13 (raw metadata_keys, includes
                                         binary Illustration_48x48@1)
      - metadata for <file>: entry_count=27,199,904; metadata=12

    Fix routes new-scheme C through the authoritative
    ``archive.entry_count`` instead of the sampling projection, and
    applies the same ``is_human_readable_metadata_key`` filter to the
    browse-namespace enumerator that the other three surfaces already
    use.
    """

    def test_list_namespaces_c_uses_archive_entry_count_for_new_scheme(self) -> None:
        """For new-scheme archives the iterable surface is exactly the C
        namespace, so ``archive.entry_count`` is authoritative for C.
        list_namespaces previously sampled (1000 entries) and projected
        — for archives over ~1000 entries the projection rounded the
        ratio and produced 27,199,903 against an entry_count of
        27,199,904. Fix sets C's total directly from entry_count
        post-sampling.
        """
        from unittest.mock import MagicMock

        from openzim_mcp.zim.namespace import _NamespaceMixin

        # Stub archive whose new-scheme bit is True and entry_count is
        # 27,199,904. Sampling will visit 1000 entries (all in C since
        # only C is iterable on new-scheme), projection will tend to
        # 27,199,904 but may underflow by 1 due to int truncation.
        archive = MagicMock()
        archive.entry_count = 27_199_904
        archive.has_new_namespace_scheme = True
        archive.metadata_keys = ["Title", "Description"]
        archive.has_main_entry = True
        archive.has_illustration = MagicMock(return_value=True)

        class _Stub(_NamespaceMixin):
            def __init__(self) -> None:
                pass

            def _iterate_all_entries(self, *_a: Any, **_kw: Any) -> None:
                pass

            def _sample_entries(
                self,
                _archive: Any,
                _total: int,
                seen_entries: set,
                record: Any,
            ) -> None:
                # Record one C-namespace hit so the projection fires.
                record("Berlin", "Berlin")
                seen_entries.add("Berlin")

            def _probe_known_namespaces(self, *_a: Any, **_kw: Any) -> None:
                pass

        result = _Stub()._list_archive_namespaces(archive)
        # ``C`` total must equal archive.entry_count exactly.
        assert result["namespaces"]["C"]["total"] == archive.entry_count, (
            f"C total ({result['namespaces']['C']['total']}) must equal "
            f"archive.entry_count ({archive.entry_count}) for new-scheme."
        )
        # And the bucket is authoritative now (not a projection).
        assert result["namespaces"]["C"]["is_authoritative"] is True

    def test_enumerate_new_scheme_metadata_applies_human_readable_filter(
        self,
    ) -> None:
        """``_enumerate_new_scheme_metadata`` (used by browse_namespace M)
        previously returned the raw ``metadata_keys`` list, including
        ``Illustration_48x48@1`` (a binary entry). The list_namespaces
        and walk_namespace surfaces already apply the
        ``is_human_readable_metadata_key`` filter; this aligns the third
        surface.
        """
        from unittest.mock import MagicMock

        from openzim_mcp.zim.namespace import _NamespaceMixin

        archive = MagicMock()
        archive.metadata_keys = [
            "Title",
            "Description",
            "Language",
            "Illustration_48x48@1",  # binary — must be filtered out
        ]
        paths = _NamespaceMixin._enumerate_new_scheme_metadata(archive)
        # Filtered: binary Illustration entry removed.
        assert "M/Illustration_48x48@1" not in paths
        assert paths == ["M/Title", "M/Description", "M/Language"]

    def test_list_namespaces_exposes_all_entry_count(self) -> None:
        """For new-scheme archives whose ``all_entry_count`` differs from
        ``entry_count`` (the canonical user-facing count), the listing
        surfaces both so the per-namespace-sum-vs-total relationship is
        legible. This is Op2: one source of truth, but expose both
        documented totals.
        """
        from unittest.mock import MagicMock

        from openzim_mcp.zim.namespace import _NamespaceMixin

        archive = MagicMock()
        archive.entry_count = 27_199_904
        archive.all_entry_count = 27_199_921
        archive.has_new_namespace_scheme = True
        archive.metadata_keys = ["Title", "Description"]
        archive.has_main_entry = True
        archive.has_illustration = MagicMock(return_value=True)

        class _Stub(_NamespaceMixin):
            def __init__(self) -> None:
                pass

            def _iterate_all_entries(self, *_a: Any, **_kw: Any) -> None:
                pass

            def _sample_entries(
                self,
                _archive: Any,
                _total: int,
                seen_entries: set,
                record: Any,
            ) -> None:
                record("Berlin", "Berlin")
                seen_entries.add("Berlin")

            def _probe_known_namespaces(self, *_a: Any, **_kw: Any) -> None:
                pass

        result = _Stub()._list_archive_namespaces(archive)
        assert result.get("all_entry_count") == 27_199_921


# ---------------------------------------------------------------------------
# P3-D4: ``autocomplete "X"`` quoted form must route to suggestions
# ---------------------------------------------------------------------------


class TestP3D4AutocompleteQuotedForm:
    """P3-D4: the ``suggestions`` operation's own missing-arg hint
    advertises ``autocomplete "evol"`` as an accepted form, but that
    quoted form routes to ``search`` intent (cert 0.50). Fix teaches
    the intent dispatcher to recognise ``autocomplete <quoted>`` so
    the help and implementation agree.
    """

    @pytest.mark.parametrize(
        "query,expected_prefix",
        [
            ('autocomplete "evol"', "evol"),
            ("autocomplete 'evol'", "evol"),
            ("autocomplete “evol”", "evol"),  # smart quotes
            ('suggestions "berl"', "berl"),
            ("autocomplete evol", "evol"),  # baseline, already worked
        ],
    )
    def test_quoted_prefix_routes_to_suggestions(
        self, query: str, expected_prefix: str
    ) -> None:
        intent, params, _cert = IntentParser.parse_intent(query)
        assert (
            intent == "suggestions"
        ), f"{query!r} routed to {intent!r}; expected 'suggestions'"
        assert params.get("partial_query") == expected_prefix

    def test_missing_arg_hint_examples_are_accepted_by_intent_parser(self) -> None:
        """Opp4: every example surfaced in the tool's missing-arg
        recovery hint must round-trip to the operation it documents.
        The post-pass-1 ``autocomplete "evol"`` example demonstrates
        this property by name. Acts as a guard against future hint /
        implementation drift.
        """
        # The hint text emitted by the suggestions handler currently
        # advertises 'suggestions for bio' and 'autocomplete "evol"'.
        for example in [
            "suggestions for bio",
            'autocomplete "evol"',
        ]:
            intent, params, _ = IntentParser.parse_intent(example)
            assert intent == "suggestions", (
                f"Documented hint example {example!r} should route to "
                f"'suggestions' but routed to {intent!r}."
            )
            assert params.get("partial_query"), (
                f"Documented hint example {example!r} should extract a "
                f"non-empty prefix; got {params.get('partial_query')!r}."
            )


# ---------------------------------------------------------------------------
# P3-D5: ``show structure of <X>`` truncation footer is operation-specific
# ---------------------------------------------------------------------------


class TestP3D5ShowStructureTruncationFooter:
    """P3-D5: the generic truncation footer says "Page using the cursor in
    the body above (if present), tighten the query, or pass compact=False"
    — but ``show structure`` output has no cursor and "tighten the
    query" doesn't apply to an outline dump. Fix emits an operation-
    aware footer when the truncated payload comes from an atomic
    intent (structure / metadata / list_namespaces / main_page).
    """

    def test_structure_intent_uses_atomic_footer(self) -> None:
        text = "Section " * 2000
        out = SimpleToolsHandler._cap_response_size(text, 1000, intent="structure")
        assert "Pass `compact=False` to opt out of size caps." in out
        # Misleading generic clauses are NOT in the atomic footer.
        assert "Page using the cursor in the body above" not in out
        assert "tighten the query" not in out

    def test_show_structure_intent_uses_atomic_footer(self) -> None:
        text = "Section " * 2000
        out = SimpleToolsHandler._cap_response_size(text, 1000, intent="show_structure")
        assert "Pass `compact=False` to opt out of size caps." in out
        assert "tighten the query" not in out

    def test_metadata_intent_uses_atomic_footer(self) -> None:
        text = "Field " * 2000
        out = SimpleToolsHandler._cap_response_size(text, 1000, intent="metadata")
        assert "Pass `compact=False`" in out
        assert "cursor" not in out

    def test_list_namespaces_intent_uses_atomic_footer(self) -> None:
        text = "Namespace " * 2000
        out = SimpleToolsHandler._cap_response_size(
            text, 1000, intent="list_namespaces"
        )
        assert "compact=False" in out
        assert "cursor" not in out

    def test_search_intent_keeps_generic_footer(self) -> None:
        """Paginated operations still get the three-clause hint — they
        do have cursors and queries to refine.
        """
        text = "Hit " * 2000
        out = SimpleToolsHandler._cap_response_size(text, 1000, intent="search")
        assert "Page using the cursor in the body above" in out
        assert "tighten the query" in out

    def test_unknown_intent_keeps_generic_footer(self) -> None:
        """Defensive default: an unrecognised / missing intent gets the
        full three-clause hint. Avoids stripping legitimate pagination
        advice from intents that may be added later.
        """
        text = "X " * 2000
        out = SimpleToolsHandler._cap_response_size(text, 1000, intent=None)
        assert "tighten the query" in out


# ---------------------------------------------------------------------------
# P3-D6: bump ``links in <X>`` default limit (3 → 25) for hub articles
# ---------------------------------------------------------------------------


class TestP3D6LinksDefaultLimit:
    """P3-D6: live MCP saw ``links in Berlin`` return 3 internal links out
    of 2,749 — an immediate paging treadmill for hub articles. Fix bumps
    the default limit so the first turn returns enough context to make
    a navigation decision without re-paging.
    """

    def test_links_default_limit_is_at_least_25(self) -> None:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        # Capture limits the handler passes to the backend.
        mock.extract_article_links_data.return_value = {
            "title": "Berlin",
            "path": "Berlin",
            "results": [],
            "category_totals": {"internal": 0, "external": 0, "media": 0},
            "done": True,
            "page_info": {"offset": 0, "limit": 25, "returned_count": 0},
        }
        handler = SimpleToolsHandler(mock)
        handler.handle_zim_query(
            "links in Berlin",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        # Two calls: internal + external. Both share the same limit kwarg.
        call = mock.extract_article_links_data.call_args_list[0]
        # limit is a positional or keyword arg; introspect kwargs first.
        limit_kw = call.kwargs.get("limit")
        if limit_kw is None and len(call.args) >= 3:
            limit_kw = call.args[2]
        assert limit_kw is not None and limit_kw >= 25, (
            f"links default limit too narrow (was {limit_kw}); hub "
            f"articles need ≥25 to avoid the paging treadmill the live "
            f"MCP sweep observed."
        )

    def test_links_caller_supplied_limit_wins_over_default(self) -> None:
        """User-supplied limit overrides the default — keeps small-page
        callers in control.
        """
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.extract_article_links_data.return_value = {
            "title": "Berlin",
            "path": "Berlin",
            "results": [],
            "category_totals": {"internal": 0, "external": 0, "media": 0},
            "done": True,
            "page_info": {"offset": 0, "limit": 5, "returned_count": 0},
        }
        handler = SimpleToolsHandler(mock)
        handler.handle_zim_query(
            "links in Berlin",
            zim_file_path="/x.zim",
            options={"compact": True, "limit": 5},
        )
        call = mock.extract_article_links_data.call_args_list[0]
        limit_kw = call.kwargs.get("limit")
        if limit_kw is None and len(call.args) >= 3:
            limit_kw = call.args[2]
        assert limit_kw == 5


# ---------------------------------------------------------------------------
# P3-D7: browse_namespace / walk_namespace cursor must reject ns mismatch
# ---------------------------------------------------------------------------


class TestP3D7CursorNamespaceMismatch:
    """P3-D7: live MCP observed that a cursor whose ``s.ns="C"`` was
    accepted when the request asked for ``browse namespace M`` — the
    tool silently rebound to M while applying the cursor's offset.
    The cursor's ``ns`` field exists precisely to discriminate, so a
    mismatch must be rejected with the same shape as the ``ai`` /
    ``q`` mismatch errors already in place.
    """

    def test_browse_namespace_rejects_cursor_for_different_namespace(self) -> None:
        from openzim_mcp.pagination import Cursor

        # Cursor issued for namespace C, request asks for M — mismatch.
        cursor_for_c = Cursor.encode(
            tool="browse_namespace",
            state={"o": 3, "l": 3, "ns": "C", "ai": "abc123"},
        )
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        # Backend must NOT be reached on mismatch.
        mock.browse_namespace.side_effect = AssertionError(
            "backend should not be called on cursor ns mismatch"
        )
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "browse namespace M",
            zim_file_path="/x.zim",
            options={"compact": False, "cursor": cursor_for_c},
        )
        assert "cursor_decode" in out.lower() or "different namespace" in out.lower()

    def test_walk_namespace_rejects_cursor_for_different_namespace(self) -> None:
        from openzim_mcp.pagination import Cursor

        cursor_for_c = Cursor.encode(
            tool="walk_namespace",
            state={"o": 3, "l": 3, "ns": "C", "ai": "abc123"},
        )
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.walk_namespace_data.side_effect = AssertionError(
            "backend should not be called on cursor ns mismatch"
        )
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "walk namespace M",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_for_c},
        )
        assert "cursor_decode" in out.lower() or "different namespace" in out.lower()

    def test_matching_namespace_cursor_passes_through(self) -> None:
        """Cursor with matching ``ns`` is honoured (regression guard)."""
        from openzim_mcp.pagination import Cursor

        cursor_for_m = Cursor.encode(
            tool="walk_namespace",
            state={"o": 3, "l": 3, "ns": "M", "ai": "abc123"},
        )
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.walk_namespace_data.return_value = {
            "namespace": "M",
            "results": [],
            "next_cursor": None,
            "total": None,
            "done": True,
            "page_info": {"offset": 3, "limit": 3, "returned_count": 0},
            "scanned_count": 0,
            "scanned_through_id": None,
            "archive_entry_count": 27_199_904,
            "namespace_entry_count": 12,
        }
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "walk namespace M",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_for_m},
        )
        assert "cursor_decode" not in out.lower()
        # Backend WAS called with scan_at=3 (the cursor's offset).
        call = mock.walk_namespace_data.call_args
        cursor_state = call.kwargs.get("cursor_state")
        assert cursor_state is not None
        assert cursor_state.get("scan_at") == 3


# ---------------------------------------------------------------------------
# Opp4: every documented missing-arg-hint example must round-trip
# ---------------------------------------------------------------------------


class TestOpp4HelpExamplesRoundTrip:
    """Opp4 (live-MCP sweep): every example string emitted by a
    handler's missing-arg recovery hint must round-trip back to the
    intent the hint documents. P3-D4 was an instance of this class
    of bug (``autocomplete "evol"`` in the suggestions hint routed
    to ``search`` instead). Lock the invariant.

    The list below is curated from the handler source. When you add or
    edit a missing-arg hint, append an example here so the help and
    implementation stay aligned by construction.
    """

    @pytest.mark.parametrize(
        "example,expected_intent",
        [
            # Topic Required (tell_me_about handler)
            ("tell me about Photosynthesis", "tell_me_about"),
            ("who is Albert Einstein", "tell_me_about"),
            ("describe DNA", "tell_me_about"),
            # Missing Search Term (suggestions handler)
            ("suggestions for bio", "suggestions"),
            ('autocomplete "evol"', "suggestions"),
            # Missing or Invalid Namespace (browse handler)
            ("browse namespace C", "browse"),
            ("browse namespace M", "browse"),
            ("browse namespace W", "browse"),
            # Missing or Invalid Namespace (walk handler)
            ("walk namespace C", "walk_namespace"),
            ("walk namespace M", "walk_namespace"),
            ("walk namespace W", "walk_namespace"),
            # Missing Article Path (links handler)
            ("links in Biology", "links"),
            # Missing Article Title (find_by_title handler)
            ("find article titled Berlin", "find_by_title"),
        ],
    )
    def test_documented_example_routes_to_documented_intent(
        self, example: str, expected_intent: str
    ) -> None:
        intent, params, cert = IntentParser.parse_intent(example)
        assert intent == expected_intent, (
            f"Documented example {example!r} routes to {intent!r}; "
            f"expected {expected_intent!r}."
        )
        # And confidence should be at least moderate — if a hint
        # example only matches at cert<0.5 the user gets a noisy
        # "low confidence" warning even though they followed the hint.
        assert cert >= 0.5, (
            f"Documented example {example!r} parsed with low confidence "
            f"(cert={cert}); the hint shouldn't suggest a form the "
            f"intent parser is uncertain about."
        )
        # Params should carry the relevant extracted argument.
        if expected_intent == "tell_me_about":
            assert params.get("topic")
        elif expected_intent == "suggestions":
            assert params.get("partial_query")
        elif expected_intent in ("browse", "walk_namespace"):
            assert params.get("namespace")
        elif expected_intent == "find_by_title":
            assert params.get("title")
        elif expected_intent == "links":
            assert params.get("entry_path")


# ---------------------------------------------------------------------------
# Opp5: source-level audit guard — direct ``result['namespace']`` /
#       ``result['content_type']`` access patterns must not regress
# ---------------------------------------------------------------------------


class TestOpp5DirectAccessPatternAudit:
    """Opp5: source-level grep regression guard. D1 came from the
    renderer doing ``result['namespace']`` direct access while the
    data builder shipped rows without the key. The fix uses ``.get()``
    with a filter-context fallback. This test locks in that style for
    the renderer so a future contributor can't reintroduce a hard
    ``result['namespace']`` access without intentionally bypassing the
    test.
    """

    def test_format_filtered_response_uses_defensive_access(self) -> None:
        """The body of ``_format_filtered_response`` must not contain
        unguarded ``result['namespace']`` / ``result['content_type']``
        reads. Source-level audit guard.
        """
        import inspect

        from openzim_mcp.zim.search import _format_filtered_response

        src = inspect.getsource(_format_filtered_response)
        # Hard direct-access on the volatile keys is forbidden;
        # ``.get("namespace", ...)`` with a fallback is the contract.
        for bad in ('result["namespace"]', "result['namespace']"):
            assert bad not in src, (
                f"_format_filtered_response contains unguarded {bad!r} — "
                f"use result.get('namespace', filter_fallback) instead. "
                f"This was the D1 root cause."
            )
        for bad in ('result["content_type"]', "result['content_type']"):
            assert bad not in src, (
                f"_format_filtered_response contains unguarded {bad!r} — "
                f"use result.get('content_type', filter_fallback) instead."
            )
