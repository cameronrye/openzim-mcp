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
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union, cast

from libzim.reader import Archive  # type: ignore[import-untyped]

import openzim_mcp.zim_operations as _zim_ops_mod
from openzim_mcp.exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpFileNotFoundError,
    OpenZimMcpValidationError,
)
from openzim_mcp.meta import attach_meta
from openzim_mcp.pagination import Cursor
from openzim_mcp.responses import ToolErrorPayload, tool_error
from openzim_mcp.zim._ops_base import _json
from openzim_mcp.zim.content import reject_path_traversal

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

    def get_article_structure_data(
        self, zim_file_path: str, entry_path: str
    ) -> "ArticleStructureResponse":
        """Structured variant of ``get_article_structure``.

        Returns the result dict directly (not a JSON string) so MCP tools
        can hand it straight to FastMCP's structured-content path.

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
        from openzim_mcp.bundle import get_or_build_bundle

        if validated_path is None:
            # Falling back to Path(entry_path) makes the bundle cache key
            # archive-agnostic — the same key collides across every ZIM
            # whose archive holds this entry path. Require the caller to
            # pass the resolved archive path so bundles stay archive-bound.
            raise OpenZimMcpValidationError(
                "_extract_article_structure_data requires validated_path"
            )

        try:
            bundle = get_or_build_bundle(
                archive,
                entry_path,
                cache=self.cache,
                validated_path=validated_path,
                content_processor=self.content_processor,
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
                    "content_preview": md[
                        s["char_start"] : s["char_start"] + PREVIEW_CHARS
                    ],
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
        can hand it straight to FastMCP's structured-content path.

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
        # Caller-input validation surfaces as OpenZimMcpValidationError so the
        # tool layer can render a targeted validation message (separate from
        # archive-access errors).
        if limit < 1 or limit > 500:
            raise OpenZimMcpValidationError(
                f"limit must be between 1 and 500 (provided: {limit})"
            )
        if offset < 0:
            raise OpenZimMcpValidationError(
                f"offset must be non-negative (provided: {offset})"
            )
        if kind not in {"internal", "external", "media"}:
            raise OpenZimMcpValidationError(
                f"kind must be one of 'internal', 'external', 'media' "
                f"(provided: {kind!r})"
            )

        reject_path_traversal(entry_path)

        # Validate and resolve file path
        validated_path = self._validate_zim_path(zim_file_path)

        # Cursor integrity (Phase B #11): a cursor issued for archive A
        # must not be honoured when resubmitted against archive B.
        if cursor_archive_identity is not None:
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
                raise OpenZimMcpValidationError(str(e)) from e

        try:
            from openzim_mcp.bundle import get_or_build_bundle

            with _zim_ops_mod.zim_archive(validated_path) as archive:
                bundle = get_or_build_bundle(
                    archive,
                    entry_path,
                    cache=self.cache,
                    validated_path=validated_path,
                    content_processor=self.content_processor,
                )

            all_links_for_kind: List[Any] = cast(
                "List[Any]", bundle["links"][kind]  # type: ignore[literal-required]
            )
            total_for_kind = len(all_links_for_kind)
            page = all_links_for_kind[offset : offset + limit]
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
                    "internal": len(bundle["links"]["internal"]),
                    "external": len(bundle["links"]["external"]),
                    "media": len(bundle["links"]["media"]),
                },
            }

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
        can hand it straight to FastMCP's structured-content path.

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
        from openzim_mcp.bundle import get_or_build_bundle

        if validated_path is None:
            # Same archive-binding requirement as
            # _extract_article_structure_data — without a real archive
            # path the bundle cache collides cross-archive.
            raise OpenZimMcpValidationError(
                "_extract_table_of_contents_data requires validated_path"
            )

        try:
            bundle = get_or_build_bundle(
                archive,
                entry_path,
                cache=self.cache,
                validated_path=validated_path,
                content_processor=self.content_processor,
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
            if not bundle["content_type"].startswith("text/html"):
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
    ) -> "Union[GetSectionResponse, ToolErrorPayload]":
        """Build the bundle, find the section by id, and return GetSectionResponse.

        Returns a ToolErrorPayload if the section_id is not found in the bundle.
        """
        from openzim_mcp.bundle import get_or_build_bundle

        bundle = get_or_build_bundle(
            archive,
            entry_path,
            cache=self.cache,
            validated_path=validated_path,
            content_processor=self.content_processor,
        )

        section_idx = next(
            (i for i, s in enumerate(bundle["sections"]) if s["id"] == section_id),
            None,
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
            closest: Optional[str] = None
            try:
                import difflib as _difflib

                candidates = _difflib.get_close_matches(
                    section_id, all_ids, n=1, cutoff=0.6
                )
                closest = candidates[0] if candidates else None
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
                    + "Use get_table_of_contents to list section IDs."
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
            first_following_idx: Optional[int] = None
            for j, sib in enumerate(sections[section_idx + 1 :], start=section_idx + 1):
                if sib["char_start"] > section["char_start"]:
                    narrowed_end = min(narrowed_end, sib["char_start"])
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
            heading_len = (
                len(section.get("title", "")) + len("#" * section["level"]) + 4
            )
            if (
                narrowed_end - section["char_start"] <= heading_len + 20
                and first_following_idx is not None
            ):
                first_child = sections[first_following_idx]
                # Find the next section after this child (sibling or
                # ancestor-sibling); use its char_start as the widened
                # boundary so the slice covers child-lead-only.
                widened_end = first_child["char_end"]
                for sib in sections[first_following_idx + 1 :]:
                    if sib["char_start"] > first_child["char_start"]:
                        widened_end = min(widened_end, sib["char_start"])
                        break
                char_end = widened_end
                narrow_widened = True
            else:
                char_end = narrowed_end
        full_body = bundle["rendered_markdown"][section["char_start"] : char_end]
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
    def _is_non_article_target(path: str) -> bool:
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
        can hand it straight to FastMCP's structured-content path.

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
            for target, count in target_counts.most_common(limit):
                outbound.append(
                    {
                        "path": target,
                        # Placeholder; resolved via archive lookup below
                        # under a single archive open so we don't pay one
                        # open per result.
                        "title": target,
                        "link_text": first_text.get(target, ""),
                        "mention_count": count,
                    }
                )
            self._resolve_outbound_titles(validated_str, outbound)
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

        ``entry_path`` is looked up in the sidecar exactly as passed — the
        sidecar stores scheme-native paths (prefix-less on new-scheme
        archives, ``C/``-prefixed on old-scheme), and the runtime caller
        passes the archive-native path the search/get tools already use, so
        no namespace munging is applied here.
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

        with _zim_ops_mod.zim_archive(Path(validated_str)) as archive:
            live_uuid = str(archive.uuid)
        reader = LinkGraphReader.open_for(validated_str, live_archive_uuid=live_uuid)
        if reader is None:
            raise LinkGraphUnavailable(
                "Inbound links require a link-graph sidecar for this archive. "
                f"Run `openzim-mcp build link-graph {validated_str}` "
                "(rebuild it if the archive changed)."
            )
        try:
            page = reader.query_inbound(entry_path, limit=limit, offset=offset)
        finally:
            reader.close()

        results: List[Dict[str, Any]] = [
            {
                "path": r["path"],
                "title": r["path"],
                "inbound_degree": r["inbound_degree"],
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
        return cast("RelatedArticlesResponse", attach_meta(payload, reason=None))

    @staticmethod
    def _resolve_outbound_titles(
        zim_file_path: str, outbound: List[Dict[str, Any]]
    ) -> None:
        """Fill in each outbound entry's ``title`` from its archive title.

        Single archive open shared across all entries (limit ≤ 100). On any
        per-entry lookup failure the title stays at its placeholder (path)
        so callers always see a non-empty string. A failure to open the
        archive at all is also non-fatal — leave placeholders in place.
        """
        if not outbound:
            return
        try:
            with _zim_ops_mod.zim_archive(Path(zim_file_path)) as archive:
                for item in outbound:
                    try:
                        entry = archive.get_entry_by_path(item["path"])
                        title = getattr(entry, "title", None)
                        if title:
                            item["title"] = title
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
        base_dir = dirname(source_entry_path)
        if base_dir:
            joined = f"{base_dir}/{url}"
        else:
            joined = url
        # normpath collapses "..", "./", and double slashes.
        resolved = normpath(joined).lstrip("/")
        # Drop any leading "./" or empty segments.
        if resolved in (".", ""):
            return None
        if had_trailing_slash and not resolved.endswith("/"):
            resolved += "/"
        return resolved

    @staticmethod
    def _parse_internal_link_targets(
        html: str,
        *,
        source_path: str,
        archive: "Optional[Archive]",
    ) -> List[str]:
        """Return one source entry's deduped, canonical INTERNAL link targets.

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
        targets: List[str] = []
        for link in links_data["internal_links"]:
            target = _StructureMixin._resolve_link_to_entry_path(
                link.get("url", ""), source_path
            )
            if not target or target == source_path:
                continue
            if _StructureMixin._is_non_article_target(target):
                continue
            if archive is not None:
                # Canonicalize through the redirect chain so the builder
                # inverts edges against the served (non-redirect) path.
                # Best-effort: a missing entry or malformed chain falls
                # back to the path-normalized target rather than dropping
                # an otherwise-valid edge.
                try:
                    entry = archive.get_entry_by_path(target)
                    resolved = best_effort_redirect_chain(entry)
                    resolved_path = getattr(resolved, "path", None)
                    if resolved_path:
                        target = resolved_path
                except Exception as e:
                    logger.debug(f"redirect canonicalization for {target} failed: {e}")
            if target in seen or target == source_path:
                continue
            seen.add(target)
            targets.append(target)
        return targets
