"""A cache persisted by 2.7.0 must not re-serve pre-3.0.0 renderings.

The ``entry:`` response-cache key carried an archive stat token but no
version, so it invalidated when the ARCHIVE changed and never when the
server's rendering of an unchanged archive changed. 3.0.0 changes that
rendering in three separate ways — the empty ``M/<key>`` fallback, the
page-boundary whitespace fix, and ``_meta.more_at_offset`` — so an operator
upgrading with ``persistence_enabled`` kept being served the old value until
the TTL expired, with each fix inert on exactly the entries it was written
for.
"""

from __future__ import annotations

import re
from pathlib import Path

_CONTENT = Path("openzim_mcp/zim/content.py").read_text(encoding="utf-8")
_NAMESPACE = Path("openzim_mcp/zim/namespace.py").read_text(encoding="utf-8")

_ENTRY_KEYS = re.findall(r'f"entry:[^"]*"', _CONTENT)


def test_both_entry_cache_keys_are_versioned() -> None:
    assert len(_ENTRY_KEYS) == 2, _ENTRY_KEYS
    for key in _ENTRY_KEYS:
        assert re.match(r'^f"entry:v\d+:', key), key


def test_the_two_entry_keys_are_byte_identical() -> None:
    """Their comments already require it: a divergence silently halves the
    cache and lets one call path serve what the other invalidated."""
    assert _ENTRY_KEYS[0] == _ENTRY_KEYS[1], _ENTRY_KEYS


def test_entry_key_is_not_the_unversioned_2_7_0_spelling() -> None:
    assert 'f"entry:{validated_path}' not in _CONTENT


def test_browse_namespace_key_moved_past_the_2_7_0_spelling() -> None:
    """``scanned_count`` joined the new-scheme W payload this release."""
    assert "browse_ns_data:v2d:" not in _NAMESPACE
    assert re.search(r'f"browse_ns_data:v\d+[a-z]?:', _NAMESPACE), "no versioned key"
