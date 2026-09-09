"""A title warc2zim cut short must not stand in for the article's name.

v3.3.1 field report, fid 70. warc2zim truncates a scraped ``<title>`` at a
curly apostrophe, so on the shipped MedlinePlus archive::

    entry.title == 'Alzheimer'      body <h1> == "Alzheimer's Disease"
    entry.title == 'Meniere'        body <h1> == "Meniere's Disease"

Four of five rows for ``alzheimer disease`` then carry the identical title
"Alzheimer" — the topic page, the genetics page, the caregivers page and
the translations page, indistinguishable in a result list. And because a
truncated title still scores an exact 1.0 title match, ``sartre-p``
("Sartre's Political Philosophy", stored as "Sartre") outranked the real
overview article.

The fuller name is already in hand. Every search row renders the document
to markdown to build its snippet, that render is cached, and it opens with
the page's ``# <h1>``. Reading the first line of a render the row has just
produced costs nothing; the alternative — a second body read per row — is
what kept this open.

Only a strict prefix is upgraded. A title that merely differs from the H1
is a different editorial choice, not a truncation, and overriding it would
replace the archive's own naming with the page's typography.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest
from libzim.writer import Creator

from openzim_mcp.zim_operations import ZimOperations
from tests.conftest_v2_fixtures import _HtmlItem, make_zim_ops

HOST = "medlineplus.gov"


def _page(h1: str, body: str) -> str:
    return f"<html><body><article><h1>{h1}</h1><p>{body}</p></article></body></html>"


# (path, stored title, body H1)
PAGES = [
    # The reported shape: warc2zim cut the title at the curly apostrophe.
    (
        f"{HOST}/alzheimersdisease.html",
        "Alzheimer",
        "Alzheimer&#x27;s Disease",
        "Alzheimer's disease is the most common cause of dementia in older adults.",
    ),
    (
        f"{HOST}/alzheimerscaregivers.html",
        "Alzheimer",
        "Alzheimer&#x27;s Caregivers",
        "A caregiver gives care to someone with Alzheimer's who needs help.",
    ),
    # Control: a stored title that is NOT a prefix of the H1. The archive
    # chose a different name on purpose; nothing should override it.
    (
        f"{HOST}/dementia.html",
        "Dementia: MedlinePlus Medical Encyclopedia",
        "About Dementia",
        "Dementia is a loss of brain function occurring with certain diseases.",
    ),
    # Control: stored title and H1 already agree.
    (
        f"{HOST}/asthma.html",
        "Asthma",
        "Asthma",
        "Asthma is a chronic disease affecting the airways of the lungs.",
    ),
]


@pytest.fixture(scope="module")
def truncated_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("fr-truncated-titles")
    out_path = out_dir / "medlineplus_like.zim"
    with Creator(out_path).config_indexing(True, "eng") as creator:
        for path, title, h1, body in PAGES:
            creator.add_item(_HtmlItem(path, title, _page(h1, body)))
        creator.set_mainpath(f"{HOST}/asthma.html")
    return out_path


@pytest.fixture(scope="module")
def ops(truncated_zim: Path) -> ZimOperations:
    return make_zim_ops(str(truncated_zim.parent))


def _titles(ops: ZimOperations, zim: Path, query: str) -> Dict[str, str]:
    payload = ops.search_zim_file_data(str(zim), query, limit=10)
    return {r["path"]: r["title"] for r in payload["results"]}


# ---------------------------------------------------------------------------
# The truncation is repaired from the page's own H1
# ---------------------------------------------------------------------------


def test_a_truncated_title_is_completed_from_the_body(ops, truncated_zim):
    titles = _titles(ops, truncated_zim, "alzheimer")

    shown = titles.get(f"{HOST}/alzheimersdisease.html")
    assert shown == "Alzheimer's Disease", titles


def test_two_pages_sharing_a_truncated_title_become_distinguishable(ops, truncated_zim):
    """The reported symptom: rows that a reader cannot tell apart."""
    titles = _titles(ops, truncated_zim, "alzheimer")

    disease = titles.get(f"{HOST}/alzheimersdisease.html")
    caregivers = titles.get(f"{HOST}/alzheimerscaregivers.html")
    assert disease and caregivers, titles
    assert disease != caregivers, titles


# ---------------------------------------------------------------------------
# ...and nothing else is touched
# ---------------------------------------------------------------------------


def test_a_title_that_is_not_a_prefix_is_left_alone(ops, truncated_zim):
    """The archive named this page differently on purpose. A rule that
    preferred the H1 whenever they disagreed would replace the archive's
    own naming with the page's typography."""
    titles = _titles(ops, truncated_zim, "dementia")

    assert (
        titles.get(f"{HOST}/dementia.html")
        == "Dementia: MedlinePlus Medical Encyclopedia"
    ), titles


def test_a_title_that_already_matches_is_unchanged(ops, truncated_zim):
    titles = _titles(ops, truncated_zim, "asthma")

    assert titles.get(f"{HOST}/asthma.html") == "Asthma", titles


def test_no_row_loses_its_title(ops, truncated_zim):
    """Paired with the upgrades above: "different from before" must not be
    reachable by emptying the field."""
    titles = _titles(ops, truncated_zim, "alzheimer")

    assert titles, "no results at all"
    assert all(t.strip() for t in titles.values()), titles


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stored,h1,expected",
    [
        ("Alzheimer", "Alzheimer's Disease", "Alzheimer's Disease"),
        ("Meniere", "Meniere's Disease", "Meniere's Disease"),
        ("Sartre", "Sartre's Political Philosophy", "Sartre's Political Philosophy"),
        # Equal — nothing to add.
        ("Asthma", "Asthma", "Asthma"),
        # Not a prefix — a different name, not a truncation.
        ("About Dementia", "Dementia Overview", "About Dementia"),
        # The H1 is SHORTER; the stored title is the fuller one.
        ("Asthma in Children", "Asthma", "Asthma in Children"),
        # Too short to be a meaningful prefix: "A" prefixes almost anything.
        ("A", "A Very Different Article", "A"),
        # No H1 at all.
        ("Alzheimer", "", "Alzheimer"),
    ],
)
def test_only_a_real_truncation_is_repaired(stored: str, h1: str, expected: str):
    from openzim_mcp.zim.content import completed_title

    assert completed_title(stored, h1) == expected


def test_the_h1_is_read_from_rendered_markdown_not_raw_html():
    """The render is what the row already has, and it is plain: highlighting
    happens later, per query, so the cached text carries no emphasis to
    strip. Pinned because reading raw HTML here would mean a second body
    read per row — the cost that kept this finding open."""
    from openzim_mcp.zim.content import leading_h1

    assert leading_h1("#  Alzheimer's Disease \n\nAlso called: AD") == (
        "Alzheimer's Disease"
    )
    assert leading_h1("## Summary\n\nNot a leading H1.") == ""
    assert leading_h1("") == ""
    # A heading further down is a SECTION, not the page's name. Scanning for
    # one would let "## Summary … # Related Issues" rename the article after
    # its own boilerplate — so the match is anchored at the top.
    assert leading_h1("## Summary\n\nProse.\n\n# Related Issues\n") == ""
