"""Regression guard: per-tool description Markdown files are packaged.

Phase F tools read their LLM-facing description from a committed
sibling ``.md`` file at import time. If ``pyproject.toml`` loses the
``tools/*.md`` glob from ``[tool.setuptools.package-data]`` (or
someone adds a new tool whose description file isn't covered by the
glob), the wheel will install without the file and the tool's module
import will ``FileNotFoundError``.

This test pins the packaging invariant by reading the file through
``importlib.resources`` — which is what the runtime path uses — so a
broken wheel produces a clean, actionable failure here instead of a
mysterious crash at first MCP-server boot.
"""

from __future__ import annotations

import importlib.resources as resources

import pytest


def test_zim_query_description_packaged() -> None:
    """The b13 zim_query description ships verbatim with the wheel."""
    contents = ""
    try:
        ref = resources.files("openzim_mcp.tools").joinpath("zim_query_description.md")
        contents = ref.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as e:
        pytest.fail(
            "zim_query_description.md is not packaged with openzim_mcp.tools. "
            "Likely cause: pyproject.toml [tool.setuptools.package-data] does "
            "not include 'tools/*.md'. "
            f"Original error: {e}"
        )

    # Sanity-check the file isn't truncated. b13's docstring is ~5 KB; if
    # the file shipped truncated the wheel would silently pass a too-short
    # description to the MCP server.
    assert len(contents) > 1000, (
        f"zim_query_description.md suspiciously small ({len(contents)} bytes); "
        "did the file ship truncated?"
    )

    # Smoke-check the content for a marker phrase known to be in b13's
    # docstring — protects against a future commit accidentally writing
    # garbage into the file.
    assert "Query ZIM archives" in contents
