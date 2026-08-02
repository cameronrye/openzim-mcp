"""An unusable ZIM archive must never be reported as a bad argument.

P12 split ``OpenZimMcpValidationError`` out ahead of the broad ``except
Exception`` at six intent handlers so a genuine limit-range rejection stops
rendering as ``**Article not found**``. But ``PathValidator.validate_zim_file``
raises that same type for ``File does not exist`` / ``Path is not a file`` /
``File is not a ZIM file`` / ``Failed to resolve file path``, so a hallucinated
archive name started rendering as an out-of-range argument — complete with
"retry with a smaller ``limit``" advice on four handlers that accept no
``limit`` at all, and a "retry with no extra options" bullet that loops forever
against a nonexistent file.

The fix refines the TYPE (never string-matching): the archive-level failures
raise :class:`OpenZimMcpArchivePathError`, a subclass, which each handler
re-raises so ``handle_zim_query``'s catch-all can emit the envelope that lists
the archives that really are loaded.
"""

from unittest.mock import MagicMock

import pytest

from openzim_mcp.exceptions import (
    OpenZimMcpArchivePathError,
    OpenZimMcpValidationError,
)
from openzim_mcp.simple_tools import SimpleToolsHandler

# (query, ZimOperations attribute the handler calls, accepts a ``limit``?)
INTENT_SITES = [
    ("show structure of Biology", "get_article_structure", False),
    ("table of contents for Biology", "get_table_of_contents", False),
    ("summary of Biology", "get_entry_summary", False),
    ("links in Biology", "extract_article_links", True),
    ("get article Biology", "get_zim_entry", False),
    ("articles related to Biology", "get_related_articles", True),
]


def _ops() -> MagicMock:
    ops = MagicMock()
    ops.list_zim_files_data.return_value = [
        {"path": "/archives/wikipedia.zim"},
        {"path": "/archives/wiktionary.zim"},
    ]
    ops.config.meta.footer_enabled = False
    return ops


def test_archive_path_error_is_a_validation_error() -> None:
    """Subclassing keeps every existing broad handler working unchanged."""
    assert issubclass(OpenZimMcpArchivePathError, OpenZimMcpValidationError)


def test_validate_zim_file_raises_the_archive_subclass(tmp_path) -> None:
    """The four archive-level rejections carry the refined type."""
    from openzim_mcp.security import PathValidator

    validator = PathValidator([str(tmp_path)])

    with pytest.raises(OpenZimMcpArchivePathError):
        validator.validate_zim_file(tmp_path / "ghost.zim")

    with pytest.raises(OpenZimMcpArchivePathError):
        validator.validate_zim_file(tmp_path)  # a directory, not a file

    not_a_zim = tmp_path / "notes.txt"
    not_a_zim.write_text("x")
    with pytest.raises(OpenZimMcpArchivePathError):
        validator.validate_zim_file(not_a_zim)


@pytest.mark.parametrize("query,attr,_limit_capable", INTENT_SITES)
def test_missing_archive_is_not_rendered_as_an_invalid_argument(
    query: str, attr: str, _limit_capable: bool
) -> None:
    ops = _ops()
    getattr(ops, attr).side_effect = OpenZimMcpArchivePathError(
        "File does not exist: /archives/ghost.zim"
    )
    handler = SimpleToolsHandler(ops)
    out = handler.handle_zim_query(query, "/archives/ghost.zim")

    assert isinstance(out, str)
    assert "**Invalid Request**" not in out, out[:500]
    assert "smaller `limit`" not in out, out[:500]
    assert "out of range" not in out, out[:500]
    # The recovery must point at the archive, listing the real ones.
    assert "wikipedia.zim" in out, out[:500]


@pytest.mark.parametrize("query,attr,limit_capable", INTENT_SITES)
def test_out_of_range_argument_still_renders_invalid_request(
    query: str, attr: str, limit_capable: bool
) -> None:
    """The original P12 fix must survive the type refinement."""
    ops = _ops()
    getattr(ops, attr).side_effect = OpenZimMcpValidationError(
        "limit must be between 1 and 500 (provided: 1000)"
    )
    handler = SimpleToolsHandler(ops)
    out = handler.handle_zim_query(query, "/archives/wikipedia.zim")

    assert isinstance(out, str)
    assert "**Invalid Request**" in out, out[:500]
    assert "Article not found" not in out, out[:500]
    assert "1 and 500" in out, out[:500]


@pytest.mark.parametrize("query,attr,limit_capable", INTENT_SITES)
def test_limit_advice_only_where_a_limit_exists(
    query: str, attr: str, limit_capable: bool
) -> None:
    """Four of the six handlers take no ``limit``; do not tell them to shrink
    one."""
    ops = _ops()
    getattr(ops, attr).side_effect = OpenZimMcpValidationError(
        "kind must be one of internal, external, all (provided: bogus)"
    )
    handler = SimpleToolsHandler(ops)
    out = handler.handle_zim_query(query, "/archives/wikipedia.zim")

    assert isinstance(out, str)
    assert "**Invalid Request**" in out, out[:500]
    if limit_capable:
        assert "smaller `limit`" in out, out[:500]
    else:
        assert "smaller `limit`" not in out, out[:500]
        assert "takes no `limit`" in out, out[:500]


@pytest.mark.parametrize(
    "message",
    [
        "Path is not a file: /archives/somedir",
        "File is not a ZIM file: /archives/notes.txt",
        "Failed to resolve file path: /archives/broken.zim",
    ],
)
def test_archive_path_error_still_resolves_an_error_template(message: str) -> None:
    """``ERROR_CONFIGS`` is keyed by EXACT type, so the new subclass needs its
    own entry — otherwise these three shapes resolve to no template at all."""
    from openzim_mcp.error_messages import get_error_config

    config = get_error_config(OpenZimMcpArchivePathError(message))
    assert config is not None, message
    assert config.title == "Archive Not Available", config.title
