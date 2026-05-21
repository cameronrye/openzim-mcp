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
