"""Post-a14 sweep (F6 / B1): the ``tell_me_about`` lead-with-TOC
trailer must reference the canonical path, not the user's typo.

Motivating live regression: ``tell me about Bilogy`` resolved to the
Biology article (typo-fallback works), but the trailer suggested
``Use show structure of Bilogy ... or summary of Bilogy`` — pushing
the next call back through typo-fallback (or breaking outright if the
redirect is later removed).

Once F3 (canonical-path canonicalization in ``find_entry_by_title_data``)
landed, the promoted ``top_path`` is the canonical post-redirect path,
which the trailer then uses correctly. This test confirms the
end-to-end flow.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

from openzim_mcp.simple_tools import SimpleToolsHandler


def test_lead_trailer_uses_canonical_path_after_typo_promotion() -> None:
    """When the title-promotion path returns a canonical (post-
    redirect) entry, the lead-with-TOC trailer must reference that
    canonical path."""
    handler = SimpleToolsHandler.__new__(SimpleToolsHandler)
    handler.zim_operations = MagicMock()

    # Title-index returns canonical "Biology" for the typo "bilogy".
    def fake_find(
        zim_path: str,
        topic: str,
        *,
        cross_file: bool = False,
        limit: int = 3,
    ):
        if topic == "bilogy":
            return {
                "results": [
                    {
                        "path": "Biology",
                        "title": "Biology",
                        "score": 0.85,
                        "zim_file": zim_path,
                    }
                ]
            }
        return {"results": []}

    handler.zim_operations.find_entry_by_title_data.side_effect = fake_find

    # Article structure stub — sections exist for "Biology".
    def fake_structure(zim_path: str, entry_path: str) -> Dict[str, Any]:
        return {
            "headings": [
                {"level": 2, "text": "Etymology"},
                {"level": 2, "text": "History"},
                {"level": 2, "text": "Cells"},
            ]
        }

    handler.zim_operations.get_article_structure_data.side_effect = fake_structure

    # Body with a real h2 so the lead-cut fires and the trailer renders.
    body_with_h2 = (
        "**Biology** is the scientific study of life and living "
        "organisms.\n\n"
        "## Etymology\n\nThe word *biology* derives from..."
    )

    rendered = handler._lead_with_toc("/fake/wiki.zim", "Biology", body_with_h2)

    assert "show structure of Biology" in rendered, (
        f"Trailer should reference canonical 'Biology', got: {rendered!r}"
    )
    assert "show structure of Bilogy" not in rendered, (
        f"Trailer must NOT reference the typo path 'Bilogy', got: {rendered!r}"
    )
