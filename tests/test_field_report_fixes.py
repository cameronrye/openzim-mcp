"""Regression tests for defects found by the v3.3.1 real-world field report.

Each test drives the REAL entry point end to end and asserts on the RENDERED
output, not on a renderer called with an explicit keyword. That distinction
matters here: several past rounds in this repo shipped gates that proved a
renderer behaves *when told* something and proved nothing about it ever being
told. Where a flag has a safe default, the test therefore exercises both the
flag-set and flag-clear cases so it cannot pass by emitting the signal
unconditionally.
"""

from functools import partial
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.zim.search import _SearchMixin


def _search_payload(
    *,
    reason: Optional[str],
    results: List[Dict[str, Any]],
    suggestions: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Build a ``search_zim_file_data`` payload with a chosen ``_meta.reason``.

    Mirrors the wire shape ``openzim_mcp/zim/search.py`` produces: ``reason``
    lives under ``_meta`` alongside the suggestion pool, and ``results`` carries
    the ranked hits.
    """
    meta: Dict[str, Any] = {}
    if reason is not None:
        meta["reason"] = reason
    if suggestions is not None:
        meta["suggestions"] = suggestions
    return {
        "query": "metformin dosage",
        "results": results,
        "total": len(results),
        "done": True,
        "next_cursor": None,
        "page_info": {"offset": 0, "limit": 10, "returned_count": len(results)},
        "_meta": meta,
    }


# Nine supplement monographs — the real MedlinePlus response to
# "metformin dosage", none of which token-match the query. This is the
# observed shape the field report captured, not an invented one.
_WEAK_HITS: List[Dict[str, Any]] = [
    {
        "path": "medlineplus.gov/druginfo/natural/97.html",
        "title": "Black Psyllium: MedlinePlus Supplements",
        "snippet": "Black psyllium is a herb.",
    },
    {
        "path": "medlineplus.gov/druginfo/natural/866.html",
        "title": "Blond Psyllium: MedlinePlus Supplements",
        "snippet": "Blond psyllium is a herb.",
    },
    {
        "path": "medlineplus.gov/druginfo/natural/78.html",
        "title": "Bee Pollen: MedlinePlus Supplements",
        "snippet": "Bee pollen is a food.",
    },
]

_STRONG_HITS: List[Dict[str, Any]] = [
    {
        "path": "medlineplus.gov/druginfo/meds/a696005.html",
        "title": "Metformin: MedlinePlus Drug Information",
        "snippet": "Metformin is used to treat type 2 diabetes.",
    },
]


class TestLowRelevanceReachesTheNaturalLanguageSurface:
    """``low_relevance`` must survive the trip to ``zim_query``'s output.

    The backend computes the verdict (``zim/search.py``), the footer branch
    that renders it already exists (``meta.py``), and ``_handle_search``
    dropped it on the floor for every non-empty result set — so simple mode,
    where ``zim_query`` is the only tool, presented nine irrelevant supplement
    monographs as a confident complete answer.
    """

    @pytest.fixture
    def ops(self) -> Mock:
        """A stubbed backend that still renders through the REAL formatter.

        Only the data-fetch call is faked. ``_format_search_text`` is bound to
        the genuine implementation so the assertions below run against the
        markdown a real client receives, not against a Mock's repr.
        """
        mock = Mock()
        mock.list_zim_files.return_value = (
            '[{"path": "/test/file.zim", "name": "file.zim"}]'
        )
        mock._format_search_text = partial(_SearchMixin._format_search_text, mock)
        return mock

    def _run(self, ops: Mock, payload: Dict[str, Any]) -> str:
        """Drive the real ``handle_zim_query`` with a stubbed backend."""
        ops.search_zim_file_data.return_value = payload
        handler = SimpleToolsHandler(ops)
        # ``compact=True`` is the shape ``zim_query`` actually runs in — it is
        # the default the MCP tool passes, and the only branch that consults
        # the structured payload's ``_meta``.
        result = handler.handle_zim_query(
            "search for metformin dosage",
            "/test/file.zim",
            {"compact": True},
        )
        assert isinstance(result, str), result
        return result

    def test_weak_hits_are_flagged_in_the_rendered_output(self, ops: Mock) -> None:
        """A low-relevance result set must not read as a confident answer."""
        rendered = self._run(
            ops, _search_payload(reason="low_relevance", results=_WEAK_HITS)
        )
        # Positive: the caller is told the hits are weak. Paired with the
        # negative below so "renders nothing at all" cannot satisfy this.
        assert "weak" in rendered.lower() or "low relevance" in rendered.lower(), (
            "rendered output carries no low-relevance signal:\n" + rendered
        )
        # The hits themselves are still returned — this is a caveat, not a
        # suppression.
        assert "Black Psyllium" in rendered

    def test_strong_hits_are_not_flagged(self, ops: Mock) -> None:
        """The signal must be conditional, or the previous test is vacuous."""
        rendered = self._run(ops, _search_payload(reason=None, results=_STRONG_HITS))
        assert "low relevance" not in rendered.lower()
        assert "Metformin" in rendered

    def test_backend_suggestions_survive_alongside_the_flag(self, ops: Mock) -> None:
        """A low-relevance response keeps the recovery pool it was given."""
        rendered = self._run(
            ops,
            _search_payload(
                reason="low_relevance",
                results=_WEAK_HITS,
                suggestions=[{"type": "alt_spelling", "value": "glucophage"}],
            ),
        )
        # ``glucophage`` appears nowhere but the suggestion pool, so this
        # cannot be satisfied by the query echo the way "metformin" would be.
        assert "suggestions for glucophage" in rendered, rendered


class TestInboundLinkQuestionsGetInboundAnswers:
    """ "What links TO x" must not be answered with what x links FROM.

    Simple mode had no inbound concept at all: every inbound phrasing fell
    through to the outbound ``related`` / ``links`` intents and was rendered
    under a header asserting the opposite direction. The archive ships a
    ``.linkgraph.sqlite`` sidecar that answers the real question in
    milliseconds, and ``zim_links(direction="inbound")`` already uses it — so
    the data was present and simply unreachable from the only tool simple
    mode exposes.
    """

    INBOUND_PHRASINGS = [
        "what links to iep.utm.edu/plato/",
        "inbound links to iep.utm.edu/plato/",
        "backlinks for iep.utm.edu/plato/",
        "which articles link to iep.utm.edu/plato/",
        "articles linking to iep.utm.edu/plato/",
    ]

    OUTBOUND_PHRASINGS = [
        "what links from iep.utm.edu/plato/",
        "links in iep.utm.edu/plato/",
    ]

    @pytest.mark.parametrize("query", INBOUND_PHRASINGS)
    def test_inbound_phrasings_parse_to_the_inbound_intent(self, query: str) -> None:
        intent, _params, _conf = IntentParser.parse_intent(query)
        assert intent == "inbound_links", f"{query!r} parsed as {intent!r}"

    @pytest.mark.parametrize("query", OUTBOUND_PHRASINGS)
    def test_outbound_phrasings_stay_outbound(self, query: str) -> None:
        """Direction words must actually discriminate, or the above is vacuous."""
        intent, _params, _conf = IntentParser.parse_intent(query)
        assert intent != "inbound_links", f"{query!r} wrongly parsed as inbound"

    def test_inbound_query_calls_the_inbound_backend(self) -> None:
        """End to end: the handler must hit the sidecar, not the outbound path."""
        ops = Mock()
        ops.get_inbound_links_data.return_value = {
            "entry_path": "iep.utm.edu/plato/",
            "results": [
                {"path": "iep.utm.edu/aristotle/", "title": "Aristotle"},
            ],
            "total": 97,
            "done": False,
            "next_cursor": None,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 1},
        }
        handler = SimpleToolsHandler(ops)
        rendered = handler.handle_zim_query(
            "what links to iep.utm.edu/plato/", "/test/file.zim"
        )
        assert isinstance(rendered, str), rendered
        ops.get_inbound_links_data.assert_called_once()
        # The outbound backend must NOT have been consulted — paired with the
        # positive assertion above so "called nothing" fails too.
        ops.extract_article_links.assert_not_called()
        # And the rendering must not claim the opposite direction.
        assert "linked from" not in rendered.lower(), rendered


class TestBudgetCutIsNeverReportedAsComplete:
    """A page the response budget cut must never claim to be the last one.

    ``exhausted`` is decided at FETCH time for a whole batch; the response
    budget can break out part-way through RENDERING that batch. Both flags
    then read true, ``done`` follows ``exhausted``, and the
    ``budget_truncated and not done`` gate suppressed the truncation notice
    — so a page that really did withhold rows shipped as complete, with no
    ``next_offset`` and no cursor. That is worse than the unbounded response
    it replaced: the caller cannot even tell it lost data.
    """

    def _collect(self, *, batch_len, want, budget_binds_at):
        """Drive the real collector with a stubbed Xapian search object."""
        from openzim_mcp.zim import search as search_mod

        rows = [f"e{i}" for i in range(batch_len)]

        class _FakeSearch:
            def getResults(self, start, count):  # noqa: N802 - libzim spelling
                return rows[:count]

        mixin = search_mod._SearchMixin.__new__(search_mod._SearchMixin)
        calls = {"n": 0}

        def _row(archive, entry_id, **kw):
            calls["n"] += 1
            # Blow the char budget exactly at the configured row.
            pad = "x" * (10**7 if calls["n"] == budget_binds_at else 1)
            return {"path": str(entry_id), "title": "t", "snippet": pad}

        mixin._search_result_row = _row  # type: ignore[method-assign]
        return search_mod._SearchMixin._collect_distinct_hits(
            mixin,
            _FakeSearch(),
            None,
            "q",
            limit=want,
            offset=0,
            total_results=10_000,
            snippet_length=None,
            max_paragraphs=None,
            validated_path=None,
        )

    def test_mid_batch_budget_break_does_not_mark_the_stream_exhausted(self):
        """The bug: a short batch + a budget break = 'done', silently."""
        _rows, _consumed, exhausted, budget_truncated = self._collect(
            batch_len=5, want=10, budget_binds_at=2
        )
        # Positive: the budget really did bind (else the negative is vacuous).
        assert budget_truncated is True
        # Negative: and the stream must NOT be called exhausted, because rows
        # 3..5 of the fetched batch were never rendered.
        assert exhausted is False

    def test_fully_consumed_short_batch_still_marks_exhausted(self):
        """The discriminator: no budget break means the short batch IS the end."""
        _rows, _consumed, exhausted, budget_truncated = self._collect(
            batch_len=5, want=10, budget_binds_at=None
        )
        assert budget_truncated is False
        assert exhausted is True


class TestTruncationVerdictRequiresAnActualZim:
    """ "Truncated, re-download it" must not be said about a non-archive.

    ``is_truncated_zim`` compared bytes 72..79 as a declared size without ever
    re-checking the ZIM magic — and it is only ever reached AFTER the magic
    check has already failed. So for any readable non-ZIM file of at least 80
    bytes those bytes are effectively random, almost always form a huge value,
    and the listing told the user to re-download a file that was never an
    archive. That inverts the exact remedy distinction the warning exists to
    draw.
    """

    def test_a_plain_text_file_is_not_called_a_truncated_archive(self, tmp_path):
        from openzim_mcp.zim.archive import is_truncated_zim

        # Well over the 80-byte header, no ZIM magic anywhere.
        decoy = tmp_path / "notazim.zim"
        decoy.write_bytes(
            b"This is a plain text file pretending to be an archive. " * 8
        )
        assert is_truncated_zim(decoy) is False

    def test_a_genuinely_short_zim_is_still_called_truncated(self, tmp_path):
        """The discriminator — otherwise the assertion above is vacuous."""
        import struct

        from openzim_mcp.zim.archive import ZIM_MAGIC, is_truncated_zim

        header = bytearray(80)
        header[: len(ZIM_MAGIC)] = ZIM_MAGIC
        # checksumPos declares a file far larger than what is on disk.
        struct.pack_into("<Q", header, 72, 10_000_000)
        short = tmp_path / "half.zim"
        short.write_bytes(bytes(header))
        assert is_truncated_zim(short) is True

    def test_a_zim_header_stub_below_the_header_size_is_truncated(self, tmp_path):
        """A real ZIM always carries a full 80-byte header."""
        from openzim_mcp.zim.archive import ZIM_MAGIC, is_truncated_zim

        stub = tmp_path / "header_only.zim"
        stub.write_bytes(ZIM_MAGIC + b"partial")
        assert is_truncated_zim(stub) is True


class TestConsecutiveBreaksDoNotDoubleTheSeparator:
    """``<br><br>`` in a table cell is one line break, not two separators.

    The flattening pass that turns a cell's ``<br>`` into ``"; "`` fired on
    every break, so a run of two rendered ``HDL; ; Good`` on a real
    MedlinePlus cholesterol page.
    """

    def test_a_run_of_breaks_collapses_to_one_separator(self):
        from bs4 import BeautifulSoup

        from openzim_mcp.content_processor import _flatten_multiline_table_cells

        soup = BeautifulSoup(
            "<table><tr><td>HDL<br><br>Good</td></tr></table>", "html.parser"
        )
        _flatten_multiline_table_cells(soup)
        text = soup.get_text()
        assert "; ;" not in text, text
        # Positive half: the break still became a separator at all.
        assert "HDL; Good" in text, text

    def test_a_single_break_still_separates(self):
        """Discriminator — otherwise the above passes by removing everything."""
        from bs4 import BeautifulSoup

        from openzim_mcp.content_processor import _flatten_multiline_table_cells

        soup = BeautifulSoup(
            "<table><tr><td>5th in Europe<br>1st in Germany</td></tr></table>",
            "html.parser",
        )
        _flatten_multiline_table_cells(soup)
        assert "5th in Europe; 1st in Germany" in soup.get_text()
