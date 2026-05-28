"""zim_get — single/batch/binary/main-page entry fetch. Phase F surface.

Collapses 7 legacy tools (get_zim_entry + get_zim_entries + get_main_page +
get_binary_entry + get_entry_summary + get_table_of_contents +
get_article_structure) into one 4-branch entry point.

## Branch matrix (defense-in-depth handler validation)

  - Single body view: requires `entry_path`. Optional `view`,
    `max_content_length`, `content_offset`, `compact`, `compact_budget`.
    Forbidden: `entry_paths`, `binary=True`, `main_page=True`.
  - Single binary: requires `entry_path` + `binary=True`. `view`
    locked to ``"full"``. Forbidden: `entry_paths`,
    `view∈{summary,toc,structure}`, `main_page=True`.
  - Batch: requires `entry_paths`. Optional `view`,
    `max_content_length`, `compact`, `compact_budget`. Forbidden:
    `entry_path`, `binary=True`, `main_page=True`.
  - Main page: requires `main_page=True`. `view` ignored (defaults to
    full-shaped response). Forbidden: `entry_path`, `entry_paths`,
    `binary=True`, `view∈{summary,toc,structure}`.

The spec's preferred wire shape is JSON Schema oneOf over these
branches. Gate 0.3 (small-model oneOf parsing) is `unvalidated` in
gate_0b_decision.json, so per the spec fallback the schema ships
flat and the handler validates invalid combinations — returning
`tool_error("invalid_path_combination", ...)` so a small model that
flattens the oneOf gets a clean error rather than partial-success
nonsense.

## compact default

`compact=False` at v2.0 — preserves legacy `get_zim_entry`
raw-markdown shape, so the v1.x → v2.0 migration is rename-only on
this axis. v2.5 revisits the default with adoption telemetry.
"""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING, Any, List, Literal, Optional, Union

from ..responses import tool_error

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

_DIR = pathlib.Path(__file__).parent
_DESCRIPTION = (_DIR / "zim_get_description.md").read_text(encoding="utf-8")

_VALID_VIEWS = {"full", "summary", "toc", "structure"}


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_get` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_get(
        zim_file_path: str,
        entry_path: Optional[str] = None,
        entry_paths: Optional[List[str]] = None,
        view: Literal["full", "summary", "toc", "structure"] = "full",
        binary: bool = False,
        main_page: bool = False,
        max_content_length: Optional[int] = None,
        content_offset: int = 0,
        compact: bool = False,
        compact_budget: Optional[Union[str, int]] = None,
    ) -> Any:
        try:
            # Post-v2.0.0 D-F (sibling fix from pass-4): mirror the
            # input-validation envelopes ``zim_query`` adopted in pass-3.
            # Pre-fix this advanced surface silently passed
            # ``content_offset < 0`` / ``max_content_length <= 0`` to the
            # data layer (zim_get accepted negatives and ``<= 0`` meant
            # "no limit"). Keeping the two surfaces consistent prevents
            # a misconfigured advanced caller from bypassing the cap.
            if content_offset < 0:
                return tool_error(
                    operation="invalid_content_offset",
                    message=(
                        "`content_offset` must be non-negative "
                        f"(provided: {content_offset})."
                    ),
                )
            if max_content_length is not None and max_content_length < 1:
                return tool_error(
                    operation="invalid_max_content_length",
                    message=(
                        "`max_content_length` must be a positive integer "
                        f"(provided: {max_content_length})."
                    ),
                )
            err = _validate_branch_combination(
                entry_path=entry_path,
                entry_paths=entry_paths,
                view=view,
                binary=binary,
                main_page=main_page,
            )
            if err is not None:
                return err

            if main_page:
                return await ops.get_main_page_data(zim_file_path)
            if binary:
                assert entry_path is not None  # validator guarantees this
                return await ops.get_binary_entry_data(zim_file_path, entry_path)
            if entry_paths:
                # Legacy get_entries_data expects a list of dicts so it can
                # honor cross-archive batches; rc1 keeps batch single-archive
                # by mapping the simpler entry_paths list to that shape with
                # the same zim_file_path repeated.
                entries = [
                    {"zim_file_path": zim_file_path, "entry_path": p}
                    for p in entry_paths
                ]
                return await ops.get_entries_data(
                    entries,
                    max_content_length=max_content_length,
                    compact=compact,
                )

            # Single-entry body view
            assert entry_path is not None
            if view == "summary":
                return await ops.get_entry_summary_data(
                    zim_file_path, entry_path, compact=compact
                )
            if view == "toc":
                return await ops.get_table_of_contents_data(zim_file_path, entry_path)
            if view == "structure":
                return await ops.get_article_structure_data(zim_file_path, entry_path)
            return await ops.get_zim_entry_data(
                zim_file_path,
                entry_path,
                max_content_length=max_content_length,
                content_offset=content_offset,
                compact=compact,
            )

        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            logger.error(f"Error in zim_get: {e}")
            return server._create_enhanced_error_message(
                operation="zim_get",
                error=e,
                context=f"Path: {entry_path or entry_paths}",
            )


def _validate_branch_combination(
    *,
    entry_path: Optional[str],
    entry_paths: Optional[List[str]],
    view: str,
    binary: bool,
    main_page: bool,
) -> Any:
    """Return a structured `invalid_path_combination` envelope if the
    requested branch is impossible, or None if the call is valid.
    Defense-in-depth — when wire-schema oneOf is enabled later, this
    layer catches invalid combos from flattening clients."""
    if view not in _VALID_VIEWS:
        return tool_error(
            operation="invalid_view",
            message=f"`view` must be one of {sorted(_VALID_VIEWS)}; got {view!r}",
        )
    if entry_path and entry_paths:
        return tool_error(
            operation="invalid_path_combination",
            message="`entry_path` and `entry_paths` are mutually exclusive.",
        )
    if binary:
        if entry_paths:
            return tool_error(
                operation="invalid_path_combination",
                message="Binary mode is single-entry only; use `entry_path`.",
            )
        if view != "full":
            return tool_error(
                operation="invalid_path_combination",
                message="Binary mode locks `view='full'`.",
            )
        if main_page:
            return tool_error(
                operation="invalid_path_combination",
                message="`main_page=True` cannot be combined with `binary=True`.",
            )
        if not entry_path:
            return tool_error(
                operation="invalid_path_combination",
                message="Binary mode requires `entry_path`.",
            )
    if main_page:
        if entry_path or entry_paths:
            return tool_error(
                operation="invalid_path_combination",
                message=(
                    "`main_page=True` is the path-free branch — omit "
                    "`entry_path` and `entry_paths`."
                ),
            )
        if view != "full":
            return tool_error(
                operation="invalid_path_combination",
                message="`main_page=True` locks `view='full'`.",
            )
    if not (entry_path or entry_paths or main_page):
        return tool_error(
            operation="invalid_path_combination",
            message=(
                "Provide one of `entry_path`, `entry_paths`, or " "`main_page=True`."
            ),
        )
    return None
