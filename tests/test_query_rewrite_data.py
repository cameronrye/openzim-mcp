"""Tests for query_rewrite_data — bundled misspelling map + exclusions loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from openzim_mcp.query_rewrite_data import (
    load_exclusions,
    load_misspellings,
)


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    load_misspellings.cache_clear()
    load_exclusions.cache_clear()


class TestLoadMisspellings:
    def test_bundled_default_loads(self) -> None:
        mapping = load_misspellings(None)
        assert isinstance(mapping, dict)
        # Sanity check a known seed entry
        assert mapping.get("recieve") == "receive"
        assert mapping.get("photosythesis") == "photosynthesis"

    def test_keys_and_values_are_lowercase(self) -> None:
        mapping = load_misspellings(None)
        for k, v in mapping.items():
            assert k == k.lower(), f"key {k!r} should be lowercase"
            assert v == v.lower(), f"value {v!r} should be lowercase"

    def test_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "m.txt"
        f.write_text(
            "# this is a comment\n"
            "\n"
            "foo=bar\n"
            "   # leading whitespace comment\n"
            "baz=qux\n"
        )
        mapping = load_misspellings(f)
        assert mapping == {"foo": "bar", "baz": "qux"}

    def test_malformed_lines_are_skipped(self, tmp_path: Path) -> None:
        # Lines without `=` are silently skipped (defensive: a malformed
        # file shouldn't blow up the server at import time).
        f = tmp_path / "m.txt"
        f.write_text("foo=bar\nNOT_A_PAIR\nbaz=qux\n")
        mapping = load_misspellings(f)
        assert mapping == {"foo": "bar", "baz": "qux"}

    def test_hard_cap_enforced(self, tmp_path: Path) -> None:
        # Cap at 500 entries; anything beyond is dropped with a warning.
        f = tmp_path / "m.txt"
        f.write_text("\n".join(f"k{i}=v{i}" for i in range(600)))
        mapping = load_misspellings(f)
        assert len(mapping) == 500

    def test_caches_per_path(self, tmp_path: Path) -> None:
        f = tmp_path / "m.txt"
        f.write_text("foo=bar\n")
        a = load_misspellings(f)
        b = load_misspellings(f)
        assert a is b  # lru_cache should return the same object


class TestLoadExclusions:
    def test_bundled_default_loads_as_set(self) -> None:
        excl = load_exclusions(None)
        assert isinstance(excl, frozenset)

    def test_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "e.txt"
        f.write_text("# header\nbilogy\n\n   # indented comment\nphotosythesis\n")
        excl = load_exclusions(f)
        assert excl == frozenset({"bilogy", "photosythesis"})

    def test_lowercased(self, tmp_path: Path) -> None:
        f = tmp_path / "e.txt"
        f.write_text("FooBar\nBAZ\n")
        excl = load_exclusions(f)
        assert excl == frozenset({"foobar", "baz"})
