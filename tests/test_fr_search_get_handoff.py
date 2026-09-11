"""The search → get handoff must not dead-end on a one-archive server.

v3.3.1 field report (fid 27), graded High and confirmed independently: the
most common two-call sequence on this server, on exactly the deployment the
README quickstart describes.

    zim_search "stoicism"             hit keys: path, title, snippet
                                      zim_file: ABSENT
    zim_search "stoicism" mode=title  hit keys: path, title, score,
                                      zim_file, match_type, pre_redirect_path
    zim_get      { entry_path: … }    isError: zim_file_path: Field required

The archive is auto-selected, so the caller never learns its path — and
``mode='title'`` teaches a model that a hit carries ``zim_file`` while
fulltext silently drops it.

Both ends are closed here, because a model can arrive from either:

* the fulltext response now names the archive it resolved, once, at the
  top level (``zim_file_path``) rather than repeated on every row — the
  row is where the response budget is spent, and a 1000-row page would
  have paid the same absolute path a thousand times for one fact; and
* a ``zim_file_path: Field required`` rejection names the sole loaded
  archive when there is exactly one, so the retry is mechanical.

Every test drives the registered handler (or the real ``call_tool``
envelope path) against a real libzim archive on disk.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any, Optional

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

_MINI = "wikipedia_en_climate_change_mini_2024-06.zim"


def _one_archive_server(
    tmp_path: Path, corpus: Optional[Path], *, cache: bool = False
) -> OpenZimMcpServer:
    if corpus is None:
        pytest.skip("ZIM_TEST_DATA_DIR not set")
    source = corpus / "withns" / _MINI
    if not source.exists():
        pytest.skip(f"{_MINI} not in the corpus")
    solo = tmp_path / "solo"
    solo.mkdir()
    shutil.copy(source, solo / _MINI)
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(solo)],
            tool_mode="advanced",
            cache=(
                CacheConfig(
                    enabled=True,
                    persistence_enabled=False,
                    persistence_path=str(tmp_path / "cache"),
                )
                if cache
                else CacheConfig(enabled=False)
            ),
        )
    )


@pytest.fixture
def solo_server(tmp_path, zim_test_data_dir) -> OpenZimMcpServer:
    return _one_archive_server(tmp_path, zim_test_data_dir)


def _handler(server: OpenZimMcpServer, name: str) -> Any:
    return server.mcp._tool_manager._tools[name].fn


# ---------------------------------------------------------------------------
# The fulltext response names the archive it searched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_naming_the_archive_leaves_the_cached_page_alone(
    tmp_path, zim_test_data_dir
):
    """The stamp re-measures ``_meta`` on the page it returns, and
    ``_strip_next_cursor`` copies only the top level — so that ``_meta`` was
    the dict inside the cached search page. Every fulltext call rewrote the
    cache's size fields to describe a body the cache does not hold, and a
    cross-archive call for the same query then reported a different size
    than a fresh server did. The same defect class as the title demote that
    reordered its cached page, one call site over."""
    server = _one_archive_server(tmp_path, zim_test_data_dir, cache=True)
    archive = str(tmp_path / "solo" / _MINI)
    ops = server.zim_operations
    cached = copy.deepcopy(ops.search_zim_file_data(archive, "carbon", 5, 0))

    await _handler(server, "zim_search")(query="carbon", limit=5)

    assert ops.search_zim_file_data(archive, "carbon", 5, 0) == cached


@pytest.mark.asyncio
async def test_a_fulltext_hit_can_be_opened_without_a_second_lookup(solo_server):
    """The whole finding, end to end: search, then get, using only what
    the search returned."""
    hits = await _handler(solo_server, "zim_search")(
        query="climate", mode="fulltext", limit=2
    )

    assert hits.get("error") is not True, hits
    assert hits["results"], "fixture archive returned no fulltext hits"
    archive = hits.get("zim_file_path")
    assert archive, (
        "a fulltext response must name the archive it resolved — the caller "
        f"never passed one. Payload keys: {sorted(hits)}"
    )

    entry = await _handler(solo_server, "zim_get")(
        zim_file_path=archive, entry_path=hits["results"][0]["path"]
    )
    assert entry.get("error") is not True, entry


@pytest.mark.asyncio
async def test_the_archive_named_is_the_archive_searched(solo_server, tmp_path):
    """Positive identity, not just presence: an echoed path that named the
    wrong archive would satisfy "is not empty" and dead-end just as hard."""
    hits = await _handler(solo_server, "zim_search")(
        query="climate", mode="fulltext", limit=1
    )

    on_disk = str((tmp_path / "solo" / _MINI).resolve())
    assert str(Path(hits["zim_file_path"]).resolve()) == on_disk


@pytest.mark.asyncio
async def test_a_pinned_call_gets_the_same_field(solo_server, tmp_path):
    """The echo is not conditional on auto-selection.

    A caller that *did* pass the path is the case where the field is
    redundant — but a response whose shape depends on how the archive was
    chosen is one a model has to branch on, which is the asymmetry this
    finding is about in the first place.
    """
    pinned = str(tmp_path / "solo" / _MINI)
    hits = await _handler(solo_server, "zim_search")(
        query="climate", mode="fulltext", limit=1, zim_file_path=pinned
    )

    assert Path(hits["zim_file_path"]).resolve() == Path(pinned).resolve()


@pytest.mark.asyncio
async def test_the_two_search_modes_agree_that_a_hit_is_openable(solo_server):
    """fid 27's core asymmetry: title mode taught the shape, fulltext broke it.

    Neither surface has to spell it the same way, but both must let a
    caller open a hit without a second lookup.
    """
    search = _handler(solo_server, "zim_search")

    title = await search(query="Climate change", mode="title", limit=1)
    fulltext = await search(query="climate", mode="fulltext", limit=1)

    title_archive = title["results"][0].get("zim_file")
    fulltext_archive = fulltext.get("zim_file_path")

    assert title_archive, "control: title mode has always carried zim_file"
    assert fulltext_archive, "fulltext mode still drops the archive identity"
    assert Path(title_archive).resolve() == Path(fulltext_archive).resolve()


@pytest.mark.asyncio
async def test_a_filtered_fulltext_page_names_it_too(solo_server):
    """The filtered branch is a different data call and was equally silent."""
    hits = await _handler(solo_server, "zim_search")(
        query="climate", mode="fulltext", limit=2, namespace="A"
    )

    assert hits.get("error") is not True, hits
    assert hits.get("zim_file_path"), sorted(hits)


# ---------------------------------------------------------------------------
# The other end: the rejection names the archive it could have used
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_field_required_names_the_sole_loaded_archive(solo_server, tmp_path):
    """A model that reads the rejection rather than the search payload.

    The bare "zim_file_path: Field required" is true and useless on a
    server where exactly one archive could ever have been meant.
    """
    result = await solo_server.mcp.call_tool(
        "zim_get", {"entry_path": "A/Climate_change_in_the_Americas"}
    )

    assert result.is_error is True
    message = result.content[0].text
    assert "Field required" in message, message
    assert _MINI in message, (
        "with one archive loaded the rejection must name it: " + message
    )


@pytest.mark.asyncio
async def test_the_hint_is_withheld_when_it_would_be_a_guess(tmp_path):
    """Two archives loaded — naming one would be picking for the caller.

    Paired with the test above so "names the archive" cannot be satisfied
    by a message that always names something.
    """
    pair = tmp_path / "pair"
    pair.mkdir()
    for name in ("a.zim", "b.zim"):
        (pair / name).write_bytes(b"ZIM\x04" + b"\0" * 100)
    server = OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(pair)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
    )

    result = await server.mcp.call_tool("zim_get", {"entry_path": "A/Anything"})

    assert result.is_error is True
    message = result.content[0].text
    assert "Field required" in message, message
    assert "a.zim" not in message and "b.zim" not in message, (
        "with two archives loaded the server must not pick one: " + message
    )


@pytest.mark.asyncio
async def test_the_envelope_measures_the_page_that_ships(solo_server):
    """The data layer sized the payload before this field existed.

    Restating the archive without restating the size is the same defect
    this report opened with — a number the server computes and then makes
    wrong on the way out.
    """
    import json

    hits = await _handler(solo_server, "zim_search")(
        query="climate", mode="fulltext", limit=2
    )

    body = json.dumps(
        {k: v for k, v in hits.items() if k != "_meta"}, ensure_ascii=False
    )
    assert hits["_meta"]["chars"] == len(body)
    assert hits["zim_file_path"] in body
