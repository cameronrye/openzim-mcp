"""Quoting a batch of entry paths must not append the quote to each path.

The namespace lookbehind excludes the *opening* quote from the match while
the suffix class accepts the *closing* one, so ``get entries 'A/Foo' and
'A/Bar'`` reached ``get_entries`` as ``A/Foo'`` / ``A/Bar'`` and resolved to
nothing. The paths a title legitimately spells with apostrophes
(``A/Rock_'n'_Roll``) have to keep them, so the trim follows the same
balance rule the sibling paren case already uses.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from openzim_mcp.intent_parser import _extract_get_zim_entries, _trim_entry_token


class TestTrimEntryToken:
    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            ("A/Foo'", "A/Foo"),
            ("A/Mercury_(planet)'", "A/Mercury_(planet)"),
            ("A/C++'", "A/C++"),
            # Balanced apostrophes belong to the title.
            ("A/Rock_'n'_Roll", "A/Rock_'n'_Roll"),
            # ...and the quoted spelling of that same title is odd again, so
            # the closer comes off and the title's own pair survives.
            ("A/Rock_'n'_Roll'", "A/Rock_'n'_Roll"),
            # Pre-existing behaviour must not regress.
            ("A/Bar.", "A/Bar"),
            ("A/Foo)", "A/Foo"),
            ("A/Mercury_(planet)", "A/Mercury_(planet)"),
        ],
    )
    def test_trims_only_unbalanced_closers(self, token: str, expected: str) -> None:
        assert _trim_entry_token(token) == expected


class TestQuotedBatchExtraction:
    def test_single_quoted_paths_lose_the_quote(self) -> None:
        params: Dict[str, Any] = {}
        _extract_get_zim_entries("get entries 'A/Foo' and 'A/Bar'", params)
        assert params["entries"] == ["A/Foo", "A/Bar"]

    def test_quoted_disambiguated_title_keeps_its_parens(self) -> None:
        params: Dict[str, Any] = {}
        _extract_get_zim_entries("get entries 'A/Mercury_(planet)'", params)
        assert params["entries"] == ["A/Mercury_(planet)"]

    def test_apostrophe_in_the_title_survives(self) -> None:
        params: Dict[str, Any] = {}
        _extract_get_zim_entries("get entries A/Rock_'n'_Roll", params)
        assert params["entries"] == ["A/Rock_'n'_Roll"]

    def test_unquoted_batch_is_unchanged(self) -> None:
        params: Dict[str, Any] = {}
        _extract_get_zim_entries("get entries A/Foo and A/Bar", params)
        assert params["entries"] == ["A/Foo", "A/Bar"]
