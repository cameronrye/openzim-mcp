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

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.error_messages import get_error_config
from openzim_mcp.exceptions import (
    OpenZimMcpArchiveNameError,
    OpenZimMcpArchivePathError,
    OpenZimMcpSecurityError,
)
from openzim_mcp.security import PathValidator
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


# ---------------------------------------------------------------------------
# D03 — a bare archive name is resolved, or reported as not found; never as a
# security block
# ---------------------------------------------------------------------------


def test_d03_bare_name_resolves_against_allowed_directories(temp_dir: Path) -> None:
    """The exact ``loaded_archives[].name`` string zim_health publishes must
    be usable as ``zim_file_path``."""
    target = temp_dir / "medlineplus.zim"
    target.write_bytes(b"ZIM\x04")
    validator = PathValidator([str(temp_dir)])

    assert validator.validate_path("medlineplus.zim") == target.resolve()


def test_d03_bare_name_matches_a_nested_archive(temp_dir: Path) -> None:
    """``list_zim_files`` walks ``**/*.zim``; a bare name must match the same
    set, not just the top level."""
    nested = temp_dir / "sub" / "deep.zim"
    nested.parent.mkdir()
    nested.write_bytes(b"ZIM\x04")
    validator = PathValidator([str(temp_dir)])

    assert validator.validate_path("deep.zim") == nested.resolve()
    assert validator.validate_path("sub/deep.zim") == nested.resolve()


def test_d03_ambiguous_bare_name_is_rejected_as_not_resolvable(
    temp_dir: Path,
) -> None:
    """Two archives sharing a basename (the test corpus itself ships
    withns/small.zim and nons/small.zim) must not be guessed between."""
    for sub in ("a", "b"):
        (temp_dir / sub).mkdir()
        (temp_dir / sub / "small.zim").write_bytes(b"ZIM\x04")
    validator = PathValidator([str(temp_dir)])

    with pytest.raises(OpenZimMcpArchiveNameError, match="2 loaded archives"):
        validator.validate_path("small.zim")


def test_d03_unmatched_relative_name_is_not_found_not_security(
    temp_dir: Path,
) -> None:
    validator = PathValidator([str(temp_dir)])

    for name in ("ghost.zim", "zim/ghost.zim", "superuser"):
        with pytest.raises(OpenZimMcpArchiveNameError) as info:
            validator.validate_path(name)
        assert "did not match any loaded archive" in str(info.value), name
        assert "outside allowed directories" not in str(info.value), name
        # Still an archive-path failure for every broad handler upstream.
        assert isinstance(info.value, OpenZimMcpArchivePathError)


def test_d03_absolute_and_traversal_inputs_keep_the_security_framing(
    temp_dir: Path,
) -> None:
    validator = PathValidator([str(temp_dir)])

    with pytest.raises(OpenZimMcpSecurityError, match="outside allowed directories"):
        validator.validate_path("/etc/passwd")
    with pytest.raises(OpenZimMcpSecurityError, match="suspicious pattern"):
        validator.validate_path("../ghost.zim")


def test_d03_name_error_renders_a_not_found_template_pointing_at_paths() -> None:
    err = OpenZimMcpArchiveNameError("Path did not match any loaded archive: x.zim")

    config = get_error_config(err, operation="zim_browse")

    assert config is not None
    assert config.title == "Archive Not Found"
    assert "security" not in (config.title + config.issue).lower()
    assert any("loaded_archives[].path" in s for s in config.steps), config.steps
    # zim_browse requires the parameter: no omission advice (D02 contract).
    assert not _omission_steps(config)


def test_d03_ops_layer_prologue_accepts_a_bare_name(temp_dir: Path) -> None:
    """``_validate_zim_path`` is the prologue every domain mixin runs, so
    zim_metadata / zim_browse / zim_get all inherit the resolution."""
    (temp_dir / "only.zim").write_bytes(b"ZIM\x04")
    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    server = OpenZimMcpServer(config)

    resolved = server.zim_operations._validate_zim_path("only.zim")

    assert resolved == (temp_dir / "only.zim").resolve()
