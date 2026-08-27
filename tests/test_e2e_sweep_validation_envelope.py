"""Schema-level argument rejections must use the documented JSON envelope.

The shipped server instructions promise that "A rejected argument is flagged
isError with a JSON body carrying 'error', 'operation' and a 'message'
describing how to correct the call", and ``mcp_envelope`` already delivers
that for *unknown argument names*, negative limits, bad offsets and bad
modes.

Three rejection classes still escaped through the SDK instead: a value
outside a ``Literal`` enum, a value of the wrong type, and a missing
required argument. Each arrived as pydantic's own report stringified into a
bare text block — "1 validation error for zim_searchArguments … visit
https://errors.pydantic.dev/…" — which is the exact leak D04 removed from
``zim_browse``, and which a client parsing the body as JSON cannot read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.test_mcp_session import _text, advanced_session


def _payload(result: Any) -> dict[str, Any]:
    text = _text(result)
    assert "pydantic" not in text, text
    assert "validation error for" not in text, text
    return json.loads(text)


@pytest.mark.asyncio
async def test_enum_violation_uses_the_envelope(tmp_path: Path) -> None:
    """``mode="query"`` is a plausible guess — ``fulltext`` is the real name."""
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(
            "zim_search",
            {
                "query": "climate",
                "zim_file_path": str(tmp_path / "a.zim"),
                "mode": "query",
            },
        )

    assert result.is_error is True
    payload = _payload(result)
    assert payload["error"] is True
    assert payload["operation"] == "invalid_argument"
    # The caller has to learn which argument and which values are legal.
    assert "mode" in payload["message"]
    assert "fulltext" in payload["message"]


@pytest.mark.asyncio
async def test_wrong_type_uses_the_envelope(tmp_path: Path) -> None:
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(
            "zim_browse",
            {
                "namespace": "C",
                "zim_file_path": str(tmp_path / "a.zim"),
                "limit": "five",
            },
        )

    assert result.is_error is True
    payload = _payload(result)
    assert payload["operation"] == "invalid_argument"
    assert "limit" in payload["message"]


@pytest.mark.asyncio
async def test_missing_required_argument_uses_the_envelope(tmp_path: Path) -> None:
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(
            "zim_search", {"zim_file_path": str(tmp_path / "a.zim")}
        )

    assert result.is_error is True
    payload = _payload(result)
    assert payload["operation"] == "invalid_argument"
    assert "query" in payload["message"]


@pytest.mark.asyncio
async def test_envelope_lists_the_offending_arguments(tmp_path: Path) -> None:
    """A model retrying from ``message`` alone still needs the field names."""
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(
            "zim_get",
            {
                "entry_path": "A/Anything",
                "zim_file_path": str(tmp_path / "a.zim"),
                "view": "nonsense_view",
            },
        )

    payload = _payload(result)
    assert payload["invalid_arguments"] == ["view"]


@pytest.mark.asyncio
async def test_union_typed_argument_reports_the_wire_name(tmp_path: Path) -> None:
    """A union-typed argument must not be named by its member tags.

    ``compact_budget`` accepts ``str | int``, so pydantic reports one error
    per member with locs ``("compact_budget", "str")`` and
    ``("compact_budget", "int")``. Joining every loc part named
    ``compact_budget.str`` — an argument the caller never sent and cannot
    correct.
    """
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(
            "zim_get",
            {
                "entry_path": "A/Anything",
                "zim_file_path": str(tmp_path / "a.zim"),
                "compact_budget": ["a", "b"],
            },
        )

    payload = _payload(result)
    assert payload["invalid_arguments"] == ["compact_budget"]
    assert ".str" not in payload["message"]
    assert ".int" not in payload["message"]


@pytest.mark.asyncio
async def test_valid_enum_value_still_dispatches(tmp_path: Path) -> None:
    """Positive control: the guard must not reject legitimate calls."""
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(
            "zim_search",
            {
                "query": "climate",
                "zim_file_path": str(tmp_path / "a.zim"),
                "mode": "title",
            },
        )

    # The stub archive is not a real ZIM, so this fails downstream — but it
    # must fail on the archive, never on argument validation.
    text = _text(result)
    assert "invalid_argument" not in text
