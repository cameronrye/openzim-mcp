"""Tests for the Phase F ``zim_get`` tool (Task D5).

zim_get is the 4-branch oneOf collapse (7 legacy tools → 1). Tests
cover the branch-validation matrix + each branch's dispatch target.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import openzim_mcp.tools.zim_get as zim_get_module
from openzim_mcp.tools.zim_get import _validate_branch_combination
from openzim_mcp.tools.zim_get import register as register_zim_get


@pytest.fixture
def server() -> MagicMock:
    srv = MagicMock()
    tools_store: dict[str, Any] = {}

    def _tool(*, description: str = ""):
        def decorate(fn: Any) -> Any:
            tools_store[fn.__name__] = (fn, description)
            return fn

        return decorate

    srv.mcp.tool = _tool
    srv._tools_store = tools_store
    return srv


def _patch_async_ops(
    monkeypatch: pytest.MonkeyPatch, **method_returns: Any
) -> MagicMock:
    mock_ops = MagicMock()
    for name, value in method_returns.items():
        setattr(mock_ops, name, AsyncMock(return_value=value))
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations",
        lambda _zim_ops: mock_ops,
    )
    return mock_ops


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_zim_get_registers(server: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    assert "zim_get" in server._tools_store


def test_zim_get_description_attached(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    _, description = server._tools_store["zim_get"]
    assert "Fetch entries from a ZIM archive" in description
    assert "main_page" in description


# ---------------------------------------------------------------------------
# Branch dispatch (happy paths)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_entry_full_view(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_zim_entry_data={"content": "body"})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat")
    ops.get_zim_entry_data.assert_awaited_once_with(
        "/x.zim",
        "A/Cat",
        max_content_length=None,
        content_offset=0,
        compact=False,
    )


@pytest.mark.asyncio
async def test_single_entry_summary_view(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_entry_summary_data={"summary": "..."})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", view="summary")
    ops.get_entry_summary_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", compact=False
    )


@pytest.mark.asyncio
async def test_single_entry_toc_view(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_table_of_contents_data={"toc": []})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", view="toc")
    ops.get_table_of_contents_data.assert_awaited_once_with("/x.zim", "A/Cat")


@pytest.mark.asyncio
async def test_single_entry_structure_view(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_article_structure_data={"sections": []})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", view="structure")
    ops.get_article_structure_data.assert_awaited_once_with("/x.zim", "A/Cat")


@pytest.mark.asyncio
async def test_single_entry_binary(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_binary_entry_data={"bytes": b"png"})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="I/cat.png", binary=True)
    ops.get_binary_entry_data.assert_awaited_once_with(
        "/x.zim", "I/cat.png", max_size_bytes=None
    )


@pytest.mark.asyncio
async def test_batch_dispatches_to_get_entries(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_entries_data={"results": []})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_paths=["A/Cat", "A/Dog"])
    ops.get_entries_data.assert_awaited_once_with(
        [
            {"zim_file_path": "/x.zim", "entry_path": "A/Cat"},
            {"zim_file_path": "/x.zim", "entry_path": "A/Dog"},
        ],
        max_content_length=None,
        compact=False,
    )


@pytest.mark.asyncio
async def test_batch_with_content_offset_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_entries_data always renders each entry's first page, yet truncated
    batch bodies advertise the `pass content_offset=N` footer — honoring the
    combination silently loops page 1 forever, so reject it instead."""
    ops = _patch_async_ops(monkeypatch, get_entries_data={"results": []})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(
        zim_file_path="/x.zim", entry_paths=["A/Cat", "A/Dog"], content_offset=500
    )
    assert result["operation"] == "invalid_path_combination"
    assert "content_offset" in result["message"]
    ops.get_entries_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_with_zero_content_offset_allowed(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit content_offset=0 (the default) stays a valid batch call."""
    ops = _patch_async_ops(monkeypatch, get_entries_data={"results": []})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_paths=["A/Cat"], content_offset=0)
    ops.get_entries_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_binary_forwards_max_content_length(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Binary mode maps max_content_length onto the data layer's byte cap —
    without it the 10MB default applies and a caller-passed cap is dropped."""
    ops = _patch_async_ops(monkeypatch, get_binary_entry_data={"size": 76998})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(
        zim_file_path="/x.zim",
        entry_path="I/cat.png",
        binary=True,
        max_content_length=10000,
    )
    ops.get_binary_entry_data.assert_awaited_once_with(
        "/x.zim", "I/cat.png", max_size_bytes=10000
    )


@pytest.mark.asyncio
async def test_main_page(server: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    ops = _patch_async_ops(monkeypatch, get_main_page_data={"content": "Welcome"})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", main_page=True)
    ops.get_main_page_data.assert_awaited_once_with(
        "/x.zim", compact=False, max_content_length=None
    )


@pytest.mark.asyncio
async def test_main_page_forwards_compact(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``compact`` is documented unscoped and permitted alongside ``main_page``
    by the branch validator, so it must reach the data layer rather than being
    silently dropped by the async wrapper's signature."""
    ops = _patch_async_ops(monkeypatch, get_main_page_data={"content": "Welcome"})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", main_page=True, compact=True)
    ops.get_main_page_data.assert_awaited_once_with(
        "/x.zim", compact=True, max_content_length=None
    )


@pytest.mark.asyncio
async def test_compact_default_is_false(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v2.0 preserves legacy get_zim_entry behavior — compact=False default."""
    ops = _patch_async_ops(monkeypatch, get_zim_entry_data={"content": "body"})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat")
    _, kwargs = ops.get_zim_entry_data.call_args
    assert kwargs["compact"] is False


# ---------------------------------------------------------------------------
# Invalid branch combinations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entry_path_and_entry_paths_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", entry_path="A", entry_paths=["B"])
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_binary_with_batch_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", entry_paths=["A"], binary=True)
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_binary_with_non_full_view_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(
        zim_file_path="/x.zim", entry_path="A", binary=True, view="summary"
    )
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_main_page_with_entry_path_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", main_page=True, entry_path="A")
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_main_page_with_non_full_view_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", main_page=True, view="summary")
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_no_path_branch_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim")  # no path / paths / main_page
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_invalid_view_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", entry_path="A", view="bogus")  # type: ignore[arg-type]
    assert result["operation"] == "invalid_view"


# ---------------------------------------------------------------------------
# Validator-regression guards
#
# The two handler branches that need ``entry_path`` used to narrow it with a
# bare ``assert``. That assert sat inside the b13 ``except Exception``, which
# swallowed the AssertionError into a generic ``zim_get`` envelope — and
# ``python -O`` strips asserts entirely, so under an optimised interpreter
# None went straight through to the data layer. These tests simulate the
# validator regressing (it is the only thing that makes the branches
# reachable) and pin the structured envelope.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_binary_without_entry_path_returns_envelope_if_validator_regresses(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_binary_entry_data={"content": b""})
    monkeypatch.setattr(
        "openzim_mcp.tools.zim_get._validate_branch_combination",
        lambda **_kwargs: None,
    )
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", entry_path=None, binary=True)
    assert result["operation"] == "invalid_path_combination"
    assert result["message"] == "Binary mode requires `entry_path`."
    ops.get_binary_entry_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_entry_without_entry_path_returns_envelope_if_validator_regresses(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_zim_entry_data={"content": ""})
    monkeypatch.setattr(
        "openzim_mcp.tools.zim_get._validate_branch_combination",
        lambda **_kwargs: None,
    )
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", entry_path=None)
    assert result["operation"] == "invalid_path_combination"
    assert (
        result["message"]
        == "Provide one of `entry_path`, `entry_paths`, or `main_page=True`."
    )
    ops.get_zim_entry_data.assert_not_awaited()


# ---------------------------------------------------------------------------
# content_offset pages a full single-entry body and nothing else
#
# The batch guard above was one branch of a wider drop: the summary / toc /
# structure views, the main page and the binary fetch each took a
# ``content_offset`` and threw it away, so a caller paging any of them re-read
# the same response instead of advancing.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "dropped_call"),
    [
        ({"entry_path": "A/Cat", "view": "summary"}, "get_entry_summary_data"),
        ({"entry_path": "A/Cat", "view": "toc"}, "get_table_of_contents_data"),
        ({"entry_path": "A/Cat", "view": "structure"}, "get_article_structure_data"),
        ({"main_page": True}, "get_main_page_data"),
        ({"entry_path": "I/cat.png", "binary": True}, "get_binary_entry_data"),
    ],
)
async def test_content_offset_rejected_outside_single_entry_full_view(
    server: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    dropped_call: str,
) -> None:
    ops = _patch_async_ops(
        monkeypatch,
        get_entry_summary_data={"summary": ""},
        get_table_of_contents_data={"toc": []},
        get_article_structure_data={"sections": []},
        get_main_page_data={"content": ""},
        get_binary_entry_data={"bytes": 0},
    )
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", content_offset=500, **kwargs)
    assert result.get("operation") == "invalid_path_combination", (
        f"`content_offset` was accepted for {kwargs!r} and silently "
        f"discarded; got {result!r}"
    )
    assert "content_offset" in result["message"]
    getattr(ops, dropped_call).assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "expected_call"),
    [
        ({"entry_path": "A/Cat", "view": "summary"}, "get_entry_summary_data"),
        ({"main_page": True}, "get_main_page_data"),
        ({"entry_path": "I/cat.png", "binary": True}, "get_binary_entry_data"),
    ],
)
async def test_zero_content_offset_still_dispatches(
    server: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    expected_call: str,
) -> None:
    """content_offset=0 is the default — it must never trip the guard."""
    ops = _patch_async_ops(
        monkeypatch,
        get_entry_summary_data={"summary": ""},
        get_main_page_data={"content": ""},
        get_binary_entry_data={"bytes": 0},
    )
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", content_offset=0, **kwargs)
    assert "operation" not in result, result
    getattr(ops, expected_call).assert_awaited_once()


# ---------------------------------------------------------------------------
# ... and the rejection has to leave the caller somewhere to go
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "must_name"),
    [
        ({"entry_path": "I/cat.png", "binary": True}, "max_content_length"),
        ({"main_page": True}, "entry_path"),
    ],
)
async def test_content_offset_recovery_is_not_the_call_that_just_failed(
    server: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    must_name: str,
) -> None:
    """`view='full'` is already forced on the binary and main-page branches.

    Offering it as the recovery there sends the caller back with a request
    that differs from the rejected one in no way the server can see, and it
    earns the byte-identical envelope — the re-ask loop this guard exists to
    end. Each branch has to name something that changes the outcome.
    """
    _patch_async_ops(
        monkeypatch,
        get_main_page_data={"content": ""},
        get_binary_entry_data={"bytes": 0},
    )
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]

    rejected = await fn(zim_file_path="/x.zim", content_offset=500, **kwargs)
    retried = await fn(
        zim_file_path="/x.zim", content_offset=500, view="full", **kwargs
    )
    assert (
        retried == rejected
    ), "premise gone: adding `view='full'` to this branch used to be a no-op"

    recovery = rejected["message"].split("ignores it. ", 1)[1]
    assert "view=" not in recovery, (
        f"the recovery offered for {kwargs!r} is the call that just failed: "
        f"{recovery!r}"
    )
    assert (
        must_name in recovery
    ), f"the recovery for {kwargs!r} names nothing actionable: {recovery!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "expected_message"),
    [
        (
            {"main_page": True, "entry_path": "A/Cat"},
            "`main_page=True` is the path-free branch — omit `entry_path` "
            "and `entry_paths`.",
        ),
        (
            {"entry_path": "I/cat.png", "binary": True, "view": "summary"},
            "Binary mode locks `view='full'`.",
        ),
        (
            {"view": "summary"},
            "Provide one of `entry_path`, `entry_paths`, or `main_page=True`.",
        ),
    ],
)
async def test_a_broken_branch_outranks_the_content_offset_guard(
    server: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    expected_message: str,
) -> None:
    """A doubly-invalid call must be diagnosed by its most specific fault.

    `content_offset` is the least specific thing wrong with any of these:
    dropping it as instructed still leaves a call that cannot be served, so
    diagnosing it first costs a round trip and teaches the wrong lesson.
    """
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]

    result = await fn(zim_file_path="/x.zim", content_offset=500, **kwargs)

    assert result["operation"] == "invalid_path_combination"
    assert result["message"] == expected_message, (
        f"{kwargs!r} was diagnosed by its content_offset rather than by its "
        f"broken branch; got {result['message']!r}"
    )


def test_branch_matrix_docstring_records_the_content_offset_rejection() -> None:
    """The module docstring is this file's contract table; keep it true.

    Each branch that refuses a non-zero `content_offset` at runtime has to say
    so in its own `Forbidden:` list, so a maintainer reading the matrix to
    wire up a new caller does not discover the rejection from an envelope.
    """
    docstring = zim_get_module.__doc__ or ""
    matrix = docstring[docstring.index("## Branch matrix") :]
    blocks = {
        block.split(":", 1)[0].strip(): block for block in matrix.split("  - ")[1:]
    }
    assert set(blocks) == {
        "Single body view",
        "Single binary",
        "Batch",
        "Main page",
    }, sorted(blocks)

    rejecting_branches = {
        "Single binary": dict(entry_path="I/cat.png", binary=True, view="full"),
        "Batch": dict(entry_paths=["A/Cat"], view="full"),
        "Main page": dict(main_page=True, view="full"),
    }
    for label, call in rejecting_branches.items():
        rejected = _validate_branch_combination(
            entry_path=call.get("entry_path"),
            entry_paths=call.get("entry_paths"),
            view=call["view"],
            binary=call.get("binary", False),
            main_page=call.get("main_page", False),
            content_offset=7,
        )
        assert rejected is not None, f"{label} no longer rejects content_offset"
        forbidden = blocks[label].split("Forbidden:", 1)[1]
        assert "content_offset" in forbidden, (
            f"the {label!r} row rejects a non-zero `content_offset` but its "
            f"Forbidden list does not mention it: {forbidden!r}"
        )

    single = blocks["Single body view"]
    assert (
        _validate_branch_combination(
            entry_path="A/Cat",
            entry_paths=None,
            view="summary",
            binary=False,
            main_page=False,
            content_offset=7,
        )
        is not None
    )
    assert "content_offset" in single.split("Forbidden:", 1)[1], single
    assert (
        _validate_branch_combination(
            entry_path="A/Cat",
            entry_paths=None,
            view="full",
            binary=False,
            main_page=False,
            content_offset=7,
        )
        is None
    ), "the one branch that honours content_offset stopped honouring it"
