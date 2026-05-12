"""Tests for the v2.0.0a9 D11/Op6 fix: ``browse_namespace`` fast-rejects
unknown namespace letters.

Live a8 testing showed ``browse namespace Q`` returning an empty
result with ``discovery_method=full_iteration`` — the legacy code path
walked all 27 M entries of a Wikipedia archive looking for a letter
the ZIM spec doesn't define. Even when the walk returned in finite
time (because nothing matched), it was the same path the D2 fix
specifically called out as slow and memory-hostile. The a9 fix
rejects unknown letters before any iteration starts and surfaces a
structured ``bad_namespace`` reason so the model's footer renders a
recovery hint instead of a misleading "no results" message.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


@pytest.fixture
def server(test_config: OpenZimMcpConfig):
    srv = OpenZimMcpServer(test_config)
    srv.zim_operations.path_validator = MagicMock()
    srv.zim_operations.path_validator.validate_path.side_effect = lambda p: p
    srv.zim_operations.path_validator.validate_zim_file.side_effect = lambda p: p
    return srv


def test_unknown_namespace_returns_bad_namespace_reason(server):
    """``browse namespace Q`` returns an empty result tagged with
    ``_meta.reason='bad_namespace'`` — no archive open, no iteration."""
    # Even with no archive open at all, the reject path must return
    # cleanly. Patch zim_archive to raise if it's called; the fix
    # should never reach it.
    with patch(
        "openzim_mcp.zim_operations.zim_archive",
        side_effect=AssertionError(
            "browse_namespace_data must reject unknown namespaces BEFORE opening the archive"
        ),
    ):
        result = server.zim_operations.browse_namespace_data(
            "/zim/test.zim", "Q", limit=10, offset=0
        )
    assert result["results"] == []
    assert result["total"] == 0
    assert result["done"] is True
    assert result["discovery_method"] == "rejected_unknown_namespace"
    # The bad_namespace reason drives the empty-result footer's
    # recovery hint ("Try `list_namespaces` to see valid options.").
    assert result["_meta"]["reason"] == "bad_namespace"


def test_known_namespace_falls_through_to_normal_path(server):
    """Known letters (C, M, W, X, A, I, -) do NOT short-circuit; they
    flow into the normal browse path so existing behaviour is preserved.
    """
    fake_archive = MagicMock()
    fake_archive.has_new_namespace_scheme = False
    fake_archive.entry_count = 0
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_open:
        mock_open.return_value.__enter__.return_value = fake_archive
        result = server.zim_operations.browse_namespace_data(
            "/zim/test.zim", "M", limit=10, offset=0
        )
    # We don't care about the actual entries (none, since the mock
    # archive is empty); we care that the reject path DIDN'T fire and
    # the call went through to the archive layer.
    assert result["_meta"].get("reason") != "bad_namespace"


def test_lowercase_unknown_namespace_rejected(server):
    """``browse namespace q`` (lowercase) canonicalises to ``Q``, then
    fast-rejects same as the uppercase form."""
    with patch(
        "openzim_mcp.zim_operations.zim_archive",
        side_effect=AssertionError("must not open archive for unknown namespace"),
    ):
        result = server.zim_operations.browse_namespace_data(
            "/zim/test.zim", "q", limit=10, offset=0
        )
    assert result["_meta"]["reason"] == "bad_namespace"


def test_long_form_unknown_namespace_rejected(server):
    """Long-form aliases that don't map to a known letter
    (``"weird-thing"``) are rejected; the canonicaliser passes them
    through unchanged and the reject path catches them."""
    with patch(
        "openzim_mcp.zim_operations.zim_archive",
        side_effect=AssertionError(
            "must not open archive for unknown long-form namespace"
        ),
    ):
        result = server.zim_operations.browse_namespace_data(
            "/zim/test.zim", "weird-thing", limit=10, offset=0
        )
    assert result["_meta"]["reason"] == "bad_namespace"
