"""The reported cache hit rate must describe the cache, not the caller.

v3.3.1 field report, fid 127 — from the "diagnostics that lie" cluster.
The same workload, with every repeat served from cache in 0.001 s, reports
either "Server is running optimally" or "Cache hit rate is low — consider
issuing repeated queries" depending on the ``limit`` the caller passed::

    limit=1   hits 9  misses 11   hit_rate 0.45    -> "running optimally"
    limit=50  hits 18 misses 247  hit_rate 0.0679  -> "hit rate is low"

The extra 236 misses are not response lookups at all. ``_get_entry_snippet``
consults a per-entry ``snippet_render:v1:`` fragment once per search RESULT,
so a 50-row search charges 50 lookups to a counter a human reads as "how
often did the server avoid repeating work for a client". A client that
obeys the advice and repeats its queries cannot move that number.

The cache can already tell an ancillary *hit* (the key is in
``_ancillary_keys``) but not an ancillary *miss* — on a miss the key is not
there yet — and in the reported case essentially all of the polluting
lookups are first-time misses. So the call site declares what it is asking
for, which is the only place that knows.

The capacity half of fid 127 ("say the cache is full") shipped already;
``test_a_full_cache_is_still_reported_as_full`` keeps it honest here.
"""

from __future__ import annotations

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig


@pytest.fixture
def cache() -> OpenZimMcpCache:
    return OpenZimMcpCache(CacheConfig(enabled=True, max_size=100, ttl_seconds=3600))


# ---------------------------------------------------------------------------
# hit_rate counts response lookups only
# ---------------------------------------------------------------------------


def test_an_ancillary_miss_does_not_move_the_headline_rate(cache):
    """The reported defect, minimally: fragment lookups swamp the rate."""
    cache.set("search:q", {"rows": []})
    cache.get("search:q")  # one response hit

    before = cache.stats()["hit_rate"]
    for i in range(200):
        cache.get(f"snippet_render:v1:{i}", ancillary=True)
    after = cache.stats()

    assert after["hit_rate"] == before == 1.0, after
    assert after["hits"] == 1 and after["misses"] == 0, after


def test_ancillary_traffic_is_still_reported_somewhere(cache):
    """Excluded from the headline is not the same as thrown away — the
    fragment cache is a real cache and its behaviour is worth seeing."""
    cache.set("snippet_render:v1:a", "body", ancillary=True)
    cache.get("snippet_render:v1:a", ancillary=True)
    cache.get("snippet_render:v1:b", ancillary=True)

    stats = cache.stats()
    assert stats["ancillary_hits"] == 1, stats
    assert stats["ancillary_misses"] == 1, stats
    assert stats["hits"] == 0 and stats["misses"] == 0, stats


def test_response_lookups_still_count_both_ways(cache):
    """Control: the headline counters must keep working."""
    cache.get("search:cold")
    cache.set("search:cold", {"rows": []})
    cache.get("search:cold")

    stats = cache.stats()
    assert (stats["hits"], stats["misses"]) == (1, 1), stats
    assert stats["hit_rate"] == 0.5, stats


def test_the_verdict_no_longer_depends_on_the_page_size(cache):
    """fid 127's actual claim, as the property it is.

    Two runs of the same five-query workload, all five repeats cached,
    differing only in how many rows each query rendered. The verdict a
    human reads must be the same.
    """

    def workload(rows_per_query: int) -> float:
        c = OpenZimMcpCache(CacheConfig(enabled=True, max_size=100, ttl_seconds=3600))
        for q in range(5):
            c.get(f"search:{q}")  # cold
            c.set(f"search:{q}", {"rows": rows_per_query})
            for row in range(rows_per_query):
                c.get(f"snippet_render:v1:{q}:{row}", ancillary=True)
                c.set(f"snippet_render:v1:{q}:{row}", "body", ancillary=True)
            c.get(f"search:{q}")  # the repeat the advice asks for
        return float(c.stats()["hit_rate"])

    assert workload(1) == workload(50)


# ---------------------------------------------------------------------------
# what zim_health says about it
# ---------------------------------------------------------------------------


def _recommendations(stats: dict) -> list:
    from openzim_mcp.server_state import _append_cache_recommendations

    out: list = []
    _append_cache_recommendations(stats, out)
    return out


def test_a_well_used_cache_is_not_told_to_repeat_itself():
    """The limit=50 run in the finding: every repeat cached, advised to
    "issue repeated queries against the same ZIM files"."""
    stats = {
        "enabled": True,
        "size": 6,
        "max_size": 100,
        "hits": 55,
        "misses": 6,
        "hit_rate": 0.9,
        "ancillary_entries": 241,
        "ancillary_hits": 0,
        "ancillary_misses": 247,
    }

    advice = " ".join(_recommendations(stats))
    assert "repeated queries" not in advice, advice


def test_a_genuinely_cold_cache_still_gets_the_advice():
    """Control: the low-hit-rate recommendation has to survive for the
    workload it was written for."""
    stats = {
        "enabled": True,
        "size": 6,
        "max_size": 100,
        "hits": 2,
        "misses": 60,
        "hit_rate": 0.032,
        "ancillary_entries": 0,
    }

    advice = " ".join(_recommendations(stats))
    assert "repeated queries" in advice, advice


def test_a_full_cache_is_still_reported_as_full():
    """The other half of fid 127, already shipped — pinned so the counter
    split above cannot quietly displace it."""
    stats = {
        "enabled": True,
        "size": 100,
        "max_size": 100,
        "hits": 170,
        "misses": 759,
        "hit_rate": 0.183,
        "ancillary_entries": 471,
    }

    advice = " ".join(_recommendations(stats))
    assert "full" in advice.lower(), advice
    assert "repeated queries" not in advice, advice


def test_every_fragment_lookup_declares_itself():
    """A drift guard, because the two halves live in different statements.

    ``set(..., ancillary=True)`` and ``get(..., ancillary=True)`` describe
    the same key. Adding a fragment cache and marking only the write puts
    its misses straight back into the headline rate — silently, since
    nothing else about the response changes.

    Stated as "every lookup of a FRAGMENT key is marked", not as "the two
    call counts match per file": the fid-70 title completion reads back the
    render its own snippet build wrote, from a different module, and a
    counting guard would have called that a defect.

    A fragment key is one produced by ``snippet_render_key``, so the scan
    first learns which local names hold one — matching on the literal
    ``"snippet_render"`` at the call site finds nothing, because every call
    site passes a variable, which is how the first version of this guard
    managed to pass while both call sites were unmarked.
    """
    import re
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    # ``[^=\n]`` on the optional annotation: a character class that allows
    # newlines lets the name capture drift lines above the assignment, which
    # is how this matched ``try`` and ``throughout`` on its first outing.
    binding = re.compile(
        r"^[ \t]*(\w+)(?:[ \t]*:[^=\n]+)?[ \t]*=[ \t]*snippet_render_key\(", re.M
    )
    unmarked: list[str] = []
    writes = 0
    checked = 0
    for path in (repo / "openzim_mcp").rglob("*.py"):
        if path.name == "cache.py":
            continue  # the implementation, not a call site
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(repo))
        writes += len(re.findall(r"\.set\([^)]*ancillary=True", text, re.S))
        names = set(binding.findall(text))
        for name in names:
            for call in re.finditer(
                rf"\.get\(\s*{re.escape(name)}\b(?P<rest>[^)]*)\)", text
            ):
                checked += 1
                if "ancillary=True" not in call.group("rest"):
                    lineno = text[: call.start()].count("\n") + 1
                    unmarked.append(f"{rel}:{lineno}: get({name}, ...)")

    assert writes, "no ancillary cache writes found — has the fixture moved?"
    assert checked >= 2, (
        f"only {checked} fragment lookups found; the guard is not reaching "
        "the call sites it exists for"
    )
    assert (
        not unmarked
    ), "these fragment lookups are charged to the headline hit rate: " + "; ".join(
        unmarked
    )
