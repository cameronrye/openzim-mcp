"""MCP resource registration for OpenZIM MCP server.

Resources let MCP clients browse ZIM files using URI references rather than
tool calls, which integrates with @-mention pickers and resource browsers in
Claude Code, Inspector, etc.

URI scheme:
- ``zim://files`` — directory of all available ZIM files
- ``zim://{name}`` — overview of one ZIM file (metadata + namespace summary +
  main page preview). ``{name}`` is the bare basename without ``.zim``.

Per-entry resources (e.g. ``zim://{name}/entry/A/Article``) are intentionally
not exposed: FastMCP URI templates don't handle the literal ``/`` inside
entry paths cleanly, and the existing ``get_zim_entry`` tool already covers
that use case.
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_resources(server: "OpenZimMcpServer") -> None:
    """Register MCP resources that expose ZIM files for client-side browsing."""

    @server.mcp.resource(
        "zim://files",
        name="zim_files",
        title="Available ZIM files",
        description=(
            "Index of every ZIM file in the server's allowed directories. "
            "JSON list of {name, path, size, modified}."
        ),
        mime_type="application/json",
    )
    def list_zim_files_resource() -> str:
        try:
            files = server.zim_operations.list_zim_files_data()
            return json.dumps(files, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Resource zim://files failed: {e}")
            return json.dumps({"error": str(e)})

    @server.mcp.resource(
        "zim://{name}",
        name="zim_file_overview",
        title="ZIM file overview",
        description=(
            "Overview of one ZIM file: metadata, namespace summary, and main "
            "page preview. {name} is the bare basename without .zim "
            "(e.g. 'wikipedia_en_climate_change_mini_2024-06')."
        ),
        mime_type="application/json",
    )
    def zim_file_overview(name: str) -> str:
        try:
            files = server.zim_operations.list_zim_files_data()
            target_path = None
            for f in files:
                stem = Path(f["path"]).stem
                if stem == name or f["name"] == name:
                    target_path = f["path"]
                    break

            if not target_path:
                return json.dumps(
                    {
                        "error": (
                            f"ZIM file '{name}' not found. Available: "
                            + ", ".join(Path(f["path"]).stem for f in files)
                        )
                    }
                )

            overview: dict = {"name": name, "path": target_path}

            # Best-effort: fetch each section, log and continue on failure.
            try:
                overview["metadata"] = json.loads(
                    server.zim_operations.get_zim_metadata(target_path)
                )
            except Exception as e:
                overview["metadata_error"] = str(e)

            try:
                overview["namespaces"] = json.loads(
                    server.zim_operations.list_namespaces(target_path)
                )
            except Exception as e:
                overview["namespaces_error"] = str(e)

            try:
                main_page_text = server.zim_operations.get_main_page(target_path)
                # Trim to a preview — full body is too large for an overview.
                if len(main_page_text) > 2000:
                    main_page_text = main_page_text[:2000] + "\n\n... (truncated)"
                overview["main_page_preview"] = main_page_text
            except Exception as e:
                overview["main_page_error"] = str(e)

            return json.dumps(overview, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Resource zim://{name} failed: {e}")
            return json.dumps({"error": str(e)})
