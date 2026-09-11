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

import asyncio
from typing import TYPE_CHECKING, Any, Literal, Optional

from ..constants import MAX_QUERY_LENGTH, MAX_SEARCH_RESULT_LIMIT
from ..responses import tool_error
from ..zim.search import demote_crawl_artefacts
from ._common import (
    READ_ONLY_ANNOTATIONS,
    enforce_rate_limit,
    load_description,
    tool_error_response,
)

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

_DESCRIPTION = load_description("zim_search")

# Baked-in at rc1 PR time from gate_0b_decision.json. Drift between this
# value and the committed decision artifact is caught by
# tests/test_phase_f_gate_decision_consistency.py (Task D14a, lands
# alongside the orchestrator in D11).
_CRITERION_C_PATH: Literal["wired", "fallback"] = "wired"

_VALID_MODES = {"fulltext", "title", "suggest"}

# The title / suggest data-layer calls cap ``limit`` at 50
# (``find_entry_by_title_data`` / ``get_search_suggestions_data``); only
# fulltext accepts the full ``MAX_SEARCH_RESULT_LIMIT`` range. Validating
# the tighter cap here keeps the rejection a structured ``invalid_limit``
# envelope instead of a generic broad-except one.
_CAPPED_LIMIT_MODES = {"title", "suggest"}
_CAPPED_MODE_RESULT_LIMIT = 50

# Fulltext's dispatch targets carry their own data-layer caps, mirrored here
# for the same reason: ``search_all_data`` rejects ``limit_per_file`` > 50
# and ``search_with_filters_data`` rejects ``limit`` > 100 (both in
# ``zim/search.py``); only plain single-archive fulltext accepts the full
# ``MAX_SEARCH_RESULT_LIMIT`` range.
_CROSS_FILE_RESULT_LIMIT = 50
_FILTERED_RESULT_LIMIT = 100

# Page size title mode asks the data layer for when the caller omits ``limit``.
_TITLE_DEFAULT_LIMIT = 10


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_search` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION, annotations=READ_ONLY_ANNOTATIONS)
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
            # Price/limit on the INTERNAL operation this call will dispatch to
            # — ``zim_search`` is a multiplexer and is absent from
            # ``RATE_LIMIT_COSTS``, so keying the bucket on the wire name made
            # every mode cost 1 and made ``per_operation_limits`` overrides
            # (documented against these internal names) silently inert.
            if mode == "suggest":
                _rl_op = "suggestions"
            elif mode == "title":
                _rl_op = "find_entry_by_title"
            elif namespace or content_type:
                _rl_op = "search_with_filters"
            else:
                _rl_op = "search"
            rl = enforce_rate_limit(server, _rl_op)
            if rl is not None:
                return rl
            # Same front-door cap as zim_query (D59): the query is run
            # through the misspelling map's regexes and echoed back verbatim
            # in ``query`` / ``partial_query``, so an unbounded input is both
            # GIL-held regex work no timeout can interrupt and a 1:1
            # response amplifier. Checked before ``mode`` so the rejection
            # never depends on which branch would have echoed it.
            if len(query) > MAX_QUERY_LENGTH:
                return tool_error(
                    operation="invalid_query",
                    message=(
                        f"`query` must not exceed {MAX_QUERY_LENGTH} characters "
                        f"(provided: {len(query)}). Pass search terms, not a "
                        "document."
                    ),
                )
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
            if mode in _CAPPED_LIMIT_MODES:
                max_limit = _CAPPED_MODE_RESULT_LIMIT
            elif cross_file:
                max_limit = _CROSS_FILE_RESULT_LIMIT
            elif namespace is not None or content_type is not None:
                # ``is not None`` matches the dispatch condition in
                # ``_handle_fulltext_mode``, not truthiness.
                max_limit = _FILTERED_RESULT_LIMIT
            else:
                max_limit = MAX_SEARCH_RESULT_LIMIT
            if limit is not None and limit > max_limit:
                # Only single-archive fulltext paginates — recommending
                # `offset` anywhere else points at the M28 rejection below.
                hint = (
                    "Page through larger result sets with `offset` instead."
                    if mode == "fulltext" and not cross_file
                    else "This mode returns one unpaginated page."
                )
                return tool_error(
                    operation="invalid_limit",
                    message=(
                        f"`limit` must not exceed {max_limit} for mode={mode!r}"
                        f"{' with cross_file=True' if cross_file else ''} "
                        f"(provided: {limit}). {hint}"
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
            # Only ``_handle_fulltext_mode`` was ever handed these — the title
            # and suggest data calls have no filter parameters, so both
            # arguments were accepted in every mode and dropped in two of the
            # three. A model asking for one namespace got every namespace,
            # with nothing in the payload saying the filter had gone. Same
            # class as the M28 ``offset`` guard above: reject the call rather
            # than answer a narrower question than the one that was asked.
            if mode != "fulltext" and (
                namespace is not None or content_type is not None
            ):
                dropped = " and ".join(
                    f"`{name}`"
                    for name, value in (
                        ("namespace", namespace),
                        ("content_type", content_type),
                    )
                    if value is not None
                )
                return tool_error(
                    operation="invalid_combination",
                    message=(
                        f"{dropped} filtering is only supported in "
                        f"`mode='fulltext'`; mode={mode!r} has no filter step "
                        "and would return unfiltered results. Switch to "
                        "`mode='fulltext'`, or drop the filter."
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
                    if _no_archives_loaded(server):
                        return _no_archives_error()
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


def _no_archives_loaded(server: "OpenZimMcpServer") -> bool:
    """Whether the allowed directories hold no ``.zim`` file at all.

    Consulted only on a path that is already failing or already empty, so
    the directory listing never lands on the success path.
    """
    try:
        return not server.zim_operations.list_zim_files_data()
    except Exception:  # pragma: no cover — defensive; a probe must not throw
        return False


def _no_archives_error() -> Any:
    """The structured refusal for "there is nothing loaded to search".

    v3.3.1 field report (fids 2/3). Two shapes of the same defect:

    * ``cross_file=True`` over zero archives returned ``isError=false`` with
      an empty ``results`` list — indistinguishable from a genuine miss, so
      a model would rephrase the query forever. Simple mode has answered
      this condition with "**No ZIM Archives Loaded**" all along
      (``simple_tools._nothing_to_search_response``); the advanced tool
      never applied it.
    * ``_resolve_path`` returns ``None`` for two different worlds — zero
      archives loaded and two-or-more loaded without one pinned — and the
      ``missing_archive`` advice only fitted the second. On an empty server
      all three of its steps are dead ends: there is no path to pass,
      nothing to load, and ``cross_file=True`` returned the silent empty
      page above.
    """
    from ..onboarding import acquisition_hint_line

    return tool_error(
        operation="no_archives_loaded",
        message=(
            "No ZIM archives are loaded: the allowed directories contain no "
            "`.zim` files, so there is nothing to search. "
            f"{acquisition_hint_line()}"
        ),
    )


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
        # An empty fan-out is only "no hits" when there was something to fan
        # out over. ``files_available`` comes straight off the payload, so
        # this costs no extra directory listing.
        if isinstance(payload, dict) and payload.get("files_available") == 0:
            return _no_archives_error()
        return _annotate_cross_file_paging(_strip_next_cursor(payload))

    resolved_path = _resolve_path(server, zim_file_path)
    if resolved_path is None:
        if _no_archives_loaded(server):
            return _no_archives_error()
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
        return _name_the_archive(_strip_next_cursor(payload), resolved_path)

    payload = await ops.search_zim_file_data(
        resolved_path, query, limit=limit, offset=offset
    )
    payload = await _splice_canonical_title_hit(
        server, payload, resolved_path=resolved_path, query=query, offset=offset
    )
    return _name_the_archive(_strip_next_cursor(payload), resolved_path)


def _name_the_archive(payload: Any, resolved_path: str) -> Any:
    """Stamp the resolved archive onto a single-archive fulltext response.

    v3.3.1 field report (fid 27): ``zim_file_path`` is optional on
    ``zim_search`` and required on ``zim_get`` / ``zim_get_section`` /
    ``zim_links`` / ``zim_browse`` / ``zim_metadata``. On the one-archive
    deployment the README quickstart describes, the caller omits it, the
    server auto-selects — and then nothing in the fulltext page says which
    archive answered, so the obvious next call is rejected for a field the
    caller has no way to fill. ``mode='title'`` had carried ``zim_file`` on
    every hit all along, which made the gap worse than a plain omission: it
    taught the shape and then broke it.

    Stamped once at the top level rather than onto every row. The rows are
    what the response budget is spent on (``SEARCH.MAX_RESULT_CHARS``, which
    counts ``path``/``title``/``snippet``), so repeating one absolute path
    across a 1000-row page would have added six figures of payload that the
    budget does not see — the exact shape of the caps defect this same
    report opened with.

    Applied unconditionally, including when the caller pinned the path.
    A field that appears only on auto-selected pages is one more thing for
    a model to branch on, and asymmetry between two ways of asking the same
    question is what this finding is.
    """
    if isinstance(payload, dict) and not payload.get("error"):
        from ..meta import remeasure

        payload["zim_file_path"] = resolved_path
        # The data layer measured the payload before this field existed, so
        # ``_meta.chars`` would under-report the body by exactly the path it
        # now carries. Same defect as the splice's stale envelope, and the
        # same reason it matters: a size a caller budgets against has to be
        # the size that ships.
        remeasure(payload)
    return payload


# ``_meta`` keys that describe the SOURCE rather than the rendered page, so
# they survive a splice rewrite. Mirrors ``_PROMOTION_CARRIED_META_KEYS``
# below; kept separate because the two rewrites carry different verdicts.
_SPLICE_CARRIED_META_KEYS = (
    "detected_type",
    "detection_confidence",
    "preset_applied",
)


async def _splice_canonical_title_hit(
    server: "OpenZimMcpServer",
    payload: Any,
    *,
    resolved_path: str,
    query: str,
    offset: int,
) -> Any:
    """Promote the canonical title-index hit onto a fulltext page.

    v3.3.1 field report (fid 58): ``_splice_title_match_into_search`` — the
    canonical-title promotion plus the list/catalog demote — was wired into
    ``simple_tools`` only. ``zim_search(mode='fulltext')``, the tool whose
    whole job is search, called the data layer raw. On the shipped philosophy
    archive that put ``iep.utm.edu/epistemo/`` at rank 27 of 100 for the query
    ``epistemology`` (and off a default-sized page entirely) behind seven
    sub-topic articles, while ``zim_query`` answered the same query on the
    same archive with that article at rank 1. The advanced tool a capable
    model prefers was the one without the relevance machinery, and nothing in
    the payload said so.

    Reuses the simple-tools implementation rather than copying it, so the two
    surfaces cannot drift. That method is already copy-on-write (an earlier
    cache-poisoning defect forced it) and reads nothing off ``self`` but
    ``zim_operations``, so it is safe to drive from here. It runs blocking
    libzim probes — archive open, SuggestionSearcher, redirect walks — so it
    is offloaded like every other data-layer touch.

    Gated to the first page: the splice is a promotion, and re-injecting the
    canonical at every ``offset`` would re-serve the same row forever.
    """
    if offset or not isinstance(payload, dict):
        return payload
    results = payload.get("results")
    if not results:
        return payload
    handler = getattr(server, "simple_tools_handler", None)
    if handler is None:  # pragma: no cover — registered in both tool modes
        return payload
    top_before = results[0].get("path") if isinstance(results[0], dict) else None
    try:
        spliced = await asyncio.to_thread(
            handler._splice_title_match_into_search,
            payload,
            resolved_path,
            query,
        )
    except Exception:  # pragma: no cover — defensive; never fail the search
        return payload
    if not isinstance(spliced, dict) or spliced.get("results") == results:
        return payload
    new_results = spliced.get("results") or []
    top_after = (
        new_results[0].get("path")
        if new_results and isinstance(new_results[0], dict)
        else None
    )
    _restamp_spliced_meta(
        spliced,
        dict(payload.get("_meta") or {}),
        top_changed=top_after != top_before,
    )
    return spliced


def _restamp_spliced_meta(out: dict, raw_meta: dict, *, top_changed: bool) -> None:
    """Re-measure ``out`` after the splice rewrote ``results``.

    The inherited envelope measured the pre-splice payload, so its ``chars``
    / ``tokens_est`` described bytes that never went on the wire — the same
    defect ``_refresh_promotion_meta`` fixes on the title path.

    ``low_relevance`` is dropped when the splice changed rank 1, on the same
    reasoning ``simple_tools`` applies: the verdict means "no hit
    token-matches the query", and an exact title-index match is a hit that
    does. Reporting it beside the answer would be its own lie.
    """
    from ..meta import attach_meta

    carried = {
        key: raw_meta[key]
        for key in _SPLICE_CARRIED_META_KEYS
        if raw_meta.get(key) is not None
    }
    reason = raw_meta.get("reason")
    suggestions = raw_meta.get("suggestions") or None
    if top_changed and reason == "low_relevance":
        reason = None
        suggestions = None
    attach_meta(
        out,
        reason=reason,
        suggestions=suggestions,
        # The response-size budget is a property of the rows the data layer
        # assembled; the splice adds one title-index row and cannot clear it.
        truncated=bool((out.get("page_info") or {}).get("budget_truncated")),
        **carried,
    )


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


def _annotate_cross_file_paging(payload: Any) -> Any:
    """Name the way out of an unfinished cross-archive page.

    v3.3.1 field report (fid 66): a fan-out block would announce
    ``done: false`` with 829 further hits and a ``next_cursor`` this tool
    had just blanked, while ``offset`` and ``cursor`` are both rejected for
    ``cross_file=True``. Every advertised continuation was refused and
    nothing said what to do instead. The route exists — re-run pinned to
    that archive, where ``offset`` does page — so say so, per archive that
    actually has more.
    """
    if not isinstance(payload, dict):
        return payload
    unfinished = [
        str(row.get("zim_file_path") or "")
        for row in (payload.get("results") or [])
        if isinstance(row, dict)
        and isinstance(row.get("result"), dict)
        and row["result"].get("done") is False
    ]
    unfinished = [p for p in unfinished if p]
    if not unfinished:
        return payload
    meta = dict(payload.get("_meta") or {})
    meta["hint"] = (
        "Cross-archive pages are not resumable: `offset` and `cursor` are "
        "rejected for `cross_file=True`. To page an archive that has more "
        "hits, re-run pinned to it — "
        + ", ".join(f"`zim_file_path={p}`" for p in unfinished[:3])
        + " — with `offset`."
    )
    out = dict(payload)
    out["_meta"] = meta
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
    effective_limit = limit if limit is not None else _TITLE_DEFAULT_LIMIT
    if _CRITERION_C_PATH == "fallback":
        return await ops.find_entry_by_title_data(
            zim_file_path or "",
            query,
            cross_file=cross_file,
            limit=effective_limit,
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
            limit=effective_limit,
        )
        # Same guard as the cross-file fulltext branch: a fan-out that
        # searched nothing is not a miss, and a hint about per-archive
        # promotion is noise on a server with nothing to promote.
        if isinstance(raw, dict) and raw.get("files_searched") == 0:
            return _no_archives_error()
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
        if _no_archives_loaded(server):
            return _no_archives_error()
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
        limit=effective_limit,
    )

    from ..topic_preprocessing import promote_topic_via_title_index

    # Promotion runs up to dozens of blocking libzim probes (archive open +
    # SuggestionSearcher + redirect walks per tail/window probe, and empty
    # probes are deliberately uncached). Offload like every other data-layer
    # touch so the probe train doesn't hold the event loop.
    promoted = await asyncio.to_thread(
        promote_topic_via_title_index,
        zim_operations=server.zim_operations,
        zim_file_path=resolved_path,
        topic=preprocessed,
    )
    merged = _merge_promotion_into_title_results(raw, promoted, effective_limit)
    # v3.3.1 field report (fid 71), at the RESPONSE EDGE and nowhere earlier.
    # Scraper output — translation hubs, image-caption stubs, subtitle
    # sidecars — outranks real articles on 39 of ~55 measured title pages
    # (``title 'hepatitis b'`` puts ``languages/hepatitisb.html`` above a real
    # ency article). Demoting it inside ``find_entry_by_title_data`` instead
    # would reorder the list the promotion probes above read as
    # score-descending, which blanks the canonical probe and hoists a weaker
    # fallback to rank 1 at a fabricated 1.0. Promotion has run by here, so
    # reordering is safe.
    return _demote_artefacts_in_response(merged)


def _demote_artefacts_in_response(payload: Any) -> Any:
    """Sink crawl artefacts in a title-mode response, leaving ``_meta`` sized.

    Reorders ``results`` only: no row is added or dropped, so ``total``,
    ``done`` and the page arithmetic are untouched and ``_meta`` stays
    accurate without a re-measure.
    """
    if not isinstance(payload, dict) or payload.get("error"):
        return payload
    rows = payload.get("results")
    if isinstance(rows, list):
        payload["results"] = demote_crawl_artefacts(rows)
    return payload


# ``_meta`` keys that describe the SOURCE rather than the rendered page, so
# they survive a promotion rewrite. Everything else in the envelope — chars,
# tokens_est, truncated — is a measurement of the payload and must be taken
# again once ``results`` has been replaced.
_PROMOTION_CARRIED_META_KEYS = (
    "detected_type",
    "detection_confidence",
    "preset_applied",
)


def _refresh_promotion_meta(
    out: dict, raw_meta: dict, *, carry_recovery_hints: bool
) -> None:
    """Re-measure ``out`` and restamp the envelope after a promotion rewrite.

    ``attach_meta`` recomputes ``chars`` / ``tokens_est`` from the payload as
    it now stands (sans ``_meta``), which is the whole point: the inherited
    envelope was measured before ``results`` was replaced, so it described
    bytes that never went on the wire. A caller sizing its context window
    from ``tokens_est`` was under-reserving by more than 2x on the empty-page
    branch, where a zero-row page with suggestions became a one-row hit.

    ``carry_recovery_hints`` is False for the empty-page branch, where pass 3
    established that a promoted canonical is a confident hit and must not
    carry the zero-result ``reason`` / ``suggestions`` alongside the answer.
    """
    from ..meta import attach_meta

    carried = {
        key: raw_meta[key]
        for key in _PROMOTION_CARRIED_META_KEYS
        if raw_meta.get(key) is not None
    }
    if carry_recovery_hints:
        for key in ("reason", "suggestions"):
            if raw_meta.get(key) is not None:
                carried[key] = raw_meta[key]
    attach_meta(out, **carried)
    out["_meta"]["promotion_applied"] = True


def _merge_promotion_into_title_results(
    raw: dict, promoted: Optional[dict], limit: int = _TITLE_DEFAULT_LIMIT
) -> dict:
    """Apply Z3/Z4/OPP-1 promotion as a post-filter on raw title-lookup
    results. The promoted entry is hoisted to the top of `results`; other
    matches keep their relative ranking. Promotion that returns None
    passes the raw response through unchanged.

    ``raw`` follows the legacy FindEntryResponse shape: list of
    candidate rows under ``results`` (NOT ``matches``) — see
    tool_schemas.FindEntryResponse.

    ``promote_topic_via_title_index`` returns the ``find_title_match``
    shape, which carries no ``score`` — the hoisted row is normalised to
    FindEntryHit before it goes on the wire, and the merged page is
    re-trimmed to ``limit`` with its counts recomputed so
    ``total == page_info.returned_count == len(results)`` still holds.
    """
    if promoted is None:
        return raw
    matches = raw.get("results", [])
    promoted_path = promoted.get("path") or promoted.get("entry_path")
    if not matches:
        # An empty raw page is the case promotion exists for: filler-prose
        # queries miss on the full phrase (reason="0_hits") while the
        # tail/window probes resolve the canonical. Serve the promoted row
        # as the page rather than discarding a resolved answer.
        promoted_row = dict(promoted)
        promoted_row.setdefault("score", 1.0)
        out = dict(raw)  # copy-on-write: raw may be the H15-cached object
        out["results"] = [promoted_row]
        if "total" in out:
            out["total"] = 1
        page_info = out.get("page_info")
        if isinstance(page_info, dict):
            out["page_info"] = {**page_info, "returned_count": 1}
        # The raw page's "0_hits" verdict is stale once promotion answered, and
        # so are its suggestions. ``_assemble_find_response`` fills
        # ``suggestions`` only for the no-results and fuzzy-hit cases, and its
        # stated contract is that a confident hit carries none "so confident
        # matches aren't muddled by alt-spelling noise". Promotion produces
        # exactly such a hit — a canonical title-index match — so leaving the
        # zero-result recovery hints attached would hand the model "did you
        # mean X?" alongside the answer it asked for.
        #
        # The size fields are stale too, and for the same reason: they measured
        # an empty page. Re-measure rather than inherit.
        _refresh_promotion_meta(
            out, dict(raw.get("_meta", {}) or {}), carry_recovery_hints=False
        )
        return out
    top = matches[0]
    top_path = top.get("entry_path") or top.get("path")
    if top_path == promoted_path:
        return raw
    hoisted = [
        m for m in matches if (m.get("entry_path") or m.get("path")) != promoted_path
    ]
    promoted_row = dict(promoted)
    # Score 1.0 keeps the emitted rank consistent with the ranking signal:
    # promotion only accepts canonical title-index hits, and a hoisted row
    # scored below the rows it displaced would be re-sorted back down by any
    # caller ordering on ``score``.
    promoted_row.setdefault("score", 1.0)
    results = [promoted_row, *hoisted][:limit]
    # COPY-ON-WRITE: ``raw`` is the cached ``find_title:v1`` object (H15 caches
    # single-archive title lookups, returned by reference) and is shared with
    # the internal promotion probes that read the same key. Mutating it in place
    # would poison that cache (the H12 defect class), so build a new dict.
    out = dict(raw)
    out["results"] = results
    if "total" in out:
        out["total"] = len(results)
    page_info = out.get("page_info")
    if isinstance(page_info, dict):
        out["page_info"] = {**page_info, "returned_count": len(results)}
    # ``results`` was just rewritten (hoist + re-trim), so the inherited
    # ``chars`` / ``tokens_est`` no longer describe what ships. Recovery hints
    # are carried here — unlike the empty-page branch above, this page had real
    # matches, so any ``suggestions`` came from the fuzzy-hit case and still
    # describe the query rather than a zero-result recovery.
    _refresh_promotion_meta(
        out, dict(raw.get("_meta", {}) or {}), carry_recovery_hints=True
    )
    return out
