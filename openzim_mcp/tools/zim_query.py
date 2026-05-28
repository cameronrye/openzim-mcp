"""zim_query — natural-language entry point. Phase F surface.

Hoists the b13 ``zim_query`` registration from ``server._register_simple_tools``
into a per-tool module under ``openzim_mcp/tools/``. The handler body
(parameter validation, options dict, async-thread dispatch via
``SimpleToolsHandler.handle_zim_query``, error envelope) is preserved
byte-for-byte from the b13 surface — the only thing moving is the
registration site. The description is committed as a sibling
``zim_query_description.md`` file (b13 docstring verbatim) and read at
import time, packaged via ``[tool.setuptools.package-data]``.

The Task D14b prototype-rc1 schema-parity test pins the resulting
wire footprint to within ±5% bytes of the prototype's snapshot — drift
beyond that flips the test red so the description doesn't silently
diverge from what Gate 0b measured.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from ..responses import ToolErrorPayload, tool_error
from ..synthesize import SynthesizeResponse

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

# Read description at IMPORT TIME from committed file shipped with the
# package. Per-tool packaging guard in test_phase_f_packaging.py
# verifies the wheel ships this file.
_DIR = pathlib.Path(__file__).parent
_DESCRIPTION = (_DIR / "zim_query_description.md").read_text(encoding="utf-8")


def register(server: "OpenZimMcpServer") -> None:
    """Register the ``zim_query`` tool with the MCP server.

    Mirrors the b13 ``server._register_simple_tools`` surface; the only
    move is the registration site. ``handle_zim_query`` is synchronous
    and performs blocking ZIM I/O, so the tool dispatches via
    ``asyncio.to_thread`` to keep the event loop free.
    """

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_query(
        query: str,
        zim_file_path: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        content_offset: int = 0,
        cursor: Optional[str] = None,
        max_content_length: Optional[int] = None,
        compact: bool = True,
        compact_budget: Optional[Union[str, int]] = None,
        synthesize: bool = False,
    ) -> Union[str, SynthesizeResponse, ToolErrorPayload]:
        try:
            if content_offset < 0:
                return tool_error(
                    operation="invalid_content_offset",
                    message=(
                        "`content_offset` must be non-negative "
                        f"(provided: {content_offset})."
                    ),
                )
            if limit is not None and limit < 1:
                return tool_error(
                    operation="invalid_limit",
                    message=(
                        "`limit` must be a positive integer " f"(provided: {limit})."
                    ),
                )
            if offset < 0:
                return tool_error(
                    operation="invalid_offset",
                    message=(f"`offset` must be non-negative (provided: {offset})."),
                )
            # Post-v2.0.0 D-F: `max_content_length` was the only sibling
            # of `limit` / `offset` / `content_offset` without an upfront
            # validator. Pre-fix `max_content_length <= 0` silently meant
            # "no limit" because the truncation site
            # (`simple_tools.py:3329-3334`) gates on `max_len > 0`. That
            # contradicts the param contract (positive char-cap) and
            # diverges from the existing `limit < 1` rejection shape.
            if max_content_length is not None and max_content_length < 1:
                return tool_error(
                    operation="invalid_max_content_length",
                    message=(
                        "`max_content_length` must be a positive integer "
                        f"(provided: {max_content_length})."
                    ),
                )

            # Simple-mode defaults: 3 results × 4 000-char bodies fit
            # comfortably in an 8B Q4 model's agentic prompt window.
            # Callers can override via explicit limit / max_content_length.
            options: Dict[str, Any] = {
                "limit": limit if limit is not None else 3,
                "max_content_length": (
                    max_content_length if max_content_length is not None else 4000
                ),
                "compact": compact,
                "synthesize": synthesize,
            }
            if offset != 0:
                options["offset"] = offset
            if content_offset != 0:
                options["content_offset"] = content_offset
            if compact_budget is not None:
                options["compact_budget"] = compact_budget
            if cursor is not None and str(cursor).strip():
                options["cursor"] = str(cursor).strip()

            if server.simple_tools_handler:
                handler = server.simple_tools_handler
                return await asyncio.to_thread(
                    handler.handle_zim_query, query, zim_file_path, options
                )
            return "Error: Simple tools handler not initialized"

        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            logger.error(f"Error in zim_query: {e}")
            return server._create_enhanced_error_message(
                operation="zim_query",
                error=e,
                context=f"Query: {query}, File: {zim_file_path}",
            )
