"""Characterization tests for ``ZimOperations._extract_zim_metadata``.

These pin the *byte-identical* output of the metadata aggregator across
both namespace schemes before Task 3.4 decomposes the 206-line method
into per-scheme value readers. The old-scheme branch (HTML distillation
+ redirect walk) was the least-covered path in ``archive.py`` (~67% file
coverage), so the bulk of the assertions below target it: the
``[extracted from N-char HTML]`` annotation logic, the bounded
redirect-walk (including a cycle that must be skipped not raised), and
the per-key ``except`` that swallows a missing key.

All tests use hand-built mock archives (no live ZIM). The expected
strings are computed against the real ``_extract_metadata_text`` /
``_parse_counter_metadata`` helpers so they stay exact, not approximate.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from openzim_mcp.zim.archive import (
    _METADATA_PREVIEW_CAP,
    MAX_REDIRECT_DEPTH,
)


def _make_server(test_config):
    """Construct a server and return its ``ZimOperations``."""
    from openzim_mcp.server import OpenZimMcpServer

    return OpenZimMcpServer(test_config).zim_operations


def _base_counts(mock_archive: MagicMock) -> None:
    """Stamp the four intrinsic count fields onto a mock archive."""
    mock_archive.entry_count = 100
    mock_archive.all_entry_count = 120
    mock_archive.article_count = 50
    mock_archive.media_count = 50


def _identity(mock_archive: MagicMock) -> None:
    """Stamp the identity / index-capability fields onto a mock archive."""
    mock_archive.uuid = "0123abcd-0000-0000-0000-000000000000"
    mock_archive.is_multipart = False
    mock_archive.has_fulltext_index = True
    mock_archive.has_title_index = True


# ---------------------------------------------------------------------------
# Identity / counts — always present regardless of scheme
# ---------------------------------------------------------------------------


def test_identity_and_counts_always_present_new_scheme(test_config):
    """The basic counts + identity block is emitted verbatim and never
    depends on the M-namespace read succeeding."""
    zim_ops = _make_server(test_config)
    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = True
    mock_archive.metadata_keys = []
    mock_archive.get_metadata_item.side_effect = RuntimeError("none")

    md = zim_ops._extract_zim_metadata(mock_archive)

    assert md["entry_count"] == 100
    assert md["all_entry_count"] == 120
    assert md["article_count"] == 50
    assert md["media_count"] == 50
    assert md["uuid"] == "0123abcd-0000-0000-0000-000000000000"
    assert md["is_multipart"] is False
    assert md["has_fulltext_index"] is True
    assert md["has_title_index"] is True
    # No readable metadata -> no metadata_entries key at all.
    assert "metadata_entries" not in md


# ---------------------------------------------------------------------------
# New-scheme branch
# ---------------------------------------------------------------------------


def test_new_scheme_plain_value_stored_as_is(test_config):
    """A plain-text new-scheme value is stored verbatim (no HTML pass)."""
    zim_ops = _make_server(test_config)
    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = True
    mock_archive.metadata_keys = []

    def fake_get_metadata_item(key):
        if key == "Title":
            item = MagicMock()
            item.content = b"Wikipedia"
            return item
        raise RuntimeError("not present")

    mock_archive.get_metadata_item.side_effect = fake_get_metadata_item

    md = zim_ops._extract_zim_metadata(mock_archive)
    assert md["metadata_entries"]["Title"] == "Wikipedia"


def test_new_scheme_value_over_cap_truncated_with_marker(test_config):
    """A new-scheme value longer than the cap is truncated with the exact
    ``… [truncated, N chars total]`` suffix."""
    zim_ops = _make_server(test_config)
    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = True
    mock_archive.metadata_keys = []

    blob = "x" * 5000

    def fake_get_metadata_item(key):
        if key == "Description":
            item = MagicMock()
            item.content = blob.encode("utf-8")
            return item
        raise RuntimeError("not present")

    mock_archive.get_metadata_item.side_effect = fake_get_metadata_item

    md = zim_ops._extract_zim_metadata(mock_archive)
    desc = md["metadata_entries"]["Description"]
    expected = (
        f"{blob[:_METADATA_PREVIEW_CAP].rstrip()}… "
        f"[truncated, {len(blob):,} chars total]"
    )
    assert desc == expected


def test_new_scheme_empty_and_missing_keys_skipped(test_config):
    """An empty (whitespace-only) value and a missing key both produce no
    entry — they are skipped, not stored as ``""``."""
    zim_ops = _make_server(test_config)
    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = True
    mock_archive.metadata_keys = []

    def fake_get_metadata_item(key):
        if key == "Title":
            item = MagicMock()
            item.content = b"   "  # whitespace only -> empty after strip
            return item
        if key == "Creator":
            return None  # explicit None -> skipped
        # Everything else missing.
        raise RuntimeError("not present")

    mock_archive.get_metadata_item.side_effect = fake_get_metadata_item

    md = zim_ops._extract_zim_metadata(mock_archive)
    assert "metadata_entries" not in md  # nothing readable at all


def test_new_scheme_metadata_keys_extras_discovered_and_filtered(test_config):
    """``metadata_keys`` extras are appended (human-readable only); binary
    ``Illustration_*`` keys are filtered out."""
    zim_ops = _make_server(test_config)
    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = True
    mock_archive.metadata_keys = [
        "Title",
        "Illustration_48x48@1",  # binary — filtered
        "CustomKey",  # not in hardcoded list — discovered
    ]

    def fake_get_metadata_item(key):
        mapping = {
            "Title": b"Wikipedia",
            "CustomKey": b"custom-value",
            "Illustration_48x48@1": b"\x89PNG\r\n",
        }
        if key in mapping:
            item = MagicMock()
            item.content = mapping[key]
            return item
        raise RuntimeError("not present")

    mock_archive.get_metadata_item.side_effect = fake_get_metadata_item

    md = zim_ops._extract_zim_metadata(mock_archive)
    entries = md["metadata_entries"]
    assert entries["Title"] == "Wikipedia"
    assert entries["CustomKey"] == "custom-value"
    assert "Illustration_48x48@1" not in entries


def test_new_scheme_metadata_keys_read_raises_falls_back_to_hardcoded(test_config):
    """When ``archive.metadata_keys`` access RAISES, the discovery falls
    back to the hardcoded ``common_metadata`` list (discovered=[]) and
    logs ``metadata_keys read failed``.

    Pins the defensive ``except`` branch in ``_discover_metadata_keys``:
    a property that throws (not a missing attribute) propagates past the
    ``getattr`` default into the try/except, which logs + degrades to the
    conventional list rather than crashing the whole metadata read.

    A dedicated handler is attached directly to the archive module logger
    AFTER constructing the server: ``OpenZimMcpConfig.setup_logging`` calls
    ``logging.basicConfig(force=True)`` during server init, which strips
    pytest's ``caplog`` handler off the root, so ``caplog`` can't see the
    record. Capturing on the module logger sidesteps that reset.
    """
    import logging
    from unittest.mock import PropertyMock

    zim_ops = _make_server(test_config)

    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    arch_logger = logging.getLogger("openzim_mcp.zim.archive")
    handler = _Capture(level=logging.DEBUG)
    prev_level = arch_logger.level
    arch_logger.addHandler(handler)
    arch_logger.setLevel(logging.DEBUG)

    mock_archive = MagicMock()
    # ``metadata_keys`` as a property whose access raises (e.g. a libzim
    # archive with a corrupt M-namespace index).
    type(mock_archive).metadata_keys = PropertyMock(
        side_effect=RuntimeError("corrupt index")
    )

    expected_hardcoded = [
        "Title",
        "Description",
        "Long_Description",
        "Language",
        "Creator",
        "Publisher",
        "Date",
        "Source",
        "License",
        "Relation",
        "Flavour",
        "Tags",
        "Counter",
        "Name",
        "Scraper",
    ]

    try:
        keys = zim_ops._discover_metadata_keys(mock_archive, has_new_scheme=True)
    finally:
        arch_logger.removeHandler(handler)
        arch_logger.setLevel(prev_level)

    # discovered=[] -> no extras appended -> exactly the hardcoded list.
    assert keys == expected_hardcoded
    assert any("metadata_keys read failed" in msg for msg in captured)


# ---------------------------------------------------------------------------
# Old-scheme branch — the critical under-tested path
# ---------------------------------------------------------------------------


def _old_scheme_entry(content: bytes) -> MagicMock:
    """A non-redirect old-scheme M-entry yielding ``content``."""
    item = MagicMock()
    item.content = content
    entry = MagicMock()
    entry.is_redirect = False
    entry.get_item.return_value = item
    return entry


def test_old_scheme_html_title_extracted_with_annotation(test_config):
    """An ``M/Title`` whose content is a full HTML doc is distilled by
    ``_extract_metadata_text`` and annotated with the source size."""
    zim_ops = _make_server(test_config)

    title_html = (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head>\n'
        '    <meta charset="UTF-8">\n'
        "    <title>Title</title>\n"
        '    <link rel="canonical" href="https://en.wikipedia.org/wiki/Title">\n'
        "</head><body>\n"
        "<h1>Wikipedia</h1>\n"
        "<p>The Free Encyclopedia</p>\n"
        "</body></html>"
    )
    raw_len = len(title_html)

    def fake_get_entry_by_path(path):
        if path == "M/Title":
            return _old_scheme_entry(title_html.encode("utf-8"))
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = False
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path

    md = zim_ops._extract_zim_metadata(mock_archive)
    # extracted text is "Wikipedia The Free Encyclopedia" (31 chars), the
    # raw doc is much larger -> annotated branch (785-798).
    assert md["metadata_entries"]["Title"] == (
        f"Wikipedia The Free Encyclopedia [extracted from {raw_len:,}-char HTML]"
    )


def test_old_scheme_html_value_within_16_chars_not_annotated(test_config):
    """When the HTML wrapper strips <=16 chars, the extracted value is
    stored bare with NO ``[extracted from …]`` annotation (branch 792-793)."""
    zim_ops = _make_server(test_config)
    raw = "<html>Hi</html>"  # 15 chars -> extracts "Hi" (2 chars), delta 13

    def fake_get_entry_by_path(path):
        if path == "M/Name":
            return _old_scheme_entry(raw.encode("utf-8"))
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = False
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path

    md = zim_ops._extract_zim_metadata(mock_archive)
    assert md["metadata_entries"]["Name"] == "Hi"


def test_old_scheme_plain_text_value_stored_verbatim(test_config):
    """A non-HTML old-scheme value passes through unchanged (else, 799-800)."""
    zim_ops = _make_server(test_config)

    def fake_get_entry_by_path(path):
        if path == "M/Creator":
            return _old_scheme_entry(b"Wikipedia Project")
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = False
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path

    md = zim_ops._extract_zim_metadata(mock_archive)
    assert md["metadata_entries"]["Creator"] == "Wikipedia Project"


def test_old_scheme_long_extracted_value_truncated_with_marker(test_config):
    """When the *extracted* text still exceeds the cap, it is truncated
    with the ``… [truncated, N chars total]`` suffix using the ORIGINAL
    char count (branch 779-784)."""
    zim_ops = _make_server(test_config)
    # Plain (non-HTML) content longer than the cap. _extract_metadata_text
    # returns it as-is, so extracted == content and len(extracted) > cap.
    body = "y" * (_METADATA_PREVIEW_CAP + 200)

    def fake_get_entry_by_path(path):
        if path == "M/Long_Description":
            return _old_scheme_entry(body.encode("utf-8"))
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = False
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path

    md = zim_ops._extract_zim_metadata(mock_archive)
    value = md["metadata_entries"]["Long_Description"]
    expected = (
        f"{body[:_METADATA_PREVIEW_CAP].rstrip()}… "
        f"[truncated, {len(body):,} chars total]"
    )
    assert value == expected


def test_old_scheme_redirect_resolved_via_walk(test_config):
    """A redirecting ``M/`` entry is resolved through the bounded
    redirect-walk to its canonical target."""
    zim_ops = _make_server(test_config)

    target = _old_scheme_entry(b"Resolved Title")
    # One-hop redirect: r1 -> target.
    r1 = MagicMock()
    r1.is_redirect = True
    r1.path = "M/Title"
    r1.get_redirect_entry.return_value = target

    def fake_get_entry_by_path(path):
        if path == "M/Title":
            return r1
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = False
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path

    md = zim_ops._extract_zim_metadata(mock_archive)
    assert md["metadata_entries"]["Title"] == "Resolved Title"


def test_old_scheme_redirect_cycle_skipped_not_raised(test_config):
    """A redirect cycle is skipped (the key is omitted) rather than
    raising — metadata is best-effort."""
    zim_ops = _make_server(test_config)

    a = MagicMock()
    b = MagicMock()
    a.is_redirect = True
    a.path = "M/Title"
    b.is_redirect = True
    b.path = "M/TitleAlias"
    a.get_redirect_entry.return_value = b
    b.get_redirect_entry.return_value = a  # cycle

    def fake_get_entry_by_path(path):
        if path == "M/Title":
            return a
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = False
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path

    md = zim_ops._extract_zim_metadata(mock_archive)
    # Cycle -> Title omitted, nothing else readable -> no entries.
    assert "metadata_entries" not in md


def test_old_scheme_redirect_depth_bound_skips(test_config):
    """A redirect chain longer than ``MAX_REDIRECT_DEPTH`` is abandoned and
    the key omitted (still a redirect after the bound -> skipped)."""
    zim_ops = _make_server(test_config)

    # Build a chain of MAX_REDIRECT_DEPTH + 2 unique redirect hops so the
    # walk hits its depth bound while ``entry`` is still a redirect.
    chain = []
    for i in range(MAX_REDIRECT_DEPTH + 2):
        e = MagicMock()
        e.is_redirect = True
        e.path = f"M/hop{i}"
        chain.append(e)
    for i in range(len(chain) - 1):
        chain[i].get_redirect_entry.return_value = chain[i + 1]
    chain[-1].get_redirect_entry.return_value = chain[-1]

    def fake_get_entry_by_path(path):
        if path == "M/Title":
            return chain[0]
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = False
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path

    md = zim_ops._extract_zim_metadata(mock_archive)
    assert "metadata_entries" not in md


def test_old_scheme_missing_key_swallowed_by_per_key_except(test_config):
    """A ``get_entry_by_path`` that raises for one key doesn't abort the
    whole aggregation — other keys still surface."""
    zim_ops = _make_server(test_config)

    def fake_get_entry_by_path(path):
        if path == "M/Title":
            raise RuntimeError("boom")  # swallowed by per-key except
        if path == "M/Creator":
            return _old_scheme_entry(b"Wikipedia")
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = False
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path

    md = zim_ops._extract_zim_metadata(mock_archive)
    entries = md["metadata_entries"]
    assert "Title" not in entries
    assert entries["Creator"] == "Wikipedia"


def test_old_scheme_empty_content_skipped(test_config):
    """An old-scheme entry whose decoded content is empty after strip is
    not stored."""
    zim_ops = _make_server(test_config)

    def fake_get_entry_by_path(path):
        if path == "M/Title":
            return _old_scheme_entry(b"   \n  ")  # empty after strip
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = False
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path

    md = zim_ops._extract_zim_metadata(mock_archive)
    assert "metadata_entries" not in md


# ---------------------------------------------------------------------------
# Counter parse — applies to both schemes
# ---------------------------------------------------------------------------


def test_counter_breakdown_new_scheme(test_config):
    """``M/Counter`` is parsed into a structured ``counter_breakdown``."""
    zim_ops = _make_server(test_config)
    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = True
    mock_archive.metadata_keys = []

    def fake_get_metadata_item(key):
        if key == "Counter":
            item = MagicMock()
            item.content = b"text/html=123;image/png=45;bad-pair;image/svg+xml=7"
            return item
        raise RuntimeError("not present")

    mock_archive.get_metadata_item.side_effect = fake_get_metadata_item

    md = zim_ops._extract_zim_metadata(mock_archive)
    assert md["metadata_entries"]["Counter"] == (
        "text/html=123;image/png=45;bad-pair;image/svg+xml=7"
    )
    assert md["counter_breakdown"] == {
        "text/html": 123,
        "image/png": 45,
        "image/svg+xml": 7,
    }


def test_parse_counter_metadata_preserves_parameterized_mimetypes():
    """Parameterized content-types (``; charset=...; profile="..."``) are
    kept as whole buckets instead of being shattered on the inner ``;``/``=``.

    Regression for the real-world Wikipedia ``Counter`` where the
    575,138-entry profiled-SVG bucket and the iso-8859-1 HTML bucket were
    silently dropped by a naive ``split(';')`` / ``partition('=')``.
    """
    from openzim_mcp.zim.archive import _parse_counter_metadata

    raw = (
        "image/svg+xml=25;"
        "image/svg+xml; charset=utf-8; "
        'profile="https://www.mediawiki.org/wiki/Specs/SVG/1.0.0"=575138;'
        "image/webp=7585596;"
        "text/html=8425786;"
        "text/html; charset=iso-8859-1=1;"
        "text/javascript=3"
    )
    result = _parse_counter_metadata(raw)

    assert result["image/svg+xml"] == 25
    assert (
        result[
            "image/svg+xml; charset=utf-8; "
            'profile="https://www.mediawiki.org/wiki/Specs/SVG/1.0.0"'
        ]
        == 575138
    )
    assert result["image/webp"] == 7585596
    assert result["text/html"] == 8425786
    assert result["text/html; charset=iso-8859-1"] == 1
    assert result["text/javascript"] == 3
    # No bucket is silently lost.
    assert sum(result.values()) == 25 + 575138 + 7585596 + 8425786 + 1 + 3


def test_parse_counter_metadata_drops_truly_malformed_pairs():
    """A standalone junk token with no ``=count`` (``bad-pair``) is dropped,
    not merged into an adjacent bucket."""
    from openzim_mcp.zim.archive import _parse_counter_metadata

    result = _parse_counter_metadata(
        "text/html=123;image/png=45;bad-pair;image/svg+xml=7"
    )
    assert result == {"text/html": 123, "image/png": 45, "image/svg+xml": 7}


def test_counter_breakdown_old_scheme(test_config):
    """The Counter parse fires identically on the old-scheme path."""
    zim_ops = _make_server(test_config)

    def fake_get_entry_by_path(path):
        if path == "M/Counter":
            return _old_scheme_entry(b"text/html=10;image/jpeg=3")
        raise RuntimeError("not present")

    mock_archive = MagicMock()
    _base_counts(mock_archive)
    _identity(mock_archive)
    mock_archive.has_new_namespace_scheme = False
    mock_archive.get_entry_by_path.side_effect = fake_get_entry_by_path

    md = zim_ops._extract_zim_metadata(mock_archive)
    assert md["counter_breakdown"] == {"text/html": 10, "image/jpeg": 3}
