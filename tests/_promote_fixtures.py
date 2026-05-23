"""Shared test fixtures for the post-bN beta-test sweep regression
suites.

Each sweep file (``test_post_b6_beta_fixes``, ``test_post_b7_beta_fixes``,
``test_post_b8_beta_fixes``, …) drives
``SimpleToolsHandler._promote_topic_via_title_index`` with a patched
``find_title_match``. The fixtures below — a stub handler, a
``find_title_match`` builder keyed by lowered topic, and a one-call
unbound driver — were copy-pasted across the sweep files until the
post-b8 sweep ran into SonarCloud's 3% new-duplicated-lines-density
threshold. Extracting to this module is purely a deduplication step;
no behaviour change.

The module name starts with an underscore so pytest's
``python_files = ["test_*.py"]`` collector skips it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional
from unittest.mock import patch


def make_simple_handler() -> Any:
    """Return a stub ``SimpleToolsHandler``-shaped object suitable for
    calling ``_promote_topic_via_title_index`` unbound."""

    class _StubOps:
        pass

    class _Handler:
        zim_operations = _StubOps()

    return _Handler()


def fake_find_title_match(
    mapping: Dict[str, Optional[Dict[str, Any]]],
    *,
    min_score_floor: float = 0.0,
) -> Callable[..., Optional[Dict[str, Any]]]:
    """Build a ``find_title_match`` stand-in from ``{topic_lower: row}``.

    Returns the mapped row when ``topic.lower()`` is a key AND the
    caller's ``min_score`` is at or below ``min_score_floor`` (default
    0.0 = no threshold check). Each test passes
    ``min_score_floor=0.95`` when it wants the stub to mimic the
    libzim suggestion-rank cap (rows at score 0.95 only visible when
    caller requests ≤ 0.95).
    """

    def fake(
        zim_ops: Any,
        zim_file_path: str,
        topic: str,
        *,
        cross_file: bool = False,
        min_score: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        if min_score > min_score_floor and min_score_floor > 0.0:
            return None
        return mapping.get(topic.lower())

    return fake


def run_promote_simple(
    topic: str, fake_find: Callable[..., Optional[Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    """Drive ``SimpleToolsHandler._promote_topic_via_title_index`` with
    ``fake_find`` patched at the import site."""
    from openzim_mcp.simple_tools import SimpleToolsHandler

    with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake_find):
        return SimpleToolsHandler._promote_topic_via_title_index(
            make_simple_handler(),
            "test.zim",
            topic,
        )
