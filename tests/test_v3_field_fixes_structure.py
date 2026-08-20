"""v3.0.0 field-defect fixes — ``structure`` workstream (links / sections / TOC).

One test class per defect from the 2026-08-19 real-world sweep, in packet
order. Each docstring names the defect id and the behaviour it pins.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations

ARCHIVE_CTX = "openzim_mcp.zim_operations.zim_archive"


@pytest.fixture
def ops(tmp_path: Path) -> ZimOperations:
    """ZimOperations rooted in a temp dir holding one fake ``.zim`` path."""
    (tmp_path / "test.zim").touch()
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=100_000, snippet_length=200),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache, enable_background_cleanup=False),
        ContentProcessor(snippet_length=200),
    )


@pytest.fixture
def zim_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.zim")


def _html_archive(
    html: str,
    *,
    title: str = "Test",
    entry_path: str = "Test",
    mime: str = "text/html",
) -> MagicMock:
    """Mock libzim archive serving ``html`` for any requested path."""
    item = MagicMock()
    item.content = html.encode("utf-8")
    item.mimetype = mime
    item.path = entry_path
    entry = MagicMock()
    entry.title = title
    entry.path = entry_path
    entry.is_redirect = False
    entry.get_item.return_value = item
    archive = MagicMock()
    archive.get_entry_by_path.return_value = entry
    archive.has_entry_by_path.return_value = True
    return archive


def _missing_entry_archive() -> MagicMock:
    """Mock archive whose every path lookup misses the way libzim does."""
    archive = MagicMock()
    archive.get_entry_by_path.side_effect = KeyError("Cannot find entry")
    archive.has_entry_by_path.return_value = False
    return archive


# ---------------------------------------------------------------------------
# D18 — zim_get_section on a nonexistent entry must return entry_not_found
# ---------------------------------------------------------------------------


class TestD18SectionMissingEntry:
    """D18: a missing entry_path is an ``entry_not_found`` envelope, not a
    raw ``KeyError`` that the wrapper renders as a transient server fault."""

    def test_missing_entry_returns_entry_not_found_payload(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _missing_entry_archive()
            result = ops.get_section_data(zim_path, "A/Nope", section_id="summary")

        assert result.get("error") is True
        assert result["operation"] == "entry_not_found"
        assert "A/Nope" in result["message"]
        assert "KeyError" not in result["message"]
        # The guidance must point at path correction, not retries.
        assert "spelling" in result["message"].lower()


# ---------------------------------------------------------------------------
# D19 — duplicate explicit anchors must yield unique, fetchable section ids
# ---------------------------------------------------------------------------

DUPLICATE_ANCHOR_HTML = """\
<html><body>
<h1>Thrasymachus</h1>
<p>Lead paragraph.</p>
<h2 id="SH4b">b. Secondary Sources</h2>
<p>Books about Thrasymachus.</p>
<h2 id="SH4b">Author Information</h2>
<p>Written by a scholar.</p>
</body></html>
"""


class TestD19DuplicateAnchorIds:
    """D19: when an archive reuses an anchor name, the second heading gets a
    disambiguated id so every TOC node is fetchable and no id silently
    resolves to the wrong section. The first occurrence keeps its anchor."""

    def test_toc_ids_are_unique_and_first_anchor_is_preserved(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(
                DUPLICATE_ANCHOR_HTML
            )
            toc = ops.get_table_of_contents_data(zim_path, "Test")

        ids = [node["section_id"] for node in toc["toc"][0]["children"]]
        assert ids == ["SH4b", "SH4b_2"]
        assert len(set(ids)) == len(ids)

    def test_second_id_fetches_second_section(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(
                DUPLICATE_ANCHOR_HTML
            )
            first = ops.get_section_data(zim_path, "Test", section_id="SH4b")
            second = ops.get_section_data(zim_path, "Test", section_id="SH4b_2")

        assert first["section_title"] == "b. Secondary Sources"
        assert "Books about" in first["content_markdown"]
        assert second["section_title"] == "Author Information"
        assert "Written by" in second["content_markdown"]


# ---------------------------------------------------------------------------
# D20 — compact=True section text must match zim_get's compact article text
# ---------------------------------------------------------------------------

LINKED_HTML = """\
<html><body>
<h1>Diabetes</h1>
<p>Lead paragraph.</p>
<h2 id="what-is-diabetes">What is diabetes?</h2>
<p>Diabetes raises your <a href="bloodglucose.html">blood glucose</a>,
also called <a href="sugar.html">blood sugar</a>, above normal.</p>
</body></html>
"""


class TestD20CompactLinkParity:
    """D20: both compact surfaces promise the same slice shape, so a
    compact section body must be link-stripped exactly like the compact
    article body — and therefore be a substring of it."""

    def test_compact_section_is_substring_of_compact_article(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(LINKED_HTML)
            article = ops.get_zim_entry_data(zim_path, "Test", compact=True)
            section = ops.get_section_data(
                zim_path, "Test", section_id="what-is-diabetes", compact=True
            )

        body = section["content_markdown"]
        assert "](" not in body, body
        assert "blood glucose" in body
        assert body.strip() in article["content"]
        assert section["char_count"] == len(body)

    def test_raw_section_keeps_links(self, ops: ZimOperations, zim_path: str) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(LINKED_HTML)
            section = ops.get_section_data(
                zim_path, "Test", section_id="what-is-diabetes", compact=False
            )
        assert "](bloodglucose.html)" in section["content_markdown"]


# ---------------------------------------------------------------------------
# D21 — the advertised include_subsections knob must exist and be forwarded
# ---------------------------------------------------------------------------


def _tool_server() -> MagicMock:
    """Stand-in server whose ``mcp.tool`` decorator records the function."""
    srv = MagicMock()
    store: dict = {}

    def _tool(*, description: str = ""):
        def decorate(fn):
            store[fn.__name__] = (fn, description)
            return fn

        return decorate

    srv.mcp.tool = _tool
    srv._tools_store = store
    return srv


class TestD21IncludeSubsections:
    """D21: the description's first sentence promised 'optional subsection
    inclusion' while the tool had no such parameter and silently dropped
    it. The data layer already implements the flag; forward it."""

    @pytest.mark.asyncio
    async def test_include_subsections_false_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import AsyncMock

        from openzim_mcp.tools.zim_get_section import register

        mock_ops = MagicMock()
        mock_ops.get_section_data = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(
            "openzim_mcp.async_operations.AsyncZimOperations",
            lambda _ops: mock_ops,
        )
        server = _tool_server()
        register(server)
        fn, description = server._tools_store["zim_get_section"]

        await fn(
            zim_file_path="/x.zim",
            entry_path="A/Cat",
            section_id="History",
            include_subsections=False,
        )
        mock_ops.get_section_data.assert_awaited_once_with(
            "/x.zim",
            "A/Cat",
            "History",
            max_chars=None,
            include_subsections=False,
            compact=True,
        )
        assert "include_subsections" in description


# ---------------------------------------------------------------------------
# D22 — view=toc / view=structure on a missing entry classify as not-found
# ---------------------------------------------------------------------------


class TestD22TocStructureMissingEntry:
    """D22: the same missing entry must get the same not-found classification
    from the toc/structure views that the full view gives — not an
    'Archive Operation Error ... verify the ZIM file is not corrupted'."""

    @pytest.mark.parametrize(
        "method", ["get_table_of_contents_data", "get_article_structure_data"]
    )
    def test_missing_entry_renders_not_found_template(
        self, ops: ZimOperations, zim_path: str, method: str
    ) -> None:
        from openzim_mcp.error_messages import NOT_FOUND_ERROR_CONFIG, get_error_config

        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _missing_entry_archive()
            with pytest.raises(Exception) as excinfo:
                getattr(ops, method)(zim_path, "A/Nope")

        err = excinfo.value
        assert "A/Nope" in str(err)
        assert get_error_config(err) is NOT_FOUND_ERROR_CONFIG, str(err)


# ---------------------------------------------------------------------------
# D23 — section_not_found on a section-free entry must say why
# ---------------------------------------------------------------------------


class TestD23SectionFreeEntries:
    """D23: when the entry can have no sections, the error must say so and
    why (non-HTML / no headings) instead of listing zero ids and sending
    the caller on a TOC round-trip that can only confirm the same."""

    def test_non_html_entry_explains_content_type(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(
                "binary", mime="image/jpeg", entry_path="I/plato.jpg"
            )
            result = ops.get_section_data(zim_path, "I/plato.jpg", section_id="x")

        assert result["operation"] == "section_not_found"
        assert result["reason"] == "non_html"
        assert result["content_type"] == "image/jpeg"
        assert "image/jpeg" in result["message"]
        assert "no sections" in result["message"].lower()
        assert "view='toc'" not in result["message"]

    def test_heading_free_html_explains_no_headings(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(
                "<html><body><p>Just prose, no headings.</p></body></html>"
            )
            result = ops.get_section_data(zim_path, "Test", section_id="summary")

        assert result["operation"] == "section_not_found"
        assert result["reason"] == "no_headings"
        assert "no headings" in result["message"].lower()
        assert "zim_get" in result["message"]
        assert "view='toc'" not in result["message"]


# ---------------------------------------------------------------------------
# D24 — a pure case mismatch on a short anchor id gets a closest_match
# ---------------------------------------------------------------------------

ANCHOR_ID_HTML = """\
<html><body>
<h1 id="H1">Plato</h1>
<p>Lead.</p>
<h2 id="SH2d">d. The Republic</h2>
<p>On justice.</p>
<h2 id="SH2e">e. Later Dialogues</h2>
<p>On being.</p>
</body></html>
"""


class TestD24CaseInsensitiveClosestMatch:
    """D24: 'sh2d' vs 'SH2d' scores 0.5 under difflib's 0.6 cutoff, so the
    easiest typo to repair got no Did-you-mean. Compare case-folded."""

    def test_case_variant_gets_closest_match(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(ANCHOR_ID_HTML)
            result = ops.get_section_data(zim_path, "Test", section_id="sh2d")

        assert result["operation"] == "section_not_found"
        assert result["closest_match"] == "SH2d"
        assert "Did you mean 'SH2d'?" in result["message"]

    def test_fuzzy_match_still_works_across_case(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(ANCHOR_ID_HTML)
            result = ops.get_section_data(zim_path, "Test", section_id="Sh2E")

        assert result["closest_match"] == "SH2e"


# ---------------------------------------------------------------------------
# D25 — the rate-limit message must never say "wait 0.00 seconds"
# ---------------------------------------------------------------------------


class TestD25RateLimitWaitFloor:
    """D25: a sub-centisecond (or, via the post-acquire refill race, exactly
    zero) wait formatted as 0.00 is a nonsensical instruction. Floor it."""

    @pytest.mark.parametrize("wait", [0.0, 0.0004, 0.0099])
    def test_wait_is_floored_to_a_displayable_value(
        self, monkeypatch: pytest.MonkeyPatch, wait: float
    ) -> None:
        from openzim_mcp.exceptions import OpenZimMcpRateLimitError
        from openzim_mcp.rate_limiter import (
            RateLimitConfig,
            RateLimiter,
            TokenBucket,
        )

        monkeypatch.setattr(TokenBucket, "acquire", lambda self, tokens=1: False)
        monkeypatch.setattr(TokenBucket, "get_wait_time", lambda self, tokens=1: wait)
        limiter = RateLimiter(RateLimitConfig(requests_per_second=200.0, burst_size=5))

        with pytest.raises(OpenZimMcpRateLimitError) as excinfo:
            limiter.check_rate_limit("op", cost=1, client_id="c")

        message = str(excinfo.value)
        assert "0.00 seconds" not in message
        assert "0.01 seconds" in message
        assert "wait_time=0.01s" in str(excinfo.value.details)

    def test_real_wait_is_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from openzim_mcp.exceptions import OpenZimMcpRateLimitError
        from openzim_mcp.rate_limiter import (
            RateLimitConfig,
            RateLimiter,
            TokenBucket,
        )

        monkeypatch.setattr(TokenBucket, "acquire", lambda self, tokens=1: False)
        monkeypatch.setattr(TokenBucket, "get_wait_time", lambda self, tokens=1: 1.5)
        limiter = RateLimiter(RateLimitConfig(requests_per_second=2.0, burst_size=1))

        with pytest.raises(OpenZimMcpRateLimitError, match=r"1\.50 seconds"):
            limiter.check_rate_limit("op", cost=1, client_id="c")


# ---------------------------------------------------------------------------
# D33 — related rows must follow redirects: real title, canonical path
# ---------------------------------------------------------------------------

CLIMATE_ZIM = Path(
    "test_data/zim-testing-suite/withns/wikipedia_en_climate_change_mini_2024-06.zim"
)


def _redirect_archive() -> MagicMock:
    """Archive where ``C/aristotl`` is a zimit-style redirect whose own title
    is the path string, pointing at ``C/aristotle/`` with the real title."""
    target = MagicMock()
    target.is_redirect = False
    target.path = "C/aristotle/"
    target.title = "Aristotle | Internet Encyclopedia of Philosophy"
    stub = MagicMock()
    stub.is_redirect = True
    stub.path = "C/aristotl"
    stub.title = "C/aristotl"
    stub.get_redirect_entry.return_value = target

    def lookup(path: str) -> MagicMock:
        if path == "C/aristotl":
            return stub
        if path == "C/aristotle/":
            return target
        raise KeyError("Cannot find entry")

    archive = MagicMock()
    archive.get_entry_by_path.side_effect = lookup
    return archive


class TestD33RelatedFollowsRedirects:
    """D33: ``_resolve_outbound_titles`` took the redirect stub's own title
    (the path string, on zimit archives) and left the pre-redirect path,
    so every related row read ``title == path`` and fed back zero inbound
    rows. Follow the chain like the sidecar builder does."""

    def test_redirect_stub_resolves_to_target_title_and_path(self) -> None:
        from openzim_mcp.zim.structure import _StructureMixin

        rows = [{"path": "C/aristotl", "title": "C/aristotl"}]
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _redirect_archive()
            _StructureMixin._resolve_outbound_titles("/x.zim", rows)

        assert rows[0]["path"] == "C/aristotle/"
        assert rows[0]["title"] == "Aristotle | Internet Encyclopedia of Philosophy"

    def test_non_redirect_entry_is_unchanged(self) -> None:
        from openzim_mcp.zim.structure import _StructureMixin

        rows = [{"path": "C/aristotle/", "title": "C/aristotle/"}]
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _redirect_archive()
            _StructureMixin._resolve_outbound_titles("/x.zim", rows)

        assert rows[0]["path"] == "C/aristotle/"
        assert rows[0]["title"].startswith("Aristotle")

    @pytest.mark.skipif(not CLIMATE_ZIM.exists(), reason="test ZIM corpus absent")
    def test_real_archive_redirect_is_followed(self) -> None:
        from openzim_mcp.zim.structure import _StructureMixin

        rows = [{"path": 'A/"dry_spell"', "title": 'A/"dry_spell"'}]
        _StructureMixin._resolve_outbound_titles(str(CLIMATE_ZIM), rows)

        assert rows[0]["path"] == "A/Drought"
        assert rows[0]["title"] != rows[0]["path"]
        assert "Drought" in rows[0]["title"]

    def test_related_merges_spellings_of_one_target(
        self, test_config: OpenZimMcpConfig
    ) -> None:
        """Two hrefs that redirect to the same canonical entry are one
        related row with the summed mention_count, not two rows whose
        paths disagree with what inbound returns."""
        from openzim_mcp.server import OpenZimMcpServer

        srv = OpenZimMcpServer(test_config)
        srv.zim_operations.path_validator = MagicMock()
        srv.zim_operations.path_validator.validate_path.side_effect = lambda p: p
        srv.zim_operations.path_validator.validate_zim_file.side_effect = lambda p: p
        srv.zim_operations.extract_article_links_data = MagicMock(
            return_value={
                "kind": "internal",
                "path": "C/plato/",
                "results": [
                    {"url": "../aristotl", "text": "Aristotle (stub)"},
                    {"url": "../aristotle/", "text": "Aristotle"},
                    {"url": "../aristotl", "text": "Aristotle (stub)"},
                ],
            }
        )
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _redirect_archive()
            result = srv.zim_operations.get_related_articles_data(
                "/zim/test.zim", "C/plato/", limit=10
            )

        assert [r["path"] for r in result["results"]] == ["C/aristotle/"]
        assert result["results"][0]["mention_count"] == 3
        assert result["results"][0]["title"].startswith("Aristotle")
        assert result["total"] == 1


# ---------------------------------------------------------------------------
# D34 — outbound internal rows carry a fetchable, resolved ``path``
# ---------------------------------------------------------------------------

PLATO_HTML = """\
<html><body>
<h1>Plato</h1>
<p>See <a href="../aristotl">Aristotle</a> and
<a href="../zenos-paradoxes">Zeno</a>; also <a href="#SH2a">below</a>
and <a href="https://example.org/x">outside</a>.
<img src="../wp-content/media/plato.jpg" alt="Plato"></p>
</body></html>
"""


def _links_archive(
    html: str, *, source: str, targets: dict[str, MagicMock]
) -> MagicMock:
    """Archive serving ``html`` at ``source`` plus the given target entries."""
    page = _html_archive(html, title="Plato | IEP", entry_path=source)
    page_entry = page.get_entry_by_path.return_value

    def lookup(path: str) -> MagicMock:
        if path == source:
            return page_entry
        if path in targets:
            return targets[path]
        raise KeyError("Cannot find entry")

    archive = MagicMock()
    archive.get_entry_by_path.side_effect = lookup
    return archive


def _redirect_pair() -> dict[str, MagicMock]:
    target = MagicMock()
    target.is_redirect = False
    target.path = "iep.utm.edu/aristotle/"
    target.title = "Aristotle | IEP"
    stub = MagicMock()
    stub.is_redirect = True
    stub.path = "iep.utm.edu/aristotl"
    stub.title = "iep.utm.edu/aristotl"
    stub.get_redirect_entry.return_value = target
    return {"iep.utm.edu/aristotl": stub, "iep.utm.edu/aristotle/": target}


class TestD34OutboundResolvedPath:
    """D34: ``url`` is the raw document-relative href and does not round-trip
    into zim_get. Each internal row also carries ``path`` — resolved against
    the served entry, redirect-followed when the archive can verify it."""

    def test_internal_rows_carry_resolved_path(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        archive = _links_archive(
            PLATO_HTML, source="iep.utm.edu/plato/", targets=_redirect_pair()
        )
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = archive
            data = ops.extract_article_links_data(
                zim_path, "iep.utm.edu/plato/", kind="internal"
            )

        rows = {r["url"]: r for r in data["results"]}
        assert set(rows) == {"../aristotl", "../zenos-paradoxes"}
        # Raw href kept for fidelity; canonical post-redirect path added.
        assert rows["../aristotl"]["path"] == "iep.utm.edu/aristotle/"
        # Unverifiable target: best-effort path-normalized, still present.
        assert rows["../zenos-paradoxes"]["path"] == "iep.utm.edu/zenos-paradoxes"

    def test_external_and_media_rows_have_no_path(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        archive = _links_archive(
            PLATO_HTML, source="iep.utm.edu/plato/", targets=_redirect_pair()
        )
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = archive
            external = ops.extract_article_links_data(
                zim_path, "iep.utm.edu/plato/", kind="external"
            )
            media = ops.extract_article_links_data(
                zim_path, "iep.utm.edu/plato/", kind="media"
            )

        assert external["results"] and all("path" not in r for r in external["results"])
        assert media["results"] and all("path" not in r for r in media["results"])
