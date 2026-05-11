"""Tests for the openzim_mcp.meta module."""

import pytest

from openzim_mcp.meta import attach_meta, build_meta, format_footer, tokens_est


def test_tokens_est_basic():
    # tiktoken cl100k_base encodes "hello world" as 2 tokens
    assert tokens_est("hello world") == pytest.approx(2, abs=1)


def test_tokens_est_empty():
    assert tokens_est("") == 0


def test_tokens_est_unicode():
    # Multi-byte characters tokenize predictably with cl100k_base
    n = tokens_est("こんにちは世界")
    assert n > 0
    assert n < 50


def test_tokens_est_long_string_scales_linearly():
    short = tokens_est("Hello, this is a sample sentence. " * 10)
    long = tokens_est("Hello, this is a sample sentence. " * 100)
    # Linear scaling within ±5%
    assert long == pytest.approx(short * 10, rel=0.05)


def test_build_meta_basic_dict():
    meta = build_meta(rendered='{"results": []}')
    assert meta["chars"] == len('{"results": []}')
    assert meta["tokens_est"] >= 1
    assert meta["truncated"] is False
    assert "more_at_offset" not in meta
    assert "suggestions" not in meta


def test_build_meta_truncated_with_content_chars_emits_more_at_offset():
    meta = build_meta(
        rendered="X" * 100,
        total_chars=10_000,
        current_offset=0,
        content_chars=100,
        truncated=True,
    )
    assert meta["truncated"] is True
    assert meta["more_at_offset"] == 100
    assert meta["total_chars"] == 10_000


def test_build_meta_truncated_without_content_chars_omits_more_at_offset():
    """Tools that truncate WITHOUT a follow-up offset (binary cap, section cap,
    summary word cap) must not surface ``more_at_offset`` — a caller can't
    page past where there is no continuation."""
    meta = build_meta(
        rendered="X" * 100,
        total_chars=10_000,
        truncated=True,
    )
    assert meta["truncated"] is True
    assert "more_at_offset" not in meta
    assert meta["total_chars"] == 10_000


def test_build_meta_more_at_offset_uses_content_not_envelope():
    """Regression: ``more_at_offset`` must reflect content byte offset,
    not the JSON envelope size. Earlier code mistakenly used
    ``len(rendered)`` (envelope) which inflated the offset by the wrapper
    field bytes (`path`, `title`, …) and broke follow-up pagination."""
    envelope = '{"path":"A/Foo","title":"Foo","content":"' + "X" * 100 + '"}'
    meta = build_meta(
        rendered=envelope,
        current_offset=200,
        content_chars=100,
        truncated=True,
    )
    # Caller asked for offset=200, returned 100 chars of content → next
    # call uses offset=300. The envelope is much longer than 100, but
    # that doesn't enter the calculation.
    assert meta["more_at_offset"] == 300


def test_build_meta_with_suggestions():
    meta = build_meta(
        rendered="No results found.",
        suggestions=[
            {"type": "alt_spelling", "value": "Photosynthesis"},
            {"type": "alt_archive", "value": "wikipedia_en_all"},
        ],
        reason="0_hits",
    )
    assert meta["suggestions"][0]["type"] == "alt_spelling"
    assert meta["reason"] == "0_hits"


def test_build_meta_omits_empty_suggestions():
    meta = build_meta(rendered="content", suggestions=[])
    assert "suggestions" not in meta


def test_build_meta_pads_token_count_for_envelope():
    rendered = "X" * 1000
    meta = build_meta(rendered=rendered)
    raw_tokens = tokens_est(rendered)
    assert meta["tokens_est"] >= raw_tokens


def test_footer_basic():
    meta = {"tokens_est": 4283, "chars": 17034, "truncated": False}
    footer = format_footer(meta, footer_enabled=True)
    assert footer.startswith("> ")
    assert "~4.3K tokens" in footer
    assert "more" not in footer
    assert "chars" not in footer


def test_footer_truncated():
    meta = {
        "tokens_est": 4283,
        "chars": 17034,
        "truncated": True,
        "more_at_offset": 17034,
        "total_chars": 87421,
    }
    footer = format_footer(meta, footer_enabled=True)
    assert "17K of 87K chars" in footer
    assert "offset=17034" in footer


def test_footer_empty_results():
    meta = {
        "tokens_est": 50,
        "chars": 200,
        "truncated": False,
        "reason": "0_hits",
        "suggestions": [
            {"type": "alt_spelling", "value": "Photosynthesis"},
            {"type": "alt_archive", "value": "wikipedia_en_all"},
        ],
    }
    footer = format_footer(meta, footer_enabled=True)
    assert footer.startswith("> No results.")
    assert "Photosynthesis" in footer
    assert "wikipedia_en_all" in footer


def test_footer_disabled():
    meta = {"tokens_est": 100, "chars": 400, "truncated": False}
    assert format_footer(meta, footer_enabled=False) == ""


def test_footer_caps_visible_suggestions_at_three():
    meta = {
        "tokens_est": 50,
        "chars": 200,
        "truncated": False,
        "reason": "0_hits",
        "suggestions": [{"type": "alt_spelling", "value": f"alt{i}"} for i in range(7)],
    }
    footer = format_footer(meta, footer_enabled=True)
    assert footer.count("·") <= 3


def test_attach_meta_adds_meta_key():
    payload = {"results": [{"path": "A/Foo"}], "total": 1}
    out = attach_meta(payload)
    assert "_meta" in out
    assert out["_meta"]["chars"] > 0
    assert out["_meta"]["tokens_est"] >= 1
    # Original keys preserved
    assert out["results"] == [{"path": "A/Foo"}]
    assert out["total"] == 1


def test_attach_meta_excludes_existing_meta_from_render():
    """If payload already has _meta, the rendered form for token estimation should exclude it."""
    payload = {"results": [], "_meta": {"old": "data"}}
    out = attach_meta(payload)
    # _meta is overwritten, not nested
    assert "old" not in out["_meta"]
