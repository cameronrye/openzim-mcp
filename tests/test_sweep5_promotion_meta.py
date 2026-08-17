"""Promotion must re-measure the payload it rewrote.

``_meta.chars`` / ``_meta.tokens_est`` are produced by ``meta.build_meta``
against the payload as it stood when ``attach_meta`` ran, inside
``find_entry_by_title_data``. ``_merge_promotion_into_title_results`` then
*replaces* ``results`` — the empty-page branch swaps ``[]`` for a full
promoted hit row — and carried the old envelope forward verbatim, popping
only ``reason`` and ``suggestions``. Nothing was recomputed, so the
advertised size described a payload that never went on the wire.

The gap is largest in exactly the branch this PR added: the measured payload
had zero result rows plus alt-spelling suggestions, while the emitted one
carries a hit row and no suggestions. A caller sizing its context window
from ``tokens_est`` under-reserved by more than 2x.

This is the consumer contract pass 4 already repaired elsewhere — a budget
field must describe the bytes actually emitted.
"""

from __future__ import annotations

import json

from openzim_mcp.meta import tokens_est
from openzim_mcp.tools.zim_search import _merge_promotion_into_title_results


def _fresh_size(payload: dict) -> tuple:
    """Measure ``payload`` the way ``attach_meta`` would (sans ``_meta``).

    Mirrors ``build_meta``'s 5% envelope pad so the comparison is against
    the real formula rather than the raw tokenizer count.
    """
    rendered = json.dumps(
        {k: v for k, v in payload.items() if k != "_meta"}, ensure_ascii=False
    )
    return len(rendered), int(tokens_est(rendered) * 1.05) + 1


class TestEmptyPageBranch:
    """The zero-hit page promotion turns into a one-row answer."""

    def _raw(self) -> dict:
        payload = {
            "results": [],
            "total": 0,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 0},
        }
        chars, toks = _fresh_size(payload)
        payload["_meta"] = {
            "chars": chars,
            "tokens_est": toks,
            "truncated": False,
            "reason": "0_hits",
            "suggestions": [{"text": "biofuels"}],
        }
        return payload

    def test_meta_measures_the_emitted_payload(self) -> None:
        promoted = {"path": "A/Biofuel", "title": "Biofuel"}
        out = _merge_promotion_into_title_results(self._raw(), promoted, limit=10)

        expected_chars, expected_tokens = _fresh_size(out)
        assert out["_meta"]["chars"] == expected_chars
        assert out["_meta"]["tokens_est"] == expected_tokens

    def test_promotion_flag_and_hint_removal_survive(self) -> None:
        promoted = {"path": "A/Biofuel", "title": "Biofuel"}
        out = _merge_promotion_into_title_results(self._raw(), promoted, limit=10)

        assert out["_meta"]["promotion_applied"] is True
        # Pass 3's fix must not regress: a confident hit carries no
        # zero-result recovery hints.
        assert "reason" not in out["_meta"]
        assert "suggestions" not in out["_meta"]


class TestPopulatedPageBranch:
    """Hoisting a promoted row over existing matches also rewrites results."""

    def _raw(self) -> dict:
        payload = {
            "results": [
                {"path": "A/Biomass", "title": "Biomass", "score": 0.4},
                {"path": "A/Biogas", "title": "Biogas", "score": 0.3},
            ],
            "total": 2,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 2},
        }
        chars, toks = _fresh_size(payload)
        payload["_meta"] = {"chars": chars, "tokens_est": toks, "truncated": False}
        return payload

    def test_meta_measures_the_emitted_payload(self) -> None:
        promoted = {"path": "A/Biofuel", "title": "Biofuel"}
        out = _merge_promotion_into_title_results(self._raw(), promoted, limit=10)

        expected_chars, expected_tokens = _fresh_size(out)
        assert out["_meta"]["chars"] == expected_chars
        assert out["_meta"]["tokens_est"] == expected_tokens
        assert out["_meta"]["promotion_applied"] is True


def test_content_annotations_are_carried_through() -> None:
    """Archive-type annotations describe the source, not the page size."""
    payload = {
        "results": [],
        "total": 0,
        "page_info": {"offset": 0, "limit": 10, "returned_count": 0},
    }
    chars, toks = _fresh_size(payload)
    payload["_meta"] = {
        "chars": chars,
        "tokens_est": toks,
        "truncated": False,
        "detected_type": "wikipedia",
        "detection_confidence": "high",
    }
    out = _merge_promotion_into_title_results(
        payload, {"path": "A/Biofuel", "title": "Biofuel"}, limit=10
    )
    assert out["_meta"]["detected_type"] == "wikipedia"
    assert out["_meta"]["detection_confidence"] == "high"


def test_no_promotion_passes_raw_through_untouched() -> None:
    payload = {"results": [], "_meta": {"chars": 1, "tokens_est": 1}}
    assert _merge_promotion_into_title_results(payload, None) is payload
