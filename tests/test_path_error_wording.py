"""Real-world-test regression: a non-matching but in-scope ``zim_file_path``
token (e.g. ``superuser``) was reported with the security-flavoured
"Access denied - Path is outside allowed directories" wording — the same
message used for a genuine ``/etc/passwd`` traversal. That conflates a typo
with an attack and leaks the path-allowlisting mechanism.
"""

from __future__ import annotations

from openzim_mcp.simple_tools import SimpleToolsHandler

_SECURITY = "Access denied - Path is outside allowed directories: {p}"


def test_bare_nonmatching_name_is_not_reported_as_access_denied():
    reason = SimpleToolsHandler._path_failure_reason(
        "superuser",
        _SECURITY.format(p="…/superuser").lower(),
        _SECURITY.format(p="…/superuser"),
    )
    assert "outside allowed directories" not in reason
    assert "did not match any loaded archive" in reason


def test_traversal_path_keeps_the_security_reason():
    reason = SimpleToolsHandler._path_failure_reason(
        "/etc/passwd",
        _SECURITY.format(p="/etc/passwd").lower(),
        _SECURITY.format(p="/etc/passwd"),
    )
    assert "outside allowed directories" in reason


def test_dotdot_traversal_keeps_the_security_reason():
    reason = SimpleToolsHandler._path_failure_reason(
        "../../etc/passwd",
        _SECURITY.format(p="../../etc/passwd").lower(),
        _SECURITY.format(p="../../etc/passwd"),
    )
    assert "outside allowed directories" in reason


def test_non_security_error_passes_through_unchanged():
    reason = SimpleToolsHandler._path_failure_reason(
        "foo", "file does not exist: foo", "File does not exist: foo"
    )
    assert reason == "File does not exist: foo"
