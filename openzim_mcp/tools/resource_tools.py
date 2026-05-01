"""MCP resource registration for OpenZIM MCP server.

Resources let MCP clients browse ZIM files using URI references rather than
tool calls, which integrates with @-mention pickers and resource browsers in
Claude Code, Inspector, etc.

URI scheme:
- ``zim://files`` — directory of all available ZIM files
- ``zim://{name}`` — overview of one ZIM file (metadata + namespace summary +
  main page preview). ``{name}`` is the bare basename without ``.zim``.
- ``zim://{name}/entry/{path}`` — single entry served with native MIME type.
  Clients MUST URL-encode ``/`` as ``%2F`` in the ``{path}`` segment because
  FastMCP's URI template engine treats ``/`` as a segment separator. See
  ``docs/superpowers/notes/2026-05-01-per-entry-resource-uri-spike.md`` for
  the full SDK-behaviour analysis.

The per-entry resource detects each entry's MIME type from the libzim Item
at read time and reports it back in the response. FastMCP's standard
``@mcp.resource`` decorator can't express that — it freezes ``mime_type`` at
registration time — so we register a custom ``ResourceTemplate`` /
``Resource`` pair directly on the resource manager.
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union
from urllib.parse import unquote

from mcp.server.fastmcp.resources.base import Resource
from mcp.server.fastmcp.resources.templates import ResourceTemplate
from pydantic import AnyUrl, ConfigDict, Field

from ..zim_operations import zim_archive

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def _detect_mime_type(item: Any) -> str:
    """Return a clean MIME type for a libzim Item.

    libzim ``Item.mimetype`` may include a charset parameter (e.g.
    ``'text/html; charset=utf-8'``) or be empty for unknown types. We strip
    the parameters and fall back to ``application/octet-stream`` for missing
    or empty values.
    """
    raw = getattr(item, "mimetype", None) or ""
    if not raw or not isinstance(raw, str):
        return "application/octet-stream"
    return raw.split(";", 1)[0].strip().lower() or "application/octet-stream"


class ZimEntryResource(Resource):
    """Resource that reads one ZIM entry and reports its native MIME type.

    The MIME type is detected from the libzim ``Item.mimetype`` and assigned
    to ``self.mime_type`` during ``read()`` so that FastMCP's ``read_resource``
    handler — which fetches ``resource.mime_type`` *after* ``read()`` — sees
    the detected value, not the placeholder set at construction time.
    """

    model_config = ConfigDict(validate_default=True, arbitrary_types_allowed=True)

    archive_path: str = Field(description="Resolved path to the ZIM file")
    entry_path: str = Field(description="Decoded entry path inside the archive")
    path_validator: Any = Field(default=None, exclude=True, repr=False)

    async def read(self) -> Union[str, bytes]:
        """Read the entry, set ``self.mime_type`` to the libzim native MIME."""
        validated = self.path_validator.validate_path(self.archive_path)
        validated = self.path_validator.validate_zim_file(validated)

        with zim_archive(validated) as archive:
            entry = archive.get_entry_by_path(self.entry_path)
            item = entry.get_item()
            mime = _detect_mime_type(item)
            raw = bytes(item.content)

        # Mutate so FastMCP's read_resource picks up the detected MIME.
        # Resource has no validate_assignment, so this is a plain attribute set.
        self.mime_type = mime

        if mime.startswith(("text/", "application/json")) or mime in (
            "application/xml",
            "application/javascript",
        ):
            return raw.decode("utf-8", errors="replace")
        # Binary — FastMCP base64-wraps when content is bytes.
        return raw


class ZimEntryTemplate(ResourceTemplate):
    """Template that materialises a ``ZimEntryResource`` for each request.

    Bypasses ``ResourceTemplate.from_function`` because we don't want to wrap
    the result in a ``FunctionResource`` (which would freeze ``mime_type`` at
    template-registration time). Instead we construct our own ``Resource``
    subclass and let it mutate its own MIME during ``read()``.
    """

    server_ref: Any = Field(default=None, exclude=True, repr=False)

    async def create_resource(
        self,
        uri: str,
        params: dict,
        context: Any = None,
    ) -> Resource:
        """Resolve {name} → archive_path and build a ZimEntryResource."""
        name = params["name"]
        files = self.server_ref.zim_operations.list_zim_files_data()
        target_path: Optional[str] = None
        for f in files:
            stem = Path(f["path"]).stem
            if stem == name or f["name"] == name:
                target_path = f["path"]
                break
        if not target_path:
            raise ValueError(f"ZIM file '{name}' not found")

        # FastMCP captures `%2F` literally; restore to `/` for libzim.
        decoded_path = unquote(params["path"])
        return ZimEntryResource(
            uri=AnyUrl(uri),
            name=self.name,
            title=self.title,
            description=self.description,
            # Placeholder; ZimEntryResource.read() mutates this to the
            # detected MIME before FastMCP reads it back.
            mime_type="application/octet-stream",
            archive_path=target_path,
            entry_path=decoded_path,
            path_validator=self.server_ref.path_validator,
        )


_ZIM_ENTRY_URI_TEMPLATE = "zim://{name}/entry/{path}"


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

    # Register the per-entry template directly on the resource manager so
    # ZimEntryResource controls its own MIME type at read time.
    template = ZimEntryTemplate(
        uri_template=_ZIM_ENTRY_URI_TEMPLATE,
        name="zim_entry",
        title="ZIM entry (raw, native MIME)",
        description=(
            "Raw content of a single ZIM entry, served with its native MIME "
            "type. HTML/text entries return text/html (or text/plain) with "
            "the unprocessed body; binary entries (images, PDFs, etc.) "
            "return the appropriate MIME with base64-encoded body. "
            "IMPORTANT: clients MUST URL-encode '/' as '%2F' in {path} "
            "(other RFC 3986 reserved characters too). Example: "
            "zim://wikipedia_en/entry/A%2FClimate_change. "
            "Use the get_zim_entry tool for processed/truncated text output."
        ),
        # Placeholder; the per-call MIME is set on each ZimEntryResource.
        mime_type="application/octet-stream",
        # ResourceTemplate requires `fn` and `parameters`; we never call fn
        # because we override create_resource(), but the fields are required.
        fn=lambda name, path: None,  # noqa: ARG005 — sentinel
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["name", "path"],
        },
        context_kwarg=None,
        server_ref=server,
    )
    server.mcp._resource_manager._templates[_ZIM_ENTRY_URI_TEMPLATE] = template
