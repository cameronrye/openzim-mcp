"""v3.0.0 field-defect fixes — ``errors`` cluster.

Regressions from the 2026-08-19 real-world sweep, error-surface slice:
recovery advice that names parameters a tool cannot omit (D02), a bare
archive name reported as a security block (D03), an ``invalid_mode``
promise the input schema made unreachable (D04), a browse description
that disagreed with its own soft-reject (D05), undocumented per-mode
``limit`` bounds (D06), an uncapped ``zim_search`` query (D59), an
uncapped ``Technical Details`` echo (D60), and tab/newline surviving
``sanitize_context_for_error`` (D61).
"""

from __future__ import annotations

from pathlib import Path

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.error_messages import get_error_config
from openzim_mcp.exceptions import OpenZimMcpArchivePathError
from openzim_mcp.server import OpenZimMcpServer

_GHOST = OpenZimMcpArchivePathError("File does not exist: /archives/ghost.zim")


def _omission_steps(config) -> list[str]:
    return [s for s in config.steps if "Omit `zim_file_path`" in s]


# ---------------------------------------------------------------------------
# D02 — "Omit `zim_file_path`" advice only where the tool can honour it
# ---------------------------------------------------------------------------


def test_d02_required_param_tools_are_not_told_to_omit_it() -> None:
    """zim_metadata / zim_browse / zim_get / zim_links / zim_get_section
    declare ``zim_file_path`` as a required schema field; following "omit
    it" advice there yields a raw pydantic ``Field required`` error."""
    for operation in (
        "zim_metadata",
        "zim_browse",
        "zim_get",
        "zim_links",
        "zim_get_section",
    ):
        config = get_error_config(_GHOST, operation=operation, count_archives=lambda: 1)
        assert config is not None
        assert config.title == "Archive Not Available"
        assert not _omission_steps(config), (operation, config.steps)
        # The archive-listing pointer survives the parameterisation.
        assert any("list available ZIM files" in s for s in config.steps)


def test_d02_omittable_tools_advertise_omission_only_for_a_single_archive() -> None:
    for operation in ("zim_query", "zim_search", "zim_health"):
        config = get_error_config(_GHOST, operation=operation, count_archives=lambda: 1)
        assert config is not None
        (step,) = _omission_steps(config)
        assert "only loaded archive" in step, step


def test_d02_multiple_archives_loaded_means_no_auto_select_claim() -> None:
    config = get_error_config(_GHOST, operation="zim_search", count_archives=lambda: 2)
    assert config is not None
    assert not _omission_steps(config), config.steps
    assert any("2 archives are loaded" in s for s in config.steps), config.steps


def test_d02_unknown_archive_count_uses_conditional_wording() -> None:
    config = get_error_config(_GHOST, operation="zim_query")
    assert config is not None
    (step,) = _omission_steps(config)
    assert "exactly one archive is loaded" in step, step


def test_d02_counting_failure_degrades_to_conditional_wording() -> None:
    def _boom() -> int:
        raise RuntimeError("listing failed")

    config = get_error_config(_GHOST, operation="zim_search", count_archives=_boom)
    assert config is not None
    (step,) = _omission_steps(config)
    assert "exactly one archive is loaded" in step, step


def test_d02_legacy_call_shape_still_resolves_the_archive_template() -> None:
    """Positional-only callers (and the existing tests) keep working."""
    config = get_error_config(_GHOST)
    assert config is not None
    assert config.title == "Archive Not Available"


def test_d02_server_threads_operation_and_archive_count(temp_dir: Path) -> None:
    """End to end through ``_create_enhanced_error_message``: the rendered
    envelope for a required-param tool never advertises omission, and the
    omittable tool sees the real archive count."""
    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    server = OpenZimMcpServer(config)

    msg = server._create_enhanced_error_message("zim_metadata", _GHOST, "Path: x")
    assert "Omit `zim_file_path`" not in msg, msg

    # Zero archives loaded: nothing to auto-select, so no omission claim.
    msg = server._create_enhanced_error_message("zim_search", _GHOST, "Path: x")
    assert "Omit `zim_file_path`" not in msg, msg

    (temp_dir / "only.zim").write_bytes(b"ZIM\x04")
    msg = server._create_enhanced_error_message("zim_search", _GHOST, "Path: x")
    assert "Omit `zim_file_path` entirely to auto-select the only loaded archive" in msg
