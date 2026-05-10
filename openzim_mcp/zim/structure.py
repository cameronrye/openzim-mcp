"""Article-structure methods for ``ZimOperations``.

This mixin handles HTML structure extraction: headings, sections, links,
table-of-contents, and link-following for related-article discovery.
Methods run as instance methods of ``ZimOperations`` via the mixin
pattern.

``zim_archive`` is accessed through ``openzim_mcp.zim_operations`` so
existing test patches against the shim's symbols continue to work
without changes.
"""

import json
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

# MIME type that drives the HTML-aware structure/links code paths.
TEXT_HTML_MIME = "text/html"


def _sections_to_toc_tree(sections: "List[SectionMeta]") -> "List[TocHeading]":
    """Build a hierarchical TOC tree from a flat SectionMeta list.

    Uses a stack to nest headings by level. Each TocHeading has the
    Phase C field name ``section_id`` (renamed from the old ``id``).
    """
    root: "List[TocHeading]" = []
    stack: "List[Tuple[int, List[TocHeading]]]" = [(0, root)]

    for s in sections:
        node: "TocHeading" = cast(
            "TocHeading",
            {
                "section_id": s["id"],
                "text": s["title"],
                "level": s["level"],
                "children": [],
            },
        )
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
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

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
        return json.dumps(
            self.get_article_structure_data(zim_file_path, entry_path),
            indent=2,
            ensure_ascii=False,
        )

    def _extract_article_structure_data(
        self,
        archive: Archive,
        entry_path: str,
        *,
        validated_path: "Optional[Path]" = None,
    ) -> "ArticleStructureResponse":
        """Extract structure from article content via bundle."""
        from openzim_mcp.bundle import get_or_build_bundle

        try:
            bundle = get_or_build_bundle(
                archive,
                entry_path,
                cache=self.cache,
                validated_path=validated_path or Path(entry_path),
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

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

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
                next_cursor = Cursor.encode(
                    tool="extract_article_links",
                    state={
                        "o": last_index,
                        "l": limit,
                        "ep": entry_path,
                        "k": kind,
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
        return json.dumps(
            self.extract_article_links_data(
                zim_file_path,
                entry_path,
                limit=limit,
                offset=offset,
                kind=kind,
            ),
            indent=2,
            ensure_ascii=False,
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
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

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
        return json.dumps(
            self.get_table_of_contents_data(zim_file_path, entry_path),
            indent=2,
            ensure_ascii=False,
        )

    def _extract_table_of_contents_data(
        self,
        archive: Archive,
        entry_path: str,
        *,
        validated_path: "Optional[Path]" = None,
    ) -> "TableOfContentsResponse":
        """Extract hierarchical table of contents from article via bundle."""
        from openzim_mcp.bundle import get_or_build_bundle

        try:
            bundle = get_or_build_bundle(
                archive,
                entry_path,
                cache=self.cache,
                validated_path=validated_path or Path(entry_path),
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
    ) -> "Union[GetSectionResponse, ToolErrorPayload]":
        """Public entry point for the get_section tool.

        Returns the typed response or a ToolErrorPayload on
        file-not-found / entry-not-found / section-not-found.
        """
        try:
            validated_path = self.path_validator.validate_path(zim_file_path)
            validated_path = self.path_validator.validate_zim_file(validated_path)
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                return self._get_section_data(
                    archive, validated_path, entry_path, section_id, max_chars
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

        section = next(
            (s for s in bundle["sections"] if s["id"] == section_id),
            None,
        )
        if section is None:
            return tool_error(
                operation="section_not_found",
                message=(
                    f"No section with id={section_id!r} in entry {entry_path!r}. "
                    f"Use get_table_of_contents to list available section IDs."
                ),
                extras={"available_section_ids": [s["id"] for s in bundle["sections"]]},
            )

        body = bundle["rendered_markdown"][section["char_start"] : section["char_end"]]
        cap = (
            max_chars
            if max_chars is not None
            else self.config.content.max_content_length
        )
        truncated = len(body) > cap
        if truncated:
            body = body[:cap]

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
        return cast(
            "GetSectionResponse",
            attach_meta(cast(Dict[str, Any], payload), truncated=truncated),
        )

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

        # Resolve the path once so both link extraction and the title
        # resolution archive open use the same canonical absolute path.
        # Without this, ``~/zims/foo.zim`` opens fine for link extraction
        # (validated inside extract_article_links_data) but silently fails
        # in _resolve_outbound_titles, which would otherwise call
        # ``Path("~/zims/foo.zim")`` directly — Path does not expand ``~``.
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)
        validated_str = str(validated_path)

        outbound: List[Dict[str, Any]] = []
        outbound_error: Optional[str] = None

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
            # extract_article_links_data resolves redirects internally and
            # stores the post-redirect entry path in ``links_data["path"]``.
            # Resolve relative links against THAT path, not the caller-supplied
            # entry_path: if entry_path was a redirect to a different
            # directory (or namespace), resolving against the source's
            # dirname produces non-existent paths.
            resolved_source = links_data.get("path") or entry_path
            seen: set[str] = set()
            for link in links_data.get("results", []):
                target = self._resolve_link_to_entry_path(
                    link.get("url", ""), resolved_source
                )
                if (
                    not target
                    or target in seen
                    or target in (entry_path, resolved_source)
                ):
                    continue
                seen.add(target)
                outbound.append(
                    {
                        "path": target,
                        # Placeholder; resolved via archive lookup below
                        # under a single archive open so we don't pay one
                        # open per result.
                        "title": target,
                        "link_text": link.get("text") or link.get("title") or "",
                    }
                )
                if len(outbound) >= limit:
                    break
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
        return cast("RelatedArticlesResponse", attach_meta(payload))

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
        return json.dumps(
            self.get_related_articles_data(zim_file_path, entry_path, limit),
            indent=2,
            ensure_ascii=False,
        )

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
