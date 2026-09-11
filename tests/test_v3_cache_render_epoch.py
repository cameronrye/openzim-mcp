"""Content-derived cache keys must move when this server's rendering moves.

``archive_stat_token`` invalidates a cached value when the ARCHIVE is
replaced. Nothing invalidated it when the SERVER changed what it renders
from an unchanged archive — and 3.0.1 does exactly that: ``noscript``
stripping, in-page-nav stripping and duplicate-anchor ``section_id``
disambiguation all alter the cached ``EntryBundle``, the cached entry text
and the cached snippet render. An operator running with
``persistence_enabled`` restores a snapshot written by 3.0.0 and keeps being
served the pre-fix rendering — including duplicate ``section_id``s that
``zim_get_section`` cannot resolve, since ``section_id`` is a fetch handle —
until the TTL expires. Every fix inert on precisely the entries it was
written for.

The remedy is a render epoch inside the stat token, so it reaches every key
that already embeds the token by contract rather than only the keys whose
author remembered a prefix bump. These tests pin the mechanism: the shape of
the token, the three key families that carry it, and a fingerprint of the
rendering those caches hold, so a future rendering change cannot land
without bumping the epoch.
"""

from __future__ import annotations

import ast
import hashlib
import json
from contextlib import suppress
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from openzim_mcp.bundle import (
    _BUNDLE_KEY_PREFIX,
    _RENDER_EPOCH,
    _bundle_cache_key,
    _compute_section_offsets,
    archive_stat_token,
)
from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import (
    ContentProcessor,
    _build_headings,
    select_main_content,
)
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations

# The key shapes a 3.0.0 process wrote, reconstructed literally. Nothing in
# them encodes the server build, which is the whole defect.
_PRE_FIX_BUNDLE_PREFIX = "bundle:v2f"
_PRE_FIX_ENTRY_PREFIX = "entry:v3"
_PRE_FIX_SNIPPET_PREFIX = "snippet_render:v1"


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


class _RecordingCache:
    """Cache stand-in that records lookups and always misses."""

    def __init__(self) -> None:
        self.gets: List[str] = []

    def get(self, key: str, **kwargs: Any) -> Optional[Any]:
        self.gets.append(key)
        return None

    def set(self, key: str, value: Any, **kwargs: Any) -> None:
        pass

    def delete(self, key: str) -> None:
        pass


def _observed_key(cache: _RecordingCache, prefix_family: str) -> str:
    """Return the single recorded key whose first two segments name ``family``."""
    hits = [k for k in cache.gets if k.split(":")[0] == prefix_family]
    assert hits, f"no {prefix_family} cache lookup was recorded: {cache.gets}"
    return hits[0]


class TestStatTokenCarriesRenderEpoch:
    """The token every content-derived key embeds must encode the build."""

    def test_token_is_not_the_pre_fix_mtime_size_pair(self, temp_dir: Path) -> None:
        """A 3.0.0 token was ``<mtime_ns>:<size>`` and nothing else."""
        zim_file = temp_dir / "archive.zim"
        zim_file.write_bytes(b"content")
        st = zim_file.stat()

        assert archive_stat_token(zim_file) != f"{st.st_mtime_ns}:{st.st_size}", (
            "the stat token is byte-identical to 3.0.0's, so every key built "
            "from it re-serves the pre-upgrade rendering after a restart"
        )

    def test_token_ends_with_the_render_epoch(self, temp_dir: Path) -> None:
        """Bumping ``_RENDER_EPOCH`` must be what invalidates the keys."""
        zim_file = temp_dir / "archive.zim"
        zim_file.write_bytes(b"content")

        assert archive_stat_token(zim_file).endswith(f":{_RENDER_EPOCH}")

    def test_unstattable_path_also_carries_the_epoch(self, temp_dir: Path) -> None:
        """The OSError fallback must not drop back to a build-blind token."""
        missing = temp_dir / "gone.zim"

        assert archive_stat_token(missing).endswith(f":{_RENDER_EPOCH}")


class TestPreFixKeysAreNotReused:
    """Each of the three key families must differ from its 3.0.0 spelling."""

    def test_bundle_key_differs_from_the_pre_fix_key(self, temp_dir: Path) -> None:
        """``_compute_section_offsets`` now emits different ``section_id``s."""
        zim_file = temp_dir / "archive.zim"
        zim_file.write_bytes(b"content")
        st = zim_file.stat()
        pre_fix = (
            f"{_PRE_FIX_BUNDLE_PREFIX}:{zim_file}:"
            f"{st.st_mtime_ns}:{st.st_size}:A/Test:compact"
        )

        assert _bundle_cache_key(zim_file, "A/Test", True) != pre_fix

    def test_bundle_prefix_advanced_past_the_pre_fix_release(self) -> None:
        """The prefix documents WHICH content change; bump it as well."""
        assert _BUNDLE_KEY_PREFIX != _PRE_FIX_BUNDLE_PREFIX

    def test_entry_key_differs_from_the_pre_fix_key(
        self, zim_operations: ZimOperations, temp_dir: Path
    ) -> None:
        """Entry text changed too (noscript, in-page nav, leading H1)."""
        zim_file = temp_dir / "archive.zim"
        zim_file.write_bytes(b"content")
        validated = zim_operations._validate_zim_path(str(zim_file))
        st = validated.stat()
        recorder = _RecordingCache()
        zim_operations.cache = recorder  # type: ignore[assignment]

        with suppress(Exception):
            zim_operations.get_zim_entry(str(zim_file), "A/Test", 1000, 0)

        pre_fix = (
            f"{_PRE_FIX_ENTRY_PREFIX}:{validated}:{st.st_mtime_ns}:{st.st_size}:"
            f"A/Test:1000:0:compact=False"
        )
        assert _observed_key(recorder, "entry") != pre_fix

    def test_snippet_render_key_differs_from_the_pre_fix_key(
        self, zim_operations: ZimOperations, temp_dir: Path
    ) -> None:
        """Snippets are rendered by the same pipeline the PR changed."""
        zim_file = temp_dir / "archive.zim"
        zim_file.write_bytes(b"content")
        st = zim_file.stat()
        recorder = _RecordingCache()
        zim_operations.cache = recorder  # type: ignore[assignment]
        entry = Mock()
        entry.path = "A/Test"
        entry.title = "Test"

        with suppress(Exception):
            zim_operations._get_entry_snippet(entry, validated_path=str(zim_file))

        pre_fix = (
            f"{_PRE_FIX_SNIPPET_PREFIX}:{zim_file}:"
            f"{st.st_mtime_ns}:{st.st_size}:A/Test"
        )
        assert _observed_key(recorder, "snippet_render") != pre_fix


# A page carrying every construct this release changed: a ``noscript``
# sentence, an "On this page" in-page nav menu, and a heading anchor declared
# twice. Deliberately small — the fingerprint below is a change detector, and
# a large fixture would make it fire on changes it does not care about.
_RENDER_FIXTURE_HTML = """
<html><body><main>
<h1>Diabetes</h1>
<noscript>To use the sharing features on this page, enable JavaScript.</noscript>
<nav aria-label="On this page"><ul>
<li><a href="#summary">Summary</a></li>
<li><a href="#SH4b">Author Information</a></li>
<li><a href="#refs">References</a></li>
</ul></nav>
<p>Real prose about the topic.</p>
<h2><a name="SH4b"></a>Author Information</h2>
<p>First author block.</p>
<h2><a name="SH4b"></a>Author Information</h2>
<p>Second author block.</p>
</main></body></html>
"""

# (epoch, sha256) over the rendering these caches hold. If this assertion
# fails, the server renders something different from what a cache written by
# the current epoch contains: bump ``_RENDER_EPOCH`` in openzim_mcp/bundle.py,
# then re-pin BOTH pairs in this file with the new epoch and the printed
# digest. The epoch is part of the pin so that reverting a bump fails too —
# pinning the digest alone let ``r3`` go back to ``r2`` with every suite green.
_PINNED_RENDER_FINGERPRINT = (
    "r3",
    "d62d668001dd2a7ca972108f82ff6e49d7f2b2d5bebeb40af0890a607ba89c18",
)


def _render_fingerprint(content_processor: ContentProcessor) -> str:
    """Digest the bundle render + section ids + the entry-text render."""
    soup = BeautifulSoup(_RENDER_FIXTURE_HTML, "html.parser")
    root = select_main_content(soup)
    headings = _build_headings(root, include_line_text=True)
    rendered = content_processor._render_soup_to_text(root, compact=True)
    sections = _compute_section_offsets(rendered, headings)
    # ``scope_main_content=True`` mirrors the entry-content fetch, which is
    # what the ``entry:`` keys hold (see ``_get_entry_content``).
    entry_text = content_processor.process_mime_content(
        _RENDER_FIXTURE_HTML.encode("utf-8"),
        "text/html",
        compact=True,
        scope_main_content=True,
    )
    payload = json.dumps(
        {
            "rendered": rendered,
            "sections": [
                [s["id"], s["level"], s["char_start"], s["char_end"]] for s in sections
            ],
            "entry_text": entry_text,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_render_fingerprint_is_pinned_to_the_current_epoch(
    content_processor: ContentProcessor,
) -> None:
    """A rendering change must not land without an epoch bump."""
    observed = (_RENDER_EPOCH, _render_fingerprint(content_processor))

    assert observed == _PINNED_RENDER_FINGERPRINT, (
        f"what the bundle/entry/snippet caches hold, or the epoch, changed "
        f"(observed {observed}). Bump _RENDER_EPOCH in openzim_mcp/bundle.py "
        f"so an upgrade invalidates persisted values, then re-pin both pairs."
    )


# The epoch also guards what a RANKING cache holds. ``suggestions_data``
# stores its page after the fid 71 crawl-artefact demote, under a key whose
# only build-sensitive part is the epoch, so a snapshot persisted by a build
# that ranked differently re-serves that build's order until its TTL — which
# is what reverting this release's ``r2`` -> ``r3`` bump did, with every
# suite green. Every shape the demote treats specially is in the fixture,
# including the two it deliberately leaves alone.
_RANKING_FIXTURE_PATHS = (
    "a/languages/x.html",
    "a/real.html",
    "a/ency/imagepages/1.htm",
    "a/captions/x.srt",
    "a/b.html",
    "a/category/c/",
    "a/category/c/page/2/",
)
_PINNED_RANKING_FINGERPRINT = (
    "r3",
    "5d5745359f1eaa811b415ce912d61851e74d0fcc475704852100369c371896f4",
)


def _ranking_fingerprint() -> str:
    """Digest the order ``demote_crawl_artefacts`` gives the fixture."""
    from openzim_mcp.zim.search import demote_crawl_artefacts

    rows = [{"path": p} for p in _RANKING_FIXTURE_PATHS]
    ordered = [r["path"] for r in demote_crawl_artefacts(rows)]
    return hashlib.sha256(json.dumps(ordered).encode("utf-8")).hexdigest()


def test_ranking_fingerprint_is_pinned_to_the_current_epoch() -> None:
    """A change to the cached suggest ranking must not land without a bump."""
    observed = (_RENDER_EPOCH, _ranking_fingerprint())

    assert observed == _PINNED_RANKING_FINGERPRINT, (
        f"what the suggestions cache holds, or the epoch, changed (observed "
        f"{observed}). Bump _RENDER_EPOCH in openzim_mcp/bundle.py so an "
        f"upgrade invalidates persisted values, then re-pin both pairs."
    )


# The fixture above only sees a change that moves one of its seven paths: a
# new artefact shape, a dropped regex flag or a new rule inside the demote all
# passed it, and a persisted snapshot then served the old order. So the CODE
# the suggestions cache's order comes from is pinned as well — read through
# ``ast``, so comments and docstrings can change freely. If this fails and the
# cached ordering provably does not change, re-pin it with the same epoch;
# otherwise bump the epoch.
_RANKING_CODE_NAMES = (
    "_CRAWL_ARTEFACT_RE",
    "is_crawl_artefact",
    "demote_crawl_artefacts",
)
_PINNED_RANKING_CODE = (
    "r3",
    "d8cdb6b474b72f0f6fe73971a01d483540d48b9da34d4014ee13f5b2e8e0544b",
)


def _ranking_code_fingerprint() -> str:
    """Digest the demote's source with docstrings stripped and comments gone."""
    source = (
        Path(__file__).resolve().parents[1] / "openzim_mcp" / "zim" / "search.py"
    ).read_text(encoding="utf-8")
    parts: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in _RANKING_CODE_NAMES:
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                node.body = node.body[1:]
            parts[node.name] = ast.unparse(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in _RANKING_CODE_NAMES:
                    parts[target.id] = ast.unparse(node)
    assert set(parts) == set(_RANKING_CODE_NAMES), sorted(parts)
    blob = "\x00".join(parts[name] for name in _RANKING_CODE_NAMES)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def test_ranking_code_is_pinned_to_the_current_epoch() -> None:
    """A change to the demote's code must not land without a decision."""
    observed = (_RENDER_EPOCH, _ranking_code_fingerprint())

    assert observed == _PINNED_RANKING_CODE, (
        f"the crawl-artefact demote's code, or the epoch, changed (observed "
        f"{observed}). If what the suggestions cache holds changes, bump "
        f"_RENDER_EPOCH in openzim_mcp/bundle.py and re-pin every pair here; "
        f"if it provably does not, re-pin this one with the same epoch."
    )
