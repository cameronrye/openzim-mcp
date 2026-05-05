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
  FastMCP's URI template engine treats ``/`` as a segment separator.

The per-entry resource detects each entry's MIME type from the libzim Item
at read time and reports it back in the response. FastMCP's standard
``@mcp.resource`` decorator can't express that — it freezes ``mime_type`` at
registration time — so we register a custom ``ResourceTemplate`` /
``Resource`` pair directly on the resource manager.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union
from urllib.parse import unquote

from mcp.server.fastmcp.resources.base import Resource
from mcp.server.fastmcp.resources.templates import ResourceTemplate
from pydantic import AnyUrl, ConfigDict, Field

from ..constants import INPUT_LIMIT_ENTRY_PATH
from ..exceptions import OpenZimMcpArchiveError
from ..security import sanitize_input
from ..zim_operations import MAX_REDIRECT_DEPTH, zim_archive

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

# Default MIME type when libzim has no mimetype for an entry.
DEFAULT_BINARY_MIME = "application/octet-stream"

# Byte cap for text bodies served via ``zim://{name}/entry/{path}``. Resources
# don't carry per-call parameters in MCP, so callers can't ask for paging
# inline; without a cap, a 1 MB Wikipedia article would land in the response
# verbatim and overflow the LLM token budget. 256 KB ≈ ~64K tokens worst-case
# and matches the order of magnitude of ``get_zim_entry``'s default
# ``content_max_length`` (100 KB) while leaving headroom for richer HTML.
DEFAULT_RESOURCE_MAX_BYTES = 256 * 1024


def _truncate_text_body(body: str, max_bytes: int) -> str:
    """Truncate ``body`` so its UTF-8 encoding fits within ``max_bytes``.

    Appends a notice that points callers at ``get_zim_entry``, which supports
    paging via ``content_offset`` / ``max_content_length``. Multi-byte
    characters (CJK, emoji) are counted by their UTF-8 byte width so a
    Japanese/Chinese article can't bypass the cap by virtue of having many
    short visible characters.

    A non-positive ``max_bytes`` returns the notice on its own — callers that
    misconfigure the cap don't get a wedged response, just an empty body.
    """
    notice_template = (
        "\n\n[Resource truncated at {limit:,} bytes. The full entry has "
        "{total:,} bytes. Use the get_zim_entry tool with `content_offset` "
        "to page through the rest, or get_binary_entry for raw bytes.]"
    )
    encoded = body.encode("utf-8")
    total = len(encoded)
    if max_bytes <= 0:
        return notice_template.format(limit=max_bytes, total=total).lstrip()
    if total <= max_bytes:
        return body
    # Decode the head safely — utf-8 'replace' handles any boundary that
    # would split a multi-byte sequence.
    head = encoded[:max_bytes].decode("utf-8", errors="replace")
    return head + notice_template.format(limit=max_bytes, total=total)


def _resolve_zim_name(server: "OpenZimMcpServer", name: str) -> Optional[str]:
    """Resolve a ZIM ``name`` (bare stem or full filename) to its archive path.

    Accepts either ``wikipedia`` (basename without extension) or
    ``wikipedia.zim`` (full filename) and returns the absolute file path of
    the matching archive, or ``None`` if no match is found.

    This helper is sync — it performs an in-memory scan over the result of
    ``list_zim_files_data``. Async callers (e.g. resource templates serving
    HTTP/SSE clients) should wrap the underlying ``list_zim_files_data`` call
    in ``asyncio.to_thread`` themselves; this helper is fast enough to run
    inline once that data is already in memory.
    """
    files = server.zim_operations.list_zim_files_data()
    for f in files:
        if Path(f["path"]).stem == name or f["name"] == name:
            return str(f["path"])
    return None


def _detect_mime_type(item: Any) -> str:
    """Return a clean MIME type for a libzim Item.

    libzim ``Item.mimetype`` may include a charset parameter (e.g.
    ``'text/html; charset=utf-8'``) or be empty for unknown types. We strip
    the parameters and fall back to ``application/octet-stream`` for missing
    or empty values.
    """
    raw = getattr(item, "mimetype", None) or ""
    if not raw or not isinstance(raw, str):
        return DEFAULT_BINARY_MIME
    return raw.split(";", 1)[0].strip().lower() or DEFAULT_BINARY_MIME


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

        def _sync_read() -> tuple[str, bytes]:
            validated = self.path_validator.validate_path(self.archive_path)
            validated = self.path_validator.validate_zim_file(validated)

            with zim_archive(validated) as archive:
                entry = archive.get_entry_by_path(self.entry_path)
                # libzim raises RuntimeError if get_item() is called on a
                # redirect entry, so walk the chain (bounded against cycles)
                # before reading the body.
                seen: set[str] = set()
                for _ in range(MAX_REDIRECT_DEPTH):
                    if not getattr(entry, "is_redirect", False):
                        break
                    if entry.path in seen:
                        raise OpenZimMcpArchiveError(
                            f"Redirect cycle detected at {entry.path}"
                        )
                    seen.add(entry.path)
                    entry = entry.get_redirect_entry()
                if getattr(entry, "is_redirect", False):
                    raise OpenZimMcpArchiveError(
                        f"Redirect chain too deep (>{MAX_REDIRECT_DEPTH}) "
                        f"starting at {self.entry_path}"
                    )
                item = entry.get_item()
                return _detect_mime_type(item), bytes(item.content)

        # libzim and PathValidator do filesystem I/O; offload so concurrent
        # HTTP/SSE clients don't stall on each other.
        mime, raw = await asyncio.to_thread(_sync_read)

        # Mutate so FastMCP's read_resource picks up the detected MIME.
        # Resource has no validate_assignment, so this is a plain attribute set.
        self.mime_type = mime

        if mime.startswith(("text/", "application/json")) or mime in (
            "application/xml",
            "application/javascript",
        ):
            # Cap text bodies so an 800 KB Wikipedia article doesn't overrun
            # the response token budget. The notice points callers at the
            # paged get_zim_entry tool for the rest.
            decoded = raw.decode("utf-8", errors="replace")
            return _truncate_text_body(decoded, DEFAULT_RESOURCE_MAX_BYTES)
        # Binary — FastMCP base64-wraps when content is bytes. Cap on raw
        # byte length (base64 inflates ~33%, so the wire size is ~340 KB).
        if len(raw) > DEFAULT_RESOURCE_MAX_BYTES:
            return raw[:DEFAULT_RESOURCE_MAX_BYTES]
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
        # _resolve_zim_name calls list_zim_files_data (sync filesystem I/O —
        # Path.glob + stat). Offload the whole helper to a thread so
        # concurrent HTTP/SSE clients don't block on one another while a
        # directory scan runs.
        target_path = await asyncio.to_thread(_resolve_zim_name, self.server_ref, name)
        if not target_path:
            raise ValueError(f"ZIM file '{name}' not found")

        # FastMCP captures `%2F` literally; restore to `/` for libzim.
        decoded_path = unquote(params["path"])
        # Strip control characters (e.g. NUL bytes from %00) before they
        # reach libzim, which has no defense against embedded NULs.
        decoded_path = sanitize_input(decoded_path, INPUT_LIMIT_ENTRY_PATH)
        return ZimEntryResource(
            uri=AnyUrl(uri),
            name=self.name,
            title=self.title,
            description=self.description,
            # Placeholder; ZimEntryResource.read() mutates this to the
            # detected MIME before FastMCP reads it back.
            mime_type=DEFAULT_BINARY_MIME,
            archive_path=target_path,
            entry_path=decoded_path,
            path_validator=self.server_ref.path_validator,
        )


_ZIM_ENTRY_URI_TEMPLATE = "zim://{name}/entry/{path}"  # NOSONAR(python:S3776)


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
    async def list_zim_files_resource() -> str:
        # ``list_zim_files_data`` does Path.glob + stat across every allowed
        # directory; offload to a worker thread so concurrent HTTP/SSE
        # clients aren't stalled while a directory scan runs.
        def _build() -> str:
            try:
                files = server.zim_operations.list_zim_files_data()
                return json.dumps(files, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"Resource zim://files failed: {e}")
                return json.dumps({"error": str(e)})

        return await asyncio.to_thread(_build)

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
    async def zim_file_overview(name: str) -> str:
        # Three blocking archive opens (metadata + namespaces + main page)
        # add up — under HTTP/SSE we must not run them on the event loop.
        # Offload the whole synchronous body to a worker thread.
        def _build_overview() -> str:
            try:
                target_path = _resolve_zim_name(server, name)

                if not target_path:
                    # Re-fetch the file list for the error message's "available"
                    # listing. _resolve_zim_name returns None without exposing
                    # the list, but the cost (one glob+stat) is fine on the
                    # error path.
                    files = server.zim_operations.list_zim_files_data()
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

        return await asyncio.to_thread(_build_overview)

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
            "zim://wikipedia_en/entry/C%2FClimate_change. "
            "Use the get_zim_entry tool for processed/truncated text output."
        ),
        # Placeholder; the per-call MIME is set on each ZimEntryResource.
        mime_type=DEFAULT_BINARY_MIME,
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
