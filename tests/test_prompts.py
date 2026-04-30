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
