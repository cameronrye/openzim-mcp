"""Pin the public surface of the ``constants`` backward-compat facade.

``openzim_mcp.constants`` re-exports values from ``defaults`` for backward
compatibility; sibling modules and external consumers import them from here.
CodeQL's ``py/unused-import`` (alert #240) flagged the re-exports because the
facade lacked an ``__all__``. The fix declares ``__all__`` rather than
deleting the imports. These tests guard against a future "just delete the
unused import" regression that would silently break the public API.
"""

from __future__ import annotations

from openzim_mcp import constants


def test_all_names_are_defined() -> None:
    """Every name in ``__all__`` must resolve (guards F822-style drift and
    accidental deletion of a re-export)."""
    missing = [name for name in constants.__all__ if not hasattr(constants, name)]
    assert not missing, f"__all__ lists undefined names: {missing}"


def test_previously_flagged_reexports_present() -> None:
    """The exact re-exports CodeQL #240 flagged must remain importable from
    ``constants`` (they are consumed by server/security/main/content_processor
    and the documented backward-compat surface)."""
    flagged = [
        "FURNITURE_HEADING_DENYLIST",
        "FURNITURE_HEADING_PREFIXES",
        "RATE_LIMIT",
        "SERVER",
        "TOOL_MODE_ADVANCED",
        "TOOL_MODE_SIMPLE",
        "UNWANTED_HTML_SELECTORS",
        "VALID_TOOL_MODES",
        "VALID_TRANSPORT_TYPES",
        "ZIM_FILE_EXTENSION",
    ]
    for name in flagged:
        assert name in constants.__all__, f"{name} dropped from constants.__all__"
        assert hasattr(constants, name), f"{name} no longer importable from constants"


def test_all_has_no_duplicates_and_is_public() -> None:
    """``__all__`` entries are unique and public (no dunder/private names)."""
    assert len(constants.__all__) == len(set(constants.__all__)), "duplicate in __all__"
    assert all(not n.startswith("_") for n in constants.__all__)
