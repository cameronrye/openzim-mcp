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

import json
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


# ---------------------------------------------------------------------------
# D04 — invalid `mode` reaches the handler's invalid_mode envelope over the wire
# ---------------------------------------------------------------------------


def _text(result) -> str:
    from mcp_types import TextContent

    return "".join(b.text for b in result.content if isinstance(b, TextContent))


@pytest.mark.asyncio
async def test_d04_invalid_mode_is_a_structured_envelope_over_the_wire(
    tmp_path: Path,
) -> None:
    """The description promises "Invalid `mode` returns `invalid_mode`". A
    ``Literal`` annotation let pydantic reject the call first, leaking
    ``zim_browseArguments ... errors.pydantic.dev`` text instead."""
    from tests.test_mcp_session import advanced_session

    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(
            "zim_browse",
            {
                "zim_file_path": str(tmp_path / "a.zim"),
                "namespace": "M",
                "mode": "bogus",
            },
        )

    assert result.is_error is True
    text = _text(result)
    assert "pydantic" not in text, text
    payload = json.loads(text)
    assert payload["error"] is True
    assert payload["operation"] == "invalid_mode"
    assert "'bogus'" in payload["message"]


def test_d04_browse_mode_schema_still_advertises_the_enum(tmp_path: Path) -> None:
    """Dropping ``Literal`` must not drop the wire enum: the prototype-parity
    snapshot (and dispatch quality) depend on clients seeing the two values."""
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode="advanced")
    server = OpenZimMcpServer(config)
    mode_schema = server.mcp._tool_manager._tools["zim_browse"].parameters[
        "properties"
    ]["mode"]

    assert mode_schema == {
        "default": "page",
        "enum": ["page", "walk"],
        "title": "Mode",
        "type": "string",
    }


# ---------------------------------------------------------------------------
# D05 — the browse description documents the unknown-namespace soft reject
# ---------------------------------------------------------------------------


def _browse_errors_section() -> str:
    from openzim_mcp.tools._common import load_description

    text = load_description("zim_browse")
    return text[text.index("ERRORS:") :]


def test_d05_description_documents_the_soft_reject_shape() -> None:
    """namespace.py deliberately soft-rejects an unknown letter with
    ``isError=false`` (pinned by test_browse_namespace_d11_v2a9); the
    ERRORS section claimed an error envelope, so clients branching on
    ``isError`` never saw the reject."""
    errors = _browse_errors_section()

    assert "rejected_unknown_namespace" in errors, errors
    assert "bad_namespace" in errors, errors
    assert "isError=false" in errors, errors
    assert "unknown\n  namespace returns the underlying data-layer error" not in errors


# ---------------------------------------------------------------------------
# D06 — per-mode `limit` bounds are documented and rejected in one style
# ---------------------------------------------------------------------------


def test_d06_description_states_the_per_mode_limit_bounds() -> None:
    from openzim_mcp.tools._common import load_description

    text = load_description("zim_browse")
    params = text[text.index("PARAMETERS:") : text.index("RESPONSE:")]
    limit_line = next(
        ln for ln in params.splitlines() if ln.strip().startswith("limit")
    )
    # Bounds may wrap onto a continuation line; take the line plus the next.
    idx = params.splitlines().index(limit_line)
    limit_text = " ".join(params.splitlines()[idx : idx + 2])

    assert "1-200" in limit_text and "1-500" in limit_text, limit_text
    assert "page" in limit_text and "walk" in limit_text, limit_text


def test_d06_page_and_walk_limit_rejections_share_one_style(temp_dir: Path) -> None:
    """Page mode said "Limit must be between 1 and 200"; walk said "limit
    must be between 1 and 500 (provided: N)". One data-layer style, with
    the offending value echoed, for both."""
    from openzim_mcp.exceptions import OpenZimMcpValidationError

    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    ops = OpenZimMcpServer(config).zim_operations

    with pytest.raises(
        OpenZimMcpValidationError,
        match=r"limit must be between 1 and 200 \(provided: 300\)",
    ):
        ops.browse_namespace_data("any.zim", "C", limit=300)
    with pytest.raises(
        OpenZimMcpValidationError,
        match=r"limit must be between 1 and 500 \(provided: 600\)",
    ):
        ops.walk_namespace_data("any.zim", "C", limit=600)


# ---------------------------------------------------------------------------
# D59 — zim_search shares zim_query's front-door query length cap
# ---------------------------------------------------------------------------


def _register_with_fake_mcp(register, server):
    captured = {}

    class _FakeMcp:
        def tool(self, description=None):
            def deco(fn):
                captured["fn"] = fn
                return fn

            return deco

    server.mcp = _FakeMcp()
    register(server)
    return captured["fn"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fulltext", "title", "suggest"])
async def test_d59_zim_search_rejects_an_oversized_query(mode: str) -> None:
    """A 1 MB query was accepted in every mode and echoed back 1:1 in the
    response's ``query`` field. zim_query caps the same argument at
    ``MAX_QUERY_LENGTH``; the sibling tool must share the bound."""
    from unittest.mock import MagicMock

    from openzim_mcp.constants import MAX_QUERY_LENGTH
    from openzim_mcp.tools import zim_search as zim_search_tool

    server = MagicMock()
    server.rate_limiter.check_rate_limit.return_value = None
    fn = _register_with_fake_mcp(zim_search_tool.register, server)

    result = await fn("x" * (MAX_QUERY_LENGTH + 1), mode=mode, zim_file_path="/a.zim")

    assert result["error"] is True
    assert result["operation"] == "invalid_query"
    assert str(MAX_QUERY_LENGTH) in result["message"]
    # The oversized input must not be echoed back.
    assert len(result["message"]) < 512, len(result["message"])


def test_d59_query_cap_is_one_constant_for_both_tools() -> None:
    from openzim_mcp.constants import MAX_QUERY_LENGTH
    from openzim_mcp.tools.zim_query import MAX_QUERY_LENGTH as query_cap

    assert query_cap == MAX_QUERY_LENGTH == 4096
