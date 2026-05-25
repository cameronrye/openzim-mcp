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

    # Phase F: ``_promote_topic_via_title_index`` is a thin wrapper over
    # ``openzim_mcp.topic_preprocessing.promote_topic_via_title_index`` which
    # imports ``find_title_match`` from ``title_promotion`` at its own module
    # scope. Patching the symbol in ``simple_tools`` is no longer effective;
    # the live binding sits in ``topic_preprocessing``.
    with patch(
        "openzim_mcp.topic_preprocessing.find_title_match", side_effect=fake_find
    ):
        return SimpleToolsHandler._promote_topic_via_title_index(
            make_simple_handler(),
            "test.zim",
            topic,
        )


def picasso_paris_cubism_mapping() -> Dict[str, Optional[Dict[str, Any]]]:
    """Z4 biographical-exemption fixture: head probe ``picasso`` resolves
    to the same canonical (``Pablo_Picasso``) the orchestrator is about
    to promote, so Z4 must accept the promotion. Shared between the b11
    sweep regression and the direct ``topic_preprocessing`` unit tests
    (Sonar new-code duplication threshold).
    """
    return {
        "picasso paris cubism": {
            "path": "Pablo_Picasso",
            "title": "Pablo Picasso",
            "zim_file": "test.zim",
            "match_type": "redirect",
            "pre_redirect_path": "Picasso",
        },
        "picasso": {
            "path": "Pablo_Picasso",
            "title": "Pablo Picasso",
            "zim_file": "test.zim",
            "match_type": "redirect",
            "pre_redirect_path": "Picasso",
        },
        "paris": {
            "path": "Paris",
            "title": "Paris",
            "zim_file": "test.zim",
            "match_type": "direct",
        },
        "cubism": {
            "path": "Cubism",
            "title": "Cubism",
            "zim_file": "test.zim",
            "match_type": "direct",
        },
    }


def beethoven_9th_symphony_mapping() -> Dict[str, Optional[Dict[str, Any]]]:
    """Z4 digit-specificity-exemption fixture: canonical extras
    ``{no, 9}`` include a digit AND topic ``{beethoven, 9th, symphony}``
    includes a digit token, so Z4 must accept the specific numbered
    instance. Shared between the b11 sweep regression and the direct
    ``topic_preprocessing`` unit tests.
    """
    return {
        "beethoven 9th symphony": {
            "path": "Symphony_No._9_(Beethoven)",
            "title": "Symphony No. 9 (Beethoven)",
            "zim_file": "test.zim",
            "match_type": "fuzzy_suggest",
        },
        "9th symphony": {
            "path": "Symphony_No._9_(Beethoven)",
            "title": "Symphony No. 9 (Beethoven)",
            "zim_file": "test.zim",
            "match_type": "fuzzy_suggest",
        },
        "symphony": {
            "path": "Symphony",
            "title": "Symphony",
            "zim_file": "test.zim",
            "match_type": "direct",
        },
        "beethoven": {
            "path": "Ludwig_van_Beethoven",
            "title": "Ludwig van Beethoven",
            "zim_file": "test.zim",
            "match_type": "redirect",
            "pre_redirect_path": "Beethoven",
        },
    }


def make_disambig_handler(
    *,
    article_body: str,
    search_results: list,
    title_index: Optional[Dict[str, Any]] = None,
    zim_file_path: str = "/x.zim",
    bm25_fallback_text: str = "## BM25 fallback rendered\n\n...",
) -> tuple[Any, Any]:
    """Build a ``(SimpleToolsHandler, mock)`` pair for tell_me_about
    integration tests that exercise the disambig-render-time rejection
    path (post-b11 Sub-pattern C + post-b12 phrasing variants).

    The mock supplies the standard tell_me_about dependencies:
    BM25 search results, title-index lookup, article body fetch, the
    fall-to-search rendering hook, and a stubbed article structure.
    Returns the (handler, mock) tuple so callers can assert on mock
    invocations like ``mock.search_zim_file.assert_called()``.

    Extracted to share between b11 + b12 sweep test files (Sonar
    new-code duplication threshold).
    """
    from unittest.mock import MagicMock

    from openzim_mcp.simple_tools import SimpleToolsHandler

    mock = MagicMock()
    mock.list_zim_files_data.return_value = [{"path": zim_file_path}]
    mock.search_zim_file_data.return_value = {"results": search_results}
    mock.search_zim_file.return_value = bm25_fallback_text
    mock.get_zim_entry.return_value = article_body
    mock.config.meta.footer_enabled = False
    mock.find_entry_by_title_data.return_value = (
        {"results": [title_index]} if title_index else {"results": []}
    )
    mock.get_article_structure_data.return_value = {"sections": []}
    return SimpleToolsHandler(mock), mock
