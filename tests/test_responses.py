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
