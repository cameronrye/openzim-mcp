"""A bundle cached by the previous release must not be re-served by this one.

``EntryBundle`` stores the extracted ``sections`` list, and pass 5 (1e1bd8e)
changed what goes into it: headings that the locator previously failed to find
— an H1 whose title is italicised, a heading split by a ``<br>`` — now yield
sections. The bundle cache key is ``bundle:<prefix>:<path>:<mtime>:<size>:
<entry>:<mode>``, and none of those components changes when the *code* that
builds the bundle changes.

So an operator running with ``persistence_enabled`` who upgrades from 2.7.0
restores a snapshot whose bundles were built by the pre-fix extractor, and
``get_or_build_bundle`` returns them verbatim with no revalidation. Every
affected article keeps reporting ``heading_count: 0`` for the full cache TTL
after the upgrade — the release's headline fix silently inert on exactly the
entries it was written for.

The codebase already establishes the remedy: the comment above
``_BUNDLE_KEY_PREFIX`` records that the v2c -> v2d bump existed because a fix
would otherwise "silently keep serving the child heading until TTL expiry
without the key bump". Pass 5 changed bundle contents and did not bump it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openzim_mcp.bundle import _BUNDLE_KEY_PREFIX, _bundle_cache_key
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

# The prefix in use up to and including 2.7.0, i.e. while the heading locator
# still dropped italicised-H1 and <br>-split headings.
_PRE_FIX_PREFIX = "bundle:v2d"
_ITALIC_H1_ENTRY = "A/2040_(film)"


def test_prefix_advanced_past_the_pre_fix_release() -> None:
    """Content-changing fixes must invalidate, not inherit."""
    assert _BUNDLE_KEY_PREFIX != _PRE_FIX_PREFIX, (
        "pass 5 changed what EntryBundle.sections contains but left the cache "
        "key prefix alone, so a persisted 2.7.0 snapshot re-serves pre-fix "
        "bundles after upgrade"
    )


@pytest.fixture
def server_and_zim(real_content_zim_files):
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("wikipedia climate corpus archive not available")
    config = OpenZimMcpConfig(allowed_directories=[str(zim.parent)])
    return OpenZimMcpServer(config), Path(zim).resolve()


def test_a_pre_fix_bundle_is_not_served(server_and_zim) -> None:
    """Seed the old key with a pre-fix bundle; the fix must still apply."""
    server, zim = server_and_zim
    ops = server.zim_operations

    fresh = ops.get_table_of_contents_data(str(zim), _ITALIC_H1_ENTRY)
    assert fresh.get("heading_count") == 1, fresh

    # Rebuild the exact key a 2.7.0 process would have written, and store the
    # bundle its extractor would have produced (the heading was dropped).
    current_key = _bundle_cache_key(zim, _ITALIC_H1_ENTRY, True)
    legacy_key = current_key.replace(_BUNDLE_KEY_PREFIX, _PRE_FIX_PREFIX, 1)
    cached = server.cache.get(current_key)
    assert cached is not None, "expected the read above to populate the cache"
    stale = dict(cached)
    stale["sections"] = []
    server.cache.set(legacy_key, stale)
    server.cache.delete(current_key)

    again = ops.get_table_of_contents_data(str(zim), _ITALIC_H1_ENTRY)
    assert again.get("heading_count") == 1, (
        "a bundle stored under the previous release's key prefix was re-served, "
        "so the heading fix is inert after an upgrade"
    )
