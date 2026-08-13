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
