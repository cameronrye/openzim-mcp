"""Field-report fixes: response caps, payload size, and bundle sectioning.

Covers the ``caps-and-size`` group of the v3.3.1 real-world sweep:

* fid 44 / fid 45 — ``_cap_response_size`` sliced the rendered response with
  a blind ``text[:keep]``. On the JSON-rendered intents that severed a string
  literal (the body no longer parsed) and deleted the trailing
  ``next_cursor`` / ``_meta`` that the appended footer then told the caller to
  page with; on the binary intent it cut base64 mid-quantum, so a caller that
  decoded the field got a corrupt file. Both are the same slice.
* fid 54 — a ``## `` heading lifted verbatim out of archive prose into a
  ``Snippet:`` block renders as tool-response structure between the numbered
  results.
* fid 115 — the strict single-space heading matcher could skip forward to a
  duplicate heading further down the document, poisoning the monotonic cursor
  so every later heading was lost and one section served another's prose.
* fid 117 — a structural container heading (one immediately followed by a
  same-level heading) was silently dropped from the bundle, so ``view="toc"``
  refused to list a heading ``view="full"`` emits.
* fid 123 — ``zim_get(binary=True)`` had no ceiling on ``max_content_length``.
* fid 124 — ``_meta.tokens_est`` tiktoken-encoded the whole serialized
  payload, base64 included.

Every test here drives the real object end to end (the handler, the bundle
extractor, the registered tool) and asserts on the rendered output rather
than calling a helper with a hand-made keyword argument.
"""

from __future__ import annotations

import base64
import json
import re
from types import MethodType
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from openzim_mcp.bundle import extract_entry_bundle
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.meta import _raw_tokens_est, build_meta
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.tools.zim_get import MAX_BINARY_CONTENT_LENGTH
from openzim_mcp.zim.search import _SearchMixin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FOOTER_RE = re.compile(
    r"\n\n---\n_Response truncated at [\d,]+ chars \(was [\d,]+\)\..*?_", re.DOTALL
)


def _strip_footer(text: str) -> str:
    """Return the response body with the outer truncation footer removed."""
    return _FOOTER_RE.sub("", text)


def _body_json(text: str) -> Any:
    """Parse the JSON body of a compact-mode response.

    Strips the truncation footer, the ``<!-- intent=... -->`` telemetry
    marker and the ``> ~N tokens`` meta footer that are appended *after* the
    size cap, then parses what is left. A blind character slice leaves this
    raising ``json.JSONDecodeError``.
    """
    body = _strip_footer(text)
    body = re.sub(r"\n<!-- intent=.*", "", body, flags=re.DOTALL)
    return json.loads(body.strip())


def _make_handler(**backend: Any) -> SimpleToolsHandler:
    mock = MagicMock()
    mock.list_zim_files_data.return_value = [{"path": "/zim/test.zim"}]
    for name, value in backend.items():
        getattr(mock, name).return_value = value
    return SimpleToolsHandler(mock)


def _browse_payload(
    rows: int, *, next_cursor: str = "eyJ2IjoyLCJ0IjoiYnJvd3NlIn0"
) -> str:
    """A ``browse_namespace`` response in the exact shape the backend emits."""
    return json.dumps(
        {
            "namespace": "C",
            "results": [
                {
                    "path": f"iep.utm.edu/article-with-a-long-path-{i:04d}/",
                    "title": f"Article Number {i:04d} | Internet Encyclopedia",
                    "content_type": "text/html",
                    "preview": "",
                }
                for i in range(rows)
            ],
            "next_cursor": next_cursor,
            "total": 3178,
            "done": False,
            "page_info": {"offset": 0, "limit": rows, "returned_count": rows},
            "_meta": {"chars": 1234, "truncated": False, "tokens_est": 456},
        },
        indent=2,
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# fid 44 — JSON-rendered intents must survive the compact cap
# ---------------------------------------------------------------------------


class TestCompactCapKeepsJsonParseable:
    """`browse namespace C` at default arguments returned unparseable JSON."""

    def test_browse_body_still_parses_and_keeps_its_cursor(self) -> None:
        handler = _make_handler(browse_namespace=_browse_payload(60))
        out = handler.handle_zim_query("browse namespace C", options={"compact": True})

        assert "Response truncated" in out, out[-400:]
        payload = _body_json(out)
        # Positive: the continuation cursor and the envelope survive.
        assert payload["next_cursor"] == "eyJ2IjoyLCJ0IjoiYnJvd3NlIn0"
        assert payload["total"] == 3178
        assert isinstance(payload["_meta"], dict)
        # The rows that DID ship are whole rows, not a severed prefix.
        assert payload["results"], "expected at least one surviving row"
        for row in payload["results"]:
            assert set(row) == {"path", "title", "content_type", "preview"}
        assert len(payload["results"]) < 60
        # And the body says so, instead of claiming completeness.
        assert payload["truncated"] is True
        assert payload["_meta"]["truncated"] is True
        assert payload["_meta"]["rows_omitted"] == 60 - len(payload["results"])
        # The page's own count must not assert rows that are no longer there.
        assert payload["page_info"]["returned_count"] == len(payload["results"])

    def test_footer_names_a_route_that_exists(self) -> None:
        """The generic footer points at a cursor; when rows were dropped the
        cursor skips them, so the footer must name the smaller-limit route."""
        handler = _make_handler(browse_namespace=_browse_payload(60))
        out = handler.handle_zim_query("browse namespace C", options={"compact": True})
        assert "result rows were dropped" in out
        assert "smaller `limit`" in out

    def test_response_stays_within_the_budget(self) -> None:
        handler = _make_handler(browse_namespace=_browse_payload(60))
        out = handler.handle_zim_query(
            "browse namespace C", options={"compact": True, "compact_budget": "tiny"}
        )
        body = out.split("\n<!-- intent=")[0]
        assert len(body) <= 2_000
        payload = _body_json(out)
        assert payload["next_cursor"] == "eyJ2IjoyLCJ0IjoiYnJvd3NlIn0"


class TestCompactCapKeepsMarkdownListings:
    """`walk namespace C` renders markdown whose cursor line is the LAST
    line, so a character slice is exactly what removes it."""

    def _walk_data(self, rows: int) -> Dict[str, Any]:
        return {
            "namespace": "C",
            "results": [
                {
                    "path": f"iep.utm.edu/entry-{i:04d}/",
                    "title": f"Entry {i:04d} | Internet Encyclopedia of Philosophy",
                }
                for i in range(rows)
            ],
            "next_cursor": "eyJ2IjoyLCJ0Ijoid2Fsa19uYW1lc3BhY2UifQ",
            "done": False,
            "page_info": {"offset": 0, "limit": rows, "returned_count": rows},
            "scanned_count": rows,
            "archive_entry_count": 3178,
            "namespace_entry_count": 3178,
        }

    def test_trailing_cursor_line_survives(self) -> None:
        handler = _make_handler(walk_namespace_data=self._walk_data(200))
        out = handler.handle_zim_query("walk namespace C", options={"compact": True})

        assert "Response truncated" in out
        assert "Pass `cursor=eyJ2IjoyLCJ0Ijoid2Fsa19uYW1lc3BhY2UifQ`" in out
        # Positive/negative pair: real bullets shipped, and none of them is
        # a half-emitted line.
        body = _strip_footer(out)
        bullets = [ln for ln in body.splitlines() if ln.startswith("- ")]
        assert len(bullets) >= 10
        for line in bullets:
            assert line.endswith(("`", "`)")), line
            assert line.count("`") % 2 == 0, line
            assert line.count("**") % 2 == 0, line
        # The cursor skips the bullets that were cut, so the footer names the
        # route that recovers them rather than the one that does not.
        assert "result rows were dropped" in out
        assert "smaller `limit`" in out

    def test_body_stays_within_budget(self) -> None:
        handler = _make_handler(walk_namespace_data=self._walk_data(200))
        out = handler.handle_zim_query(
            "walk namespace C", options={"compact": True, "compact_budget": "small"}
        )
        body = out.split("\n<!-- intent=")[0]
        assert len(body) <= 4_000


# ---------------------------------------------------------------------------
# fid 45 — the binary intent must not hand back corrupt base64
# ---------------------------------------------------------------------------

_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + bytes(range(256)) * 40
    + b"\xff\xd9"
)


def _binary_payload() -> str:
    return json.dumps(
        {
            "path": "iep.utm.edu/wp-content/media/anselm.jpg",
            "title": "iep.utm.edu/wp-content/media/anselm.jpg",
            "mime_type": "image/jpeg",
            "size": len(_JPEG),
            "size_human": "10.05 KB",
            "encoding": "base64",
            "data": base64.b64encode(_JPEG).decode("ascii"),
            "truncated": False,
            "_meta": {"chars": 1, "truncated": False, "tokens_est": 1},
        },
        indent=2,
        ensure_ascii=False,
    )


class TestBinaryIntentTruncation:
    def test_base64_that_ships_is_decodable_and_declared_truncated(self) -> None:
        handler = _make_handler(get_binary_entry=_binary_payload())
        out = handler.handle_zim_query(
            "get binary content of iep.utm.edu/wp-content/media/anselm.jpg",
            options={"compact": True},
        )

        assert "Response truncated" in out
        payload = _body_json(out)
        data = payload["data"]
        assert data, "expected a base64 prefix, not an empty field"
        # Positive: what shipped decodes cleanly and is a real prefix of the
        # source bytes. Pre-fix this raised binascii.Error / lost a byte.
        decoded = base64.b64decode(data, validate=True)
        assert _JPEG.startswith(decoded)
        # Negative: the payload no longer claims to be complete.
        assert payload["truncated"] is True
        assert payload["size"] == len(_JPEG)

    def test_footer_does_not_offer_a_cursor_for_a_byte_fetch(self) -> None:
        handler = _make_handler(get_binary_entry=_binary_payload())
        out = handler.handle_zim_query(
            "get binary content of iep.utm.edu/wp-content/media/anselm.jpg",
            options={"compact": True},
        )
        assert "Pass `compact=False` to opt out of size caps." in out
        assert "Page using the cursor in the body above" not in out
        assert "tighten the query" not in out


class TestProseTruncationIsUnchanged:
    """The structural path must not steal the prose path's behaviour: a
    paragraph with no bullets and no JSON is still cut at the budget."""

    def test_prose_is_still_cut_at_the_character_budget(self) -> None:
        text = "Word " * 4000
        out = SimpleToolsHandler._cap_response_size(text, 6000, intent="tell_me_about")
        assert len(out) <= 6000
        assert out.startswith("Word Word Word")
        assert "Response truncated at 6,000 chars" in out


# ---------------------------------------------------------------------------
# fid 54 — archive prose must not inject headings into the result list
# ---------------------------------------------------------------------------


class TestSnippetHeadingsAreNeutralised:
    def _search_payload(self) -> Dict[str, Any]:
        return {
            "query": "aspirin quiz",
            "results": [
                {
                    "path": "medlineplus.gov/coronaryarterydisease.html",
                    "title": "Coronary Artery Disease | CAD | MedlinePlus",
                    "snippet": (
                        "  * Coronary Artery Disease Quiz (Medical Encyclopedia) "
                        "Also in Spanish\n\n## Clinical Trials \n\n"
                        "  * ClinicalTrials.gov: Coronary Artery Disease"
                    ),
                },
                {
                    "path": "medlineplus.gov/heartdiseases.html",
                    "title": "Heart Disease | MedlinePlus",
                    "snippet": "  * Heart Palpitations Quiz\n\n## Statistics and Research \n",
                },
            ],
            "total": 2,
            "done": True,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 2},
        }

    def test_prose_headings_do_not_become_result_headings(self) -> None:
        handler = _make_handler(search_zim_file_data=self._search_payload())
        # The REAL backend renderer builds the ``## N. Title / Path: /
        # Snippet:`` shape; it uses no instance state, so binding it to the
        # stub keeps this an end-to-end drive of the rendering pipeline.
        handler.zim_operations._format_search_text = MethodType(
            _SearchMixin._format_search_text, handler.zim_operations
        )
        out = handler.handle_zim_query(
            "search for aspirin quiz", options={"compact": True}
        )

        headings = [ln for ln in out.splitlines() if re.match(r"^#{1,6} ", ln)]
        numbered = [ln for ln in headings if re.match(r"^## \d+\. ", ln)]
        # Positive: the two real results are still numbered headings.
        assert len(numbered) == 2, out
        # Negative: nothing else is.
        assert headings == numbered, headings
        # And the prose itself is still delivered, just not as structure.
        assert "Clinical Trials" in out
        assert "Statistics and Research" in out


# ---------------------------------------------------------------------------
# fid 115 / fid 117 — bundle sectioning
# ---------------------------------------------------------------------------

# html2text renders ``<h3>d. Responsibility as a Virtue</h3>`` with TWO
# spaces after the hashes when the heading carries inline markup, and with
# one when it does not. The IEP article ``iep.utm.edu/responsi/`` carries
# both spellings of the same heading text — the two-space one in section 2,
# the one-space one 20k chars later in section 4. The strict matcher only
# accepts the single-space form, so it skipped forward to the LATER heading
# and left the monotonic cursor past everything in between.
_DUPLICATE_HEADING_HTML = """
<html><body><main>
<h1>Responsibility</h1>
<p>Lead prose.</p>
<h2>2. Individual Responsibility</h2>
<p>Individual prose.</p>
<h3><em>d. Responsibility as a Virtue</em></h3>
<p>INDIVIDUAL virtue prose about one person's character.</p>
<h2>3. Moral versus Legal Responsibility</h2>
<p>Legal prose.</p>
<h2>4. Collective Responsibility</h2>
<p>Collective prose.</p>
<h3>d. Responsibility as a Virtue</h3>
<p>COLLECTIVE virtue prose about groups, companies and states.</p>
</main></body></html>
"""

# A heading immediately followed by a same-level heading: a structural
# container with no prose of its own. IEP builds every multi-part article
# this way (``2. Phenomenology and Existentialism`` then ``a. Introduction``).
_CONTAINER_HEADING_HTML = """
<html><body><main>
<h1>Aesthetics</h1>
<p>Lead prose.</p>
<h2>2. Phenomenology and Existentialism</h2>
<h2>a. Introduction</h2>
<p>Phenomenology introduction prose.</p>
<h2>b. Heidegger</h2>
<p>Heidegger prose.</p>
<h2>3. Hermeneutics</h2>
<h2>a. Introduction</h2>
<p>Hermeneutics introduction prose.</p>
</main></body></html>
"""


def _bundle_for(cp: ContentProcessor, html: str) -> Any:
    archive = MagicMock()
    entry = MagicMock()
    entry.is_redirect = False
    entry.path = "A/Test"
    entry.title = "Test"
    item = MagicMock()
    item.mimetype = "text/html"
    item.content = memoryview(html.encode("utf-8"))
    item.title = "Test"
    entry.get_item.return_value = item
    archive.get_entry_by_path.return_value = entry
    return extract_entry_bundle(archive, "A/Test", content_processor=cp)


@pytest.fixture
def cp() -> ContentProcessor:
    from openzim_mcp.config import OpenZimMcpConfig

    config = OpenZimMcpConfig(allowed_directories=["/tmp"])
    return ContentProcessor(config.content)


class TestDuplicateHeadingDoesNotPoisonTheCursor:
    def test_all_headings_are_located(self, cp: ContentProcessor) -> None:
        bundle = _bundle_for(cp, _DUPLICATE_HEADING_HTML)
        titles = [s["title"] for s in bundle["sections"]]
        # Positive: every heading in the rendered body is in the outline.
        assert "3. Moral versus Legal Responsibility" in titles
        assert "4. Collective Responsibility" in titles
        assert titles.count("d. Responsibility as a Virtue") == 2

    def test_each_duplicate_serves_its_own_prose(self, cp: ContentProcessor) -> None:
        bundle = _bundle_for(cp, _DUPLICATE_HEADING_HTML)
        md = bundle["rendered_markdown"]
        virtues = [
            s
            for s in bundle["sections"]
            if s["title"] == "d. Responsibility as a Virtue"
        ]
        assert len(virtues) == 2
        first = md[virtues[0]["char_start"] : virtues[0]["char_end"]]
        second = md[virtues[1]["char_start"] : virtues[1]["char_end"]]
        # The first occurrence must NOT serve the second's text.
        assert "INDIVIDUAL virtue prose" in first
        assert "COLLECTIVE virtue prose" not in first
        assert "COLLECTIVE virtue prose" in second

    def test_parent_section_is_not_a_fused_blob(self, cp: ContentProcessor) -> None:
        bundle = _bundle_for(cp, _DUPLICATE_HEADING_HTML)
        md = bundle["rendered_markdown"]
        h2 = next(
            s
            for s in bundle["sections"]
            if s["title"] == "2. Individual Responsibility"
        )
        body = md[h2["char_start"] : h2["char_end"]]
        assert "Individual prose" in body
        assert "Collective Responsibility" not in body


class TestContainerHeadingsStayInTheOutline:
    def test_container_headings_are_listed(self, cp: ContentProcessor) -> None:
        bundle = _bundle_for(cp, _CONTAINER_HEADING_HTML)
        titles = [s["title"] for s in bundle["sections"]]
        assert "2. Phenomenology and Existentialism" in titles
        assert "3. Hermeneutics" in titles
        # Positive control: the ambiguous children are still there too, and
        # the outline is no longer a flat list of indistinguishable entries.
        assert titles.count("a. Introduction") == 2

    def test_every_rendered_heading_is_listed(self, cp: ContentProcessor) -> None:
        """``view="full"`` must not emit a heading ``view="toc"`` refuses."""
        bundle = _bundle_for(cp, _CONTAINER_HEADING_HTML)
        md = bundle["rendered_markdown"]
        rendered = {
            re.sub(r"\\(.)", r"\1", m.group(1)).strip()
            for m in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", md)
        }
        listed = {s["title"] for s in bundle["sections"]}
        assert rendered <= listed, rendered - listed

    def test_sections_stay_ordered_and_non_overlapping(
        self, cp: ContentProcessor
    ) -> None:
        bundle = _bundle_for(cp, _CONTAINER_HEADING_HTML)
        sections = bundle["sections"]
        md_len = len(bundle["rendered_markdown"])
        starts = [s["char_start"] for s in sections]
        assert starts == sorted(starts)
        for s in sections:
            assert 0 <= s["char_start"] <= s["char_end"] <= md_len


# ---------------------------------------------------------------------------
# fid 124 — token estimation must not tokenise a multi-megabyte blob
# ---------------------------------------------------------------------------


class TestTokenEstimationIsBounded:
    def test_large_payload_is_not_handed_to_tiktoken(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point is that tiktoken never sees the big string."""
        seen: List[int] = []
        real = _raw_tokens_est.__globals__["_get_encoder"]()
        if real is None:  # pragma: no cover — sandboxed env without tiktoken
            pytest.skip("tiktoken unavailable")

        class _Spy:
            def encode(self, text: str, **kw: Any) -> List[int]:
                seen.append(len(text))
                return real.encode(text, **kw)

        monkeypatch.setattr("openzim_mcp.meta._get_encoder", lambda: _Spy())

        blob = base64.b64encode(b"\x00\x01\x02\x03" * 400_000).decode("ascii")
        assert len(blob) > 2_000_000
        est = _raw_tokens_est(blob)

        assert seen, "expected a bounded sample to still be tokenised"
        assert max(seen) <= 200_000, seen
        assert sum(seen) < len(blob) // 4
        # Positive: the estimate is still in the right ballpark for base64
        # (cl100k averages ~1.4 chars per token on it), not a char/4 guess.
        assert est is not None
        assert len(blob) / 2.5 < est < len(blob)

    def test_small_payloads_are_still_counted_exactly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = _raw_tokens_est.__globals__["_get_encoder"]()
        if real is None:  # pragma: no cover
            pytest.skip("tiktoken unavailable")
        text = "The quick brown fox jumps over the lazy dog. " * 100
        assert _raw_tokens_est(text) == len(real.encode(text, disallowed_special=()))

    def test_build_meta_reports_the_real_char_count(self) -> None:
        blob = "A" * 1_000_000
        meta = build_meta(rendered=blob)
        assert meta["chars"] == 1_000_000
        assert meta["tokens_est"] > 0


# ---------------------------------------------------------------------------
# fid 123 — the binary branch needs a ceiling on max_content_length
# ---------------------------------------------------------------------------


class _Recorder:
    """Stands in for the registered tool so the decorator can capture it."""

    def __init__(self) -> None:
        self.fn: Any = None

    def tool(self, **kwargs: Any) -> Any:
        def _wrap(fn: Any) -> Any:
            self.fn = fn
            return fn

        return _wrap


@pytest.fixture
def zim_get_tool(monkeypatch: pytest.MonkeyPatch) -> Any:
    from unittest.mock import AsyncMock

    from openzim_mcp.tools import zim_get as zim_get_module

    ops = MagicMock()
    ops.get_binary_entry_data = AsyncMock(return_value={"binary": True})
    ops.get_zim_entry_data = AsyncMock(return_value={"text": True})
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations", lambda _ops: ops
    )
    recorder = _Recorder()
    server = MagicMock()
    server.mcp = recorder
    zim_get_module.register(server)
    assert recorder.fn is not None
    return recorder.fn, ops


@pytest.mark.asyncio
class TestBinaryFetchCeiling:
    async def test_absurd_max_content_length_is_refused(
        self, zim_get_tool: Any
    ) -> None:
        fn, ops = zim_get_tool
        result = await fn(
            zim_file_path="/zim/test.zim",
            entry_path="video.mp4",
            binary=True,
            max_content_length=100_000_000,
        )
        assert result["error"] is True
        assert result["operation"] == "invalid_max_content_length"
        # The message must name the ceiling, not another number to raise to.
        assert f"{MAX_BINARY_CONTENT_LENGTH:,}" in result["message"]
        assert "raise" not in result["message"]
        # The refusal happens before any read: no 68 MB payload is built.
        ops.get_binary_entry_data.assert_not_called()

    async def test_a_request_under_the_ceiling_still_reaches_the_data_layer(
        self, zim_get_tool: Any
    ) -> None:
        fn, ops = zim_get_tool
        out = await fn(
            zim_file_path="/zim/test.zim",
            entry_path="doc.pdf",
            binary=True,
            max_content_length=20_000_000,
        )
        assert out == {"binary": True}
        ops.get_binary_entry_data.assert_awaited_once_with(
            "/zim/test.zim", "doc.pdf", max_size_bytes=20_000_000
        )

    async def test_ceiling_does_not_apply_to_the_text_branch(
        self, zim_get_tool: Any
    ) -> None:
        """``max_content_length`` on a text body is a character cap on a
        paginable field, not a base64 blob — it keeps its old range."""
        fn, ops = zim_get_tool
        result = await fn(
            zim_file_path="/zim/test.zim",
            entry_path="A/Long",
            max_content_length=100_000_000,
        )
        assert result == {"text": True}
        ops.get_zim_entry_data.assert_awaited_once()
