"""Tests for MCP prompts (research, summarize, explore)."""

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


class TestPromptsRegistered:
    """Test that prompts are wired into the server."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_server_starts_with_prompts(self, server: OpenZimMcpServer):
        """register_prompts wires without raising; server has FastMCP attached."""
        assert server.mcp is not None


class TestPromptRendering:
    """Test prompt body rendering — verify each returns non-empty content."""

    def test_research_prompt_body(self):
        """research(topic) renders a multi-message conversation referencing topic."""
        from openzim_mcp.tools.prompts import _research_body

        messages = _research_body("climate change")
        assert len(messages) >= 1
        body_text = "\n".join(
            m["content"]["text"] if isinstance(m["content"], dict) else m["content"]
            for m in messages
        )
        assert "climate change" in body_text

    def test_summarize_prompt_body(self):
        """summarize(zim, entry) references the entry path."""
        from openzim_mcp.tools.prompts import _summarize_body

        messages = _summarize_body("/zim/wikipedia.zim", "C/Photosynthesis")
        assert len(messages) >= 1
        body_text = "\n".join(
            m["content"]["text"] if isinstance(m["content"], dict) else m["content"]
            for m in messages
        )
        assert "C/Photosynthesis" in body_text

    def test_explore_prompt_body(self):
        """explore(zim) references the zim file path."""
        from openzim_mcp.tools.prompts import _explore_body

        messages = _explore_body("/zim/wikipedia.zim")
        assert len(messages) >= 1
        body_text = "\n".join(
            m["content"]["text"] if isinstance(m["content"], dict) else m["content"]
            for m in messages
        )
        assert "/zim/wikipedia.zim" in body_text

    def test_research_empty_topic_asks_for_input(self):
        """research(topic='') returns guard message rather than malformed workflow."""
        from openzim_mcp.tools.prompts import _research_body

        messages = _research_body("")
        body = "\n".join(m["content"]["text"] for m in messages)
        assert "research" in body.lower() or "topic" in body.lower()
        assert "search_all" not in body  # don't render the workflow

    def test_summarize_empty_args_asks_for_input(self):
        """Summarize with empty zim_file_path or entry_path returns guard."""
        from openzim_mcp.tools.prompts import _summarize_body

        messages = _summarize_body("", "")
        body = "\n".join(m["content"]["text"] for m in messages)
        assert "summarize" in body.lower() or "path" in body.lower()
        assert "get_table_of_contents" not in body

    def test_explore_empty_path_asks_for_input(self):
        """explore('') returns a guard message."""
        from openzim_mcp.tools.prompts import _explore_body

        messages = _explore_body("")
        body = "\n".join(m["content"]["text"] for m in messages)
        assert "explore" in body.lower() or "path" in body.lower()
        assert "get_zim_metadata" not in body
