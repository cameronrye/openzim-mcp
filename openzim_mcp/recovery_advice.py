"""Mode-aware recovery clauses for runtime error and content messages.

Every clause here is the tail of a message a *client* reads while it is
recovering from a failure, so it may only name something that client can
actually issue. ``tool_mode='simple'`` (the default —
``ServerDefaults.TOOL_MODE``, and what the README tells users to
copy-paste) registers ``zim_query`` alone, so an advanced tool name there
describes a tool the client cannot see. The simple half is therefore
phrased as a query :class:`openzim_mcp.intent_parser.IntentParser`
actually resolves; a plain-English paraphrase would be worse than useless,
because it parses as a literal full-text search for its own text.

The clauses live in one module for two reasons:

* the call sites (``zim/content.py``, ``zim/archive.py``,
  ``content_processor.py``) then contain no tool name at all, so a scan of
  the package can insist that only modules the guard *renders* may name a
  tool in a runtime string;
* ``tests/test_recovery_advice_tool_names.py`` renders every clause below
  in both modes against the live tool registry, which is what makes that
  insistence worth anything.

Each function defaults to the fail-safe mode: a caller that forgets to
thread ``tool_mode`` degrades to a ``zim_query``-shaped instruction rather
than to an uncallable tool name.

The advanced wording is deliberately unchanged from what these messages
carried before the split, ``Try using zim_search()`` phrasing included —
``SimpleToolsHandler._BACKEND_API_LEAK_RE`` strips that exact sentence
shape out of echoed backend errors, and rewording it here would change
what advanced ``zim_query`` callers see for reasons unrelated to this fix.
"""

from __future__ import annotations

ADVANCED = "advanced"


def locate_entry(tool_mode: str) -> str:
    """The tail of a "that path is not in the archive" message."""
    return (
        "Try using zim_search() to find available entries."
        if tool_mode == ADVANCED
        else "Ask for `find article titled <title>` to locate the entry."
    )


def locate_or_explore(tool_mode: str) -> str:
    """Same miss, on the surfaces that also offer namespace exploration."""
    return (
        "Try using zim_search() to find available entries, or zim_browse() "
        "to explore the archive's namespaces."
        if tool_mode == ADVANCED
        else "Ask for `find article titled <title>` to locate the entry, or "
        "`list namespaces` to see what the archive holds."
    )


def correct_entry_path(tool_mode: str) -> str:
    """The path may be misspelt rather than absent."""
    return (
        "Try using zim_search() to find the correct entry path."
        if tool_mode == ADVANCED
        else "Ask for `find article titled <title>` to get the correct path."
    )


def verify_archive(tool_mode: str) -> str:
    """The archive itself may be unreadable, not the entry."""
    return (
        "Try using zim_health() to verify the archive is loaded and readable."
        if tool_mode == ADVANCED
        else "Ask for `list available ZIM files` to check the archive loaded."
    )


def metadata_keys(tool_mode: str) -> str:
    """A miss under the ``M/`` (metadata) namespace."""
    return (
        'Use zim_browse(namespace="M") to list the available keys.'
        if tool_mode == ADVANCED
        else "Ask for `browse namespace M` to list the available keys."
    )


def fetch_binary(tool_mode: str) -> str:
    """An entry whose bytes cannot be rendered as text.

    Named as the single-entry call rather than a bare ``binary=True``:
    batch mode rejects that combination, so the shorter phrasing sent
    batch callers to an error.
    """
    return (
        "fetch it with zim_get(entry_path=..., binary=True)"
        if tool_mode == ADVANCED
        else "ask for `get binary content of <path>`"
    )
