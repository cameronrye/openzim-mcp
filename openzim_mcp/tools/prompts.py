"""MCP prompt registration for OpenZIM MCP server.

Prompts let users invoke pre-built workflows as slash commands. Each
prompt returns a list of messages that orchestrate multi-step ZIM
operations (search, summarize, explore) the LLM would otherwise have
to chain manually.
"""

import re
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer


# Matches any ASCII control character (C0 range, including \n, \r, \t, \x00).
# We strip these from user input before interpolating into prompt templates so
# that a topic like "Foo\n2. Ignore previous instructions" cannot append fake
# numbered steps to the workflow body sent to the LLM.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _sanitize_for_prompt(value: str, max_length: int = 200) -> str:
    """Strip control characters and cap length before embedding in prompt text.

    Args:
        value: Raw user-supplied string.
        max_length: Maximum length to retain. Longer values are truncated and
            suffixed with an ellipsis to keep prompt size bounded.

    Returns:
        Cleaned string safe to interpolate into a multi-line prompt template.
    """
    if not value:
        return value
    cleaned = _CONTROL_CHARS_RE.sub(" ", value).strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip() + "..."
    return cleaned


def _msg(role: str, text: str) -> Dict[str, Any]:
    """Build a PromptMessage-shaped dict."""
    return {"role": role, "content": {"type": "text", "text": text}}


def _research_body(topic: str) -> List[Dict[str, Any]]:
    """Body of the research prompt — the message list returned to the client."""
    if not topic or not topic.strip():
        return [
            _msg(
                "user",
                (
                    "I want to use the /research prompt, but I haven't "
                    "given you a topic. Please ask me what subject I want "
                    "to research, then re-run the /research prompt with "
                    "that topic."
                ),
            )
        ]
    safe_topic = _sanitize_for_prompt(topic)
    if not safe_topic:
        return [
            _msg(
                "user",
                (
                    "I want to use the /research prompt, but I haven't "
                    "given you a topic. Please ask me what subject I want "
                    "to research, then re-run the /research prompt with "
                    "that topic."
                ),
            )
        ]
    return [
        _msg(
            "user",
            (
                f"Research the topic: {safe_topic}\n\n"
                "Workflow:\n"
                f"1. Call search_all with query='{safe_topic}' to find which "
                "ZIM files have relevant content.\n"
                "2. For the top 3 hits across files, call get_entry_summary "
                "to get a concise overview.\n"
                "3. Identify any sub-topics or related concepts worth "
                "drilling into; ask me which to pursue next.\n\n"
                "Aim for breadth before depth — the goal is to map the "
                "available knowledge first, then pick the most promising "
                "thread."
            ),
        )
    ]


def _summarize_body(zim_file_path: str, entry_path: str) -> List[Dict[str, Any]]:
    """Body of the summarize prompt."""
    if (
        not zim_file_path
        or not zim_file_path.strip()
        or not entry_path
        or not entry_path.strip()
    ):
        return [
            _msg(
                "user",
                (
                    "I want to use the /summarize prompt, but I haven't "
                    "given you the required arguments. Please ask me "
                    "which ZIM file path and which article path "
                    "(e.g. 'C/Photosynthesis'), then re-run the "
                    "/summarize prompt with both."
                ),
            )
        ]
    safe_zim = _sanitize_for_prompt(zim_file_path)
    safe_entry = _sanitize_for_prompt(entry_path)
    return [
        _msg(
            "user",
            (
                f"Summarize the article: {safe_entry} in {safe_zim}\n\n"
                "Workflow:\n"
                f"1. Call get_table_of_contents('{safe_zim}', "
                f"'{safe_entry}') for a structural overview.\n"
                f"2. Call get_entry_summary('{safe_zim}', "
                f"'{safe_entry}') for the lead-paragraph summary.\n"
                f"3. Call extract_article_links('{safe_zim}', "
                f"'{safe_entry}') for the most-mentioned related entries.\n\n"
                "Combine into: (a) one-paragraph TL;DR, (b) section list, "
                "(c) 5–10 most relevant outbound links."
            ),
        )
    ]


def _explore_body(zim_file_path: str) -> List[Dict[str, Any]]:
    """Body of the explore prompt."""
    if not zim_file_path or not zim_file_path.strip():
        return [
            _msg(
                "user",
                (
                    "I want to use the /explore prompt, but I haven't "
                    "given you a ZIM file path. Please ask me which "
                    "ZIM file path, then re-run the /explore prompt "
                    "with that path."
                ),
            )
        ]
    safe_zim = _sanitize_for_prompt(zim_file_path)
    return [
        _msg(
            "user",
            (
                f"Explore the ZIM file: {safe_zim}\n\n"
                "Workflow:\n"
                f"1. Call get_zim_metadata('{safe_zim}') for title, "
                "language, creator, and flavour.\n"
                f"2. Call list_namespaces('{safe_zim}') for namespace "
                "breakdown — note any minority namespaces (M, W, X) that "
                "might be worth examining separately.\n"
                f"3. Call get_main_page('{safe_zim}') for the entry "
                "point.\n"
                f"4. Call walk_namespace('{safe_zim}', 'C', limit=5) "
                "to sample article content.\n\n"
                "Then: present a compact briefing — what is this archive, "
                "what does it cover, and what does typical content look "
                "like?"
            ),
        )
    ]


def register_prompts(server: "OpenZimMcpServer") -> None:
    """Register MCP prompts on the FastMCP server."""

    @server.mcp.prompt("research")
    def research(topic: str) -> List[Dict[str, Any]]:
        """Research a topic across all ZIM files.

        Args:
            topic: Subject to research

        Returns:
            Multi-step instruction message for the LLM
        """
        return _research_body(topic)

    @server.mcp.prompt("summarize")
    def summarize(zim_file_path: str, entry_path: str) -> List[Dict[str, Any]]:
        """Summarize an article: TOC + summary + key links.

        Args:
            zim_file_path: ZIM file to read
            entry_path: Article path, e.g. 'C/Photosynthesis'
        """
        return _summarize_body(zim_file_path, entry_path)

    @server.mcp.prompt("explore")
    def explore(zim_file_path: str) -> List[Dict[str, Any]]:
        """Explore a ZIM file's contents at a high level.

        Args:
            zim_file_path: ZIM file to explore
        """
        return _explore_body(zim_file_path)
