"""Tests for the shared structured-response helpers."""

from openzim_mcp.responses import ToolErrorPayload, tool_error


class TestToolError:
    """Tests for the ``tool_error`` factory and ``ToolErrorPayload`` shape."""

    def test_returns_dict_with_expected_keys(self) -> None:
        """All supplied fields appear verbatim in the payload."""
        payload = tool_error(
            operation="list ZIM files",
            message="Test error message",
            context="Scanning directories",
        )
        assert payload["error"] is True
        assert payload["operation"] == "list ZIM files"
        assert payload["message"] == "Test error message"
        assert payload["context"] == "Scanning directories"

    def test_context_is_optional(self) -> None:
        """Omitting ``context`` yields a payload without that key."""
        payload = tool_error(operation="x", message="y")
        assert payload["error"] is True
        assert payload["operation"] == "x"
        assert payload["message"] == "y"
        assert "context" not in payload

    def test_empty_string_context_preserved(self) -> None:
        """An explicitly empty context string is preserved (not dropped as falsy)."""
        payload = tool_error(operation="x", message="y", context="")
        assert payload.get("context") == ""

    def test_payload_is_typeddict_compatible(self) -> None:
        """Return value satisfies the ``ToolErrorPayload`` TypedDict.

        ``ToolErrorPayload`` should be a TypedDict so callers can annotate
        and so FastMCP's structured-output schema generation works.
        """
        payload: ToolErrorPayload = tool_error(operation="x", message="y")
        assert isinstance(payload, dict)

    def test_extras_merged_into_payload(self) -> None:
        """extras dict keys are merged into the returned payload."""
        payload = tool_error(
            operation="section_not_found",
            message="Not found",
            extras={"available_section_ids": ["intro", "history"]},
        )
        assert payload["error"] is True
        assert "available_section_ids" in payload
        assert payload["available_section_ids"] == ["intro", "history"]  # type: ignore[typeddict-item]

    def test_extras_none_does_not_add_keys(self) -> None:
        """Omitting extras (default None) leaves the payload unaffected."""
        payload = tool_error(operation="x", message="y")
        # Only the three base keys (and no extras) should be present.
        assert set(payload.keys()) == {"error", "operation", "message"}

    def test_extras_empty_dict_does_not_add_keys(self) -> None:
        """An empty extras dict does not add any keys to the payload."""
        payload = tool_error(operation="x", message="y", extras={})
        assert set(payload.keys()) == {"error", "operation", "message"}
