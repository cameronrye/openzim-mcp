"""Argument completions for prompts and resource templates.

MCP lets a client ask what a given argument could be, which is how a picker
offers real choices instead of a free-text box. Every argument this server
exposes that names an archive was previously untyped: the user had to recall a
filesystem path or a bare basename and type it correctly, with a failed tool
call as the only feedback.

Two argument shapes are completable, and they are deliberately *not* the same
string. A prompt takes ``zim_file_path``, a full path the tools resolve against
the allowed directories. The ``zim://{name}`` resource template takes ``name``,
the bare basename without ``.zim`` — offering a path there would build a URI
that cannot resolve.

Everything else answers empty. A prompt topic is free text, and an entry path
inside an archive is unbounded — a Wikipedia mirror has millions. Returning
nothing is the honest answer, and it has to be an *empty list* rather than an
error: a raising handler surfaces in the client as a failed request rather than
as "no suggestions".
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional

from mcp.types import Completion

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

# The spec caps one completion response at 100 values. An allowed directory
# holding a full Kiwix mirror has far more, so the cap is enforced here and the
# true size reported in ``total`` rather than the list being silently cut.
MAX_COMPLETION_VALUES = 100

# Prompt arguments that name an archive by path. Keyed by prompt name so a new
# prompt with an unrelated ``zim_file_path`` argument cannot pick this up by
# accident.
_PATH_ARGUMENT_PROMPTS = {"summarize", "explore"}
_PATH_ARGUMENT = "zim_file_path"

# The resource template whose ``{name}`` segment is an archive basename.
_ARCHIVE_TEMPLATE_URI = "zim://{name}"
_ARCHIVE_TEMPLATE_ARGUMENT = "name"


def _page(values: List[str]) -> Completion:
    """Cap ``values`` at the protocol page size, reporting the true total."""
    total = len(values)
    page = values[:MAX_COMPLETION_VALUES]
    return Completion(
        values=page,
        total=total,
        has_more=total > len(page),
    )


def register_completions(server: "OpenZimMcpServer") -> None:
    """Register the ``completion/complete`` handler."""

    def _archives() -> List[dict]:
        """The current archive listing, read fresh on every request.

        Deliberately not cached at registration time: an operator dropping a
        new archive into an allowed directory is exactly when a user reaches
        for the picker to find it, and a startup snapshot would be missing it.
        """
        try:
            return server.zim_operations.list_zim_files_data()
        except Exception:  # noqa: BLE001 - a picker must not break the session
            logger.warning("completion: archive listing failed", exc_info=True)
            return []

    def _matching(values: List[str], typed: str) -> List[str]:
        """Values consistent with what the user has typed so far.

        Case-insensitive, and matched on the basename as well as the whole
        string so typing ``wikipedia`` still offers
        ``/srv/zim/wikipedia_en.zim``.
        """
        if not typed:
            return values
        needle = typed.lower()
        return [
            v
            for v in values
            if v.lower().startswith(needle) or Path(v).name.lower().startswith(needle)
        ]

    @server.mcp.completion()
    async def complete(
        ref: Any, argument: Any, context: Any = None
    ) -> Optional[Completion]:
        """Offer archive choices for the two argument shapes that have them."""
        name = getattr(argument, "name", None)
        typed = getattr(argument, "value", "") or ""

        ref_type = getattr(ref, "type", None)
        if ref_type == "ref/prompt":
            if getattr(ref, "name", None) not in _PATH_ARGUMENT_PROMPTS:
                return _page([])
            if name != _PATH_ARGUMENT:
                return _page([])
            paths = [row["path"] for row in _archives()]
            return _page(_matching(paths, typed))

        if ref_type == "ref/resource":
            if getattr(ref, "uri", None) != _ARCHIVE_TEMPLATE_URI:
                return _page([])
            if name != _ARCHIVE_TEMPLATE_ARGUMENT:
                return _page([])
            # ``{name}`` is the basename without the extension — the same form
            # ``zim_file_overview`` resolves and ``resources/list`` advertises.
            stems = [Path(row["path"]).stem for row in _archives()]
            return _page(_matching(stems, typed))

        return _page([])
