"""v3.0.0 field-defect fixes — ``simple`` workstream.

Each class pins one defect from the 2026-08-19 real-world sweep of the
simple-mode ``zim_query`` surface (dispatcher, intent parser, cursor
handling, compact renderers). The defect ids (D42 …) refer to the
sweep's fix plan; the docstrings restate the observed behaviour so the
regression is recognisable without the report.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock

import pytest

from openzim_mcp.pagination import Cursor
from openzim_mcp.simple_tools import SimpleToolsHandler


def _weak_results() -> List[Dict[str, Any]]:
    """Three hits that do NOT strong-match the topic ``immanuel kant``
    under the order-sensitive matcher (the IEP ``Last, First | Site``
    shape), so ``tell me about`` falls through to the rendered search.
    """
    return [
        {
            "path": "iep.utm.edu/kantaest/",
            "title": "Kant: Aesthetics | Internet Encyclopedia",
            "snippet": "...",
        },
        {
            "path": "iep.utm.edu/kant-rel/",
            "title": "Kant: Religion | Internet Encyclopedia",
            "snippet": "...",
        },
        {
            "path": "iep.utm.edu/kantmeta/",
            "title": "Kant: Metaphysics | Internet Encyclopedia",
            "snippet": "...",
        },
    ]


# ---------------------------------------------------------------------------
# D42: tell_me_about advertises ``pass offset=N`` but hardcoded offset 0
# ---------------------------------------------------------------------------


class TestD42TellMeAboutHonoursOffset:
    """The weak-match ``tell me about`` render ends with ``Showing 1-3 of
    ~151 — pass offset=3 for the next page``, but every search call in
    ``_search_or_recover_tell_me_about`` passed a literal ``0``: replaying
    with ``offset=3`` returned the byte-identical first page forever.
    """

    @pytest.fixture
    def mock_ops(self) -> Mock:
        mock = Mock()
        mock.search_zim_file_data.return_value = {"results": _weak_results()}
        mock.search_zim_file.return_value = "rendered page"
        return mock

    def test_offset_reaches_structured_search_and_rendered_fallback(
        self, mock_ops: Mock
    ) -> None:
        handler = SimpleToolsHandler(mock_ops)
        handler.handle_zim_query(
            "tell me about immanuel kant",
            zim_file_path="/zims/iep.zim",
            options={"offset": 3},
        )
        data_call = mock_ops.search_zim_file_data.call_args
        assert data_call is not None
        assert data_call.args[3] == 3, "structured search ignored the offset"
        render_call = mock_ops.search_zim_file.call_args
        assert render_call is not None
        assert render_call.args[3] == 3, "rendered fallback ignored the offset"

    def test_offset_reaches_empty_result_render(self, mock_ops: Mock) -> None:
        mock_ops.search_zim_file_data.return_value = {"results": []}
        handler = SimpleToolsHandler(mock_ops)
        handler.handle_zim_query(
            "tell me about immanuel kant",
            zim_file_path="/zims/iep.zim",
            options={"offset": 6},
        )
        assert mock_ops.search_zim_file.call_args.args[3] == 6

    def test_paged_call_never_auto_fetches_from_page_n(self, mock_ops: Mock) -> None:
        """A continuation request is walking the weak-match list the
        footer advertised; page N's top hit strong-matching the topic
        must not flip the response into an article body.
        """
        mock_ops.search_zim_file_data.return_value = {
            "results": [
                {"path": "Immanuel_Kant", "title": "Immanuel Kant", "snippet": ""}
            ]
        }
        handler = SimpleToolsHandler(mock_ops)
        out = handler.handle_zim_query(
            "tell me about immanuel kant",
            zim_file_path="/zims/iep.zim",
            options={"offset": 3},
        )
        mock_ops.get_zim_entry.assert_not_called()
        assert "rendered page" in out
        assert mock_ops.search_zim_file.call_args.args[3] == 3

    def test_first_page_behaviour_unchanged(self, mock_ops: Mock) -> None:
        handler = SimpleToolsHandler(mock_ops)
        handler.handle_zim_query(
            "tell me about immanuel kant", zim_file_path="/zims/iep.zim"
        )
        assert mock_ops.search_zim_file_data.call_args.args[3] == 0
        assert mock_ops.search_zim_file.call_args.args[3] == 0


# Shared helper for handler-level tests that need a realistic backend mock.
def _handler_with(**overrides: Any) -> tuple[SimpleToolsHandler, MagicMock]:
    mock = MagicMock()
    mock.list_zim_files_data.return_value = [{"path": "/zims/test.zim"}]
    mock.config.meta.footer_enabled = False
    for name, value in overrides.items():
        setattr(mock, name, value)
    return SimpleToolsHandler(mock), mock


def _text(out: Any) -> str:
    """Human-readable body of a handler result, whatever its envelope."""
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        return str(out.get("message", ""))
    return str(out)


def _browse_cursor(*, offset: int = 5, limit: int = 5) -> str:
    state: Dict[str, Any] = {"o": offset, "l": limit, "ns": "C", "ai": "6d0b22d20314"}
    return Cursor.encode(tool="browse_namespace", state=state)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# D44: foreign cursors silently accepted by the intents without a guard
# ---------------------------------------------------------------------------


class TestD44ForeignCursorRejectedUniformly:
    """The dispatcher projects a decoded cursor's offset / limit into
    ``options`` for EVERY intent, but only five handlers rejected a
    cursor minted by another tool. A ``browse_namespace`` cursor handed
    to ``find article titled Measles`` was silently applied and resized
    the page from 10 to 5; ``tell me about`` swallowed it too.
    """

    @pytest.mark.parametrize(
        ("query", "backend_method"),
        [
            ("find article titled Measles", "find_entry_by_title_data"),
            ("find article titled Measles", "find_entry_by_title"),
            ("tell me about Measles", "search_zim_file_data"),
            ("suggestions for meas", "get_search_suggestions"),
            ("articles related to Measles", "get_related_entries"),
            ("get article Measles", "get_zim_entry"),
        ],
    )
    def test_unguarded_intents_reject_foreign_cursor(
        self, query: str, backend_method: str
    ) -> None:
        handler, mock = _handler_with()
        out = handler.handle_zim_query(
            query,
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": _browse_cursor()},
        )
        body = _text(out)
        assert "Cursor / Tool Mismatch" in body
        assert "browse_namespace" in body
        assert not getattr(mock, backend_method).called

    def test_find_by_title_page_size_not_resized_by_foreign_cursor(self) -> None:
        """Without a cursor the default page (10) reaches the backend; the
        foreign cursor's ``l=5`` must never get there.
        """
        handler, mock = _handler_with()
        handler.handle_zim_query(
            "find article titled Measles",
            zim_file_path="/zims/test.zim",
            options={"compact": True},
        )
        assert mock.find_entry_by_title_data.call_args.kwargs["limit"] == 10
        mock.find_entry_by_title_data.reset_mock()
        handler.handle_zim_query(
            "find article titled Measles",
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": _browse_cursor(limit=5)},
        )
        assert not mock.find_entry_by_title_data.called

    def test_guarded_handlers_keep_their_own_diagnosis(self) -> None:
        """The existing handler-edge guards stay authoritative for the
        cursor-consuming intents (no double rejection, same diagnosis).
        """
        handler, mock = _handler_with()
        out = handler.handle_zim_query(
            "walk namespace C",
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": _browse_cursor()},
        )
        body = _text(out)
        assert "Cursor / Tool Mismatch" in body
        assert "walk_namespace" in body
        assert not mock.walk_namespace_data.called
