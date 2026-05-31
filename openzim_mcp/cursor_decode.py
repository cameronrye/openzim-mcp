"""Simple-mode pagination cursor decoding for offset extraction.

This module hosts :func:`decode_offset_cursor`, extracted verbatim from the
former inline block at the top of
:meth:`openzim_mcp.simple_tools.SimpleToolsHandler.handle_zim_query`. The
simple-mode router dispatches by parsed intent, not by the tool that emitted
the cursor, so it deliberately bypasses
:meth:`openzim_mcp.pagination.Cursor.decode`'s ``expected_tool`` check and
reads ``s.o`` (offset) directly from any tool's cursor.

Behavior is byte-identical to the inline original: the five distinct structured
``cursor_decode`` error payloads (the query-mismatch payload is shared by two
branches), the offset/ns/ai/tool projections, and the
token-overlap-vs-substring query-mismatch branching (gated on the
``_Q_EMITTING_CURSOR_TOOLS`` set) are preserved exactly. The broad
``except Exception`` that emitted the "undecodable" error AND a
``logger.warning("Could not decode cursor ...")`` is preserved here so the
caller's logging behavior is unchanged.
"""

import base64
import json
import logging
from dataclasses import dataclass
from typing import AbstractSet, Optional, Union

from .responses import ToolErrorPayload, tool_error
from .text_utils import tokenize_for_relevance

logger = logging.getLogger(__name__)


@dataclass
class CursorDecodeResult:
    """Successful decode: the offset to project into ``options['offset']``
    plus the optional ``ns`` / ``ai`` / ``tool`` fields the dispatcher
    stashes into ``options['_cursor_ns']`` / ``['_cursor_ai']`` /
    ``['_cursor_t']`` when truthy.
    """

    offset: int
    ns: Optional[str] = None
    ai: Optional[str] = None
    tool: Optional[str] = None


def decode_offset_cursor(
    token: str,
    *,
    query: str,
    q_emitting_tools: AbstractSet[str],
) -> Union[CursorDecodeResult, ToolErrorPayload]:
    """Decode a simple-mode pagination cursor for offset extraction.

    Returns either a CursorDecodeResult (offset + optional ns/ai/tool to
    project into options) OR a ToolErrorPayload (one of the five distinct
    structured cursor_decode errors). Behavior is identical to the former
    inline block
    in handle_zim_query; q_emitting_tools is the handler's
    _Q_EMITTING_CURSOR_TOOLS set.
    """
    # Defense-in-depth: cap the token length at 2 KB so an
    # adversarially-crafted cursor can't trigger oversized
    # base64-decode or json.loads work. Legitimate cursors
    # issued by ``Cursor.encode`` are well under 200 chars.
    if len(token) > 2048:
        # H24: errors travel as ToolErrorPayload so callers can
        # programmatically branch on ``result.error``. The legacy
        # markdown string forced clients to substring-match the
        # heading, breaking the same shape the advanced tools use.
        return tool_error(
            operation="cursor_decode",
            message=(
                "The `cursor` value exceeds the maximum length. "
                "Drop the cursor and call again with an explicit "
                "`offset` (or no pagination arg)."
            ),
            context=f"cursor={token[:64]}...",
        )
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded_payload = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        )
        # A11 E3 (post-a10): a base64+JSON token that decodes
        # but lacks the expected ``s`` envelope (or whose ``s``
        # has no ``o`` offset) used to be silently treated as
        # "no cursor" — the caller thought they were paginating
        # and got page 1 instead with no signal anything was
        # wrong. Surface a structured ``cursor_decode`` error
        # for these too so the contract matches the totally-
        # garbled-token case below.
        state = decoded_payload.get("s") if isinstance(decoded_payload, dict) else None
        if not isinstance(state, dict):
            return tool_error(
                operation="cursor_decode",
                message=(
                    "The `cursor` payload is missing the expected "
                    "`s` envelope. Drop the cursor and call "
                    "again with an explicit `offset` (or no "
                    "pagination arg)."
                ),
                context=f"cursor={token[:64]}",
            )
        decoded_offset = state.get("o")
        if not isinstance(decoded_offset, int) or decoded_offset < 0:
            return tool_error(
                operation="cursor_decode",
                message=(
                    "The `cursor` payload's `s.o` (offset) is "
                    "missing or invalid. Drop the cursor and "
                    "call again with an explicit `offset` (or "
                    "no pagination arg)."
                ),
                context=f"cursor={token[:64]}",
            )
        result = CursorDecodeResult(offset=decoded_offset)
        # P3-D7 (live-MCP sweep): stash the cursor's ``s.ns``
        # so namespace-bound handlers (``_handle_browse`` /
        # ``_handle_walk_namespace``) can reject mismatches.
        # Live MCP saw a cursor for ``ns="C"`` accepted by a
        # ``browse namespace M`` call — the tool silently
        # rebound to M while applying the cursor's offset.
        # Same defence-in-depth shape as the existing ``ai`` /
        # ``q`` mismatch checks: cursors must match the
        # context they were issued for.
        cursor_ns = state.get("ns")
        if isinstance(cursor_ns, str) and cursor_ns:
            result.ns = cursor_ns
        # Post-a17 P1-D3: stash the cursor's ``s.ai`` so
        # cursor-rebuilding handlers (``_handle_walk_namespace``
        # rebuilds ``{scan_at, l}`` from ``offset`` and passes
        # that synthetic dict to ``walk_namespace_data``, whose
        # unconditional ``verify_archive_identity`` then
        # rejects the missing ``ai`` with a misleading
        # "missing archive-identity field" error). Preserving
        # the original ``ai`` round-trips it back through the
        # check so a walk-namespace cursor returned by the
        # tool can be replayed against the same archive.
        cursor_ai = state.get("ai")
        if isinstance(cursor_ai, str) and cursor_ai:
            result.ai = cursor_ai
        # Post-a18 P1-D4: stash the cursor's tool name so the
        # simple-tools dispatcher can reject cross-tool reuse
        # (e.g. a ``walk_namespace`` cursor passed to
        # ``browse namespace M`` silently walked browse from
        # walk's offset). The advanced tools already enforce
        # tool-binding via ``Cursor.decode(expected_tool=...)``;
        # the simple-tools layer decoded the cursor in-place
        # earlier in this block, bypassing that check. The
        # ``_cursor_tool_mismatch`` helper fires in each
        # cursor-consuming handler (``_handle_browse`` /
        # ``_handle_walk_namespace``) so the user sees a clear
        # rejection instead of a silent wrong-result.
        cursor_t = decoded_payload.get("t")
        if isinstance(cursor_t, str) and cursor_t:
            result.tool = cursor_t
        # D9 (beta): the original implementation treated the
        # cursor's ``s.q`` field as decorative — only ``s.o``
        # was read. That meant a caller who reused a cursor
        # issued for ``query="algebra"`` with a fresh request
        # for ``query="photosynthesis"`` silently got page 2
        # of "photosynthesis" results (offset applied to the
        # NEW query). Pagination state coupled to the wrong
        # query is the same class of bug the advanced tools
        # explicitly reject via ``CursorMismatchError`` /
        # ``OpenZimMcpValidationError``.
        #
        # D9 (beta, second pass): the first revision used a
        # one-directional substring check
        # (``cursor_q.lower() in query.lower()``). That
        # false-rejected legitimate pagination when the
        # model shortened the query on the retry —
        # cursor issued for ``"berlin culture"`` then
        # resubmitted with ``"berlin"`` errored out
        # even though both name the same topic. Use a
        # token-set overlap test instead: as long as
        # cursor and current query share at least one
        # meaningful (≥3-char) token, accept the cursor.
        # This catches the ``"algebra"`` → ``"photosynthesis"``
        # swap while tolerating same-topic phrase reshaping
        # in either direction. Cursors whose stored query
        # has no ≥3-char tokens fall back to a bidirectional
        # substring check.
        cursor_q = state.get("q")
        # Post-a20 P1-D1: only ``search_zim_file`` /
        # ``search_with_filters`` legitimately emit ``s.q``
        # in their cursors (see ``Cursor.encode`` callsites
        # in zim/search.py). When ``_cursor_t`` claims a
        # non-q-emitting tool (``walk_namespace`` /
        # ``browse_namespace`` / ``extract_article_links``)
        # but the payload still carries ``s.q``, the field
        # is adversarial or vestigial — skipping the
        # dispatcher q-overlap check here lets the
        # handler-level ``_cursor_tool_mismatch`` fire
        # with the correct ``Cursor / Tool Mismatch``
        # diagnosis instead of the misleading
        # ``Cursor was issued for query X; current request
        # shares no terms`` shape (which advises starting
        # the search over — useless when the real fault
        # is cross-tool reuse).
        # ``cursor_t`` (read above) already holds ``decoded_payload["t"]``;
        # at this point ``decoded_payload`` is guaranteed a dict (a
        # non-dict would have set ``state = None`` and returned early),
        # so reuse it directly rather than re-reading behind a dead guard.
        cursor_t_emits_q = (
            not isinstance(cursor_t, str)
            or not cursor_t
            or cursor_t in q_emitting_tools
        )
        if isinstance(cursor_q, str) and cursor_q.strip() and cursor_t_emits_q:
            cursor_tokens = tokenize_for_relevance(cursor_q)
            query_tokens = tokenize_for_relevance(query or "")
            cursor_q_lower = cursor_q.lower()
            query_lower = (query or "").lower()
            # Three outcomes:
            #   1. Cursor has meaningful tokens AND they
            #      share at least one with the query → ok.
            #   2. Cursor has meaningful tokens AND no
            #      overlap → reject.
            #   3. Cursor has only short tokens (rare;
            #      e.g. ``"bio"``) → bidirectional
            #      substring check.
            # The two reject branches return a single, identical
            # payload (formerly duplicated verbatim inline).
            mismatch = _query_mismatch_error(cursor_q)
            if cursor_tokens:
                shares_token = bool(cursor_tokens & query_tokens)
                if not shares_token:
                    return mismatch
            else:
                mutually_unrelated = (
                    cursor_q_lower not in query_lower
                    and query_lower not in cursor_q_lower
                )
                if mutually_unrelated:
                    return mismatch
        return result
    except Exception as e:
        logger.warning("Could not decode cursor %r: %s", token, e)
        # H24: see above — keep simple-mode error shape consistent
        # with the advanced surface.
        return tool_error(
            operation="cursor_decode",
            message=(
                "The `cursor` value could not be decoded. Drop "
                "the cursor and call again with an explicit "
                "`offset` (or no pagination arg)."
            ),
            context=f"cursor={token[:64]}",
        )


def _query_mismatch_error(cursor_q: str) -> ToolErrorPayload:
    """The single source of truth for the (formerly duplicated) D9
    query-mismatch payload. Both the token-overlap and substring-fallback
    reject branches return this identical error.
    """
    return tool_error(
        operation="cursor_decode",
        message=(
            f"Cursor was issued for query {cursor_q!r}; "
            f"current request shares no terms "
            f"with it. Drop the cursor and start "
            f"the search over for the new query."
        ),
        context=f"cursor_q={cursor_q!r}",
    )
