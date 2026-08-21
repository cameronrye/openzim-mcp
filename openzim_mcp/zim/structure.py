"""Article-structure methods for ``ZimOperations``.

This mixin handles HTML structure extraction: headings, sections, links,
table-of-contents, and link-following for related-article discovery.
Methods run as instance methods of ``ZimOperations`` via the mixin
pattern.

``zim_archive`` is accessed through ``openzim_mcp.zim_operations`` so
existing test patches against the shim's symbols continue to work
without changes.
"""

import logging
from contextlib import suppress
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    NamedTuple,
    Optional,
    Tuple,
    Union,
    cast,
)
from urllib.parse import unquote

from libzim.reader import Archive  # type: ignore[import-untyped]

import openzim_mcp.zim_operations as _zim_ops_mod
from openzim_mcp.exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpCursorMismatchError,
    OpenZimMcpFileNotFoundError,
    OpenZimMcpValidationError,
)
from openzim_mcp.meta import attach_meta
from openzim_mcp.pagination import Cursor
from openzim_mcp.responses import ToolErrorPayload, tool_error
from openzim_mcp.zim._ops_base import _json
from openzim_mcp.zim.content import _strip_markdown_links_shared, reject_path_traversal

if TYPE_CHECKING:
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator
    from openzim_mcp.tool_schemas import (
        ArticleStructureResponse,
        GetSectionResponse,
        LinksResponse,
        RelatedArticlesResponse,
        SectionMeta,
        TableOfContentsResponse,
        TocHeading,
    )

logger = logging.getLogger(__name__)


def _resolve_entry_spelling(archive: Any, path: str) -> Tuple[Optional[Any], str]:
    """Return ``(entry, spelling)`` for whichever spelling of ``path`` resolves.

    ZIM stores entry paths as raw UTF-8 (``A/El_Niño``) while the ``<a href>``
    in archived HTML is percent-encoded per RFC 3986 (``El_Ni%C3%B1o``).
    ``_resolve_link_to_entry_path`` normalises the href but never decodes it,
    so link targets for any article with a non-ASCII or reserved character in
    its path came back in a spelling libzim cannot serve — unfetchable if the
    caller passed it to ``zim_get``, and an unusable key in the inbound link
    graph.

    The RAW spelling is tried first and the decoded one only as a fallback,
    because some archives genuinely store a literal ``%`` in a path (warc2zim
    asset names such as ``I/Al_Gore%2C_2007.webp``); decoding unconditionally
    would break the paths that already work.

    Returns ``(None, path)`` unchanged when neither spelling resolves, so a
    caller that cannot verify the target still keeps its best-effort edge
    rather than dropping it.
    """
    # Broad on purpose: libzim reports a miss as a bare ``KeyError`` and a
    # corrupt cluster as ``RuntimeError``, and the probe's only job is to
    # answer "does this spelling resolve?" — any failure means "no". Callers
    # such as ``get_inbound_links_data`` rely on it never raising.
    with suppress(Exception):
        return archive.get_entry_by_path(path), path
    decoded = unquote(path)
    if decoded != path:
        with suppress(Exception):
            return archive.get_entry_by_path(decoded), decoded
    return None, path


# Prefix shared by every servable article mimetype (``text/html`` and
# ``text/html; charset=utf-8``). The structure views answer "is there
# anything to parse?" with this one test.
_HTML_MIME_PREFIX = "text/html"

# Mimetype families that are never navigable articles. Used by
# ``_StructureMixin._is_non_article_target`` so query-string / extensionless
# asset URLs (e.g. ``fonts.googleapis.com/css2?family=...`` mimetype
# ``text/css``, ``...?css=...``) are caught even when the path-extension
# heuristic misses. ``text/html`` and ``application/xhtml+xml`` are
# intentionally absent — they are real articles.
_ASSET_MIME_EXACT = frozenset(
    {
        "text/css",
        "application/javascript",
        "text/javascript",
        "application/json",
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-font-ttf",
        "application/x-font-woff",
        "application/font-woff",
        "application/vnd.ms-fontobject",
    }
)
_ASSET_MIME_PREFIXES = ("image/", "video/", "audio/", "font/")

_LINK_KINDS = frozenset({"internal", "external", "media"})


def _resolve_outbound_item(archive: Any, item: Dict[str, Any]) -> None:
    """Rewrite one outbound row's ``path`` to the servable spelling; fill ``title``.

    The href the row was built from is percent-encoded, so a non-ASCII
    target arrived here as ``A/El_Ni%C3%B1o`` — which both failed the title
    lookup (leaving the raw path as the "title" placeholder) and, worse,
    went out on the wire as a ``path`` the caller could not fetch.
    ``_resolve_entry_spelling`` picks whichever spelling the archive serves.

    A redirect stub is followed to its canonical target before the title is
    read; ``title`` is left alone when nothing resolvable has one, so the
    caller's placeholder survives. Raises whatever the archive raises — the
    caller (``_resolve_outbound_titles``) treats any failure as "keep the
    placeholder".
    """
    from openzim_mcp.zim.redirects import best_effort_redirect_chain

    entry, spelling = _resolve_entry_spelling(archive, item["path"])
    # ``is True``: the mock archives used across the test suite hand back
    # MagicMock entries whose ``is_redirect`` is itself a truthy MagicMock.
    if entry is not None and getattr(entry, "is_redirect", False) is True:
        resolved = best_effort_redirect_chain(entry)
        resolved_path = getattr(resolved, "path", None)
        if isinstance(resolved_path, str) and resolved_path:
            entry, spelling = resolved, resolved_path
    item["path"] = spelling
    title = getattr(entry, "title", None) if entry else None
    if title:
        item["title"] = title


class _OutboundLinkBuckets(NamedTuple):
    """One article's outbound links, split the way ``zim_links`` reports them.

    Built by ``_StructureMixin._bucket_outbound_links`` from the cached
    bundle's raw ``internal`` / ``external`` / ``media`` lists.
    """

    internal: List[Any]
    """Cross-article links only: anchors and anchor-wrapped assets removed."""

    external: List[Any]
    media: List[Any]
    """The page's own media rows plus anchor-wrapped assets (``type="asset"``)."""

    anchor_count: int
    """In-page ``#fragment`` links dropped from ``internal``."""

    folded_targets: set[str]
    """Entry paths of media rows that absorbed a same-target anchor."""

    def for_kind(self, kind: str) -> List[Any]:
        if kind == "internal":
            return self.internal
        if kind == "media":
            return self.media
        return self.external


def _entry_not_found_error(entry_path: str) -> OpenZimMcpArchiveError:
    """Typed not-found error for a missing ``entry_path``.

    libzim reports a miss as a bare ``KeyError('Cannot find entry')``. Left
    unwrapped it reaches the tool wrappers' broad ``except`` and renders as
    a generic "Operation Failed / KeyError" envelope advising retries and a
    health check; wrapped as a generic archive error it renders as
    "verify the ZIM file is not corrupted". Neither points at the one thing
    actually wrong — the path. The "Entry not found" phrasing is what
    ``error_messages.get_error_config`` pattern-matches onto the focused
    *Resource Not Found* template, the same envelope ``zim_get`` produces
    for the identical miss.
    """
    return OpenZimMcpArchiveError(
        f"Entry not found: '{entry_path}'. Double-check the spelling and "
        "path (entry paths are case-sensitive), or use "
        "`zim_search(mode='title')` to locate the entry."
    )


def _section_preview(
    md: str, char_start: int, char_end: int, preview_chars: int
) -> str:
    """Slice a section's lead preview, bounded by ``char_end``.

    ``char_end`` is the start of the next equal-or-higher-level heading, so
    bounding the slice there keeps the preview to the section's OWN content.
    Previously the slice was a fixed ``char_start + preview_chars`` window
    that bled the heading and body of the following section into a short
    section's preview.
    """
    end = min(char_start + preview_chars, char_end)
    return md[char_start:end]


def _sections_to_toc_tree(sections: "List[SectionMeta]") -> "List[TocHeading]":
    """Build a hierarchical TOC tree from a flat SectionMeta list.

    Uses a stack to nest headings by level. Each TocHeading has the
    Phase C field name ``section_id`` (renamed from the old ``id``).
    """
    root: "List[TocHeading]" = []
    stack: "List[Tuple[int, List[TocHeading]]]" = [(0, root)]

    for s in sections:
        node_dict: Dict[str, Any] = {
            "section_id": s["id"],
            "text": s["title"],
            "level": s["level"],
            "children": [],
        }
        # ``id_source`` is preserved per the Phase C spec so callers can
        # tell stable anchors from generated slugs. Drop when absent so
        # the wire shape stays minimal for bundles built before the
        # field was tracked.
        if "id_source" in s:
            node_dict["id_source"] = s["id_source"]
        node: "TocHeading" = cast("TocHeading", node_dict)
        while stack and stack[-1][0] >= s["level"]:
            stack.pop()
        if stack:
            stack[-1][1].append(node)
        else:
            root.append(node)
        stack.append((s["level"], node["children"]))

    return root


class _StructureMixin:
    """Article-structure / link / TOC methods for ZimOperations."""

    if TYPE_CHECKING:
        config: "OpenZimMcpConfig"
        path_validator: "PathValidator"
        cache: "OpenZimMcpCache"
        content_processor: "ContentProcessor"

        def _validate_zim_path(self, zim_file_path: str) -> Path:
            """Resolve via ``_ArchiveAccessMixin`` on the concrete coordinator."""

        def _resolve_entry_with_fallback(
            self, archive: Archive, entry_path: str
        ) -> Tuple[Any, str]:
            """Resolve via ``ZimOperations`` on the concrete coordinator."""

    def _build_bundle(
        self,
        archive: Archive,
        entry_path: str,
        *,
        validated_path: Path,
        compact: bool = True,
    ) -> Any:
        """``get_or_build_bundle`` with the libzim miss surfaced as not-found.

        Every bundle consumer in this mixin (structure / TOC / links /
        section) used to let the lookup ``KeyError`` escape into a broad
        ``except Exception`` that re-labelled it an extraction failure.
        Converting it here, at the single place the lookup happens, keeps
        all four surfaces on the same not-found classification as
        ``zim_get``.
        """
        from openzim_mcp.bundle import get_or_build_bundle

        try:
            return get_or_build_bundle(
                archive,
                entry_path,
                cache=self.cache,
                validated_path=validated_path,
                content_processor=self.content_processor,
                compact=compact,
            )
        except KeyError as e:
            raise _entry_not_found_error(entry_path) from e

    def get_article_structure_data(
        self, zim_file_path: str, entry_path: str
    ) -> "ArticleStructureResponse":
        """Structured variant of ``get_article_structure``.

        Returns the result dict directly (not a JSON string) so MCP tools
        can hand it straight to the SDK's structured-content path.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If structure extraction fails
        """
        reject_path_traversal(entry_path)

        # Validate and resolve file path
        validated_path = self._validate_zim_path(zim_file_path)

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result = self._extract_article_structure_data(
                    archive, entry_path, validated_path=validated_path
                )

            logger.info(f"Extracted structure for: {entry_path}")
            return cast("ArticleStructureResponse", result)

        except OpenZimMcpArchiveError:
            # Inner helper already raised a typed archive error with full
            # context. Don't re-wrap and double the message prefix.
            raise
        except Exception as e:
            logger.error(f"Structure extraction failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Structure extraction failed: {e}") from e

    def get_article_structure(self, zim_file_path: str, entry_path: str) -> str:
        """Legacy JSON-string variant of ``get_article_structure_data``.

        Extract article structure including headings, sections, and key metadata.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'

        Returns:
            JSON string containing article structure

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If structure extraction fails
        """
        return _json(self.get_article_structure_data(zim_file_path, entry_path))

    def _extract_article_structure_data(
        self,
        archive: Archive,
        entry_path: str,
        *,
        validated_path: "Optional[Path]" = None,
    ) -> "ArticleStructureResponse":
        """Extract structure from article content via bundle."""
        if validated_path is None:
            # Falling back to Path(entry_path) makes the bundle cache key
            # archive-agnostic — the same key collides across every ZIM
            # whose archive holds this entry path. Require the caller to
            # pass the resolved archive path so bundles stay archive-bound.
            raise OpenZimMcpValidationError(
                "_extract_article_structure_data requires validated_path"
            )

        try:
            bundle = self._build_bundle(
                archive, entry_path, validated_path=validated_path
            )

            md = bundle["rendered_markdown"]
            PREVIEW_CHARS = 300

            headings = [
                {
                    "id": s["id"],
                    "text": s["title"],
                    "level": s["level"],
                    "position": i,
                }
                for i, s in enumerate(bundle["sections"])
            ]
            sections = [
                {
                    "title": s["title"],
                    "level": s["level"],
                    "content_preview": _section_preview(
                        md, s["char_start"], s["char_end"], PREVIEW_CHARS
                    ),
                }
                for s in bundle["sections"]
            ]
            payload: "ArticleStructureResponse" = cast(
                "ArticleStructureResponse",
                {
                    "title": bundle["title"],
                    "path": bundle["entry_path"],
                    "content_type": bundle["content_type"],
                    "headings": headings,
                    "sections": sections,
                    "metadata": {},
                    "word_count": bundle["word_count"],
                    "character_count": bundle["char_count"],
                },
            )
            return cast(
                "ArticleStructureResponse",
                attach_meta(cast(Dict[str, Any], payload)),
            )

        except OpenZimMcpArchiveError:
            raise
        except Exception as e:
            logger.error(f"Error extracting structure for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(
                f"Failed to extract article structure: {e}"
            ) from e

    @staticmethod
    def _validate_links_args(limit: int, offset: int, kind: str) -> None:
        """Reject out-of-range ``extract_article_links_data`` arguments.

        Caller-input validation surfaces as OpenZimMcpValidationError so the
        tool layer can render a targeted validation message (separate from
        archive-access errors).
        """
        if limit < 1 or limit > 500:
            raise OpenZimMcpValidationError(
                f"limit must be between 1 and 500 (provided: {limit})"
            )
        if offset < 0:
            raise OpenZimMcpValidationError(
                f"offset must be non-negative (provided: {offset})"
            )
        if kind not in _LINK_KINDS:
            raise OpenZimMcpValidationError(
                f"kind must be one of 'internal', 'external', 'media' "
                f"(provided: {kind!r})"
            )

    @staticmethod
    def _verify_links_cursor_identity(
        cursor_archive_identity: Optional[str], validated_path: Path
    ) -> None:
        """Cursor integrity (Phase B #11).

        A cursor issued for archive A must not be honoured when resubmitted
        against archive B. No-op when the call carried no cursor.
        """
        if cursor_archive_identity is None:
            return
        from openzim_mcp.pagination import Cursor as _CursorClass
        from openzim_mcp.pagination import (
            CursorMismatchError,
            archive_identity,
        )

        try:
            _CursorClass.verify_archive_identity(
                cast("Any", {"ai": cursor_archive_identity}),
                expected=archive_identity(validated_path),
                tool="extract_article_links",
            )
        except CursorMismatchError as e:
            raise OpenZimMcpCursorMismatchError(str(e)) from e

    def _media_target(self, link: Any, entry_path: str) -> Optional[str]:
        """Entry path a media/anchor row's href resolves to, or ``None``."""
        return self._resolve_link_to_entry_path(str(link.get("url", "")), entry_path)

    def _bucket_outbound_links(self, bundle: Any) -> _OutboundLinkBuckets:
        """Split the bundle's raw link lists into the reported categories.

        BUG #6: the bundle 'internal' bucket carries BOTH real
        cross-article links (type=='internal') and in-page '#anchor'
        fragment links (type=='anchor'). Anchors are not navigation targets
        and are dropped by the inbound link-graph builder, so exclude them
        from the 'internal' kind's results/total and the internal count,
        surfacing them under a separate 'anchor' count so outbound and
        inbound agree on cross-article link totals.

        zimit/warc2zim wraps an article's lead image (and figure links) in
        ``<a href="…/plato.jpg">``, so the anchor classifier typed
        image/font/script assets 'internal' and they inflated
        ``category_totals.internal`` — while the related direction and the
        sidecar builder both drop them via ``_is_non_article_target``. Apply
        the same test here: assets move to the media bucket
        (``type="asset"``, after the page's own ``<img>``-style rows) so
        'internal' counts navigable articles consistently across directions.

        R2-6: zimit's ``<a href="x.jpg"><img src="x.jpg">`` is ONE asset,
        but the ``<img>`` already sits in the media bucket, so the
        reclassified anchor doubled it (and the media total). Rule: an
        anchor whose href resolves to the same entry path as an existing
        media row is folded into that row — the richer ``image`` row
        survives and inherits the anchor's fetchable ``path``. Anchors to a
        genuinely different entry (full-size file vs thumbnail) keep their
        own ``asset`` row.
        """
        entry_path: str = bundle["entry_path"]
        internal_bucket: List[Any] = cast("List[Any]", bundle["links"]["internal"])
        non_anchor_internal = [
            lk
            for lk in internal_bucket
            if not (isinstance(lk, dict) and lk.get("type") == "anchor")
        ]
        anchor_count = len(internal_bucket) - len(non_anchor_internal)

        media_rows: List[Any] = list(bundle["links"]["media"])
        media_targets = {
            t
            for t in (
                self._media_target(lk, entry_path)
                for lk in media_rows
                if isinstance(lk, dict)
            )
            if t
        }
        cross_article_internal: List[Any] = []
        anchor_wrapped_assets: List[Any] = []
        folded_targets: set[str] = set()
        for lk in non_anchor_internal:
            if isinstance(lk, dict) and self._is_non_article_target(
                str(lk.get("url", ""))
            ):
                target = self._media_target(lk, entry_path)
                if target and target in media_targets:
                    folded_targets.add(target)
                    continue
                anchor_wrapped_assets.append({**lk, "type": "asset"})
            else:
                cross_article_internal.append(lk)
        return _OutboundLinkBuckets(
            internal=cross_article_internal,
            external=cast("List[Any]", bundle["links"]["external"]),
            media=media_rows + anchor_wrapped_assets,
            anchor_count=anchor_count,
            folded_targets=folded_targets,
        )

    def _resolve_page_paths(
        self,
        archive: Any,
        kind: str,
        page: List[Any],
        folded_targets: set[str],
        entry_path: str,
    ) -> List[Any]:
        """Attach a fetchable ``path`` to the rows of ``page`` that earn one.

        ``url`` is the raw document-relative href (``../aristotl``) and
        does not round-trip into ``zim_get`` or the other directions;
        related/inbound already ship a resolved ``path``. Internal rows get
        one here too — resolved against the SERVED entry (``entry_path`` is
        post-redirect) and redirect-followed where the archive can verify
        it. Fresh dicts: ``page`` aliases the cached bundle's rows.

        Anchor-wrapped assets were ``<a href>``s, so they get the same
        resolved ``path`` internal rows do — usable with
        ``zim_get(binary=True)``. Media rows that absorbed such an anchor
        get it too, so folding loses nothing. External rows pass through
        untouched.
        """
        if kind == "internal":
            return [self._with_resolved_path(archive, lk, entry_path) for lk in page]
        if kind == "media":
            return [
                (
                    self._with_resolved_path(archive, lk, entry_path)
                    if isinstance(lk, dict)
                    and (
                        lk.get("type") == "asset"
                        or self._media_target(lk, entry_path) in folded_targets
                    )
                    else lk
                )
                for lk in page
            ]
        return page

    def extract_article_links_data(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 100,
        offset: int = 0,
        kind: str = "internal",
        *,
        cursor_archive_identity: Optional[str] = None,
    ) -> "LinksResponse":
        """Structured variant of ``extract_article_links``. v2 Phase B contract.

        Returns the result dict directly (not a JSON string) so MCP tools
        can hand it straight to the SDK's structured-content path.

        v2 Phase B: ``kind`` is required-with-default. Each call returns
        exactly one category in ``results``; ``category_totals`` reports
        the full counts for all three categories so callers can size
        their next request. To enumerate all three categories, issue
        three calls with different ``kind`` values.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'
            limit: Max items per page (1-500, default 100).
            offset: Starting offset within the requested category (default 0).
            kind: Which category to return — ``"internal"`` (default),
                ``"external"``, or ``"media"``.

        Returns:
            ``LinksResponse``: ``results`` (paged subset of one category),
            top-level contract keys (``next_cursor``, ``total``, ``done``,
            ``page_info``), plus ``title``, ``path``, ``content_type``,
            ``kind``, and ``category_totals`` (full counts per category).

        Raises:
            OpenZimMcpValidationError: limit/offset/kind out of range.
            OpenZimMcpFileNotFoundError: If ZIM file not found.
            OpenZimMcpArchiveError: If link extraction fails.
        """
        self._validate_links_args(limit, offset, kind)

        reject_path_traversal(entry_path)

        # Validate and resolve file path
        validated_path = self._validate_zim_path(zim_file_path)

        self._verify_links_cursor_identity(cursor_archive_identity, validated_path)

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                bundle = self._build_bundle(
                    archive, entry_path, validated_path=validated_path
                )
                buckets = self._bucket_outbound_links(bundle)
                all_links_for_kind = buckets.for_kind(kind)
                total_for_kind = len(all_links_for_kind)
                page = self._resolve_page_paths(
                    archive,
                    kind,
                    all_links_for_kind[offset : offset + limit],
                    buckets.folded_targets,
                    bundle["entry_path"],
                )
            returned_count = len(page)
            last_index = offset + returned_count
            done = last_index >= total_for_kind
            next_cursor: Optional[str] = None
            if not done:
                from openzim_mcp.pagination import archive_identity

                next_cursor = Cursor.encode(
                    tool="extract_article_links",
                    state={
                        "o": last_index,
                        "l": limit,
                        "ep": entry_path,
                        "k": kind,
                        "ai": archive_identity(validated_path),
                    },
                )

            payload: Dict[str, Any] = {
                "title": bundle["title"],
                "path": bundle["entry_path"],
                "content_type": bundle["content_type"],
                "kind": kind,
                "results": page,
                "next_cursor": next_cursor,
                "total": total_for_kind,
                "done": done,
                "page_info": {
                    "offset": offset,
                    "limit": limit,
                    "returned_count": returned_count,
                },
                "category_totals": {
                    "internal": len(buckets.internal),
                    "external": len(buckets.external),
                    "media": len(buckets.media),
                    "anchor": buckets.anchor_count,
                },
            }
            # ``LinksResponse.message`` is documented as set for non-HTML
            # entries, and the sibling TOC payload sets it; without it an
            # image entry's empty result was indistinguishable from an
            # article that simply has no links.
            if not bundle["content_type"].startswith(_HTML_MIME_PREFIX):
                payload["message"] = (
                    f"Link extraction requires HTML content, "
                    f"got: {bundle['content_type']}"
                )

            logger.info(
                f"Extracted links for: {entry_path} "
                f"(limit={limit}, offset={offset}, kind={kind})"
            )
            return cast("LinksResponse", attach_meta(payload))

        except OpenZimMcpValidationError:
            raise
        except OpenZimMcpArchiveError:
            # Inner helper already raised a typed archive error with full
            # context. Don't re-wrap and double the message prefix.
            raise
        except Exception as e:
            logger.error(f"Link extraction failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Link extraction failed: {e}") from e

    def extract_article_links(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 100,
        offset: int = 0,
        kind: str = "internal",
    ) -> str:
        """Legacy JSON-string variant of ``extract_article_links_data``.

        Extract links of one category from an article, with pagination.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'
            limit: Max items per page (1-500, default 100).
            offset: Starting offset within the requested category (default 0).
            kind: Which category — ``"internal"`` (default), ``"external"``,
                or ``"media"``.

        Returns:
            JSON string containing the v2 Phase B ``LinksResponse`` payload
            (single-category ``results`` plus pagination contract).

        Raises:
            OpenZimMcpValidationError: limit/offset/kind out of range.
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If link extraction fails
        """
        return _json(
            self.extract_article_links_data(
                zim_file_path,
                entry_path,
                limit=limit,
                offset=offset,
                kind=kind,
            )
        )

    def get_table_of_contents_data(
        self, zim_file_path: str, entry_path: str
    ) -> "TableOfContentsResponse":
        """Structured variant of ``get_table_of_contents``.

        Returns the result dict directly (not a JSON string) so MCP tools
        can hand it straight to the SDK's structured-content path.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If TOC extraction fails
        """
        reject_path_traversal(entry_path)

        # Validate and resolve file path
        validated_path = self._validate_zim_path(zim_file_path)

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result = self._extract_table_of_contents_data(
                    archive, entry_path, validated_path=validated_path
                )

            logger.info(f"Extracted TOC for: {entry_path}")
            return cast("TableOfContentsResponse", result)

        except OpenZimMcpArchiveError:
            # Inner helper already raised a typed archive error with full
            # context. Don't re-wrap and double the message prefix.
            raise
        except Exception as e:
            logger.error(f"TOC extraction failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"TOC extraction failed: {e}") from e

    def get_table_of_contents(self, zim_file_path: str, entry_path: str) -> str:
        """Legacy JSON-string variant of ``get_table_of_contents_data``.

        Extract a hierarchical table of contents from an article.

        Returns a structured TOC tree based on heading levels (h1-h6),
        suitable for navigation and content overview.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'

        Returns:
            JSON string containing hierarchical table of contents

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If TOC extraction fails
        """
        return _json(self.get_table_of_contents_data(zim_file_path, entry_path))

    def _extract_table_of_contents_data(
        self,
        archive: Archive,
        entry_path: str,
        *,
        validated_path: "Optional[Path]" = None,
    ) -> "TableOfContentsResponse":
        """Extract hierarchical table of contents from article via bundle."""
        if validated_path is None:
            # Same archive-binding requirement as
            # _extract_article_structure_data — without a real archive
            # path the bundle cache collides cross-archive.
            raise OpenZimMcpValidationError(
                "_extract_table_of_contents_data requires validated_path"
            )

        try:
            bundle = self._build_bundle(
                archive, entry_path, validated_path=validated_path
            )

            payload: "TableOfContentsResponse" = cast(
                "TableOfContentsResponse",
                {
                    "title": bundle["title"],
                    "path": bundle["entry_path"],
                    "content_type": bundle["content_type"],
                    "toc": _sections_to_toc_tree(bundle["sections"]),
                    "heading_count": len(bundle["sections"]),
                    "max_depth": max(
                        (s["level"] for s in bundle["sections"]), default=0
                    ),
                },
            )
            if not bundle["content_type"].startswith(_HTML_MIME_PREFIX):
                payload["message"] = (
                    f"TOC extraction requires HTML content, "
                    f"got: {bundle['content_type']}"
                )
            elif not bundle["sections"]:
                payload["message"] = "No headings found in article"
            return cast(
                "TableOfContentsResponse",
                attach_meta(cast(Dict[str, Any], payload)),
            )

        except OpenZimMcpArchiveError:
            raise
        except Exception as e:
            logger.error(f"Error extracting TOC for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(
                f"Failed to extract table of contents: {e}"
            ) from e

    def get_section_data(
        self,
        zim_file_path: str,
        entry_path: str,
        section_id: str,
        *,
        max_chars: "Optional[int]" = None,
        include_subsections: bool = True,
        compact: bool = True,
    ) -> "Union[GetSectionResponse, ToolErrorPayload]":
        """Public entry point for the get_section tool.

        ``include_subsections`` (Op3): when ``True`` (the default), the
        returned slice covers the requested section plus every nested
        descendant (Geography → Geography + Topography + Climate, the
        legacy behavior). When ``False``, the slice ends at the next
        heading of *any* level, so a caller can fetch just the
        Geography lead-paragraph without the H3 subsections it
        contains. Small models that have already seen the TOC can
        choose the subsection IDs directly; ``False`` lets them avoid
        re-pulling the full sub-tree just to get a narrow span.

        Returns the typed response or a ToolErrorPayload on
        file-not-found / entry-not-found / section-not-found.
        """
        # A non-positive cap reaches the body slice as a Python negative
        # index and trims the section TAIL (``max_chars=-5`` returns all
        # but the last 5 chars, flagged ``truncated``). Reject it the way
        # the sibling surfaces reject ``max_content_length < 1``.
        if max_chars is not None and max_chars < 1:
            return tool_error(
                operation="invalid_max_chars",
                message=(
                    f"`max_chars` must be a positive integer (provided: {max_chars})."
                ),
            )
        try:
            reject_path_traversal(entry_path)
            validated_path = self._validate_zim_path(zim_file_path)
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                return self._get_section_data(
                    archive,
                    validated_path,
                    entry_path,
                    section_id,
                    max_chars,
                    include_subsections=include_subsections,
                    compact=compact,
                )
        except OpenZimMcpFileNotFoundError as e:
            return tool_error(operation="file_not_found", message=str(e))
        except OpenZimMcpArchiveError as e:
            return tool_error(operation="entry_not_found", message=str(e))

    def _get_section_data(
        self,
        archive: Archive,
        validated_path: Path,
        entry_path: str,
        section_id: str,
        max_chars: "Optional[int]",
        *,
        include_subsections: bool = True,
        compact: bool = True,
    ) -> "Union[GetSectionResponse, ToolErrorPayload]":
        """Build the bundle, find the section by id, and return GetSectionResponse.

        Returns a ToolErrorPayload if the section_id is not found in the bundle.
        """
        bundle = self._build_bundle(
            archive, entry_path, validated_path=validated_path, compact=compact
        )

        section_idx = next(
            (i for i, s in enumerate(bundle["sections"]) if s["id"] == section_id),
            None,
        )
        if section_idx is None and not bundle["sections"]:
            # The entry cannot have sections at all, so the wrong-id advice
            # below ("list the IDs with view='toc'") would only send the
            # caller on a round-trip that confirms the same thing. Say why
            # — the bundle already knows — and point at the fetch that can
            # actually serve the entry.
            content_type = bundle["content_type"]
            if not content_type.startswith(_HTML_MIME_PREFIX):
                reason = "non_html"
                message = (
                    f"Entry {entry_path!r} has no sections: it is not an HTML "
                    f"article (content_type: {content_type}). Sections exist "
                    "only for HTML entries; fetch it with `zim_get` "
                    "(`binary=True` for media)."
                )
            else:
                reason = "no_headings"
                message = (
                    f"Entry {entry_path!r} has no sections: the article "
                    "contains no headings. Read the whole body with "
                    "`zim_get(view='full')`."
                )
            return tool_error(
                operation="section_not_found",
                message=message,
                extras={
                    "reason": reason,
                    "content_type": content_type,
                    "available_section_ids": [],
                    "available_section_ids_truncated": False,
                    "available_section_ids_total": 0,
                },
            )
        if section_idx is None:
            # M25: cap the returned ID list. A long Wikipedia article
            # (United States, World War II) carries 80-150 section IDs;
            # echoing every one back in a tool_error inflates the
            # response to 4-6 KB of mostly-irrelevant slugs, which on a
            # small model can crowd out the rest of the prompt.
            _MAX_IDS = 50
            all_ids = [s["id"] for s in bundle["sections"]]
            truncated_ids = all_ids[:_MAX_IDS]
            # Op5: surface the lexically-closest match so a fat-fingered
            # ID hint ("Goegraphy" → "Geography") gives the model a
            # direct retry path instead of forcing it to scan the IDs.
            # Compare case-folded: difflib is case-sensitive, and a pure case
            # variant of a short anchor id (``sh2d`` vs ``SH2d``) scores 0.5
            # — under the cutoff — so the easiest typo to repair got no
            # suggestion at all. Fold both sides, then map back to the real
            # id (first occurrence wins if two ids fold together).
            closest: Optional[str] = None
            try:
                import difflib as _difflib

                folded: Dict[str, str] = {}
                for sid in all_ids:
                    folded.setdefault(sid.casefold(), sid)
                wanted = section_id.casefold()
                if wanted in folded:
                    closest = folded[wanted]
                else:
                    candidates = _difflib.get_close_matches(
                        wanted, list(folded), n=1, cutoff=0.6
                    )
                    closest = folded[candidates[0]] if candidates else None
            except Exception:
                closest = None
            extras: Dict[str, Any] = {
                "available_section_ids": truncated_ids,
                "available_section_ids_truncated": len(all_ids) > _MAX_IDS,
                "available_section_ids_total": len(all_ids),
            }
            if closest:
                extras["closest_match"] = closest
            return tool_error(
                operation="section_not_found",
                message=(
                    f"No section with id={section_id!r} in entry {entry_path!r}. "
                    + (f"Did you mean {closest!r}? " if closest else "")
                    + "Use `zim_get(view='toc')` to list section IDs."
                ),
                extras=extras,
            )
        section = bundle["sections"][section_idx]

        # Op3: when ``include_subsections`` is False, narrow the slice
        # so it ends at the next heading (any level), not at the next
        # same-or-higher heading. Lets a caller fetch just the H2 lead
        # paragraphs without the cascading H3 sub-tree. The legacy
        # behavior (True) returns the full sub-tree.
        char_end = section["char_end"]
        narrow_widened = False
        if not include_subsections:
            sections = bundle["sections"]
            narrowed_end = char_end
            # The first section in document order strictly after the
            # requested one is the first child (or the next sibling).
            # Sweep follow-up: the boundary is the following section's
            # ``heading_start`` — ``char_start`` is its BODY start, so
            # narrowing there left the child's heading line dangling at
            # the end of the "no subsections" slice. Fall back to
            # ``char_start`` for bundles cached before the field existed.
            first_following_idx: Optional[int] = None
            for j, sib in enumerate(sections[section_idx + 1 :], start=section_idx + 1):
                if sib["char_start"] > section["char_start"]:
                    narrowed_end = min(
                        narrowed_end, sib.get("heading_start", sib["char_start"])
                    )
                    first_following_idx = j
                    break
            # D5 (v2.0.0a9): when the narrow slice has essentially no
            # body (the section heading is immediately followed by a
            # subheading), widening to include the first immediate
            # child gives the caller useful content instead of just
            # the section title. H18: previously widened to
            # ``first_child.char_end`` which included that child's
            # own descendant subtree (a grandchild's full body shipped
            # along). Widen instead to *that child's* first-following
            # heading start so the caller sees the child's lead prose
            # only — same shape as the requested narrow contract,
            # just bumped one level down.
            # The measured slice starts at ``char_start``, the section's
            # BODY offset (``heading_start`` is the heading line), so the
            # budget covers stray whitespace only and must not scale with
            # the title's length — otherwise a long-titled section
            # swallows a genuine lead paragraph. Only widen when the
            # following section really is a child, too: a near-empty
            # section followed by a same-level (or higher) sibling must
            # keep its own narrow slice rather than return the sibling's
            # heading and lead prose.
            if (
                narrowed_end - section["char_start"] <= 20
                and first_following_idx is not None
                and sections[first_following_idx]["level"] > section["level"]
            ):
                first_child = sections[first_following_idx]
                # Find the next section after this child (sibling or
                # ancestor-sibling); use its char_start as the widened
                # boundary so the slice covers child-lead-only.
                widened_end = first_child["char_end"]
                for sib in sections[first_following_idx + 1 :]:
                    if sib["char_start"] > first_child["char_start"]:
                        widened_end = min(
                            widened_end, sib.get("heading_start", sib["char_start"])
                        )
                        break
                char_end = widened_end
                narrow_widened = True
            else:
                char_end = narrowed_end
        full_body = bundle["rendered_markdown"][section["char_start"] : char_end]
        # ``compact=True`` promises the ``zim_get(compact=True)`` slice shape.
        # The bundle's compact rendering carries the table placeholders but
        # not the link strip — ``zim_get`` applies that in the content layer
        # after rendering — so on link-heavy archives a compact section
        # shipped ~65% more characters than the same prose fetched as an
        # article, and was never a substring of it. Strip here, BEFORE
        # measuring, so ``char_count`` / ``total_chars`` / ``truncated``
        # describe the text actually served (the same rule zim_get follows).
        # The bundle itself is left untouched: its offsets index the
        # unstripped markdown that TOC/structure/summary slice.
        if compact:
            full_body = _strip_markdown_links_shared(full_body)
        cap = (
            max_chars
            if max_chars is not None
            else self.config.content.max_content_length
        )
        full_len = len(full_body)
        truncated = full_len > cap
        body = full_body[:cap] if truncated else full_body

        payload: "GetSectionResponse" = cast(
            "GetSectionResponse",
            {
                "entry_path": bundle["entry_path"],
                "title": bundle["title"],
                "section_id": section["id"],
                "section_title": section["title"],
                "level": section["level"],
                "parent_id": section.get("parent_id"),
                "content_markdown": body,
                "char_count": len(body),
                "word_count": len(body.split()),
                "truncated": truncated,
            },
        )
        # D5: signal when the narrow slice was widened so the caller
        # can interpret the response correctly ("the section has no
        # lead prose; we returned the first subsection instead").
        if narrow_widened:
            payload = cast(
                "GetSectionResponse",
                {**payload, "narrow_widened_to_first_child": True},
            )
        # When truncation happens, surface ``total_chars`` so the caller
        # can tell how much of the section was elided. ``more_at_offset``
        # is intentionally omitted — get_section truncation is not
        # resumable; callers needing the full body fall back to
        # ``get_zim_entry`` with ``content_offset``.
        return cast(
            "GetSectionResponse",
            attach_meta(
                cast(Dict[str, Any], payload),
                truncated=truncated,
                total_chars=full_len if truncated else None,
            ),
        )

    @staticmethod
    def _is_non_article_target(path: str, content_type: Optional[str] = None) -> bool:
        """Report whether ``path`` is a binary asset, not a navigable article.

        ZIMIT / warc2zim wraps an article's lead image in an
        ``<a href="…/plato.jpg">`` anchor, so the image leaks into the
        internal-link graph. Pre-fix, ``articles related to Plato`` on the IEP
        archive surfaced ``iep.utm.edu/wp-content/media/plato.jpg`` as the
        rank-1 "related article". Asset targets (images, fonts, styles,
        scripts, media, archives) are never navigable articles and must be
        excluded from the related-article set.

        ``.htm`` / ``.html`` are intentionally NOT treated as assets —
        MedlinePlus article paths legitimately end in ``.html`` / ``.htm``.

        When ``content_type`` is supplied (browse/walk pass the per-row
        libzim mimetype) a known asset mimetype (``text/css``,
        ``application/javascript``, ``font/*``, ``image/*``, ``video/*``,
        ``audio/*`` …) marks the row as an asset even when the path has no
        asset extension — catching query-string / extensionless asset URLs
        like ``fonts.googleapis.com/css2?family=...`` and ``...?css=...``.
        ``content_type`` defaults to ``None`` so the related-article / link
        callers (which have no mimetype) keep the extension-only behaviour.
        """
        extensions = (
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".svg",
            ".webp",
            ".bmp",
            ".ico",
            ".tif",
            ".tiff",
            ".eot",
            ".otf",
            ".ttf",
            ".woff",
            ".woff2",
            ".css",
            ".js",
            ".mjs",
            ".json",
            ".pdf",
            ".zip",
            ".gz",
            ".mp4",
            ".webm",
            ".mp3",
            ".ogg",
            ".wav",
            ".avi",
            ".mov",
            ".m4a",
        )
        if content_type:
            ct = content_type.split(";", 1)[0].strip().lower()
            if ct in _ASSET_MIME_EXACT or ct.startswith(_ASSET_MIME_PREFIXES):
                return True
        base = path.split("?", 1)[0].split("#", 1)[0].lower()
        return base.endswith(extensions)

    def get_related_articles_data(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 10,
    ) -> "RelatedArticlesResponse":
        """Structured variant of ``get_related_articles``.

        Returns the result dict directly (not a JSON string) so MCP tools
        can hand it straight to the SDK's structured-content path.

        v2 Phase B contract: the response carries ``results`` /
        ``next_cursor`` / ``total`` / ``done`` / ``page_info`` plus the
        tool-specific ``entry_path``. This tool is non-paginated, so
        ``next_cursor`` is always ``None`` and ``done`` is always ``True``.
        The contract is applied for uniformity and anticipates Phase E's
        inbound-link feature where ``direction`` becomes a parameter and
        ``results`` covers either side.

        Each outbound result carries:

        - ``path``: the resolved ZIM entry path of the link target.
        - ``title``: the linked entry's actual archive title (resolved by
          looking up ``path`` in the archive). Falls back to ``path`` when
          the entry is missing or the lookup fails.
        - ``link_text``: the original anchor text from the source article.
        """
        if limit < 1 or limit > 100:
            raise OpenZimMcpValidationError(
                f"limit must be between 1 and 100 (provided: {limit})"
            )

        reject_path_traversal(entry_path)

        # Resolve the path once so both link extraction and the title
        # resolution archive open use the same canonical absolute path.
        # Without this, ``~/zims/foo.zim`` opens fine for link extraction
        # (validated inside extract_article_links_data) but silently fails
        # in _resolve_outbound_titles, which would otherwise call
        # ``Path("~/zims/foo.zim")`` directly — Path does not expand ``~``.
        validated_path = self._validate_zim_path(zim_file_path)
        validated_str = str(validated_path)

        outbound: List[Dict[str, Any]] = []
        outbound_error: Optional[str] = None
        links_scan_truncated = False
        links_total_internal: Optional[int] = None

        try:
            # Use the dict-returning extract_article_links_data so we don't
            # round-trip through json.dumps + json.loads just to walk the
            # outbound link graph. v2 Phase B: ask for the internal bucket
            # explicitly; ``results`` carries the internal links.
            links_data = self.extract_article_links_data(
                validated_str,
                entry_path,
                limit=500,
                kind="internal",
            )
            # Hub articles (``List of …``, ``Index of …``) routinely carry
            # 1000–5000 internal links. The 500-link cap above evaluates
            # frequency rank on a truncated sample, so the surfaced
            # "most-related" set is biased toward the document-order head.
            # Surface that fact so callers can decide whether the rank is
            # trustworthy for their use case.
            category_totals = links_data.get("category_totals") or {}
            links_total_internal = (
                category_totals.get("internal")
                if isinstance(category_totals, dict)
                else None
            )
            links_scan_truncated = not bool(links_data.get("done", True))
            # extract_article_links_data resolves redirects internally and
            # stores the post-redirect entry path in ``links_data["path"]``.
            # Resolve relative links against THAT path, not the caller-supplied
            # entry_path: if entry_path was a redirect to a different
            # directory (or namespace), resolving against the source's
            # dirname produces non-existent paths.
            resolved_source = links_data.get("path") or entry_path
            # D9 (v2.0.0a9): rank by link frequency rather than first-N
            # in document order. A target referenced N times in the
            # article is N-stronger as a "related article" signal
            # than one mentioned once — a cheap, robust proxy for
            # semantic relatedness that doesn't require categories or
            # rebuilding an embedding index. First-link-text wins for
            # the surfaced ``link_text`` field; ``mention_count`` is
            # added to the response so the caller can see the
            # ranking signal.
            from collections import Counter

            target_counts: Counter[str] = Counter()
            first_text: Dict[str, str] = {}
            for link in links_data.get("results", []):
                target = self._resolve_link_to_entry_path(
                    link.get("url", ""), resolved_source
                )
                if not target or target in (entry_path, resolved_source):
                    continue
                if self._is_non_article_target(target):
                    # ZIMIT/warc2zim wraps the lead image in
                    # ``<a href="…/plato.jpg">`` so the image leaks into the
                    # internal-link graph; asset targets are not navigable
                    # articles and must not rank as "related".
                    continue
                target_counts[target] += 1
                if target not in first_text:
                    first_text[target] = link.get("text") or link.get("title") or ""
            # Rank: frequency descending, ties broken by first-appearance
            # order (Counter.most_common preserves insertion order for
            # equal counts).
            ranked: List[Dict[str, Any]] = [
                {
                    "path": target,
                    # Placeholder; resolved via archive lookup below
                    # under a single archive open so we don't pay one
                    # open per result.
                    "title": target,
                    "link_text": first_text.get(target, ""),
                    "mention_count": count,
                }
                for target, count in target_counts.most_common()
            ]
            # Resolve BEFORE slicing to ``limit``: title resolution also
            # canonicalizes redirect spellings, so two hrefs that redirect
            # to one entry must merge into one row (summed mention_count)
            # rather than ship as two rows whose paths disagree with what
            # ``direction="inbound"`` indexes. Slicing first would also
            # leave the page short whenever a merge happened inside it.
            self._resolve_outbound_titles(validated_str, ranked)
            merged: Dict[str, Dict[str, Any]] = {}
            for row in ranked:
                canonical = row["path"]
                if canonical in (entry_path, resolved_source):
                    # A redirect spelling of the source article itself.
                    continue
                if canonical in merged:
                    merged[canonical]["mention_count"] += row["mention_count"]
                else:
                    merged[canonical] = row
            # ``sorted`` is stable, so equal counts keep their first-
            # appearance order from ``most_common``.
            outbound = sorted(merged.values(), key=lambda r: -r["mention_count"])[
                :limit
            ]
        except OpenZimMcpArchiveError as e:
            # Partial-success contract: an archive- or extraction-level
            # failure surfaces as an empty result with an error string,
            # not a hard tool error. Programming errors (TypeError,
            # AttributeError, etc.) are intentionally NOT caught here
            # so they propagate up to the tool layer and become real
            # tool_error envelopes instead of fake successes.
            logger.debug(f"get_related_articles outbound failed: {e}")
            outbound_error = str(e)

        payload: Dict[str, Any] = {
            "entry_path": entry_path,
            "results": outbound,
            "next_cursor": None,
            "total": len(outbound),
            "done": True,
            "page_info": {
                "offset": 0,
                "limit": limit,
                "returned_count": len(outbound),
            },
        }
        if outbound_error is not None:
            payload["outbound_error"] = outbound_error
        # Frequency rank was computed over only the first 500 internal links.
        # Hub/index articles can have many more; the surfaced ranking is then
        # biased toward the document-head links. Flag this so callers don't
        # treat the rank as authoritative for those articles.
        if links_scan_truncated:
            payload["scan_truncated"] = True
            if links_total_internal is not None:
                payload["scan_total_internal"] = links_total_internal
            payload["scan_limit"] = 500
        meta_reason = "scan_truncated" if links_scan_truncated else None
        return cast("RelatedArticlesResponse", attach_meta(payload, reason=meta_reason))

    def get_inbound_links_data(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 10,
        offset: int = 0,
        *,
        cursor_archive_identity: Optional[str] = None,
    ) -> "RelatedArticlesResponse":
        """Return the inbound linkers for ``entry_path`` from the sidecar.

        Ranked by each linker's own inbound-degree. Raises
        ``LinkGraphUnavailable`` when the sidecar is absent or stale (the
        tool layer renders that as a structured error). Phase-B five-key
        contract; paginated.

        ``entry_path`` is first resolved against the live archive: a path
        neither the archive nor the index has heard of raises the same
        not-found error the outbound direction raises, instead of a silent
        ``total=0`` indistinguishable from "genuinely no inbound links". A
        target the archive cannot serve but the index does carry — a red
        link the builder kept on purpose — still reports its linkers, since
        that is exactly what "what links here?" is asking. A redirect
        spelling is canonicalized through its chain because
        the sidecar builder indexes canonical targets — looked up verbatim,
        ``iep.utm.edu/plato`` returned 0 while ``iep.utm.edu/plato/`` had
        106 linkers. No namespace munging is applied: the sidecar stores
        scheme-native paths and the caller passes the archive-native path
        the search/get tools already use. The caller's spelling is echoed
        as ``entry_path`` (cursor ``ep`` matching relies on it); the
        canonical one is reported as ``resolved_path`` when it differs.
        """
        if limit < 1 or limit > 100:
            raise OpenZimMcpValidationError(
                f"limit must be between 1 and 100 (provided: {limit})"
            )
        if offset < 0:
            raise OpenZimMcpValidationError(
                f"offset must be non-negative (provided: {offset})"
            )
        reject_path_traversal(entry_path)
        validated_path = self._validate_zim_path(zim_file_path)
        validated_str = str(validated_path)

        from openzim_mcp.linkgraph.reader import (
            LinkGraphReader,
            LinkGraphUnavailable,
        )
        from openzim_mcp.pagination import archive_identity

        # Cursor integrity: an inbound cursor issued for archive A must not
        # resume against archive B (same guard every other paginated surface
        # applies — see extract_article_links_data above).
        if cursor_archive_identity is not None:
            from openzim_mcp.pagination import Cursor as _CursorClass
            from openzim_mcp.pagination import CursorMismatchError

            try:
                _CursorClass.verify_archive_identity(
                    cast("Any", {"ai": cursor_archive_identity}),
                    expected=archive_identity(validated_path),
                    tool="get_inbound_links",
                )
            except CursorMismatchError as e:
                raise OpenZimMcpCursorMismatchError(str(e)) from e

        with _zim_ops_mod.zim_archive(Path(validated_str)) as archive:
            live_uuid = str(archive.uuid)
            entry, _spelling = _resolve_entry_spelling(archive, entry_path)
            in_archive = entry is not None
            # Class-qualified: the helper is static, and the unit tests drive
            # this method through a stub ``self`` exposing only the seams it
            # already needed.
            lookup_path = _StructureMixin._canonical_target_path(archive, entry_path)
        reader = LinkGraphReader.open_for(validated_str, live_archive_uuid=live_uuid)
        if reader is None:
            raise LinkGraphUnavailable(
                "Inbound links require a link-graph sidecar for this archive. "
                f"Run `openzim-mcp build link-graph {validated_str}`. "
                "If a sidecar file is already present it is stale — built for "
                "a different archive revision or an older schema, which 3.0.0 "
                "makes true of every sidecar built before it — and the build "
                "refuses to overwrite without `--force`."
            )
        try:
            page = reader.query_inbound(lookup_path, limit=limit, offset=offset)
        finally:
            reader.close()

        # Not-found is decided AFTER the query, on both sources: the builder
        # deliberately keeps edges whose target the archive cannot verify
        # (red links and broken cross-references — see
        # ``_parse_internal_link_edges``), so "absent from the archive" alone
        # is not "unknown path". Only a target neither the archive nor the
        # index has heard of is a miss; a dangling one still has real linkers
        # to report, which is the whole question "what links here?" asks.
        if not in_archive and page.total == 0:
            raise _entry_not_found_error(entry_path)

        results: List[Dict[str, Any]] = [
            {
                "path": r["path"],
                "title": r["path"],
                "inbound_degree": r["inbound_degree"],
                "anchor_text": r["anchor_text"],
            }
            for r in page.rows
        ]
        self._resolve_outbound_titles(validated_str, results)

        returned = len(results)
        has_more = offset + returned < page.total
        next_cursor = None
        if has_more:
            next_cursor = Cursor.encode(
                tool="get_inbound_links",
                state={
                    "o": offset + returned,
                    "l": limit,
                    "ep": entry_path,
                    "ai": archive_identity(validated_path),
                },
            )
        payload: Dict[str, Any] = {
            "entry_path": entry_path,
            "results": results,
            "next_cursor": next_cursor,
            "total": page.total,
            "done": not has_more,
            "page_info": {
                "offset": offset,
                "limit": limit,
                "returned_count": returned,
            },
        }
        if lookup_path != entry_path:
            payload["resolved_path"] = lookup_path
        return cast("RelatedArticlesResponse", attach_meta(payload, reason=None))

    @staticmethod
    def _resolve_outbound_titles(
        zim_file_path: str, outbound: List[Dict[str, Any]]
    ) -> None:
        """Fill in each outbound entry's ``title`` from its archive title.

        Single archive open shared across all entries. On any per-entry
        lookup failure the title stays at its placeholder (path) so callers
        always see a non-empty string. A failure to open the archive at all
        is also non-fatal — leave placeholders in place.

        Redirect entries are followed to their canonical target (the same
        best-effort walk the sidecar builder uses), and ``item["path"]`` is
        rewritten to the canonical path. zimit archives give a redirect
        stub its own path string as its title, so reading the stub's title
        "succeeded" with junk — every related row on the IEP read
        ``title == path`` — and the pre-redirect path it shipped yielded
        zero rows when fed back to ``direction="inbound"``, which indexes
        canonical paths.
        """
        if not outbound:
            return
        try:
            with _zim_ops_mod.zim_archive(Path(zim_file_path)) as archive:
                for item in outbound:
                    try:
                        _resolve_outbound_item(archive, item)
                    except Exception as e:
                        logger.debug(f"title lookup for {item['path']} failed: {e}")
        except Exception as e:
            logger.debug(f"archive open for title resolution failed: {e}")

    def get_related_articles(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 10,
    ) -> str:
        """Legacy JSON-string variant of ``get_related_articles_data``.

        Find articles related to entry_path via outbound links.
        """
        return _json(self.get_related_articles_data(zim_file_path, entry_path, limit))

    @staticmethod
    def _canonical_target_path(archive: Any, target: str) -> str:
        """Best-effort canonical spelling of a resolved link ``target``.

        Tries the raw and percent-decoded spellings (``_resolve_entry_spelling``)
        and then names the entry libzim actually served — its own ``path``,
        after walking any redirect chain. Reporting the spelling that *resolved*
        is not enough: libzim matches a namespace prefix leniently, so
        ``C/main.html`` and ``A/main.html`` both serve the entry stored as
        ``main.html`` and only the stored path is the key
        ``_parse_internal_link_edges`` indexed. Returns ``target`` unchanged
        when nothing in the archive can verify it, so the caller keeps a
        best-effort path rather than dropping the row. Same walk
        ``_parse_internal_link_edges`` uses for the sidecar, so outbound rows,
        related rows, and the inbound index all name one entry the same way.
        """
        from openzim_mcp.zim.redirects import best_effort_redirect_chain

        try:
            entry, spelling = _resolve_entry_spelling(archive, target)
            if entry is None:
                return spelling
            resolved_path = getattr(best_effort_redirect_chain(entry), "path", None)
            # ``isinstance``: test-suite mock archives hand back MagicMock
            # entries whose ``path`` is itself a truthy MagicMock.
            if isinstance(resolved_path, str) and resolved_path:
                return resolved_path
            return spelling
        except Exception as e:  # pragma: no cover - defensive
            logger.debug(f"canonical path for {target} failed: {e}")
            return target

    def _with_resolved_path(
        self, archive: Any, link: Any, source_entry_path: str
    ) -> Any:
        """Return a copy of an outbound internal ``link`` row with ``path`` set.

        ``path`` is the href resolved against the served entry's directory
        and canonicalized through the archive; rows whose href cannot be
        resolved (query-only, self-referential) are returned unchanged.
        """
        if not isinstance(link, dict):
            return link
        target = self._resolve_link_to_entry_path(
            str(link.get("url", "")), source_entry_path
        )
        if not target:
            return link
        return {**link, "path": self._canonical_target_path(archive, target)}

    @staticmethod
    def _resolve_link_to_entry_path(url: str, source_entry_path: str) -> Optional[str]:
        """Resolve an extracted href to an absolute ZIM entry path.

        Skips anchors, external links, and unsupported schemes. Relative
        paths are resolved against ``source_entry_path``'s directory using
        posixpath semantics, then the leading "./" is stripped.

        Returns ``None`` for non-resolvable inputs (anchors, externals,
        empty, query-only).
        """
        from posixpath import dirname, normpath

        if not url:
            return None
        url = url.strip()
        if not url or url.startswith("#"):
            return None
        # External / non-navigable schemes — extract_article_links already
        # filters most, but be defensive in case callers pass raw HTML refs.
        if "://" in url or url.startswith("//"):
            return None
        # Strip query string and fragment; ZIM entries don't carry them.
        for sep in ("#", "?"):
            if sep in url:
                url = url.split(sep, 1)[0]
        if not url:
            return None
        # Self-referential / non-navigable inputs. ``.`` and ``./`` mean
        # "stay here" — returning the source's directory or namespace
        # prefix produces non-fetchable paths like ``C/`` for legacy
        # archives. ``/`` is an absolute web path with no ZIM analogue.
        # ``..``/``../`` are intentionally NOT in this list: they go to
        # the parent, which on domain-scheme archives is often a real
        # entry (e.g. the archive index).
        if url in (".", "./", "/"):
            return None
        # Domain-scheme ZIMs store directory entries with a trailing slash
        # (e.g. ``iep.utm.edu/a/``). normpath strips trailing slashes, so
        # remember the URL's slash-ness and restore it after normalization.
        had_trailing_slash = url.endswith("/")
        if url.startswith("/"):
            # Root-absolute href: posix semantics say it ignores the base.
            # Joining it onto the source's directory produced non-existent
            # targets like ``C/foo/A/Berlin`` for ``/A/Berlin``.
            joined = url
        else:
            base_dir = dirname(source_entry_path)
            joined = f"{base_dir}/{url}" if base_dir else url
        # normpath collapses "..", "./", and double slashes.
        resolved = normpath(joined).lstrip("/")
        # Drop any leading "./" or empty segments.
        if resolved in (".", ""):
            return None
        if had_trailing_slash and not resolved.endswith("/"):
            resolved += "/"
        return resolved

    @staticmethod
    def _parse_internal_link_edges(
        html: str,
        *,
        source_path: str,
        archive: "Optional[Archive]",
    ) -> List[Tuple[str, str]]:
        """Return one source entry's deduped, canonical INTERNAL ``(target, anchor_text)`` edges.

        Parses ``html`` with the same anchor classifier the bundle uses
        (``ContentProcessor._classify_anchor``), so "internal" here means
        exactly what ``extract_article_links``'s internal bucket means:
        every ``<a href>`` whose scheme is not external (``http(s)://``,
        protocol-relative ``//``) and not a non-navigable scheme
        (``javascript:``/``mailto:``/etc.). Media-element sources
        (``<img src>`` and friends) are NOT anchors and never appear.

        Each surviving internal href is then canonicalized to a fetchable
        ZIM entry path the way ``get_related_articles_data`` does:

        * ``_resolve_link_to_entry_path`` resolves the href against
          ``source_path``'s directory (posixpath semantics) and drops bare
          fragments, query-only, and non-resolvable inputs;
        * targets equal to ``source_path`` are dropped (no self-edges);
        * asset targets (``.png``/``.css``/``.mp4``/… via
          ``_is_non_article_target``) are dropped — ZIMIT wraps lead images
          in anchors, so they leak into the internal bucket otherwise.

        When ``archive`` is provided, each resolved target is additionally
        followed through its redirect chain (best-effort via
        ``best_effort_redirect_chain``) so the returned path is the
        canonical (non-redirect) entry actually served — this is what the
        offline builder needs to invert into a stable reverse-edge graph.
        When ``archive`` is ``None`` the redirect step is skipped and the
        path-normalized target is returned as-is, which keeps the helper
        unit-testable without a ZIM.

        Results preserve first-appearance order and are deduplicated.
        """
        from bs4 import BeautifulSoup, Tag

        from openzim_mcp.content_processor import (
            HTML_PARSER,
            _classify_anchor,
        )
        from openzim_mcp.zim.redirects import best_effort_redirect_chain

        try:
            soup = BeautifulSoup(html, HTML_PARSER)
        except Exception as e:  # pragma: no cover - defensive parse guard
            logger.warning(f"Internal-link parse failed for {source_path}: {e}")
            return []

        # Reuse the exact anchor classifier the bundle path uses so the
        # set of "internal" anchors here matches the extract_article_links
        # internal bucket. We only consume the ``internal_links`` list.
        links_data: Dict[str, Any] = {
            "internal_links": [],
            "external_links": [],
            "media_links": [],
        }
        for link in soup.find_all("a", href=True):
            if not isinstance(link, Tag):
                continue
            _classify_anchor(link, links_data)

        seen: set = set()
        edges: List[Tuple[str, str]] = []
        for link in links_data["internal_links"]:
            target = _StructureMixin._resolve_link_to_entry_path(
                link.get("url", ""), source_path
            )
            if not target or target == source_path:
                continue
            if _StructureMixin._is_non_article_target(target):
                continue
            anchor = (link.get("text") or "").strip()
            if archive is not None:
                # Canonicalize through the redirect chain so the builder
                # inverts edges against the served (non-redirect) path.
                # Best-effort: a missing entry or malformed chain falls
                # back to the path-normalized target rather than dropping
                # an otherwise-valid edge.
                try:
                    # Percent-decode fallback first: the href these targets
                    # come from is RFC 3986-encoded, so a non-ASCII article
                    # arrives as ``A/El_Ni%C3%B1o`` and this lookup would miss
                    # it entirely — indexing the edge under a key nothing can
                    # fetch.
                    entry, target = _resolve_entry_spelling(archive, target)
                    if entry is not None:
                        resolved = best_effort_redirect_chain(entry)
                        resolved_path = getattr(resolved, "path", None)
                        if resolved_path:
                            target = resolved_path
                except Exception as e:
                    logger.debug(f"redirect canonicalization for {target} failed: {e}")
            if target in seen or target == source_path:
                continue
            seen.add(target)
            edges.append((target, anchor))
        return edges
