"""Tests for replace_oversized_tables (Phase A item #2)."""

import pytest
from bs4 import BeautifulSoup

from openzim_mcp.content_processor import ContentProcessor


@pytest.fixture
def processor() -> ContentProcessor:
    return ContentProcessor()


def _table_html(rows: int, cols: int) -> str:
    body = "".join(
        "<tr>" + "".join("<td>cell</td>" for _ in range(cols)) + "</tr>"
        for _ in range(rows)
    )
    return f"<table>{body}</table>"


def test_small_table_preserved(processor):
    html = f"<div>{_table_html(rows=3, cols=2)}</div>"
    soup = BeautifulSoup(html, "html.parser")
    processor.replace_oversized_tables(soup, row_threshold=8, char_threshold=600)
    assert soup.find("table") is not None
    assert "Table:" not in soup.get_text()


def test_large_row_count_replaced(processor):
    html = f"<div>{_table_html(rows=20, cols=4)}</div>"
    soup = BeautifulSoup(html, "html.parser")
    processor.replace_oversized_tables(soup, row_threshold=8, char_threshold=600)
    assert soup.find("table") is None
    txt = soup.get_text()
    assert "Table 1:" in txt
    assert "20 rows" in txt
    assert "compact=False" in txt


def test_large_char_count_replaced(processor):
    # 5 rows × 5 cells × "padding-text-" * 3 (39 chars/cell) ≈ 975 chars > 600
    html = (
        "<table>"
        + "".join(
            "<tr>"
            + "".join("<td>" + "padding-text-" * 3 + "</td>" for _ in range(5))
            + "</tr>"
            for _ in range(5)
        )
        + "</table>"
    )
    soup = BeautifulSoup(html, "html.parser")
    processor.replace_oversized_tables(soup, row_threshold=8, char_threshold=600)
    assert soup.find("table") is None


def test_multiple_tables_indexed_in_document_order(processor):
    html = (
        f"<div>{_table_html(rows=20, cols=2)}{_table_html(rows=3, cols=2)}"
        f"{_table_html(rows=15, cols=3)}</div>"
    )
    soup = BeautifulSoup(html, "html.parser")
    processor.replace_oversized_tables(soup, row_threshold=8, char_threshold=600)
    tables = soup.find_all("table")
    assert len(tables) == 1
    txt = soup.get_text()
    assert "Table 1:" in txt
    assert "Table 3:" in txt
    assert "Table 2:" not in txt
