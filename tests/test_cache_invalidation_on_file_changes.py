"""Cache must reflect runtime ZIM file changes (issue #307).

Two distinct staleness classes are covered here:

1. **Directory listing** — ``list_zim_files_data`` caches the result of
   scanning the allowed directories. When a ``.zim`` file is added or removed
   at runtime (the common Kubernetes / shared-volume case from issue #307),
   the cached listing must reflect the change rather than serving the prior
   snapshot until the TTL expires or the server restarts.

2. **Per-file content caches** — anything derived from a single archive's
   contents (metadata, namespace listings, main page, search, suggestions)
   must invalidate when that archive is replaced in place at the same path
   (an atomic same-name swap, e.g. a stable ``wikipedia.zim`` symlink that is
   re-pointed). The codebase's :func:`openzim_mcp.bundle.archive_stat_token`
   contract requires these keys to embed an ``<mtime_ns>:<size>`` token; this
   module pins that requirement for the caches that previously omitted it.
"""

from pathlib import Path

import pytest

from openzim_mcp.bundle import archive_stat_token as _stat
from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def zim_operations(
    test_config: OpenZimMcpConfig,
    path_validator: PathValidator,
    openzim_mcp_cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
) -> ZimOperations:
    """A ZimOperations wired to the shared in-memory cache fixture."""
    return ZimOperations(
        test_config, path_validator, openzim_mcp_cache, content_processor
    )


class TestDirectoryListingFreshness:
    """``list_zim_files_data`` must track add/remove without a restart."""

    def test_added_file_is_visible_without_restart(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """A ``.zim`` added after the first scan must appear on the next call."""
        (temp_dir / "alpha.zim").write_text("alpha")

        first = zim_operations.list_zim_files_data()
        assert {f["name"] for f in first} == {"alpha.zim"}

        # New archive dropped into the allowed dir while the server runs.
        (temp_dir / "beta.zim").write_text("beta")

        second = zim_operations.list_zim_files_data()
        assert {f["name"] for f in second} == {"alpha.zim", "beta.zim"}, (
            "Newly added .zim must be listed without waiting for the cache "
            "TTL or a server restart (issue #307)."
        )

    def test_removed_file_disappears_without_restart(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """A ``.zim`` removed after the first scan must drop off the next call."""
        (temp_dir / "alpha.zim").write_text("alpha")
        (temp_dir / "beta.zim").write_text("beta")

        first = zim_operations.list_zim_files_data()
        assert {f["name"] for f in first} == {"alpha.zim", "beta.zim"}

        (temp_dir / "beta.zim").unlink()

        second = zim_operations.list_zim_files_data()
        assert {f["name"] for f in second} == {"alpha.zim"}, (
            "Removed .zim must disappear from the listing without waiting for "
            "the cache TTL or a server restart (issue #307)."
        )

    def test_unchanged_directory_still_serves_from_cache(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """When nothing changes, the listing must still be cache-served.

        The fix must not turn every call into a full rescan: a repeat call
        against an unchanged directory should hit the cache (one stored entry,
        a recorded hit).
        """
        (temp_dir / "alpha.zim").write_text("alpha")

        zim_operations.list_zim_files_data()
        hits_before = zim_operations.cache.stats()["hits"]
        zim_operations.list_zim_files_data()
        hits_after = zim_operations.cache.stats()["hits"]

        assert (
            hits_after > hits_before
        ), "An unchanged directory must be served from cache, not rescanned."


# Per-cache contract: each content-derived cache key must embed the
# ``archive_stat_token`` so an in-place same-path archive replacement (a
# monthly refresh behind a stable filename) is seen as a miss rather than
# served stale. Each case names the buggy *path-only* key the cache used
# before the fix and the *token-bearing* key it must use after. Poisoning
# both and asserting the method returns the token-keyed value pins the
# contract without opening a real archive (the cache hit short-circuits
# before libzim is ever touched).
#
# Each entry: (id, call(zim_operations, path), old_key(vp), new_key(vp, token)).
_CONTENT_CACHE_CASES = [
    (
        "metadata_data",
        lambda zo, p: zo.get_zim_metadata_data(p),
        lambda vp: f"metadata_data:v2c:{vp}",
        lambda vp, tok: f"metadata_data:v2c:{vp}:{tok}",
    ),
    (
        "namespaces_data",
        lambda zo, p: zo.list_namespaces_data(p),
        lambda vp: f"namespaces_data:v2b:{vp}",
        lambda vp, tok: f"namespaces_data:v2b:{vp}:{tok}",
    ),
    (
        "main_page",
        lambda zo, p: zo.get_main_page(p, compact=False),
        lambda vp: f"main_page:{vp}:compact=False",
        lambda vp, tok: f"main_page:{vp}:{tok}:compact=False",
    ),
    (
        "main_page_data",
        lambda zo, p: zo.get_main_page_data(p, compact=False),
        lambda vp: f"main_page_data:{vp}:compact=False",
        lambda vp, tok: f"main_page_data:{vp}:{tok}:compact=False",
    ),
    (
        "browse_ns_data",
        lambda zo, p: zo.browse_namespace_data(p, "A", 50, 0),
        lambda vp: f"browse_ns_data:v2d:{vp}:A:50:0:assets=False",
        lambda vp, tok: f"browse_ns_data:v2d:{vp}:{tok}:A:50:0:assets=False",
    ),
    (
        # An explicit limit is passed so the key is not affected by the
        # ``limit is None -> default_search_limit`` resolution these methods do.
        "search_v2b",
        lambda zo, p: zo.search_zim_file_data(p, "test", 5, 0),
        lambda vp: f"search_v2b:{vp}:test:5:0",
        lambda vp, tok: f"search_v2b:{vp}:{tok}:test:5:0",
    ),
    (
        "search_filtered",
        lambda zo, p: zo.search_with_filters(p, "test", limit=5),
        lambda vp: f"search_filtered:{vp}:test:None:None:5:0:dq=",
        lambda vp, tok: f"search_filtered:{vp}:{tok}:test:None:None:5:0:dq=",
    ),
    (
        "search_filtered_v2b",
        lambda zo, p: zo.search_with_filters_data(p, "test", limit=5),
        lambda vp: f"search_filtered_v2b:{vp}:test:None:None:5:0",
        lambda vp, tok: f"search_filtered_v2b:{vp}:{tok}:test:None:None:5:0",
    ),
    (
        "suggestions_data",
        lambda zo, p: zo.get_search_suggestions_data(p, "te", 10),
        lambda vp: f"suggestions_data:v2b:{vp}:te:10",
        lambda vp, tok: f"suggestions_data:v2b:{vp}:{tok}:te:10",
    ),
    (
        # Entry content/response caches: an explicit max_content_length keeps
        # the key clear of the ``None -> default`` resolution.
        "entry",
        lambda zo, p: zo.get_zim_entry(p, "A/Test", 1000, 0),
        lambda vp: f"entry:{vp}:A/Test:1000:0:compact=False",
        lambda vp, tok: f"entry:{vp}:{tok}:A/Test:1000:0:compact=False",
    ),
    (
        "entry_data",
        lambda zo, p: zo.get_zim_entry_data(p, "A/Test", 1000, 0),
        lambda vp: f"entry_data:{vp}:A/Test:1000:0:compact=False",
        lambda vp, tok: f"entry_data:{vp}:{tok}:A/Test:1000:0:compact=False",
    ),
]


class TestContentCacheReplacementInvalidation:
    """Content-derived caches must key by ``archive_stat_token`` (in-place swap)."""

    @pytest.mark.parametrize(
        "case_id, call, old_key, new_key",
        _CONTENT_CACHE_CASES,
        ids=[c[0] for c in _CONTENT_CACHE_CASES],
    )
    def test_stat_token_key_invalidates_on_in_place_replacement(
        self,
        zim_operations: ZimOperations,
        temp_dir: Path,
        case_id: str,
        call,
        old_key,
        new_key,
    ):
        """End-to-end: a real same-path replacement must serve fresh data.

        Two phases, both hermetic (cache hits short-circuit before any real
        archive is opened):

        1. **Reads the token key** — with both the path-only key and the
           token-bearing key populated, the method must return the
           token-keyed value. A path-only key would survive a replacement and
           serve stale data forever (until TTL/restart).
        2. **Invalidates on a real change** — after actually rewriting the
           file at the same path (new size/mtime → new stat token → new key),
           the method must route to the *new* token's entry, not the now-stale
           v1 one. This exercises the real invalidation, not just the key
           shape. See :func:`openzim_mcp.bundle.archive_stat_token`.
        """
        zim_file = temp_dir / "archive.zim"
        zim_file.write_bytes(b"v1 content")
        validated = zim_operations._validate_zim_path(str(zim_file))
        token = _stat(validated)

        # Phase 1: with both keys populated, the method must read the
        # token-bearing key (never opening a real archive).
        stale = f"STALE::{case_id}"
        fresh = f"FRESH::{case_id}"
        zim_operations.cache.set(old_key(validated), stale)
        zim_operations.cache.set(new_key(validated, token), fresh)

        result = call(zim_operations, str(zim_file))
        assert result == fresh, (
            f"{case_id}: cache key must embed archive_stat_token so an "
            f"in-place archive replacement invalidates it; got the path-only "
            f"(stale-prone) entry instead."
        )

        # Phase 2: replace the archive in place. Growing the file guarantees
        # the stat token changes regardless of mtime resolution, so the v1
        # entry ('fresh') is now stale and the method must serve the entry
        # keyed by the *new* token.
        zim_file.write_bytes(b"v2 content, deliberately longer than v1")
        token2 = _stat(validated)
        assert token2 != token, "premise: a same-path rewrite must change the token"
        fresh2 = f"FRESH2::{case_id}"
        zim_operations.cache.set(new_key(validated, token2), fresh2)

        result2 = call(zim_operations, str(zim_file))
        assert result2 == fresh2, (
            f"{case_id}: an in-place archive replacement must invalidate the "
            f"cached entry (route to the new stat-token key), not serve v1."
        )
