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
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from libzim.reader import Archive  # type: ignore[import-untyped]

import openzim_mcp.zim_operations as _zim_ops_mod
from openzim_mcp.exceptions import OpenZimMcpArchiveError, OpenZimMcpValidationError

if TYPE_CHECKING:
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator

logger = logging.getLogger(__name__)

# MIME type that drives the HTML-aware structure/links code paths.
TEXT_HTML_MIME = "text/html"


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
    ) -> Dict[str, Any]:
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

        # Cache key distinct from the legacy string cache so old persisted
        # entries (which hold strings) don't collide with the new dict shape.
        cache_key = f"structure_data:{validated_path}:{entry_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached structure dict for: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result = self._extract_article_structure_data(archive, entry_path)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(f"Extracted structure for: {entry_path}")
            return result

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
        self, archive: Archive, entry_path: str
    ) -> Dict[str, Any]:
        """Extract structure from article content as a dict."""
        try:
            entry, entry_path = self._resolve_entry_with_fallback(archive, entry_path)
            title = entry.title or "Untitled"

            # Get raw content
            item = entry.get_item()
            mime_type = item.mimetype or ""
            raw_content = bytes(item.content).decode("utf-8", errors="replace")

            structure: Dict[str, Any] = {
                "title": title,
                "path": entry_path,
                "content_type": mime_type,
                "headings": [],
                "sections": [],
                "metadata": {},
                "word_count": 0,
                "character_count": len(raw_content),
            }

            # Process HTML content for structure
            if mime_type.startswith(TEXT_HTML_MIME):
                structure.update(
                    self.content_processor.extract_html_structure(raw_content)
                )
            elif mime_type.startswith("text/"):
                # For plain text, try to extract basic structure. Re-encode the
                # already-decoded raw_content rather than re-reading item.content,
                # which can trigger another full decompression from the archive.
                plain_text = self.content_processor.process_mime_content(
                    raw_content.encode("utf-8"), mime_type
                )
                structure["word_count"] = len(plain_text.split())
                structure["sections"] = [
                    {"title": "Content", "content_preview": plain_text[:500]}
                ]
            else:
                structure["sections"] = [
                    {
                        "title": "Non-text content",
                        "content_preview": f"({mime_type} content)",
                    }
                ]

            return structure

        except Exception as e:
            logger.error(f"Error extracting structure for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(
                f"Failed to extract article structure: {e}"
            ) from e

    def extract_article_links_data(
        self, zim_file_path: str, entry_path: str
    ) -> Dict[str, Any]:
        """Structured variant of ``extract_article_links``.

        Returns the result dict directly (not a JSON string) so MCP tools
        can hand it straight to FastMCP's structured-content path.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If link extraction fails
        """
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Cache key distinct from the legacy string cache so old persisted
        # entries (which hold strings) don't collide with the new dict shape.
        cache_key = f"links_data:{validated_path}:{entry_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached links dict for: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result = self._extract_article_links_data(archive, entry_path)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(f"Extracted links for: {entry_path}")
            return result

        except OpenZimMcpArchiveError:
            # Inner helper already raised a typed archive error with full
            # context. Don't re-wrap and double the message prefix.
            raise
        except Exception as e:
            logger.error(f"Link extraction failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Link extraction failed: {e}") from e

    def extract_article_links(self, zim_file_path: str, entry_path: str) -> str:
        """Legacy JSON-string variant of ``extract_article_links_data``.

        Extract internal and external links from an article.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'

        Returns:
            JSON string containing extracted links

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If link extraction fails
        """
        return json.dumps(
            self.extract_article_links_data(zim_file_path, entry_path),
            indent=2,
            ensure_ascii=False,
        )

    def _extract_article_links_data(
        self, archive: Archive, entry_path: str
    ) -> Dict[str, Any]:
        """Extract links from article content as a dict."""
        try:
            entry, entry_path = self._resolve_entry_with_fallback(archive, entry_path)
            title = entry.title or "Untitled"

            # Get raw content
            item = entry.get_item()
            mime_type = item.mimetype or ""
            raw_content = bytes(item.content).decode("utf-8", errors="replace")

            links_data: Dict[str, Any] = {
                "title": title,
                "path": entry_path,
                "content_type": mime_type,
                "internal_links": [],
                "external_links": [],
                "media_links": [],
                "total_links": 0,
            }

            # Process HTML content for links
            if mime_type.startswith(TEXT_HTML_MIME):
                links_data.update(
                    self.content_processor.extract_html_links(raw_content)
                )
            else:
                # For non-HTML content, we can't extract structured links
                links_data["message"] = f"Link extraction not supported for {mime_type}"

            links_data["total_links"] = (
                len(links_data.get("internal_links", []))
                + len(links_data.get("external_links", []))
                + len(links_data.get("media_links", []))
            )

            return links_data

        except Exception as e:
            logger.error(f"Error extracting links for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Failed to extract article links: {e}") from e

    def get_table_of_contents(self, zim_file_path: str, entry_path: str) -> str:
        """Extract a hierarchical table of contents from an article.

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
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"toc:{validated_path}:{entry_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached TOC for: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result = self._extract_table_of_contents(archive, entry_path)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(f"Extracted TOC for: {entry_path}")
            return result

        except OpenZimMcpArchiveError:
            # Inner helper already raised a typed archive error with full
            # context. Don't re-wrap and double the message prefix.
            raise
        except Exception as e:
            logger.error(f"TOC extraction failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"TOC extraction failed: {e}") from e

    def _extract_table_of_contents(self, archive: Archive, entry_path: str) -> str:
        """Extract hierarchical table of contents from article."""
        try:
            entry, entry_path = self._resolve_entry_with_fallback(archive, entry_path)

            title = entry.title or "Untitled"
            item = entry.get_item()
            mime_type = item.mimetype or ""

            toc_data: Dict[str, Any] = {
                "title": title,
                "path": entry_path,
                "content_type": mime_type,
                "toc": [],
                "heading_count": 0,
                "max_depth": 0,
            }

            if not mime_type.startswith(TEXT_HTML_MIME):
                toc_data["message"] = (
                    f"TOC extraction requires HTML content, got: {mime_type}"
                )
                return json.dumps(toc_data, indent=2, ensure_ascii=False)

            raw_content = bytes(item.content).decode("utf-8", errors="replace")
            toc_data.update(self._build_hierarchical_toc(raw_content))

            return json.dumps(toc_data, indent=2, ensure_ascii=False)

        except OpenZimMcpArchiveError:
            raise
        except Exception as e:
            logger.error(f"Error extracting TOC for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(
                f"Failed to extract table of contents: {e}"
            ) from e

    def _build_hierarchical_toc(self, html_content: str) -> Dict[str, Any]:
        """Build a hierarchical table of contents from HTML headings.

        Returns a tree structure where each node has:
        - level: heading level (1-6)
        - text: heading text
        - id: heading id attribute (for anchor links)
        - children: nested headings

        Errors propagate to the caller so a transient parse failure is not
        cached as a permanent ``{"error": "..."}`` blob for the full TTL.
        ``get_table_of_contents`` translates the exception into a user-facing
        ``TOC extraction failed`` error response.
        """
        from bs4 import BeautifulSoup, Tag

        result: Dict[str, Any] = {
            "toc": [],
            "heading_count": 0,
            "max_depth": 0,
        }

        soup = BeautifulSoup(html_content, "html.parser")

        # Remove unwanted elements
        for selector in ["script", "style", "nav", ".mw-editsection"]:
            for element in soup.select(selector):
                element.decompose()

        # Find all headings in order
        headings: List[Dict[str, Any]] = []
        from openzim_mcp.content_processor import resolve_heading_id

        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            if isinstance(heading, Tag):
                level = int(heading.name[1])
                text = heading.get_text().strip()
                anchor_id, id_source = resolve_heading_id(heading)

                if text:  # Skip empty headings
                    headings.append(
                        {
                            "level": level,
                            "text": text,
                            "id": anchor_id,
                            "id_source": id_source,
                            "children": [],
                        }
                    )

        if not headings:
            result["message"] = "No headings found in article"
            return result

        result["heading_count"] = len(headings)
        result["max_depth"] = max(h["level"] for h in headings)

        # Build hierarchical tree
        result["toc"] = self._headings_to_tree(headings)

        return result

    def _headings_to_tree(self, headings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert flat list of headings to hierarchical tree structure.

        Uses a stack-based approach to properly nest headings based on level.
        """
        if not headings:
            return []

        # Create root nodes list
        root: List[Dict[str, Any]] = []
        # Stack to track parent nodes at each level
        stack: List[tuple[int, List[Dict[str, Any]]]] = [(0, root)]

        for heading in headings:
            level = heading["level"]
            node = {
                "level": level,
                "text": heading["text"],
                "id": heading["id"],
                "id_source": heading.get("id_source", "none"),
                "children": [],
            }

            # Pop stack until we find a parent with lower level
            while stack and stack[-1][0] >= level:
                stack.pop()

            # Add to appropriate parent
            if stack:
                parent_list = stack[-1][1]
                parent_list.append(node)
            else:
                root.append(node)

            # Push this node's children list onto stack
            stack.append((level, node["children"]))

        return root

    def get_related_articles(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 10,
    ) -> str:
        """Find articles related to entry_path via outbound links."""
        if limit < 1 or limit > 100:
            raise OpenZimMcpValidationError(
                f"limit must be between 1 and 100 (provided: {limit})"
            )

        result: Dict[str, Any] = {"entry_path": entry_path}

        try:
            links_json = self.extract_article_links(zim_file_path, entry_path)
            links_data = json.loads(links_json)
            # extract_article_links resolves redirects internally and stores
            # the post-redirect entry path in ``links_data["path"]``. Resolve
            # relative links against THAT path, not the caller-supplied
            # entry_path: if entry_path was a redirect to a different
            # directory (or namespace), resolving against the source's
            # dirname produces non-existent paths.
            resolved_source = links_data.get("path") or entry_path
            seen: set[str] = set()
            outbound: List[Dict[str, Any]] = []
            for link in links_data.get("internal_links", []):
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
                title = link.get("text") or link.get("title") or target
                outbound.append({"path": target, "title": title})
                if len(outbound) >= limit:
                    break
            result["outbound_results"] = outbound
        except Exception as e:
            logger.debug(f"get_related_articles outbound failed: {e}")
            result["outbound_results"] = []
            result["outbound_error"] = str(e)

        return json.dumps(result, indent=2, ensure_ascii=False)

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
