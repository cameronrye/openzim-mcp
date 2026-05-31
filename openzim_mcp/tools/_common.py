"""Shared helpers for the thin Phase F tool wrappers."""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

_DESCRIPTIONS_DIR = pathlib.Path(__file__).parent


def load_description(name: str) -> str:
    """Read the ``<name>_description.md`` markdown next to the tool modules.

    Centralizes the ``(_DIR / "...md").read_text(encoding="utf-8")`` line
    each wrapper repeated."""
    return (_DESCRIPTIONS_DIR / f"{name}_description.md").read_text(encoding="utf-8")


def tool_error_response(
    server: "OpenZimMcpServer",
    *,
    operation: str,
    error: Exception,
    context: Optional[str] = None,
) -> str:
    """Log + build the standard enhanced error payload for a tool's broad
    ``except`` block. Mirrors the b13 envelope every wrapper repeats."""
    import logging

    logging.getLogger("openzim_mcp.tools").error("Error in %s: %s", operation, error)
    return server._create_enhanced_error_message(
        operation=operation, error=error, context=context or ""
    )
