"""Pagination cursor primitives — versioned, tool-bound, opaque.

v2 Phase B promotes the v1 ``PaginationCursor`` (offset/limit/query only) to
a tool-bound, versioned cursor. The wire format is a URL-safe base64 encoding
of a JSON object:

    {"v": 1, "t": "<tool_name>", "s": {<tool-specific state>}}

* ``v`` lets us add new required fields later without a wire-format break.
* ``t`` rejects cross-tool cursor reuse (a search cursor passed to browse
  raises ``CursorMismatchError`` instead of silently misbehaving).
* ``s`` carries the per-tool paging state — offset/limit/query for search,
  scan_at for walk_namespace, etc.
* Cross-tool reuse raises ``CursorMismatchError`` (a ``ValueError`` subclass).

Decode failures and tool mismatches both subclass ``ValueError`` so a single
except-clause in tool wrappers catches both.
"""

from __future__ import annotations

import base64
import json
from typing import TypedDict, cast

CURRENT_VERSION = 1


class CursorState(TypedDict, total=False):
    """Tool-specific state inside a cursor payload."""

    o: int  # offset (search, browse, links)
    l: int  # noqa: E741 — single-letter wire-format key, kept short to keep cursors small
    q: str  # query (search, search_all per-file)
    ns: str  # namespace (browse_namespace)
    scan_at: int  # entry id (walk_namespace — replaces today's int cursor)
    ep: str  # entry path (extract_article_links)
    k: str  # kind: "internal" | "external" | "media"
    ct: str  # content_type (search_with_filters)


class CursorPayload(TypedDict):
    """Full cursor payload: version, tool name, and tool-specific state."""

    v: int  # cursor version, currently 1
    t: str  # tool name (e.g., "browse_namespace")
    s: CursorState  # tool-specific state


class CursorMismatchError(ValueError):
    """Raised when a cursor's ``t`` field doesn't match ``expected_tool``."""


class Cursor:
    """Encode/decode opaque pagination cursors."""

    @staticmethod
    def encode(
        *, tool: str, state: "CursorState", version: int = CURRENT_VERSION
    ) -> str:
        """Encode a cursor payload as URL-safe base64 JSON.

        Args:
            tool: Tool name. Decoders verify this matches their expected tool.
            state: Tool-specific paging state (offset/limit/query/scan_at/etc.).
            version: Cursor format version. Defaults to ``CURRENT_VERSION``.

        Returns:
            URL-safe base64 string suitable for ``next_cursor`` in a tool response.
        """
        payload: CursorPayload = {"v": version, "t": tool, "s": state}
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")

    @staticmethod
    def decode(token: str, *, expected_tool: str) -> "CursorPayload":
        """Decode a cursor and verify it was issued by ``expected_tool``.

        Args:
            token: A previously-encoded cursor. Padding-stripped tokens are tolerated.
            expected_tool: The tool whose state ``token`` is expected to carry.

        Returns:
            The decoded payload dict with keys ``v``, ``t``, ``s``.

        Raises:
            ValueError: Token isn't valid base64 / JSON, or is missing required
                fields, or carries an unsupported version. Subclasses include:
            CursorMismatchError: Token's ``t`` field doesn't match ``expected_tool``.
        """
        try:
            padded = token + "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
            payload = json.loads(raw)
        except Exception as e:
            raise ValueError(f"Invalid pagination cursor: {e}") from e

        if not isinstance(payload, dict):
            raise ValueError("Invalid pagination cursor: payload must be an object")
        if "v" not in payload or "t" not in payload or "s" not in payload:
            raise ValueError(
                "Invalid pagination cursor: missing required fields (v, t, s)"
            )
        if payload["v"] != CURRENT_VERSION:
            raise ValueError(
                f"Unsupported cursor version: got v={payload['v']}, expected v={CURRENT_VERSION}"
            )
        if not isinstance(payload["t"], str):
            raise ValueError("Invalid pagination cursor: 't' must be a string")
        if not isinstance(payload["s"], dict):
            raise ValueError("Invalid pagination cursor: 's' must be an object")
        if payload["t"] != expected_tool:
            raise CursorMismatchError(
                f"Cursor was issued by '{payload['t']}', cannot be used by '{expected_tool}'"
            )
        return cast("CursorPayload", payload)
