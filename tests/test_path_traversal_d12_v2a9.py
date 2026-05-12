"""Tests for the v2.0.0a9 D12 fix: ``get_zim_entry`` rejects
path-traversal-shaped inputs with a distinct security message
instead of the generic "Entry not found" + browse remediation hint.

The behaviour is structurally safe in both versions (libzim's path
lookup is sandboxed to the archive's entry table; no filesystem
escape is reachable), but the prior message was misleading to both
operators (no log signal that this was an attack pattern) and to
small models (false advice to "check the path / browse_namespace"
for what is obviously not a real ZIM path).
"""

from __future__ import annotations

import pytest

from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.zim.content import _looks_like_path_traversal


@pytest.mark.parametrize(
    "evil",
    [
        "../../etc/passwd",
        "..\\windows\\system32",
        "/etc/passwd",
        "/absolute/path",
        "..",
        "..%2Fetc/passwd",
        "%2e%2e/secret",
        "%2E%2E/secret",
        "foo/../bar",
        "foo\\..\\bar",
    ],
)
def test_detects_traversal_shape(evil):
    """Each well-known path-traversal pattern is detected."""
    assert _looks_like_path_traversal(evil) is True


@pytest.mark.parametrize(
    "legit",
    [
        "C/Berlin",
        "A/Some_Article",
        "Berlin",
        "M/Title",
        "W/mainPage",
        "Articles/with.dots.in/name",
        "Wikipedia:Manual_of_Style",
        "",
        "Berlin_(disambiguation)",
        "café",  # unicode is fine
    ],
)
def test_legit_entry_paths_pass_through(legit):
    """Real ZIM entry paths must not trip the detector."""
    assert _looks_like_path_traversal(legit) is False


def test_get_zim_entry_rejects_traversal_with_distinct_message(test_config):
    """End-to-end: an attempt to fetch ``../../etc/passwd`` returns a
    security-flavoured error string, not the generic ``Entry not found``."""
    from openzim_mcp.server import OpenZimMcpServer

    server = OpenZimMcpServer(test_config)
    # Bypass file path validation so the error comes from the entry
    # path check, not the file path check.
    from unittest.mock import MagicMock

    server.zim_operations.path_validator = MagicMock()
    server.zim_operations.path_validator.validate_path.side_effect = lambda p: p
    server.zim_operations.path_validator.validate_zim_file.side_effect = lambda p: p

    with pytest.raises(OpenZimMcpArchiveError) as excinfo:
        server.zim_operations.get_zim_entry("/zim/test.zim", "../../etc/passwd")
    msg = str(excinfo.value)
    # Security-flavoured wording, NOT the generic "Entry not found".
    assert "Rejected suspicious entry path" in msg
    assert "Entry not found" not in msg
    # The hint about ZIM path shape is included so a confused (rather
    # than malicious) caller sees how to fix the input.
    assert "namespace-prefixed" in msg
