"""Regression tests for the post-a11 beta-test sweep.

The post-a11 live sweep against the 118 GB Wikipedia ZIM surfaced a
mix of structural defects (regex character classes silently truncating
at the first space / ``@`` character; early-return guidance paths
bypassing the intent telemetry suffix) and behavioural defects
(``tell me about France`` returning the football-team article;
filtered search dropping the canonical title-match hit; truncation
footer mis-labelling the remaining-content count as the article
total). Each test below pins one of those failures so the same
silent fall-through can't reappear.
"""

from unittest.mock import MagicMock

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler

# ---------------------------------------------------------------------------
# Intent parser regex character class (C2 / M2)
# ---------------------------------------------------------------------------


class TestEntryPathExtractor:
    """C2 / M2: ``_extract_entry_path_keyworded`` used to capture only
    ``[A-Za-z0-9_/.-]+`` after a keyword, silently dropping spaces
    (``United States`` -> ``United``) and ``@`` (``M/Illustration_48x48@1``
    -> ``M/Illustration_48x48``). The fix takes the LAST keyword and
    captures everything that follows.
    """

    @pytest.fixture
    def parser(self):
        return IntentParser()

    def test_multi_word_title_captured_get_article(self, parser):
        intent, params, _ = parser.parse_intent("get article United States")
        assert intent == "get_article"
        assert params["entry_path"] == "United States"

    def test_multi_word_title_captured_structure(self, parser):
        intent, params, _ = parser.parse_intent("show structure of World War II")
        assert intent == "structure"
        assert params["entry_path"] == "World War II"

    def test_multi_word_title_captured_summary(self, parser):
        intent, params, _ = parser.parse_intent("summary of Albert Einstein")
        assert intent == "summary"
        assert params["entry_path"] == "Albert Einstein"

    def test_multi_word_title_captured_links(self, parser):
        intent, params, _ = parser.parse_intent("links in Albert Einstein")
        assert intent == "links"
        assert params["entry_path"] == "Albert Einstein"

    def test_at_suffix_preserved_for_metadata_path(self, parser):
        intent, params, _ = parser.parse_intent("get article M/Illustration_48x48@1")
        assert intent == "get_article"
        assert params["entry_path"] == "M/Illustration_48x48@1"

    def test_apostrophe_preserved(self, parser):
        intent, params, _ = parser.parse_intent("get article Newton's_laws")
        assert intent == "get_article"
        assert params["entry_path"] == "Newton's_laws"

    def test_table_of_contents_for_target(self, parser):
        # ``of contents for Biology`` should pick the trailing target,
        # not capture ``contents``.
        intent, params, _ = parser.parse_intent("table of contents for Biology")
        assert intent == "toc"
        assert params["entry_path"] == "Biology"

    def test_quoted_path_still_overrides_keyword_capture(self, parser):
        intent, params, _ = parser.parse_intent('get article "C/Foo bar"')
        assert intent == "get_article"
        assert params["entry_path"] == "C/Foo bar"

    def test_trailing_question_mark_stripped(self, parser):
        intent, params, _ = parser.parse_intent("get article United States?")
        assert intent == "get_article"
        assert params["entry_path"] == "United States"


# ---------------------------------------------------------------------------
# Chained-intent guidance trim (L2)
# ---------------------------------------------------------------------------


class TestChainedIntentLeftOpTrim:
    """L2: when the connector is ``then`` (not ``and then``), the left
    half of the guidance message used to leak the orphan ``and``
    (``First op (left): tell me about berlin and``). Strip dangling
    connectors so the suggested split-up call is cleanly pasteable.
    """

    @pytest.fixture
    def handler(self):
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        return SimpleToolsHandler(mock)

    def test_orphan_and_trimmed_from_left_op(self, handler):
        out = handler.handle_zim_query(
            "tell me about berlin and then list namespaces",
            zim_file_path="/x.zim",
        )
        assert "Chained Operations Detected" in out
        # No trailing "and" in the left op gist.
        assert "tell me about berlin and`" not in out
        assert "tell me about berlin`" in out
        assert "list namespaces`" in out

    def test_orphan_semicolon_trimmed(self, handler):
        out = handler.handle_zim_query(
            "tell me about berlin ; list namespaces",
            zim_file_path="/x.zim",
        )
        # The semicolon split itself; the left op is "tell me about berlin"
        # without trailing punctuation.
        if "Chained Operations Detected" in out:
            assert "tell me about berlin`" in out


# ---------------------------------------------------------------------------
# Intent telemetry on early-return guidance/error responses (L1)
# ---------------------------------------------------------------------------


class TestEarlyReturnTelemetry:
    """L1: structured guidance / error responses used to skip the
    Opp6 ``<!-- intent=... cert=... -->`` telemetry suffix that every
    article-body response carries. A calling LLM that branches on the
    comment couldn't tell why the dispatch was rejected.
    """

    @pytest.fixture
    def handler(self):
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        return SimpleToolsHandler(mock)

    def test_topic_required_carries_telemetry(self, handler):
        out = handler.handle_zim_query("tell me about ", zim_file_path="/x.zim")
        assert "**Topic Required**" in out
        assert "<!-- intent=topic_required cert=" in out

    def test_search_terms_required_carries_telemetry(self, handler):
        out = handler.handle_zim_query("search for ", zim_file_path="/x.zim")
        assert "**Search Terms Required**" in out
        assert "<!-- intent=search_terms_required cert=" in out

    def test_chained_intent_carries_telemetry(self, handler):
        out = handler.handle_zim_query(
            "tell me about berlin then list namespaces",
            zim_file_path="/x.zim",
        )
        assert "Chained Operations Detected" in out
        assert "<!-- intent=chained_intent_rejected cert=" in out

    def test_meta_only_query_carries_telemetry(self, handler):
        """Second-pass L1: ``do both`` / ``try again`` / other meta-only
        queries hit the ``_meta_query_guidance`` early return, which the
        first L1 fix missed.
        """
        out = handler.handle_zim_query("do both", zim_file_path="/x.zim")
        assert "<!-- intent=meta_only_guidance cert=" in out

    def test_empty_query_carries_telemetry(self, handler):
        """Second-pass L1: empty / whitespace queries hit the
        ``Query Required`` early return — also missed by the first
        L1 fix.
        """
        out = handler.handle_zim_query("", zim_file_path="/x.zim")
        assert "**Query Required**" in out
        assert "<!-- intent=query_required cert=" in out


# ---------------------------------------------------------------------------
# C1 sibling auto-pick: canonical-over-extends-topic (France defect)
# ---------------------------------------------------------------------------


class TestCanonicalOverExtendsTopic:
    """C1: ``tell me about France`` used to silently return
    ``France_national_football_team_results_(2000–2019)`` because
    Xapian's top hit was the football-team article and
    ``is_strong_title_match`` accepts it via the candidate-extends-
    topic rule. The canonical ``France`` article was reachable in the
    title index but the H3 probe was gated to ``len(strong_matches)
    >= 2`` cases. The fix extends the gate to fire when the lone
    strong match is an extends-topic hit, then a sibling auto-pick
    prefers the canonical.
    """

    @pytest.fixture
    def make_handler(self):
        def factory(*, search_results, title_index=None):
            mock = MagicMock()
            mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
            mock.search_zim_file_data.return_value = {"results": search_results}
            mock.get_zim_entry.return_value = "Body content for France country article."
            mock.config.meta.footer_enabled = False
            mock.find_entry_by_title_data.return_value = (
                {"results": [title_index]} if title_index else {"results": []}
            )
            mock.get_article_structure_data.return_value = {"sections": []}
            return SimpleToolsHandler(mock), mock

        return factory

    def test_france_picks_canonical_over_football_extends(self, make_handler):
        handler, _mock = make_handler(
            search_results=[
                {
                    "path": "France_national_football_team_results_(2000-2019)",
                    "title": "France national football team results (2000–2019)",
                    "score": 100,
                },
            ],
            title_index={
                "path": "France",
                "title": "France",
                "score": 1.0,
            },
        )
        out = handler.handle_zim_query(
            "tell me about France",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        # Canonical France article picked, not the football team article.
        assert "_Source: `France`_" in out
        # Football article surfaced as a "may also refer to" hint, not
        # silently dropped.
        assert "May also refer to" in out
        assert "France_national_football_team_results_(2000-2019)" in out

    def test_country_with_only_canonical_top_hit_resolves_directly(self, make_handler):
        # Germany shape: search top hit IS the country article. The
        # extends-topic gate must NOT fire here — the auto-fetch path
        # is correct.
        handler, _mock = make_handler(
            search_results=[
                {"path": "Germany", "title": "Germany", "score": 100},
            ],
            title_index={
                "path": "Germany",
                "title": "Germany",
                "score": 1.0,
            },
        )
        out = handler.handle_zim_query(
            "tell me about Germany",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "_Source: `Germany`_" in out
        # No "may also refer to" footer when the only strong match is
        # itself the canonical.
        assert "May also refer to" not in out

    def test_apollo_11_auto_resolves_canonical_with_variants_hint(self, make_handler):
        # The original C2 H3 fix prepended the canonical to the disambig
        # set; the post-a11 sibling auto-pick now picks Apollo_11
        # outright and surfaces the variants in the footer.
        handler, _mock = make_handler(
            search_results=[
                {
                    "path": "Apollo_11_anniversaries",
                    "title": "Apollo 11 anniversaries",
                    "score": 100,
                },
                {
                    "path": "Apollo_11_lunar_sample_display",
                    "title": "Apollo 11 lunar sample display",
                    "score": 90,
                },
                {
                    "path": "Apollo_11_goodwill_messages",
                    "title": "Apollo 11 goodwill messages",
                    "score": 80,
                },
            ],
            title_index={"path": "Apollo_11", "title": "Apollo 11", "score": 1.0},
        )
        out = handler.handle_zim_query(
            "tell me about Apollo 11",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "_Source: `Apollo_11`_" in out
        assert "May also refer to" in out
        assert "Apollo_11_anniversaries" in out


# ---------------------------------------------------------------------------
# H1: punctuation smear in find_title_match
# ---------------------------------------------------------------------------


class TestPunctuationSmearGuard:
    """H1: title-index lookups for topics containing load-bearing
    punctuation (``+``, ``#``, etc.) silently smeared to candidates
    that dropped the punctuation entirely. Live failure: ``get
    article C++`` resolved to the letter ``C`` (paired with the M2
    regex fix that now actually preserves ``++`` through extraction,
    this guard then rejects the title-index probe's letter match).

    Known limitation: the libzim title index also maps ``C++`` to
    ``C/C++`` — both retain 2 ``+`` chars, so the count-based guard
    can't detect the second smear shape. That deeper case requires
    redirect-target inspection, deferred for a later fix.
    """

    def test_punctuation_smear_detected_drops_plus(self):
        from openzim_mcp.title_promotion import _punctuation_smear_detected

        # Topic has 2 ``+``, candidate has 0 — smear detected.
        assert _punctuation_smear_detected("C++", "C") is True
        assert _punctuation_smear_detected("F#", "F") is True

    def test_punctuation_smear_clean_passes(self):
        from openzim_mcp.title_promotion import _punctuation_smear_detected

        # Newton's_laws -> Newton's_laws_of_motion preserves apostrophe;
        # apostrophe isn't currently in the load-bearing list anyway.
        assert (
            _punctuation_smear_detected("Newton's laws", "Newton's_laws_of_motion")
            is False
        )
        # No punctuation at all in topic — never trips the guard.
        assert _punctuation_smear_detected("Berlin", "Berlin") is False
        assert _punctuation_smear_detected("Berlin", "Berlin_Wall") is False
        # Same punctuation count on both sides — passes.
        assert _punctuation_smear_detected("C++", "C++_programming_language") is False

    def test_find_title_match_rejects_smear(self):
        from openzim_mcp.title_promotion import find_title_match

        mock = MagicMock()
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {"path": "C", "title": "C", "score": 1.0},
            ]
        }
        # Topic has 2 ``+``, candidate has 0 — smear detected, returns None.
        result = find_title_match(mock, "/x.zim", "C++")
        assert result is None

    def test_find_title_match_accepts_clean_match(self):
        from openzim_mcp.title_promotion import find_title_match

        mock = MagicMock()
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {"path": "Berlin", "title": "Berlin", "score": 1.0},
            ]
        }
        result = find_title_match(mock, "/x.zim", "Berlin")
        assert result is not None
        assert result["path"] == "Berlin"


# ---------------------------------------------------------------------------
# M1: shared metadata-key filter (walk M / metadata-for agreement)
# ---------------------------------------------------------------------------


class TestMetadataKeyFilter:
    """M1: ``walk namespace M`` reported 13 entries (incl. binary
    illustration) while ``metadata for <file>`` reported 12 (filtered
    illustration). The shared
    :func:`is_human_readable_metadata_key` filter pins agreement.
    """

    def test_illustration_keys_filtered(self):
        from openzim_mcp.zim.namespace import is_human_readable_metadata_key

        assert is_human_readable_metadata_key("Illustration_48x48@1") is False
        assert is_human_readable_metadata_key("Illustration_96x96@1") is False

    def test_text_metadata_keys_kept(self):
        from openzim_mcp.zim.namespace import is_human_readable_metadata_key

        for key in (
            "Title",
            "Description",
            "Language",
            "Date",
            "Counter",
            "Tags",
            "Scraper",
        ):
            assert is_human_readable_metadata_key(key) is True


# ---------------------------------------------------------------------------
# M4: truncation footer wording stable across pagination
# ---------------------------------------------------------------------------


class TestTruncationFooterWording:
    """M4: at offset N>0 the footer used to say "total of M characters"
    where M was actually the post-slice remaining length. A user
    paging through a 146 KB article saw the "total" decrease with
    every page. The fix takes ``original_total`` from the caller so
    the denominator stays stable.
    """

    @pytest.fixture
    def cp(self, tmp_path):
        from openzim_mcp.config import OpenZimMcpConfig
        from openzim_mcp.content_processor import ContentProcessor

        config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)])
        return ContentProcessor(config)

    def test_initial_page_total_uses_original_length(self, cp):
        body = "x" * 10000
        out = cp.truncate_content(body, 4000, current_offset=0, original_total=10000)
        assert "total of 10,000 characters" in out
        assert "showing first 4,000" in out

    def test_paginated_page_uses_chars_x_y_of_z_wording(self, cp):
        # Caller already sliced [4000:] so passes the post-slice body.
        body = "y" * 6000
        out = cp.truncate_content(body, 4000, current_offset=4000, original_total=10000)
        # Denominator stays the article's true length, not 6000.
        assert "of 10,000-char body" in out
        assert "chars 4,000" in out  # en-dash variants are platform-dependent

    def test_fallback_when_original_total_missing(self, cp):
        body = "z" * 6000
        # Without original_total we approximate as len(content) +
        # current_offset, which still beats the prior "len(content)"
        # under-report.
        out = cp.truncate_content(body, 4000, current_offset=4000)
        assert "of 10,000-char body" in out


# ---------------------------------------------------------------------------
# L3: canonical-title-match snippet rendered as a badge
# ---------------------------------------------------------------------------


class TestCanonicalTitleMatchBadge:
    """L3: the canonical-title-match splice injects a synthetic row
    whose ``snippet`` is the literal sentinel ``(canonical title
    match)``. Rendering that as a snippet line confused callers; the
    fix surfaces it as a distinct ``Match type:`` badge so the
    sentinel doesn't pipe into snippet processing downstream.
    """

    def test_format_search_text_renders_badge_for_canonical_row(self):
        from openzim_mcp.zim.search import _SearchMixin

        # Build a minimal payload with one canonical splice row
        # alongside a normal hit.
        payload = {
            "query": "berlin",
            "results": [
                {
                    "path": "Berlin",
                    "title": "Berlin",
                    "snippet": "(canonical title match)",
                },
                {
                    "path": "Berlin_Wall",
                    "title": "Berlin Wall",
                    "snippet": "The Berlin Wall was a guarded concrete...",
                },
            ],
            "total": 2,
            "done": True,
            "next_cursor": None,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 2},
        }
        # Use the unbound method on _SearchMixin via a type ignore
        # since the formatter doesn't touch ``self``.
        out = _SearchMixin._format_search_text(None, payload)  # type: ignore[arg-type]
        assert "Match type: canonical title match" in out
        assert "Snippet: The Berlin Wall" in out
        # The sentinel string itself isn't rendered as snippet text.
        assert "Snippet: (canonical title match)" not in out
