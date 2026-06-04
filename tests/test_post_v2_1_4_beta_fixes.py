"""Post-v2.1.4 live-beta-sweep regression suite.

The v2.1.4 live beta sweep (deployed v2.1.6 server, dual-archive library:
Wikipedia 2026-02 + superuser.com 2026-02) surfaced two synthesize
defects of one class — a **2-token tail-hijack** where the query's last
token exact-title-matches a generic article that is then promoted to
rank 1, burying the relevant content:

  #253 — ``synthesize("connection refused")`` promotes the Wikipedia
  article ``Refused`` (a punk band) at rank 1 while the relevant
  superuser.com SSH troubleshooting Q&As are buried. The hit is a
  single-token tail from a NON-PRIMARY archive, tagged ``promoted``, so
  ``_drop_cross_archive_leakage`` unconditionally exempts it from the
  cross-archive path-overlap floor.

  #252 — ``synthesize("Einstein's theory")`` promotes the generic
  ``Theory`` instead of the more-specific ``Theory_of_relativity`` (same
  class as ``Plato's cave`` -> ``Cave`` vs ``Allegory_of_the_cave``).
  The apostrophe-stripped topic (``einstein theory``) cannot reach the
  specific canonical that the apostrophe-preserving original query
  (``einstein's theory``) resolves to at score 1.0.

The two filed issues share the enabling cause: the ``< 3 token`` floor
in ``title_promotion._accept_non_possessive`` waves any 2-token query's
generic-tail promotion through. The floor protects legitimate 2-token
tails (``planet earth`` -> ``Earth``, ``Berlin Germany`` -> ``Berlin``),
so the fix must stay cross-archive-aware / more-specific-canonical-aware.

These defects are NOT reproducible from a local checkout (they depend on
the live 118 GB title index); the mocks below encode the live-observed
``find_title_match`` / ``title_match_hit`` result shapes.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

from openzim_mcp.title_promotion import is_single_token_tail_match


def test_single_token_tail_match_fires_on_2token_query() -> None:
    # "connection refused" -> "Refused": the #253 shape the floored
    # is_tail_hijack_shape MISSES because the query has only 2 tokens.
    assert is_single_token_tail_match({"path": "Refused"}, "connection refused")


def test_single_token_tail_match_ignores_multitoken_canonical() -> None:
    # darwins evolution -> On_the_Origin_of_Species: multi-token canonical,
    # the legitimate lexically-disjoint promotion exemption.
    assert not is_single_token_tail_match(
        {"path": "On_the_Origin_of_Species"}, "darwins evolution"
    )


def test_single_token_tail_match_requires_tail_position() -> None:
    # head-position single token is not a tail hijack ("Berlin Germany"->Berlin)
    assert not is_single_token_tail_match({"path": "Berlin"}, "berlin germany")


def test_leak_gate_drops_nonprimary_promoted_tail_hijack() -> None:
    # superuser is primary (path overlap {connection, refused} = 2);
    # wiki/Refused is a tagged promoted hit but a single-token tail from
    # the non-primary archive -> must be dropped despite the `promoted` tag.
    from openzim_mcp.synthesize import _drop_cross_archive_leakage

    top_hits = [
        (
            "wikipedia",
            {"path": "Refused", "promoted": True, "snippet": "", "score": 1.0},
        ),
        (
            "superuser",
            {"path": "questions/1/ssh-connection-refused", "snippet": "", "score": 0.5},
        ),
    ]
    kept = _drop_cross_archive_leakage(
        top_hits,
        query="connection refused",
        fallback_used="rrf_fusion",
        max_secondary_archive_hits=1,
        min_overlap=1,
    )
    paths = [h["path"] for _, h in kept]
    assert "Refused" not in paths
    assert "questions/1/ssh-connection-refused" in paths


def test_leak_gate_keeps_multitoken_promoted_exemption() -> None:
    # darwins evolution -> On_the_Origin_of_Species (promoted, lexically
    # disjoint, multi-token) must KEEP its exemption.
    from openzim_mcp.synthesize import _drop_cross_archive_leakage

    top_hits = [
        (
            "wikipedia",
            {
                "path": "On_the_Origin_of_Species",
                "promoted": True,
                "snippet": "",
                "score": 1.0,
            },
        ),
        ("superuser", {"path": "questions/2/git-merge", "snippet": "", "score": 0.5}),
    ]
    kept = _drop_cross_archive_leakage(
        top_hits,
        query="darwins evolution",
        fallback_used="rrf_fusion",
        max_secondary_archive_hits=1,
        min_overlap=1,
    )
    assert "On_the_Origin_of_Species" in [h["path"] for _, h in kept]


def test_promote_title_match_accepts_original_query_kw() -> None:
    # Plumbing-only: passing original_query must not change a no-op promote.
    from openzim_mcp.synthesize import _promote_title_match

    top_hits = [("wikipedia", {"path": "Berlin", "snippet": "", "score": 1.0})]
    # Berlin is already a strong title match for "berlin" -> short-circuit,
    # returns input unchanged regardless of original_query.
    out = _promote_title_match(
        top_hits,
        query="berlin",
        original_query="berlin",
        archives=[],
        archives_searched=[],
        search_handler=object(),
    )
    assert out == top_hits


def _rescue_handler(
    title_index_by_query: Dict[str, Dict[str, Any]],
    hit_by_title: Dict[str, Dict[str, Any]],
) -> Any:
    """Mock search_handler: find_entry_by_title_data keyed by query,
    title_match_hit keyed by resolved title."""
    m = MagicMock()

    def fake_fetbd(
        _vp: str, q: str, *, cross_file: bool = False, limit: int = 3
    ) -> Dict[str, Any]:
        row = title_index_by_query.get(q.lower())
        return {"results": [row] if row else []}

    m.find_entry_by_title_data.side_effect = fake_fetbd
    m.title_match_hit.side_effect = lambda _archive, title: hit_by_title.get(
        title.lower()
    )
    return m


def test_einsteins_theory_rescues_theory_of_relativity() -> None:
    # tail "theory" -> generic "Theory"; original "einstein's theory"
    # resolves to the more-specific multi-token canonical containing "theory".
    from openzim_mcp.synthesize import _promote_title_match

    handler = _rescue_handler(
        title_index_by_query={
            "einstein's theory": {
                "path": "Theory_of_relativity",
                "title": "Theory of relativity",
                "score": 1.0,
            },
            "theory": {"path": "Theory", "title": "Theory", "score": 1.0},
        },
        hit_by_title={
            "theory": {"path": "Theory", "snippet": "...", "score": 1.0},
            "theory of relativity": {
                "path": "Theory_of_relativity",
                "snippet": "...",
                "score": 1.0,
            },
        },
    )
    archive = object()
    # A weak BM25 top hit that does NOT strong-title-match the 2-token
    # query (a bare "Einstein" would prefix-match "einstein theory" and
    # short-circuit _promote_title_match before the tail loop runs).
    out = _promote_title_match(
        [("wikipedia", {"path": "Some_BM25_Noise", "snippet": "", "score": 0.5})],
        query="einstein theory",  # stripped topic (what synthesize gets today)
        original_query="einstein's theory",  # raw query (apostrophe preserved)
        archives=[(archive, "wiki.zim")],
        archives_searched=["wikipedia"],
        search_handler=handler,
    )
    assert out[0][1]["path"] == "Theory_of_relativity"
    assert out[0][1].get("promoted") is True


def test_planet_earth_keeps_bare_tail_no_rescue() -> None:
    # original "planet earth" resolves only to single-token "Earth" -> no
    # more-specific canonical -> keep the legitimate bare-tail promotion.
    from openzim_mcp.synthesize import _promote_title_match

    handler = _rescue_handler(
        title_index_by_query={
            "planet earth": {"path": "Earth", "title": "Earth", "score": 1.0},
            "earth": {"path": "Earth", "title": "Earth", "score": 1.0},
        },
        hit_by_title={"earth": {"path": "Earth", "snippet": "...", "score": 1.0}},
    )
    archive = object()
    # Weak BM25 top hit (a bare "Planet" would prefix-match "planet earth"
    # and short-circuit before the promotion path runs).
    out = _promote_title_match(
        [("wikipedia", {"path": "Some_BM25_Noise", "snippet": "", "score": 0.5})],
        query="planet earth",
        original_query="planet earth",
        archives=[(archive, "wiki.zim")],
        archives_searched=["wikipedia"],
        search_handler=handler,
    )
    assert out[0][1]["path"] == "Earth"


def test_possessive_rescue_skips_when_canonical_lacks_tail_token() -> None:
    # Fix D (#252 review): possessive original query whose canonical does
    # NOT contain the tail token must NOT be rescued. ``einstein's theory``
    # (stripped ``einstein theory``) resolves to ``Special_relativity``
    # (tokens ``special``, ``relativity`` — no ``theory``). The rescue must
    # not promote it. Because the query is an apostrophe-possessive, the
    # tail loop runs with ``min_len=2`` and never probes the bare ``theory``
    # tail, so the generic ``Theory`` is not promoted either — the result
    # falls through to the untouched BM25 ranking. This is a regression
    # guard: it already passes against the post-Fix-A/B/C code (the rescue's
    # ``tail_tok[0] in rescued_tokens`` check would reject ``Special_relativity``
    # anyway, and the ``min_len=2`` floor keeps the rescue from even being
    # reached), so it documents that no path promotes the tail-less canonical.
    from openzim_mcp.synthesize import _promote_title_match

    handler = _rescue_handler(
        title_index_by_query={
            # Original possessive resolves to a multi-token canonical that
            # does NOT contain the tail token "theory".
            "einstein's theory": {
                "path": "Special_relativity",
                "title": "Special relativity",
                "score": 1.0,
            },
            "theory": {"path": "Theory", "title": "Theory", "score": 1.0},
        },
        hit_by_title={
            "theory": {"path": "Theory", "snippet": "...", "score": 1.0},
            "special relativity": {
                "path": "Special_relativity",
                "snippet": "...",
                "score": 1.0,
            },
        },
    )
    archive = object()
    out = _promote_title_match(
        [("wikipedia", {"path": "Some_BM25_Noise", "snippet": "", "score": 0.5})],
        query="einstein theory",  # stripped topic
        original_query="einstein's theory",  # raw possessive query
        archives=[(archive, "wiki.zim")],
        archives_searched=["wikipedia"],
        search_handler=handler,
    )
    # The rescue must NOT fire: the canonical lacks the tail token.
    assert out[0][1]["path"] != "Special_relativity"
