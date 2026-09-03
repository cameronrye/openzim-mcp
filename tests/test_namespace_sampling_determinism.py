"""``list_namespaces`` on any archive over 1,000 entries was a coin flip.

``_list_archive_namespaces`` takes the sampled branch whenever
``entry_count > NAMESPACE_MAX_SAMPLE_SIZE`` — i.e. for every real archive.
That branch called ``archive.get_random_entry()`` a thousand times, which
made the response:

* **non-deterministic** — three consecutive calls returned three different
  ``sample_entries`` lists, so the response the cache stores is a lottery
  ticket and every warm read hands the client a payload that disagrees with
  the last one. Determinism is repo doctrine (see
  ``tests/test_list_ordering_determinism.py``: "a list whose order wobbles
  turns every cache entry into a miss"), and the cache block in
  ``namespace.py`` already carries a scar from the same class of bug.
* **blind** — libzim's ``get_random_entry`` draws from the *article* index,
  not the entry index, so on the climate-change fixture all 1,000 draws
  landed in ``A``. The 110 ``I/`` images and the 54 ``-/`` layout entries
  were structurally undiscoverable; only the canonical-path probes ever
  surfaced anything outside ``A``.
* **arithmetically impossible** — because 100% of the sample landed in
  ``A``, ``A`` was projected at the archive's entire ``entry_count`` and the
  probed namespaces were then stacked on top: ``A=20565 + M=5 + X=2 + -=1``
  summed to 20,573 against a stated ``total_entries`` of 20,565.

The sample is now a systematic (strided) walk over entry ids, phase-shifted
by a digest of the archive UUID: same archive, same sample, forever — and
because old-scheme ZIM archives store dirents grouped by namespace, an
evenly strided walk represents every namespace in proportion to its real
size instead of missing the small ones.

The fixture used here is the one already in the corpus:
``wikipedia_en_climate_change_mini_2024-06.zim``, 20,565 entries, whose true
namespace distribution is ``A=20387, I=110, -=54, M=12, X=2``.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path
from typing import Dict, Optional

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.constants import NAMESPACE_MAX_SAMPLE_SIZE
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim.namespace import (
    _NAMESPACE_PROJECTION_MIN_SAMPLES,
    _clamp_projections_to_total,
    _deterministic_sample_ids,
    _NamespaceMixin,
)
from openzim_mcp.zim_operations import ZimOperations

_NAMESPACE_SRC = Path("openzim_mcp/zim/namespace.py").read_text(encoding="utf-8")


@pytest.fixture
def sampled_ops(real_content_zim_files: Dict[str, Optional[Path]]):
    """Ops bound to the one corpus archive big enough to sample, cache OFF.

    The cache is disabled deliberately: a cached payload would mask the
    non-determinism by serving the first roll of the dice back to every
    later caller.
    """
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("climate-change ZIM fixture not available")
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(zim.parent)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=100_000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    ops = ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache, enable_background_cleanup=False),
        ContentProcessor(snippet_length=100),
    )
    return ops, str(zim)


def test_the_fixture_really_takes_the_sampled_branch(sampled_ops) -> None:
    """Vacuity guard for every other test in this file.

    If the fixture were ever swapped for one under the threshold, the
    assertions below would all pass against the exhaustive branch without
    exercising a single line of the sampling code they exist to pin.
    """
    ops, zim = sampled_ops
    payload = ops.list_namespaces_data(zim)
    assert payload["total_entries"] > NAMESPACE_MAX_SAMPLE_SIZE
    assert payload["discovery_method"] == "sampling"
    assert payload["is_total_authoritative"] is False


def test_repeated_calls_return_a_byte_identical_payload(sampled_ops) -> None:
    """The whole point: the same archive must answer the same thing."""
    ops, zim = sampled_ops
    blobs = [
        json.dumps(ops.list_namespaces_data(zim), sort_keys=True) for _ in range(3)
    ]
    assert blobs[0] == blobs[1] == blobs[2], (
        "list_namespaces_data is non-deterministic on the sampled path; "
        "every cache entry it feeds is a lottery ticket"
    )


def test_per_namespace_totals_cannot_sum_above_the_archive_total(
    sampled_ops,
) -> None:
    """A projection that sums past the authoritative total is nonsense."""
    ops, zim = sampled_ops
    payload = ops.list_namespaces_data(zim)
    total = payload["total_entries"]
    per_ns = {k: v["total"] for k, v in payload["namespaces"].items()}
    assert sum(per_ns.values()) <= total, (
        f"per-namespace projections sum to {sum(per_ns.values())} against a "
        f"stated total_entries of {total}: {per_ns}"
    )


def test_sampling_sees_namespaces_the_article_index_hides(sampled_ops) -> None:
    """``I`` holds 110 real entries and was invisible to random sampling.

    ``get_random_entry`` draws from the article index, so images and layout
    assets could only ever be reached by the canonical-path probe list. The
    ``I`` probe on that list (``I/favicon.png``) does not exist in this
    archive — ``has_entry_by_path`` returns False for it, while ``-/favicon``
    matches, which is why ``-`` showed up at 1 and ``I`` not at all. Probing
    proves existence at one guessed path; only walking entry ids finds a
    namespace whose paths you cannot guess.
    """
    ops, zim = sampled_ops
    found = set(ops.list_namespaces_data(zim)["namespaces"])
    assert "I" in found, f"image namespace never discovered; found {sorted(found)}"


def test_projections_track_the_true_distribution(sampled_ops) -> None:
    """Compare the sampled estimate against an exhaustive count.

    Full iteration of 20,565 entries is cheap enough to do here, and it is
    the only honest way to say the projection is *right* rather than merely
    self-consistent.

    The two namespaces are checked against different bands on purpose,
    because they rest on wildly different amounts of signal. Pinning both
    to one tight number would pin this fixture's luck rather than the
    projection, and would red on any future change to the stride or the
    UUID phase with a message that reads like an accuracy regression.
    """
    ops, zim = sampled_ops
    from libzim.reader import Archive

    archive = Archive(zim)
    truth: collections.Counter = collections.Counter()
    for entry_id in range(archive.entry_count):
        path = archive._get_entry_by_id(entry_id).path
        truth[path.split("/", 1)[0] if "/" in path else "?"] += 1

    buckets = ops.list_namespaces_data(zim)["namespaces"]

    # ``A`` is 99% of the archive, so its projection rests on ~1,000 sampled
    # hits. 5% is a real constraint here (measured error: 0.06%) and does
    # not care where the stride lands.
    a_actual, a_estimated = truth["A"], buckets.get("A", {}).get("total", 0)
    assert abs(a_estimated - a_actual) <= 0.05 * a_actual, (
        f"namespace A: estimated {a_estimated}, actual {a_actual} — the "
        f"dominant namespace's projection should be near-exact"
    )

    # ``I`` is the namespace the article-index sampler could never reach.
    # Split into two claims so a failure says which half broke.
    assert "I" in buckets, f"image namespace never discovered: {sorted(buckets)}"
    i_bucket = buckets["I"]
    assert i_bucket["sampled_count"] >= _NAMESPACE_PROJECTION_MIN_SAMPLES, (
        f"the stride landed only {i_bucket['sampled_count']} draws in I, below "
        f"the {_NAMESPACE_PROJECTION_MIN_SAMPLES}-hit floor for projecting at "
        f"all — I's total is now a probe floor, not an estimate"
    )
    # 50%, not 10%: at ~5 hits the sampling standard error is already ~45%,
    # so a tighter band asserts luck. It still fails loudly on the pre-fix
    # behaviour, which estimated 0 against a true 110 (100% error).
    i_actual, i_estimated = truth["I"], i_bucket["total"]
    assert (
        abs(i_estimated - i_actual) <= 0.50 * i_actual
    ), f"namespace I: estimated {i_estimated}, actual {i_actual}"


# ---------------------------------------------------------------------------
# The sibling sampler: browse_namespace must describe the same archive.
# ---------------------------------------------------------------------------


def test_browse_agrees_with_list_about_which_namespaces_have_entries(
    sampled_ops,
) -> None:
    """Two tools must not contradict each other about one archive.

    ``browse_namespace``'s own sampler used ``get_random_entry`` too, so it
    inherited the article-index blindness: ``list_namespaces`` advertised
    ``I`` at 102 entries and ``browse_namespace('I')`` answered ``total: 0,
    results: []``. An agent that reads the first and then calls the second
    concludes the archive — or the server — is broken.

    The counts themselves are not compared: browse returns a lower bound
    capped at ``NAMESPACE_MAX_ENTRIES`` and says so via
    ``page_info.total_is_lower_bound``. Non-emptiness is the claim both
    tools make, so non-emptiness is what has to match.
    """
    ops, zim = sampled_ops
    advertised = {
        ns: info["total"]
        for ns, info in ops.list_namespaces_data(zim)["namespaces"].items()
        if info["total"] > 0
    }
    assert advertised, "fixture surfaced no namespaces at all"

    empty_in_browse = {}
    for namespace in sorted(advertised):
        page = ops.browse_namespace_data(zim, namespace, 5, 0)
        if page["total"] == 0 or not page["results"]:
            empty_in_browse[namespace] = page["total"]

    assert not empty_in_browse, (
        f"list_namespaces advertises {advertised} but browse_namespace "
        f"reports these empty: {empty_in_browse}"
    )


def test_browse_returns_a_byte_identical_page_on_the_sampled_path(
    sampled_ops,
) -> None:
    """Same archive, same page — browse is cached and paginated.

    A sampler that re-rolls per call gives page 2 a different population
    than page 1, so a client walking the cursor sees entries appear, vanish
    and repeat.
    """
    ops, zim = sampled_ops
    blobs = [
        json.dumps(ops.browse_namespace_data(zim, "A", 5, 0), sort_keys=True)
        for _ in range(3)
    ]
    assert (
        blobs[0] == blobs[1] == blobs[2]
    ), "browse_namespace_data is non-deterministic on the sampled path"


def test_browse_probes_cover_every_namespace_list_can_surface_by_probe() -> None:
    """Structural guard behind the agreement test above.

    ``list_namespaces`` finds ``X`` only via ``X/fulltext/xapian``; browse's
    own pattern list guessed ``X/fulltext`` and missed. Rather than keeping
    two hand-maintained lists in sync, browse now seeds its patterns from
    the canonical probe list, so this holds for namespaces no fixture in the
    corpus happens to contain.
    """
    ops = _NamespaceMixin()
    for probe in ops._get_known_namespace_probes():
        namespace = probe.split("/", 1)[0]
        assert probe in ops._get_common_namespace_patterns(namespace), (
            f"{probe} proves {namespace!r} exists to list_namespaces but "
            f"browse_namespace never tries it"
        )


# ---------------------------------------------------------------------------
# The two pieces of arithmetic, unit-tested away from libzim.
# ---------------------------------------------------------------------------


def test_sample_ids_are_stable_distinct_and_spread() -> None:
    ids = _deterministic_sample_ids(20_565, 1_000, "some-archive-uuid")
    assert ids == _deterministic_sample_ids(20_565, 1_000, "some-archive-uuid")
    assert len(ids) == 1_000
    assert len(set(ids)) == 1_000, "ids must be distinct — a repeat wastes a draw"
    assert all(0 <= i < 20_565 for i in ids)
    # Spread, not "the first N": the walk must reach both ends of the id
    # space, or a namespace stored at the tail of the dirent table is
    # unreachable by construction.
    assert min(ids) < 0.05 * 20_565
    assert max(ids) > 0.95 * 20_565


def test_sample_ids_are_phase_shifted_per_archive() -> None:
    """Two archives of identical size must not sample identical positions."""
    a = _deterministic_sample_ids(20_565, 1_000, "uuid-a")
    b = _deterministic_sample_ids(20_565, 1_000, "uuid-b")
    assert a != b


def test_sample_ids_degenerate_cases() -> None:
    assert _deterministic_sample_ids(0, 1_000, "x") == []
    assert _deterministic_sample_ids(100, 0, "x") == []
    # Asking for at least as many as exist is exhaustive iteration.
    assert _deterministic_sample_ids(7, 7, "x") == list(range(7))
    assert _deterministic_sample_ids(7, 99, "x") == list(range(7))


def test_clamp_shrinks_projections_but_never_the_observed_floor() -> None:
    """Probed floors are facts; only the extrapolated part may be shaved."""
    # 900 of 1000 samples in A, 100 in C; four namespaces known only from
    # canonical-path probes then stack their floors on top.
    estimates = {"A": 9_000, "C": 1_000, "M": 6, "W": 3, "X": 2, "-": 1}
    floors = {"A": 900, "C": 100, "M": 6, "W": 3, "X": 2, "-": 1}
    _clamp_projections_to_total(estimates, floors, 10_000)
    assert sum(estimates.values()) <= 10_000
    for ns, floor in floors.items():
        assert estimates[ns] >= floor, f"{ns} clamped below what we observed"


def test_a_sample_of_unreadable_entries_degrades_instead_of_raising() -> None:
    """A dirent that libzim refuses to read must not sink the whole listing.

    The old sampler swallowed per-draw failures; the id-driven one has to
    keep doing so, or one bad entry in a 20,000-entry archive turns
    ``list_namespaces`` into an ``OpenZimMcpArchiveError``.
    """
    from unittest.mock import MagicMock

    archive = MagicMock()
    archive.entry_count = 5_000
    archive.uuid = "unreadable"
    archive.has_new_namespace_scheme = False
    archive.has_entry_by_path.return_value = False
    archive._get_entry_by_id.side_effect = RuntimeError("corrupt dirent")

    recorded: list = []
    _NamespaceMixin._sample_entries(archive, 5_000, lambda *a, **kw: recorded.append(a))

    assert recorded == []
    assert archive._get_entry_by_id.call_count == NAMESPACE_MAX_SAMPLE_SIZE


def test_finalise_sampled_actually_clamps_what_it_publishes() -> None:
    """Pin the clamp *call site*, not just the clamp.

    The three ``test_clamp_*`` cases below call the helper directly, so they
    stay green if the call disappears from ``_finalise_sampled``; and on the
    one corpus archive large enough to sample, the projections happen to fit
    under ``total_entries`` on their own, so the integration invariant is
    green either way. Deleting the call really did leave the whole suite
    passing. This drives the production function with the shape that
    overflows — a sample that lands entirely in one namespace, plus buckets
    known only from canonical-path probes stacking their floors on top — and
    reads the published ``total`` values back out.
    """
    namespaces = {
        "A": {"_sampled_count": 1_000, "_probed_count": 0},
        "M": {"_sampled_count": 0, "_probed_count": 1},
        "X": {"_sampled_count": 0, "_probed_count": 1},
        "-": {"_sampled_count": 0, "_probed_count": 1},
    }
    _NamespaceMixin._finalise_sampled(namespaces, 10_000)

    published = {ns: info["total"] for ns, info in namespaces.items()}
    assert sum(published.values()) <= 10_000, (
        f"published per-namespace totals sum to {sum(published.values())} "
        f"against total_entries 10000: {published}"
    )
    # The clamp must shave the extrapolation, never the entries we saw:
    # the three probe-only buckets keep their floor of 1 each.
    assert published["M"] == 1
    assert published["X"] == 1
    assert published["-"] == 1
    # ...and ``A`` must still carry essentially the whole archive rather
    # than collapsing to its 1,000-entry sampled floor.
    assert published["A"] > 9_000
    assert namespaces["A"]["estimated_total"] == published["A"]


def test_clamp_is_a_no_op_when_the_projection_already_fits() -> None:
    estimates = {"A": 9_000, "M": 6}
    floors = {"A": 900, "M": 6}
    _clamp_projections_to_total(estimates, floors, 10_000)
    assert estimates == {"A": 9_000, "M": 6}


def test_clamp_leaves_floors_alone_when_they_already_exceed_the_total() -> None:
    """A pathological total is not a licence to under-report real entries."""
    estimates = {"A": 50, "M": 40}
    floors = {"A": 50, "M": 40}
    _clamp_projections_to_total(estimates, floors, 10)
    assert estimates == {"A": 50, "M": 40}


# ---------------------------------------------------------------------------
# Cache versioning: the payload changed, so the key must too.
# ---------------------------------------------------------------------------


def test_namespaces_cache_key_moved_past_the_3_2_5_spelling() -> None:
    """An operator with ``persistence_enabled`` restores a snapshot whose
    namespace listings were built by the random sampler. Nothing in the
    ``namespaces_data:v2b:<path>:<stat_token>`` key changes when the *code*
    changes, so those pre-fix payloads — wrong sums, missing ``I``, a random
    ``sample_entries`` — would be re-served verbatim until TTL expiry, with
    this release's fix inert on exactly the archives it was written for.
    Same rule as the ``bundle:v2d`` and ``browse_ns_data:v2e`` bumps.
    """
    assert "namespaces_data:v2b:" not in _NAMESPACE_SRC


def test_namespaces_cache_key_is_versioned() -> None:
    assert re.search(
        r'f"namespaces_data:v\d+[a-z]?:', _NAMESPACE_SRC
    ), "namespaces cache key lost its version segment"


def test_browse_cache_key_moved_past_the_3_2_5_spelling() -> None:
    """``browse_namespace``'s payload changed too, so its key must move.

    Same reasoning as the ``namespaces_data`` bump: a restored
    ``persistence_enabled`` snapshot holds pages built by the random
    sampler, including the empty ``I`` / ``-`` listings this release exists
    to correct.
    """
    assert "browse_ns_data:v2e:" not in _NAMESPACE_SRC
