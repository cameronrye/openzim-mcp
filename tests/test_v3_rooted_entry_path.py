"""A rooted entry path must not be served by one view and called an attack
by the next.

D17 taught the entry-fetch ladder to try the un-slashed spelling of
``/medlineplus.gov/diabetes.html`` — a leading slash is a plausible client
slip, and ZIM paths are never rooted. But the ladder is reached only after
``reject_path_traversal``, and every sibling surface still calls that guard
first, so the same tool served the body for ``view="full"`` and answered
``view="summary"`` (or the same path inside a batch ``entry_paths``) with
"Rejected suspicious entry path ... absolute prefixes are blocked" —
security-flavoured wording for a path it had just served.

Un-rooting happens before the guard here, so the ``..`` checks are untouched:
only the leading separator is dropped, never a segment.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations

_TOPIC = "medlineplus.gov/diabetes.html"
_ROOTED = "/" + _TOPIC
_TRAVERSAL = "/../../etc/passwd"


@pytest.fixture
def ops(
    test_config: OpenZimMcpConfig,
    path_validator: PathValidator,
    openzim_mcp_cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
) -> ZimOperations:
    return ZimOperations(
        test_config, path_validator, openzim_mcp_cache, content_processor
    )


@pytest.fixture
def zim_file(temp_dir: Path) -> Path:
    """A placeholder file inside the allowed directory; the archive is mocked."""
    path = temp_dir / "corpus.zim"
    path.write_text("x")
    return path


def _archive_with_topic() -> MagicMock:
    """A mock libzim Archive resolving exactly the un-rooted topic spelling."""
    entry = MagicMock()
    entry.is_redirect = False
    entry.path = _TOPIC
    entry.title = "Diabetes"
    item = MagicMock()
    item.mimetype = "text/html"
    item.content = (
        "<html><body><main><h1>Diabetes</h1>"
        "<p>Diabetes is a disease.</p>"
        "<h2>Summary</h2><p>Prose about diabetes.</p>"
        "</main></body></html>"
    ).encode("utf-8")
    item.size = len(item.content)
    entry.get_item.return_value = item

    inst = MagicMock()
    inst.has_new_namespace_scheme = True
    inst.get_entry_by_path.side_effect = lambda p: (
        entry if p == _TOPIC else _raise_missing()
    )
    inst.has_entry_by_path.side_effect = lambda p: p == _TOPIC
    return inst


def _raise_missing() -> None:
    raise KeyError("Cannot find entry")


class TestRootedPathIsServedByEveryContentSurface:
    """The surfaces that share ``reject_path_traversal`` must agree with D17."""

    @patch("openzim_mcp.zim_operations.Archive")
    def test_summary_view_serves_the_rooted_path(
        self, mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
    ) -> None:
        """``zim_get(view="summary")`` rejected what ``view="full"`` served."""
        mock_archive.return_value = _archive_with_topic()

        result = ops.get_entry_summary_data(str(zim_file), _ROOTED)

        assert not result.get("error"), result

    @patch("openzim_mcp.zim_operations.Archive")
    def test_legacy_text_entry_serves_the_rooted_path(
        self, mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
    ) -> None:
        """The text variant rejected it at the boundary, so D17 was dead there."""
        mock_archive.return_value = _archive_with_topic()

        result = ops.get_zim_entry(str(zim_file), _ROOTED)

        assert "Diabetes is a disease." in result

    @patch("openzim_mcp.zim_operations.Archive")
    def test_batch_entry_paths_serve_the_rooted_path(
        self, mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
    ) -> None:
        """A path fetched fine alone must not fail inside ``entry_paths``."""
        mock_archive.return_value = _archive_with_topic()

        results = ops.get_entries_data(
            [{"zim_file_path": str(zim_file), "entry_path": _ROOTED}]
        )

        assert results["results"][0]["success"] is True, results

    @patch("openzim_mcp.zim_operations.Archive")
    def test_binary_entry_serves_the_rooted_path(
        self, mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
    ) -> None:
        """Same slip, same remedy, for the binary fetch."""
        mock_archive.return_value = _archive_with_topic()

        result = ops.get_binary_entry_data(str(zim_file), _ROOTED)

        assert not result.get("error"), result


class TestTraversalIsStillRejected:
    """Un-rooting must not open the shape the D12 guard was written for."""

    def test_rooted_parent_segment_is_still_rejected(
        self, ops: ZimOperations, zim_file: Path
    ) -> None:
        """``/../../etc/passwd`` un-roots to ``../../etc/passwd``, still evil."""
        with pytest.raises(OpenZimMcpArchiveError, match="Rejected suspicious"):
            ops.get_zim_entry(str(zim_file), _TRAVERSAL)

    def test_rooted_parent_segment_is_still_rejected_in_summary(
        self, ops: ZimOperations, zim_file: Path
    ) -> None:
        """The same holds for the summary view."""
        with pytest.raises(OpenZimMcpArchiveError, match="Rejected suspicious"):
            ops.get_entry_summary_data(str(zim_file), _TRAVERSAL)
