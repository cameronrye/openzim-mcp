"""Recovery advice may only instruct tools the client can actually see.

``tests/test_prompts.py::TestPromptsReferenceRegisteredTools`` already
enforces this invariant for *prompt* bodies. The same invariant was never
enforced for the recovery strings the server emits when a call fails, and
they had drifted: five of the names they instructed
(``find_entry_by_title``, ``browse_namespace``, ``walk_namespace``,
``list_namespaces``, ``list_zim_files``) were deleted in v2.0.0.

This module generalises the prompts guard over the two tool modes. The
simple half matters most: ``tool_mode='simple'`` is the default
(``ServerDefaults.TOOL_MODE``) and what the README tells every user to
copy-paste, and it registers ``zim_query`` alone. Naming any *other* tool
there describes a tool the client cannot see — at the exact moment the
model is recovering from a failure.

Three rules, of which the third is the one that makes the first two worth
having:

* **Rendered scan** — every recovery string the covered surfaces produce is
  re-rendered in both modes and checked against that mode's live registry.
* **Successor mapping** — the advanced half must name the v2 replacement,
  so a future "fix" cannot satisfy the scan by deleting the tool name and
  stripping the recovery of its actionable step.
* **Coverage** — a static walk of *every* runtime string literal in the
  ``openzim_mcp`` package. A module that names a tool in user-facing text
  must be one this module actually renders, or an explicitly justified
  advanced-only surface. Without this the guard would only ever be as good
  as the list of functions someone remembered to add to it, which is how
  ``zim/structure.py`` shipped ``zim_search`` advice to a simple-mode
  client while a guard for exactly that defect sat green next to it.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Dict, Iterator, List, Set, Tuple

import pytest

import openzim_mcp
from openzim_mcp import error_messages as em
from openzim_mcp.compact_renderers import render_search_all
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.meta import format_footer
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.zim.structure import _entry_not_found_error

from .test_phase_f_migration import LEGACY_TO_PHASE_F

TOOL_MODES = ("simple", "advanced")

_PACKAGE_ROOT = pathlib.Path(openzim_mcp.__file__).resolve().parent

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
# *parameters* a model passes rather than invokes.
# ``test_non_tool_vocabulary_is_not_a_tool_name`` keeps this list from being
# used to smuggle a tool name past the guard.
NON_TOOL_VOCABULARY = frozenset(
    {
        "content_type",  # zim_search / zim_browse filter argument
        "zim_file_path",  # the archive-selection argument every tool takes
    }
)

# Modules whose user-facing recovery strings this module RENDERS, and so
# checks per mode. Coverage is tracked per ``(module, tool)`` pair rather
# than per module — a module being rendered at all must not silently excuse
# a tool name that never appears in anything rendered.
# ``test_every_covered_module_contributes_a_rendered_string`` pins that each
# name below really does contribute.
RENDERED_MODULES = frozenset(
    {
        "openzim_mcp/meta.py",
        "openzim_mcp/compact_renderers.py",
        "openzim_mcp/error_messages.py",
        "openzim_mcp/zim/structure.py",
    }
)

# Runtime strings that name an advanced-only tool but can never reach a
# simple-mode client, with the structural reason. Keyed by (module, tool) so
# a NEW tool name appearing in one of these modules is still a failure.
#
# * ``tools/resource_tools.py`` — MCP Resources are registered only on the
#   advanced surface (``tools/__init__.register_phase_f_tools`` returns
#   before ``register_resources``), pinned by
#   ``test_simple_mode_registers_no_resources``.
# * ``zim/structure.py`` — the ``zim_get`` names live in
#   ``get_section_data``'s section-miss payloads. Simple mode never forwards
#   them: ``SimpleToolsHandler._handle_get_section`` resolves the heading
#   against its own list and writes its own not-found / empty-section bodies,
#   pinned by ``test_simple_mode_get_section_never_forwards_the_payload``.
#   (Its ``zim_search`` name is a different story — that one IS echoed to
#   simple-mode clients, which is why ``_entry_not_found_error`` is rendered
#   below rather than exempted here.)
ADVANCED_ONLY_ADVICE: Dict[Tuple[str, str], str] = {
    ("openzim_mcp/tools/resource_tools.py", "zim_get"): (
        "MCP Resources register on the advanced surface only"
    ),
    ("openzim_mcp/zim/structure.py", "zim_get"): (
        "section-miss payloads; simple mode renders its own body instead"
    ),
}

# A backticked span is read as a tool reference when it is a bare snake_case
# identifier, or that identifier immediately followed by a call paren —
# ``zim_browse`` and ``zim_browse(mode='walk')`` both count, while
# ``synthesize=True`` (an argument), ``tell me about X`` (query prose) and
# ``OPENZIM_MCP_...`` (an env var) do not.
_BACKTICKED = re.compile(r"`([^`]+)`")
_TOOL_SHAPED = re.compile(r"^([a-z_][a-z0-9_]*)\s*(?:\(|$)")


@pytest.fixture(scope="session")
def servers(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, OpenZimMcpServer]:
    """One server per tool mode.

    ``tests/conftest.py``'s ``test_config`` fixture pins
    ``tool_mode='advanced'``, so the simple half has to build its own. The
    allowed directory comes from ``tmp_path_factory`` rather than a
    module-level ``mkdtemp`` so pytest owns its lifetime.
    """
    directory = str(tmp_path_factory.mktemp("recovery_advice"))
    return {
        mode: OpenZimMcpServer(
            OpenZimMcpConfig(allowed_directories=[directory], tool_mode=mode)
        )
        for mode in TOOL_MODES
    }


@pytest.fixture(scope="session")
def registries(servers: Dict[str, OpenZimMcpServer]) -> Dict[str, Set[str]]:
    return {
        mode: set(server.mcp._tool_manager._tools) for mode, server in servers.items()
    }


def _footer_strings(tool_mode: str) -> Iterator[Tuple[str, str, str]]:
    for reason in ADVICE_REASONS:
        yield (
            "openzim_mcp/meta.py",
            f"format_footer(reason={reason!r})",
            format_footer({"reason": reason}, footer_enabled=True, tool_mode=tool_mode),
        )


def _search_all_strings(tool_mode: str) -> Iterator[Tuple[str, str, str]]:
    yield (
        "openzim_mcp/compact_renderers.py",
        "render_search_all(no hits)",
        render_search_all(
            {"results": [], "files_searched": 2, "files_failed": 0},
            "photosynthesis",
            tool_mode=tool_mode,
        ),
    )
    yield (
        "openzim_mcp/compact_renderers.py",
        "render_search_all(all failed)",
        render_search_all(
            {"results": [], "files_searched": 2, "files_failed": 2},
            "photosynthesis",
            tool_mode=tool_mode,
        ),
    )


def _structure_strings(tool_mode: str) -> Iterator[Tuple[str, str, str]]:
    """``zim_query('structure of X')`` / ``('what links to X')`` echo this."""
    yield (
        "openzim_mcp/zim/structure.py",
        "_entry_not_found_error",
        str(_entry_not_found_error("C/Nope", tool_mode=tool_mode)),
    )


def _error_template_strings(tool_mode: str) -> Iterator[Tuple[str, str, str]]:
    """Every ``error_messages`` template, in the wording each mode renders.

    The type-keyed table and the two message-pattern configs are rendered
    directly; ``_archive_path_config``'s composed steps are driven through
    ``get_error_config`` for each archive count, because the zero-archive
    branch is the one that names a tool.
    """
    module = "openzim_mcp/error_messages.py"
    static = list(em.ERROR_CONFIGS.values()) + [
        em.PERMISSION_ERROR_CONFIG,
        em.NOT_FOUND_ERROR_CONFIG,
    ]
    for config in static:
        rendered = em._for_tool_mode(config, tool_mode)
        yield (module, f"ErrorConfig({rendered.title!r})", "\n".join(rendered.steps))

    for count in (0, 1, 2):
        for operation in ("zim_query", "zim_health", "zim_browse"):
            config = em.get_error_config(
                em.OpenZimMcpArchiveNameError("Path did not match: x.zim"),
                operation=operation,
                count_archives=lambda c=count: c,  # type: ignore[misc]
                tool_mode=tool_mode,
            )
            assert config is not None
            yield (
                module,
                f"get_error_config(ArchiveNameError, {operation}, {count} archives)",
                "\n".join(config.steps),
            )

    yield (
        module,
        "format_generic_error",
        em.format_generic_error(
            operation="zim_query",
            error_type="RuntimeError",
            context="ctx",
            details="details",
            tool_mode=tool_mode,
        ),
    )


def _advice_strings(tool_mode: str) -> Iterator[Tuple[str, str, str]]:
    """Yield ``(module, label, text)`` for every user-facing recovery string."""
    yield from _footer_strings(tool_mode)
    yield from _search_all_strings(tool_mode)
    yield from _structure_strings(tool_mode)
    yield from _error_template_strings(tool_mode)


def _tool_references(text: str) -> List[str]:
    """Identifiers in ``text`` that read as an instruction to call a tool."""
    found: List[str] = []
    for span in _BACKTICKED.findall(text):
        m = _TOOL_SHAPED.match(span.strip())
        if m:
            found.append(m.group(1))
    return found


def _runtime_string_literals(path: pathlib.Path) -> Iterator[Tuple[int, str]]:
    """String constants in ``path`` that are not docstrings.

    Docstrings and comments are excluded on purpose: they discuss internal
    Python method names (``zim_operations.find_entry_by_title`` still
    exists) and are never shown to a client.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            yield node.lineno, node.value


def _rendered_pairs() -> Set[Tuple[str, str]]:
    """``(module, tool)`` pairs this module actually renders and checks."""
    return {
        (module, tool)
        for tool_mode in TOOL_MODES
        for module, _label, text in _advice_strings(tool_mode)
        for tool in _tool_references(text)
        if tool not in NON_TOOL_VOCABULARY
    }


def _package_tool_mentions() -> Iterator[Tuple[str, int, str]]:
    """``(module, lineno, identifier)`` for every backticked tool-shaped name."""
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        module = path.relative_to(_PACKAGE_ROOT.parent).as_posix()
        for lineno, value in _runtime_string_literals(path):
            for span in _BACKTICKED.findall(value):
                m = _TOOL_SHAPED.match(span.strip())
                if m:
                    yield module, lineno, m.group(1)


class TestRecoveryAdviceReferencesRegisteredTools:
    """No recovery string may instruct a tool absent from the live registry."""

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_advice_names_only_registered_tools(
        self, tool_mode: str, registries: Dict[str, Set[str]]
    ) -> None:
        registered = registries[tool_mode]
        allowed = registered | NON_TOOL_VOCABULARY
        offenders = []
        for _module, label, text in _advice_strings(tool_mode):
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
        for _module, label, text in _advice_strings(tool_mode):
            for legacy in LEGACY_TO_PHASE_F:
                if legacy in text:
                    offenders.append(f"{label}: {legacy!r}")
        assert not offenders, (
            f"recovery advice in tool_mode={tool_mode!r} names tool(s) deleted "
            f"in v2.0.0: {offenders}"
        )

    def test_simple_mode_advice_names_only_zim_query(
        self, registries: Dict[str, Set[str]]
    ) -> None:
        """Simple mode registers ``zim_query`` alone, so advice routes by prose.

        ``zim_query`` itself is fair game — it is the one tool that exists
        there, and ``error_messages`` already ships
        ``zim_query("list available ZIM files")`` on this surface. Any OTHER
        name, even a correct advanced one, is unreachable for the client.
        """
        assert registries["simple"] == {"zim_query"}, registries["simple"]
        offenders = []
        for _module, label, text in _advice_strings("simple"):
            refs = [
                n
                for n in _tool_references(text)
                if n not in NON_TOOL_VOCABULARY and n != "zim_query"
            ]
            if refs:
                offenders.append(f"{label}: {refs}")
        assert not offenders, (
            "simple-mode recovery advice may name no tool but `zim_query`; "
            f"found: {offenders}"
        )

    def test_simple_mode_advice_uses_intents_the_parser_resolves(self) -> None:
        """Prose is not enough — it has to parse as the intent it describes.

        A paraphrase like "ask again without naming a namespace" parses as a
        literal full-text search for its own text, so following the advice
        throws the recovery away. Each replacement below is the query the
        intent parser maps to the advanced tool the same branch names.
        """
        from openzim_mcp.intent_parser import IntentParser

        parser = IntentParser()
        expected = {
            "no_xapian_index": ("find article titled Aspirin", "find_by_title"),
            "bad_namespace": ("list namespaces", "list_namespaces"),
            "sample_only": ("walk namespace C", "walk_namespace"),
        }
        for reason, (probe, intent) in expected.items():
            footer = format_footer(
                {"reason": reason}, footer_enabled=True, tool_mode="simple"
            )
            stem = probe.rsplit(" ", 1)[0] if intent != "list_namespaces" else probe
            assert f"`{stem}" in footer, (
                f"simple footer for {reason!r} should instruct {stem!r}; "
                f"got {footer!r}"
            )
            parsed, _params, confidence = parser.parse_intent(probe)
            assert parsed == intent and confidence >= 0.85, (
                f"{probe!r} must resolve to {intent} for the advice to work; "
                f"got {(parsed, confidence)}"
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
        for _module, label, text in _search_all_strings("advanced"):
            assert "zim_health" in _tool_references(
                text
            ), f"advanced {label} should route to zim_health; got {text!r}"
        not_found = str(_entry_not_found_error("C/Nope", tool_mode="advanced"))
        assert "zim_search" in _tool_references(not_found), not_found

    def test_non_tool_vocabulary_is_not_a_tool_name(
        self, registries: Dict[str, Set[str]]
    ) -> None:
        """The allowlist cannot be used to wave a tool name through."""
        tool_names = registries["advanced"] | set(LEGACY_TO_PHASE_F)
        assert not (NON_TOOL_VOCABULARY & tool_names)


class TestRecoveryAdviceGuardCoverage:
    """The guard is only worth its rendered surface — pin that surface."""

    def test_no_runtime_string_anywhere_names_a_deleted_tool(self) -> None:
        """Package-wide, no exemptions: the defect class, not one function.

        Backticks are the discriminator — a backticked identifier in a
        non-docstring literal is being shown to a client as something to
        call. Bare occurrences are skipped because the deleted *tool* names
        are still live Python method names on ``ZimOperations``.
        """
        offenders = [
            f"{module}:{lineno}: `{name}`"
            for module, lineno, name in _package_tool_mentions()
            if name in LEGACY_TO_PHASE_F
        ]
        assert not offenders, (
            "runtime strings instruct tool(s) deleted in v2.0.0: " f"{offenders}"
        )

    def test_every_module_naming_a_tool_is_covered_by_this_guard(
        self, registries: Dict[str, Set[str]]
    ) -> None:
        """A new module with recovery advice must be brought in, not ignored.

        This is the rule that makes the rendered scan mean something: it
        fails until the new name is either rendered by ``_advice_strings``
        (and so checked in both modes) or declared advanced-only with a
        reason. Matching is per ``(module, tool)``, so a module already in
        the rendered set does not get a blanket pass for a tool name that
        nothing rendered mentions.
        """
        simple_registry = registries["simple"]
        advanced_registry = registries["advanced"]
        rendered = _rendered_pairs()
        uncovered = []
        for module, lineno, name in _package_tool_mentions():
            if name in simple_registry or name not in advanced_registry:
                # Callable everywhere, or not a tool name at all.
                continue
            if (module, name) in rendered:
                continue
            if (module, name) in ADVANCED_ONLY_ADVICE:
                continue
            uncovered.append(f"{module}:{lineno}: `{name}`")
        assert not uncovered, (
            "these runtime strings name an advanced-only tool that this guard "
            "never renders — add the surface to _advice_strings() or declare "
            f"it in ADVANCED_ONLY_ADVICE with a reason: {uncovered}"
        )

    def test_every_covered_module_contributes_a_rendered_string(self) -> None:
        """``RENDERED_MODULES`` cannot claim coverage it does not have.

        Without this, dropping a surface from ``_advice_strings`` would
        quietly shrink the guard rather than fail it.
        """
        rendered = {module for module, _tool in _rendered_pairs()}
        assert rendered == set(RENDERED_MODULES), (
            "RENDERED_MODULES disagrees with what _advice_strings() actually "
            f"renders: only-declared={sorted(set(RENDERED_MODULES) - rendered)}, "
            f"only-rendered={sorted(rendered - set(RENDERED_MODULES))}"
        )

    def test_advanced_only_exemptions_name_real_advanced_tools(
        self, registries: Dict[str, Set[str]]
    ) -> None:
        """An exemption may excuse an advanced tool, never a deleted one."""
        for (module, name), reason in ADVANCED_ONLY_ADVICE.items():
            assert name in registries["advanced"], (module, name)
            assert name not in LEGACY_TO_PHASE_F, (module, name)
            assert reason.strip(), (module, name)

    def test_simple_mode_registers_no_resources(
        self, servers: Dict[str, OpenZimMcpServer]
    ) -> None:
        """Pins the ``tools/resource_tools.py`` exemption.

        Its ``zim_get`` advice is unreachable in simple mode only because
        Resources are never registered there.
        """

        def counts(server: OpenZimMcpServer) -> Tuple[int, int]:
            manager = server.mcp._resource_manager
            return len(manager._resources), len(manager._templates)

        assert counts(servers["simple"]) == (0, 0)
        assert counts(servers["advanced"]) != (0, 0)

    def test_simple_mode_get_section_never_forwards_the_payload(self) -> None:
        """Pins the ``zim/structure.py`` ``zim_get`` exemption.

        ``get_section_data`` returns a ``ToolErrorPayload`` whose ``message``
        names ``zim_get``. The simple-mode handler must never surface that
        field — it writes its own bodies from the heading list.
        """
        import inspect

        from openzim_mcp.simple_tools import SimpleToolsHandler

        source = inspect.getsource(SimpleToolsHandler._handle_get_section)
        assert '"message"' not in source and "'message'" not in source, (
            "_handle_get_section now forwards a structured payload field; the "
            "zim/structure.py zim_get exemption no longer holds"
        )

    def test_api_reference_quotes_the_real_footers(self) -> None:
        """The docs' mode table must quote the strings the code emits.

        ``api-reference.mdx`` previously gave one Recovery column and scoped
        it to "the simple-mode footer" — after the mode split that sent a
        simple-mode reader looking for tools their client does not register.
        The table it carries now is only worth having if it stays true.
        """
        doc = (
            pathlib.Path(__file__).resolve().parents[1]
            / "website/src/content/docs/api-reference.mdx"
        ).read_text(encoding="utf-8")
        documented = ("no_xapian_index", "bad_namespace", "sample_only")
        for reason in documented:
            for tool_mode in TOOL_MODES:
                footer = format_footer(
                    {"reason": reason}, footer_enabled=True, tool_mode=tool_mode
                )
                advice = footer.split(". ", 1)[1] if ". " in footer else footer
                assert advice in doc, (
                    f"api-reference.mdx does not quote the {tool_mode} footer "
                    f"for {reason!r}: {advice!r}"
                )

    def test_advice_reasons_match_the_implementation(self) -> None:
        """Every advice reason in meta.py is exercised by this module.

        Read out of the ``reason in {...}`` gate rather than the individual
        ``reason == "..."`` branches, so a dict-dispatch refactor or an
        ``in``-style branch cannot add a reason this module never renders.
        """
        import inspect

        from openzim_mcp import meta

        tree = ast.parse(inspect.getsource(meta.format_footer))
        declared: Set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not (isinstance(node.left, ast.Name) and node.left.id == "reason"):
                continue
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(
                    comparator.value, str
                ):
                    declared.add(comparator.value)
                elif isinstance(comparator, (ast.Set, ast.Tuple, ast.List)):
                    for elt in comparator.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            declared.add(elt.value)
        assert declared == set(ADVICE_REASONS), (
            "format_footer's advice reasons drifted from ADVICE_REASONS: "
            f"only-in-meta={sorted(declared - set(ADVICE_REASONS))}, "
            f"only-in-guard={sorted(set(ADVICE_REASONS) - declared)}"
        )
