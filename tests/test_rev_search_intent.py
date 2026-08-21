"""Regression tests for the search / title-promotion / intent review lane.

Each test pins a defect the review found in the v3 field-defect branch:
the rendered footer ignoring the dedup resume point, cache keys not bumped
alongside their payload change, "City, State" titles inverting into person
names, the typo sweep running unbounded, the unconditional "about" peel and
the archive-hint term strip on a non-routed call.
"""

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
