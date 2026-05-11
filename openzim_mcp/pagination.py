"""Pagination cursor primitives — versioned, tool-bound, opaque.

v2 Phase B promotes the v1 ``PaginationCursor`` (offset/limit/query only) to
a tool-bound, versioned cursor. The wire format is a URL-safe base64 encoding
of a JSON object:

    {"v": 2, "t": "<tool_name>", "s": {<tool-specific state>}}

* ``v`` lets us add new required fields later without a wire-format break.
* ``t`` rejects cross-tool cursor reuse (a search cursor passed to browse
  raises ``CursorMismatchError`` instead of silently misbehaving).
* ``s`` carries the per-tool paging state — offset/limit/query for search,
  scan_at for walk_namespace, etc.
* ``s.ai`` (archive identity) is included on every cursor whose result
  depends on a specific ZIM file; mismatches raise ``CursorMismatchError``
  so a cursor from archive A can't be resubmitted against archive B.
* Cross-tool reuse raises ``CursorMismatchError`` (a ``ValueError`` subclass).

Version bump v1→v2 (alpha-line clean break): added ``ai`` archive identity
and required ``ns`` on walk_namespace/browse_namespace cursors. v1 cursors
are rejected with a clear error so callers learn to re-fetch rather than
silently follow stale state.

Decode failures and tool mismatches both subclass ``ValueError`` so a single
except-clause in tool wrappers catches both.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import TypedDict, Union, cast

CURRENT_VERSION = 2


def archive_identity(validated_path: Union[Path, str]) -> str:
    """Short stable token derived from a validated archive path.

    Used in cursor ``s.ai`` so a cursor issued for archive A can't be
    resubmitted against archive B. SHA-256 truncated to 12 hex chars —
    collision probability is ~2^-48 across a session, well under the
    practical archive count.
    """
    raw = str(validated_path).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


class CursorState(TypedDict, total=False):
    """Tool-specific state inside a cursor payload."""

    o: int  # offset (search, browse, links)
    l: int  # noqa: E741 — single-letter wire-format key, kept short to keep cursors small
    q: str  # query (search, search_all per-file)
    ns: str  # namespace (browse_namespace, walk_namespace)
    scan_at: int  # entry id (walk_namespace — replaces today's int cursor)
    ep: str  # entry path (extract_article_links)
    k: str  # kind: "internal" | "external" | "media"
    ct: str  # content_type (search_with_filters)
    ai: str  # archive identity (short SHA-256 token of validated_path)


class CursorPayload(TypedDict):
    """Full cursor payload: version, tool name, and tool-specific state."""

    v: int  # cursor version, currently 1
    t: str  # tool name (e.g., "browse_namespace")
    s: CursorState  # tool-specific state


class CursorMismatchError(ValueError):
    """Raised when a cursor's ``t`` field doesn't match ``expected_tool``,
    or its ``s.ai`` archive identity doesn't match the call's archive."""


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

    @staticmethod
    def verify_archive_identity(
        state: "CursorState", *, expected: str, tool: str
    ) -> None:
        """Verify ``s.ai`` in a decoded cursor matches the current archive.

        Tools that page over a specific ZIM file (extract_article_links,
        walk_namespace, browse_namespace, search_zim_file) call this
        after ``decode`` to ensure the cursor's archive identity matches
        the archive being passed to the follow-up call.

        Passing a cursor from archive A back to a call against archive B
        previously silently returned results from B starting at the
        offset A had reached — confusing and wrong. Cursors issued
        before v2 (no ``ai`` field) were already rejected by the version
        check; v2+ cursors always carry ``ai``.

        Raises:
            CursorMismatchError: ``s.ai`` is absent or doesn't match.
        """
        actual = state.get("ai")
        if actual is None:
            raise CursorMismatchError(
                f"Cursor for '{tool}' missing archive-identity field. "
                f"Re-issue the request without a cursor."
            )
        if actual != expected:
            raise CursorMismatchError(
                f"Cursor for '{tool}' was issued against a different archive. "
                f"Drop the cursor and start the paginated call over."
            )
