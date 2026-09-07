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

from ..config import SYNTHESIZE_MAX_PASSAGES
from ..constants import MAX_QUERY_LENGTH, MAX_SEARCH_RESULT_LIMIT
from ..responses import tool_error
from ._common import (
    READ_ONLY_ANNOTATIONS,
    enforce_rate_limit,
    load_description,
    tool_error_response,
)

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

# Read description at IMPORT TIME from committed file shipped with the
# package. Per-tool packaging guard in test_phase_f_packaging.py
# verifies the wheel ships this file.
_DESCRIPTION = load_description("zim_query")

# ``MAX_QUERY_LENGTH`` is re-exported from ``constants`` (imported above) so
# existing ``tools.zim_query.MAX_QUERY_LENGTH`` references keep working; the
# bound itself is shared with zim_search, which echoes the same argument.


def register(server: "OpenZimMcpServer") -> None:
    """Register the ``zim_query`` tool with the MCP server.

    Mirrors the b13 ``server._register_simple_tools`` surface; the only
    move is the registration site. ``handle_zim_query`` is synchronous
    and performs blocking ZIM I/O, so the tool dispatches via
    ``asyncio.to_thread`` to keep the event loop free.
    """

    @server.mcp.tool(description=_DESCRIPTION, annotations=READ_ONLY_ANNOTATIONS)
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
    ) -> Any:
        # Annotated ``Any`` — matching the other 7 tools — so the SDK derives
        # no ``outputSchema``. The previous ``Union[str, SynthesizeResponse,
        # ToolErrorPayload]`` annotation generated a 4.7KB schema (16% of the
        # whole advanced surface) that described a ``{"result": "<markdown>"}``
        # wrapper: the SDK wraps non-dict returns, and this tool's ordinary
        # return is a markdown string. Clients got a schema promising nothing
        # they couldn't already read from the text block, and the surface paid
        # for it in every request. The runtime return shapes are unchanged.
        try:
            rl = enforce_rate_limit(server, "zim_query")
            if rl is not None:
                return rl
            # Front-door cap on the natural-language query. The intent
            # parser runs dozens of regexes over this string and CPython's
            # ``re`` holds the GIL for the whole match, so the nominal
            # per-regex timeout cannot interrupt a pathological input — an
            # oversized query is a process-wide availability risk, not just a
            # slow request. No legitimate natural-language query approaches
            # this length (the longest in the test corpus is ~200 chars).
            if len(query) > MAX_QUERY_LENGTH:
                return tool_error(
                    operation="invalid_query",
                    message=(
                        f"`query` must not exceed {MAX_QUERY_LENGTH} characters "
                        f"(provided: {len(query)}). Pass a natural-language "
                        "request, not a document."
                    ),
                )
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
            if limit is not None and limit > MAX_SEARCH_RESULT_LIMIT:
                return tool_error(
                    operation="invalid_limit",
                    message=(
                        f"`limit` must not exceed {MAX_SEARCH_RESULT_LIMIT} "
                        f"(provided: {limit}). Page through larger result sets "
                        "with `offset` instead."
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

            # v3.3.1 field report (fid 130). `limit`, `offset`,
            # `content_offset` and `cursor` were range-checked here and then
            # dropped: `_handle_synthesize_query` never received them, so
            # `limit=50` and `limit=1000` returned byte-identical payloads
            # while `limit=1001` was rejected — the tool validating an
            # argument on a path that ignores it.
            #
            # `limit` maps onto the pipeline's own passage count
            # (`SynthesizeConfig.top_n`, bounded 1..50), so it is honoured
            # below. Past that bound there is nothing to honour, and a
            # silent clamp would be the same defect one size down. The
            # pipeline fuses a single ranked set and does not paginate at
            # all, so the paging arguments are refused rather than mapped
            # onto something that does not exist.
            if synthesize:
                if limit is not None and limit > SYNTHESIZE_MAX_PASSAGES:
                    return tool_error(
                        operation="invalid_limit",
                        message=(
                            "`limit` must not exceed "
                            f"{SYNTHESIZE_MAX_PASSAGES} with `synthesize=True` "
                            f"(provided: {limit}) — it selects the number of "
                            "cited passages, not a page size. Re-run at or "
                            "below the cap."
                        ),
                    )
                unpaginated = [
                    name
                    for name, value in (
                        ("offset", offset),
                        ("content_offset", content_offset),
                        ("cursor", cursor),
                    )
                    if value
                ]
                if unpaginated:
                    named = " and ".join(f"`{n}`" for n in unpaginated)
                    return tool_error(
                        operation="invalid_combination",
                        message=(
                            f"{named} cannot be used with `synthesize=True`: "
                            "the synthesize pipeline fuses one ranked set "
                            "across every archive and has no next page. Drop "
                            f"{'them' if len(unpaginated) > 1 else 'it'}, or "
                            "use `synthesize=False` to page a search."
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
