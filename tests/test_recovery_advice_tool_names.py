"""Recovery advice may only instruct tools the client can actually see.

``tests/test_prompts.py::TestPromptsReferenceRegisteredTools`` already
enforces this invariant for *prompt* bodies. The same invariant was never
enforced for the recovery footers ``format_footer`` emits when a query
fails, nor for the ``render_search_all`` no-results / all-archives-failed
bodies — and both had drifted: five of the names they instructed
(``find_entry_by_title``, ``browse_namespace``, ``walk_namespace``,
``list_namespaces``, ``list_zim_files``) were deleted in v2.0.0.

This module generalises the prompts guard over the two tool modes. The
simple half matters most: ``tool_mode='simple'`` is the default
(``ServerDefaults.TOOL_MODE``) and what the README tells every user to
copy-paste, and it registers ``zim_query`` alone. Naming *any* other tool
there describes a tool the client cannot see — at the exact moment the
model is recovering from a failure.
"""

from __future__ import annotations

import re
import tempfile
from typing import Iterator, List, Set, Tuple

import pytest

from openzim_mcp.compact_renderers import render_search_all
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.meta import format_footer
from openzim_mcp.server import OpenZimMcpServer

from .test_phase_f_migration import LEGACY_TO_PHASE_F

_ALLOWED_DIR = tempfile.mkdtemp(prefix="openzim_mcp_recovery_advice_")

TOOL_MODES = ("simple", "advanced")

# Every ``reason`` that routes ``format_footer`` into its advice branches.
# Kept as a literal so a new branch added without a test here shows up as a
# drift between this tuple and the reason set in ``meta.format_footer``
# (pinned by ``test_advice_reasons_match_the_implementation``).
ADVICE_REASONS = (
    "0_hits",
    "low_relevance",
    "bad_query",
    "no_xapian_index",
    "bad_namespace",
    "no_content_type_match",
    "sample_only",
    "archive_unavailable",
    "search_all_budget_exceeded",
)

# Backticked bare identifiers that are deliberately NOT tool calls: tool
# *parameters* and query vocabulary a model passes rather than invokes.
# ``test_non_tool_vocabulary_is_not_a_tool_name`` keeps this list from being
# used to smuggle a tool name past the guard.
NON_TOOL_VOCABULARY = frozenset(
    {
        "content_type",  # zim_search / zim_browse filter argument
    }
)

# A backticked span is read as a tool reference when it is a bare snake_case
# identifier, or that identifier immediately followed by a call paren —
# ``zim_browse`` and ``zim_browse(mode='walk')`` both count, while
# ``synthesize=True`` (an argument), ``tell me about X`` (query prose) and
# ``OPENZIM_MCP_...`` (an env var) do not.
_BACKTICKED = re.compile(r"`([^`]+)`")
_TOOL_SHAPED = re.compile(r"^([a-z_][a-z0-9_]*)\s*(?:\(|$)")


def _config(tool_mode: str) -> OpenZimMcpConfig:
    """A config for ``tool_mode``.

    ``tests/conftest.py``'s ``test_config`` fixture pins
    ``tool_mode='advanced'``, so the simple half has to build its own.
    """
    return OpenZimMcpConfig(allowed_directories=[_ALLOWED_DIR], tool_mode=tool_mode)


def _registered_tools(tool_mode: str) -> Set[str]:
    return set(OpenZimMcpServer(_config(tool_mode)).mcp._tool_manager._tools)


def _advice_strings(tool_mode: str) -> Iterator[Tuple[str, str]]:
    """Yield ``(label, text)`` for every user-facing recovery string."""
    for reason in ADVICE_REASONS:
        yield (
            f"format_footer(reason={reason!r})",
            format_footer({"reason": reason}, footer_enabled=True, tool_mode=tool_mode),
        )
    yield (
        "render_search_all(no hits)",
        render_search_all(
            {"results": [], "files_searched": 2, "files_failed": 0},
            "photosynthesis",
            tool_mode=tool_mode,
        ),
    )
    yield (
        "render_search_all(all failed)",
        render_search_all(
            {"results": [], "files_searched": 2, "files_failed": 2},
            "photosynthesis",
            tool_mode=tool_mode,
        ),
    )


def _tool_references(text: str) -> List[str]:
    """Identifiers in ``text`` that read as an instruction to call a tool."""
    found: List[str] = []
    for span in _BACKTICKED.findall(text):
        m = _TOOL_SHAPED.match(span.strip())
        if m:
            found.append(m.group(1))
    return found


class TestRecoveryAdviceReferencesRegisteredTools:
    """No recovery string may instruct a tool absent from the live registry."""

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_advice_names_only_registered_tools(self, tool_mode: str) -> None:
        registered = _registered_tools(tool_mode)
        allowed = registered | NON_TOOL_VOCABULARY
        offenders = []
        for label, text in _advice_strings(tool_mode):
            for name in _tool_references(text):
                if name not in allowed:
                    offenders.append(f"{label}: `{name}` in {text!r}")
        assert not offenders, (
            f"recovery advice in tool_mode={tool_mode!r} names identifiers the "
            f"client cannot call: {offenders}; registered tools: "
            f"{sorted(registered)}"
        )

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_advice_never_names_a_deleted_tool(self, tool_mode: str) -> None:
        """Substring scan — catches a legacy name even outside backticks."""
        offenders = []
        for label, text in _advice_strings(tool_mode):
            for legacy in LEGACY_TO_PHASE_F:
                if legacy in text:
                    offenders.append(f"{label}: {legacy!r}")
        assert not offenders, (
            f"recovery advice in tool_mode={tool_mode!r} names tool(s) deleted "
            f"in v2.0.0: {offenders}"
        )

    def test_simple_mode_advice_names_no_tool_at_all(self) -> None:
        """Simple mode registers zim_query alone, so advice routes by prose.

        Even a *correct* advanced tool name would be unreachable here; the
        recovery has to be phrased as something zim_query can act on.
        """
        offenders = []
        for label, text in _advice_strings("simple"):
            refs = [n for n in _tool_references(text) if n not in NON_TOOL_VOCABULARY]
            if refs:
                offenders.append(f"{label}: {refs}")
        assert not offenders, (
            "simple-mode recovery advice must not name a tool; found: " f"{offenders}"
        )

    def test_advanced_mode_advice_routes_to_the_v2_replacements(self) -> None:
        """The advanced half is not merely tool-free — it names the successor.

        Guards against "fix" by deletion: dropping the tool name entirely
        would satisfy the two scans above while stripping the recovery of
        its actionable next step.
        """
        expected = {
            "no_xapian_index": "zim_search",
            "bad_namespace": "zim_metadata",
            "no_content_type_match": "zim_browse",
            "sample_only": "zim_browse",
            "archive_unavailable": "zim_health",
        }
        for reason, tool in expected.items():
            footer = format_footer(
                {"reason": reason}, footer_enabled=True, tool_mode="advanced"
            )
            assert tool in _tool_references(footer), (
                f"advanced footer for {reason!r} should route to {tool}; "
                f"got {footer!r}"
            )
        for label, text in _advice_strings("advanced"):
            if "render_search_all" in label:
                assert "zim_health" in _tool_references(
                    text
                ), f"advanced {label} should route to zim_health; got {text!r}"

    def test_non_tool_vocabulary_is_not_a_tool_name(self) -> None:
        """The allowlist cannot be used to wave a tool name through."""
        tool_names = _registered_tools("advanced") | set(LEGACY_TO_PHASE_F)
        assert not (NON_TOOL_VOCABULARY & tool_names)

    def test_advice_reasons_match_the_implementation(self) -> None:
        """Every advice reason in meta.py is exercised by this module."""
        import inspect

        source = inspect.getsource(format_footer)
        declared = set(re.findall(r'reason == "([a-z_0-9]+)"', source))
        missing = declared - set(ADVICE_REASONS)
        assert not missing, (
            f"format_footer grew advice branch(es) {sorted(missing)} that this "
            "guard does not scan"
        )
