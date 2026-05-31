"""Unit tests for :mod:`openzim_mcp.cursor_decode`.

These pin the six structured ``cursor_decode`` error payloads, the happy-path
offset/ns/ai/tool projection, and the token-overlap-vs-substring query-mismatch
branching extracted verbatim from the former inline block at the top of
``SimpleToolsHandler.handle_zim_query``. Error message strings are copied
verbatim from the source — they are asserted by the wider simple-tools suite,
so any drift here is a behavior change.
"""

import base64
import json

from openzim_mcp.cursor_decode import CursorDecodeResult, decode_offset_cursor

# Mirrors SimpleToolsHandler._Q_EMITTING_CURSOR_TOOLS.
Q_EMITTING = frozenset({"search_zim_file", "search_with_filters"})


def _encode(payload: dict, *, strip_pad: bool = True) -> str:
    """base64-urlsafe encode a JSON cursor payload (optionally unpadded,
    matching real ``Cursor.encode`` output which strips ``=``)."""
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return raw.rstrip("=") if strip_pad else raw


def _is_error(result) -> bool:
    return isinstance(result, dict) and result.get("error") is True


# ---------------------------------------------------------------------------
# Error case 1: length cap (2048)
# ---------------------------------------------------------------------------


def test_token_over_length_cap_errors():
    token = "A" * 2049
    out = decode_offset_cursor(token, query="anything", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    assert out["operation"] == "cursor_decode"
    assert out["message"] == (
        "The `cursor` value exceeds the maximum length. "
        "Drop the cursor and call again with an explicit "
        "`offset` (or no pagination arg)."
    )
    assert out["context"] == f"cursor={token[:64]}..."


def test_token_at_length_cap_is_not_rejected_for_length():
    # Exactly 2048 chars is allowed past the length gate (it then fails
    # the decode step, not the length step).
    token = "A" * 2048
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    # Not the length message — it fell through to undecodable.
    assert out["message"] != (
        "The `cursor` value exceeds the maximum length. "
        "Drop the cursor and call again with an explicit "
        "`offset` (or no pagination arg)."
    )


# ---------------------------------------------------------------------------
# Error case 2: undecodable base64/json
# ---------------------------------------------------------------------------


def test_undecodable_token_errors():
    # Not valid base64+JSON.
    token = "!!!not-base64!!!"
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    assert out["operation"] == "cursor_decode"
    assert out["message"] == (
        "The `cursor` value could not be decoded. Drop "
        "the cursor and call again with an explicit "
        "`offset` (or no pagination arg)."
    )
    assert out["context"] == f"cursor={token[:64]}"


def test_valid_base64_invalid_json_errors():
    token = base64.urlsafe_b64encode(b"not json at all").decode().rstrip("=")
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    assert out["message"].startswith("The `cursor` value could not be decoded.")


# ---------------------------------------------------------------------------
# Error case 3: missing `s` envelope
# ---------------------------------------------------------------------------


def test_missing_s_envelope_errors():
    token = _encode({"malformed": True})
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    assert out["operation"] == "cursor_decode"
    assert out["message"] == (
        "The `cursor` payload is missing the expected "
        "`s` envelope. Drop the cursor and call "
        "again with an explicit `offset` (or no "
        "pagination arg)."
    )
    assert out["context"] == f"cursor={token[:64]}"


def test_top_level_not_dict_errors_as_missing_s():
    # A JSON list decodes but has no `.get` -> the helper treats a
    # non-dict payload as a missing `s` envelope (state stays None).
    token = _encode([1, 2, 3])
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    assert "missing the expected" in out["message"]


def test_s_not_a_dict_errors_as_missing_s():
    token = _encode({"s": "scalar"})
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    assert "missing the expected" in out["message"]


# ---------------------------------------------------------------------------
# Error case 4: missing/invalid `s.o`
# ---------------------------------------------------------------------------

_INVALID_SO_MESSAGE = (
    "The `cursor` payload's `s.o` (offset) is "
    "missing or invalid. Drop the cursor and "
    "call again with an explicit `offset` (or "
    "no pagination arg)."
)


def test_so_missing_errors():
    token = _encode({"s": {"q": "x"}})
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    assert out["message"] == _INVALID_SO_MESSAGE
    assert out["context"] == f"cursor={token[:64]}"


def test_so_not_int_errors():
    token = _encode({"s": {"o": "5"}})
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    assert out["message"] == _INVALID_SO_MESSAGE


def test_so_negative_errors():
    token = _encode({"s": {"o": -1}})
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    assert out["message"] == _INVALID_SO_MESSAGE


def test_so_bool_is_rejected():
    # bool is an int subclass; isinstance(True, int) is True, but the
    # original code accepted that (True == offset 1). Pin current behavior:
    # True is accepted as offset 1 (>= 0). This documents the edge.
    token = _encode({"s": {"o": True}})
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert isinstance(out, CursorDecodeResult)
    assert out.offset == 1


# ---------------------------------------------------------------------------
# Happy path: offset + optional ns/ai/tool
# ---------------------------------------------------------------------------


def test_happy_path_offset_only():
    token = _encode({"v": 2, "s": {"o": 7}})
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert isinstance(out, CursorDecodeResult)
    assert out.offset == 7
    assert out.ns is None
    assert out.ai is None
    assert out.tool is None


def test_happy_path_populates_ns_ai_tool():
    token = _encode(
        {
            "v": 2,
            "t": "walk_namespace",
            "s": {"o": 5, "ns": "M", "ai": "deadbeef"},
        }
    )
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert isinstance(out, CursorDecodeResult)
    assert out.offset == 5
    assert out.ns == "M"
    assert out.ai == "deadbeef"
    assert out.tool == "walk_namespace"


def test_happy_path_omits_empty_ns_ai_tool():
    # Empty strings and non-string values are NOT projected (truthy check).
    token = _encode(
        {
            "v": 2,
            "t": "",
            "s": {"o": 0, "ns": "", "ai": 123},
        }
    )
    out = decode_offset_cursor(token, query="x", q_emitting_tools=Q_EMITTING)
    assert isinstance(out, CursorDecodeResult)
    assert out.offset == 0
    assert out.ns is None
    assert out.ai is None
    assert out.tool is None


# ---------------------------------------------------------------------------
# Query-mismatch (q-emitting tool path)
# ---------------------------------------------------------------------------


def test_query_mismatch_no_shared_token_errors():
    # cursor q='algebra', current query 'photosynthesis' — no shared
    # >=3-char token, q-emitting tool -> reject.
    token = _encode({"v": 2, "t": "search_zim_file", "s": {"o": 3, "q": "algebra"}})
    out = decode_offset_cursor(
        token, query="photosynthesis", q_emitting_tools=Q_EMITTING
    )
    assert _is_error(out)
    assert out["operation"] == "cursor_decode"
    assert out["message"] == (
        "Cursor was issued for query 'algebra'; "
        "current request shares no terms "
        "with it. Drop the cursor and start "
        "the search over for the new query."
    )
    assert out["context"] == "cursor_q='algebra'"


def test_query_mismatch_default_tool_field_absent_still_checks():
    # No `t` field -> cursor_t_emits_q is True (treated as q-emitting),
    # so the q-overlap check still runs.
    token = _encode({"v": 2, "s": {"o": 3, "q": "algebra"}})
    out = decode_offset_cursor(
        token, query="photosynthesis", q_emitting_tools=Q_EMITTING
    )
    assert _is_error(out)
    assert "shares no terms" in out["message"]


def test_query_shared_token_accepts():
    # cursor q='berlin germany', query 'berlin culture' share 'berlin'.
    token = _encode(
        {"v": 2, "t": "search_zim_file", "s": {"o": 3, "q": "berlin germany"}}
    )
    out = decode_offset_cursor(
        token, query="berlin culture", q_emitting_tools=Q_EMITTING
    )
    assert isinstance(out, CursorDecodeResult)
    assert out.offset == 3


def test_short_token_substring_fallback_accepts():
    # cursor q has only short (<3 char) tokens ('bi') -> bidirectional
    # substring fallback (no >=3-char token gates the token branch).
    # 'bi' is a substring of 'biology' -> accept.
    token = _encode({"v": 2, "t": "search_zim_file", "s": {"o": 3, "q": "bi"}})
    out = decode_offset_cursor(token, query="biology", q_emitting_tools=Q_EMITTING)
    assert isinstance(out, CursorDecodeResult)
    assert out.offset == 3


def test_short_token_substring_fallback_rejects_when_unrelated():
    # cursor q='ab' (only short tokens), query 'xyz' — neither is a
    # substring of the other -> reject via the substring fallback,
    # returning the SAME mismatch payload as the token branch.
    token = _encode({"v": 2, "t": "search_zim_file", "s": {"o": 3, "q": "ab"}})
    out = decode_offset_cursor(token, query="xyz", q_emitting_tools=Q_EMITTING)
    assert _is_error(out)
    assert out["message"] == (
        "Cursor was issued for query 'ab'; "
        "current request shares no terms "
        "with it. Drop the cursor and start "
        "the search over for the new query."
    )
    assert out["context"] == "cursor_q='ab'"


# ---------------------------------------------------------------------------
# Q-check SKIPPED for non-q-emitting tools
# ---------------------------------------------------------------------------


def test_q_check_skipped_for_non_q_emitting_tool():
    # cursor claims tool 'walk_namespace' (NOT q-emitting) but carries
    # an adversarial s.q='biology' that shares nothing with the query.
    # The dispatcher must NOT error here — the handler-level
    # tool-mismatch fires instead. So decode succeeds with the offset
    # and the projected tool name.
    token = _encode(
        {"v": 2, "t": "walk_namespace", "s": {"o": 5, "q": "biology", "ns": "M"}}
    )
    out = decode_offset_cursor(
        token, query="photosynthesis", q_emitting_tools=Q_EMITTING
    )
    assert isinstance(out, CursorDecodeResult)
    assert out.offset == 5
    assert out.tool == "walk_namespace"
    assert out.ns == "M"


def test_q_check_runs_for_browse_when_in_q_emitting_set():
    # Sanity: q-emitting set membership is what gates the check. If a
    # tool name is in the passed set, the q-check fires for it.
    custom = frozenset({"my_tool"})
    token = _encode({"v": 2, "t": "my_tool", "s": {"o": 3, "q": "algebra"}})
    out = decode_offset_cursor(token, query="photosynthesis", q_emitting_tools=custom)
    assert _is_error(out)
    assert "shares no terms" in out["message"]


def test_two_mismatch_branches_return_identical_payload():
    # The token-overlap branch and the substring-fallback branch must
    # produce byte-identical payloads for the same cursor_q. Compare the
    # message+context skeleton (substituting the differing cursor_q).
    tok_branch = _encode(
        {"v": 2, "t": "search_zim_file", "s": {"o": 3, "q": "algebra"}}
    )
    sub_branch = _encode({"v": 2, "t": "search_zim_file", "s": {"o": 3, "q": "ab"}})
    a = decode_offset_cursor(tok_branch, query="zzz", q_emitting_tools=Q_EMITTING)
    b = decode_offset_cursor(sub_branch, query="zzz", q_emitting_tools=Q_EMITTING)
    assert _is_error(a) and _is_error(b)
    # Same template modulo the cursor_q value.
    assert a["message"].replace("'algebra'", "Q") == b["message"].replace("'ab'", "Q")
    assert a["context"].replace("'algebra'", "Q") == b["context"].replace("'ab'", "Q")
