"""The ``.zim``-suffixed overview spelling must notify, not just read.

``_resolve_zim_name`` deliberately accepts two spellings of an archive —
the bare stem (``wikipedia``) and the full filename (``wikipedia.zim``) —
and ``zim://files``, the discovery resource, publishes the *filename* in
its ``name`` field. So a client that builds its overview URI from that
listing reads ``zim://wikipedia.zim`` successfully and is handed the
hour-long ``archive_read_ttl_ms``, then subscribes with the same string.

The watcher only ever published the stem spelling, and SDK delivery is
exact-string (``event_matches`` does ``event.uri in uris``), so that
subscription matched nothing: silence on every replacement, and a stale
overview for the life of the stream.

This is the same defect shape the percent-encoding pair in
``test_subscriptions.py`` already covers — "both spellings that READ must
also be spellings that NOTIFY" — along the extension axis instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openzim_mcp.subscriptions import MtimeWatcher


async def _events_for_replacement(tmp_path: Path, filename: str) -> list:
    """Replace ``filename`` under ``tmp_path`` and return the watcher events."""
    target = tmp_path / filename
    target.write_bytes(b"v1")

    events: list = []

    async def emit(uri: str, change_type: str) -> None:
        events.append((uri, change_type))

    watcher = MtimeWatcher([str(tmp_path)], interval=100, on_change=emit)
    await watcher.start()
    try:
        target.write_bytes(b"v2-with-a-different-length")
        await watcher._tick()
    finally:
        await watcher.stop()
    return events


@pytest.mark.asyncio
async def test_filename_spelling_is_published(tmp_path: Path) -> None:
    events = await _events_for_replacement(tmp_path, "wikipedia.zim")
    # The stem spelling keeps working (regression guard)...
    assert ("zim://wikipedia", "replaced") in events
    # ...and the filename spelling, which reads just as well, now fires too.
    assert ("zim://wikipedia.zim", "replaced") in events


@pytest.mark.asyncio
async def test_filename_spelling_matches_what_zim_files_advertises(
    tmp_path: Path,
) -> None:
    """Pin the coupling: ``zim://files`` rows carry ``Path.name``.

    If the listing ever stops advertising the extension this test still
    passes, but it documents *why* the filename spelling is published.
    """
    target = tmp_path / "wikipedia.zim"
    target.write_bytes(b"v1")
    from openzim_mcp.zim.archive import ZimOperations  # noqa: F401  (import guard)

    advertised = target.name
    events = await _events_for_replacement(tmp_path, "wikipedia.zim")
    assert (f"zim://{advertised}", "replaced") in events


@pytest.mark.asyncio
async def test_percent_encoded_filename_spelling_is_published(
    tmp_path: Path,
) -> None:
    """A name needing encoding must publish all four readable spellings."""
    events = await _events_for_replacement(tmp_path, "wikipedia es niños.zim")
    uris = {uri for uri, _ in events}
    assert "zim://wikipedia es niños" in uris
    assert "zim://wikipedia%20es%20ni%C3%B1os" in uris
    assert "zim://wikipedia es niños.zim" in uris
    assert "zim://wikipedia%20es%20ni%C3%B1os.zim" in uris


@pytest.mark.asyncio
async def test_no_duplicate_publishes_for_an_unreserved_stem(
    tmp_path: Path,
) -> None:
    """A plain ASCII name publishes each distinct URI exactly once.

    The encoded and raw forms are identical here, so de-duplication must
    collapse them rather than double-firing every subscriber.
    """
    events = await _events_for_replacement(tmp_path, "wikipedia.zim")
    replaced = [uri for uri, kind in events if kind == "replaced"]
    assert sorted(replaced) == ["zim://wikipedia", "zim://wikipedia.zim"]
