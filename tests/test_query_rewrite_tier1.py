"""Sub-D-2: Tier 1 query rewriting rules.

Per-rule unit tests with three sides each:
- Fix side: input that SHOULD rewrite
- No-op side: input that should pass through unchanged
- Boundary side: looks like a rewrite target but isn't
"""

from __future__ import annotations

from typing import Callable, Optional  # noqa: F401 — used by Tasks 4-5

import pytest  # noqa: F401 — used by test decorators

from openzim_mcp.intent_parser import IntentParser


class TestNormalizeTopicCase:
    def test_lowercases_uppercase_input(self) -> None:
        assert IntentParser._normalize_topic_case("BERLIN") == "berlin"

    def test_lowercases_mixed_case(self) -> None:
        assert IntentParser._normalize_topic_case("BeRlIn") == "berlin"

    def test_already_lowercase_is_no_op(self) -> None:
        assert IntentParser._normalize_topic_case("berlin") == "berlin"

    def test_empty_string_passes_through(self) -> None:
        assert IntentParser._normalize_topic_case("") == ""

    def test_whitespace_preserved(self) -> None:
        assert IntentParser._normalize_topic_case("Berlin Germany") == "berlin germany"

    def test_idempotent(self) -> None:
        # Running twice produces the same output as running once.
        once = IntentParser._normalize_topic_case("BERLIN")
        twice = IntentParser._normalize_topic_case(once)
        assert once == twice == "berlin"


class TestApplyMisspellingMap:
    def test_substitutes_known_misspelling_without_probe(self) -> None:
        # Probe omitted → substitute (degraded mode).
        result = IntentParser._apply_misspelling_map(
            "recieve a letter", title_probe=None
        )
        assert result == "receive a letter"

    def test_leaves_unknown_word_alone(self) -> None:
        result = IntentParser._apply_misspelling_map("berlin germany", title_probe=None)
        assert result == "berlin germany"

    def test_already_correct_passes_through(self) -> None:
        result = IntentParser._apply_misspelling_map(
            "receive a letter", title_probe=None
        )
        assert result == "receive a letter"

    def test_probe_suppresses_substitution_when_canonical_hit(self) -> None:
        # Probe returns True → suppress (the original token is a real entity).
        seen: list[str] = []

        def probe(token: str) -> bool:
            seen.append(token)
            return True  # always says "yes, canonical hit"

        result = IntentParser._apply_misspelling_map(
            "recieve a letter", title_probe=probe
        )
        # Substitution suppressed because the probe claimed the original
        # is a canonical title.
        assert result == "recieve a letter"
        assert "recieve" in seen

    def test_probe_allows_substitution_when_no_canonical_hit(self) -> None:
        def probe(token: str) -> bool:
            return False

        result = IntentParser._apply_misspelling_map(
            "recieve a letter", title_probe=probe
        )
        assert result == "receive a letter"

    def test_multiple_substitutions_in_one_query(self) -> None:
        result = IntentParser._apply_misspelling_map(
            "recieve and seperate", title_probe=None
        )
        assert result == "receive and separate"

    def test_exclusions_block_substitution(self, tmp_path, monkeypatch) -> None:
        # Temporarily swap in an exclusions file with `recieve` listed.
        excl = tmp_path / "excl.txt"
        excl.write_text("recieve\n")
        from openzim_mcp import query_rewrite_data

        query_rewrite_data.load_exclusions.cache_clear()
        monkeypatch.setattr(
            IntentParser,
            "_exclusions_path",
            excl,
            raising=False,
        )
        result = IntentParser._apply_misspelling_map(
            "recieve a letter", title_probe=None
        )
        # Even though `recieve` is in the map, the exclusion wins.
        assert result == "recieve a letter"
        query_rewrite_data.load_exclusions.cache_clear()

    def test_idempotent(self) -> None:
        once = IntentParser._apply_misspelling_map("recieve", title_probe=None)
        twice = IntentParser._apply_misspelling_map(once, title_probe=None)
        assert once == twice == "receive"

    def test_preserves_inter_word_whitespace(self) -> None:
        # Multiple spaces between words should be preserved (don't
        # silently collapse — that's a different rule's job).
        result = IntentParser._apply_misspelling_map(
            "recieve  a  letter", title_probe=None
        )
        assert result == "receive  a  letter"


class TestDetectStopwordPhrase:
    def test_strips_leading_the_without_probe(self) -> None:
        # No probe → strip (degraded mode favors cleaner query).
        result = IntentParser._detect_stopword_phrase(
            "the population of berlin", title_probe=None
        )
        assert result == "population of berlin"

    def test_strips_leading_a(self) -> None:
        result = IntentParser._detect_stopword_phrase(
            "a list of countries", title_probe=None
        )
        assert result == "list of countries"

    def test_strips_leading_an(self) -> None:
        result = IntentParser._detect_stopword_phrase("an apple tree", title_probe=None)
        assert result == "apple tree"

    def test_strips_leading_of(self) -> None:
        result = IntentParser._detect_stopword_phrase(
            "of mice and men", title_probe=None
        )
        # No probe → strip (we miss this is a real title; that's the
        # degraded-mode tradeoff documented in the spec).
        assert result == "mice and men"

    def test_no_leading_article_is_no_op(self) -> None:
        result = IntentParser._detect_stopword_phrase(
            "population of berlin", title_probe=None
        )
        assert result == "population of berlin"

    def test_probe_keeps_canonical_title(self) -> None:
        # Probe returns True for the full query → keep article.
        def probe(token: str) -> bool:
            return token == "the beatles"

        result = IntentParser._detect_stopword_phrase("the beatles", title_probe=probe)
        assert result == "the beatles"

    def test_probe_strips_when_no_canonical(self) -> None:
        def probe(token: str) -> bool:
            return False

        result = IntentParser._detect_stopword_phrase(
            "the population of berlin", title_probe=probe
        )
        assert result == "population of berlin"

    def test_only_one_probe_call_per_query(self) -> None:
        call_count = [0]

        def probe(token: str) -> bool:
            call_count[0] += 1
            return False

        IntentParser._detect_stopword_phrase(
            "the population of berlin", title_probe=probe
        )
        assert call_count[0] == 1

    def test_idempotent(self) -> None:
        once = IntentParser._detect_stopword_phrase("the population", title_probe=None)
        twice = IntentParser._detect_stopword_phrase(once, title_probe=None)
        assert once == twice == "population"

    def test_case_insensitive_article_detection(self) -> None:
        # Sub-D-2 typically runs after rule 1, but the rule itself
        # should still handle uppercase input correctly.
        result = IntentParser._detect_stopword_phrase(
            "The Population", title_probe=None
        )
        assert result == "Population"


class TestDecomposeXOfY:
    def test_x_of_y_matches(self) -> None:
        text, hint = IntentParser._decompose_x_of_y("population of berlin")
        assert text == "berlin population"
        assert hint == {"entity": "berlin", "attribute": "population"}

    def test_possessive_matches(self) -> None:
        text, hint = IntentParser._decompose_x_of_y("berlin's population")
        assert text == "berlin population"
        assert hint == {"entity": "berlin", "attribute": "population"}

    def test_no_match_returns_unchanged_and_none(self) -> None:
        text, hint = IntentParser._decompose_x_of_y("just a regular query")
        assert text == "just a regular query"
        assert hint is None

    def test_multi_word_entity_in_of_form(self) -> None:
        text, hint = IntentParser._decompose_x_of_y("capital of new south wales")
        assert text == "new south wales capital"
        assert hint == {
            "entity": "new south wales",
            "attribute": "capital",
        }

    def test_idempotent(self) -> None:
        once_text, once_hint = IntentParser._decompose_x_of_y("population of berlin")
        twice_text, twice_hint = IntentParser._decompose_x_of_y(once_text)
        # Second pass produces no hint (already rewritten); text is stable.
        assert once_text == twice_text == "berlin population"
        assert once_hint is not None
        assert twice_hint is None

    def test_of_form_requires_attr_to_be_single_word(self) -> None:
        # Reject "annual revenue of Berlin" so we don't mis-decompose
        # multi-word attributes (a deferred Tier 2 / sub-D-3 concern).
        text, hint = IntentParser._decompose_x_of_y("annual revenue of berlin")
        assert text == "annual revenue of berlin"
        assert hint is None

    def test_possessive_requires_single_word_attr(self) -> None:
        # Same: "berlin's annual revenue" stays a search.
        text, hint = IntentParser._decompose_x_of_y("berlin's annual revenue")
        assert text == "berlin's annual revenue"
        assert hint is None
