"""Regression tests for the search / title-promotion / intent review lane.

Each test pins a defect the review found in the v3 field-defect branch:
the rendered footer ignoring the dedup resume point, cache keys not bumped
alongside their payload change, "City, State" titles inverting into person
names, the typo sweep running unbounded, the unconditional "about" peel and
the archive-hint term strip on a non-routed call.
"""

import re
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# search.py — the rendered footer must advance by the dedup resume point
# ---------------------------------------------------------------------------


def test_rendered_footer_advances_by_source_consumed(tmp_path) -> None:
    """The markdown footer is what the model pages with; it must match the
    cursor. A deduped page mints a cursor, so the ``source_consumed``
    correction previously sat on an unreachable branch and the footer
    replayed the previous page's last row."""
    from tests.zim_stubs import make_archive_stub, make_ops, make_search_stub

    ops = make_ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")
    entry_ids = [
        "C/quiz/001214_3.htm",
        "C/quiz/001214_3.htm?quiz=1",
        "C/quiz/000249_49.htm",
        "C/quiz/007617_46.htm",
        "C/quiz/007617_46.htm?quiz=1",
        "C/quiz/000123_9.htm",
    ]
    with patch("openzim_mcp.zim_operations.Searcher") as searcher:
        searcher.return_value.search.return_value = make_search_stub(entry_ids)
        page1, _ = ops._perform_search(
            make_archive_stub(), "quiz", 2, 0, validated_path=zim_file
        )

    assert page1["page_info"]["source_consumed"] == 3
    assert "pass `offset=3` for the next page" in ops._format_search_text(page1)


def test_rendered_footer_unchanged_without_dedup(tmp_path) -> None:
    """A page that collapsed nothing keeps the plain ``offset + limit``
    footer — the correction must not perturb the common case."""
    from tests.zim_stubs import make_archive_stub, make_ops, make_search_stub

    ops = make_ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")
    with patch("openzim_mcp.zim_operations.Searcher") as searcher:
        searcher.return_value.search.return_value = make_search_stub(
            ["C/a.htm", "C/b.htm", "C/c.htm", "C/d.htm"]
        )
        page, _ = ops._perform_search(
            make_archive_stub(), "quiz", 2, 0, validated_path=zim_file
        )

    assert "source_consumed" not in page["page_info"]
    assert "pass `offset=2` for the next page" in ops._format_search_text(page)


# ---------------------------------------------------------------------------
# search.py — cache keys must move when their payload shape moves
# ---------------------------------------------------------------------------


_SEARCH_SRC = Path("openzim_mcp/zim/search.py").read_text(encoding="utf-8")

# The pre-3.0.1 spellings. Each of these payloads changed in the v3
# field-defect pass (dedup + ``page_info.source_consumed``, the
# ``_snippet_query`` anchoring, ``total_is_lower_bound``, the widened
# ``exact_ci`` score), so a cache persisted by 3.0.0 must not satisfy them.
_STALE_SEARCH_KEYS = (
    'f"search_v2b:{validated_path}:"',
    'f"search_filtered:{validated_path}:"',
    'f"search_filtered_v2b:{validated_path}:"',
    'f"find_title:v1:{files[0]}:"',
)


def test_changed_search_payloads_left_their_stale_cache_keys_behind() -> None:
    for stale in _STALE_SEARCH_KEYS:
        assert stale not in _SEARCH_SRC, stale


def test_every_search_cache_key_carries_a_version_token() -> None:
    keys = re.findall(
        r'f"(search[a-z_]*|find_title):[^"]*\{(?:validated_path|files\[0\])\}',
        _SEARCH_SRC,
    )
    assert keys, "no search cache keys found"
    for prefix in keys:
        assert re.search(r"_?v\d", prefix) or f'f"{prefix}:v' in _SEARCH_SRC, prefix
