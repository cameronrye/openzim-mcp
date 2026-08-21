"""A cache persisted by 2.7.0 must not re-serve pre-3.0.0 suggestion payloads.

3.0.0 changes what ``_generate_search_suggestions`` produces: the
canonical-suggestion probe's Strategy B now takes the minimum over ALL
prefix matches and declines when the shortest title is already on the page,
where 2.7.0 could promote the next-shortest title above the canonical and
trim a genuine suggestion off the end. The ``suggestions_data`` key embeds
an archive stat token, but the archive did not change — so an operator
upgrading with ``persistence_enabled`` kept being served the wrongly
promoted payloads until TTL expiry, with the fix inert on exactly the
cached queries it was written for. Same shape, same rule as the
``entry:v3`` and ``browse_ns_data:v2e`` bumps this release already made:
a change to what a payload contains needs a new prefix.
"""

from __future__ import annotations

import re
from pathlib import Path

_SEARCH = Path("openzim_mcp/zim/search.py").read_text(encoding="utf-8")


def test_suggestions_key_moved_past_the_2_7_0_spelling() -> None:
    assert "suggestions_data:v2b:" not in _SEARCH


def test_suggestions_key_is_versioned() -> None:
    assert re.search(r'f"suggestions_data:v\d+[a-z]?:', _SEARCH), "no versioned key"
