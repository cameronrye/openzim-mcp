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
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from ..responses import ToolErrorPayload, tool_error
from ..synthesize import SynthesizeResponse
from ._common import enforce_rate_limit, load_description, tool_error_response

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

# Read description at IMPORT TIME from committed file shipped with the
# package. Per-tool packaging guard in test_phase_f_packaging.py
# verifies the wheel ships this file.
_DESCRIPTION = load_description("zim_query")


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
            rl = enforce_rate_limit(server, "zim_query")
            if rl is not None:
                return rl
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
                "max_content_length": (
                    max_content_length if max_content_length is not None else 4000
                ),
                "compact": compact,
                "synthesize": synthesize,
            }
            # M14: only set ``limit`` when the caller explicitly passed one
            # (mirroring offset / content_offset below). Forcing ``limit=3``
            # for every intent made all per-intent defaults unreachable via the
            # MCP surface — ``links in X`` returned 3 of thousands (not 25),
            # ``browse`` 3 (not 50), ``walk`` 3 (not 200),
            # find_by_title/related/suggestions 3 (not 10), search_all 3 per
            # file (not 5). With ``limit`` unset, each handler's
            # ``options.get("limit", N)`` per-intent default applies; the
            # tell_me_about body-fetch path still self-caps at 3.
            if limit is not None:
                options["limit"] = limit
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
            return tool_error_response(
                server,
                operation="zim_query",
                error=e,
                context=f"Query: {query}, File: {zim_file_path}",
            )
