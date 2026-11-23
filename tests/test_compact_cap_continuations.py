"""The compact size cap must not advertise a continuation past rows it cut.

Sweep finding (size cap and paging): ``_cap_response_size`` drops whole rows
to fit ``compact_budget``, but it shipped the page's continuation exactly as
the backend minted it — and that continuation points at the page AFTER the
one requested, so every dropped row fell into a gap no advertised call could
reach:

* ``browse namespace A`` on the climate mini fixture shipped 13 of 50 rows
  with ``next_cursor`` still at ``{"o": 50}``: 37 rows never seen, under a
  ``_meta`` still claiming the 15,732 chars of the uncut page;
* ``walk namespace A`` re-attached ``Pass `cursor=...``` after 104 of its 200
  rows were cut;
* ``search for climate`` with ``limit=50`` said "showing 1-50" over rows 1-17,
  and the ``pass `offset=50``` line went with the cut, leaving the footer
  pointing at "the cursor in the body above", which no longer existed.

Each test here follows the continuation a response actually offers (the JSON
``next_cursor``, a markdown ``Pass `cursor=...``` line, or the cap footer's
``offset=``) and checks the rows it reaches, so a continuation that skips rows
fails on the rows themselves rather than on its wording.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest
from libzim.writer import Creator, Hint, Item, StringProvider

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig, RateLimitConfig
from openzim_mcp.meta import _raw_tokens_est
from openzim_mcp.server import OpenZimMcpServer
from tests.conftest_v2_fixtures import _HtmlItem

_ROWS = 80


def _note(i: int) -> str:
    return f"zebra_{i:03d}"


def _html(title: str, body: str) -> str:
    return (
        f"<html><head><title>{title}</title></head><body><main>"
        f"<h1>{title}</h1>{body}</main></body></html>"
    )


class _StyleItem(Item):
    """A stylesheet: an asset the new-scheme ``C`` walk filters out."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path

    def get_path(self) -> str:
        return self._path

    def get_title(self) -> str:
        return ""

    def get_mimetype(self) -> str:
        return "text/css"

    def get_contentprovider(self) -> StringProvider:
        return StringProvider("body { color: black; }")

    def get_hints(self) -> Dict[Hint, int]:
        return {Hint.FRONT_ARTICLE: 0}


def _build(out: Path, *, with_assets: bool = False, hub: bool = False) -> Path:
    """``_ROWS`` short notes that all match ``zebra``.

    ``with_assets`` interleaves a stylesheet after every third note, so a walk
    has to scan more entry ids than it returns rows. ``hub`` adds one article
    linking to every note, for the links listing.
    """
    with Creator(str(out)).config_indexing(True, "eng") as creator:
        for i in range(_ROWS):
            title = f"Zebra field note {i:03d}"
            prose = (
                f"<p>Zebra observation {i:03d}: the herd crossed the river at "
                "dawn, and every zebra in it carried its stripes.</p>"
            )
            creator.add_item(_HtmlItem(_note(i), title, _html(title, prose)))
            if with_assets and i % 3 == 0:
                creator.add_item(_StyleItem(f"{_note(i)}.css"))
        if hub:
            links = "".join(
                f'<li><a href="{_note(i)}">Zebra field note {i:03d}</a></li>'
                for i in range(_ROWS)
            )
            creator.add_item(
                _HtmlItem(
                    "zebra_hub", "Zebra hub", _html("Zebra hub", f"<ul>{links}</ul>")
                )
            )
        creator.set_mainpath(_note(0))
    return out


@pytest.fixture
def plain_zim(tmp_path: Path) -> Path:
    return _build(tmp_path / "plain.zim")


@pytest.fixture
def mixed_zim(tmp_path: Path) -> Path:
    return _build(tmp_path / "mixed.zim", with_assets=True)


@pytest.fixture
def hub_zim(tmp_path: Path) -> Path:
    return _build(tmp_path / "hub.zim", hub=True)


@pytest.fixture
def long_title_zim(tmp_path: Path) -> Path:
    """Entries whose walk rows are each longer than the smallest budget."""
    out = tmp_path / "long_titles.zim"
    with Creator(str(out)).config_indexing(True, "eng") as creator:
        for i in range(5):
            title = f"Zebra field note {i:03d} " + "with an unusually long title " * 15
            creator.add_item(
                _HtmlItem(_note(i), title, _html(title, "<p>Zebra stripes.</p>"))
            )
        creator.set_mainpath(_note(0))
    return out


@pytest.fixture
def query(tmp_path: Path) -> Callable[..., str]:
    """The registered simple-mode ``zim_query`` tool, cache ON.

    Cache on so a fix that rewrote a cached page in place, or ran only on the
    cold path, shows up as a second pass that disagrees with the first.
    """
    server = OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)],
            tool_mode="simple",
            cache=CacheConfig(
                enabled=True,
                persistence_enabled=False,
                persistence_path=str(tmp_path / "cache"),
            ),
            rate_limit=RateLimitConfig(enabled=False),
        )
    )
    fn = server.mcp._tool_manager._tools["zim_query"].fn

    def _call(**kwargs: Any) -> str:
        out = asyncio.run(fn(**kwargs))
        assert isinstance(out, str), out
        return out

    return _call


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_CAP_FOOTER_RE = re.compile(r"\n\n---\n_Response truncated at .*?_(?=\n|$)", re.DOTALL)
_WALK_ROW_RE = re.compile(r"^- \*\*[^\n]*?\*\* \(`([^`]+)`\)$", re.MULTILINE)
_WALK_CURSOR_RE = re.compile(r"Pass `cursor=([A-Za-z0-9_\-=]+)`")
_FOOTER_OFFSET_RE = re.compile(r"pass `offset=(\d+)` to resume")


def _cap_footer(text: str) -> Optional[str]:
    m = _CAP_FOOTER_RE.search(text)
    return m.group(0) if m else None


def _json_body(text: str) -> Dict[str, Any]:
    """The JSON page of a compact response, fence and footers removed."""
    body = _CAP_FOOTER_RE.sub("", text)
    body = re.sub(r"\n<!-- intent=.*", "", body, flags=re.DOTALL)
    payload = json.loads(body[body.index("{") :].strip())
    assert isinstance(payload, dict)
    return payload


def _decode(token: str) -> Dict[str, Any]:
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    decoded = json.loads(raw)
    assert isinstance(decoded, dict)
    return decoded


def _resume_offset(text: str) -> Optional[int]:
    footer = _cap_footer(text) or ""
    m = _FOOTER_OFFSET_RE.search(footer)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# browse — a JSON page whose ``next_cursor`` the cap has to re-point
# ---------------------------------------------------------------------------


def _browse_everything(
    query: Callable[..., str], zim: Path, budget: Any
) -> List[Dict[str, Any]]:
    """Every page a client reaches by following what each response offers."""
    pages: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    offset = 0
    for _ in range(4 * _ROWS):
        kwargs: Dict[str, Any] = {
            "query": "browse namespace C",
            "zim_file_path": str(zim),
            "compact_budget": budget,
        }
        if cursor:
            kwargs["cursor"] = cursor
        elif offset:
            kwargs["offset"] = offset
        out = query(**kwargs)
        payload = _json_body(out)
        pages.append({"text": out, "payload": payload})
        if payload.get("next_cursor"):
            cursor, offset = payload["next_cursor"], 0
            continue
        resume = _resume_offset(out)
        if resume is not None:
            cursor, offset = None, resume
            continue
        return pages
    raise AssertionError("pagination did not terminate")


class TestBrowseContinuation:
    def test_following_the_continuation_visits_every_row_once(
        self, query: Callable[..., str], plain_zim: Path
    ) -> None:
        uncut = _json_body(
            query(
                query="browse namespace C",
                zim_file_path=str(plain_zim),
                limit=200,
                compact_budget=64_000,
            )
        )
        expected = [row["path"] for row in uncut["results"]]
        assert expected == [_note(i) for i in range(_ROWS)]

        first = _browse_everything(query, plain_zim, "tiny")
        seen = [row["path"] for page in first for row in page["payload"]["results"]]
        assert seen == expected
        # Positive control: the cap really did cut pages, including the last
        # one (which has no cursor of its own to re-point).
        cut = [p for p in first if p["payload"].get("_meta", {}).get("rows_omitted")]
        assert len(cut) >= 2
        assert not cut[-1]["payload"]["next_cursor"]

        # The second pass runs on a warm cache and must agree byte for byte.
        second = _browse_everything(query, plain_zim, "tiny")
        assert [p["text"] for p in second] == [p["text"] for p in first]

    def test_a_cut_page_resumes_at_its_first_dropped_row(
        self, query: Callable[..., str], plain_zim: Path
    ) -> None:
        out = query(
            query="browse namespace C",
            zim_file_path=str(plain_zim),
            compact_budget="tiny",
        )
        payload = _json_body(out)
        shipped = len(payload["results"])
        assert 0 < shipped < 50
        state = _decode(payload["next_cursor"])["s"]
        # Negative: not the page the backend minted the cursor for (50).
        assert state["o"] == shipped
        # Positive: every other field is the backend's own.
        assert state["l"] == 50
        assert state["ns"] == "C"
        assert isinstance(state["ai"], str) and state["ai"]
        assert payload["page_info"]["returned_count"] == shipped
        assert payload["_meta"]["rows_omitted"] == 50 - shipped
        assert "the cursor in the body above resumes at the first of them" in out

    def test_meta_measures_the_page_that_shipped(
        self, query: Callable[..., str], plain_zim: Path
    ) -> None:
        payload = _json_body(
            query(
                query="browse namespace C",
                zim_file_path=str(plain_zim),
                compact_budget="tiny",
            )
        )
        shipped = json.dumps(
            {k: v for k, v in payload.items() if k != "_meta"}, ensure_ascii=False
        )
        meta = payload["_meta"]
        assert meta["chars"] == len(shipped)
        raw = _raw_tokens_est(shipped)
        if raw is not None:
            assert meta["tokens_est"] == int(raw * 1.05) + 1
        # Positive control: the page really was cut, so the backend's own
        # figures (for 50 rows) would not have matched.
        assert meta["rows_omitted"] > 0


# ---------------------------------------------------------------------------
# walk — a markdown page whose ``Pass `cursor=…``` line is the continuation
# ---------------------------------------------------------------------------


class TestWalkContinuation:
    def test_following_the_continuation_visits_every_row_once(
        self, query: Callable[..., str], plain_zim: Path
    ) -> None:
        seen: List[str] = []
        cut_pages = 0
        last_page_resumes = 0
        cursor: Optional[str] = None
        offset = 0
        for _ in range(4 * _ROWS):
            # 1,000 chars holds ~15 rows, so pages with a cursor AND cut last
            # pages (no cursor of their own) both occur before the walk ends.
            kwargs: Dict[str, Any] = {
                "query": "walk namespace C",
                "zim_file_path": str(plain_zim),
                "limit": 50,
                "compact_budget": 1000,
            }
            if cursor:
                kwargs["cursor"] = cursor
            elif offset:
                kwargs["offset"] = offset
            out = query(**kwargs)
            rows = _walk_row_paths(out)
            assert rows, out
            # The header names exactly the rows this page shipped.
            first = len(seen) + 1
            assert f"— entries {first}-{first + len(rows) - 1} " in out.splitlines()[0]
            seen.extend(rows)
            if _cap_footer(out):
                cut_pages += 1
            m = _WALK_CURSOR_RE.search(out)
            if m:
                cursor, offset = m.group(1), 0
                continue
            resume = _resume_offset(out)
            if resume is not None:
                last_page_resumes += 1
                cursor, offset = None, resume
                continue
            break
        else:
            raise AssertionError("walk did not terminate")
        assert seen == [_note(i) for i in range(_ROWS)]
        # Positive controls: both continuations were exercised.
        assert cut_pages >= 3
        assert last_page_resumes >= 1

    def test_a_filtered_page_drops_the_cursor_it_cannot_remint(
        self, query: Callable[..., str], mixed_zim: Path
    ) -> None:
        """Assets interleaved with the rows: the walk scanned more entry ids
        than it returned, so "first dropped row" has no offset the cap can
        name. The stale cursor must go, and the footer must name the route
        that does recover the rows."""
        out = query(
            query="walk namespace C",
            zim_file_path=str(mixed_zim),
            limit=50,
            compact_budget="tiny",
        )
        rows = _walk_row_paths(out)
        assert 0 < len(rows) < 50
        assert "Pass `cursor=" not in out
        assert "re-run with a smaller `limit`" in out
        assert out.splitlines()[0].startswith(
            f"# Namespace `C` — {len(rows)} of 50 entries (scan positions 1-"
        )

    @pytest.mark.parametrize("limit", [3, 5], ids=["page-with-a-cursor", "last-page"])
    def test_a_page_with_no_room_for_a_row_does_not_point_at_itself(
        self, query: Callable[..., str], long_title_zim: Path, limit: int
    ) -> None:
        """No row fits, so "the first dropped row" is the page's own start: a
        cursor (or offset) re-pointed there would serve this page to its
        follower forever."""
        out = query(
            query="walk namespace C",
            zim_file_path=str(long_title_zim),
            limit=limit,
            compact_budget=500,
        )
        assert _walk_row_paths(out) == []
        assert "result rows were dropped" in out
        assert "Pass `cursor=" not in out
        assert _resume_offset(out) is None

    def test_the_offset_a_filtered_page_did_not_cut_still_ships(
        self, query: Callable[..., str], mixed_zim: Path
    ) -> None:
        """Control: a filtered page that fits keeps its cursor untouched."""
        out = query(
            query="walk namespace C",
            zim_file_path=str(mixed_zim),
            limit=5,
            compact_budget="tiny",
        )
        assert _cap_footer(out) is None
        assert len(_walk_row_paths(out)) == 5
        assert _WALK_CURSOR_RE.search(out)
        assert "— 5 entries (scan positions 1-" in out.splitlines()[0]


def _walk_row_paths(text: str) -> List[str]:
    return _WALK_ROW_RE.findall(text)


# ---------------------------------------------------------------------------
# search — a markdown page whose ``pass `offset=N``` line cannot be re-pointed
# ---------------------------------------------------------------------------


class TestSearchContinuation:
    def test_a_cut_page_does_not_advertise_the_offset_it_skipped(
        self, query: Callable[..., str], plain_zim: Path
    ) -> None:
        out = query(
            query="search for zebra",
            zim_file_path=str(plain_zim),
            limit=50,
            compact_budget="small",
        )
        ordinals = [int(n) for n in re.findall(r"^## (\d+)\. ", out, re.MULTILINE)]
        assert 0 < len(ordinals) < 50
        assert ordinals == list(range(1, len(ordinals) + 1))
        # The page reorders rows within itself (crawl-artefact and list
        # demotes), so "offset + rows shipped" is not a resume point the cap
        # can vouch for: the continuation goes, and so does its claim.
        assert "`offset=" not in out
        assert "re-run with a smaller `limit`" in out
        # The header names the rows that shipped, not the 50 requested.
        assert f"showing 1-{ordinals[-1]}:" in out
        assert "showing 1-50" not in out
        # Every row that shipped is whole: its heading and its path.
        last = out.rindex(f"## {ordinals[-1]}. ")
        assert re.match(r"## \d+\. [^\n]*\nPath: [^\n]+\n", out[last:]), out[last:]

    def test_no_budget_ships_a_row_without_its_path(
        self, query: Callable[..., str], plain_zim: Path
    ) -> None:
        """Sweep the cut across every position of a row: wherever it lands,
        the last row that ships has its path, and the header counts it."""
        shipped_counts = set()
        for budget in range(1200, 2600, 7):
            out = query(
                query="search for zebra",
                zim_file_path=str(plain_zim),
                limit=50,
                compact_budget=budget,
            )
            ordinals = [int(n) for n in re.findall(r"^## (\d+)\. ", out, re.M)]
            assert ordinals, (budget, out)
            last = out.rindex(f"## {ordinals[-1]}. ")
            tail = out[last:]
            assert re.match(r"## \d+\. [^\n]*\nPath: zebra_\d{3}\n", tail), (
                budget,
                tail,
            )
            assert f"showing 1-{ordinals[-1]}:" in out, budget
            shipped_counts.add(len(ordinals))
        # Positive control: the sweep moved the cut across several rows, so it
        # passed through every part of a row, heading and path included.
        assert len(shipped_counts) >= 5, shipped_counts

    def test_a_page_that_fits_keeps_its_offset(
        self, query: Callable[..., str], plain_zim: Path
    ) -> None:
        out = query(
            query="search for zebra",
            zim_file_path=str(plain_zim),
            limit=3,
            compact_budget="small",
        )
        assert _cap_footer(out) is None
        assert "showing 1-3:" in out
        assert "pass `offset=3` for the next page" in out


class TestUnpagedLookup:
    def test_a_cut_suggestions_page_is_not_offered_an_offset(
        self, query: Callable[..., str], plain_zim: Path
    ) -> None:
        """Suggestions are one unpaged page (``offset`` is not honoured), so
        the last-page ``offset=`` resume browse and walk get must not reach
        it, even though its envelope looks like a complete last page."""
        out = query(
            query="suggestions for zebra",
            zim_file_path=str(plain_zim),
            limit=50,
            compact_budget="tiny",
        )
        payload = _json_body(out)
        assert 0 < len(payload["results"]) < 50
        assert "result rows were dropped" in out
        assert "`offset=" not in out


# ---------------------------------------------------------------------------
# links — a markdown page with per-section counts and an ``offset=`` tail
# ---------------------------------------------------------------------------


class TestLinksContinuation:
    def test_a_cut_page_restates_its_section_count(
        self, query: Callable[..., str], hub_zim: Path
    ) -> None:
        out = query(
            query="links in zebra_hub",
            zim_file_path=str(hub_zim),
            limit=60,
            compact_budget=1000,
        )
        m = re.search(r"^## Internal \((\d+) of (\d+)\)$", out, re.MULTILINE)
        assert m, out
        shipped = len(re.findall(r"^- Zebra field note \d+ -> zebra_\d+$", out, re.M))
        assert 0 < shipped < 60
        assert int(m.group(1)) == shipped
        assert int(m.group(2)) == _ROWS
        # Both buckets page on one shared offset, so no single offset resumes
        # a page cut inside one of them.
        assert "`offset=" not in out
        assert "re-run with a smaller `limit`" in out
