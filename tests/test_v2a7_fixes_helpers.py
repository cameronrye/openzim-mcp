"""Integration-shape tests for the v2.0.0a7 defect-fix batch.

These tests use fixture data only (no live ZIM file) and exercise the
helper-level contracts that the v2.0.0a7 fixes introduce:

  * D2/D3 — new-scheme C / W namespace paging via dedicated paths.
  * D5  — synthesize strips intent-shaped NL prefix from the search query.
  * D6  — tell_me_about promotes a title-index 1.0 score over BM25 hits.
  * D8  — synthesize section attribution survives bold-marker insertion.
  * D10 — zim_query.cursor decodes to options["offset"].
  * D11 — metadata previews cap at 800 chars + ``[truncated, …]`` marker.
  * Op2 — compact-structure renderer carries per-heading summary.
  * Op3 — get_section honors ``include_subsections=False`` by ending
    the slice at the next heading of any level.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

from openzim_mcp.compact_renderers import compact_structure_payload
from openzim_mcp.synthesize import _locate_passage, _strip_bold
from openzim_mcp.zim.archive import _METADATA_PREVIEW_CAP


# ---------------------------------------------------------------------------
# D8: synthesize section attribution survives bold markers in passages
# ---------------------------------------------------------------------------


def test_strip_bold_removes_paired_markers():
    """``**term**`` is collapsed to ``term`` for substring location."""
    assert _strip_bold("**Berlin** is the **capital**") == "Berlin is the capital"


def test_locate_passage_finds_bolded_text_in_plain_markdown():
    """Section attribution must not be killed by ``_highlight_terms`` adding
    ``**`` markers around the query term — the bundle's rendered_markdown
    carries no highlight wrapping."""
    bundle_md = (
        "# Berlin\n\nBerlin is the capital of Germany.\n\n"
        "## Geography\n\nBerlin is in northeastern Germany.\n"
    )
    passage = "**Berlin** is in northeastern Germany."
    pos = _locate_passage(bundle_md, passage)
    assert pos >= 0, "Bolded passage should still locate in plain bundle markdown"
    # The found position points at the plain "Berlin is in northeastern…"
    assert bundle_md[pos:].startswith("Berlin is in northeastern")


# ---------------------------------------------------------------------------
# D11: metadata preview cap
# ---------------------------------------------------------------------------


def test_metadata_preview_cap_constant_is_sane():
    """The cap stays below 4 kB so a worst-case 10-field metadata
    response can't blow past a typical compact budget."""
    assert 200 <= _METADATA_PREVIEW_CAP <= 4000


# ---------------------------------------------------------------------------
# Op2: compact structure carries per-section summaries
# ---------------------------------------------------------------------------


def test_compact_structure_includes_summary_when_section_preview_exists():
    """A payload with both headings AND sections produces compact
    headings carrying an 80-char summary derived from the section's
    content_preview."""
    payload = {
        "title": "Berlin",
        "path": "Berlin",
        "headings": [
            {"level": 1, "text": "Berlin", "id": "Berlin"},
            {"level": 2, "text": "Geography", "id": "Geography"},
        ],
        "sections": [
            {"title": "Berlin", "level": 1, "content_preview": "Berlin is the capital."},
            {
                "title": "Geography",
                "level": 2,
                "content_preview": (
                    "Berlin is in northeastern Germany, in an area of low-lying "
                    "marshy woodlands with a mainly flat topography."
                ),
            },
        ],
    }
    rendered = json.loads(compact_structure_payload(payload))
    headings = rendered["headings"]
    by_text = {h["text"]: h for h in headings}
    assert "summary" in by_text["Geography"]
    assert len(by_text["Geography"]["summary"]) <= 80
    assert by_text["Geography"]["summary"].startswith("Berlin is in northeastern Germany")


def test_compact_structure_skips_summary_when_no_section_preview():
    """When the payload only carries ``headings`` (no ``sections``), the
    compact view skips the summary field — no source data to derive from."""
    payload = {
        "title": "Sparse",
        "path": "Sparse",
        "headings": [{"level": 1, "text": "Sparse", "id": "Sparse"}],
    }
    rendered = json.loads(compact_structure_payload(payload))
    assert "summary" not in rendered["headings"][0]


# ---------------------------------------------------------------------------
# Op3: get_section narrow-mode parsing
# ---------------------------------------------------------------------------


def test_intent_parser_narrow_section_sets_flag():
    """``narrow section Geography of Berlin`` parses to params with
    ``narrow=True`` and the section / entry stripped clean."""
    from openzim_mcp.intent_parser import IntentParser

    parser = IntentParser()
    intent, params, _confidence = parser.parse_intent(
        "narrow section Geography of Berlin"
    )
    assert intent == "get_section"
    assert params.get("narrow") is True
    assert params.get("section_name") == "Geography"
    assert params.get("entry_path") == "Berlin"


def test_intent_parser_just_section_alias():
    """``just section X of Y`` is treated identically to ``narrow``."""
    from openzim_mcp.intent_parser import IntentParser

    parser = IntentParser()
    _intent, params, _confidence = parser.parse_intent(
        "just section Climate of Berlin"
    )
    assert params.get("narrow") is True


def test_intent_parser_plain_section_no_narrow_flag():
    """Without the prefix, ``narrow`` stays unset so the handler defaults
    to ``include_subsections=True`` (legacy behavior)."""
    from openzim_mcp.intent_parser import IntentParser

    parser = IntentParser()
    _intent, params, _confidence = parser.parse_intent("section Geography of Berlin")
    assert params.get("narrow") in (None, False)


# ---------------------------------------------------------------------------
# D5: synthesize strips the natural-language interrogative prefix BEFORE
# handing the query to the search stage
# ---------------------------------------------------------------------------


def test_synthesize_strips_tell_me_about_prefix(test_config, monkeypatch):
    """``synthesize=True`` with ``"tell me about Berlin"`` MUST pass
    just ``"Berlin"`` to the search backend — otherwise BM25 matches on
    ``tell``/``me``/``about`` and returns Irving Berlin songs instead
    of the canonical Berlin article."""
    from openzim_mcp.server import OpenZimMcpServer
    from openzim_mcp.simple_tools import SimpleToolsHandler

    server = OpenZimMcpServer(test_config)
    if server.simple_tools_handler is None:
        # ``test_config`` opens advanced mode; the simple-mode handler
        # we want to exercise has to be constructed explicitly.
        server.simple_tools_handler = SimpleToolsHandler(server.zim_operations)
    captured_query: dict = {}

    def fake_synthesize(query, **kwargs):
        captured_query["search_query"] = query
        captured_query["original_query"] = kwargs.get("original_query")
        return {
            "query": kwargs.get("original_query") or query,
            "answer_markdown": "",
            "passages": [],
            "citations": [],
            "archives_searched": [],
            "fallback_used": "xapian_score",
            "total_chars": 0,
            "total_words": 0,
            "_meta": {},
        }

    monkeypatch.setattr("openzim_mcp.synthesize.synthesize_query", fake_synthesize)
    # Skip the archive-resolution machinery: pretend there's one
    # already-validated archive to hand to synthesize_query.
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive",
        lambda *a, **kw: _DummyCtx(MagicMock()),
    )
    monkeypatch.setattr(
        server.zim_operations.path_validator,
        "validate_path",
        lambda p: __import__("pathlib").Path(p),
    )
    monkeypatch.setattr(
        server.zim_operations.path_validator,
        "validate_zim_file",
        lambda p: p,
    )

    server.simple_tools_handler._handle_synthesize_query(
        "tell me about Berlin",
        "/fake/test.zim",
        compact=True,
    )

    # The search-stage query has the NL prefix stripped.
    assert captured_query["search_query"] == "Berlin"
    # The original NL form is preserved in original_query for echo.
    assert captured_query["original_query"] == "tell me about Berlin"


class _DummyCtx:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *a):
        return False


# ---------------------------------------------------------------------------
# D6: tell_me_about falls back to find_entry_by_title for 1.0 promotion
# ---------------------------------------------------------------------------


def test_tell_me_about_promotes_title_index_match(test_config, monkeypatch):
    """When BM25 ranks ``List of songs about Berlin`` above the
    canonical ``Berlin`` article, ``_find_title_match_for_topic``
    queries the title index and promotes the score-1.0 entry."""
    from openzim_mcp.server import OpenZimMcpServer
    from openzim_mcp.simple_tools import SimpleToolsHandler

    server = OpenZimMcpServer(test_config)
    if server.simple_tools_handler is None:
        # ``test_config`` opens advanced mode; the simple-mode handler
        # we want to exercise has to be constructed explicitly.
        server.simple_tools_handler = SimpleToolsHandler(server.zim_operations)
    handler = server.simple_tools_handler

    # Title index says the canonical entry exists with score 1.0.
    monkeypatch.setattr(
        handler.zim_operations,
        "find_entry_by_title_data",
        lambda zim_file_path, topic, cross_file=False, limit=3: {
            "results": [
                {"path": "Berlin", "title": "Berlin", "score": 1.0},
            ]
        },
    )
    promoted = handler._find_title_match_for_topic("/fake.zim", "Berlin")
    assert promoted == {"path": "Berlin", "title": "Berlin"}


def test_tell_me_about_does_not_promote_weak_title_match(test_config, monkeypatch):
    """Score < 1.0 (a SuggestionSearcher partial match) must NOT be
    promoted — the disambiguation branch handles ambiguous topics."""
    from openzim_mcp.server import OpenZimMcpServer
    from openzim_mcp.simple_tools import SimpleToolsHandler

    server = OpenZimMcpServer(test_config)
    if server.simple_tools_handler is None:
        # ``test_config`` opens advanced mode; the simple-mode handler
        # we want to exercise has to be constructed explicitly.
        server.simple_tools_handler = SimpleToolsHandler(server.zim_operations)
    handler = server.simple_tools_handler
    monkeypatch.setattr(
        handler.zim_operations,
        "find_entry_by_title_data",
        lambda zim_file_path, topic, cross_file=False, limit=3: {
            "results": [
                {"path": "Java_(programming_language)", "title": "Java", "score": 0.95},
            ]
        },
    )
    promoted = handler._find_title_match_for_topic("/fake.zim", "Java")
    assert promoted is None


# ---------------------------------------------------------------------------
# D10: zim_query.cursor decodes to options["offset"]
# ---------------------------------------------------------------------------


def test_handle_zim_query_decodes_cursor_into_offset(test_config, monkeypatch):
    """A v2 Phase B cursor passed via ``options["cursor"]`` decodes to
    its embedded ``s.o`` offset and forwards to the downstream handler."""
    from openzim_mcp.server import OpenZimMcpServer
    from openzim_mcp.simple_tools import SimpleToolsHandler

    server = OpenZimMcpServer(test_config)
    if server.simple_tools_handler is None:
        # ``test_config`` opens advanced mode; the simple-mode handler
        # we want to exercise has to be constructed explicitly.
        server.simple_tools_handler = SimpleToolsHandler(server.zim_operations)
    handler = server.simple_tools_handler

    # Encode an arbitrary cursor with offset=42.
    payload = {"v": 2, "t": "browse_namespace", "s": {"o": 42, "l": 50, "ns": "C"}}
    raw = json.dumps(payload).encode("utf-8")
    cursor = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    captured: dict = {}

    def fake_browse(zim_file_path, namespace, limit, offset):
        captured["offset"] = offset
        captured["namespace"] = namespace
        return ""

    monkeypatch.setattr(handler.zim_operations, "browse_namespace", fake_browse)
    monkeypatch.setattr(
        handler,
        "_auto_select_zim_file",
        lambda: str(next(iter(test_config.allowed_directories))) + "/test.zim",
    )

    handler.handle_zim_query(
        "browse namespace C",
        options={"cursor": cursor, "limit": 50, "compact": False},
    )
    assert captured.get("offset") == 42


def test_handle_zim_query_rejects_garbage_cursor(test_config):
    """A malformed cursor surfaces a structured error message rather
    than silently dropping into the default offset=0 path."""
    from openzim_mcp.server import OpenZimMcpServer
    from openzim_mcp.simple_tools import SimpleToolsHandler

    server = OpenZimMcpServer(test_config)
    if server.simple_tools_handler is None:
        # ``test_config`` opens advanced mode; the simple-mode handler
        # we want to exercise has to be constructed explicitly.
        server.simple_tools_handler = SimpleToolsHandler(server.zim_operations)
    out = server.simple_tools_handler.handle_zim_query(
        "browse namespace C",
        options={"cursor": "not-a-valid-cursor", "compact": False},
    )
    assert isinstance(out, str)
    assert "Invalid Cursor" in out


# ---------------------------------------------------------------------------
# D11: metadata preview cap actually applies to long values
# ---------------------------------------------------------------------------


def test_metadata_cap_applies_to_long_entry_values(test_config, monkeypatch):
    """A metadata entry whose content exceeds the cap is truncated with
    a ``[truncated, N chars total]`` marker."""
    from openzim_mcp.server import OpenZimMcpServer
    from openzim_mcp.simple_tools import SimpleToolsHandler

    server = OpenZimMcpServer(test_config)
    if server.simple_tools_handler is None:
        # ``test_config`` opens advanced mode; the simple-mode handler
        # we want to exercise has to be constructed explicitly.
        server.simple_tools_handler = SimpleToolsHandler(server.zim_operations)
    ops = server.zim_operations

    # Build a mock archive that returns a 5000-char ``Title`` blob —
    # the Wikipedia ZIM scenario that prompted D11.
    long_content = "x" * 5000

    mock_item = MagicMock()
    mock_item.content = long_content.encode("utf-8")
    mock_entry = MagicMock()
    mock_entry.get_item.return_value = mock_item
    mock_entry.is_redirect = False

    def fake_get_entry_by_path(path):
        if path == "M/Title":
            return mock_entry
        # Other M/ entries don't exist for this test.
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path
    mock_archive.entry_count = 100
    mock_archive.all_entry_count = 100
    mock_archive.article_count = 50
    mock_archive.media_count = 50

    metadata = ops._extract_zim_metadata(mock_archive)
    title = metadata["metadata_entries"]["Title"]
    assert len(title) <= _METADATA_PREVIEW_CAP + 50  # cap + marker tail
    assert "[truncated, 5,000 chars total]" in title


def test_metadata_short_value_not_capped(test_config):
    """Values shorter than the cap pass through verbatim."""
    from openzim_mcp.server import OpenZimMcpServer
    from openzim_mcp.simple_tools import SimpleToolsHandler

    server = OpenZimMcpServer(test_config)
    if server.simple_tools_handler is None:
        # ``test_config`` opens advanced mode; the simple-mode handler
        # we want to exercise has to be constructed explicitly.
        server.simple_tools_handler = SimpleToolsHandler(server.zim_operations)
    ops = server.zim_operations

    short = "Wikipedia"
    mock_item = MagicMock()
    mock_item.content = short.encode("utf-8")
    mock_entry = MagicMock()
    mock_entry.get_item.return_value = mock_item
    mock_entry.is_redirect = False

    def fake_get_entry_by_path(path):
        if path == "M/Creator":
            return mock_entry
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path
    mock_archive.entry_count = 100
    mock_archive.all_entry_count = 100
    mock_archive.article_count = 50
    mock_archive.media_count = 50

    metadata = ops._extract_zim_metadata(mock_archive)
    assert metadata["metadata_entries"]["Creator"] == "Wikipedia"
