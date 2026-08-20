"""v3.0.0 field-defect fixes — content cluster (zim_get bodies, lead extraction).

Each test pins one defect from the 2026-08-19 real-world sweep against the
MedlinePlus / IEP corpora. Fixtures are trimmed copies of the real archive
HTML so the shapes that broke in the field are the shapes under test.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def ops(
    test_config: OpenZimMcpConfig,
    path_validator: PathValidator,
    openzim_mcp_cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
) -> ZimOperations:
    return ZimOperations(
        test_config, path_validator, openzim_mcp_cache, content_processor
    )


@pytest.fixture
def zim_file(temp_dir: Path) -> Path:
    """A placeholder file inside the allowed directory; the archive is mocked."""
    path = temp_dir / "corpus.zim"
    path.write_text("x")
    return path


def _html_entry(path: str, title: str, html: str) -> MagicMock:
    entry = MagicMock()
    entry.is_redirect = False
    entry.path = path
    entry.title = title
    item = MagicMock()
    item.mimetype = "text/html"
    item.content = html.encode("utf-8")
    entry.get_item.return_value = item
    return entry


def _archive_with(entries: dict[str, MagicMock]) -> MagicMock:
    """A mock libzim Archive that resolves exactly the given path spellings."""
    inst = MagicMock()
    inst.has_new_namespace_scheme = True

    def _get(path: str) -> MagicMock:
        if path in entries:
            return entries[path]
        raise KeyError("Cannot find entry")

    inst.get_entry_by_path.side_effect = _get
    inst.has_entry_by_path.side_effect = lambda p: p in entries
    return inst


# ---------------------------------------------------------------------------
# D07 — percent-encoded paths served by the archive's own links must resolve
# ---------------------------------------------------------------------------

_IEP_RAW = "iep.utm.edu/gauḍapad/"
_IEP_ENCODED = "iep.utm.edu/gau%E1%B8%8Dapad/"


@patch("openzim_mcp.zim_operations.Archive")
def test_percent_encoded_path_resolves_before_search_fallback(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D07: the IEP G-index links ``../gau%E1%B8%8Dapad/`` exactly as archived;
    libzim stores the raw UTF-8 spelling. Feeding the served link back into
    zim_get must resolve via percent-decoding, not dead-end in not-found."""
    mock_archive.return_value = _archive_with(
        {_IEP_RAW: _html_entry(_IEP_RAW, "Gaudapada", "<h1>Gaudapada</h1><p>x</p>")}
    )
    search = MagicMock(return_value=None)
    with patch.object(ops, "_find_entry_by_search", search):
        result = ops.get_zim_entry_data(str(zim_file), _IEP_ENCODED)

    assert not result.get("error"), result
    assert result["path"] == _IEP_RAW
    assert result["requested_path"] == _IEP_ENCODED
    assert "Gaudapada" in result["content"]
    # The decoded spelling is a cheap exact probe; it must win before the
    # search-based fallback is consulted at all.
    search.assert_not_called()


@patch("openzim_mcp.zim_operations.Archive")
def test_literal_percent_path_is_not_decoded_away(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """warc2zim stores some asset names with a literal ``%``; the raw spelling
    must still be tried first so those keep resolving."""
    literal = "I/Al_Gore%2C_2007.webp"
    mock_archive.return_value = _archive_with(
        {literal: _html_entry(literal, "Al Gore", "<p>photo</p>")}
    )
    result = ops.get_zim_entry_data(str(zim_file), literal)
    assert result["path"] == literal
    assert "requested_path" not in result


# ---------------------------------------------------------------------------
# D08 — not-found guidance must name tools the v3 surface actually exposes
# ---------------------------------------------------------------------------

_STALE_TOOL_NAMES = ("search_zim_file", "browse_namespace")


def _assert_names_real_tools(message: str) -> None:
    for stale in _STALE_TOOL_NAMES:
        assert stale not in message, message
    assert "zim_search" in message or "zim_health" in message, message


@patch("openzim_mcp.zim_operations.Archive")
def test_entry_not_found_guidance_names_real_tools(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D08: the ladder's not-found text pointed at pre-v3 helper names."""
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    mock_archive.return_value = _archive_with({})
    with patch.object(ops, "_find_entry_by_search", MagicMock(return_value=None)):
        with pytest.raises(OpenZimMcpArchiveError) as exc:
            ops.get_zim_entry_data(str(zim_file), "medlineplus.gov/nope.html")
    _assert_names_real_tools(str(exc.value))
    assert "zim_browse" in str(exc.value)


@patch("openzim_mcp.zim_operations.Archive")
def test_search_fallback_failure_guidance_names_real_tools(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    mock_archive.return_value = _archive_with({})
    boom = MagicMock(side_effect=RuntimeError("xapian down"))
    with patch.object(ops, "_find_entry_by_search", boom):
        with pytest.raises(OpenZimMcpArchiveError) as exc:
            ops.get_zim_entry_data(str(zim_file), "medlineplus.gov/nope.html")
    _assert_names_real_tools(str(exc.value))


@patch("openzim_mcp.zim_operations.Archive")
def test_file_level_failure_guidance_names_real_tools(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    mock_archive.return_value = _archive_with({})
    with patch.object(ops, "_smart_retrieve_entry", MagicMock(side_effect=ValueError)):
        with pytest.raises(OpenZimMcpArchiveError) as data_exc:
            ops.get_zim_entry_data(str(zim_file), "A/x")
        with pytest.raises(OpenZimMcpArchiveError) as text_exc:
            ops.get_zim_entry(str(zim_file), "A/x")
    _assert_names_real_tools(str(data_exc.value))
    _assert_names_real_tools(str(text_exc.value))


@patch("openzim_mcp.zim_operations.zim_archive")
def test_binary_not_found_guidance_names_real_tools(
    mock_zim_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    mock_zim_archive.return_value.__enter__.return_value = _archive_with({})
    with patch.object(ops, "_find_entry_by_search", MagicMock(return_value=None)):
        with pytest.raises(OpenZimMcpArchiveError) as exc:
            ops.get_binary_entry_data(str(zim_file), "I/nope.png")
    _assert_names_real_tools(str(exc.value))


def test_resolve_with_fallback_guidance_names_real_tools(ops: ZimOperations) -> None:
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    with patch.object(ops, "_find_entry_by_search", MagicMock(return_value=None)):
        with pytest.raises(OpenZimMcpArchiveError) as exc:
            ops._resolve_entry_with_fallback(_archive_with({}), "A/nope")
    _assert_names_real_tools(str(exc.value))


@patch("openzim_mcp.zim_operations.Archive")
def test_simple_mode_sanitizer_still_strips_reworded_guidance(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """zim_query has no zim_search/zim_browse either; its leak sanitizer must
    keep stripping the backend sentence after the rewording."""
    from openzim_mcp.exceptions import OpenZimMcpArchiveError
    from openzim_mcp.simple_tools import SimpleToolsHandler

    mock_archive.return_value = _archive_with({})
    with patch.object(ops, "_find_entry_by_search", MagicMock(return_value=None)):
        with pytest.raises(OpenZimMcpArchiveError) as exc:
            ops.get_zim_entry_data(str(zim_file), "medlineplus.gov/nope.html")
    stripped = SimpleToolsHandler._BACKEND_API_LEAK_RE.sub("", str(exc.value))
    assert "zim_search" not in stripped
    assert "zim_browse" not in stripped
    assert "Entry not found" in stripped


# ---------------------------------------------------------------------------
# D09 — binary oversize hint must name the knob zim_get actually exposes
# ---------------------------------------------------------------------------


@patch("openzim_mcp.zim_operations.zim_archive")
def test_binary_oversize_message_names_max_content_length(
    mock_zim_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D09: zim_get maps ``max_content_length`` onto the byte cap; the hint
    offered ``include_data`` / ``max_size_bytes``, neither reachable over
    the wire, so following it changed nothing."""
    entry = MagicMock()
    entry.is_redirect = False
    entry.path = "I/big.jpg"
    entry.title = "big"
    item = MagicMock()
    item.mimetype = "image/jpeg"
    item.size = 9944
    item.content = b"x" * 9944
    entry.get_item.return_value = item
    mock_zim_archive.return_value.__enter__.return_value = _archive_with(
        {"I/big.jpg": entry}
    )

    result = ops.get_binary_entry_data(str(zim_file), "I/big.jpg", max_size_bytes=100)

    assert result["truncated"] is True
    message = result["message"]
    assert "max_content_length" in message, message
    assert "include_data" not in message, message
    assert "max_size_bytes" not in message, message
    # The cap the caller hit is still reported so they can size the retry.
    assert "100 B" in message


# ---------------------------------------------------------------------------
# D10 / D11 — main_page must be scoped and capped like a path fetch
# ---------------------------------------------------------------------------

# Trimmed from medlineplus.gov/ (warc2zim): federal banner + skip-nav +
# header menus OUTSIDE <article>, the welcome prose INSIDE it.
_MEDLINEPLUS_HOME_HTML = """\
<html><body>
<a class="usa-skipnav" href="#main">Skip navigation</a>
<section class="usa-banner"><p>An official website of the United States government</p>
<p>Here's how you know</p><p><strong>Official websites use .gov</strong></p></section>
<header><nav><ul><li><a href="healthtopics.html">Health Topics</a></li>
<li><a href="druginfo/">Drugs &amp; Supplements</a></li></ul></nav></header>
<article>
<h1>Welcome to MedlinePlus</h1>
<p>MedlinePlus is an online health information resource for patients and
their families and friends.</p>
<h2>Health Topics</h2>
<p>Find information on health, wellness, disorders and conditions.</p>
</article>
<footer><p>Stay Connected</p></footer>
</body></html>
"""


def _archive_with_main_page(html: str, path: str = "medlineplus.gov/") -> MagicMock:
    entry = _html_entry(path, "MedlinePlus", html)
    inst = _archive_with({path: entry})
    inst.main_entry = entry
    return inst


@patch("openzim_mcp.zim_operations.Archive")
def test_main_page_scopes_site_chrome_like_a_path_fetch(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D10: main_page=True served the banner/skip-nav/menus that fetching the
    identical entry by path already strips; both branches must agree."""
    mock_archive.return_value = _archive_with_main_page(_MEDLINEPLUS_HOME_HTML)

    main = ops.get_main_page_data(str(zim_file))
    by_path = ops.get_zim_entry_data(str(zim_file), "medlineplus.gov/")

    assert "Skip navigation" not in main["content"], main["content"]
    assert "official website" not in main["content"], main["content"]
    assert main["content"].lstrip().startswith("# Welcome to MedlinePlus")
    assert main["content"] == by_path["content"]


@patch("openzim_mcp.zim_operations.Archive")
def test_main_page_honors_max_content_length(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D11: max_content_length was silently ignored on the main_page branch;
    every other unsupported combination on this tool errors loudly."""
    long_html = _MEDLINEPLUS_HOME_HTML.replace(
        "<h2>Health Topics</h2>",
        # ~1.2K chars: above the 200 cap under test, below the branch's
        # 5000-char default so the uncapped control read is NOT truncated.
        "<h2>Health Topics</h2>" + "<p>" + ("lorem ipsum " * 100) + "</p>",
    )
    mock_archive.return_value = _archive_with_main_page(long_html)

    capped = ops.get_main_page_data(str(zim_file), max_content_length=200)
    body, sep, footer = capped["content"].partition("\n\n... [Content truncated")
    assert sep, capped["content"]
    assert len(body) <= 200
    assert capped["_meta"]["truncated"] is True
    assert capped["_meta"]["total_chars"] > 200
    # The footer must not advertise content_offset: the branch never reads it.
    assert "content_offset=" not in footer

    # The cap is part of the response identity — an uncapped call right after
    # must not be served the capped rendering from cache.
    uncapped = ops.get_main_page_data(str(zim_file))
    assert len(uncapped["content"]) > len(capped["content"])
    assert uncapped["_meta"]["truncated"] is False


@pytest.mark.asyncio
async def test_zim_get_forwards_max_content_length_to_main_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool layer dropped max_content_length on the main_page branch."""
    from unittest.mock import AsyncMock

    from openzim_mcp.tools.zim_get import register as register_zim_get

    srv = MagicMock()
    store: dict = {}

    def _tool(*, description: str = ""):
        def decorate(fn):
            store[fn.__name__] = fn
            return fn

        return decorate

    srv.mcp.tool = _tool
    mock_ops = MagicMock()
    mock_ops.get_main_page_data = AsyncMock(return_value={"content": "Welcome"})
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations", lambda _ops: mock_ops
    )
    register_zim_get(srv)

    await store["zim_get"](
        zim_file_path="/x.zim", main_page=True, max_content_length=200
    )

    mock_ops.get_main_page_data.assert_awaited_once_with(
        "/x.zim", compact=False, max_content_length=200
    )
