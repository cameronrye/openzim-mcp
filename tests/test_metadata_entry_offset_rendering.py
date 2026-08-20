"""The ``M/<key>`` text presenter must honor the offset contract.

``_get_metadata_entry_data`` computes ``content_offset`` / ``total_chars`` /
``content_offset_past_end`` exactly like the regular-entry payload builder,
and the regular-entry text renderer (``_render_entry_payload_text``) surfaces
them. The metadata text presenter is the only text surface that dropped that
accounting: a tail slice rendered as the complete value, and a past-end
offset rendered as a silently empty value with ``content_ok=True``.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple
from unittest.mock import MagicMock

from openzim_mcp.zim.content import _ContentMixin


def _presenter_with_payload(payload: Dict[str, Any]) -> _ContentMixin:
    """A stub mixin whose payload builder returns a canned success payload."""

    class _Stub(_ContentMixin):
        def __init__(self) -> None:
            pass

        def _get_metadata_entry_data(
            self, *a: Any, **k: Any
        ) -> Tuple[Dict[str, Any], bool]:
            return payload, True

    return _Stub()


def test_metadata_text_shows_offset_accounting() -> None:
    """A tail slice must not be rendered as the complete value."""
    stub = _presenter_with_payload(
        {
            "title": "Title",
            "path": "M/Title",
            "content_type": "text/plain",
            "content": "pedia",
            "content_offset": 4,
            "total_chars": 9,
        }
    )
    text, ok = stub._get_metadata_entry(MagicMock(), "M/Title", 800, content_offset=4)
    assert ok
    assert "Content Offset: 4 of 9 characters" in text
    assert "pedia" in text


def test_metadata_text_explains_past_end_offset() -> None:
    """``content_offset >= len(value)`` must not read as "value is empty"."""
    stub = _presenter_with_payload(
        {
            "title": "Title",
            "path": "M/Title",
            "content_type": "text/plain",
            "content": "",
            "content_offset": 50,
            "total_chars": 9,
            "content_offset_past_end": True,
        }
    )
    text, ok = stub._get_metadata_entry(MagicMock(), "M/Title", 800, content_offset=50)
    assert ok
    assert "past the end" in text
    assert "(No content — offset beyond end of body)" in text


def test_empty_metadata_value_says_so() -> None:
    """A genuinely empty value must not render as a bare ``## Content``.

    The past-end case above has a placeholder; the *empty value* case did not,
    because this presenter was a copy of ``_render_entry_payload_text`` that
    dropped its ``or "(No content)"`` fallback. The result read as a truncated
    response rather than "the archive stores this key with an empty value" —
    the same silently-empty rendering the offset accounting was added to fix.
    """
    stub = _presenter_with_payload(
        {
            "title": "Title",
            "path": "M/Title",
            "content_type": "text/plain",
            "content": "",
        }
    )
    text, ok = stub._get_metadata_entry(MagicMock(), "M/Title", 800)
    assert ok
    assert text.endswith("## Content\n\n(No content)")


def test_metadata_and_entry_renderers_agree_on_shared_lines() -> None:
    """Both text surfaces must render offset and body identically.

    They drifted once — the metadata copy lost the empty-value fallback and the
    content-type default's casing — so this pins the shared builder rather than
    the two outputs separately: any future edit to one renderer that doesn't go
    through ``_render_offset_and_body`` breaks here.
    """
    from openzim_mcp.zim.content import _render_entry_payload_text

    payload = {
        "title": "Title",
        "path": "M/Title",
        "content": "pedia",
        "content_offset": 4,
        "total_chars": 9,
    }
    entry_text = _render_entry_payload_text(dict(payload))
    metadata_text, ok = _presenter_with_payload(dict(payload))._get_metadata_entry(
        MagicMock(), "M/Title", 800, content_offset=4
    )

    assert ok
    for shared in ("Type: Unknown", "Content Offset: 4 of 9 characters", "pedia"):
        assert shared in entry_text
        assert shared in metadata_text


def test_metadata_text_unchanged_without_offset() -> None:
    """No offset applied → no offset lines (the common path stays stable)."""
    stub = _presenter_with_payload(
        {
            "title": "Title",
            "path": "M/Title",
            "content_type": "text/plain",
            "content": "Wikipedia",
        }
    )
    text, ok = stub._get_metadata_entry(MagicMock(), "M/Title", 800)
    assert ok
    assert "Content Offset" not in text
    assert "Wikipedia" in text
