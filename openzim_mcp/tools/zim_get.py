"""zim_get — single/batch/binary/main-page entry fetch. Phase F surface.

Collapses 7 legacy tools (get_zim_entry + get_zim_entries + get_main_page +
get_binary_entry + get_entry_summary + get_table_of_contents +
get_article_structure) into one 4-branch entry point.

## Branch matrix (defense-in-depth handler validation)

  - Single body view: requires `entry_path`. Optional `view`,
    `max_content_length`, `content_offset`, `compact`, `compact_budget`.
    Forbidden: `entry_paths`, `binary=True`, `main_page=True`.
  - Single binary: requires `entry_path` + `binary=True`. `view`
    locked to ``"full"``. Optional `max_content_length` (caps the
    fetched BYTES — oversize entries return metadata with
    ``truncated: true``). Forbidden: `entry_paths`,
    `view∈{summary,toc,structure}`, `main_page=True`.
  - Batch: requires `entry_paths`. Full-body only — `view` is locked to
    "full" (a non-full `view` returns `invalid_path_combination`).
    Optional `max_content_length`, `compact`. Forbidden: `entry_path`,
    `binary=True`, `main_page=True`, non-zero `content_offset`.
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

from typing import TYPE_CHECKING, Any, List, Literal, Optional, Union

from ..constants import MAX_BATCH_SIZE
from ..defaults import RATE_LIMIT_COSTS
from ..responses import tool_error
from ._common import (
    _clamp_cost_to_capacity,
    enforce_rate_limit,
    load_description,
    tool_error_response,
)

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

_DESCRIPTION = load_description("zim_get")

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
            # Price/limit on the INTERNAL operation this call will dispatch
            # to. ``zim_get`` is a multiplexer and is absent from
            # ``RATE_LIMIT_COSTS``, so keying the bucket on the wire name
            # priced a 10MB binary fetch and a 50-article batch identically
            # with a single-article read, and made the documented
            # ``per_operation_limits`` overrides inert. Deliberately NOT
            # flat-mapped to one cost: the text path really is cheap.
            _rl_cost: Optional[int] = None
            if binary:
                _rl_op = "get_binary_entry"
            elif entry_paths:
                _rl_op = "get_zim_entries"
                # One token per requested entry — a batch is N reads. Price
                # the batch the server could actually serve, not the raw
                # caller-supplied length: the data layer rejects anything
                # above ``MAX_BATCH_SIZE``, so a 500-path list must not be
                # billed as 500 reads. The capacity clamp then keeps a legal
                # max-size batch at "drains the bucket" rather than "can
                # never succeed" (``acquire`` denies unconditionally above
                # ``burst_size``), and — because the total is clamped here —
                # the two debits below sum to at most one bucket.
                _rl_cost = _clamp_cost_to_capacity(
                    server,
                    _rl_op,
                    min(len(entry_paths), MAX_BATCH_SIZE)
                    * RATE_LIMIT_COSTS["get_zim_entries"],
                )
            elif view in ("summary", "toc", "structure"):
                _rl_op = "get_structure"
            else:
                _rl_op = "get_entry"
            # Split debit. The flat table cost is charged BEFORE validation so
            # a malformed call is never free — garbage must not bypass the
            # throttle. The batch-sized remainder is charged only once the
            # request is known to be dispatchable (below), because a request
            # that performs zero work must not cost full bucket capacity: an
            # `entry_path` + `entry_paths` combination used to debit the whole
            # bucket and then return `invalid_path_combination`, denying the
            # caller's next legitimate call.
            rl = enforce_rate_limit(server, _rl_op)
            if rl is not None:
                return rl
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
                content_offset=content_offset,
            )
            if err is not None:
                return err

            # Oversize batches are rejected by the data layer before any
            # entry is read — reject them here instead, before the remainder
            # debit, so the zero-work failure costs the flat price and comes
            # back as a structured envelope rather than a generic one after
            # draining the bucket.
            if entry_paths is not None and len(entry_paths) > MAX_BATCH_SIZE:
                return tool_error(
                    operation="invalid_batch_size",
                    message=(
                        f"`entry_paths` accepts at most {MAX_BATCH_SIZE} "
                        f"paths per call (provided: {len(entry_paths)}); "
                        f"split into multiple batches."
                    ),
                )

            # Dispatchable batch: charge the rest of the per-entry cost. The
            # flat table cost was already debited above, so the two together
            # come to the clamped batch price computed there.
            if _rl_cost is not None:
                _rl_remainder = _rl_cost - RATE_LIMIT_COSTS["get_zim_entries"]
                if _rl_remainder > 0:
                    rl = enforce_rate_limit(server, _rl_op, cost=_rl_remainder)
                    if rl is not None:
                        return rl

            if main_page:
                # ``max_content_length`` is documented as the body cap and is
                # not on this branch's forbidden list, so it must apply here
                # too rather than being dropped on the floor.
                return await ops.get_main_page_data(
                    zim_file_path,
                    compact=compact,
                    max_content_length=max_content_length,
                )
            if binary:
                assert entry_path is not None  # validator guarantees this
                # ``max_content_length`` caps the fetched BYTES here — it maps
                # onto the data layer's ``max_size_bytes`` (default 10MB when
                # None); oversize entries come back metadata-only with
                # ``truncated: true``, the recovery the resource layer's
                # oversize-binary error directs callers to.
                return await ops.get_binary_entry_data(
                    zim_file_path, entry_path, max_size_bytes=max_content_length
                )
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
            return tool_error_response(
                server,
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
    content_offset: int = 0,
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
    if entry_paths and view != "full":
        # H13: the batch branch calls get_entries_data, which has no ``view``
        # parameter and always returns full article bodies. Silently ignoring a
        # requested ``view`` (the model believes it asked for summaries and
        # gets full bodies at much higher token cost) is worse than an explicit
        # rejection. Batch is full-body only; fetch other views per entry.
        return tool_error(
            operation="invalid_path_combination",
            message=(
                "Batch mode (`entry_paths`) returns full article bodies only; "
                f"`view={view!r}` is not supported. Fetch a summary / toc / "
                "structure with a single-entry `entry_path` call instead."
            ),
        )
    if entry_paths and content_offset:
        # Like the H13 view guard: get_entries_data always renders each
        # entry's first page (it has no offset parameter), yet truncated
        # batch bodies still advertise the `pass content_offset=N` footer.
        # Silently dropping the offset would loop the caller on page 1
        # forever, so reject the combination with the working recovery.
        return tool_error(
            operation="invalid_path_combination",
            message=(
                "Batch mode (`entry_paths`) does not support "
                "`content_offset` — batch entries always return their first "
                "page. Page a long entry with a single-entry `entry_path` "
                "call instead."
            ),
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
