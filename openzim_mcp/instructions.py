"""Server ``instructions``: the built-in text, and an operator's replacement.

The SDK serves one string in two places: the handshake-era ``initialize``
result, and the ``server/discover`` result that protocol revision 2026-07-28
uses in place of that handshake. Operators can replace the built-in text
(#479); see :func:`resolve_instructions` for the rules, and the end of this
module for what startup logs about it.

``instructions`` is the one place to put *cross-tool* guidance. Tool
descriptions can only describe themselves, so every disambiguation between two
tools had to be paid for twice — once in each description — out of the surface
budget the 8-tool consolidation exists to protect. This text is sent with
discovery instead of on every ``tools/list``.

The routing lines below are not guesses. They target the confusion pairs the
committed dispatch-eval run actually produced against qwen3-8b-q4
(``tests/dispatch_eval/runs/rc1__advanced__*.jsonl``), most-frequent first:

    305  zim_search  -> zim_query     (over-routing to the NL entry point)
    158  zim_get     -> zim_query
     40  zim_query   -> zim_search
     15  zim_get     -> zim_metadata  ("main page" read as archive metadata)
     14  zim_links   -> zim_query
     11  zim_links   -> zim_search
     10  zim_browse  -> zim_metadata  (namespace listing vs archive description)

Some of those are scored ``either_acceptable`` — a ``zim_query`` answer to a
prose request is a working outcome, not a defect (see docs/roadmap.md, #199).
The lines here aim at the pairs where the wrong tool yields a worse answer:
the ``zim_get``/``zim_metadata`` main-page split, ``zim_browse`` vs
``zim_metadata``, and ``zim_links`` needing an entry path rather than a query.

The closing ``isError`` sentence is deliberately scoped to *rejected
arguments*. ``zim_query``'s intent-level guidance (no archive specified, no results, no
such article) returns markdown rather than a ``tool_error`` envelope, so it is
still delivered with ``isError=False``. Path and security failures left that
set in D58: they now return a ``zim_path_not_found`` envelope with
``isError=True``. Routing those templates
through :func:`openzim_mcp.responses.tool_error` is a payload change to the
small-model surface and belongs in its own commit.
"""

import codecs
import difflib
import logging
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Tuple, Union

from .exceptions import OpenZimMcpConfigurationError
from .tools import TOOL_NAMES

logger = logging.getLogger(__name__)

ADVANCED_INSTRUCTIONS = """\
Offline ZIM archives (Wikipedia, Stack Exchange, Wiktionary, …). Retrieval \
only — content is read from local archives.

Choosing a tool:
- zim_query — a natural-language question when you don't have an entry path. \
Searches, picks the best entry, and renders it in one call.
- zim_search — search *terms* rather than a question, or when you need \
mode="title"/"suggest", namespace and content-type filters, or paging.
- zim_get — you already have an entry_path from a search hit or a link. \
main_page=True fetches the archive's front page: that is zim_get, not \
zim_metadata.
- zim_get_section — one named section of an article you have already located.
- zim_browse — list the entries in a namespace. zim_metadata describes the \
*archive* (Name, Title, Creator, entry counts) and does not list entries.
- zim_links — outbound links, inbound links, or related articles for one \
article. It takes an entry_path, not a query; it is not a search tool.
- zim_health — server state, or validation of a single archive.

Entry paths are archive-relative (e.g. "A/Aspirin"), never URLs. A rejected \
argument is flagged isError with a JSON body carrying "error", "operation" and \
a "message" describing how to correct the call.
"""

SIMPLE_INSTRUCTIONS = """\
Offline ZIM archives (Wikipedia, Stack Exchange, Wiktionary, …). Retrieval \
only — content is read from local archives.

zim_query takes a natural-language question and handles search, entry \
selection and rendering in one call. Ask it the question directly rather than \
composing search terms. A rejected argument is flagged isError with a JSON body \
carrying "error", "operation" and a "message" describing how to correct it; \
other problems come back as markdown that names what to do next.
"""


def instructions_for(tool_mode: str) -> str:
    """Return the instructions matching the registered tool surface.

    Advertising the 8-tool routing guide in simple mode would describe tools
    the client cannot see.
    """
    return SIMPLE_INSTRUCTIONS if tool_mode == "simple" else ADVANCED_INSTRUCTIONS


# ---------------------------------------------------------------------------
# Operator-supplied instructions (#479).
#
# The contract promised on the issue: ``OPENZIM_MCP_INSTRUCTIONS`` (the text)
# or ``OPENZIM_MCP_INSTRUCTIONS_PATH`` (a file), never both; the text replaces
# the built-in instructions, and ``{{default}}`` in it expands to the built-in
# text for the running tool mode; neither set is today's behaviour, and a path
# that is set but unusable stops startup rather than falling back. Everything
# below that is not that contract exists to keep the "never silently" half:
# each way a real deployment gets this wrong either refuses to start or is
# named in the startup log.
# ---------------------------------------------------------------------------

INSTRUCTIONS_ENV = "OPENZIM_MCP_INSTRUCTIONS"
INSTRUCTIONS_PATH_ENV = "OPENZIM_MCP_INSTRUCTIONS_PATH"

DEFAULT_TOKEN = "{{default}}"

# A ceiling, not a target: hosts put the text in the model's context on every
# turn, the built-in advanced text is about 1.2 KiB, and some hosts keep only
# the first few thousand characters. It also bounds what a mistaken path can
# publish to every client.
MAX_INSTRUCTIONS_BYTES = 16 * 1024

BOTH_INSTRUCTION_SOURCES_SET = (
    f"{INSTRUCTIONS_ENV} and {INSTRUCTIONS_PATH_ENV} are both set; set only "
    "one: the text itself, or the path to a UTF-8 file holding it."
)

_BOM = "\ufeff"
_ACCEPTED_VARIABLES = frozenset({INSTRUCTIONS_ENV, INSTRUCTIONS_PATH_ENV})

# Spellings an operator plausibly meant as the token: whitespace or case
# variants, the single-brace form an f-string or str.format renders from
# ``{{default}}``, Mustache's triple braces, Go's ``{{ .Default }}``, shell's
# ``${default}``. Every quantifier is possessive: the natural greedy form of
# this pattern is quadratic on a long run of braces or spaces, and this repo
# has shipped one quadratic regex over raw text already (#474).
_NEAR_MISS_TOKEN = re.compile(
    r"\$?(?<!\{)\{++\s*+(?:\.\s*+)?defaults?\s*+\}++", re.IGNORECASE
)

# A ``zim_*`` word that reads as a tool reference: not the tail of a longer
# identifier (``openzim_mcp``, ``my_zim_archive``) or a path component
# (``/srv/zim_data``), and not a file name (``zim_backup.zim``). A
# client-qualified name such as ``mcp__openzim__zim_search`` counts by its
# last part. Possessive, so a long run fails in one pass.
_TOOL_REFERENCE = re.compile(
    r"(?:(?<=__)|(?<![\w./\\-]))zim_[a-z0-9_]++(?![\w/\\-]|\.\w)"
)
# Calibrated on 30-odd realistic misspellings and non-tool names: 0.8 suggests
# for every typo tried (zim_serach, zim_get_secton, zim_meta_data, ...) and
# for no parameter, resource or path name the server or its docs use.
_TYPO_CUTOFF = 0.8
_MAX_TOOL_NAME = 64


@dataclass(frozen=True)
class ServerInstructions:
    """The instructions this server advertises, and where they came from.

    ``source`` is the variable that supplied them (``None`` for the built-in
    text); ``custom`` is the operator's text after newline normalisation and
    before ``{{default}}`` expands, which is what the startup warnings scan —
    the expanded built-in text is not the operator's to fix.
    """

    text: str
    source: Optional[str] = None
    path: Optional[Path] = None
    custom: Optional[str] = None
    expansions: int = 0


def is_blank(value: Any) -> bool:
    """``None``, or a string with nothing in it but whitespace and a BOM.

    Blank means unset for both variables. Templated deployments (a compose
    ``${VAR}``, a Helm value, a host's JSON ``env`` block) render an unset
    variable as ``""``, and the path field would otherwise become
    ``Path(".")`` — a directory, so a startup error.
    """
    return value is None or (
        isinstance(value, str) and not value.removeprefix(_BOM).strip()
    )


def instructions_path_from(value: Any) -> Any:
    """Normalise a configured path: blank is unset, ``~`` is expanded.

    Surrounding whitespace is dropped (a YAML ``|`` block leaves a newline on
    the value). The path is not ``resolve()``d like config.py's other paths:
    a Kubernetes ConfigMap key is a symlink through ``..data`` into a
    timestamped directory, and the resolved form would put that directory in
    every message. Anything that is not a string or a path goes through
    unchanged for pydantic to reject.
    """
    if is_blank(value):
        return None
    if isinstance(value, str):
        value = value.strip()
    if not isinstance(value, (str, os.PathLike)):
        return value
    try:
        return Path(value).expanduser()
    except RuntimeError as exc:  # an unknown ~user, or no home directory
        # Not a ValueError, so pydantic would not wrap it: it reached
        # main()'s generic "Server startup error" arm without the variable.
        raise OpenZimMcpConfigurationError(
            f"{INSTRUCTIONS_PATH_ENV}={str(value)!r} cannot be expanded: {exc}"
        ) from exc


def resolve_instructions(
    tool_mode: str,
    *,
    inline: Optional[str] = None,
    path: Union[str, Path, None] = None,
) -> ServerInstructions:
    """The instructions to advertise for ``tool_mode``.

    Neither source set returns the built-in text untouched. Otherwise the
    operator's text has every ``{{default}}`` replaced by the built-in text
    for ``tool_mode`` (without its final newline, so the token sits in a
    paragraph like any other words), surrounding whitespace trimmed, and one
    final newline — so every token-only form is the built-in text exactly.
    The result may be at most :data:`MAX_INSTRUCTIONS_BYTES` of UTF-8.

    Self-contained on purpose: ``model_copy`` and attribute assignment skip
    the config validators, so blank text, a string path and both sources set
    are all handled here as well.

    Raises:
        OpenZimMcpConfigurationError: both sources set; an unusable file (see
            :func:`_read_instructions_file`); inline text that is not UTF-8;
            or a result over the cap. Every message names the variable.
    """
    default = instructions_for(tool_mode)
    if is_blank(inline):
        inline = None
    file_path: Optional[Path] = instructions_path_from(path)
    if inline is not None and file_path is not None:
        raise OpenZimMcpConfigurationError(BOTH_INSTRUCTION_SOURCES_SET)
    if file_path is not None:
        custom = _read_instructions_file(file_path)
        source, label = INSTRUCTIONS_PATH_ENV, _path_label(file_path)
    elif inline is not None:
        custom = _inline_text(inline)
        source, label = INSTRUCTIONS_ENV, INSTRUCTIONS_ENV
    else:
        return ServerInstructions(text=default)

    expansions = custom.count(DEFAULT_TOKEN)
    text = custom.replace(DEFAULT_TOKEN, default.rstrip("\n")).strip() + "\n"
    size = len(text.encode("utf-8"))
    if size > MAX_INSTRUCTIONS_BYTES:
        raise OpenZimMcpConfigurationError(
            _over_cap_message(label, size, expansions, default, tool_mode)
        )
    return ServerInstructions(
        text=text,
        source=source,
        path=file_path,
        custom=custom,
        expansions=expansions,
    )


def _path_label(path: Path) -> str:
    """``OPENZIM_MCP_INSTRUCTIONS_PATH='…'`` for messages and the log.

    Quoted, so a stray space or a JSON-decoded control character (``"C:\\new"``
    is a newline) is visible; a relative path also says where it resolved,
    since a GUI-launched host's working directory is rarely the one the
    operator pictured.
    """
    label = f"{INSTRUCTIONS_PATH_ENV}={str(path)!r}"
    if not path.is_absolute():
        try:
            label += (
                " (resolved against the working directory: "
                f"{str(path.absolute())!r})"
            )
        except OSError:  # the working directory itself is gone
            pass
    return label


def _normalise_newlines(text: str) -> str:
    """CRLF and lone CR become LF; nothing else changes.

    Not ``splitlines()``: that also splits on form feeds, NEL and the Unicode
    line separators, and drops the final newline.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _inline_text(text: str) -> str:
    """Validate and normalise ``OPENZIM_MCP_INSTRUCTIONS``.

    ``os.environ`` decodes an undecodable byte (a Latin-1 file pasted in with
    ``$(cat …)``) to a lone surrogate, which pydantic accepts and the SDK
    cannot serialise: the stdio writer crashed on the first ``initialize``.
    A BOM carried in from such a file is dropped.
    """
    text = text.removeprefix(_BOM)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        char = text[exc.start]
        if "\udc80" <= char <= "\udcff":  # surrogateescape's stand-in for a byte
            shown = f"the undecodable byte 0x{ord(char) - 0xDC00:02x}"
        else:
            shown = f"the lone surrogate U+{ord(char):04X}"
        line = text.count("\n", 0, exc.start) + 1
        raise OpenZimMcpConfigurationError(
            f"{INSTRUCTIONS_ENV} is not valid UTF-8: it holds {shown} at "
            f"character {exc.start + 1} (line {line}). Set it from UTF-8 text, "
            f"or put the text in a UTF-8 file and set {INSTRUCTIONS_PATH_ENV}."
        ) from exc
    return _normalise_newlines(text)


def _read_instructions_file(path: Path) -> str:
    """Read ``OPENZIM_MCP_INSTRUCTIONS_PATH``, or stop startup saying why.

    One ``os.stat`` inside the ``OSError`` handler, not ``Path.is_file()``:
    that returns ``False`` for a missing file, a directory and a symlink loop
    alike, and raises on an unsearchable parent directory in Python 3.12 and
    3.13 (3.14 returns ``False``). The type check comes before ``open()``,
    which would block on a FIFO until a writer appeared.

    The read is bounded at one byte past the cap, and the size is checked on
    those raw bytes before anything is decoded: a cut through a multi-byte
    character would otherwise read as "not UTF-8", and dropping CRs or a BOM
    would bring a longer file's first 16 KiB under the cap and serve it
    truncated.
    """
    label = _path_label(path)
    try:
        mode = os.stat(path).st_mode
        if stat.S_ISDIR(mode):
            raise OpenZimMcpConfigurationError(
                f"{label} is a directory; point it at the instructions file "
                "itself. (A Docker bind mount of a host file that does not "
                "exist creates an empty directory in its place.)"
            )
        if not stat.S_ISREG(mode):
            raise OpenZimMcpConfigurationError(
                f"{label} is not a regular file (it is a FIFO, socket or device)."
            )
        with open(path, "rb") as handle:
            data = handle.read(MAX_INSTRUCTIONS_BYTES + 1)
            size = os.fstat(handle.fileno()).st_size
    except FileNotFoundError as exc:
        raise OpenZimMcpConfigurationError(f"{label} does not exist.") from exc
    except PermissionError as exc:
        raise OpenZimMcpConfigurationError(
            f"{label} cannot be read: {exc.strerror}. The file, and every "
            "directory above it, must be readable by the user the server runs as."
        ) from exc
    except OSError as exc:
        raise OpenZimMcpConfigurationError(
            f"{label} cannot be read: {exc.strerror or exc}."
        ) from exc

    if len(data) > MAX_INSTRUCTIONS_BYTES:
        # A /proc file reports size 0 however much it holds.
        shown = (
            f"{size} bytes"
            if size > MAX_INSTRUCTIONS_BYTES
            else f"more than {MAX_INSTRUCTIONS_BYTES} bytes"
        )
        raise OpenZimMcpConfigurationError(
            f"{label} is {shown}; the limit is {MAX_INSTRUCTIONS_BYTES} bytes "
            "(16 KiB)."
        )
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        # What Windows PowerShell 5.1's ``>`` and ``Out-File`` write.
        raise OpenZimMcpConfigurationError(
            f"{label} is UTF-16 (it starts with a UTF-16 byte-order mark); "
            "save it as UTF-8."
        )
    nul = data.find(b"\x00")
    if nul != -1:
        # BOM-less UTF-16 of ASCII text is valid UTF-8, NULs and all, and
        # would be served with its token unexpanded; /proc/<pid>/environ is
        # NUL-separated and would publish the server's environment.
        raise OpenZimMcpConfigurationError(
            f"{label} contains a NUL byte at offset {nul}, so it is not a "
            "UTF-8 text file (is it UTF-16 without a byte-order mark?)."
        )
    body = data.removeprefix(codecs.BOM_UTF8)  # Notepad's UTF-8 is fine
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        offset = exc.start + len(data) - len(body)
        line = data.count(b"\n", 0, offset) + 1
        raise OpenZimMcpConfigurationError(
            f"{label} is not valid UTF-8: byte 0x{body[exc.start]:02x} at "
            f"offset {offset} (line {line}); save it as UTF-8."
        ) from exc
    text = _normalise_newlines(text)
    if not text.strip():
        raise OpenZimMcpConfigurationError(
            f"{label} is empty (or holds only whitespace)."
        )
    return text


def _over_cap_message(
    label: str, size: int, expansions: int, default: str, tool_mode: str
) -> str:
    """Name what pushed the text over the cap, mode included.

    The same file can fit in simple mode (about 0.5 KiB of built-in text per
    token) and not in advanced mode (about 1.2 KiB), and the published image
    defaults to advanced while ``uvx`` defaults to simple.
    """
    limit = f"the limit is {MAX_INSTRUCTIONS_BYTES} bytes (16 KiB)."
    if not expansions:
        return f"{label} is {size} bytes; {limit}"
    each = len(default.rstrip("\n").encode("utf-8"))
    times = "once" if expansions == 1 else f"{expansions} times"
    return (
        f"{label} is {size} bytes once {DEFAULT_TOKEN} expands ({times}, to "
        f"the {each}-byte built-in {tool_mode}-mode text); {limit}"
    )


# ---------------------------------------------------------------------------
# What startup says about the instructions it is serving.
# ---------------------------------------------------------------------------


def describe_instructions(resolved: ServerInstructions, tool_mode: str) -> str:
    """The one INFO line every start writes, built-in case included.

    In several real deployments the variable never reaches the server — a
    host's ``env`` block that configures the ``docker`` CLI instead of the
    container, a compose ``${VAR}`` with nothing behind it, an image that
    predates the setting — and nothing errors, so this line is the evidence.
    It never contains the text itself.
    """
    size = len(resolved.text.encode("utf-8"))
    if resolved.source is None:
        return f"Server instructions: built-in, for {tool_mode} mode ({size} bytes)"
    where = _path_label(resolved.path) if resolved.path is not None else resolved.source
    head = (
        f"Server instructions: custom, from {where} ({size} bytes, "
        f"{len(resolved.text)} characters)"
    )
    if not resolved.expansions:
        # Plain Jinja2 renders an undefined ``{{default}}`` as nothing, so a
        # templated file can lose the token without any other signal.
        return (
            f"{head}; the built-in guidance is not included "
            f"(no {DEFAULT_TOKEN} token)"
        )
    times = "" if resolved.expansions == 1 else f" {resolved.expansions} times"
    return (
        f"{head}; the built-in {tool_mode}-mode guidance is included{times} "
        f"via {DEFAULT_TOKEN}"
    )


def near_miss_tokens(text: str) -> List[Tuple[str, int]]:
    """Each distinct near-miss of ``{{default}}`` in ``text``, with its line.

    Only the exact token expands; ``{{ default }}`` and the rest are sent to
    clients as written (or, for ``{{{default}}}``, expand with stray braces
    around them).
    """
    found: List[Tuple[str, int]] = []
    seen = set()
    line, counted = 1, 0
    for match in _NEAR_MISS_TOKEN.finditer(text):
        spelling = match.group()
        if spelling == DEFAULT_TOKEN or spelling in seen:
            continue
        seen.add(spelling)
        line += text.count("\n", counted, match.start())
        counted = match.start()
        found.append((spelling, line))
    return found


def tool_name_findings(
    text: str, registered: Sequence[str]
) -> Tuple[List[str], List[Tuple[str, str, bool]]]:
    """Tool references in ``text`` that this server will not serve.

    Returns ``(unregistered, typos)``. ``unregistered`` lists real tool names
    the running mode does not register — in simple mode, the default, only
    ``zim_query`` exists, so text naming another tool describes something
    the client cannot call. ``typos`` holds ``(name, suggestion,
    suggestion_is_registered)`` for a ``zim_*`` word that is no tool but
    closely matches one. Any other ``zim_*`` word — an argument name, a
    resource, an operation code — is not a claim about a tool and is left
    alone. Both lists keep the order of first appearance.
    """
    served = set(registered)
    unregistered: List[str] = []
    typos: List[Tuple[str, str, bool]] = []
    seen = set()
    for match in _TOOL_REFERENCE.finditer(text):
        name = match.group()
        if name in seen or name in served or len(name) > _MAX_TOOL_NAME:
            continue
        seen.add(name)
        if name in TOOL_NAMES:
            unregistered.append(name)
            continue
        close = difflib.get_close_matches(name, TOOL_NAMES, n=1, cutoff=_TYPO_CUTOFF)
        if close:
            typos.append((name, close[0], close[0] in served))
    return unregistered, typos


def misspelt_instruction_variables(environ: Mapping[str, str]) -> List[str]:
    """Environment names that look like this setting but are not it.

    pydantic-settings reads only the names of declared fields, so
    ``OPENZIM_MCP_INSTRUCTIONS_FILE`` (the Docker ``_FILE`` habit),
    ``OPENZIM_MCP_INSTRUCTIONS__PATH`` (the docs teach ``__`` for nesting)
    and the singular all start the server on the built-in text, silently.
    Names match case-insensitively, as the settings model does.
    """
    return sorted(
        key
        for key in environ
        if key.upper().startswith("OPENZIM_MCP_INSTRUCTION")
        and key.upper() not in _ACCEPTED_VARIABLES
    )


def _names_a_file(text: str) -> Optional[str]:
    """``text`` if it is a single word naming an existing file, else ``None``.

    The likeliest mix-up between the two variables: a path set where the text
    belongs is served to every client as the instructions.
    """
    candidate = text.strip()
    if not candidate or any(char.isspace() for char in candidate):
        return None
    try:
        return candidate if Path(candidate).expanduser().is_file() else None
    except (OSError, RuntimeError, ValueError):
        return None


def report_instructions(
    resolved: ServerInstructions,
    *,
    tool_mode: str,
    registered_tools: Sequence[str],
    environ: Mapping[str, str],
) -> None:
    """Log what startup resolved, and anything about it that looks wrong.

    Called once the tools are registered, so tool names are checked against
    what this mode actually serves. Every finding is a warning, never an
    error: a full rewrite, text about a tool clients only get in advanced
    mode, and unusual names are all legitimate on purpose.
    """
    logger.info("%s", describe_instructions(resolved, tool_mode))

    misspelt = misspelt_instruction_variables(environ)
    if misspelt:
        logger.warning(
            "%s %s not a setting and %s ignored: the server reads %s (the text "
            "itself) and %s (a file holding it).",
            ", ".join(misspelt),
            "is" if len(misspelt) == 1 else "are",
            "is" if len(misspelt) == 1 else "are",
            INSTRUCTIONS_ENV,
            INSTRUCTIONS_PATH_ENV,
        )

    custom = resolved.custom
    if custom is None:
        return

    unregistered, typos = tool_name_findings(custom, registered_tools)
    if unregistered:
        logger.warning(
            "Server instructions name %s, which %s mode does not register; "
            "clients are offered only %s. Set OPENZIM_MCP_TOOL_MODE=advanced "
            "(or pass --mode advanced), or remove those names.",
            ", ".join(unregistered),
            tool_mode,
            ", ".join(registered_tools),
        )
    if typos:
        logger.warning(
            "Server instructions name %s, which %s not a tool on this server.",
            ", ".join(
                f"{name} (did you mean {suggestion}?"
                f"{'' if served else ' It is registered in advanced mode only.'})"
                for name, suggestion, served in typos
            ),
            "is" if len(typos) == 1 else "are",
        )

    misses = near_miss_tokens(custom)
    if misses:
        logger.warning(
            "Server instructions contain %s, which %s not the %s token: only "
            "the exact text %s is replaced, and anything else is sent to "
            "clients as written.",
            ", ".join(f"{spelling!r} (line {line})" for spelling, line in misses),
            "is" if len(misses) == 1 else "are",
            DEFAULT_TOKEN,
            DEFAULT_TOKEN,
        )

    if resolved.source == INSTRUCTIONS_ENV:
        named = _names_a_file(custom)
        if named is not None:
            logger.warning(
                "%s holds a file path (%r), which is sent to clients as the "
                "instructions text. To load the file, set %s instead.",
                INSTRUCTIONS_ENV,
                named,
                INSTRUCTIONS_PATH_ENV,
            )
