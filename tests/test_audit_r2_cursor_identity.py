"""Regression tests: simple-mode cursors are bound to their archive.

``handle_zim_query`` decodes the caller's ``cursor`` and stashes its
``s.ai`` archive identity into ``options["_cursor_ai"]``, but only
``_handle_walk_namespace`` ever consumed it. ``_handle_browse`` /
``_handle_search`` / ``_handle_filtered_search`` routed to backend
surfaces that never received a ``cursor_archive_identity``, so a cursor
minted against archive A replayed against archive B passed the tool and
namespace guards and silently paginated the wrong corpus — the exact
failure ``Cursor.verify_archive_identity`` exists to prevent.

The advanced tools (``zim_browse`` / ``zim_links``) forward ``s.ai`` to
the data layer; these tests pin the same binding at the simple-tools
handler edge, plus the same-archive round trips that must keep working.
"""

from pathlib import Path
from typing import Dict, Optional
from unittest.mock import MagicMock

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.pagination import Cursor, archive_identity
from openzim_mcp.security import PathValidator
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.zim_operations import ZimOperations


def _body(out: object) -> str:
    """Readable body of a handler result: the ``message`` of a
    ``ToolErrorPayload`` envelope, or the markdown string itself."""
    if isinstance(out, dict):
        return str(out.get("message", ""))
    return str(out)


MISMATCH_TITLE = "Cursor / Archive Mismatch"


class TestCrossArchiveCursorReplayRejected:
    """A cursor issued against archive A must not paginate archive B."""

    @pytest.fixture
    def archives(
        self, real_content_zim_files: Dict[str, Optional[Path]]
    ) -> Dict[str, Path]:
        a = real_content_zim_files.get("wikipedia_climate")
        b = real_content_zim_files.get("wikibooks")
        if a is None or b is None:
            pytest.skip("real content ZIM fixtures not available")
        return {"a": a, "b": b}

    @pytest.fixture
    def ops(self, archives: Dict[str, Path]) -> ZimOperations:
        cfg = OpenZimMcpConfig(
            allowed_directories=[str(archives["a"].parent.parent)],
            cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
            content=ContentConfig(max_content_length=2000, snippet_length=100),
            logging=LoggingConfig(level="ERROR"),
        )
        return ZimOperations(
            cfg,
            PathValidator(cfg.allowed_directories),
            OpenZimMcpCache(cfg.cache),
            ContentProcessor(snippet_length=100),
        )

    @pytest.fixture
    def handler(self, ops: ZimOperations) -> SimpleToolsHandler:
        return SimpleToolsHandler(ops)

    def test_browse_cursor_from_other_archive_is_rejected(
        self,
        handler: SimpleToolsHandler,
        ops: ZimOperations,
        archives: Dict[str, Path],
    ) -> None:
        page1 = ops.browse_namespace_data(str(archives["a"]), "A", limit=5, offset=0)
        cursor = page1["next_cursor"]
        assert cursor

        out = handler.handle_zim_query(
            "browse namespace A",
            str(archives["b"]),
            options={"cursor": cursor, "limit": 5},
        )
        assert isinstance(out, dict), f"expected envelope, got {type(out)!r}: {out!r}"
        assert MISMATCH_TITLE in _body(out), _body(out)[:400]
        # Pre-fix, archive B's namespace-A rows came back at A's offset.
        assert "results" not in _body(out)

    def test_browse_cursor_round_trips_on_issuing_archive(
        self,
        handler: SimpleToolsHandler,
        ops: ZimOperations,
        archives: Dict[str, Path],
    ) -> None:
        page1 = ops.browse_namespace_data(str(archives["a"]), "A", limit=5, offset=0)
        cursor = page1["next_cursor"]
        assert cursor

        out = handler.handle_zim_query(
            "browse namespace A",
            str(archives["a"]),
            options={"cursor": cursor, "limit": 5},
        )
        assert isinstance(out, str)
        assert MISMATCH_TITLE not in _body(out)
        assert "results" in out

    def test_search_cursor_from_other_archive_is_rejected(
        self,
        handler: SimpleToolsHandler,
        ops: ZimOperations,
        archives: Dict[str, Path],
    ) -> None:
        page1 = ops.search_zim_file_data(str(archives["a"]), "climate", 5, 0)
        cursor = page1["next_cursor"]
        assert cursor

        out = handler.handle_zim_query(
            "search for climate",
            str(archives["b"]),
            options={"cursor": cursor, "limit": 5},
        )
        assert isinstance(out, dict), f"expected envelope, got {type(out)!r}: {out!r}"
        assert MISMATCH_TITLE in _body(out), _body(out)[:400]

    def test_search_cursor_round_trips_on_issuing_archive(
        self,
        handler: SimpleToolsHandler,
        ops: ZimOperations,
        archives: Dict[str, Path],
    ) -> None:
        page1 = ops.search_zim_file_data(str(archives["a"]), "climate", 5, 0)
        cursor = page1["next_cursor"]
        assert cursor

        out = handler.handle_zim_query(
            "search for climate",
            str(archives["a"]),
            options={"cursor": cursor, "limit": 5},
        )
        assert isinstance(out, str)
        assert MISMATCH_TITLE not in _body(out)

    def test_filtered_search_cursor_from_other_archive_is_rejected(
        self,
        handler: SimpleToolsHandler,
        ops: ZimOperations,
        archives: Dict[str, Path],
    ) -> None:
        page1 = ops.search_with_filters_data(
            str(archives["a"]), "climate", "A", None, 5, 0
        )
        cursor = page1["next_cursor"]
        assert cursor

        out = handler.handle_zim_query(
            "search for climate in namespace A",
            str(archives["b"]),
            options={"cursor": cursor, "limit": 5},
        )
        assert isinstance(out, dict), f"expected envelope, got {type(out)!r}: {out!r}"
        assert MISMATCH_TITLE in _body(out), _body(out)[:400]

    def test_filtered_search_cursor_round_trips_on_issuing_archive(
        self,
        handler: SimpleToolsHandler,
        ops: ZimOperations,
        archives: Dict[str, Path],
    ) -> None:
        page1 = ops.search_with_filters_data(
            str(archives["a"]), "climate", "A", None, 5, 0
        )
        cursor = page1["next_cursor"]
        assert cursor

        out = handler.handle_zim_query(
            "search for climate in namespace A",
            str(archives["a"]),
            options={"cursor": cursor, "limit": 5},
        )
        assert isinstance(out, str)
        assert MISMATCH_TITLE not in _body(out)

    def test_browse_without_cursor_unaffected(
        self, handler: SimpleToolsHandler, archives: Dict[str, Path]
    ) -> None:
        out = handler.handle_zim_query(
            "browse namespace A",
            str(archives["b"]),
            options={"limit": 5},
        )
        assert isinstance(out, str)
        assert MISMATCH_TITLE not in _body(out)
        assert "results" in out


class TestCursorArchiveGuardEdges:
    """Handler-edge behaviour that does not need a real archive."""

    @staticmethod
    def _handler() -> MagicMock:
        ops = MagicMock()
        ops.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        ops.config.meta.footer_enabled = False
        ops.path_validator.validate_path.return_value = Path("/x.zim")
        ops.path_validator.validate_zim_file.return_value = Path("/x.zim")
        return ops

    def test_matching_identity_reaches_backend(self) -> None:
        ops = self._handler()
        ops.browse_namespace.return_value = '{"results": []}'
        handler = SimpleToolsHandler(ops)
        cursor = Cursor.encode(
            tool="browse_namespace",
            state={  # type: ignore[typeddict-item]
                "o": 5,
                "l": 5,
                "ns": "C",
                "ai": archive_identity(Path("/x.zim")),
            },
        )

        out = handler.handle_zim_query(
            "browse namespace C", "/x.zim", options={"cursor": cursor, "limit": 5}
        )
        assert isinstance(out, str)
        assert MISMATCH_TITLE not in _body(out)
        assert ops.browse_namespace.called

    def test_foreign_identity_blocks_backend_call(self) -> None:
        ops = self._handler()
        ops.browse_namespace.return_value = '{"results": []}'
        handler = SimpleToolsHandler(ops)
        cursor = Cursor.encode(
            tool="browse_namespace",
            state={  # type: ignore[typeddict-item]
                "o": 5,
                "l": 5,
                "ns": "C",
                "ai": archive_identity(Path("/other.zim")),
            },
        )

        out = handler.handle_zim_query(
            "browse namespace C", "/x.zim", options={"cursor": cursor, "limit": 5}
        )
        assert isinstance(out, dict), f"expected envelope, got {type(out)!r}: {out!r}"
        assert MISMATCH_TITLE in _body(out)
        assert not ops.browse_namespace.called


ENTRY_MISMATCH_TITLE = "Cursor / Article Mismatch"


class TestLinksCursorEntryBinding:
    """P26 / P35: ``_handle_links`` must reject a links cursor minted on a
    different article (or a different archive) instead of applying its offset.

    Pre-fix the only guard was the tool-name check, which passes for *any*
    links cursor, while the offset WAS forwarded — so a cursor for article A
    returned article B's links starting mid-list, silently skipping page 1.

    These tests must run with ``compact=True``: the non-compact path ignores
    ``offset`` entirely and would pass vacuously.
    """

    @staticmethod
    def _ops() -> MagicMock:
        ops = MagicMock()
        ops.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        ops.config.meta.footer_enabled = False
        ops.path_validator.validate_path.return_value = Path("/x.zim")
        ops.path_validator.validate_zim_file.return_value = Path("/x.zim")
        ops.extract_article_links_data.return_value = {
            "title": "Berlin",
            "path": "A/Berlin",
            "results": [],
            "category_totals": {"internal": 0, "external": 0},
        }
        return ops

    @staticmethod
    def _cursor(entry_path: str, archive: str = "/x.zim") -> str:
        return Cursor.encode(
            tool="extract_article_links",
            state={  # type: ignore[typeddict-item]
                "o": 25,
                "l": 25,
                "ep": entry_path,
                "k": "internal",
                "ai": archive_identity(Path(archive)),
            },
        )

    def test_links_cursor_for_other_article_is_rejected(self) -> None:
        ops = self._ops()
        handler = SimpleToolsHandler(ops)
        out = handler.handle_zim_query(
            "links in Berlin",
            "/x.zim",
            options={
                "cursor": self._cursor("A/Photosynthesis"),
                "compact": True,
            },
        )
        assert isinstance(out, dict), f"expected envelope, got {type(out)!r}: {out!r}"
        assert ENTRY_MISMATCH_TITLE in _body(out), _body(out)[:400]
        assert not ops.extract_article_links_data.called

    def test_links_cursor_round_trips_across_case_and_underscores(self) -> None:
        """The simple-mode path has been through intent parsing, so the cursor's
        raw ``ep`` differs only in case / ``_`` form — that must be accepted."""
        ops = self._ops()
        handler = SimpleToolsHandler(ops)
        out = handler.handle_zim_query(
            "links in climate change",
            "/x.zim",
            options={
                "cursor": self._cursor("Climate_Change"),
                "compact": True,
            },
        )
        assert isinstance(out, str)
        assert ENTRY_MISMATCH_TITLE not in _body(out), _body(out)[:400]
        assert ops.extract_article_links_data.called
        # The cursor's ``k`` scopes its offset to that bucket: the internal
        # fetch resumes at 25 while the external fetch starts fresh.
        offsets = {
            kwargs.get("kind"): kwargs.get("offset")
            for _, kwargs in ops.extract_article_links_data.call_args_list
        }
        assert offsets.get("internal") == 25
        assert offsets.get("external") == 0

    def test_links_cursor_from_other_archive_is_rejected(self) -> None:
        """P35: ``_handle_links`` was the only cursor-consuming simple-mode
        handler with no archive-identity guard."""
        ops = self._ops()
        handler = SimpleToolsHandler(ops)
        out = handler.handle_zim_query(
            "links in Berlin",
            "/x.zim",
            options={
                "cursor": self._cursor("Berlin", archive="/other.zim"),
                "compact": True,
            },
        )
        assert isinstance(out, dict), f"expected envelope, got {type(out)!r}: {out!r}"
        assert MISMATCH_TITLE in _body(out), _body(out)[:400]
        assert not ops.extract_article_links_data.called
