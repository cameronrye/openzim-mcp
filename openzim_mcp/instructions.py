"""Server ``instructions`` advertised through the MCP ``server/discover`` result.

Protocol revision 2026-07-28 has no ``initialize`` handshake; ``server/discover``
is its stateless replacement, and that is where this text rides.

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
