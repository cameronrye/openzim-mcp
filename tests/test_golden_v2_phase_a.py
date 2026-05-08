"""Phase A golden-file regression test (Phase A items #1, #2, #5)."""

import os
from pathlib import Path

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.zim_operations import ZimOperations

GOLDEN_DIR = Path(__file__).parent / "golden"
REGENERATE = os.environ.get("REGENERATE_GOLDEN", "").lower() in ("1", "true", "yes")


def _assert_golden(name: str, body: str) -> None:
    """Assert ``body`` matches the saved golden, or regenerate when REGENERATE=1.

    Both sides are normalized to ``\\n`` line endings so the test passes on
    Windows checkouts where ``core.autocrlf=true`` rewrote the golden files.
    """
    path = GOLDEN_DIR / name
    if REGENERATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write with explicit LF newlines so regenerating on any platform
        # produces the same on-disk bytes.
        path.write_text(body, newline="\n")
        return
    if not path.exists():
        pytest.skip(
            f"golden file {name} not found; "
            f"run with REGENERATE_GOLDEN=1 to create it."
        )
    # Read in binary mode to bypass platform-specific newline translation,
    # then normalize CRLF→LF before comparing.
    expected = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    body_normalized = body.replace("\r\n", "\n")
    assert body_normalized == expected, (
        f"golden mismatch for {name}; "
        f"if intentional, regenerate with: "
        f"REGENERATE_GOLDEN=1 uv run pytest tests/test_golden_v2_phase_a.py"
    )


@pytest.fixture(scope="module")
def runner(v2_phase_a_zim):
    """Construct a SimpleToolsHandler pointing at the fixture archive.

    Uses the same construction pattern as TestListZimFilesNameFilter
    in test_integration.py and TestGetBinaryEntryDataMeta in
    test_content_tools.py.
    """
    zim_dir = str(v2_phase_a_zim.parent)
    config = OpenZimMcpConfig(
        allowed_directories=[zim_dir],
        tool_mode="simple",
        cache=CacheConfig(enabled=True, max_size=20, ttl_seconds=300),
        content=ContentConfig(
            max_content_length=10000,
            snippet_length=200,
        ),
        logging=LoggingConfig(level="WARNING"),
    )
    path_validator = PathValidator(config.allowed_directories)
    cache = OpenZimMcpCache(config.cache)
    content_processor = ContentProcessor(snippet_length=config.content.snippet_length)
    zim_ops = ZimOperations(config, path_validator, cache, content_processor)
    handler = SimpleToolsHandler(zim_ops)

    class _Runner:
        def __init__(self, h, zim_path):
            self._handler = h
            self._zim_path = str(zim_path)

        def zim_query(self, query, options=None):
            return self._handler.handle_zim_query(
                query,
                zim_file_path=self._zim_path,
                options=options or {},
            )

    return _Runner(handler, v2_phase_a_zim)


@pytest.mark.parametrize(
    "query,golden_name",
    [
        ("tell me about Einstein", "compact_einstein.txt"),
        ("tell me about PlainArticle", "compact_plain.txt"),
        ("tell me about MultiTable", "compact_multitable.txt"),
    ],
)
def test_golden_compact(runner, query, golden_name):
    """Phase A compact-mode output is stable across runs."""
    body = runner.zim_query(query, options={"compact": True})
    _assert_golden(golden_name, body)


def test_golden_compact_long_article_truncated(runner):
    """LongArticle compact output is truncated and stable."""
    body = runner.zim_query("tell me about LongArticle", options={"compact": True})
    _assert_golden("compact_long_article.txt", body)
