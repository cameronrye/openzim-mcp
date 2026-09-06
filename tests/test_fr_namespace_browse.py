"""Field-report regressions for zim_browse / namespace discovery.

Every test here pins a behaviour that a real-corpus sweep of v3.3.1 found
wrong. The archives are built to the shape the sweep used (warc2zim site
scrapes with the chrome OUTSIDE the ``<article>`` landmark) or taken from
the zim-testing-suite corpus for the old-scheme cases, because the
fixture archives that already ship with the suite are chrome-free and
new-scheme and therefore cannot see any of these defects.

Findings covered:

* fid 126 / fid 76 — ``zim_browse(mode="page")`` rendered its ``preview``
  from the whole document, so every row previewed the site's cookie
  banner (MedlinePlus) or the empty string (IEP) instead of the article.
* fid 77 — the sampled browse branch reported
  ``results_may_be_incomplete: false`` for any sample under 200 rows.
* fid 78 — ``zim_metadata``'s M bucket was sampled on old-scheme archives
  even though ``Archive.metadata_keys`` enumerates M exactly.
* fid 83 — ``zim_browse(mode="walk")`` filtered non-article assets out of
  new-scheme C without any signal that it had done so.
* fid 80 — a namespace that is not on libzim's iterable surface was
  reported with a fabricated ``discovery_method: "full_iteration"``.
* fid 81 — ``sample_entries`` published the first five recorded entries,
  i.e. one contiguous alphabetical neighbourhood.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from libzim.writer import Creator, Hint, Item, StringProvider

from openzim_mcp.zim_operations import ZimOperations
from tests.conftest_v2_fixtures import _HtmlItem, make_zim_ops


class _AssetItem(Item):
    """A non-article asset (the shape browse/walk filter out of C)."""

    def __init__(self, path: str, mimetype: str, body: str) -> None:
        super().__init__()
        self._path = path
        self._mimetype = mimetype
        self._body = body

    def get_path(self) -> str:
        return self._path

    def get_title(self) -> str:
        return self._path

    def get_mimetype(self) -> str:
        return self._mimetype

    def get_contentprovider(self) -> StringProvider:
        return StringProvider(self._body)

    def get_hints(self) -> Dict[Hint, int]:
        return {Hint.FRONT_ARTICLE: 0}


# ---------------------------------------------------------------------------
# A warc2zim-shaped archive: site chrome outside the <article> landmark.
# ---------------------------------------------------------------------------

BANNER = "An official website of the United States government"
NAV_LINK = "Skip to main navigation"

ARTICLES = [
    ("aspirin", "Aspirin", "Aspirin is a medicine that reduces pain and fever."),
    ("bursitis", "Bursitis", "Bursitis is swelling of a fluid-filled sac in a joint."),
    ("cholera", "Cholera", "Cholera is an infection of the small intestine."),
    ("dengue", "Dengue", "Dengue is a mosquito-borne viral infection."),
    ("eczema", "Eczema", "Eczema makes skin red, itchy and inflamed."),
]

# warc2zim keeps the scraped site's assets in the same namespace as its
# articles, which is why browse/walk filter them out of C by default.
ASSETS = [
    ("example.org/media/masthead.png", "image/png", "PNGDATA"),
    ("example.org/media/logo.gif", "image/gif", "GIFDATA"),
    ("example.org/static/site.css", "text/css", "body{}"),
]


def _scraped_page(heading: str, lead: str) -> str:
    """One page shaped the way warc2zim/ZIMIT wraps a scraped site.

    The banner / masthead / nav sit OUTSIDE ``<article>``; only the body
    copy is inside it. An unscoped html2text render therefore yields the
    banner as the document's first paragraph.
    """
    return (
        "<html><body>"
        f"<header><p>{BANNER}</p>"
        f"<nav><ul><li><a href='#main'>{NAV_LINK}</a></li>"
        "<li><a href='../'>Home</a></li></ul></nav></header>"
        f"<article><h1>{heading}</h1><p>{lead}</p>"
        "<p>A second paragraph that the preview should not need.</p></article>"
        "<footer><p>Site footer boilerplate repeated on every page.</p></footer>"
        "</body></html>"
    )


@pytest.fixture(scope="module")
def scraped_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a new-scheme archive whose pages carry warc2zim site chrome."""
    out_dir = tmp_path_factory.mktemp("fr-nsb-scraped")
    out_path = out_dir / "scraped_site.zim"
    with Creator(out_path).config_indexing(True, "eng") as creator:
        for slug, heading, lead in ARTICLES:
            creator.add_item(
                _HtmlItem(
                    f"example.org/{slug}.html",
                    f"{heading}: Example Health Encyclopedia",
                    _scraped_page(heading, lead),
                )
            )
        for path, mimetype, body in ASSETS:
            creator.add_item(_AssetItem(path, mimetype, body))
        creator.set_mainpath("example.org/aspirin.html")
    return out_path


@pytest.fixture(scope="module")
def scraped_ops(scraped_zim: Path) -> ZimOperations:
    return make_zim_ops(str(scraped_zim.parent))


def _rows(payload: Any) -> List[Dict[str, Any]]:
    return list(payload["results"])


# ---------------------------------------------------------------------------
# fid 126 / fid 76 — browse previews must come from the article body.
# ---------------------------------------------------------------------------


def test_browse_page_preview_is_article_body_not_site_chrome(
    scraped_ops: Any, scraped_zim: Path
) -> None:
    """fid 126/76: page-mode previews carry the lead sentence, not the banner.

    Drives ``browse_namespace_data`` end to end (the same entry point
    ``zim_browse(mode="page")`` calls) and asserts on the rendered rows.
    """
    payload = scraped_ops.browse_namespace_data(
        str(scraped_zim), namespace="C", limit=10, offset=0
    )
    rows = _rows(payload)
    assert len(rows) == len(ARTICLES), rows

    leads = {lead for _, _, lead in ARTICLES}
    for row in rows:
        preview = row["preview"]
        # Positive: the preview is the article's own lead sentence.
        assert preview, f"empty preview for {row['path']}"
        assert any(lead in preview for lead in leads), (row["path"], preview)
        # Negative: none of the surrounding site chrome leaked in.
        assert BANNER not in preview, (row["path"], preview)
        assert NAV_LINK not in preview, (row["path"], preview)


def test_browse_page_previews_are_distinct_per_row(
    scraped_ops: Any, scraped_zim: Path
) -> None:
    """fid 126: 1198 of 1200 real rows previewed the identical banner string.

    A preview that is constant across the page is pure token cost and
    makes every row look the same to a ranker, so distinctness is the
    property that actually matters.
    """
    payload = scraped_ops.browse_namespace_data(
        str(scraped_zim), namespace="C", limit=10, offset=0
    )
    previews = [row["preview"] for row in _rows(payload)]
    assert len(previews) == len(ARTICLES)
    assert len(set(previews)) == len(previews), previews


def test_browse_page_preview_drops_duplicate_title_heading(
    scraped_ops: Any, scraped_zim: Path
) -> None:
    """fid 76: the preview budget goes to body text, not a repeat of the row title.

    The row already carries ``title``; the scoped render starts with the
    page's ``<h1>``, so the snippet must be built with the title in hand
    the way the search-snippet path does.
    """
    payload = scraped_ops.browse_namespace_data(
        str(scraped_zim), namespace="C", limit=10, offset=0
    )
    rows = {row["path"]: row for row in _rows(payload)}
    row = rows["example.org/aspirin.html"]
    assert row["title"] == "Aspirin: Example Health Encyclopedia"
    # Positive: body text is present ...
    assert "Aspirin is a medicine that reduces pain and fever." in row["preview"]
    # ... negative: the duplicated markdown H1 is gone.
    assert not row["preview"].lstrip().startswith("# Aspirin")


def test_browse_page_preview_stays_a_navigation_sized_field(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """fid 126: the per-row cost has to buy something without ballooning.

    ``create_snippet`` defaults to the configured ``snippet_length``
    (3000 chars). Once previews stopped being one-line boilerplate that
    turned a 50-row page of long scholarly articles into tens of KB of
    lead paragraphs, so browse pins its own, much smaller bound.
    """
    out_dir = tmp_path_factory.mktemp("fr-nsb-long")
    out_path = out_dir / "long_articles.zim"
    lead = "Aristotle is a towering figure in ancient Greek philosophy. "
    body = " ".join(f"Sentence {i} of the body copy." for i in range(400))
    with Creator(out_path).config_indexing(True, "eng") as creator:
        creator.add_item(
            _HtmlItem(
                "example.org/aristotle.html",
                "Aristotle: Example Encyclopedia",
                _scraped_page("Aristotle", lead + body),
            )
        )
        creator.set_mainpath("example.org/aristotle.html")

    # Built with the SHIPPED snippet_length (3000), not the 200-char one
    # the golden-test helper configures — the cap has to hold against the
    # default a real server runs with.
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import (
        CacheConfig,
        ContentConfig,
        LoggingConfig,
        OpenZimMcpConfig,
    )
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.defaults import CONTENT
    from openzim_mcp.security import PathValidator

    assert CONTENT.SNIPPET_LENGTH >= 1000, CONTENT.SNIPPET_LENGTH
    config = OpenZimMcpConfig(
        allowed_directories=[str(out_path.parent)],
        tool_mode="advanced",
        cache=CacheConfig(enabled=False),
        content=ContentConfig(snippet_length=CONTENT.SNIPPET_LENGTH),
        logging=LoggingConfig(level="WARNING"),
    )
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=config.content.snippet_length),
    )
    row = ops.browse_namespace_data(str(out_path), namespace="C", limit=5, offset=0)[
        "results"
    ][0]
    # Positive: it is the article's own opening ...
    assert row["preview"].startswith(lead.strip()[:30])
    # ... negative: and it is a preview, not the article.
    assert len(row["preview"]) <= 220, len(row["preview"])


def test_prefix_cached_browse_pages_do_not_leak_through(scraped_zim: Path) -> None:
    """A persisted cache must not keep serving the pre-fix browse payload.

    Cache persistence is optional but real, and every previous change to
    this payload's shape came with a key bump for exactly this reason.
    All three changes here (scoped ``preview``, sampledness-based
    ``results_may_be_incomplete``, ``not_iterable``) are archive-
    independent, so the stat token alone would not invalidate anything.
    """
    from openzim_mcp.bundle import archive_stat_token

    ops = make_zim_ops(str(scraped_zim.parent))
    resolved = Path(scraped_zim).resolve()
    stat_token = archive_stat_token(resolved)
    poison = {
        "namespace": "C",
        "results": [{"path": "STALE", "title": "STALE", "preview": BANNER}],
        "next_cursor": None,
        "total": 1,
        "done": True,
        "page_info": {"offset": 0, "limit": 10, "returned_count": 1},
        "discovery_method": "full_iteration",
        "sampling_based": False,
        "results_may_be_incomplete": False,
    }
    stale_key = f"browse_ns_data:v2f:{resolved}:{stat_token}:C:10:0:assets=False"
    ops.cache.set(stale_key, poison)

    fresh = ops.browse_namespace_data(str(scraped_zim), namespace="C", limit=10)
    # Negative: the pre-fix page is not served ...
    assert "STALE" not in {row["path"] for row in fresh["results"]}
    # ... positive: the current page is, and it IS cached under the new key
    # (a second call returns the identical object).
    assert len(fresh["results"]) == len(ARTICLES)
    assert ops.browse_namespace_data(str(scraped_zim), namespace="C", limit=10) is fresh


# ---------------------------------------------------------------------------
# fid 83 — an exhaustive walk must say when it filtered assets away.
# ---------------------------------------------------------------------------


def test_walk_reports_the_assets_it_filtered_out(
    scraped_ops: Any, scraped_zim: Path
) -> None:
    """fid 83: walk C dropped 45% of the namespace with no signal at all.

    Both numbers a walk response carries that could serve as a
    denominator (``archive_entry_count`` / ``namespace_entry_count``)
    describe the UNFILTERED surface, so a walk that ended
    ``done: true, next_cursor: null`` after returning 1,733 of a claimed
    3,178 entries looked truncated or lossy. Page mode already emitted
    ``page_info.assets_filtered``; walk emitted nothing.
    """
    walk = scraped_ops.walk_namespace_data(
        str(scraped_zim), "C", cursor_state=None, limit=200
    )
    paths = {row["path"] for row in walk["results"]}
    # Premise: filtering really happened on this page.
    assert paths == {f"example.org/{slug}.html" for slug, _, _ in ARTICLES}
    for asset_path, _, _ in ASSETS:
        assert asset_path not in paths

    page_info = walk["page_info"]
    assert page_info["assets_filtered"] is True
    assert page_info["assets_skipped"] == len(ASSETS)
    # The arithmetic now closes: every id scanned was either returned or
    # counted as a filtered asset (new-scheme C holds nothing else).
    assert (
        page_info["returned_count"] + page_info["assets_skipped"]
        == walk["scanned_count"]
    )
    assert walk["done"] is True


def test_walk_without_the_filter_carries_no_asset_signal(
    scraped_ops: Any, scraped_zim: Path
) -> None:
    """Paired positive for fid 83: include_assets=True returns everything.

    The signal must appear only when rows were actually withheld, or it
    is just another constant field.
    """
    walk = scraped_ops.walk_namespace_data(
        str(scraped_zim),
        "C",
        cursor_state=None,
        limit=200,
        include_assets=True,
    )
    paths = {row["path"] for row in walk["results"]}
    assert paths == {f"example.org/{slug}.html" for slug, _, _ in ARTICLES} | {
        asset_path for asset_path, _, _ in ASSETS
    }
    assert "assets_filtered" not in walk["page_info"]
    assert "assets_skipped" not in walk["page_info"]


# ---------------------------------------------------------------------------
# fid 80 — a namespace off libzim's iterable surface must say so.
# ---------------------------------------------------------------------------


def test_non_iterable_namespace_is_not_labelled_full_iteration(
    scraped_ops: Any, scraped_zim: Path
) -> None:
    """fid 80: browsing I on a new-scheme archive claimed a scan that never ran.

    The empty result is correct — a new-scheme archive keeps its images
    under C — but it was published as ``discovery_method:
    "full_iteration"`` with no reason code, in 3 ms, which reads as a
    maximally confident "this archive has no images".
    """
    payload = scraped_ops.browse_namespace_data(
        str(scraped_zim), namespace="I", limit=5, offset=0
    )
    assert payload["total"] == 0
    assert payload["done"] is True
    assert payload["discovery_method"] == "not_iterable"
    assert payload["_meta"]["reason"] == "namespace_not_iterable"

    # Paired positives: the unknown-letter branch keeps its own label ...
    unknown = scraped_ops.browse_namespace_data(
        str(scraped_zim), namespace="Q", limit=5, offset=0
    )
    assert unknown["discovery_method"] == "rejected_unknown_namespace"
    assert unknown["_meta"]["reason"] == "bad_namespace"
    # ... and a namespace that really was enumerated still reports so.
    real = scraped_ops.browse_namespace_data(
        str(scraped_zim), namespace="C", limit=5, offset=0
    )
    assert real["results"]
    assert real["discovery_method"] not in {
        "not_iterable",
        "rejected_unknown_namespace",
    }


# ---------------------------------------------------------------------------
# fid 81 — published sample_entries must represent the namespace.
# ---------------------------------------------------------------------------

SAMPLE_ASSETS = [
    ("example.org/aa-logo.png", "image/png", "P"),
    ("example.org/ab-icon.gif", "image/gif", "G"),
    ("example.org/ac-hero.jpg", "image/jpeg", "J"),
    ("example.org/ad-sprite.png", "image/png", "P"),
    ("example.org/ae-theme.css", "text/css", "b{}"),
    ("example.org/af-app.js", "application/javascript", "0;"),
]
SAMPLE_ARTICLES = [f"example.org/b{chr(ord('a') + i)}-article.html" for i in range(8)]


@pytest.fixture(scope="module")
def sample_shape_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An archive whose alphabetically-first entries are all media files.

    This is the shape both real corpus archives have — IEP's C namespace
    opens on ``wp-content/media/*`` and MedlinePlus's on
    ``ency/images/ency/fullsize/*``.
    """
    out_dir = tmp_path_factory.mktemp("fr-nsb-samples")
    out_path = out_dir / "sample_shape.zim"
    with Creator(out_path).config_indexing(True, "eng") as creator:
        for path, mimetype, body in SAMPLE_ASSETS:
            creator.add_item(_AssetItem(path, mimetype, body))
        for path in SAMPLE_ARTICLES:
            creator.add_item(
                _HtmlItem(
                    path,
                    path.rsplit("/", 1)[-1],
                    _scraped_page("Heading", f"Lead sentence for {path}."),
                )
            )
        creator.set_mainpath(SAMPLE_ARTICLES[0])
    return out_path


def test_sample_entries_are_spread_and_prefer_real_articles(
    sample_shape_zim: Path,
) -> None:
    """fid 81: all five published samples were adjacent media files.

    ``sample_entries`` is the only place ``zim_metadata`` shows what an
    entry path in this archive looks like, and the recorder kept the
    first five rows it saw — one contiguous alphabetical neighbourhood,
    which on both real archives was 100% images under the label "User
    content entries (articles, main content)".
    """
    ops = make_zim_ops(str(sample_shape_zim.parent))
    listing = ops.list_namespaces_data(str(sample_shape_zim))
    bucket = listing["namespaces"]["C"]
    paths = [entry["path"] for entry in bucket["sample_entries"]]

    assert len(paths) == 5
    # Positive: every published example is a real article path ...
    assert all(p.endswith(".html") for p in paths), paths
    # ... negative: not one of the media files that sort first.
    assert not any(p in {a for a, _, _ in SAMPLE_ASSETS} for p in paths), paths
    # Spread, not the first five: the last article in the bucket is
    # represented, which a head-slice can never produce.
    assert SAMPLE_ARTICLES[-1] in paths, paths
    assert paths == sorted(paths), paths


# ---------------------------------------------------------------------------
# Old-scheme corpus fixtures (fids 77, 78) — the zim-testing-suite archive
# is the only old-scheme file above the 1000-entry sampling threshold.
# ---------------------------------------------------------------------------


@pytest.fixture
def climate_zim(real_content_zim_files: Dict[str, Optional[Path]]) -> Path:
    path = real_content_zim_files.get("wikipedia_climate")
    if path is None:
        pytest.skip("zim-testing-suite corpus not available (ZIM_TEST_DATA_DIR)")
    return path


@pytest.fixture
def climate_ops(climate_zim: Path) -> ZimOperations:
    return make_zim_ops(str(climate_zim.parent))


@pytest.fixture
def small_withns_zim(basic_test_zim_files: Dict[str, Optional[Path]]) -> Path:
    path = basic_test_zim_files.get("withns")
    if path is None:
        pytest.skip("zim-testing-suite corpus not available (ZIM_TEST_DATA_DIR)")
    return path


def test_sampled_browse_page_admits_it_may_be_incomplete(
    climate_ops: Any, climate_zim: Path, small_withns_zim: Path
) -> None:
    """fid 77: browse M said 6 entries, done, complete; walk returned 12.

    ``results_may_be_incomplete`` only ever tripped when the sample
    saturated the 200-row cap, so every sampled listing smaller than that
    self-certified as exhaustive.
    """
    page = climate_ops.browse_namespace_data(
        str(climate_zim), namespace="M", limit=50, offset=0
    )
    walk = climate_ops.walk_namespace_data(
        str(climate_zim), "M", cursor_state=None, limit=50
    )
    walk_paths = {row["path"] for row in walk["results"]}
    page_paths = {row["path"] for row in _rows(page)}

    # The premise: the two siblings really do disagree on this archive.
    assert page_paths < walk_paths, (sorted(page_paths), sorted(walk_paths))
    # The payload must not claim completeness for a sampled listing ...
    assert page["sampling_based"] is True
    assert page["results_may_be_incomplete"] is True
    # ... while an archive small enough to be enumerated exhaustively
    # keeps saying so (paired positive — the flag must not become a
    # constant True).
    exhaustive_ops = make_zim_ops(str(small_withns_zim.parent))
    exhaustive = exhaustive_ops.browse_namespace_data(
        str(small_withns_zim), namespace="M", limit=50, offset=0
    )
    assert exhaustive["sampling_based"] is False
    assert exhaustive["results_may_be_incomplete"] is False
    assert len(exhaustive["results"]) > 0


def test_metadata_namespace_is_exact_on_old_scheme_archives(
    climate_ops: Any, climate_zim: Path
) -> None:
    """fid 78: zim_metadata reported M=6 (sampled) where libzim knows M=12.

    ``Archive.metadata_keys`` is an exhaustive enumeration of M on
    old-scheme archives too, so the M bucket must be authoritative and
    must agree with ``zim_browse(mode="walk")`` on the same server.
    """
    from libzim.reader import Archive

    expected_keys = list(Archive(str(climate_zim)).metadata_keys)
    assert len(expected_keys) == 12, expected_keys

    listing = climate_ops.list_namespaces_data(str(climate_zim))
    bucket = listing["namespaces"]["M"]
    assert bucket["total"] == len(expected_keys)
    assert bucket["is_authoritative"] is True

    walk = climate_ops.walk_namespace_data(
        str(climate_zim), "M", cursor_state=None, limit=50
    )
    assert len({row["path"] for row in walk["results"]}) == bucket["total"]
