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

import contextlib
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
    # zim_health also accepts omission but does not auto-select — its own
    # wording is pinned by tests/test_v3_review_health_advice.py.
    for operation in ("zim_query", "zim_search"):
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


def test_d03_name_error_template_is_two_whole_steps() -> None:
    """Each step is written as a parenthesised pair of string literals so it
    wraps at the line limit; a dropped comma between the pairs would silently
    fuse both steps into one item that reads as two run-on sentences."""
    from openzim_mcp.error_messages import ERROR_CONFIGS

    steps = ERROR_CONFIGS[OpenZimMcpArchiveNameError].steps

    assert len(steps) == 2, steps
    assert steps[0].startswith("Use `zim_health()`"), steps[0]
    assert steps[0].endswith("verbatim as `zim_file_path`"), steps[0]
    assert steps[1].startswith("Relative names resolve"), steps[1]
    assert steps[1].endswith("the `.zim` extension"), steps[1]


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
    snapshot (and dispatch quality) depend on clients seeing the two values.

    Compared whole rather than by key, so this also pins that ``"page"``
    survives as the declared default — ``schema_slimming`` walks this property
    and drops only ``title``, and a transform that took real defaults with it
    would land here.
    """
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode="advanced")
    server = OpenZimMcpServer(config)
    mode_schema = server.mcp._tool_manager._tools["zim_browse"].parameters[
        "properties"
    ]["mode"]

    assert mode_schema == {
        "default": "page",
        "enum": ["page", "walk"],
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

    assert "1-200" in limit_text, limit_text
    assert "1-500" in limit_text, limit_text
    assert "page" in limit_text, limit_text
    assert "walk" in limit_text, limit_text


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


# ---------------------------------------------------------------------------
# D60 — the rendered "Technical Details" echo is length-bounded like `context`
# ---------------------------------------------------------------------------


def _technical_details(message: str) -> str:
    """The details value: from the marker to the next paragraph break (the
    generic template appends a "**Need Help?**" paragraph after it)."""
    marker = "**Technical Details**: "
    tail = message[message.index(marker) + len(marker) :]
    return tail.split("\n\n", 1)[0]


def test_d60_templated_error_bounds_the_details_echo(temp_dir: Path) -> None:
    """A 1 MB ``entry_path`` produced a ~1.05 MB error body: the data layer's
    "Entry not found: '<path>'" text was redacted but never capped, while
    the sibling ``context`` field was capped at 1024."""
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    server = OpenZimMcpServer(config)
    huge = "a" * 1_048_576
    err = OpenZimMcpArchiveError(
        f"Entry not found: '{huge}'. The entry path may not exist."
    )

    msg = server._create_enhanced_error_message("zim_get", err, f"Path: {huge}")

    details = _technical_details(msg)
    assert len(details) <= 1024 + len("..."), len(details)
    assert details.endswith("..."), details[-40:]
    assert len(msg) < 4096, len(msg)


def test_d60_generic_error_bounds_the_details_echo(temp_dir: Path) -> None:
    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    server = OpenZimMcpServer(config)

    msg = server._create_enhanced_error_message(
        "zim_get", RuntimeError("x" * 50_000), ""
    )

    assert "**Operation Failed**" in msg
    details = _technical_details(msg)
    assert len(details) <= 1024 + len("..."), len(details)
    assert len(msg) < 4096, len(msg)


def test_d60_short_details_are_untouched(temp_dir: Path) -> None:
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    server = OpenZimMcpServer(config)

    msg = server._create_enhanced_error_message(
        "zim_get", OpenZimMcpArchiveError("Archive corrupted"), "Path: x"
    )

    assert msg.endswith("**Technical Details**: Archive corrupted"), msg[-80:]


# ---------------------------------------------------------------------------
# D61 — tab / newline / CR do not survive sanitize_context_for_error
# ---------------------------------------------------------------------------


def test_d61_context_sanitizer_strips_every_c0_control_character() -> None:
    """The docstring promises raw user values "cannot embed control
    characters ... in the response"; the class skipped \\x09, \\x0a, \\x0d,
    so an injected LF split the "**Context**" line of the markdown."""
    from openzim_mcp.security import sanitize_context_for_error

    out = sanitize_context_for_error("Path: foo\n\tbar\r.zim")

    assert "\n" not in out, repr(out)
    assert "\t" not in out, repr(out)
    assert "\r" not in out, repr(out)
    assert "foo" in out, out
    assert "bar" in out, out
    # Every C0 control plus DEL, not just the three the field report named.
    for code in list(range(0x00, 0x20)) + [0x7F]:
        assert chr(code) not in sanitize_context_for_error(f"a{chr(code)}b"), hex(code)


def test_d61_envelope_context_and_message_are_single_line(temp_dir: Path) -> None:
    from openzim_mcp.tools._common import tool_error_response

    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    server = OpenZimMcpServer(config)
    err = OpenZimMcpSecurityError("Access denied - Path is outside allowed directories")

    payload = tool_error_response(
        server, operation="zim_metadata", error=err, context="Path: foo\n\tbar.zim"
    )

    assert "\n" not in payload["context"]
    assert "\t" not in payload["context"]
    context_line = next(
        ln for ln in payload["message"].splitlines() if ln.startswith("**Context**")
    )
    assert "bar.zim" in context_line, context_line


def test_d61_sanitize_input_keeps_its_deliberate_whitespace_carve_out() -> None:
    """``sanitize_input`` cleans multi-line query text and documents its
    newline/tab exemption; only the context sanitizer changes."""
    from openzim_mcp.security import sanitize_input

    assert sanitize_input("line one\n\tline two") == "line one\n\tline two"


# ---------------------------------------------------------------------------
# R2-3 (D61 residual) — control characters do not survive into the
# "**Technical Details**" echo or the server-side ERROR log line
# ---------------------------------------------------------------------------

_C0_AND_DEL = [chr(code) for code in list(range(0x00, 0x20)) + [0x7F]]
_INJECTED_PATH = "/Users/cameron/Developer/zim/foo\n\tbar\r.zim"


def _stray_controls(text: str) -> list[str]:
    """Control characters in ``text`` other than the template's own LFs."""
    return [ch for ch in text if ch in _C0_AND_DEL and ch != "\n"]


def test_r2_3_templated_details_line_is_single_line(temp_dir: Path) -> None:
    """D61 cleaned the ``context`` argument but the exception text was only
    length-truncated: a ``zim_file_path`` of ``foo\\n\\tbar.zim`` came back
    with the raw LF and TAB inside ``**Technical Details**``."""
    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    server = OpenZimMcpServer(config)
    err = OpenZimMcpSecurityError(f"Path contains suspicious pattern: {_INJECTED_PATH}")

    msg = server._create_enhanced_error_message(
        "zim_metadata", err, f"Path: {_INJECTED_PATH}"
    )
    clean = server._create_enhanced_error_message(
        "zim_metadata",
        OpenZimMcpSecurityError("Path contains suspicious pattern: x"),
        "Path: x",
    )

    assert not _stray_controls(msg), repr(msg)
    # No forged extra lines: same structural line count as a clean render.
    assert msg.count("\n") == clean.count("\n"), repr(msg)
    details = msg.splitlines()[-1]
    assert details.startswith("**Technical Details**:"), details
    assert "foo" in details, details
    assert "bar" in details, details


def test_r2_3_generic_details_line_is_single_line(temp_dir: Path) -> None:
    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    server = OpenZimMcpServer(config)

    msg = server._create_enhanced_error_message(
        "zim_get", RuntimeError("boom\n**Operation**: forged\x7f"), ""
    )
    clean = server._create_enhanced_error_message("zim_get", RuntimeError("boom"), "")

    assert "**Operation Failed**" in msg
    assert not _stray_controls(msg), repr(msg)
    assert msg.count("\n") == clean.count("\n"), repr(msg)
    assert "forged" in _technical_details(msg)


def test_r2_3_every_c0_control_and_del_is_stripped_from_details() -> None:
    from openzim_mcp.error_messages import (
        ERROR_CONFIGS,
        format_error_message,
        format_generic_error,
    )

    config = ERROR_CONFIGS[OpenZimMcpSecurityError]
    for ch in _C0_AND_DEL:
        details = f"a{ch}b"
        templated = format_error_message(config, "zim_get", "ctx", details)
        generic = format_generic_error("zim_get", "RuntimeError", "ctx", details)
        assert not _stray_controls(templated), hex(ord(ch))
        assert not _stray_controls(generic), hex(ord(ch))
        # An injected LF must not add a line either.
        assert _technical_details(templated) == "a b", hex(ord(ch))
        assert _technical_details(generic) == "a b", hex(ord(ch))


def test_r2_3_details_are_sanitized_before_the_length_cap() -> None:
    """The 1024 cap applies to the cleaned text, so the ellipsis marker can
    never be preceded by a stray control character."""
    from openzim_mcp.error_messages import _bound_details

    out = _bound_details("x" * 500 + "\n" + "y" * 600)

    assert "\n" not in out, repr(out[490:510])
    assert out.endswith("...")
    assert len(out) <= 1024 + len("...")


@contextlib.contextmanager
def _captured(caplog: pytest.LogCaptureFixture, logger_name: str):
    """Attach caplog's handler to one named logger for the duration.

    ``OpenZimMcpServer`` construction runs ``logging.basicConfig(force=True)``,
    which drops caplog's root handler, so ``caplog.at_level`` alone captures
    nothing once a real server exists in the process.

    Captures at WARNING, not ERROR: caller faults (a security denial, a
    validation rejection) now log at WARNING, and an ``at_level(ERROR)``
    capture discards them silently — the record-shape assertions below would
    then pass by capturing nothing. WARNING still captures ERROR, so the
    server-fault cases are unaffected. The level itself is pinned in
    ``test_v3_field_fixes_logging.py``.
    """
    import logging

    target = logging.getLogger(logger_name)
    target.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=logger_name):
            yield
    finally:
        target.removeHandler(caplog.handler)


def _messages(caplog: pytest.LogCaptureFixture, logger_name: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == logger_name]


def test_r2_3_tool_error_log_record_is_a_single_line(
    temp_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """server.err showed ``... suspicious pattern: .../foo`` followed by a
    separate physical line ``\\tbar.zim`` — log injection at ERROR level."""
    from openzim_mcp.tools._common import tool_error_response

    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    server = OpenZimMcpServer(config)
    err = OpenZimMcpSecurityError(f"Path contains suspicious pattern: {_INJECTED_PATH}")

    with _captured(caplog, "openzim_mcp.tools.zim_metadata"):
        payload = tool_error_response(
            server,
            operation="zim_metadata",
            error=err,
            context=f"Path: {_INJECTED_PATH}",
        )

    (logged,) = _messages(caplog, "openzim_mcp.tools.zim_metadata")
    assert "\n" not in logged, repr(logged)
    assert "\t" not in logged, repr(logged)
    assert "\r" not in logged, repr(logged)
    assert logged.startswith("Error in zim_metadata: Path contains suspicious")
    # Operators still see the offending path, with its controls neutralised.
    assert "foo bar .zim" in logged, logged
    # And the client-facing envelope is clean end to end.
    assert not _stray_controls(payload["message"]), repr(payload["message"])


def test_r2_3_zim_query_handler_log_record_is_a_single_line(
    temp_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """zim_query does not go through ``tool_error_response``; its own broad
    ``except`` in simple_tools logged the same raw exception text."""
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.simple_tools import SimpleToolsHandler
    from openzim_mcp.zim_operations import ZimOperations

    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=100),
    )
    handler = SimpleToolsHandler(ops)

    with _captured(caplog, "openzim_mcp.simple_tools"):
        out = handler.handle_zim_query("summarize main page", _INJECTED_PATH)

    assert isinstance(out, dict), out
    assert out["error"] is True, out
    logged = [
        m for m in _messages(caplog, "openzim_mcp.simple_tools") if "zim_query" in m
    ]
    assert logged, _messages(caplog, "openzim_mcp.simple_tools")
    for line in logged:
        assert "\n" not in line, repr(line)
        assert "\t" not in line, repr(line)
        assert "\r" not in line, repr(line)
    assert any("foo bar .zim" in m for m in logged), logged


def test_r2_3_clean_log_message_format_is_unchanged(
    temp_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """test_tools_common pins ``'Error in <op>: <err>'``; a clean exception
    must round-trip byte for byte."""
    from openzim_mcp.tools._common import tool_error_response

    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    server = OpenZimMcpServer(config)

    with _captured(caplog, "openzim_mcp.tools.zim_links"):
        tool_error_response(server, operation="zim_links", error=RuntimeError("boom"))

    assert _messages(caplog, "openzim_mcp.tools.zim_links") == [
        "Error in zim_links: boom"
    ]
