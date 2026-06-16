"""zim_search — full-text / title / suggest dispatch. Phase F surface.

Collapses 5 legacy tools (search_zim_file + search_all +
search_with_filters + find_entry_by_title + get_search_suggestions)
into a single 3-mode entry point. The handler dispatches by `mode`
parameter; the description ships as a sibling `.md` file
(zim_search_description.md) per the same packaging pattern as
zim_query.

## Schema shape: flat with prose conditionals (rc1)

The spec's preferred wire shape is JSON Schema `oneOf` over the three
modes, gating `namespace`/`content_type` to fulltext-only and
`cross_file` to fulltext+title only. The spec calls for falling back
to flat schemas + handler validation when Gate 0.3 (small-model
parsing) is `unvalidated` — which is the rc0 state. The handler
below preserves the validation semantics either way: invalid
combinations return structured ToolErrorPayload with an
`invalid_combination` operation tag.

## Criterion C path

`_CRITERION_C_PATH` is baked in at rc1-PR time from the committed
Gate 0b decision. Production code does NOT read the decision file at
runtime — that file lives under `tests/` and isn't shipped in the
wheel. A drift between this constant and the decision file is caught
by Task D14a (gate-decision-consistency test) before merge.

  wired    — single-archive `mode="title"` applies Tier 1 + filler-
             prose preprocessing AND Z3/Z4/OPP-1 promotion via the
             extracted `topic_preprocessing.promote_topic_via_title_index`.
  fallback — `mode="title"` ships as explicit-string-only.

Per `tests/dispatch_eval/gate_0b_decision.json#criterion_c_path` at
rc0 sign-off: WIRED.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Optional

from ..constants import MAX_SEARCH_RESULT_LIMIT
from ..responses import tool_error
from ._common import enforce_rate_limit, load_description, tool_error_response

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

_DESCRIPTION = load_description("zim_search")

# Baked-in at rc1 PR time from gate_0b_decision.json. Drift between this
# value and the committed decision artifact is caught by
# tests/test_phase_f_gate_decision_consistency.py (Task D14a, lands
# alongside the orchestrator in D11).
_CRITERION_C_PATH: Literal["wired", "fallback"] = "wired"

_VALID_MODES = {"fulltext", "title", "suggest"}


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_search` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_search(
        query: str,
        mode: Literal["fulltext", "title", "suggest"] = "fulltext",
        zim_file_path: Optional[str] = None,
        cross_file: bool = False,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        cursor: Optional[str] = None,
    ) -> Any:
        # Return type is intentionally Any: the dispatch returns one of
        # SearchResponse / SearchAllResponse / SearchWithFiltersResponse /
        # FindEntryResponse / SearchSuggestionsResponse / ToolErrorPayload /
        # str (the fallback envelope from _create_enhanced_error_message).
        # The TypedDict union doesn't help small MCP clients here, and
        # narrowing per-branch hurts readability without runtime payoff.
        try:
            rl = enforce_rate_limit(server, "zim_search")
            if rl is not None:
                return rl
            if mode not in _VALID_MODES:
                return tool_error(
                    operation="invalid_mode",
                    message=(
                        f"`mode` must be one of {sorted(_VALID_MODES)} "
                        f"(provided: {mode!r})."
                    ),
                )
            if limit is not None and limit < 1:
                return tool_error(
                    operation="invalid_limit",
                    message=(
                        f"`limit` must be a positive integer (provided: {limit})."
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
            # H14: ``cursor`` was accepted and documented as overriding
            # ``offset``, but no mode ever decoded it — a client following the
            # documented ``next_cursor`` loop silently got page 1 forever.
            # Until cursor pagination is wired for this tool, reject a provided
            # cursor with a clear pointer to ``offset`` instead of looping.
            # (zim_browse / zim_links DO honor their cursors.)
            if cursor is not None and str(cursor).strip():
                return tool_error(
                    operation="invalid_combination",
                    message=(
                        "`cursor` pagination is not supported by zim_search. "
                        "Paginate single-archive `mode='fulltext'` results with "
                        "`offset` instead."
                    ),
                )
            # M28: only single-archive fulltext honors ``offset`` — the suggest,
            # title, and cross-file fulltext data calls have no offset parameter
            # and silently returned the same first page. Reject a non-zero
            # offset in those modes rather than dropping it.
            if offset and not (mode == "fulltext" and not cross_file):
                return tool_error(
                    operation="invalid_combination",
                    message=(
                        "`offset` pagination is only supported in single-archive "
                        f"fulltext mode; mode={mode!r}"
                        f"{', cross_file=True' if cross_file else ''} does not "
                        "paginate. Drop `offset`."
                    ),
                )
            if cross_file and zim_file_path is not None:
                return tool_error(
                    operation="invalid_combination",
                    message=(
                        "`zim_file_path` and `cross_file=True` are mutually "
                        "exclusive. Omit `zim_file_path` for cross-archive "
                        "fan-out, or set `cross_file=False` to pin an archive."
                    ),
                )

            if mode == "suggest":
                if cross_file:
                    return tool_error(
                        operation="invalid_combination",
                        message=(
                            "`mode='suggest'` does not support "
                            "`cross_file=True` — libzim's SuggestionSearcher "
                            "is per-archive. Pin a specific `zim_file_path` "
                            "or switch to `mode='fulltext'`/`'title'`."
                        ),
                    )
                resolved_path = _resolve_path(server, zim_file_path)
                if resolved_path is None:
                    return tool_error(
                        operation="missing_archive",
                        message=(
                            "No archive available for `mode='suggest'`. "
                            "Pass `zim_file_path` or load exactly one "
                            "archive at startup."
                        ),
                    )
                return await ops.get_search_suggestions_data(
                    resolved_path, query, limit if limit is not None else 10
                )

            if mode == "fulltext":
                return await _handle_fulltext_mode(
                    ops=ops,
                    server=server,
                    query=query,
                    zim_file_path=zim_file_path,
                    cross_file=cross_file,
                    namespace=namespace,
                    content_type=content_type,
                    limit=limit,
                    offset=offset,
                )

            # mode == "title"
            return await _handle_title_mode(
                ops=ops,
                server=server,
                query=query,
                zim_file_path=zim_file_path,
                cross_file=cross_file,
                limit=limit,
                offset=offset,
                cursor=cursor,
            )

        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            return tool_error_response(
                server,
                operation="zim_search",
                error=e,
                context=f"Query: {query}, Mode: {mode}",
            )


def _resolve_path(
    server: "OpenZimMcpServer", zim_file_path: Optional[str]
) -> Optional[str]:
    """Return an explicit ``zim_file_path`` or the auto-selected single
    archive when only one is loaded. Returns ``None`` when neither is
    available — callers raise a structured error."""
    from ..topic_preprocessing import auto_select_zim_file

    if zim_file_path:
        return zim_file_path
    return auto_select_zim_file(server.zim_operations)


async def _handle_fulltext_mode(
    *,
    ops: Any,
    server: "OpenZimMcpServer",
    query: str,
    zim_file_path: Optional[str],
    cross_file: bool,
    namespace: Optional[str],
    content_type: Optional[str],
    limit: Optional[int],
    offset: int,
) -> Any:
    """Dispatch fulltext mode to the right legacy data-layer call.

    Cross-archive uses ``search_all_data`` (the legacy SearchAllResponse
    shape carries per-archive sub-results — small models can iterate the
    `results` list naturally). Filter-bearing single-archive calls use
    `search_with_filters_data`; otherwise plain `search_zim_file_data`.
    """
    if cross_file:
        # search_all_data has no namespace/content_type filters in v2.0 —
        # if the caller passed either, surface the limitation explicitly.
        if namespace is not None or content_type is not None:
            return tool_error(
                operation="invalid_combination",
                message=(
                    "`namespace` and `content_type` filters are only "
                    "supported on single-archive fulltext search. Pin a "
                    "specific `zim_file_path` to use them."
                ),
            )
        payload = await ops.search_all_data(
            query, limit_per_file=limit if limit is not None else 5
        )
        return _strip_next_cursor(payload)

    resolved_path = _resolve_path(server, zim_file_path)
    if resolved_path is None:
        return tool_error(
            operation="missing_archive",
            message=(
                "No archive available for single-archive fulltext search. "
                "Pass `zim_file_path`, load exactly one archive at startup, "
                "or pass `cross_file=True` for fan-out."
            ),
        )

    if namespace is not None or content_type is not None:
        payload = await ops.search_with_filters_data(
            resolved_path,
            query,
            namespace=namespace,
            content_type=content_type,
            limit=limit,
            offset=offset,
        )
        return _strip_next_cursor(payload)

    payload = await ops.search_zim_file_data(
        resolved_path, query, limit=limit, offset=offset
    )
    return _strip_next_cursor(payload)


def _strip_next_cursor(payload: Any) -> Any:
    """Return a copy of ``payload`` with every followable ``next_cursor`` nulled.

    H14 residue: ``search_zim_file_data`` / ``search_with_filters_data`` encode
    a real ``next_cursor`` handle (tool="search_zim_file" / "search_with_filters")
    whenever a page is unexhausted, and ``search_all_data`` nests one per archive
    under ``results[].result.next_cursor``. zim_search has no cursor pagination —
    it *rejects* a caller-provided ``cursor`` (see the ``invalid_combination``
    guard above) and pages via ``offset`` — so returning any data-layer cursor
    verbatim would advertise a handle the tool then refuses. Blank them all.

    COPY-ON-WRITE: the data layer hands out cache-by-reference dicts (``cache.get``
    returns the stored object), shared with the zim_query path which DOES surface
    ``next_cursor``. Mutating in place would poison the cache (the H12 defect
    class), so this never mutates the input — it shallow-copies only the dicts it
    has to touch.
    """
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    if "next_cursor" in out:
        out["next_cursor"] = None
    # Cross-file (search_all_data): null the per-archive nested cursors too.
    results = out.get("results")
    if isinstance(results, list):
        new_results = []
        changed = False
        for row in results:
            if (
                isinstance(row, dict)
                and isinstance(row.get("result"), dict)
                and row["result"].get("next_cursor") is not None
            ):
                row = {**row, "result": {**row["result"], "next_cursor": None}}
                changed = True
            new_results.append(row)
        if changed:
            out["results"] = new_results
    return out


async def _handle_title_mode(
    *,
    ops: Any,
    server: "OpenZimMcpServer",
    query: str,
    zim_file_path: Optional[str],
    cross_file: bool,
    limit: Optional[int],
    offset: int,
    cursor: Optional[str],
) -> Any:
    """Title-mode dispatch with conditional preprocessing + promotion.

    Behavior depends on ``_CRITERION_C_PATH``:
      - ``wired``    applies Tier 1 + filler-prose preprocessing AND
                     Z3/Z4/OPP-1 promotion via
                     ``topic_preprocessing.promote_topic_via_title_index``
                     when ``cross_file=False``. Cross-archive title
                     mode skips promotion (per-archive only) and
                     surfaces a `_meta.hint` documenting that pinning
                     an archive enables it.
      - ``fallback`` ships as pass-through: explicit-string-only title
                     lookup, no preprocessing, no promotion.
    """
    if _CRITERION_C_PATH == "fallback":
        return await ops.find_entry_by_title_data(
            zim_file_path or "",
            query,
            cross_file=cross_file,
            limit=limit if limit is not None else 10,
        )

    # Wired path — apply preprocessing.
    from ..intent_parser import IntentParser

    preprocessed = IntentParser._apply_misspelling_map(query, title_probe=None)
    preprocessed = IntentParser._detect_stopword_phrase(preprocessed, title_probe=None)

    if cross_file:
        raw = await ops.find_entry_by_title_data(
            "",
            preprocessed,
            cross_file=True,
            limit=limit if limit is not None else 10,
        )
        # Promotion is per-archive; surface the limitation so the
        # caller knows pinning a specific archive enables Z3/Z4/OPP-1.
        meta = raw.setdefault("_meta", {})
        meta["promotion_applied"] = False
        meta["hint"] = (
            "Z3/Z4/OPP-1 promotion is per-archive. Pin a specific "
            "`zim_file_path` to enable promotion."
        )
        return raw

    resolved_path = _resolve_path(server, zim_file_path)
    if resolved_path is None:
        # Multiple archives loaded but none pinned — promotion cannot
        # run safely. Fall back to a clean error rather than guessing.
        return tool_error(
            operation="missing_archive",
            message=(
                "No archive available for `mode='title'`. Pass "
                "`zim_file_path`, load exactly one archive at startup, "
                "or pass `cross_file=True` to fan out without promotion."
            ),
        )

    raw = await ops.find_entry_by_title_data(
        resolved_path,
        preprocessed,
        cross_file=False,
        limit=limit if limit is not None else 10,
    )

    from ..topic_preprocessing import promote_topic_via_title_index

    promoted = promote_topic_via_title_index(
        zim_operations=server.zim_operations,
        zim_file_path=resolved_path,
        topic=preprocessed,
    )
    return _merge_promotion_into_title_results(raw, promoted)


def _merge_promotion_into_title_results(raw: dict, promoted: Optional[dict]) -> dict:
    """Apply Z3/Z4/OPP-1 promotion as a post-filter on raw title-lookup
    results. The promoted entry is hoisted to the top of `results`; other
    matches keep their relative ranking. Promotion that returns None
    passes the raw response through unchanged.

    ``raw`` follows the legacy FindEntryResponse shape: list of
    candidate rows under ``results`` (NOT ``matches``) — see
    tool_schemas.FindEntryResponse.
    """
    if promoted is None:
        return raw
    matches = raw.get("results", [])
    promoted_path = promoted.get("path") or promoted.get("entry_path")
    if not matches:
        return raw
    top = matches[0]
    top_path = top.get("entry_path") or top.get("path")
    if top_path == promoted_path:
        return raw
    hoisted = [
        m for m in matches if (m.get("entry_path") or m.get("path")) != promoted_path
    ]
    # COPY-ON-WRITE: ``raw`` is the cached ``find_title:v1`` object (H15 caches
    # single-archive title lookups, returned by reference) and is shared with
    # the internal promotion probes that read the same key. Mutating it in place
    # would poison that cache (the H12 defect class), so build a new dict.
    out = dict(raw)
    out["results"] = [promoted] + hoisted
    out["_meta"] = {**raw.get("_meta", {}), "promotion_applied": True}
    return out
