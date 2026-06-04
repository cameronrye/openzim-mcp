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
