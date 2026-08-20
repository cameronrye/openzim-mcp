"""Server identity metadata and argument completions.

Two client-facing surfaces that the server had left empty. ``serverInfo``
carried only a name and version, so a client or registry listing had no icon
and no link home. And ``completion/complete`` was never registered, so every
argument a client could have offered a picker for — which archive to summarize,
which archive a ``zim://{name}`` URI refers to — was a free-text field the user
had to fill from memory.

Both are asserted through a real client session rather than on the server
object, because both only matter as what a client receives.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import anyio
import pytest
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import PromptReference, ResourceTemplateReference

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

DOCS_URL = "https://cameronrye.github.io/openzim-mcp/"


@asynccontextmanager
async def _session(tmp_path: Path, **kwargs: Any) -> AsyncIterator[Any]:
    """A connected client session against a server rooted at ``tmp_path``.

    The 1.x SDK shipped ``create_connected_server_and_client_session``; v2
    exposes only the stream pair, so the wiring lives here (the same shape as
    ``test_mcp_session._connected_client``). ``initialize()`` is idempotent on
    the v2 ``ClientSession``, so a test that wants the ``InitializeResult``
    just calls it again and gets the cached result.
    """
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)], tool_mode="advanced", **kwargs
    )
    server = OpenZimMcpServer(config)
    low = server.mcp._lowlevel_server
    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                low.run,
                server_read,
                server_write,
                low.create_initialization_options(),
                True,  # raise_exceptions - surface server faults in tests
            )
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                yield session
            task_group.cancel_scope.cancel()


def _make_zim(tmp_path: Path, name: str) -> Path:
    """A file that the archive scanner will list.

    The listing walks for ``*.zim`` and reports name/path/size; it does not
    open the archive, so completions can be exercised without the real corpus.
    """
    path = tmp_path / f"{name}.zim"
    path.write_bytes(b"ZIM\x04not-a-real-archive")
    return path


@pytest.mark.asyncio
async def test_server_info_carries_website_and_icon(tmp_path: Path) -> None:
    """``serverInfo`` should identify the project, not just name it.

    A registry listing or client UI has nothing to show without these: the
    icon and the link home are the only two identity fields the protocol
    offers beyond a bare name string.
    """
    async with _session(tmp_path) as session:
        result = await session.initialize()

    info = result.server_info
    assert info.website_url == DOCS_URL
    assert info.icons, "serverInfo advertises no icon"
    assert all(icon.src.startswith("https://") for icon in info.icons), (
        "an icon served over plain http would be blocked as mixed content "
        "in any browser-based client"
    )


@pytest.mark.asyncio
async def test_completes_zim_file_path_for_prompts(tmp_path: Path) -> None:
    """The ``summarize`` prompt's archive argument offers the real archives."""
    _make_zim(tmp_path, "wikipedia_en")
    _make_zim(tmp_path, "wiktionary_en")

    async with _session(tmp_path) as session:
        result = await session.complete(
            ref=PromptReference(type="ref/prompt", name="summarize"),
            argument={"name": "zim_file_path", "value": ""},
        )

    values = result.completion.values
    assert len(values) == 2
    assert any(v.endswith("wikipedia_en.zim") for v in values)
    assert any(v.endswith("wiktionary_en.zim") for v in values)


@pytest.mark.asyncio
async def test_completion_filters_by_what_was_typed(tmp_path: Path) -> None:
    """A completion that ignores the partial value is worse than none.

    The client shows the returned list as-is, so failing to filter offers the
    user entries that contradict what they have already typed.
    """
    _make_zim(tmp_path, "wikipedia_en")
    _make_zim(tmp_path, "wiktionary_en")

    async with _session(tmp_path) as session:
        result = await session.complete(
            ref=PromptReference(type="ref/prompt", name="summarize"),
            argument={"name": "zim_file_path", "value": "wikip"},
        )

    values = result.completion.values
    assert len(values) == 1
    assert values[0].endswith("wikipedia_en.zim")


@pytest.mark.asyncio
async def test_completes_archive_name_for_the_resource_template(
    tmp_path: Path,
) -> None:
    """``zim://{name}`` completes to bare basenames, not paths.

    The template's ``{name}`` segment is the basename without ``.zim``;
    offering a full filesystem path there would build a URI that cannot
    resolve.
    """
    _make_zim(tmp_path, "wikipedia_en")

    async with _session(tmp_path) as session:
        result = await session.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="zim://{name}"),
            argument={"name": "name", "value": ""},
        )

    assert result.completion.values == ["wikipedia_en"]


@pytest.mark.asyncio
async def test_unknown_completion_targets_return_empty(tmp_path: Path) -> None:
    """An argument with nothing to offer must answer empty, not fail.

    ``research(topic)`` is free text and the entry path inside an archive is
    unbounded. A client asking about either should get an empty list, since a
    handler that raises would surface as a protocol error in the client UI.
    """
    _make_zim(tmp_path, "wikipedia_en")

    async with _session(tmp_path) as session:
        free_text = await session.complete(
            ref=PromptReference(type="ref/prompt", name="research"),
            argument={"name": "topic", "value": "photo"},
        )
        unknown_prompt = await session.complete(
            ref=PromptReference(type="ref/prompt", name="does_not_exist"),
            argument={"name": "zim_file_path", "value": ""},
        )

    assert free_text.completion.values == []
    assert unknown_prompt.completion.values == []


@pytest.mark.asyncio
async def test_completion_never_exceeds_the_protocol_page_size(
    tmp_path: Path,
) -> None:
    """The spec caps a completion page at 100 values, and sets ``hasMore``.

    An allowed directory holding a full Kiwix mirror would otherwise return
    hundreds of entries in one response.
    """
    for i in range(120):
        _make_zim(tmp_path, f"archive_{i:03d}")

    async with _session(tmp_path) as session:
        result = await session.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="zim://{name}"),
            argument={"name": "name", "value": ""},
        )

    assert len(result.completion.values) == 100
    assert result.completion.total == 120
    assert result.completion.has_more is True


@pytest.mark.asyncio
async def test_completion_reflects_archives_added_after_startup(
    tmp_path: Path,
) -> None:
    """Completions must read the directory live, not a startup snapshot.

    A cached list would go stale the moment an operator drops in a new
    archive — exactly when a user reaches for the picker to find it.
    """
    _make_zim(tmp_path, "first")

    async with _session(tmp_path) as session:
        before = await session.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="zim://{name}"),
            argument={"name": "name", "value": ""},
        )
        _make_zim(tmp_path, "second")
        after = await session.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="zim://{name}"),
            argument={"name": "name", "value": ""},
        )

    assert before.completion.values == ["first"]
    assert after.completion.values == ["first", "second"]


@pytest.mark.asyncio
async def test_completion_scan_runs_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The archive scan behind completions must not run on the loop thread.

    ``list_zim_files_data`` re-walks every allowed directory on each call
    (glob + stat — the scan result is its own cache key, so even a warm cache
    scans first). Run inline in the async handler, one completion request
    against a hung network mount would wedge the event loop and with it every
    session; every comparable call site (resource templates, ``/readyz``)
    already offloads for exactly this reason.
    """
    import threading

    from openzim_mcp.zim.archive import ZimOperations

    _make_zim(tmp_path, "wikipedia_en")

    loop_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []
    original = ZimOperations.list_zim_files_data

    def recording(self: ZimOperations, *args: Any, **kwargs: Any) -> Any:
        seen_threads.append(threading.current_thread())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ZimOperations, "list_zim_files_data", recording)

    async with _session(tmp_path) as session:
        result = await session.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="zim://{name}"),
            argument={"name": "name", "value": ""},
        )

    assert result.completion.values == ["wikipedia_en"]
    assert seen_threads, "completion never consulted the archive listing"
    assert all(thread is not loop_thread for thread in seen_threads), (
        "the archive scan ran on the event-loop thread; it must be offloaded "
        "via asyncio.to_thread"
    )


def test_docs_url_matches_the_published_site() -> None:
    """The advertised website must be the one the project actually publishes."""
    readme = Path(__file__).parent.parent / "README.md"
    assert DOCS_URL.rstrip("/") in readme.read_text(encoding="utf-8"), (
        "serverInfo.websiteUrl should point at the documentation site the "
        "README links, or clients send users somewhere unmaintained"
    )
    assert json.loads(
        (Path(__file__).parent.parent / "server.json").read_text(encoding="utf-8")
    )["repository"]["url"].startswith("https://github.com/cameronrye/openzim-mcp")
