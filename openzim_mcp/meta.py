"""Response metadata helpers — `_meta` envelope, footer, token estimation.

Phase A item #5 (token & char metadata). The `_meta` envelope ships on
every dict-returning tool; the footer renders a one-line markdown
summary on prose-returning tools in compact mode. Token estimates use
tiktoken's cl100k_base encoding as a model-agnostic budget signal —
not exact for any specific model, but close enough for context
budgeting across Anthropic, OpenAI, and Llama tokenizers.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Lazy-loaded tokenizer; module-level cache means the first request pays
# the initialisation cost; subsequent requests are millions of tokens/sec.
_encoder: Any = None
_encoder_init_failed = False


def _get_encoder() -> Any:
    global _encoder, _encoder_init_failed
    if _encoder is not None or _encoder_init_failed:
        return _encoder
    try:
        import tiktoken

        _encoder = tiktoken.get_encoding("cl100k_base")
    except Exception as e:  # pragma: no cover — defensive; sandboxed envs
        logger.warning(
            "tiktoken init failed; tokens_est will return 0 for this session: %s", e
        )
        _encoder_init_failed = True
    return _encoder


def tokens_est(rendered: str) -> int:
    """Estimate the token count of a rendered string using cl100k_base."""
    if not rendered:
        return 0
    encoder = _get_encoder()
    if encoder is None:
        return 0
    return len(encoder.encode(rendered))


def build_meta(
    *,
    rendered: str,
    total_chars: Optional[int] = None,
    current_offset: int = 0,
    truncated: bool = False,
    suggestions: Optional[List[Dict[str, str]]] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a `_meta` envelope for a tool response.

    Always emits `tokens_est` (with a 5% pad to cover envelope cost),
    `chars`, `truncated`. Conditionally emits `more_at_offset`,
    `total_chars`, `suggestions`, `reason`.
    """
    chars = len(rendered)
    raw_tokens = tokens_est(rendered)
    padded_tokens = int(raw_tokens * 1.05) + 1 if raw_tokens else 0

    meta: Dict[str, Any] = {
        "tokens_est": padded_tokens,
        "chars": chars,
        "truncated": truncated,
    }
    if truncated:
        meta["more_at_offset"] = current_offset + chars
        if total_chars is not None:
            meta["total_chars"] = total_chars
    if suggestions:
        meta["suggestions"] = suggestions
    if reason is not None:
        meta["reason"] = reason
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

    if meta.get("reason") in {"0_hits", "low_relevance", "bad_query"}:
        suggestions = meta.get("suggestions") or []
        visible = suggestions[:3]
        if not visible:
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
            else:
                bits.append(f"`{v}`")
        return "> No results. Try: " + " · ".join(bits)

    parts: List[str] = [f"~{_humanize_count(meta['tokens_est'])} tokens"]
    if meta.get("truncated"):
        chars_label = _humanize_count(meta["chars"])
        total_label = _humanize_count(meta.get("total_chars", meta["chars"]))
        parts.append(f"{chars_label} of {total_label} chars")
        if "more_at_offset" in meta:
            parts.append(f"pass `offset={meta['more_at_offset']}` for more")
    return "> " + " · ".join(parts)


def attach_meta(
    payload: Dict[str, Any],
    *,
    truncated: bool = False,
    total_chars: Optional[int] = None,
    current_offset: int = 0,
    suggestions: Optional[List[Dict[str, str]]] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach a `_meta` envelope built from the JSON-rendered payload (sans _meta).

    Mutates and returns `payload`. Forwards build_meta kwargs.
    """
    rendered = _json.dumps(
        {k: v for k, v in payload.items() if k != "_meta"},
        ensure_ascii=False,
    )
    payload["_meta"] = build_meta(
        rendered=rendered,
        truncated=truncated,
        total_chars=total_chars,
        current_offset=current_offset,
        suggestions=suggestions,
        reason=reason,
    )
    return payload
