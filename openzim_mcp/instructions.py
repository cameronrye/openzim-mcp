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
import itertools
import logging
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

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
*archive* (Name, Title, Creator, entry counts) and does not page through \
entries.
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

zim_query takes a natural-language request and handles search, entry \
selection and rendering in one call. Send a question or an operation phrase \
from its description ("tell me about X", "summary of X"), not bare search \
terms. A rejected argument is flagged isError with a JSON body carrying \
"error", "operation" and a "message" describing how to correct it; other \
problems come back as markdown that names what to do next.
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

DEFAULT_TOKEN = "{{default}}"  # nosec B105 - a template placeholder, no secret

# A ceiling, not a target: hosts put the text in the model's context on every
# turn, the built-in advanced text is about 1.2 KiB, and some hosts keep only
# the first few thousand characters. It also bounds what a mistaken path can
# publish to every client.
MAX_INSTRUCTIONS_BYTES = 16 * 1024

BOTH_INSTRUCTION_SOURCES_SET = (
    f"{INSTRUCTIONS_ENV} and {INSTRUCTIONS_PATH_ENV} are both set; set only "
    "one: the text itself, or the path to a UTF-8 file holding it."
)

# U+FEFF is dropped wherever it appears. As a byte-order mark it is not text
# (Notepad's UTF-8 starts with one), and as a zero-width no-break space it was
# deprecated long ago in favour of U+2060, so nothing an operator means is
# lost. Mid-text it comes from ``cat a.md b.md`` of two such files.
_BOM = "\ufeff"
_ACCEPTED_VARIABLES = frozenset({INSTRUCTIONS_ENV, INSTRUCTIONS_PATH_ENV})

# Spellings an operator plausibly meant as the token: whitespace or case
# variants, the single-brace form an f-string or str.format renders from
# ``{{default}}``, Mustache's triple braces, Go's ``{{ .Default }}``, shell's
# ``${default}``. The lookbehind is what keeps this linear: a match can start
# only at the first brace of a run, where without it every brace would start
# a scan to the end of the run, and a run of braces would cost O(n^2) — this
# repo has shipped one quadratic regex over raw text already (#474).
_NEAR_MISS_TOKEN = re.compile(
    r"\$?(?<!\{)\{++\s*+(?:\.\s*+)?defaults?\s*+\}++", re.IGNORECASE
)

# The escapes the docs teach for keeping the token away from a template
# engine, when the engine never ran: Helm's ``{{ "{{default}}" }}`` put in a
# values file rather than a chart template, or Jinja's ``{% raw %}`` around the
# token, or around the whole file, copied as it is. The token inside still
# expands, so clients get the built-in text wrapped in template syntax. A Go
# action may span lines. A raw block is found by pairing its tags, which
# scans the text between them once.
_HELM_ESCAPE = re.compile(r"""\{\{-?\s*(["'`])\{\{default\}\}\1\s*-?\}\}""")
_JINJA_RAW_TAG = re.compile(r"\{%[-+]?\s*(raw|endraw)\s*[-+]?%\}")

# A run of the characters a tool name, a path or a file name is made of:
# ASCII letters, digits and ``_``, Latin letters with accents (so ``sección``
# stays one word), and ``. / \ -``. A letter of any other script ends a run:
# Chinese and Japanese put no space around a Latin word, and Korean attaches
# particles to it (``zim_search를``). The runs are found in one pass, since
# nothing follows the class to backtrack into, and :func:`_tool_references`
# sorts each one out in Python. (A pattern that let a match start after
# every ``__`` inside a run was quadratic on ``zim__zim__…``.)
_WORD_RUN = re.compile(
    r"[0-9A-Za-z_"
    r"\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f\u0300-\u036f\u1e00-\u1eff"
    r"./\\-]+"
)
_TOOL_NAME_SHAPE = re.compile(r"zim_[a-z0-9_]+")
_TOOLS = frozenset(TOOL_NAMES)

# Calibrated on realistic misspellings and non-tool names. One letter off in
# zim_get, the shortest tool, scores 6/7 = 0.857 (zim_gte, zim_got), and every
# other typo tried scores more (zim_qry 0.875, zim_qeury 0.889, zim_serach
# 0.9). Below the cutoff sit zim_section and zim_get_sec (0.846), zim_list
# (0.824), and zim_data, zim_meta and zim_queries (0.8) — a volume name, an
# abbreviation and a plural — and no parameter, resource or path name the
# server or its docs use reaches it.
_TYPO_CUTOFF = 0.85
_MAX_TOOL_NAME = 64

# How a path starts: the root, a home directory, ``./`` or ``../``, a drive,
# a UNC share, or a variable that a JSON ``env`` block, systemd or Kubernetes
# passed through unexpanded (``$HOME/``, ``${HOME}/``, ``$(HOME)/``,
# ``%USERPROFILE%\``). Anchored, so even a search tries one position.
_PATH_START = re.compile(
    r"\A(?:/|~[^\s/\\]*[/\\]|\.{1,2}[/\\]|[A-Za-z]:[/\\]|\\\\"
    r"|\$\{?[A-Za-z_]\w*\}?[/\\]|\$\([A-Za-z_]\w*\)[/\\]|%[A-Za-z_]\w*%[/\\])"
)
_TEXT_FILE_SUFFIXES = (".md", ".markdown", ".txt")

# The quotes a value can arrive in, each opening quote with the closing ones
# it pairs with: an ``--env-file`` line keeps ASCII quotes, and a word
# processor or chat client makes them curly in its locale's style (“…” and
# ‘…’ in English, „…“ in German, „…” in Polish, ”…” in Swedish, «…» in French,
# »…« in Danish).
_QUOTE_PAIRS = {
    '"': '"',
    "'": "'",
    "“": "”",
    "‘": "’",
    "„": "“”",
    "‚": "‘’",
    "”": "”",
    "’": "’",
    "«": "»",
    "»": "«",
}

# Letters of the scripts written without spaces between words: Thai and
# Lao, Myanmar, Khmer, kana, and Han in its three blocks. In them one
# "word" can be a whole sentence that ends in a file name (Chinese
# 参见说明.md, Japanese 詳しくはREADME.md), so a name alone is no evidence of
# a path there.
_SPACELESS_SCRIPT = re.compile(
    r"[\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff\u3040-\u30ff"
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)


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
    """``None``, or a string with nothing in it but whitespace and BOMs.

    Blank means unset for both variables. Templated deployments (a compose
    ``${VAR}``, a Helm value, a host's JSON ``env`` block) render an unset
    variable as ``""``, and the path field would otherwise become
    ``Path(".")`` — a directory, so a startup error. A BOM counts wherever it
    sits, as everywhere else (see :data:`_BOM`); ``str.strip`` would keep it.
    """
    return value is None or (
        isinstance(value, str) and not value.replace(_BOM, "").strip()
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
    except ValueError as exc:  # a NUL in a ~user name, passed in from code
        raise OpenZimMcpConfigurationError(
            f"{INSTRUCTIONS_PATH_ENV}={str(value)!r} is not a usable path: {exc}."
        ) from exc


def resolve_instructions(
    tool_mode: str,
    *,
    inline: Optional[str] = None,
    path: str | Path | None = None,
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
    BOMs carried in from such a file are dropped (see :data:`_BOM`), after
    the check, so a position counts every character the value holds.
    """
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
    return _normalise_newlines(text.replace(_BOM, ""))


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
    except ValueError as exc:  # a NUL in a path set in code; env cannot hold one
        raise OpenZimMcpConfigurationError(
            f"{label} is not a usable path: {exc}."
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
    try:
        # A UTF-8 BOM decodes to U+FEFF, dropped with any others just below.
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = data.count(b"\n", 0, exc.start) + 1
        raise OpenZimMcpConfigurationError(
            f"{label} is not valid UTF-8: byte 0x{data[exc.start]:02x} at "
            f"offset {exc.start} (line {line}); save it as UTF-8."
        ) from exc
    text = _normalise_newlines(text.replace(_BOM, ""))
    if not text.strip():
        raise OpenZimMcpConfigurationError(
            f"{label} is empty (or holds only whitespace)."
        )
    return text


def _over_cap_message(
    label: str, size: int, expansions: int, default: str, tool_mode: str
) -> str:
    """Name what pushed the text over the cap, mode included.

    ``size`` is what clients would receive, not the file or the variable:
    trimmed, ended with one newline, every token expanded. Said so, because a
    16384-byte file without a final newline would otherwise be "16385 bytes"
    while ``ls -l`` says 16384. The same file can fit in simple mode (about
    0.5 KiB of built-in text per token) and not in advanced mode (about
    1.2 KiB), and the published image defaults to advanced while ``uvx``
    defaults to simple.
    """
    limit = f"the limit is {MAX_INSTRUCTIONS_BYTES} bytes (16 KiB)."
    if not expansions:
        return (
            f"{label} is {size} bytes as clients would receive it (trimmed, "
            f"with one final newline); {limit}"
        )
    each = len(default.rstrip("\n").encode("utf-8"))
    times = "once" if expansions == 1 else f"{expansions} times"
    return (
        f"{label} is {size} bytes as clients would receive it, once "
        f"{DEFAULT_TOKEN} expands ({times}, to the {each}-byte built-in "
        f"{tool_mode}-mode text); {limit}"
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
    It never contains the text itself. ``OPENZIM_MCP_LOGGING__LEVEL=WARNING``
    or above hides it, so only at INFO does its absence mean anything.
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
    matches = ((m.start(), m.group()) for m in _NEAR_MISS_TOKEN.finditer(text))
    return _distinct_spellings(text, matches, skip=DEFAULT_TOKEN)


def unrendered_escapes(text: str) -> List[Tuple[str, int]]:
    """Each distinct template escape of the token in ``text``, with its line.

    See :data:`_HELM_ESCAPE`: the token inside expands, and the escape around
    it is sent to clients as written. A Helm escape is quoted whole, a Jinja
    raw block by its opening tag, which keeps the operator's own text inside
    the block out of the log.
    """
    helm = ((m.start(), m.group()) for m in _HELM_ESCAPE.finditer(text))
    found = sorted(itertools.chain(helm, _raw_blocks_holding_the_token(text)))
    return _distinct_spellings(text, found)


def _raw_blocks_holding_the_token(text: str) -> Iterator[Tuple[int, str]]:
    """``(position, opening tag)`` of each Jinja raw block holding the token.

    Raw blocks do not nest: a ``{% raw %}`` inside one is text, and only the
    first ``{% endraw %}`` closes it. A tag that is a code span of its own
    (```{% raw %}```) is prose about the syntax, not an escape.
    """
    opened: Optional["re.Match[str]"] = None
    for tag in _JINJA_RAW_TAG.finditer(text):
        quoted = (
            text[tag.start() - 1 : tag.start()]
            == "`"
            == text[tag.end() : tag.end() + 1]
        )
        if quoted:
            continue
        if tag.group(1) == "raw":
            if opened is None:
                opened = tag
        elif opened is not None:
            if text.find(DEFAULT_TOKEN, opened.end(), tag.start()) != -1:
                yield opened.start(), opened.group()
            opened = None


def _distinct_spellings(
    text: str, found: Iterable[Tuple[int, str]], skip: Optional[str] = None
) -> List[Tuple[str, int]]:
    """Each distinct spelling in ``found`` but ``skip``, with the line it is on.

    ``found`` holds ``(position, spelling)`` pairs in order of position, so
    the line count runs on from one to the next and the whole scan stays one
    pass over the text.
    """
    spellings: List[Tuple[str, int]] = []
    seen = set()
    line, counted = 1, 0
    for start, spelling in found:
        if spelling == skip or spelling in seen:
            continue
        seen.add(spelling)
        line += text.count("\n", counted, start)
        counted = start
        spellings.append((spelling, line))
    return spellings


def _tool_references(text: str) -> Iterator[str]:
    """Each ``zim_*`` word in ``text`` that reads as a tool reference.

    Markdown emphasis around a name is not part of it (``__zim_search__``,
    ``_zim_query_``), nor are full stops after it, even inside the closing
    marker (``_Then call zim_get._``, which is how Prettier writes italics),
    and a client-qualified name such as ``mcp__openzim-mcp__zim_search``
    counts by its last part. Not references: the tail of a longer identifier
    in any script (``openzim_mcp``, ``my_zim_archive``, ``café_zim_search``,
    ``кафе_zim_search``), a dotted or file name (``tools.zim_search``,
    ``.zim_search``, ``zim_links.md``), a hyphenated or camel-case word
    (``zim_data-2024``, ``zim_searchAPI``), and a path (``/srv/zim_data``,
    ``zim_data\\x.zim``) — except that tool names joined by ``/`` and nothing
    else are alternatives (``zim_get/zim_get_section``).
    """
    for match in _WORD_RUN.finditer(text):
        run = _cleaned_run(text, match)
        if run is None or "zim_" not in run:
            continue
        if "/" in run or "\\" in run:
            parts = run.split("/")
            if len(parts) > 1 and all(part in _TOOLS for part in parts):
                yield from parts
            continue
        last = run.rsplit("__", 1)[-1]
        # ``zim__search`` is a doubled underscore, not a qualified ``search``.
        name = last if last.startswith("zim_") else run
        if _TOOL_NAME_SHAPE.fullmatch(name):
            yield name


def _cleaned_run(text: str, match: "re.Match[str]") -> Optional[str]:
    """A run without its emphasis and full stops, or ``None`` when it is part
    of a longer identifier.

    A letter or digit just outside a run is of another script, since a Latin
    one would have continued it. An underscore against it joins the two into
    one identifier (``кафе_zim_search``, ``zim_get_раздел``), unless the run
    has underscores at both ends and one side is free: that is emphasis,
    which Chinese and Japanese glue to the word before it and Korean to the
    particle after it (``用_zim_get_``, ``_zim_get_으로``). A hyphen after such
    a letter attaches a prefix, the way Hebrew writes ``ב-zim_search``.
    Emphasis comes off before full stops, which can sit inside the closing
    marker.
    """
    run = match.group()
    glued_before = text[match.start() - 1 : match.start()].isalnum()
    glued_after = text[match.end() : match.end() + 1].isalnum()
    leading, trailing = run.startswith("_"), run.endswith("_")
    if leading and trailing:
        identifier = glued_before and glued_after
    else:
        identifier = (leading and glued_before) or (trailing and glued_after)
    if identifier:
        return None
    if run.startswith("-") and glued_before:
        run = run[1:]
    return run.lstrip("_").rstrip("._")


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
    for name in _tool_references(text):
        if name in seen or name in served or len(name) > _MAX_TOOL_NAME:
            continue
        seen.add(name)
        if name in _TOOLS:
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
    """The inline text when it is a file path rather than instructions.

    The likeliest mix-up between the two variables: a path set where the text
    belongs is served to every client as the instructions. One line counts
    when it names a file that exists; when it is one word with a text-file
    extension, such as a file name or a relative path, unless it is written
    in a script without spaces, where one word can be a whole sentence
    (:data:`_SPACELESS_SCRIPT`); or when it starts like a path
    (:data:`_PATH_START`) and has no spaces or has such an extension, since
    the mount behind it may be missing too. Quotes and a command
    substitution no shell ran are taken off first (:func:`_unwrapped`).
    """
    candidate = _unwrapped(text.strip())
    if not candidate or "\n" in candidate:
        return None
    spaced = any(char.isspace() for char in candidate)
    suffixed = candidate.lower().endswith(_TEXT_FILE_SUFFIXES)
    file_name = suffixed and not spaced and _SPACELESS_SCRIPT.search(candidate) is None
    if file_name or (_PATH_START.match(candidate) and (suffixed or not spaced)):
        return candidate
    try:
        return candidate if Path(candidate).expanduser().is_file() else None
    except (OSError, RuntimeError, ValueError):  # ENAMETOOLONG, an unknown ~user
        return None


def _unwrapped(candidate: str) -> str:
    """``candidate`` without one pair of quotes around it, and without a
    command substitution that no shell ran: ``$(cat PATH)``, ``$(< PATH)``
    or a backquoted ``cat PATH``. A JSON ``env`` block or systemd passes those
    through as written, and the path inside is what was meant to be loaded.
    One level only, so no value can nest its way into a deep recursion.
    """
    candidate = _without_quotes(candidate)
    if candidate.startswith("$(") and candidate.endswith(")"):
        inner = candidate[2:-1].strip()
    elif len(candidate) > 1 and candidate[0] == candidate[-1] == "`":
        inner = candidate[1:-1].strip()
    else:
        return candidate
    for command in ("cat ", "<"):
        if inner.startswith(command):
            return _without_quotes(inner[len(command) :].strip())
    return candidate


def _without_quotes(candidate: str) -> str:
    if len(candidate) > 1 and candidate[-1] in _QUOTE_PAIRS.get(candidate[0], ""):
        return candidate[1:-1].strip()
    return candidate


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
    _warn_about_misspelt_variables(environ)
    custom = resolved.custom
    if custom is None:
        return
    _warn_about_tool_names(custom, tool_mode, registered_tools)
    _warn_about_near_misses(custom)
    _warn_about_unrendered_escapes(custom)
    if resolved.source == INSTRUCTIONS_ENV:
        _warn_about_an_inline_path(custom)


def _printable(name: str) -> str:
    """An environment name as logged: ``repr`` it when it would break the line
    or pass for another name. cmd.exe's ``set NAME = value`` keeps the space,
    and ``OPENZIM_MCP_INSTRUCTIONS `` would read as the real variable."""
    return name if name.isprintable() and " " not in name else repr(name)


def _warn_about_misspelt_variables(environ: Mapping[str, str]) -> None:
    misspelt = misspelt_instruction_variables(environ)
    if not misspelt:
        return
    logger.warning(
        "%s %s: the server reads %s (the text itself) and %s (a file holding it).",
        ", ".join(_printable(key) for key in misspelt),
        (
            "is not a setting and is ignored"
            if len(misspelt) == 1
            else "are not settings and are ignored"
        ),
        INSTRUCTIONS_ENV,
        INSTRUCTIONS_PATH_ENV,
    )


def _warn_about_tool_names(
    custom: str, tool_mode: str, registered_tools: Sequence[str]
) -> None:
    unregistered, typos = tool_name_findings(custom, registered_tools)
    if unregistered:
        logger.warning(
            "Server instructions name %s, which %s mode does not register; "
            "clients are offered only %s. Set OPENZIM_MCP_TOOL_MODE=advanced "
            "(or pass --mode advanced), or remove %s.",
            ", ".join(unregistered),
            tool_mode,
            ", ".join(registered_tools),
            "that name" if len(unregistered) == 1 else "those names",
        )
    if typos:
        logger.warning(
            "Server instructions name %s, which %s on this server.",
            ", ".join(_typo_with_suggestion(*typo) for typo in typos),
            "is not a tool" if len(typos) == 1 else "are not tools",
        )


def _typo_with_suggestion(name: str, suggestion: str, served: bool) -> str:
    note = "" if served else " It is registered in advanced mode only."
    return f"{name} (did you mean {suggestion}?{note})"


def _warn_about_near_misses(custom: str) -> None:
    misses = near_miss_tokens(custom)
    inert = [miss for miss in misses if DEFAULT_TOKEN not in miss[0]]
    padded = [miss for miss in misses if DEFAULT_TOKEN in miss[0]]
    if inert:
        logger.warning(
            "Server instructions contain %s, which %s not the %s token: only "
            "the exact text %s is replaced, and anything else is sent to "
            "clients as written.",
            _spellings(inert),
            "is" if len(inert) == 1 else "are",
            DEFAULT_TOKEN,
            DEFAULT_TOKEN,
        )
    if padded:
        # ``{{{default}}}`` and ``${{default}}`` hold the exact token, which
        # does expand — the INFO line says so — so "sent as written" would
        # contradict it.
        logger.warning(
            "Server instructions contain %s: the %s inside expands, but the "
            "characters around it are sent to clients as written.",
            _spellings(padded),
            DEFAULT_TOKEN,
        )


def _warn_about_unrendered_escapes(custom: str) -> None:
    escapes = unrendered_escapes(custom)
    if escapes:
        logger.warning(
            "Server instructions contain %s: a %s inside a template escape that "
            "was never rendered still expands, but the escape around it is sent "
            "to clients as written.",
            _spellings(escapes),
            DEFAULT_TOKEN,
        )


def _spellings(misses: Sequence[Tuple[str, int]]) -> str:
    return ", ".join(f"{spelling!r} (line {line})" for spelling, line in misses)


def _warn_about_an_inline_path(custom: str) -> None:
    named = _names_a_file(custom)
    if named is not None:
        logger.warning(
            "%s looks like a file path (%r); clients receive it as the "
            "instructions text. To load the file, set %s instead.",
            INSTRUCTIONS_ENV,
            named,
            INSTRUCTIONS_PATH_ENV,
        )
