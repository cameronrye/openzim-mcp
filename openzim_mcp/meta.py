"""Response metadata helpers — `_meta` envelope, footer, token estimation.

Phase A item #5 (token & char metadata). The `_meta` envelope ships on
every dict-returning tool; the footer renders a one-line markdown
summary on prose-returning tools in compact mode. Token estimates use
tiktoken's cl100k_base encoding as a model-agnostic budget signal —
not exact for any specific model, but close enough for context
budgeting across Anthropic, OpenAI, and Llama tokenizers.
"""

from __future__ import annotations

import functools
import json as _json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _get_encoder() -> Any:
    """Lazy tokenizer accessor.

    H21: ``lru_cache(maxsize=1)`` replaces the previous ``_EncoderCache``
    class with its unguarded check-then-set on shared mutable state.
    ``lru_cache`` is implemented in C, holds its own lock around cache
    population, and returns the same instance on every call — so two
    concurrent ``asyncio.to_thread`` workers calling this on first-use
    no longer race to write the encoder.

    Returns the tiktoken encoder, or ``None`` if init failed (sandboxed
    envs without a writable BPE cache). Callers that need to distinguish
    "tokenizer unavailable" from "zero tokens" inspect the return value
    directly via ``_raw_tokens_est``.
    """
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception as e:  # pragma: no cover — defensive; sandboxed envs
        logger.warning(
            "tiktoken init failed; tokens_est will be omitted from _meta "
            "envelopes for this session: %s",
            e,
        )
        return None


def _raw_tokens_est(rendered: str) -> Optional[int]:
    """Tokenize ``rendered``. Returns ``None`` when the tokenizer is
    unavailable so callers can distinguish "couldn't estimate" from
    "zero tokens" — spec §5 requires omitting ``tokens_est`` on
    tiktoken init failure rather than emitting a misleading 0.
    """
    if not rendered:
        return 0
    encoder = _get_encoder()
    if encoder is None:
        return None
    return len(encoder.encode(rendered))


def tokens_est(rendered: str) -> int:
    """Estimate the token count of a rendered string using cl100k_base.

    Returns 0 on empty input and 0 when the tokenizer is unavailable —
    the public helper preserves the legacy int return; envelope builders
    that need the "unavailable" signal call :func:`_raw_tokens_est`.
    """
    raw = _raw_tokens_est(rendered)
    return raw if raw is not None else 0


def build_meta(
    *,
    rendered: str,
    total_chars: Optional[int] = None,
    current_offset: int = 0,
    content_chars: Optional[int] = None,
    truncated: bool = False,
    suggestions: Optional[List[Dict[str, str]]] = None,
    reason: Optional[str] = None,
    detected_type: Optional[str] = None,
    detection_confidence: Optional[str] = None,
    preset_applied: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a `_meta` envelope for a tool response.

    Always emits `tokens_est` (with a 5% pad to cover envelope cost),
    `chars`, `truncated`. Conditionally emits `more_at_offset`,
    `total_chars`, `suggestions`, `reason`,
    `detected_type`, `detection_confidence`, `preset_applied`.

    ``content_chars`` is the byte length of the *paginable content slice*
    in the response (e.g. ``len(payload["content"])`` for get_zim_entry).
    When set together with ``truncated``, drives ``more_at_offset =
    current_offset + content_chars`` — i.e. the offset a caller would
    use to fetch the next page. When omitted, ``more_at_offset`` is not
    emitted: tools whose ``truncated`` means "value omitted, no
    continuation" (binary cap, section-content cap, summary word cap)
    must leave it ``None``.
    """
    chars = len(rendered)
    raw_tokens = _raw_tokens_est(rendered)

    meta: Dict[str, Any] = {
        "chars": chars,
        "truncated": truncated,
    }
    # Spec §5: omit ``tokens_est`` when the tokenizer is unavailable so
    # models can distinguish "zero-token response" from "tokenizer
    # unavailable". A non-None raw count (including 0 for empty input)
    # populates the field; ``None`` skips it. The previous version's
    # ``... if raw_tokens else 0`` collapsed the rare "non-empty payload
    # that BPE tokenizes to 0 tokens" case into a misleading ``0`` — drop
    # that special-case so the +5% pad + minimum 1 applies uniformly.
    if raw_tokens is not None:
        if raw_tokens == 0 and not rendered:
            meta["tokens_est"] = 0
        else:
            meta["tokens_est"] = int(raw_tokens * 1.05) + 1
    if truncated:
        if content_chars is not None:
            meta["more_at_offset"] = current_offset + content_chars
        if total_chars is not None:
            meta["total_chars"] = total_chars
    if suggestions:
        meta["suggestions"] = suggestions
    if reason is not None:
        meta["reason"] = reason
    if detected_type is not None:
        meta["detected_type"] = detected_type
    if detection_confidence is not None:
        meta["detection_confidence"] = detection_confidence
    if preset_applied is not None:
        meta["preset_applied"] = preset_applied
    return meta


def _humanize_count(n: int) -> str:
    """Format an integer as ~XK with one decimal for K-scale, integer otherwise."""
    if n < 1000:
        return str(n)
    k = n / 1000
    if k < 10:
        return f"{k:.1f}K"
    return f"{int(k)}K"


def format_footer(meta: Dict[str, Any], *, footer_enabled: bool) -> str:
    """Render a one-line markdown blockquote footer from a `_meta` envelope."""
    if not footer_enabled or not meta:
        return ""

    reason = meta.get("reason")
    # Any structured reason on an empty/low-confidence response shapes the
    # footer as a recovery hint instead of the token-budget summary.
    # Without this, archives lacking a full-text index (``no_xapian_index``)
    # or invalid-namespace responses (``bad_namespace``) fall through to a
    # "~0 tokens" line that gives small models no actionable signal.
    #
    # Op4: expanded reason taxonomy.
    # - ``low_relevance`` (H9): Xapian found hits but none token-match the
    #   query — same recovery prose as 0_hits.
    # - ``sample_only`` (C2): the page came from a sampled discovery and
    #   more entries remain even though ``done=True``. Tells the model
    #   to pivot to ``walk_namespace`` for exhaustive iteration.
    # - ``archive_unavailable`` (H10): every per-file archive failed in a
    #   fan-out (search_all) — the issue is infrastructural, not the query.
    # - ``search_all_budget_exceeded`` (H22): the aggregate timeout fired
    #   before all archives were searched; partial results returned.
    if reason in {
        "0_hits",
        "low_relevance",
        "bad_query",
        "no_xapian_index",
        "bad_namespace",
        "sample_only",
        "archive_unavailable",
        "search_all_budget_exceeded",
    }:
        suggestions = meta.get("suggestions") or []
        visible = suggestions[:3]
        if not visible:
            if reason == "no_xapian_index":
                return (
                    "> No full-text index on this archive. "
                    "Try `find_entry_by_title` or `browse_namespace`."
                )
            if reason == "bad_namespace":
                return (
                    "> Unknown namespace. Try `list_namespaces` to see valid options."
                )
            if reason == "sample_only":
                return (
                    "> Sampled view only — more entries remain. "
                    "Use `walk_namespace` for exhaustive iteration."
                )
            if reason == "archive_unavailable":
                return (
                    "> All archives failed to respond. Check `list_zim_files` "
                    "and server logs."
                )
            if reason == "search_all_budget_exceeded":
                return (
                    "> Search-all aggregate timeout fired before every archive "
                    "was probed. Narrow the query or raise "
                    "`OPENZIM_MCP_SEARCH__SEARCH_ALL_TOTAL_TIMEOUT_SECONDS`."
                )
            return "> No results. Try a shorter or differently-spelled query."
        bits: List[str] = []
        for item in visible:
            t = item.get("type")
            v = item.get("value", "")
            if t == "alt_spelling":
                bits.append(f"`suggestions for {v}`")
            elif t == "alt_archive":
                bits.append(f"or try ZIM `{v}`")
            elif t == "broader":
                bits.append(f"`search {v}` (broader)")
            elif t == "narrower":
                bits.append(f"`search {v}` (narrower)")
            elif t == "cross_intent_tell_me_about":
                # Post-v2.0.5 D-L: structured-topic-lookup escape
                # hatch injected by the simple-mode search handler
                # so compact-mode callers see the same
                # ``tell me about X`` cross-intent nudge that the
                # non-compact ``_format_search_text`` body emits
                # (``zim/search.py:779``). Distinct type so the
                # handler can append it without colliding with
                # backend-derived suggestion types.
                bits.append(f"`tell me about {v}`")
            else:
                bits.append(f"`{v}`")
        return "> No results. Try: " + " · ".join(bits)

    # ``tokens_est`` may be absent when the tokenizer is unavailable (spec
    # §5); fall back to char-count so the footer still gives the model a
    # budget signal instead of crashing on KeyError.
    parts: List[str] = []
    if "tokens_est" in meta:
        parts.append(f"~{_humanize_count(meta['tokens_est'])} tokens")
    else:
        parts.append(f"~{_humanize_count(meta.get('chars', 0))} chars")
    if meta.get("truncated"):
        chars_label = _humanize_count(meta["chars"])
        total_label = _humanize_count(meta.get("total_chars", meta["chars"]))
        parts.append(f"{chars_label} of {total_label} chars")
        # Op5 (v2.0.0a9): make the byte-offset semantics explicit.
        # ``more_at_offset`` is the byte offset to feed back as
        # ``content_offset`` on tools that paginate article bodies
        # (today: ``get_zim_entry``). Label it ``content_offset`` so
        # callers don't confuse it with the result-set ``offset`` used
        # by search/browse/walk.
        if "more_at_offset" in meta:
            parts.append(f"pass `content_offset={meta['more_at_offset']}` for more")
    return "> " + " · ".join(parts)


def attach_meta(
    payload: Dict[str, Any],
    *,
    truncated: bool = False,
    total_chars: Optional[int] = None,
    current_offset: int = 0,
    content_chars: Optional[int] = None,
    suggestions: Optional[List[Dict[str, str]]] = None,
    reason: Optional[str] = None,
    rendered: Optional[str] = None,
    detected_type: Optional[str] = None,
    detection_confidence: Optional[str] = None,
    preset_applied: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach a `_meta` envelope built from the JSON-rendered payload (sans _meta).

    Mutates and returns `payload`. Forwards build_meta kwargs.

    H23: ``rendered`` is an optional caller-supplied serialization of the
    payload. When omitted, we serialize via ``json.dumps`` here. Callers
    that already have a rendered form (e.g. a prose body about to ship as
    TextContent) can pass it through to avoid an extra full-payload JSON
    serialization on the hot path. For a typical Wikipedia search
    response (~50 KB payload, top-of-funnel) this was the single largest
    hot-path allocation outside libzim itself.

    Note: ``_meta.chars`` reflects the size of ``rendered`` (caller-supplied
    or default JSON-of-payload). Pagination is driven by ``content_chars``
    — pass the length of the paginable field (e.g. ``len(payload["content"])``)
    so ``more_at_offset`` is computed from content bytes, not envelope bytes.
    """
    if rendered is None:
        rendered = _json.dumps(
            {k: v for k, v in payload.items() if k != "_meta"},
            ensure_ascii=False,
        )
    payload["_meta"] = build_meta(
        rendered=rendered,
        truncated=truncated,
        total_chars=total_chars,
        current_offset=current_offset,
        content_chars=content_chars,
        suggestions=suggestions,
        reason=reason,
        detected_type=detected_type,
        detection_confidence=detection_confidence,
        preset_applied=preset_applied,
    )
    return payload
