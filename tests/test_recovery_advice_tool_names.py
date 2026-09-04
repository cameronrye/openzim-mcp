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

Six rules, of which the last four are what make the first two worth
having:

* **Rendered scan** — every recovery string the covered surfaces produce is
  re-rendered in both modes and checked against that mode's live registry.
  All three spellings of an instruction count here: a backticked
  identifier, a bare ``name(`` call, and the name alone in prose ("use the
  zim_browse tool"). See ``_BARE_TOOL_WORD`` for why the third is read out
  of the rendered corpus only.
* **Successor mapping** — the advanced half must name the v2 replacement,
  so a future "fix" cannot satisfy the scan by deleting the tool name and
  stripping the recovery of its actionable step.
* **Clause contracts** — ``TestRecoveryAdviceClausesStayActionable`` is the
  positive rule the scans lack: every ``recovery_advice`` clause is pinned
  to what it must still SAY in each mode, the simple half down to the
  intent its quoted request resolves to. Every scan above is satisfied by
  the empty string, which left four of the six simple halves deletable with
  the whole suite green.
* **Coverage** — a static walk of *every* runtime string literal in the
  ``openzim_mcp`` package, reading backticked spans AND bare ``name(``
  calls. A literal that names a tool must be one this module actually
  renders, or an explicitly justified advanced-only surface. Without this
  the guard would only ever be as good as the list of functions someone
  remembered to add to it, which is how ``zim/structure.py`` shipped
  ``zim_search`` advice to a simple-mode client while a guard for exactly
  that defect sat green next to it — and how, one round later,
  ``Use zim_browse(namespace="M") …`` and
  ``fetch it with zim_get(…, binary=True)`` shipped to the same client
  past a guard that read only backticks.
* **Wiring, end to end** — ``TestToolModeReachesTheRenderers`` drives a
  real server in each mode and reads the wording out of the response. Every
  rule above calls the renderers directly with an explicit ``tool_mode=``,
  so all of them stayed green while the four kwargs that carry
  ``config.tool_mode`` into those renderers were reverted one at a time.
* **Wiring, statically** — ``TestModeAwareCallsAreWired`` generalises that:
  every call to a mode-aware helper anywhere in the package has to pass the
  configured mode, including on paths too deep to drive end to end.

Known residual, stated rather than implied away: the **coverage** walk reads
backticks and ``name(`` calls but not bare prose names, so a tool named in
bare prose inside a module this guard does not render is invisible to every
rule here. Reading bare names package-wide is not available — the v2.0.0
names are still live ``ZimOperations`` methods and intent labels and the
live ones are their own registration literals, 132 legitimate occurrences
today — and an allowlist that size would say less than it hid. Nothing
exploits the gap at present. Every bare-prose tool name left in the package
is one of three things:

* an advanced-only surface — ``tools/prompts.py``,
  ``tools/resource_tools.py``, ``tools/zim_search.py``'s description, and
  ``instructions.ADVANCED_INSTRUCTIONS`` — none of which reaches a simple
  client (``test_simple_mode_registers_no_resources``, the
  ``mode == "simple"`` return in ``openzim_mcp/tools/__init__.py``, and
  ``test_simple_instructions_name_only_the_registered_tool`` below);
* a ``config.py`` ``Field`` description, where naming both surfaces is the
  subject rather than an instruction;
* a log line, which no client reads.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Callable, Dict, Iterator, List, Set, Tuple

import pytest

import openzim_mcp
from openzim_mcp import error_messages as em
from openzim_mcp import recovery_advice as ra
from openzim_mcp.compact_renderers import render_search_all
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.meta import format_footer
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.zim.structure import _entry_not_found_error

from .test_phase_f_migration import LEGACY_TO_PHASE_F, PHASE_F_TOOLS

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

# What each ``recovery_advice`` clause must still SAY, per mode.
#
# The scans above are all negative — they forbid naming the wrong tool.
# Every one of them is satisfied by the empty string, which is how four of
# the six clauses could have their simple half emptied with the whole suite
# green: the advanced halves are pinned by the successor mapping and by
# ``tests/test_v3_field_fixes_content.py``, but the half this module exists
# to introduce had assertions for ``metadata_keys`` and ``fetch_binary``
# only. These two tables are the positive rule, keyed by clause name so a
# new clause has to be pinned before it can ship
# (``test_every_clause_is_pinned_in_both_modes``).
#
# The simple half is pinned to the request it quotes AND to the intent that
# request resolves to, because the wording alone is not the property that
# matters: a plain-English paraphrase parses as a literal full-text search
# for its own text, so a caller who follows it throws the recovery away.
CLAUSE_PLACEHOLDERS = {"<title>": "Aspirin", "<path>": "A/Photo.png"}

SIMPLE_CLAUSE_REQUESTS: Dict[str, Tuple[Tuple[str, str, float], ...]] = {
    "correct_entry_path": (("find article titled <title>", "find_by_title", 0.90),),
    "fetch_binary": (("get binary content of <path>", "binary", 0.90),),
    "locate_entry": (("find article titled <title>", "find_by_title", 0.90),),
    "locate_or_explore": (
        ("find article titled <title>", "find_by_title", 0.90),
        ("list namespaces", "list_namespaces", 0.95),
    ),
    "metadata_keys": (("browse namespace M", "browse", 0.85),),
    "verify_archive": (("list available ZIM files", "list_files", 0.95),),
}

ADVANCED_CLAUSE_TOOLS: Dict[str, Set[str]] = {
    "correct_entry_path": {"zim_search"},
    "fetch_binary": {"zim_get"},
    "locate_entry": {"zim_search"},
    "locate_or_explore": {"zim_search", "zim_browse"},
    "metadata_keys": {"zim_browse"},
    "verify_archive": {"zim_health"},
}

# Modules whose user-facing recovery strings this module RENDERS, and so
# checks per mode. Coverage itself is decided per *literal* (see
# ``_rendered_corpus``): being listed here buys a module nothing for a
# string that nothing rendered.
# ``test_every_covered_module_contributes_a_rendered_string`` pins that each
# name below really does contribute.
RENDERED_MODULES = frozenset(
    {
        "openzim_mcp/meta.py",
        "openzim_mcp/compact_renderers.py",
        "openzim_mcp/error_messages.py",
        "openzim_mcp/zim/structure.py",
        "openzim_mcp/recovery_advice.py",
    }
)

# Runtime strings that name an advanced-only tool but can never reach a
# simple-mode client, with the structural reason. Keyed by
# ``(module, enclosing function, tool)``: a new tool name, or the same one in
# a DIFFERENT function of the same module, is still a failure. (Keyed only by
# module, an exemption for one section-miss payload would have waved through
# any future ``zim_get`` string anywhere in ``zim/structure.py``.)
#
# * ``tools/resource_tools.py`` — MCP Resources are registered only on the
#   advanced surface (``tools/__init__.register_phase_f_tools`` returns
#   before ``register_resources``), pinned by
#   ``test_simple_mode_registers_no_resources``.
# * ``zim/structure.py`` — the ``zim_get`` names live in
#   ``_get_section_data``'s section-miss payloads (the body behind the
#   ``get_section_data`` entry point). Simple mode never forwards
#   them: ``SimpleToolsHandler._handle_get_section`` resolves the heading
#   against its own list and writes its own not-found / empty-section bodies,
#   pinned by ``test_simple_mode_get_section_never_forwards_the_payload``.
#   (Its ``zim_search`` name is a different story — that one IS echoed to
#   simple-mode clients, which is why ``_entry_not_found_error`` is rendered
#   below rather than exempted here.)
ADVANCED_ONLY_ADVICE: Dict[Tuple[str, str, str], str] = {
    ("openzim_mcp/tools/resource_tools.py", "_truncate_text_body", "zim_get"): (
        "MCP Resources register on the advanced surface only"
    ),
    ("openzim_mcp/tools/resource_tools.py", "ZimEntryResource.read", "zim_get"): (
        "MCP Resources register on the advanced surface only"
    ),
    ("openzim_mcp/zim/structure.py", "_StructureMixin._get_section_data", "zim_get"): (
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

# Backticks are a convention, not a contract. Two strings shipped to
# simple-mode clients named an advanced tool in bare prose —
# ``Use zim_browse(namespace="M") to list the available keys.`` and
# ``fetch it with zim_get(entry_path=..., binary=True)`` — and a guard that
# only read backticked spans could not see either.
#
# Scanning unbackticked prose is the part that risks false positives, so the
# rule is deliberately narrow rather than loosened until it stops firing:
# only ``identifier(`` counts, i.e. a name written as a *call*. Prose that
# merely contains a tool-shaped word ("browse namespace C", "the search
# index") has no paren and is ignored, and a preceding ``.`` is excluded so
# that Python API talk (``zim_operations.find_entry_by_title(...)`` — still a
# real method) is not mistaken for an instruction to the client.
# ``test_unbackticked_scan_reads_calls_not_prose`` pins all four cases.
#
# The fourth: only names that ARE tools — the eight registered ones plus the
# names v2.0.0 deleted — are read out of prose. English sentences call
# ordinary words with parens ("All 2 archive(s) returned errors"), and
# flagging those would force the rule to be watered down later. Restricting
# it cannot hide the defect: a name that is neither a live tool nor a deleted
# one is not "a tool the client cannot call" — it is not a tool at all.
# ``PHASE_F_TOOLS`` is pinned equal to the advanced registry by
# ``test_prose_scan_vocabulary_is_the_live_registry`` below.
_TOOL_CALL_IN_PROSE = re.compile(r"(?<![\w.`])([a-z_][a-z0-9_]*)\(")
_KNOWN_TOOL_NAMES = frozenset(PHASE_F_TOOLS) | frozenset(LEGACY_TO_PHASE_F)

# Third spelling: the name alone, in prose, with neither backticks nor a
# call paren — "use the zim_browse tool to see the namespaces". It reads as
# an instruction exactly as plainly as the other two, and neither of the
# rules above can see it.
#
# It is read out of the RENDERED corpus only, never out of the package-wide
# walk, and the asymmetry is deliberate rather than lazy. Package-wide the
# same rule fires on 132 literals today, essentially all of them internal:
# the v2.0.0-deleted names are still live ``ZimOperations`` methods and
# intent labels (``"search_all"``, ``"walk_namespace"``), and the live names
# are their own registration literals (``tools/zim_browse.py``'s
# ``"zim_browse"``) and mode-listing config descriptions. Watering the rule
# down to survive that would leave it meaning nothing. The rendered corpus
# is the opposite: small, client-facing and controlled, and it contains
# exactly one bare mention today — ``**Operation**: zim_query`` echoing the
# operation label, in a tool registered in both modes.
#
# What that leaves open is recorded rather than implied away: a tool name in
# bare prose in a module this guard does not render is still invisible.
# ``test_every_module_naming_a_tool_is_covered_by_this_guard`` would have to
# read bare names package-wide to catch it, and cannot.
_BARE_TOOL_WORD = re.compile(r"(?<![\w.`])([a-z][a-z0-9_]*)(?![\w(])")


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


def _clauses() -> Dict[str, Callable[[str], str]]:
    """Every public clause in ``openzim_mcp.recovery_advice``, by name.

    Read off the module rather than listed, so a clause added without a
    contract in ``SIMPLE_CLAUSE_REQUESTS`` /``ADVANCED_CLAUSE_TOOLS`` fails
    ``test_every_clause_is_pinned_in_both_modes`` instead of shipping
    unpinned.
    """
    return {
        name: getattr(ra, name)
        for name in dir(ra)
        if not name.startswith("_") and callable(getattr(ra, name))
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
        # ``title`` and ``issue`` are rendered verbatim by
        # ``format_error_message`` (``**Issue**: ...``), so scanning only
        # ``steps`` left two thirds of every envelope unguarded.
        yield (
            module,
            f"ErrorConfig({rendered.title!r})",
            "\n".join([rendered.title, rendered.issue, *rendered.steps]),
        )

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
                "\n".join([config.title, config.issue, *config.steps]),
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


def _recovery_advice_strings(tool_mode: str) -> Iterator[Tuple[str, str, str]]:
    """Every clause in ``openzim_mcp.recovery_advice``, in both modes.

    These are the tails ``zim/content.py``, ``zim/archive.py`` and
    ``content_processor.py`` append to their runtime messages. Rendering
    them here is what lets those modules carry no tool name of their own —
    two of these clauses shipped ``zim_browse(namespace="M")`` and
    ``zim_get(entry_path=..., binary=True)`` to simple-mode clients while
    the guard, reading only backticked spans, saw nothing.
    """
    module = "openzim_mcp/recovery_advice.py"
    for name, clause in sorted(_clauses().items()):
        yield module, f"recovery_advice.{name}", clause(tool_mode)


def _advice_strings(tool_mode: str) -> Iterator[Tuple[str, str, str]]:
    """Yield ``(module, label, text)`` for every user-facing recovery string."""
    yield from _footer_strings(tool_mode)
    yield from _search_all_strings(tool_mode)
    yield from _structure_strings(tool_mode)
    yield from _error_template_strings(tool_mode)
    yield from _recovery_advice_strings(tool_mode)


def _tool_references(text: str) -> List[str]:
    """Identifiers in ``text`` that read as an instruction to call a tool.

    Both spellings count: a backticked identifier, and a bare ``name(``
    call anywhere in the prose.
    """
    found: List[str] = []
    for span in _BACKTICKED.findall(text):
        m = _TOOL_SHAPED.match(span.strip())
        if m:
            found.append(m.group(1))
    found.extend(
        name for name in _TOOL_CALL_IN_PROSE.findall(text) if name in _KNOWN_TOOL_NAMES
    )
    return found


def _rendered_tool_references(text: str) -> List[str]:
    """``_tool_references`` plus bare, uncalled names — rendered text only.

    See ``_BARE_TOOL_WORD`` for why the third spelling is read here and not
    in the package-wide walk.
    """
    return _tool_references(text) + [
        name for name in _BARE_TOOL_WORD.findall(text) if name in _KNOWN_TOOL_NAMES
    ]


def _runtime_string_literals(path: pathlib.Path) -> Iterator[Tuple[int, str, str]]:
    """``(lineno, value, qualname)`` for non-docstring string constants.

    Docstrings and comments are excluded on purpose: they discuss internal
    Python method names (``zim_operations.find_entry_by_title`` still
    exists) and are never shown to a client.

    ``qualname`` is the dotted class/function the literal sits in (``""``
    at module level). Exemptions are keyed by it, so an exemption granted
    to one function cannot silently cover a new string somewhere else in
    the same module.
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

    def walk(node: ast.AST, scope: str) -> Iterator[Tuple[int, str, str]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = f"{scope}.{child.name}" if scope else child.name
                yield from walk(child, inner)
            elif (
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and id(child) not in docstrings
            ):
                yield child.lineno, child.value, scope
            else:
                yield from walk(child, scope)

    yield from walk(tree, "")


def _rendered_pairs() -> Set[Tuple[str, str]]:
    """``(module, tool)`` pairs this module actually renders and checks."""
    return {
        (module, tool)
        for tool_mode in TOOL_MODES
        for module, _label, text in _advice_strings(tool_mode)
        for tool in _tool_references(text)
        if tool not in NON_TOOL_VOCABULARY
    }


def _rendered_corpus() -> str:
    """Every rendered advice string, both modes, joined.

    Coverage is decided against this rather than against the set of
    modules or ``(module, tool)`` pairs: a literal counts as covered only
    when the text it produces really does show up in something this module
    rendered. A *new* string naming an already-rendered tool — a second
    ``zim_search`` sentence in ``zim/structure.py``, say — is therefore
    still uncovered, which is exactly the free pass the pair-keyed version
    handed out.
    """
    return "\n".join(
        text for mode in TOOL_MODES for _module, _label, text in _advice_strings(mode)
    )


def _package_tool_mentions() -> Iterator[Tuple[str, int, str, str, str]]:
    """``(module, lineno, qualname, identifier, literal)`` per tool mention.

    Backticked spans and bare ``name(`` calls both count — see
    ``_TOOL_CALL_IN_PROSE``. The literal and its enclosing function come
    along so coverage and exemptions can be decided per *string* and per
    *function*, not per module.
    """
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        module = path.relative_to(_PACKAGE_ROOT.parent).as_posix()
        for lineno, value, qualname in _runtime_string_literals(path):
            for name in dict.fromkeys(_tool_references(value)):
                yield module, lineno, qualname, name, value


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
            for name in _rendered_tool_references(text):
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
                for n in _rendered_tool_references(text)
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
            # The claim this one makes had to be weakened to be true.
            # ``include_assets`` is never threaded in simple mode, so this
            # tool cannot DISCOVER an asset — but it fetches one by path
            # perfectly well, and the old wording ("assets are not
            # reachable from this tool") talked a caller out of a
            # retrieval that works. The parser resolving the replacement
            # is what makes the weaker claim actionable.
            "no_content_type_match": ("get binary content of A/Photo.png", "binary"),
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


class TestRecoveryAdviceClausesStayActionable:
    """Every clause has to keep SAYING something, in both modes.

    The registry scans are all negative rules, and the empty string passes
    every one of them. That left the simple half of ``locate_entry``,
    ``locate_or_explore``, ``correct_entry_path`` and ``verify_archive``
    deletable with the whole suite green — the same fix-by-deletion the
    successor mapping closes on the advanced half, one column over, on the
    half this PR exists to add.
    """

    def test_every_clause_is_pinned_in_both_modes(self) -> None:
        """A new clause must arrive with its contract, not after it."""
        clauses = set(_clauses())
        assert set(SIMPLE_CLAUSE_REQUESTS) == clauses, (
            "SIMPLE_CLAUSE_REQUESTS drifted from recovery_advice: "
            f"unpinned={sorted(clauses - set(SIMPLE_CLAUSE_REQUESTS))}, "
            f"stale={sorted(set(SIMPLE_CLAUSE_REQUESTS) - clauses)}"
        )
        assert set(ADVANCED_CLAUSE_TOOLS) == clauses, (
            "ADVANCED_CLAUSE_TOOLS drifted from recovery_advice: "
            f"unpinned={sorted(clauses - set(ADVANCED_CLAUSE_TOOLS))}, "
            f"stale={sorted(set(ADVANCED_CLAUSE_TOOLS) - clauses)}"
        )

    @pytest.mark.parametrize("name", sorted(SIMPLE_CLAUSE_REQUESTS))
    def test_simple_clause_quotes_a_request_the_parser_resolves(
        self, name: str
    ) -> None:
        """The simple half quotes exactly the requests it is pinned to.

        Both halves of that matter. The set comparison stops the clause
        being emptied or having a route silently dropped; the parse stops
        it being reworded into prose that reads like advice and resolves
        to a full-text search for its own text.
        """
        from openzim_mcp.intent_parser import IntentParser

        contract = SIMPLE_CLAUSE_REQUESTS[name]
        text = _clauses()[name]("simple")
        quoted = {span.strip() for span in _BACKTICKED.findall(text)}
        assert quoted == {request for request, _intent, _conf in contract}, (
            f"recovery_advice.{name}('simple') must quote exactly the pinned "
            f"request(s); got {sorted(quoted)} from {text!r}"
        )

        parser = IntentParser()
        for request, intent, confidence in contract:
            probe = request
            for placeholder, value in CLAUSE_PLACEHOLDERS.items():
                probe = probe.replace(placeholder, value)
            assert "<" not in probe, (
                f"{request!r} carries a placeholder with no value in "
                f"CLAUSE_PLACEHOLDERS, so this test cannot parse it"
            )
            parsed, _params, got = parser.parse_intent(probe)
            assert parsed == intent and got >= confidence, (
                f"recovery_advice.{name}('simple') tells the caller to ask "
                f"{probe!r}, which must resolve to {intent} at >= "
                f"{confidence}; got {(parsed, got)}"
            )

    @pytest.mark.parametrize("name", sorted(ADVANCED_CLAUSE_TOOLS))
    def test_advanced_clause_names_its_successor(
        self, name: str, registries: Dict[str, Set[str]]
    ) -> None:
        """The advanced half names exactly the v2 tool(s) it routes to."""
        text = _clauses()[name]("advanced")
        found = set(_tool_references(text))
        assert found == ADVANCED_CLAUSE_TOOLS[name], (
            f"recovery_advice.{name}('advanced') must route to "
            f"{sorted(ADVANCED_CLAUSE_TOOLS[name])}; got {sorted(found)} "
            f"from {text!r}"
        )
        assert found <= registries["advanced"], (found, name)


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
            for module, lineno, _qualname, name, _literal in _package_tool_mentions()
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
        fails until the new string is either rendered by ``_advice_strings``
        (and so checked in both modes) or declared advanced-only with a
        reason.

        Coverage is per *literal*: the string has to turn up in something
        this module actually rendered. Keying it on ``(module, tool)``
        instead — the previous version — let a module that renders one
        ``zim_search`` sentence smuggle in a second one that nothing
        rendered. Exemptions are keyed on the enclosing function for the
        same reason.
        """
        simple_registry = registries["simple"]
        advanced_registry = registries["advanced"]
        corpus = _rendered_corpus()
        uncovered = []
        for module, lineno, qualname, name, literal in _package_tool_mentions():
            if name in simple_registry or name not in advanced_registry:
                # Callable everywhere, or not a tool name at all.
                continue
            if literal in corpus:
                continue
            if (module, qualname, name) in ADVANCED_ONLY_ADVICE:
                continue
            uncovered.append(f"{module}:{lineno} ({qualname}): `{name}`")
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
        for (module, qualname, name), reason in ADVANCED_ONLY_ADVICE.items():
            assert name in registries["advanced"], (module, qualname, name)
            assert name not in LEGACY_TO_PHASE_F, (module, qualname, name)
            assert reason.strip(), (module, qualname, name)

    def test_every_advanced_only_exemption_is_load_bearing(
        self, registries: Dict[str, Set[str]]
    ) -> None:
        """An exemption that excuses nothing is stale — drop it.

        Without this the inventory silently outlives the code it excused,
        and the next reader trusts a justification for a string that is no
        longer there.
        """
        claimed = set(ADVANCED_ONLY_ADVICE)
        corpus = _rendered_corpus()
        used = {
            (module, qualname, name)
            for module, _lineno, qualname, name, literal in _package_tool_mentions()
            if name in registries["advanced"]
            and name not in registries["simple"]
            and literal not in corpus
        }
        assert claimed == used, (
            "ADVANCED_ONLY_ADVICE drifted from the strings it excuses: "
            f"stale={sorted(claimed - used)}, missing={sorted(used - claimed)}"
        )

    def test_simple_instructions_name_only_the_registered_tool(
        self, registries: Dict[str, Set[str]]
    ) -> None:
        """Pins one leg of the bare-prose residual in the module docstring.

        ``instructions.ADVANCED_INSTRUCTIONS`` names all eight tools in bare
        prose, which no rule here can see. It is harmless only because
        ``instructions_for`` hands simple clients the other string.
        """
        from openzim_mcp.instructions import instructions_for

        for mode in TOOL_MODES:
            named = set(_rendered_tool_references(instructions_for(mode)))
            assert named <= registries[mode], (mode, sorted(named))

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
        # Every reason whose advice differs by mode. Three of the five went
        # unchecked before, so the ``archive_unavailable`` row could be
        # falsified in either column without this test noticing.
        documented = (
            "no_xapian_index",
            "bad_namespace",
            "no_content_type_match",
            "sample_only",
            "archive_unavailable",
        )
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


class TestGuardReadsUnbacktickedCalls:
    """The scan's own reading rules, pinned.

    The guard shipped believing backticks marked every tool reference. Two
    live simple-mode strings proved otherwise, so the scan now reads bare
    ``name(`` calls as well — a widening that only pays off if its edges
    stay where this class puts them.
    """

    def test_unbackticked_scan_reads_calls_not_prose(self) -> None:
        # A call in bare prose is an instruction, backticks or not.
        assert "zim_browse" in _tool_references(
            'Use zim_browse(namespace="M") to list the available keys.'
        )
        assert "zim_get" in _tool_references(
            "fetch it with zim_get(entry_path=..., binary=True)"
        )
        # A tool-shaped word without a call paren is prose, not an
        # instruction: simple-mode advice is *made* of such phrases.
        assert _tool_references("Ask for `browse namespace M` to list keys.") == []
        assert _tool_references("Ask for `walk namespace <namespace>`.") == []
        # Attribute access is Python API talk about a method that still
        # exists, not something the client is being told to call.
        assert _tool_references("zim_operations.find_entry_by_title() raised") == []
        # An ordinary English word called with parens is not a tool.
        assert _tool_references("All 2 archive(s) returned errors") == []

    def test_prose_scan_vocabulary_is_the_live_registry(
        self, registries: Dict[str, Set[str]]
    ) -> None:
        """The vocabulary the prose scan reads must be the real tool set.

        Restricting the prose rule to known tool names is what keeps it
        from firing on English. That restriction is only safe while the
        name list *is* every tool — a ninth tool registered without
        updating ``PHASE_F_TOOLS`` would be invisible to the prose scan.
        """
        assert registries["advanced"] == set(PHASE_F_TOOLS)
        assert registries["advanced"] <= _KNOWN_TOOL_NAMES
        assert set(LEGACY_TO_PHASE_F) <= _KNOWN_TOOL_NAMES


# ---------------------------------------------------------------------------
# The wiring, not the signature
# ---------------------------------------------------------------------------
#
# Everything above calls the renderers directly with an explicit
# ``tool_mode=``. That proves each renderer behaves once told the mode; it
# proves nothing about whether anything ever tells it. Reverting any of the
# threading kwargs — ``simple_tools.py``'s two, ``zim/structure.py``'s two —
# left the whole suite green, because the parameter defaults to ``simple``
# and only ADVANCED clients silently regressed.
#
# The tests below therefore assert on what a *server* emits: build a real
# ``OpenZimMcpServer`` in each mode, call the registered ``zim_query`` /
# ``zim_links`` tool, and read the wording out of the response. The renderer
# is not under test here — the path from ``config.tool_mode`` to it is.


def _server(directory: str, tool_mode: str) -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(allowed_directories=[directory], tool_mode=tool_mode)
    )


@pytest.fixture(scope="session")
def unopenable_archives(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A directory of two ``.zim`` files libzim cannot open.

    Drives the ``cross_file`` all-failed body and its ``archive_unavailable``
    footer — the one ``format_footer`` advice branch reachable end to end
    (the search path always attaches a ``tell me about X`` suggestion, so
    its advice block never fires).
    """
    directory = tmp_path_factory.mktemp("unopenable")
    for name in ("broken_a.zim", "broken_b.zim"):
        (directory / name).write_bytes(b"ZIM\x04 not really an archive" * 64)
    return str(directory)


@pytest.fixture(scope="session")
def corpus_archive(
    tmp_path_factory: pytest.TempPathFactory, zim_test_data_dir: object
) -> str:
    """A private copy of the new-scheme test archive, alone in a directory.

    Copied rather than used in place because the inbound test writes a
    link-graph sidecar next to it.
    """
    import shutil

    if zim_test_data_dir is None:
        pytest.skip("ZIM test corpus not available")
    source = pathlib.Path(str(zim_test_data_dir)) / "nons" / "small.zim"
    if not source.exists():
        pytest.skip(f"{source} not available")
    directory = tmp_path_factory.mktemp("wiring_corpus")
    shutil.copy(source, directory / "small.zim")
    return str(directory)


async def _zim_query(
    directory: str, tool_mode: str, query: str, **kwargs: object
) -> str:
    server = _server(directory, tool_mode)
    tool = server.mcp._tool_manager._tools["zim_query"].fn
    return str(await tool(query=query, **kwargs))


class TestToolModeReachesTheRenderers:
    """``config.tool_mode`` must actually arrive at each rendering seam."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    async def test_cross_file_body_follows_the_server_mode(
        self, unopenable_archives: str, tool_mode: str
    ) -> None:
        """``simple_tools`` -> ``compact_renderers.render_search_all``."""
        out = await _zim_query(
            unopenable_archives, tool_mode, "search all files for photosynthesis"
        )
        # The body, not the whole response: the footer rendered just below
        # carries the advanced wording too, so a substring check over the
        # response passes even with this seam reverted.
        body = out.split("\n\n> ")[0]
        recovery = (
            "Check `zim_health` and server logs"
            if tool_mode == "advanced"
            else "Retry shortly, or ask an operator to check the logs"
        )
        assert f"{recovery}; the query itself was not the problem." in body, body

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    async def test_cross_file_footer_follows_the_server_mode(
        self, unopenable_archives: str, tool_mode: str
    ) -> None:
        """``simple_tools`` -> ``meta.format_footer``."""
        out = await _zim_query(
            unopenable_archives, tool_mode, "search all files for photosynthesis"
        )
        footer = out.rsplit("\n", 1)[-1]
        assert footer.startswith("> All archives failed to respond."), out
        expected = format_footer(
            {"reason": "archive_unavailable"}, footer_enabled=True, tool_mode=tool_mode
        )
        assert footer == expected, out

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    async def test_structure_miss_follows_the_server_mode(
        self, corpus_archive: str, tool_mode: str
    ) -> None:
        """``zim/structure._build_bundle`` -> ``_entry_not_found_error``."""
        out = await _zim_query(
            corpus_archive, tool_mode, "show structure of C/NoSuchArticleXyz"
        )
        expected = (
            "or use `zim_search(mode='title')` to locate the entry"
            if tool_mode == "advanced"
            else "or ask for `find article titled <title>` to locate the entry"
        )
        assert expected in out, out

    @pytest.mark.asyncio
    async def test_inbound_miss_follows_the_server_mode(
        self, corpus_archive: str
    ) -> None:
        """``get_inbound_links_data`` -> ``_entry_not_found_error``.

        Advanced only: ``zim_links`` is not registered in simple mode and
        ``zim_query`` has no inbound intent, so this seam has exactly one
        live caller — and dropping its ``tool_mode`` would hand advanced
        clients the simple wording with nothing to notice it.
        """
        from libzim.reader import Archive  # type: ignore[import-untyped]

        from openzim_mcp.linkgraph.builder import build_from_link_stream
        from openzim_mcp.linkgraph.reader import sidecar_path_for

        archive_path = pathlib.Path(corpus_archive) / "small.zim"
        build_from_link_stream(
            sidecar_path_for(archive_path),
            archive_uuid=str(Archive(archive_path).uuid),
            link_stream=iter([("C/A", [("C/B", "")])]),
        )
        server = _server(corpus_archive, "advanced")
        result = await server.mcp._tool_manager._tools["zim_links"].fn(
            entry_path="C/NoSuchArticleXyz",
            direction="inbound",
            zim_file_path=str(archive_path),
        )
        assert "or use `zim_search(mode='title')` to locate the entry" in str(result)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    async def test_metadata_key_miss_follows_the_server_mode(
        self, corpus_archive: str, tool_mode: str
    ) -> None:
        """``zim/content._get_metadata_entry_data`` -> ``metadata_keys``."""
        out = await _zim_query(corpus_archive, tool_mode, "get article M/NoSuchKey")
        assert ra.metadata_keys(tool_mode) in out, out

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    async def test_image_body_follows_the_server_mode(
        self, corpus_archive: str, tool_mode: str
    ) -> None:
        """``server`` -> ``ContentProcessor`` -> ``fetch_binary``."""
        out = await _zim_query(corpus_archive, tool_mode, "get article favicon.png")
        assert f"Cannot display directly; {ra.fetch_binary(tool_mode)})" in out, out


@pytest.fixture(scope="session")
def strip_handler(tmp_path_factory: pytest.TempPathFactory) -> object:
    """A handler built only to call its renderers; it opens no archive."""
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator
    from openzim_mcp.simple_tools import SimpleToolsHandler
    from openzim_mcp.zim_operations import ZimOperations

    directory = str(tmp_path_factory.mktemp("strip_recovery"))
    cfg = OpenZimMcpConfig(allowed_directories=[directory])
    return SimpleToolsHandler(
        ZimOperations(
            cfg,
            PathValidator(cfg.allowed_directories),
            OpenZimMcpCache(cfg.cache),
            ContentProcessor(snippet_length=100),
        )
    )


class TestBackendRecoveryTailIsStrippedSymmetrically:
    """What the not-found renderer *deletes* must not depend on the mode.

    ``SimpleToolsHandler._render_not_found_recovery`` throws the backend's
    own guidance away and writes its own recovery commands from the path the
    caller actually asked for. It did that with a regex shaped like the
    ADVANCED half of a clause (``Try using zim_search() ...``), so the mode
    split silently stopped it matching for simple-mode callers alone: the
    same recovery, reworded, came through where it had always been deleted,
    putting a generic ``find article titled <title>`` directly above a
    bullet list already offering ``find article titled <the real path>``.

    The rule is now derived rather than spelt: a clause whose advanced half
    the regex eats has its simple half eaten too. The two clauses the regex
    never matched stay echoed in BOTH modes, which is the other half of the
    decision — they name the only route to a metadata key or to an entry's
    bytes, and the renderer's bullets offer neither.
    """

    STRIPPED = (
        "locate_entry",
        "locate_or_explore",
        "correct_entry_path",
        "verify_archive",
    )
    ECHOED = ("metadata_keys", "fetch_binary")

    def test_the_strip_list_covers_every_clause_in_the_module(self) -> None:
        """``_RECOVERY_CLAUSES`` is hand-written; it must stay complete.

        A clause missing from it would be classified as "never stripped"
        by omission rather than by the predicate.
        """
        from openzim_mcp.simple_tools import _RECOVERY_CLAUSES

        assert {clause.__name__ for clause in _RECOVERY_CLAUSES} == set(_clauses())

    def test_exactly_the_leak_shaped_clauses_are_stripped(self) -> None:
        """Pins the classification, so neither list can be edited by hand."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        clauses = _clauses()
        assert set(SimpleToolsHandler._SIMPLE_RECOVERY_TAILS) == {
            clauses[name]("simple") for name in self.STRIPPED
        }

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    @pytest.mark.parametrize("name", STRIPPED)
    def test_stripped_clause_leaves_no_trace_in_either_mode(
        self, strip_handler: object, name: str, tool_mode: str
    ) -> None:
        clause = _clauses()[name]
        body = strip_handler._render_not_found_recovery(  # type: ignore[attr-defined]
            "C/Nope",
            Exception(f"Entry not found: 'C/Nope'. {clause(tool_mode)}"),
            "get article",
        )
        assert clause(tool_mode) not in body, body
        assert "Entry not found: 'C/Nope'." in body, body

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    @pytest.mark.parametrize("name", ECHOED)
    def test_echoed_clause_survives_in_either_mode(
        self, strip_handler: object, name: str, tool_mode: str
    ) -> None:
        clause = _clauses()[name]
        body = strip_handler._render_not_found_recovery(  # type: ignore[attr-defined]
            "C/Nope",
            Exception(f"Entry not found: 'C/Nope'. {clause(tool_mode)}"),
            "get article",
        )
        assert clause(tool_mode) in body, body

    @pytest.mark.parametrize("tool_mode", TOOL_MODES)
    def test_a_clause_removed_from_the_middle_leaves_one_space(
        self, strip_handler: object, tool_mode: str
    ) -> None:
        """``zim/content.py`` appends a path hint AFTER the clause.

        Deleting the clause out of the middle of that message leaves the
        run of spaces that separated the two, in one mode by the regex and
        in the other by the literal replace. Both have to land on the same
        sentence.
        """
        clause = _clauses()["locate_or_explore"]
        body = strip_handler._render_not_found_recovery(  # type: ignore[attr-defined]
            "C/Nope",
            Exception(
                f"Entry not found: 'C/Nope'. {clause(tool_mode)} "
                "Did you mean 'C/Nope.html'?"
            ),
            "get article",
        )
        assert "Entry not found: 'C/Nope'. Did you mean 'C/Nope.html'?" in body, body

    def test_collapsing_spaces_never_reflows_line_breaks(self) -> None:
        """Both call sites pre-flatten newlines; the helper must not rely on it."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        # A blank line and a space-before-newline are what separate this
        # from a plain ``\s{2,}`` collapse; a lone ``\n`` is not a run, so
        # the two spellings agree on it and it proves nothing.
        assert (
            SimpleToolsHandler._strip_backend_recovery("first line. \n\nsecond  line.")
            == "first line. \n\nsecond line."
        )

    @pytest.mark.asyncio
    async def test_missing_article_body_is_mode_independent_end_to_end(
        self, corpus_archive: str
    ) -> None:
        """The live shape of it: same query, same archive, same bytes."""
        bodies = {
            mode: await _zim_query(
                corpus_archive, mode, "get article C/NoSuchArticleXyz"
            )
            for mode in TOOL_MODES
        }
        assert bodies["simple"] == bodies["advanced"], bodies


def _mode_aware_callables() -> Dict[str, str]:
    """Every package callable that takes a ``tool_mode`` parameter.

    Keyed by the name a caller writes: the function's own name, or the
    class's for a ``__init__`` that takes one (``ContentProcessor``).
    """
    found: Dict[str, str] = {}

    def visit(node: ast.AST, module: str, cls: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, module, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = [a.arg for a in (*child.args.args, *child.args.kwonlyargs)]
                if "tool_mode" in params:
                    name = cls if child.name == "__init__" and cls else child.name
                    found[name] = module
                visit(child, module, cls)
            else:
                visit(child, module, cls)

    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        module = path.relative_to(_PACKAGE_ROOT.parent).as_posix()
        visit(ast.parse(path.read_text(encoding="utf-8")), module, "")
    return found


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _suppressed_calls(tree: ast.AST) -> Set[int]:
    """Call nodes under a ``with suppress(...)``, whose raise never lands."""
    suppressed: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        if not any(
            isinstance(item.context_expr, ast.Call)
            and _called_name(item.context_expr) == "suppress"
            for item in node.items
        ):
            continue
        for stmt in node.body:
            for inner in ast.walk(stmt):
                if isinstance(inner, ast.Call):
                    suppressed.add(id(inner))
    return suppressed


def _is_mode_shaped(expr: ast.expr) -> bool:
    """``self.config.tool_mode``, ``self._tool_mode``, or a threaded param.

    A literal does not count. ``fetch_binary("advanced")`` reads as wiring
    and behaves as a hardcode, which is the mutation this rule exists to
    catch.
    """
    if isinstance(expr, ast.Attribute):
        return expr.attr in {"tool_mode", "_tool_mode"}
    return isinstance(expr, ast.Name) and expr.id == "tool_mode"


class TestModeAwareCallsAreWired:
    """Every mode-aware renderer must be *told* the mode by its caller.

    The seams the e2e class above covers were found by hand. This rule is
    the general form, and it is the cheap half of the defence: a new
    mode-aware helper, or a new call to an existing one, cannot be added
    without threading the config through — including on the paths that are
    too deep or too rare to drive end to end. It is not a replacement for
    the e2e half: it can see that a mode is passed, never that the mode
    passed is the server's.

    Calls inside a helper's own defining module are checked too — reverting
    ``zim/structure.py``'s two ``_entry_not_found_error`` kwargs is exactly
    the mutation that started this round, and both are same-module calls.

    Every parameter here defaults to ``simple`` (the fail-safe mode), so a
    missed call site degrades an advanced client to ``zim_query`` prose
    rather than naming an uncallable tool. That is what makes the failure
    silent, and this test is what makes it loud.
    """

    def test_every_mode_aware_call_passes_the_configured_mode(self) -> None:
        mode_aware = _mode_aware_callables()
        assert "format_footer" in mode_aware, sorted(mode_aware)
        assert "ContentProcessor" in mode_aware, sorted(mode_aware)
        offenders = []
        for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
            module = path.relative_to(_PACKAGE_ROOT.parent).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            suppressed = _suppressed_calls(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _called_name(node)
                if name not in mode_aware:
                    continue
                if id(node) in suppressed:
                    # A raise nothing can see carries no advice. The one
                    # such call is ``_resolve_entry_spelling``'s
                    # best-effort ``rewrite_well_known_path`` probe.
                    continue
                args = [*node.args, *(kw.value for kw in node.keywords)]
                if not any(_is_mode_shaped(a) for a in args):
                    offenders.append(f"{module}:{node.lineno}: {name}()")
        assert not offenders, (
            "these calls render mode-aware recovery text but never say which "
            f"mode, so they silently fall back to 'simple': {offenders}"
        )
