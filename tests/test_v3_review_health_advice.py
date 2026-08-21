"""``zim_health``'s archive-path recovery advice describes its own branch.

D02 taught the Archive Not Available template to name only recovery steps
the failing tool can honour, but grouped ``zim_health`` with the tools that
auto-select. Omitting ``zim_file_path`` there does not retry the validation
against the single loaded archive — ``zim_health.py`` branches to
``get_health_data`` and answers a different question entirely.
"""

from __future__ import annotations

from openzim_mcp.error_messages import get_error_config
from openzim_mcp.exceptions import OpenZimMcpArchivePathError

_GHOST = OpenZimMcpArchivePathError("File does not exist: /archives/ghost.zim")


def _omission_step(operation: str, count: int) -> str:
    config = get_error_config(_GHOST, operation=operation, count_archives=lambda: count)
    assert config is not None
    (step,) = [s for s in config.steps if "Omit `zim_file_path`" in s]
    return step


def test_zim_health_omission_step_makes_no_auto_select_promise() -> None:
    assert "auto-select" not in _omission_step("zim_health", 1)


def test_zim_health_omission_step_names_the_answer_it_actually_returns() -> None:
    assert "server-state report" in _omission_step("zim_health", 1)


def test_zim_health_omission_step_is_independent_of_the_archive_count() -> None:
    """The auto-select wording varies with how many archives are loaded;
    the server-state report is the same answer either way."""
    assert _omission_step("zim_health", 1) == _omission_step("zim_health", 3)


def test_zim_health_keeps_an_omission_step_at_all() -> None:
    """``zim_file_path`` really is optional there, so the step stays — only
    its promise changes."""
    assert _omission_step("zim_health", 1).startswith("Omit `zim_file_path`")


def test_auto_select_tools_keep_their_count_sensitive_wording() -> None:
    assert "only loaded archive" in _omission_step("zim_search", 1)
