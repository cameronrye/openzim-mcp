"""Content-retrieval methods for ``ZimOperations``.

This mixin holds the entry-content reading surface — single entry, batch
entries, binary entries, summaries, and snippets. Methods run as instance
methods of ``ZimOperations`` via the mixin pattern.

``zim_archive``, ``Searcher``, ``Query`` etc. are accessed through
``openzim_mcp.zim_operations`` so existing test patches against the
shim's symbols continue to work without changes.
"""

import base64
import json
import logging
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from libzim.reader import Archive  # type: ignore[import-untyped]

import openzim_mcp.zim_operations as _zim_ops_mod
from openzim_mcp.exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpValidationError,
)

if TYPE_CHECKING:
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator

logger = logging.getLogger(__name__)


class _ContentMixin:
    """Entry-content retrieval methods for ZimOperations.

    Attributes below are provided by the concrete ``ZimOperations`` class
    that mixes this in.
    """

    if TYPE_CHECKING:
        config: "OpenZimMcpConfig"
        path_validator: "PathValidator"
        cache: "OpenZimMcpCache"
        content_processor: "ContentProcessor"

        # Provided by other mixins / coordinator class.
        def _find_entry_by_search(
            self, archive: Archive, entry_path: str
        ) -> Optional[str]: ...

        def _resolve_entry_with_fallback(
            self, archive: Archive, entry_path: str
        ) -> Tuple[Any, str]: ...

    def _get_entry_snippet(self, entry: Any) -> str:
        """Get content snippet for search result."""
        try:
            item = entry.get_item()
            if item.mimetype.startswith("text/"):
                content = self.content_processor.process_mime_content(
                    bytes(item.content), item.mimetype
                )
                return self.content_processor.create_snippet(content)
            else:
                return f"(Unsupported content type: {item.mimetype})"
        except Exception as e:
            logger.warning(f"Error getting content snippet: {e}")
            return "(Unable to get content preview)"

    def get_zim_entry(
        self,
        zim_file_path: str,
        entry_path: str,
        max_content_length: Optional[int] = None,
        content_offset: int = 0,
    ) -> str:
        """Get detailed content of a ZIM entry with smart retrieval.

        This function implements intelligent entry retrieval that automatically handles
        path encoding inconsistencies common in ZIM files:

        1. **Direct Access**: First attempts to retrieve entry using provided path
        2. **Automatic Fallback**: If direct access fails, searches for the entry
           using various search terms derived from the path
        3. **Path Mapping Cache**: Caches successful path mappings for performance
        4. **Enhanced Error Guidance**: Provides guidance when entries not found

        This eliminates the need for manual search-first methodology and provides
        transparent operation regardless of path encoding differences.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'A/Some_Article'
            max_content_length: Maximum length of content to return
            content_offset: Character offset to start reading from (default 0).
                Combine with max_content_length to page through long articles
                without re-fetching from the beginning.

        Returns:
            Entry content text with metadata including actual path used

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If entry retrieval fails or entry cannot
                be found via direct access or search
        """
        if max_content_length is None:
            max_content_length = self.config.content.max_content_length
        if content_offset < 0:
            content_offset = 0

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Cheap response cache check: a hit avoids opening the archive
        # entirely, which is the whole point of caching here.
        cache_key = (
            f"entry:{validated_path}:{entry_path}:"
            f"{max_content_length}:{content_offset}"
        )
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached entry: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                return self._get_zim_entry_from_archive(
                    archive,
                    validated_path,
                    entry_path,
                    max_content_length,
                    content_offset,
                )
        except OpenZimMcpArchiveError:
            # Re-raise OpenZimMcpArchiveError with enhanced guidance messages
            raise
        except Exception as e:
            logger.error(f"Entry retrieval failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(
                f"Entry retrieval failed for '{entry_path}': {e}. "
                f"This may be due to file access issues or ZIM file corruption. "
                f"Try using search_zim_file() to verify the file is accessible."
            ) from e

    def _get_zim_entry_from_archive(
        self,
        archive: Archive,
        validated_path: Path,
        entry_path: str,
        max_content_length: int,
        content_offset: int = 0,
    ) -> str:
        """Retrieve and format a single entry against an already-open archive.

        Splits the open-archive concern out of ``get_zim_entry`` so batch
        callers (``get_entries``) can reuse one open archive across many
        entries from the same ZIM file.

        Honours the same response cache as ``get_zim_entry``: a cache hit
        returns the formatted text without touching the archive; misses are
        populated on success.
        """
        # Response cache: also checked here so batch callers benefit from
        # already-cached entries without re-rendering. ``get_zim_entry``
        # checks before opening the archive; this check covers the case
        # where the archive is already open (batch call) and a different
        # entry within the same ZIM file was previously cached.
        cache_key = (
            f"entry:{validated_path}:{entry_path}:"
            f"{max_content_length}:{content_offset}"
        )
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached entry: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        result, content_ok = self._get_entry_content(
            archive,
            entry_path,
            max_content_length,
            validated_path,
            content_offset,
        )

        # Only cache successful content retrieval. If process_mime_content
        # raised and we returned an error sentinel, recompute on the next
        # request rather than locking the failure in for the TTL.
        if content_ok:
            self.cache.set(cache_key, result)
        logger.info(f"Retrieved entry: {entry_path}")
        return result

    def get_entries(
        self,
        entries: List[Dict[str, str]],
        max_content_length: Optional[int] = None,
    ) -> str:
        """Fetch multiple ZIM entries in one call.

        Per-entry partial success: one failure does not abort the batch.
        Each result carries the input ``index`` so callers can correlate
        responses with their original request order.

        Args:
            entries: list of ``{"zim_file_path", "entry_path"}`` dicts.
            max_content_length: per-entry max content length.

        Returns:
            JSON string ``{"results": [...], "succeeded": N, "failed": N}``.

        Raises:
            OpenZimMcpValidationError: empty list or > MAX_BATCH_SIZE.
        """
        from openzim_mcp.constants import MAX_BATCH_SIZE

        if not entries:
            raise OpenZimMcpValidationError("entries list cannot be empty")
        if len(entries) > MAX_BATCH_SIZE:
            raise OpenZimMcpValidationError(
                f"batch size {len(entries)} exceeds limit {MAX_BATCH_SIZE}; "
                "split into multiple batches"
            )

        # Resolve the per-entry max length once — the same default applies to
        # every entry in the batch, so honour it here rather than re-resolving
        # inside _get_zim_entry_from_archive.
        if max_content_length is None:
            max_content_length = self.config.content.max_content_length

        # Group input entries by zim_file_path so we open each archive once
        # for the whole group. Preserve the original input index on every
        # entry so we can emit results in input order even after grouping.
        groups: Dict[str, List[Tuple[int, str, str]]] = {}
        for index, entry in enumerate(entries):
            zim_file_path = entry.get("zim_file_path", "")
            entry_path = entry.get("entry_path", "")
            groups.setdefault(zim_file_path, []).append(
                (index, zim_file_path, entry_path)
            )

        results: List[Dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for zim_file_path, group in groups.items():
            # Validate the path once per file. If validation itself fails,
            # every entry in this group fails with the same error rather
            # than spending an archive open per entry.
            try:
                validated_path = self.path_validator.validate_path(zim_file_path)
                validated_path = self.path_validator.validate_zim_file(validated_path)
            except Exception as e:  # noqa: BLE001 - per-group isolation
                for index, zfp, entry_path in group:
                    results.append(
                        {
                            "index": index,
                            "zim_file_path": zfp,
                            "entry_path": entry_path,
                            "success": False,
                            "error": str(e),
                        }
                    )
                    failed += 1
                continue

            # Open the archive once for the whole group via the context
            # manager. If even opening fails, mark every entry in this
            # group as failed without trying again — the failure is
            # per-file, not per-entry. The narrow try/except wraps only
            # the open so per-entry exceptions stay scoped to the inner
            # loop's handler and we don't double-count any entry.
            archive_cm = _zim_ops_mod.zim_archive(validated_path)
            try:
                archive = archive_cm.__enter__()
            except Exception as e:  # noqa: BLE001 - per-group isolation
                for index, zfp, entry_path in group:
                    results.append(
                        {
                            "index": index,
                            "zim_file_path": zfp,
                            "entry_path": entry_path,
                            "success": False,
                            "error": str(e),
                        }
                    )
                    failed += 1
                continue

            try:
                for index, zfp, entry_path in group:
                    try:
                        content = self._get_zim_entry_from_archive(
                            archive,
                            validated_path,
                            entry_path,
                            max_content_length,
                            0,
                        )
                        results.append(
                            {
                                "index": index,
                                "zim_file_path": zfp,
                                "entry_path": entry_path,
                                "success": True,
                                "content": content,
                            }
                        )
                        succeeded += 1
                    except (
                        Exception
                    ) as e:  # noqa: BLE001 - per-entry isolation by design
                        results.append(
                            {
                                "index": index,
                                "zim_file_path": zfp,
                                "entry_path": entry_path,
                                "success": False,
                                "error": str(e),
                            }
                        )
                        failed += 1
            finally:
                # Always run the context manager's __exit__ — including on
                # BaseException (KeyboardInterrupt / SystemExit) that the
                # inner per-entry handler doesn't catch — so the archive
                # is never leaked.
                with suppress(Exception):
                    archive_cm.__exit__(None, None, None)

        # Sort back into input order so callers see results in the order
        # they submitted entries (grouping is a transparent optimisation).
        results.sort(key=lambda r: r["index"])

        return json.dumps(
            {"results": results, "succeeded": succeeded, "failed": failed},
            ensure_ascii=False,
        )

    def _get_entry_content(
        self,
        archive: Archive,
        entry_path: str,
        max_content_length: int,
        validated_path: Path,
        content_offset: int = 0,
    ) -> Tuple[str, bool]:
        """Get the actual entry content with smart retrieval.

        Implements smart retrieval logic:
        1. Try direct entry access first
        2. If direct access fails, fall back to search-based retrieval
        3. Cache successful path mappings for future use

        Returns:
            (result_text, content_ok) — ``content_ok`` is False when
            ``process_mime_content`` raised and the result text is the
            ``(Error retrieving content: ...)`` sentinel; the caller must
            not cache the response in that case.
        """
        # Path mapping cache key includes archive path so identical entry
        # names in different ZIM files don't collide.
        cache_key = f"path_mapping:{validated_path}:{entry_path}"
        cached_actual_path = self.cache.get(cache_key)
        if cached_actual_path:
            logger.debug(
                f"Using cached path mapping: {entry_path} -> {cached_actual_path}"
            )
            try:
                result, content_ok, _resolved = self._get_entry_content_direct(
                    archive,
                    cached_actual_path,
                    entry_path,
                    max_content_length,
                    content_offset,
                )
                return result, content_ok
            except Exception as e:
                logger.warning(f"Cached path mapping failed: {e}")
                # Clear invalid cache entry and continue with smart retrieval
                self.cache.delete(cache_key)

        # Try direct access first
        try:
            logger.debug(f"Attempting direct entry access: {entry_path}")
            result, content_ok, resolved_path = self._get_entry_content_direct(
                archive, entry_path, entry_path, max_content_length, content_offset
            )
            # Cache the *resolved* path so a follow-up request for the same
            # redirect entry skips the redirect chain entirely. Path mapping
            # is valid even if content extraction hit a transient MIME error
            # — the path resolved, only the body raised.
            self.cache.set(cache_key, resolved_path)
            return result, content_ok
        except OpenZimMcpArchiveError:
            # Structural failures we raised ourselves (redirect cycles,
            # depth-limit) are not "entry not found" cases — searching for
            # the same path again would either return the same broken
            # redirect or a misleading match. Propagate unchanged.
            raise
        except Exception as direct_error:
            logger.debug(f"Direct entry access failed for {entry_path}: {direct_error}")

            # Fall back to search-based retrieval
            try:
                logger.info(f"Falling back to search-based retrieval for: {entry_path}")
                actual_path = self._find_entry_by_search(archive, entry_path)
                if actual_path:
                    result, content_ok, resolved_path = self._get_entry_content_direct(
                        archive,
                        actual_path,
                        entry_path,
                        max_content_length,
                        content_offset,
                    )
                    # Cache the resolved path (which may differ from
                    # ``actual_path`` if the search hit a redirect stub).
                    self.cache.set(cache_key, resolved_path)
                    logger.info(
                        f"Smart retrieval successful: {entry_path} -> {resolved_path}"
                    )
                    return result, content_ok
                else:
                    # No entry found via search
                    raise OpenZimMcpArchiveError(
                        f"Entry not found: '{entry_path}'. "
                        f"The entry path may not exist in this ZIM file. "
                        f"Try using search_zim_file() to find available entries, "
                        f"or browse_namespace() to explore the file structure."
                    )
            except OpenZimMcpArchiveError:
                # Re-raise our custom errors with guidance
                raise
            except Exception as search_error:
                logger.error(
                    f"Search-based retrieval failed for {entry_path}: "
                    f"{search_error}"
                )
                # Provide comprehensive error message with guidance
                raise OpenZimMcpArchiveError(
                    f"Failed to retrieve entry '{entry_path}'. "
                    f"Direct access failed: {direct_error}. "
                    f"Search-based fallback failed: {search_error}. "
                    f"The entry may not exist or the path format may be incorrect. "
                    f"Try using search_zim_file() to find the correct entry path."
                ) from search_error

    def _get_entry_content_direct(
        self,
        archive: Archive,
        actual_path: str,
        requested_path: str,
        max_content_length: int,
        content_offset: int = 0,
    ) -> Tuple[str, bool, str]:
        """Get entry content using the actual path from the ZIM file.

        Args:
            archive: ZIM archive instance
            actual_path: The actual path as it exists in the ZIM file
            requested_path: The originally requested path (for display)
            max_content_length: Maximum content length
            content_offset: Character offset to start reading from

        Returns:
            ``(result_text, content_ok, resolved_path)`` where
            ``content_ok`` is False when MIME processing raised and the
            body holds the ``(Error retrieving content: ...)`` sentinel,
            and ``resolved_path`` is the path of the resolved target after
            following any redirect chain (equal to ``actual_path`` when
            ``actual_path`` itself was not a redirect).
        """
        entry = archive.get_entry_by_path(actual_path)

        # Resolve redirects to the target entry so the response reflects
        # the resolved page (path, title, content) rather than the redirect
        # stub. Detect cycles and runaway chains explicitly — libzim's
        # ``Entry.get_item()`` silently follows the chain and would hang on
        # a cycle.
        seen_paths: set[str] = set()
        depth = 0
        while entry.is_redirect:
            if depth >= _zim_ops_mod.MAX_REDIRECT_DEPTH:
                raise OpenZimMcpArchiveError(
                    f"Redirect chain too deep (>{_zim_ops_mod.MAX_REDIRECT_DEPTH}) "
                    f"starting at {actual_path}"
                )
            if entry.path in seen_paths:
                raise OpenZimMcpArchiveError(f"Redirect cycle detected at {entry.path}")
            seen_paths.add(entry.path)
            entry = entry.get_redirect_entry()
            depth += 1

        # From here on, ``entry`` is the resolved target. Update
        # ``actual_path`` so the response and the path-mapping cache
        # reflect the target — subsequent lookups skip the chain entirely.
        actual_path = entry.path
        title = entry.title or "Untitled"

        # Get content
        content = ""
        content_type = ""
        content_ok = True

        try:
            item = entry.get_item()
            mime_type = item.mimetype or ""
            content_type = mime_type

            # Process content based on MIME type
            content = self.content_processor.process_mime_content(
                bytes(item.content), mime_type
            )

        except Exception as e:
            logger.warning(f"Error getting entry content: {e}")
            content = f"(Error retrieving content: {e})"
            content_ok = False

        total_length = len(content)
        offset_applied = False
        if content_offset and content_offset > 0:
            if content_offset >= total_length:
                content = ""
            else:
                content = content[content_offset:]
            offset_applied = True

        # Truncate if necessary
        content = self.content_processor.truncate_content(content, max_content_length)

        # Build return content - show both requested and actual paths if different
        result_text = f"# {title}\n\n"
        if actual_path != requested_path:
            result_text += f"Requested Path: {requested_path}\n"
            result_text += f"Actual Path: {actual_path}\n"
        else:
            result_text += f"Path: {actual_path}\n"
        result_text += f"Type: {content_type or 'Unknown'}\n"
        if offset_applied:
            result_text += (
                f"Content Offset: {content_offset} of {total_length:,} characters\n"
            )
        result_text += "## Content\n\n"
        result_text += content or "(No content)"

        return result_text, content_ok, actual_path

    def get_binary_entry(
        self,
        zim_file_path: str,
        entry_path: str,
        max_size_bytes: Optional[int] = None,
        include_data: bool = True,
    ) -> str:
        """Retrieve binary content from a ZIM entry.

        This method returns raw binary content encoded in base64, enabling
        integration with external tools for processing embedded media like
        PDFs, videos, and images.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'I/image.png' or 'C/document.pdf'
            max_size_bytes: Maximum size of content to return (default: 10MB)
            include_data: If True, include base64-encoded data; if False, metadata only

        Returns:
            JSON string containing binary content metadata and optionally the data

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If entry retrieval fails
        """
        from openzim_mcp.constants import DEFAULT_MAX_BINARY_SIZE

        if max_size_bytes is None:
            max_size_bytes = DEFAULT_MAX_BINARY_SIZE

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Cache key for invariant metadata (size, mime_type, etc.) — not data,
        # since data is potentially large and varies with max_size_bytes.
        cache_key = f"binary_meta:{validated_path}:{entry_path}"

        # If we already know the entry's metadata, we can short-circuit calls
        # that don't need bytes (include_data=False) or that would be rejected
        # for being over the size limit. include_data=True under the limit still
        # requires opening the archive to read the bytes.
        cached_meta = self.cache.get(cache_key)
        if cached_meta and (not include_data or cached_meta["size"] > max_size_bytes):
            logger.debug(f"Returning cached binary metadata for: {entry_path}")
            result = self._format_binary_response(
                cached_meta, include_data, max_size_bytes, data=None
            )
            return json.dumps(result, indent=2, ensure_ascii=False)

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                # Try direct access first
                try:
                    entry = archive.get_entry_by_path(entry_path)
                except Exception:
                    # Fall back to search-based retrieval
                    actual_path = self._find_entry_by_search(archive, entry_path)
                    if actual_path:
                        entry = archive.get_entry_by_path(actual_path)
                        entry_path = actual_path
                    else:
                        raise OpenZimMcpArchiveError(
                            f"Entry not found: '{entry_path}'. "
                            f"Try using search_zim_file() to find available entries, "
                            f"or browse_namespace() to explore the file structure."
                        )

                # Resolve the redirect chain — libzim raises RuntimeError on
                # get_item() of a redirect entry. Reflect the resolved path
                # back into entry_path so the response identifies the entry
                # actually served, matching _get_entry_content_direct. Use the
                # shared MAX_REDIRECT_DEPTH cap and a seen-set so a redirect
                # cycle is caught immediately rather than spinning to the cap.
                seen_paths: set[str] = set()
                redirect_hops = 0
                max_hops = _zim_ops_mod.MAX_REDIRECT_DEPTH
                while entry.is_redirect:
                    if redirect_hops >= max_hops:
                        raise OpenZimMcpArchiveError(
                            f"Redirect chain too deep (>{max_hops}) "
                            f"for: '{entry_path}'"
                        )
                    if entry.path in seen_paths:
                        raise OpenZimMcpArchiveError(
                            f"Redirect cycle detected at {entry.path}"
                        )
                    seen_paths.add(entry.path)
                    entry = entry.get_redirect_entry()
                    entry_path = entry.path
                    redirect_hops += 1

                item = entry.get_item()
                content_size = item.size
                meta = {
                    "path": entry_path,
                    "title": entry.title or "Untitled",
                    "mime_type": item.mimetype or "application/octet-stream",
                    "size": content_size,
                    "size_human": self._format_size(content_size),
                }

                # Read bytes only when we'll actually serve them — item.content
                # decompresses the entire entry into memory.
                encoded_data: Optional[str] = None
                if include_data and content_size <= max_size_bytes:
                    raw_content = bytes(item.content)
                    encoded_data = base64.b64encode(raw_content).decode("ascii")

                # Cache invariant metadata for future calls.
                self.cache.set(cache_key, meta)

                result = self._format_binary_response(
                    meta, include_data, max_size_bytes, data=encoded_data
                )
                logger.info(
                    f"Retrieved binary entry: {entry_path} "
                    f"({meta['mime_type']}, {self._format_size(content_size)})"
                )
                return json.dumps(result, indent=2, ensure_ascii=False)

        except OpenZimMcpArchiveError:
            raise
        except Exception as e:
            logger.error(f"Binary entry retrieval failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Failed to retrieve binary entry: {e}") from e

    def _format_binary_response(
        self,
        meta: Dict[str, Any],
        include_data: bool,
        max_size_bytes: int,
        data: Optional[str],
    ) -> Dict[str, Any]:
        """Build the response dict for get_binary_entry from cached/fresh metadata."""
        result: Dict[str, Any] = dict(meta)
        size = meta["size"]
        if include_data:
            if size <= max_size_bytes and data is not None:
                result["encoding"] = "base64"
                result["data"] = data
                result["truncated"] = False
            else:
                result["encoding"] = None
                result["data"] = None
                result["truncated"] = True
                result["message"] = (
                    f"Content size ({self._format_size(size)}) "
                    f"exceeds max_size_bytes ({self._format_size(max_size_bytes)}). "
                    f"Set include_data=False for metadata only, "
                    f"or increase max_size_bytes."
                )
        else:
            result["encoding"] = None
            result["data"] = None
            result["truncated"] = False
            result["message"] = "Data not included (include_data=False)"
        return result

    def _format_size(self, size_bytes: int) -> str:
        """Format size in bytes to human-readable string."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def get_entry_summary(
        self,
        zim_file_path: str,
        entry_path: str,
        max_words: int = 200,
    ) -> str:
        """Get a concise summary of an article without returning the full content.

        This method extracts the opening paragraph(s) or introduction section,
        providing a quick overview of the article content. Useful for getting
        context without loading full articles.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'
            max_words: Maximum number of words in the summary (default: 200)

        Returns:
            JSON string containing the article summary

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If summary extraction fails
        """
        # Clamp to a sane upper bound; the tool layer enforces the
        # documented [1, 1000] range, so we don't impose a silent floor
        # here (callers asking for max_words=1 should get one word, not
        # ten).
        if max_words < 1:
            max_words = 1
        elif max_words > 1000:
            max_words = 1000

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"summary:{validated_path}:{entry_path}:{max_words}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached summary for: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result = self._extract_entry_summary(archive, entry_path, max_words)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(f"Extracted summary for: {entry_path}")
            return result

        except Exception as e:
            logger.error(f"Summary extraction failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Summary extraction failed: {e}") from e

    def _extract_entry_summary(
        self, archive: Archive, entry_path: str, max_words: int
    ) -> str:
        """Extract summary from article content."""
        try:
            entry, entry_path = self._resolve_entry_with_fallback(archive, entry_path)

            title = entry.title or "Untitled"
            item = entry.get_item()
            mime_type = item.mimetype or ""
            raw_content = bytes(item.content).decode("utf-8", errors="replace")

            summary_data: Dict[str, Any] = {
                "title": title,
                "path": entry_path,
                "content_type": mime_type,
                "summary": "",
                "word_count": 0,
                "is_truncated": False,
            }

            if mime_type.startswith("text/html"):
                summary_data.update(self._extract_html_summary(raw_content, max_words))
            elif mime_type.startswith("text/"):
                # For plain text, take first N words
                plain_text = raw_content.strip()
                words = plain_text.split()
                if len(words) > max_words:
                    summary_data["summary"] = " ".join(words[:max_words]) + "..."
                    summary_data["is_truncated"] = True
                else:
                    summary_data["summary"] = plain_text
                summary_data["word_count"] = min(len(words), max_words)
            else:
                summary_data["summary"] = f"(Non-text content: {mime_type})"

            return json.dumps(summary_data, indent=2, ensure_ascii=False)

        except OpenZimMcpArchiveError:
            raise
        except Exception as e:
            logger.error(f"Error extracting summary for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(
                f"Failed to extract article summary: {e}"
            ) from e

    def _extract_html_summary(
        self, html_content: str, max_words: int
    ) -> Dict[str, Any]:
        """Extract summary from HTML content.

        Prioritizes:
        1. Paragraphs AFTER the first H1 (skips skip-nav and site banners
           that always sit above the title).
        2. Content of any <p> tags as fallback (with chrome stripped).
        3. Any text content as final fallback.

        Errors propagate to the caller so a transient parse failure is not
        cached as a permanent ``"(Error extracting summary)"`` sentinel for
        the full TTL. ``get_entry_summary`` translates the exception into a
        user-facing ``Summary extraction failed`` error response.
        """
        from bs4 import BeautifulSoup, Tag

        result: Dict[str, Any] = {
            "summary": "",
            "word_count": 0,
            "is_truncated": False,
        }

        soup = BeautifulSoup(html_content, "html.parser")

        # Remove navigation, sidebars, infoboxes, banners, etc.
        unwanted_selectors = [
            "nav",
            "header",
            "footer",
            "aside",
            "script",
            "style",
            "noscript",
            "form",
            # Wikipedia / MediaWiki chrome
            ".infobox",
            ".navbox",
            ".sidebar",
            ".toc",
            ".mw-editsection",
            ".reference",
            ".reflist",
            "#coordinates",
            ".hatnote",
            ".mbox",
            ".ambox",
            ".metadata",
            # USWDS / federal-site banners (MedlinePlus, NIH, NIST...)
            ".usa-banner",
            ".usa-overlay",
            ".usa-skipnav",
            "#skipnav",
            "#skipNav",
            "[role='banner']",
            "[role='navigation']",
        ]
        for selector in unwanted_selectors:
            for element in soup.select(selector):
                element.decompose()

        # Prefer paragraphs that come AFTER the first H1 — site banners,
        # cookie notices, and "skip to content" blocks always sit above
        # the document title and pollute summaries when collected naively.
        first_h1 = soup.find("h1")
        paragraph_iter: List[Tag] = []
        if isinstance(first_h1, Tag):
            paragraph_iter = [
                p for p in first_h1.find_all_next("p") if isinstance(p, Tag)
            ]
        if not paragraph_iter:
            paragraph_iter = [p for p in soup.find_all("p") if isinstance(p, Tag)]

        paragraphs = []
        for p in paragraph_iter:
            text = p.get_text().strip()
            # Skip very short paragraphs (likely captions or labels)
            if len(text) > 50:
                paragraphs.append(text)
                total_words = sum(len(para.split()) for para in paragraphs)
                if total_words >= max_words:
                    break

        if paragraphs:
            # Combine paragraphs and truncate to max_words
            combined = " ".join(paragraphs)
            words = combined.split()

            if len(words) > max_words:
                result["summary"] = " ".join(words[:max_words]) + "..."
                result["is_truncated"] = True
                result["word_count"] = max_words
            else:
                result["summary"] = combined
                result["word_count"] = len(words)
        else:
            # Fallback: use html2text to get any text
            plain_text = self.content_processor.html_to_plain_text(html_content)
            words = plain_text.split()

            if len(words) > max_words:
                result["summary"] = " ".join(words[:max_words]) + "..."
                result["is_truncated"] = True
                result["word_count"] = max_words
            else:
                result["summary"] = plain_text
                result["word_count"] = len(words)

        return result
