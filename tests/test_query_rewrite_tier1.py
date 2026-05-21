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
