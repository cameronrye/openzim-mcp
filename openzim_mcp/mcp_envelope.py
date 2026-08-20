"""MCP ``CallToolResult`` envelope conformance.

Phase F tools signal failure by *returning* a structured error envelope
(``{"error": true, "operation": ..., "message": ...}``, built by
:func:`openzim_mcp.responses.tool_error`) rather than by raising. That keeps
the failure machine-readable and lets a small model self-correct from the
``message`` — but it also meant the value travelled the SDK's ordinary success
path, so every failure reached the client with ``isError=false``.

That is a protocol defect, not a cosmetic one. Agent frameworks branch on
``isError`` to decide whether to surface, retry, or stop; with the flag always
false, a security denial is indistinguishable from a successful search that
happened to find nothing. Raising instead would fix the flag but discard the
envelope — the SDK stringifies exceptions into a bare text block.

:class:`EnvelopeAwareMCPServer` gets both. It intercepts the tool return value
before the SDK converts it, and when the value is an error envelope it emits a
``CallToolResult`` with ``is_error=True`` whose ``content`` is byte-identical to
what the plain dict return produced. Clients that parse the body keep working;
clients that check the flag start working.

The same class also stamps the per-URI half of the 2026-07-28 cache hints. The
server-wide ``cache_hints`` map is keyed by *method*, so one TTL has to cover
every ``resources/read`` — and because that method serves both sealed archives
and a live directory scan, the honest method-wide value is the short one. Only
a handler can tell the two apart, which is what :meth:`_handle_read_resource`
does here.

It is also where ``prompts/get`` failures get their JSON-RPC codes. The SDK's
prompt layer raises bare ``ValueError`` for an unknown name, a missing required
argument and an argument the prompt does not declare; the legacy dispatcher
answers those with the meaningless ``code=0`` and the modern one collapses
them to ``-32603 Internal server error`` with no detail, and both put either
nothing or pydantic's rendered report on the wire. :meth:`get_prompt` makes
the caller's mistakes ``-32602`` with a message naming the prompt and the
arguments, and a fault inside a prompt body ``-32603`` naming only the prompt.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pydantic_core
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import MCPError
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    CallToolResult,
    GetPromptResult,
    InputRequiredResult,
    ReadResourceResult,
    TextContent,
    TextResourceContents,
)
from pydantic import ValidationError

__all__ = ["EnvelopeAwareMCPServer", "is_tool_error_envelope"]

logger = logging.getLogger(__name__)

# The one ``zim://`` URI whose content is not fixed by a sealed archive file:
# it is a live scan of the allowed directories, so it must keep the
# watcher-bounded TTL that the method-wide hint supplies.
_LIVE_SCAN_URI = "zim://files"

# Per-entry URIs (``zim://{name}/entry/{path}``) are archive-backed too, but
# the long TTL would be dishonest on them: a replacement publishes
# ``resources/updated`` only for the overview URI, and both SDK delivery and
# client-side eviction are exact-URI, so nothing could ever invalidate a
# cached entry read before the TTL ran out. They stay on the watcher-bounded
# method-wide hint instead.
_ENTRY_URI_MARKER = "/entry/"

# The exact keys ``responses.tool_error`` always sets. Matching all three (and
# ``error is True`` by identity, not truthiness) keeps an ordinary payload that
# merely carries an ``error`` field from being misread as a failure.
_ENVELOPE_REQUIRED_KEYS = ("error", "operation", "message")


def is_tool_error_envelope(value: Any) -> bool:
    """True when ``value`` is a :func:`openzim_mcp.responses.tool_error` payload."""
    if not isinstance(value, dict):
        return False
    if value.get("error") is not True:
        return False
    return all(
        isinstance(value.get(key), str)
        for key in _ENVELOPE_REQUIRED_KEYS
        if key != "error"
    )


def _is_overview_error_body(result: ReadResourceResult) -> bool:
    """True when a ``zim://{name}`` overview reported failure inside its body.

    The overview resource deliberately returns errors as *successful* JSON
    bodies — ``{"error": ...}`` for a missing archive, ``*_error`` keys for
    partial section failures (a contract pinned in ``test_resources.py``).
    Those bodies describe a moment, not the sealed archive, so they must not
    be stamped with the hour-long TTL: a cached not-found error would outlive
    the operator dropping the archive into place, and nothing ever publishes
    a ``resources/updated`` that could evict it.
    """
    if len(result.contents) != 1:
        return False
    sole = result.contents[0]
    if not isinstance(sole, TextResourceContents):
        return False
    # Cheap probe first. This runs on the response path of every archive-backed
    # read, and the alternative is re-parsing a body the handler just
    # serialized — full metadata dict, namespace summary, and up to a
    # 2000-character main-page preview — on the event loop, to answer one
    # boolean. Both key shapes end in ``error"`` once serialized, so a body
    # without that substring cannot be an error body; one that has it (an
    # article mentioning the word) still gets the exact check below.
    if 'error"' not in sole.text:
        return False
    try:
        payload = json.loads(sole.text)
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    return "error" in payload or any(key.endswith("_error") for key in payload)


def _serialize_envelope(payload: dict) -> str:
    """Render an envelope exactly as the SDK's dict-return path does.

    ``func_metadata._convert_to_content`` serializes a non-str result with
    ``pydantic_core.to_json(..., fallback=str, indent=2)``. Reusing the same
    call keeps the body byte-for-byte identical to the pre-fix wire format, so
    this stays a flag change rather than a payload change.
    """
    return pydantic_core.to_json(payload, fallback=str, indent=2).decode()


def _validation_error_in_chain(exc: BaseException) -> ValidationError | None:
    """The pydantic ``ValidationError`` an SDK prompt failure wraps, if any.

    ``Prompt.render`` stringifies the ``validate_call`` failure into a
    ``ValueError`` and ``MCPServer.get_prompt`` wraps that once more, so the
    wire would carry pydantic's report verbatim; the original stays reachable
    through ``__cause__`` / ``__context__`` and is what the classifier needs.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ValidationError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _invalid_params(message: str, **data: Any) -> MCPError:
    """An ``-32602`` naming what the caller got wrong, with the same facts in ``data``."""
    return MCPError(code=INVALID_PARAMS, message=message, data=data)


def error_result(payload: dict) -> CallToolResult:
    """Wrap an error envelope as a failed ``CallToolResult``.

    ``structuredContent`` is deliberately left unset: the tool advertises no
    ``outputSchema``, and per the MCP spec ``structuredContent`` is the
    counterpart to one. The envelope stays available as parseable JSON in
    ``content``, which is where every existing client already reads it.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=_serialize_envelope(payload))],
        is_error=True,
    )


class EnvelopeAwareMCPServer(MCPServer):
    """``MCPServer`` that maps returned error envelopes onto ``is_error=True``.

    The override is at ``call_tool`` — the single point where every tool's
    return value passes through — so tools keep returning plain dicts and no
    registration site has to know about the protocol envelope.

    Args:
        archive_read_ttl_ms: TTL stamped on reads of archive-backed ``zim://``
            URIs. ``0`` leaves the result alone, so those reads fall back to
            the server-wide ``resources/read`` hint.
    """

    def __init__(self, *args: Any, archive_read_ttl_ms: int = 0, **kwargs: Any) -> None:
        """Capture the archive TTL, then defer to the SDK constructor."""
        super().__init__(*args, **kwargs)
        self._archive_read_ttl_ms = archive_read_ttl_ms

    async def _handle_read_resource(
        self, ctx: Any, params: Any
    ) -> ReadResourceResult | InputRequiredResult:
        """Stamp the long TTL on reads whose content a sealed archive fixes.

        ``apply_cache_hint`` fills only fields a handler left unset, so setting
        ``ttl_ms`` here wins over the method-wide hint for exactly these URIs
        while ``cache_scope`` still comes from the server-wide value. The
        result is built with ``model_copy(update=...)``, which records the
        field in ``model_fields_set`` — the flag the SDK keys that precedence
        on.

        This overrides a private SDK method, which the v2 port otherwise moved
        away from. It is the extension point the caching design implies: the
        SDK's own docs say a per-result hint is set "by returning a result with
        explicit ``ttl_ms``", and on this layer the only code that returns a
        ``ReadResourceResult`` is this handler — ``MCPServer`` binds it as
        ``on_read_resource`` at construction, so a subclass override is what
        the lowlevel server ends up calling. If a future SDK stops routing
        through it, the per-URI TTL tests fail rather than the hint silently
        reverting to the method-wide value.

        Which URIs qualify is stated as an exception rather than a match
        because every registered resource except ``zim://files`` is
        archive-backed. ``test_every_registered_resource_has_a_deliberate_ttl``
        fails if that stops being true. Two further carve-outs keep the long
        TTL honest: per-entry reads (see ``_ENTRY_URI_MARKER``) and overview
        reads whose JSON body reports an error (see
        ``_is_overview_error_body``) have no invalidation story, so they stay
        on the watcher-bounded method-wide hint.
        """
        result = await super()._handle_read_resource(ctx, params)
        if (
            self._archive_read_ttl_ms <= 0
            or isinstance(result, InputRequiredResult)
            or str(params.uri) == _LIVE_SCAN_URI
            or _ENTRY_URI_MARKER in str(params.uri)
            or _is_overview_error_body(result)
        ):
            return result
        return result.model_copy(update={"ttl_ms": self._archive_read_ttl_ms})

    async def run_stdio_async(self) -> None:
        """Serve stdio through the frame-answering wrapper in ``sdk_compat``.

        Body-identical to the SDK's ``run_stdio_async`` except for the
        transport context manager: the SDK's stdio server hands undecodable
        lines to a dispatcher that drops them silently, and the wrapper
        answers them with the JSON-RPC error the spec requires. Retire with
        the wrapper (see ``sdk_compat`` for the canary).
        """
        from .sdk_compat import stdio_server_answering_malformed_frames

        async with stdio_server_answering_malformed_frames() as (
            read_stream,
            write_stream,
        ):
            await self._lowlevel_server.run(
                read_stream,
                write_stream,
                self._lowlevel_server.create_initialization_options(),
            )

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        context: Context[Any, Any] | None = None,
    ) -> GetPromptResult | InputRequiredResult:
        """Render a prompt, answering client mistakes as ``-32602``.

        The checks run *before* the SDK's own because its prompt manager
        raises plain ``ValueError`` for an unknown name and a missing required
        argument, and ``Prompt.render`` turns the ``validate_call`` rejection
        of an undeclared argument into a ``ValueError`` carrying pydantic's
        full report — none of which the dispatchers classify (legacy pins
        ``code=0``, modern discards the text as ``-32603``). ``MCPError`` is
        the one exception type both eras pass through with its code intact.

        Every message names the prompt and lists arguments sorted, so the
        text is stable (the SDK interpolated an unordered ``set``) and free of
        ``register_prompts.<locals>`` paths and pydantic doc URLs. A fault
        raised inside a prompt body is a server-side problem: it stays logged
        with its traceback by the SDK and reaches the client as ``-32603``
        naming only the prompt.
        """
        prompt = self._prompt_manager.get_prompt(name)
        if prompt is None:
            available = sorted(p.name for p in self._prompt_manager.list_prompts())
            raise _invalid_params(
                f"Unknown prompt {name!r}; available prompts: "
                f"{', '.join(available) or 'none'}",
                prompt=name,
                available=available,
            )

        declared = {arg.name: arg.required for arg in prompt.arguments or []}
        provided = set(arguments or {})
        missing = sorted(
            arg
            for arg, required in declared.items()
            if required and arg not in provided
        )
        if missing:
            raise _invalid_params(
                f"Prompt {name!r} is missing required argument(s): "
                f"{', '.join(missing)}",
                prompt=name,
                missing=missing,
            )
        unexpected = sorted(provided - declared.keys())
        if unexpected:
            raise _invalid_params(
                f"Prompt {name!r} does not accept argument(s): "
                f"{', '.join(unexpected)}; it declares: "
                f"{', '.join(sorted(declared)) or 'no arguments'}",
                prompt=name,
                unexpected=unexpected,
                declared=sorted(declared),
            )

        try:
            return await super().get_prompt(name, arguments, context)
        except MCPError:
            raise
        except Exception as exc:
            validation = _validation_error_in_chain(exc)
            if validation is not None:
                # Errors located at a declared argument are the caller's
                # (a value the annotation rejects); anything else — say a
                # prompt body returning a malformed message — is ours.
                invalid = sorted(
                    {str(err["loc"][0]) for err in validation.errors() if err["loc"]}
                    & declared.keys()
                )
                if invalid:
                    raise _invalid_params(
                        f"Prompt {name!r} received invalid value(s) for "
                        f"argument(s): {', '.join(invalid)}",
                        prompt=name,
                        invalid=invalid,
                    ) from exc
            raise MCPError(
                code=INTERNAL_ERROR, message=f"Error rendering prompt {name!r}"
            ) from exc

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[Any, Any] | None = None,
    ) -> CallToolResult | InputRequiredResult:
        if context is None:
            context = Context(mcp_server=self, subscriptions=self._subscriptions)
        # convert_result=False so the raw return value is still inspectable;
        # the success path is then converted by the same
        # ``fn_metadata.convert_result`` the base class would have used, which
        # keeps that path byte-identical to a stock server.
        result = await self._tool_manager.call_tool(
            name, arguments, context, convert_result=False
        )
        if is_tool_error_envelope(result):
            return error_result(result)

        tool = self._tool_manager.get_tool(name)
        if tool is None:  # pragma: no cover - call_tool raises on unknown names
            return result  # type: ignore[no-any-return]
        converted: CallToolResult | InputRequiredResult = (
            tool.fn_metadata.convert_result(result)
        )
        return converted
