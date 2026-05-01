"""ZIM file operations with proper resource management."""

import base64
import json
import logging
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from libzim.reader import Archive  # type: ignore[import-untyped]
from libzim.search import Query, Searcher  # type: ignore[import-untyped]
from libzim.suggestion import (  # type: ignore[import-untyped]
    SuggestionSearcher,
)

from .cache import OpenZimMcpCache
from .config import OpenZimMcpConfig
from .constants import (
    DEFAULT_MAIN_PAGE_TRUNCATION,
    NAMESPACE_MAX_ENTRIES,
    NAMESPACE_MAX_SAMPLE_SIZE,
    NAMESPACE_SAMPLE_ATTEMPTS_MULTIPLIER,
)
from .content_processor import ContentProcessor
from .defaults import CONTENT
from .exceptions import (
    ArchiveOpenTimeoutError,
    OpenZimMcpArchiveError,
    OpenZimMcpValidationError,
)
from .security import PathValidator
from .timeout_utils import run_with_timeout

# Timeout for opening ZIM archives (seconds)
ARCHIVE_OPEN_TIMEOUT = 30.0

# Maximum redirect chain length before bailing out. See
# ``ContentDefaults.MAX_REDIRECT_DEPTH`` in ``defaults.py``.
MAX_REDIRECT_DEPTH = CONTENT.MAX_REDIRECT_DEPTH


class PaginationCursor:
    """Utility class for creating and parsing pagination cursors.

    Cursors encode pagination state as base64 tokens, making it easy for
    clients to continue from where they left off without tracking offset manually.
    """

    @staticmethod
    def _encode(offset: int, limit: int, query: Optional[str] = None) -> str:
        """Encode pagination state into a base64 cursor token."""
        cursor_data: Dict[str, Any] = {"o": offset, "l": limit}
        if query:
            cursor_data["q"] = query
        json_str = json.dumps(cursor_data, separators=(",", ":"))
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    @staticmethod
    def create_next_cursor(
        current_offset: int, limit: int, total: int, query: Optional[str] = None
    ) -> Optional[str]:
        """Create cursor for the next page, or None if no more results.

        Args:
            current_offset: Current offset position
            limit: Page size
            total: Total number of results
            query: Optional query string

        Returns:
            Next page cursor or None if at end
        """
        next_offset = current_offset + limit
        if next_offset >= total:
            return None
        return PaginationCursor._encode(next_offset, limit, query)

    @staticmethod
    def decode(token: str) -> Dict[str, Any]:
        """Decode a base64 cursor token back to its pagination state.

        Args:
            token: A cursor previously emitted by ``create_next_cursor``.

        Returns:
            Dict with keys ``o`` (offset, int), ``l`` (limit, int), and
            optionally ``q`` (query, str).

        Raises:
            ValueError: If the token isn't valid base64 or doesn't decode to
                the expected JSON shape. Callers should treat this as a
                client error (malformed cursor).
        """
        try:
            # Accept urlsafe and standard base64 since some clients normalise.
            padded = token + "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(padded.encode()).decode()
            data = json.loads(raw)
        except Exception as e:
            raise ValueError(f"Invalid pagination cursor: {e}") from e
        if not isinstance(data, dict) or "o" not in data or "l" not in data:
            raise ValueError("Cursor missing required fields ('o', 'l')")
        if not isinstance(data["o"], int) or not isinstance(data["l"], int):
            raise ValueError("Cursor offset and limit must be integers")
        return data


logger = logging.getLogger(__name__)


@contextmanager
def zim_archive(
    file_path: Path, timeout_seconds: float = ARCHIVE_OPEN_TIMEOUT
) -> Generator[Archive, None, None]:
    """Context manager for ZIM archive operations with resource cleanup and timeout.

    Args:
        file_path: Path to the ZIM file
        timeout_seconds: Maximum time to wait for archive to open (default: 30s)

    Yields:
        Archive object for reading ZIM content

    Raises:
        OpenZimMcpArchiveError: If archive fails to open or times out
    """

    # Open phase: wrap any failure as OpenZimMcpArchiveError so callers see
    # a consistent error type. This block must NOT contain the yield —
    # otherwise exceptions from the with-body get re-wrapped here as
    # misleading "Failed to open ZIM archive" errors.
    def open_archive() -> Archive:
        return Archive(str(file_path))

    try:
        archive = run_with_timeout(
            open_archive,
            timeout_seconds,
            f"Timed out opening ZIM archive after {timeout_seconds}s: {file_path}",
            ArchiveOpenTimeoutError,
        )
    except ArchiveOpenTimeoutError as e:
        raise OpenZimMcpArchiveError(str(e)) from e
    except Exception as e:
        raise OpenZimMcpArchiveError(f"Failed to open ZIM archive: {file_path}") from e

    logger.debug(f"Opened ZIM archive: {file_path}")
    try:
        yield archive
    finally:
        logger.debug(f"Releasing ZIM archive: {file_path}")


class ZimOperations:
    """Handles all ZIM file operations with caching and security."""

    def __init__(
        self,
        config: OpenZimMcpConfig,
        path_validator: PathValidator,
        cache: OpenZimMcpCache,
        content_processor: ContentProcessor,
    ):
        """Initialize ZIM operations.

        Args:
            config: Server configuration
            path_validator: Path validation service
            cache: Cache service
            content_processor: Content processing service
        """
        self.config = config
        self.path_validator = path_validator
        self.cache = cache
        self.content_processor = content_processor
        logger.info("ZimOperations initialized")

    def _scan_zim_files(self) -> List[Dict[str, Any]]:
        """Scan all allowed directories for ZIM files (uncached)."""
        logger.info(
            f"Searching for ZIM files in {len(self.config.allowed_directories)} "
            "directories:"
        )
        for dir_path in self.config.allowed_directories:
            logger.info(f"  - {dir_path}")

        all_zim_files: List[Dict[str, Any]] = []
        for directory_str in self.config.allowed_directories:
            directory = Path(directory_str)
            logger.debug(f"Scanning directory: {directory}")
            try:
                zim_files_in_dir = list(directory.glob("**/*.zim"))
                logger.debug(f"Found {len(zim_files_in_dir)} ZIM files in {directory}")

                for file_path in zim_files_in_dir:
                    if not file_path.is_file():
                        continue
                    try:
                        stats = file_path.stat()
                        all_zim_files.append(
                            {
                                "name": file_path.name,
                                "path": str(file_path),
                                "directory": str(directory),
                                "size": f"{stats.st_size / (1024 * 1024):.2f} MB",
                                "size_bytes": stats.st_size,
                                "modified": datetime.fromtimestamp(
                                    stats.st_mtime
                                ).isoformat(),
                            }
                        )
                    except OSError as e:
                        logger.warning(f"Error reading file stats for {file_path}: {e}")
            except Exception as e:
                logger.error(f"Error processing directory {directory}: {e}")

        return all_zim_files

    def list_zim_files_data(
        self, name_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List all ZIM files in allowed directories as structured data.

        The directory scan is cached once. Filtering is applied in-memory
        against the cached list, so distinct filters share a single cache slot.

        Args:
            name_filter: Optional case-insensitive substring; only files whose
                filename contains it are returned. Surrounding whitespace is
                ignored. Empty/None disables filtering.

        Returns:
            List of dictionaries containing ZIM file information.
            Each dict has: name, path, directory, size, size_bytes, modified
        """
        cache_key = "zim_files_list_data"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Returning cached ZIM files list data")
            all_zim_files: List[Dict[str, Any]] = cached_result
        else:
            all_zim_files = self._scan_zim_files()
            self.cache.set(cache_key, all_zim_files)
            logger.info(f"Listed {len(all_zim_files)} ZIM files")

        needle = (name_filter or "").strip().lower()
        if not needle:
            return all_zim_files
        return [f for f in all_zim_files if needle in f["name"].lower()]

    def list_zim_files(self, name_filter: Optional[str] = None) -> str:
        """List all ZIM files in allowed directories.

        Args:
            name_filter: Optional case-insensitive substring; only files whose
                filename contains it are listed. Surrounding whitespace is
                ignored. Empty/None disables filtering.

        Returns:
            JSON string containing the list of ZIM files
        """
        all_zim_files = self.list_zim_files_data(name_filter=name_filter)

        if not all_zim_files:
            if (name_filter or "").strip():
                return (
                    "No ZIM files found in allowed directories matching filter "
                    f"{name_filter!r}"
                )
            return "No ZIM files found in allowed directories"

        result_text = (
            f"Found {len(all_zim_files)} ZIM files in "
            f"{len(self.config.allowed_directories)} directories:\n\n"
        )
        result_text += json.dumps(all_zim_files, indent=2, ensure_ascii=False)
        return result_text

    def search_zim_file(
        self,
        zim_file_path: str,
        query: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> str:
        """Search within ZIM file content.

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query term
            limit: Maximum number of results to return
            offset: Result starting offset (for pagination)

        Returns:
            Search result text

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If search operation fails
        """
        if limit is None:
            limit = self.config.content.default_search_limit

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"search:{validated_path}:{query}:{limit}:{offset}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached search results for query: {query}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result, total_results = self._perform_search(
                    archive, query, limit, offset
                )

            # Don't cache zero-result responses: libzim's lazy index warm-up
            # can return 0 matches transiently, and a TTL-cached "no results"
            # would mask the index becoming ready.
            if total_results > 0:
                self.cache.set(cache_key, result)
            logger.debug(f"Search completed: query='{query}', results found")
            return result

        except Exception as e:
            logger.error(f"Search failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Search operation failed: {e}") from e

    def _perform_search(
        self, archive: Archive, query: str, limit: int, offset: int
    ) -> Tuple[str, int]:
        """Perform the actual search operation.

        Returns:
            (result_text, total_results) — caller uses total_results to decide
            whether the response is safe to cache.
        """
        # Create searcher and execute search
        query_obj = Query().set_query(query)
        searcher = Searcher(archive)
        search = searcher.search(query_obj)

        # Get total results
        total_results = search.getEstimatedMatches()

        if total_results == 0:
            return f'No search results found for "{query}"', 0

        # Guard against offset exceeding total results (would produce negative count)
        if offset >= total_results:
            return (
                f'Found {total_results} matches for "{query}", '
                f"but offset {offset} exceeds total results."
            ), total_results

        result_count = min(limit, total_results - offset)

        # Get search results
        result_entries = list(search.getResults(offset, result_count))

        # Collect search results
        results = []
        for i, entry_id in enumerate(result_entries):
            try:
                entry = archive.get_entry_by_path(entry_id)
                title = entry.title or "Untitled"

                # Get content snippet
                snippet = self._get_entry_snippet(entry)

                results.append({"path": entry_id, "title": title, "snippet": snippet})
            except Exception as e:
                logger.warning(f"Error processing search result {entry_id}: {e}")
                results.append(
                    {
                        "path": entry_id,
                        "title": f"Entry {offset + i + 1}",
                        "snippet": f"(Error getting entry details: {e})",
                    }
                )

        # Build result text with pagination info
        result_text = (
            f'Found {total_results} matches for "{query}", '
            f"showing {offset + 1}-{offset + len(results)}:\n\n"
        )

        for i, result in enumerate(results):
            result_text += f"## {offset + i + 1}. {result['title']}\n"
            result_text += f"Path: {result['path']}\n"
            result_text += f"Snippet: {result['snippet']}\n\n"

        # Add pagination information
        has_more = (offset + len(results)) < total_results
        result_text += "---\n"
        result_text += (
            f"**Pagination**: Showing {offset + 1}-{offset + len(results)} "
            f"of {total_results}\n"
        )

        if has_more:
            next_cursor = PaginationCursor.create_next_cursor(
                offset, limit, total_results, query
            )
            result_text += f"**Next cursor**: `{next_cursor}`\n"
            result_text += (
                f"**Hint**: pass `cursor={next_cursor}` "
                f"or `offset={offset + limit}` to get the next page\n"
            )
        else:
            result_text += "**End of results**\n"

        return result_text, total_results

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

        # Check cache
        cache_key = (
            f"entry:{validated_path}:{entry_path}:"
            f"{max_content_length}:{content_offset}"
        )
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached entry: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
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
        from .constants import MAX_BATCH_SIZE

        if not entries:
            raise OpenZimMcpValidationError("entries list cannot be empty")
        if len(entries) > MAX_BATCH_SIZE:
            raise OpenZimMcpValidationError(
                f"batch size {len(entries)} exceeds limit {MAX_BATCH_SIZE}; "
                "split into multiple batches"
            )

        results: List[Dict[str, Any]] = []
        succeeded = 0
        failed = 0
        for index, entry in enumerate(entries):
            zim_file_path = entry.get("zim_file_path", "")
            entry_path = entry.get("entry_path", "")
            try:
                content = self.get_zim_entry(
                    zim_file_path, entry_path, max_content_length, 0
                )
                results.append(
                    {
                        "index": index,
                        "zim_file_path": zim_file_path,
                        "entry_path": entry_path,
                        "success": True,
                        "content": content,
                    }
                )
                succeeded += 1
            except Exception as e:  # noqa: BLE001 - per-entry isolation by design
                results.append(
                    {
                        "index": index,
                        "zim_file_path": zim_file_path,
                        "entry_path": entry_path,
                        "success": False,
                        "error": str(e),
                    }
                )
                failed += 1

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
            if depth >= MAX_REDIRECT_DEPTH:
                raise OpenZimMcpArchiveError(
                    f"Redirect chain too deep (>{MAX_REDIRECT_DEPTH}) "
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

    def _find_entry_by_search(self, archive: Archive, entry_path: str) -> Optional[str]:
        """Find the actual entry path by searching for the entry.

        This method attempts to find an entry by searching for various parts
        of the provided path, handling common path encoding issues.

        Args:
            archive: ZIM archive instance
            entry_path: The requested entry path

        Returns:
            The actual entry path if found, None otherwise
        """
        from libzim.search import Query, Searcher

        # Extract potential search terms from the path
        search_terms = self._extract_search_terms_from_path(entry_path)

        for search_term in search_terms:
            if len(search_term) < 2:  # Skip very short terms
                continue

            try:
                logger.debug(f"Searching for entry with term: '{search_term}'")
                query_obj = Query().set_query(search_term)
                searcher = Searcher(archive)
                search = searcher.search(query_obj)

                total_results = search.getEstimatedMatches()
                if total_results == 0:
                    continue

                # Check first few results for exact or close matches
                max_results = min(total_results, 10)  # Limit search for performance
                result_entries = list(search.getResults(0, max_results))

                for result_path in result_entries:
                    # Check if this result is a good match for our requested path
                    result_path_str = str(result_path)
                    if self._is_path_match(entry_path, result_path_str):
                        logger.debug(f"Found matching entry: {result_path_str}")
                        return result_path_str

            except Exception as e:
                logger.debug(f"Search failed for term '{search_term}': {e}")
                continue

        return None

    def _extract_search_terms_from_path(self, entry_path: str) -> List[str]:
        """Extract potential search terms from an entry path.

        Args:
            entry_path: The entry path to extract terms from

        Returns:
            List of search terms to try
        """
        terms = []

        # Remove namespace prefix if present (e.g., "A/Article" -> "Article")
        if "/" in entry_path:
            path_without_namespace = entry_path.split("/", 1)[1]
            terms.append(path_without_namespace)
        else:
            path_without_namespace = entry_path

        # Add the full path as a search term
        terms.append(entry_path)

        # Replace underscores with spaces (common in Wikipedia-style paths)
        if "_" in path_without_namespace:
            terms.append(path_without_namespace.replace("_", " "))

        # Replace spaces with underscores
        if " " in path_without_namespace:
            terms.append(path_without_namespace.replace(" ", "_"))

        # URL decode if it looks like it might be encoded
        import urllib.parse

        try:
            decoded = urllib.parse.unquote(path_without_namespace)
            if decoded != path_without_namespace:
                terms.append(decoded)
        except Exception as e:
            logger.debug(f"URL decode failed for path '{path_without_namespace}': {e}")

        # Remove duplicates while preserving order
        seen = set()
        unique_terms = []
        for term in terms:
            if term not in seen:
                seen.add(term)
                unique_terms.append(term)

        return unique_terms

    def _is_path_match(self, requested_path: str, actual_path: str) -> bool:
        """Check if an actual path from search results matches the requested path.

        Args:
            requested_path: The originally requested path
            actual_path: A path from search results

        Returns:
            True if the paths are considered a match
        """
        # Exact match
        if requested_path == actual_path:
            return True

        # Extract the path part without namespace
        requested_part = (
            requested_path.split("/", 1)[1] if "/" in requested_path else requested_path
        )
        actual_part = (
            actual_path.split("/", 1)[1] if "/" in actual_path else actual_path
        )

        # Case-insensitive comparison
        if requested_part.lower() == actual_part.lower():
            return True

        # Compare with underscore/space variations
        requested_normalized = requested_part.replace("_", " ").lower()
        actual_normalized = actual_part.replace("_", " ").lower()
        if requested_normalized == actual_normalized:
            return True

        # URL encoding comparison
        import urllib.parse

        try:
            requested_decoded = urllib.parse.unquote(requested_part).lower()
            actual_decoded = urllib.parse.unquote(actual_part).lower()
            if requested_decoded == actual_decoded:
                return True
        except Exception as e:
            logger.debug(f"URL decode comparison failed: {e}")

        return False

    def get_zim_metadata(self, zim_file_path: str) -> str:
        """Get ZIM file metadata from M namespace entries.

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            JSON string containing ZIM metadata

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If metadata retrieval fails
        """
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"metadata:{validated_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached metadata for: {validated_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                metadata = self._extract_zim_metadata(archive)

            # Cache the result
            self.cache.set(cache_key, metadata)
            logger.info(f"Retrieved metadata for: {validated_path}")
            return metadata

        except Exception as e:
            logger.error(f"Metadata retrieval failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Metadata retrieval failed: {e}") from e

    def _extract_zim_metadata(self, archive: Archive) -> str:
        """Extract metadata from ZIM archive."""
        # Basic archive information
        metadata = {
            "entry_count": archive.entry_count,
            "all_entry_count": archive.all_entry_count,
            "article_count": archive.article_count,
            "media_count": archive.media_count,
        }

        # Try to get metadata from M namespace
        metadata_entries = {}
        try:
            # Common metadata entries in M namespace
            common_metadata = [
                "Title",
                "Description",
                "Language",
                "Creator",
                "Publisher",
                "Date",
                "Source",
                "License",
                "Relation",
                "Flavour",
                "Tags",
            ]

            for meta_key in common_metadata:
                try:
                    entry = archive.get_entry_by_path(f"M/{meta_key}")
                    if entry:
                        item = entry.get_item()
                        content = (
                            bytes(item.content)
                            .decode("utf-8", errors="replace")
                            .strip()
                        )
                        if content:
                            metadata_entries[meta_key] = content
                except Exception as e:
                    # Entry doesn't exist or can't be read - expected for optional
                    logger.debug(f"Metadata 'M/{meta_key}' not available: {e}")

        except Exception as e:
            logger.warning(f"Error extracting metadata entries: {e}")

        if metadata_entries:
            metadata["metadata_entries"] = metadata_entries

        return json.dumps(metadata, indent=2, ensure_ascii=False)

    def get_main_page(self, zim_file_path: str) -> str:
        """Get the main page entry from W namespace.

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            Main page content or information about main page

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If main page retrieval fails
        """
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"main_page:{validated_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached main page for: {validated_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result, content_ok = self._get_main_page_content(archive)

            # Don't cache error sentinels: a transient failure (e.g. MIME
            # processing error) should not be locked in for the TTL.
            if content_ok:
                self.cache.set(cache_key, result)
            logger.info(f"Retrieved main page for: {validated_path}")
            return result

        except Exception as e:
            logger.error(f"Main page retrieval failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Main page retrieval failed: {e}") from e

    def _get_main_page_content(self, archive: Archive) -> Tuple[str, bool]:
        """Get main page content from archive.

        Returns:
            (text, content_ok) — ``content_ok`` is False when the body holds an
            error sentinel produced by a fallback path (MIME processing or
            outer exception), so the caller can skip caching it.
        """
        try:
            # Try to get main page from archive metadata
            if hasattr(archive, "main_entry") and archive.main_entry:
                main_entry = archive.main_entry
                title = main_entry.title or "Main Page"
                path = main_entry.path

                # Get content
                try:
                    item = main_entry.get_item()
                    content = self.content_processor.process_mime_content(
                        bytes(item.content), item.mimetype
                    )

                    # Truncate content for main page display
                    content = self.content_processor.truncate_content(
                        content, DEFAULT_MAIN_PAGE_TRUNCATION
                    )

                    result = f"# {title}\n\n"
                    result += f"Path: {path}\n"
                    result += "Type: Main Page Entry\n"
                    result += "## Content\n\n"
                    result += content

                    return result, True

                except Exception as e:
                    logger.warning(f"Error getting main page content: {e}")
                    return (
                        f"# Main Page\n\nPath: {path}\n\n"
                        f"(Error retrieving content: {e})"
                    ), False

            # Fallback: try common main page paths
            main_page_paths = ["W/mainPage", "A/Main_Page", "A/index", ""]

            for path in main_page_paths:
                try:
                    if path:
                        entry = archive.get_entry_by_path(path)
                    else:
                        # Try to get the first entry as fallback
                        if archive.entry_count > 0:
                            entry = archive._get_entry_by_id(0)
                        else:
                            continue

                    if entry:
                        title = entry.title or "Main Page"
                        entry_path = entry.path

                        try:
                            item = entry.get_item()
                            content = self.content_processor.process_mime_content(
                                bytes(item.content), item.mimetype
                            )
                            content = self.content_processor.truncate_content(
                                content, DEFAULT_MAIN_PAGE_TRUNCATION
                            )

                            result = f"# {title}\n\n"
                            result += f"Path: {entry_path}\n"
                            result += (
                                f"Type: Main Page (found at {path or 'first entry'})\n"
                            )
                            result += "## Content\n\n"
                            result += content

                            return result, True

                        except Exception as e:
                            logger.warning(f"Error getting content for {path}: {e}")
                            continue

                except Exception:  # nosec B112 - intentional fallback
                    # Path doesn't exist, try next
                    continue

            # No main page found — this is a structural property of the
            # archive, so it's safe to cache.
            return (
                "# Main Page\n\nNo main page found in this ZIM file.\n\n"
                "The archive may not have a designated main page entry."
            ), True

        except Exception as e:
            logger.error(f"Error getting main page: {e}")
            return f"# Main Page\n\nError retrieving main page: {e}", False

    def list_namespaces(self, zim_file_path: str) -> str:
        """List available namespaces and their entry counts.

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            JSON string containing namespace information

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If namespace listing fails
        """
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"namespaces:{validated_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached namespaces for: {validated_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result = self._list_archive_namespaces(archive)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(f"Listed namespaces for: {validated_path}")
            return result

        except Exception as e:
            logger.error(f"Namespace listing failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Namespace listing failed: {e}") from e

    def _list_archive_namespaces(self, archive: Archive) -> str:
        """List namespaces in the archive.

        For small archives (entry_count <= NAMESPACE_MAX_SAMPLE_SIZE) iterate
        every entry by ID so the namespace inventory is exhaustive. For larger
        archives, fall back to random sampling and return estimated counts.
        Random sampling on small entry pools collides heavily, leaving
        namespaces undiscovered and counts wildly off.
        """
        namespaces: Dict[str, Dict[str, Any]] = {}
        namespace_descriptions = {
            "C": "User content entries (articles, main content)",
            "M": "ZIM metadata (title, description, language, etc.)",
            "W": "Well-known entries (MainPage, Favicon, navigation)",
            "X": "Search indexes and full-text search data",
            "A": "Legacy content namespace (older ZIM files)",
            "I": "Images and media files",
            "-": "Layout and template files",
        }

        has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)
        logger.debug(f"Archive uses new namespace scheme: {has_new_scheme}")

        total_entries = archive.entry_count
        full_iteration = total_entries <= NAMESPACE_MAX_SAMPLE_SIZE

        seen_entries: set[str] = set()

        def _record(path: str, title: str, is_probe: bool = False) -> None:
            if path in seen_entries:
                return
            seen_entries.add(path)
            namespace = self._extract_namespace_from_path(path, has_new_scheme)
            ns_info = namespaces.setdefault(
                namespace,
                {
                    "count": 0,
                    "description": namespace_descriptions.get(
                        namespace, f"Namespace '{namespace}'"
                    ),
                    "sample_entries": [],
                    # Track sampled vs probed separately. Probed entries are
                    # deterministic existence proofs — they do NOT carry the
                    # sampling-frequency signal needed for ratio extrapolation.
                    "_probed_count": 0,
                    "_sampled_count": 0,
                },
            )
            if is_probe:
                ns_info["_probed_count"] += 1
            else:
                ns_info["_sampled_count"] += 1
            ns_info["count"] += 1
            if len(ns_info["sample_entries"]) < 5:
                ns_info["sample_entries"].append({"path": path, "title": title or path})

        if full_iteration:
            logger.debug(
                f"Iterating all {total_entries} entries for exhaustive "
                f"namespace listing"
            )
            for entry_id in range(total_entries):
                try:
                    entry = archive._get_entry_by_id(entry_id)
                    _record(entry.path, entry.title or "")
                except Exception as e:
                    logger.debug(f"Error reading entry {entry_id}: {e}")
                    continue

            for ns_info in namespaces.values():
                ns_info["sampled_count"] = ns_info["count"]
                ns_info["estimated_total"] = ns_info["count"]
                # Drop internal counters before serialization.
                ns_info.pop("_probed_count", None)
                ns_info.pop("_sampled_count", None)
        else:
            sample_size = min(NAMESPACE_MAX_SAMPLE_SIZE, total_entries)
            max_sample_attempts = sample_size * NAMESPACE_SAMPLE_ATTEMPTS_MULTIPLIER
            logger.debug(
                f"Sampling {sample_size} entries from {total_entries} total entries"
            )
            try:
                for _ in range(max_sample_attempts):
                    if len(seen_entries) >= sample_size:
                        break
                    try:
                        entry = archive.get_random_entry()
                        _record(entry.path, entry.title or "", is_probe=False)
                    except Exception as e:
                        logger.debug(f"Error sampling entry: {e}")
                        continue
            except Exception as e:
                logger.warning(f"Error during namespace sampling: {e}")

            # Known-prefix probe: random sampling on a large archive will
            # silently miss minority namespaces (e.g. M, W, X, I when A holds
            # 99%+ of entries). Try canonical paths in each common namespace
            # to surface them deterministically.
            sampled_only_count = sum(v["_sampled_count"] for v in namespaces.values())
            for canonical_path in self._get_known_namespace_probes():
                try:
                    if (
                        archive.has_entry_by_path(canonical_path)
                        and canonical_path not in seen_entries
                    ):
                        try:
                            entry = archive.get_entry_by_path(canonical_path)
                            _record(entry.path, entry.title or "", is_probe=True)
                        except Exception as e:
                            logger.debug(
                                f"Error reading canonical entry {canonical_path}: {e}"
                            )
                except Exception as e:
                    logger.debug(f"Error probing canonical path {canonical_path}: {e}")

            # Build the final per-namespace numbers. We extrapolate ONLY the
            # randomly-sampled count via sampling ratio — probed entries are
            # confirmed-present-but-frequency-unknown, so they only contribute
            # a lower-bound floor. This avoids the previous bug where, e.g.,
            # probing 5 M/* paths produced an estimated_total of ~100 from a
            # 1000-of-20565 sample (5 / 0.0486), a fabricated number.
            sampling_ratio = (
                sampled_only_count / total_entries if sampled_only_count else 0.0
            )
            # Project only when we have enough sampled signal to make a stable
            # estimate. Below the threshold, single-hit projections vary by
            # 100%+ and effectively manufacture numbers — better to report the
            # lower-bound (confirmed sightings) honestly.
            PROJECTION_MIN_SAMPLES = 3
            for ns_info in namespaces.values():
                sampled = ns_info["_sampled_count"]
                probed = ns_info["_probed_count"]
                if sampling_ratio > 0 and sampled >= PROJECTION_MIN_SAMPLES:
                    estimated_from_sample = int(sampled / sampling_ratio)
                else:
                    estimated_from_sample = 0
                lower_bound = sampled + probed
                estimated_total = max(estimated_from_sample, lower_bound)

                ns_info["sampled_count"] = sampled
                ns_info["probed_count"] = probed
                ns_info["estimated_total"] = estimated_total
                ns_info["count"] = estimated_total
                ns_info.pop("_probed_count", None)
                ns_info.pop("_sampled_count", None)

        result = {
            "total_entries": total_entries,
            "sampled_entries": len(seen_entries),
            "has_new_namespace_scheme": has_new_scheme,
            "is_total_authoritative": full_iteration,
            "discovery_method": "full_iteration" if full_iteration else "sampling",
            "namespaces": namespaces,
        }

        return json.dumps(result, indent=2, ensure_ascii=False)

    def _extract_namespace_from_path(self, path: str, has_new_scheme: bool) -> str:
        """Extract namespace from entry path based on ZIM format."""
        if not path:
            return "Unknown"

        # For new namespace scheme, namespace is typically the first part before '/'
        # For old scheme, it might be just the first character
        if "/" in path:
            namespace = path.split("/", 1)[0]
        else:
            # If no slash, treat the first character as namespace (old scheme)
            namespace = path[0] if path else "Unknown"

        # Handle common namespace variations
        if len(namespace) == 1 and namespace.isalpha():
            # Single character namespace (typical for both old and new schemes)
            return namespace.upper()
        elif namespace in ["content", "Content"]:
            return "C"
        elif namespace in ["metadata", "Metadata"]:
            return "M"
        elif namespace in ["wellknown", "well-known", "Wellknown"]:
            return "W"
        elif namespace in ["search", "Search", "index", "Index"]:
            return "X"
        else:
            # Return as-is for other namespaces
            return namespace

    @staticmethod
    def _get_known_namespace_probes() -> List[str]:
        """Canonical paths that, if present, prove a namespace exists.

        Used by list_namespaces to deterministically surface minority
        namespaces (M, W, X, I, -) that random sampling would otherwise miss
        on archives where one namespace dominates.
        """
        return [
            # Metadata
            "M/Title",
            "M/Description",
            "M/Language",
            "M/Creator",
            "M/Date",
            # Well-known
            "W/mainPage",
            "W/favicon",
            # Search indexes
            "X/fulltext/xapian",
            "X/title/xapian",
            # Images / media
            "I/favicon.png",
            # Layout / templates
            "-/favicon",
        ]

    def browse_namespace(
        self, zim_file_path: str, namespace: str, limit: int = 50, offset: int = 0
    ) -> str:
        """Browse entries in a specific namespace with pagination.

        Args:
            zim_file_path: Path to the ZIM file
            namespace: Namespace to browse (C, M, W, X, A, I for old; domains for new)
            limit: Maximum number of entries to return
            offset: Starting offset for pagination

        Returns:
            JSON string containing namespace entries

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If browsing fails
        """
        # Validate parameters
        if limit < 1 or limit > 200:
            raise OpenZimMcpArchiveError("Limit must be between 1 and 200")
        if offset < 0:
            raise OpenZimMcpArchiveError("Offset must be non-negative")
        if not namespace or len(namespace.strip()) == 0:
            raise OpenZimMcpArchiveError("Namespace must be a non-empty string")

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"browse_ns:{validated_path}:{namespace}:{limit}:{offset}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached namespace browse for: {namespace}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result = self._browse_namespace_entries(
                    archive, namespace, limit, offset
                )

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(
                f"Browsed namespace {namespace}: {limit} entries from offset {offset}"
            )
            return result

        except Exception as e:
            logger.error(f"Namespace browsing failed for {namespace}: {e}")
            raise OpenZimMcpArchiveError(f"Namespace browsing failed: {e}") from e

    def _browse_namespace_entries(
        self, archive: Archive, namespace: str, limit: int, offset: int
    ) -> str:
        """Browse entries in a specific namespace using sampling and search."""
        entries: List[Dict[str, Any]] = []

        # Check if archive uses new namespace scheme
        has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)

        # Discover entries in the namespace.
        namespace_entries, full_iteration = self._find_entries_in_namespace(
            archive, namespace, has_new_scheme
        )

        # Apply pagination
        total_in_namespace = len(namespace_entries)
        start_idx = offset
        end_idx = min(offset + limit, total_in_namespace)
        paginated_entries = namespace_entries[start_idx:end_idx]

        # Get detailed information for paginated entries
        for entry_path in paginated_entries:
            try:
                entry = archive.get_entry_by_path(entry_path)
                title = entry.title or entry_path

                # Try to get content preview for text entries
                preview = ""
                content_type = ""
                try:
                    item = entry.get_item()
                    content_type = item.mimetype or "unknown"

                    if item.mimetype and item.mimetype.startswith("text/"):
                        content = self.content_processor.process_mime_content(
                            bytes(item.content), item.mimetype
                        )
                        preview = self.content_processor.create_snippet(
                            content, max_paragraphs=1
                        )
                    else:
                        preview = f"({content_type} content)"

                except Exception as e:
                    logger.debug(f"Error getting preview for {entry_path}: {e}")
                    preview = "(Preview unavailable)"

                entries.append(
                    {
                        "path": entry_path,
                        "title": title,
                        "content_type": content_type,
                        "preview": preview,
                    }
                )

            except Exception as e:
                logger.warning(f"Error processing entry {entry_path}: {e}")
                continue

        # Build result with pagination cursor. Base has_more on the slice
        # bounds, not on len(entries) — entries can be shorter than the page
        # when individual entries fail to load, and we don't want to advertise
        # a non-existent next page in that case.
        has_more = end_idx < total_in_namespace
        next_cursor = None
        if has_more:
            next_cursor = PaginationCursor.create_next_cursor(
                offset, limit, total_in_namespace
            )

        # When the sample hits NAMESPACE_MAX_ENTRIES, total_in_namespace is a
        # sample-bound, not the true count. has_more=False just means the sample
        # is exhausted; the real namespace may be larger. Full iteration on
        # small archives produces an authoritative count.
        if full_iteration:
            results_may_be_incomplete = False
        else:
            results_may_be_incomplete = total_in_namespace >= NAMESPACE_MAX_ENTRIES

        result = {
            "namespace": namespace,
            "total_in_namespace": total_in_namespace,
            "offset": offset,
            "limit": limit,
            "returned_count": len(entries),
            "has_more": has_more,
            "next_cursor": next_cursor,
            "entries": entries,
            "sampling_based": not full_iteration,
            "discovery_method": "full_iteration" if full_iteration else "sampling",
            "is_total_authoritative": full_iteration,
            "results_may_be_incomplete": results_may_be_incomplete,
        }

        return json.dumps(result, indent=2, ensure_ascii=False)

    def _find_entries_in_namespace(
        self, archive: Archive, namespace: str, has_new_scheme: bool
    ) -> Tuple[List[str], bool]:
        """Find entries in a specific namespace.

        Returns ``(sorted_paths, full_iteration)`` where ``full_iteration`` is
        True when every entry in the archive was inspected (so the result is
        exhaustive). For larger archives, falls back to random sampling and
        returns False — counts/paths are then a lower bound.
        """
        namespace_entries: list[str] = []
        seen_entries: set[str] = set()
        total_entries = archive.entry_count

        # Full iteration is exhaustive and far more accurate than sampling for
        # small archives. The threshold mirrors _list_archive_namespaces.
        if total_entries <= NAMESPACE_MAX_SAMPLE_SIZE:
            logger.debug(
                f"Iterating all {total_entries} entries to enumerate namespace "
                f"'{namespace}'"
            )
            for entry_id in range(total_entries):
                try:
                    entry = archive._get_entry_by_id(entry_id)
                    path = entry.path
                    if path in seen_entries:
                        continue
                    seen_entries.add(path)
                    if (
                        self._extract_namespace_from_path(path, has_new_scheme)
                        == namespace
                    ):
                        namespace_entries.append(path)
                except Exception as e:
                    logger.debug(f"Error reading entry {entry_id}: {e}")
                    continue
            logger.info(
                f"Found {len(namespace_entries)} entries in namespace '{namespace}' "
                f"via full iteration of {total_entries} entries"
            )
            return sorted(namespace_entries), True

        # Sampling fallback for large archives.
        max_samples = min(NAMESPACE_MAX_SAMPLE_SIZE * 2, total_entries)
        sample_attempts = 0
        max_attempts = max_samples * NAMESPACE_SAMPLE_ATTEMPTS_MULTIPLIER

        logger.debug(f"Sampling for entries in namespace '{namespace}'")

        while (
            len(namespace_entries) < NAMESPACE_MAX_ENTRIES
            and sample_attempts < max_attempts
        ):
            sample_attempts += 1
            try:
                entry = archive.get_random_entry()
                path = entry.path

                if path in seen_entries:
                    continue
                seen_entries.add(path)

                if self._extract_namespace_from_path(path, has_new_scheme) == namespace:
                    namespace_entries.append(path)

            except Exception as e:
                logger.debug(f"Error sampling entry: {e}")
                continue

        # Strategy 2: Try common path patterns for the namespace. The pattern
        # list contains both namespace-prefixed paths (e.g. "C/index.html")
        # and bare paths (e.g. "index.html"); the latter live in *some other*
        # namespace, so we must verify membership before appending.
        common_patterns = self._get_common_namespace_patterns(namespace)
        for pattern in common_patterns:
            try:
                if (
                    archive.has_entry_by_path(pattern)
                    and pattern not in seen_entries
                    and self._extract_namespace_from_path(pattern, has_new_scheme)
                    == namespace
                ):
                    namespace_entries.append(pattern)
                    seen_entries.add(pattern)
            except Exception as e:
                logger.debug(f"Error checking pattern {pattern}: {e}")
                continue

        logger.info(
            f"Found {len(namespace_entries)} entries in namespace '{namespace}' "
            f"after {sample_attempts} samples"
        )
        return sorted(namespace_entries), False

    def _get_common_namespace_patterns(self, namespace: str) -> List[str]:
        """Get common path patterns for a namespace."""
        patterns = []

        # Common patterns based on namespace
        if namespace == "C":
            patterns.extend(
                [
                    "index.html",
                    "main.html",
                    "home.html",
                    "C/index.html",
                    "C/main.html",
                    "content/index.html",
                ]
            )
        elif namespace == "M":
            patterns.extend(
                [
                    "M/Title",
                    "M/Description",
                    "M/Language",
                    "M/Creator",
                    "metadata/title",
                    "metadata/description",
                ]
            )
        elif namespace == "W":
            patterns.extend(
                [
                    "W/mainPage",
                    "W/favicon",
                    "W/navigation",
                    "wellknown/mainPage",
                    "wellknown/favicon",
                ]
            )
        elif namespace == "X":
            patterns.extend(
                ["X/fulltext", "X/title", "X/search", "search/fulltext", "index/title"]
            )
        elif namespace == "A":
            patterns.extend(["A/index.html", "A/main.html", "A/home.html"])
        elif namespace == "I":
            patterns.extend(["I/favicon.png", "I/logo.png", "I/image.jpg"])

        return patterns

    def search_with_filters(
        self,
        zim_file_path: str,
        query: str,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> str:
        """Search within ZIM file content with namespace and content type filters.

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query term
            namespace: Optional namespace filter (C, M, W, X, etc.)
            content_type: Optional content type filter (text/html, text/plain, etc.)
            limit: Maximum number of results to return
            offset: Result starting offset (for pagination)

        Returns:
            Search result text

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If search operation fails
        """
        if limit is None:
            limit = self.config.content.default_search_limit

        # Validate parameters
        if limit < 1 or limit > 100:
            raise OpenZimMcpArchiveError("Limit must be between 1 and 100")
        if offset < 0:
            raise OpenZimMcpArchiveError("Offset must be non-negative")
        # Validate namespace - single chars (old) or longer names (new format)
        if namespace and (len(namespace) > 50 or not namespace.strip()):
            raise OpenZimMcpArchiveError(
                "Namespace must be a non-empty string (max 50 characters)"
            )

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = (
            f"search_filtered:{validated_path}:{query}:{namespace}:"
            f"{content_type}:{limit}:{offset}"
        )
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached filtered search results for query: {query}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result, total_filtered = self._perform_filtered_search(
                    archive, query, namespace, content_type, limit, offset
                )

            # Don't cache zero-result responses: libzim's lazy index warm-up
            # can return 0 matches transiently, and a TTL-cached "no results"
            # would mask the index becoming ready.
            if total_filtered > 0:
                self.cache.set(cache_key, result)
            logger.info(
                f"Filtered search completed: query='{query}', "
                f"namespace={namespace}, type={content_type}"
            )
            return result

        except Exception as e:
            logger.error(f"Filtered search failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(
                f"Filtered search operation failed: {e}"
            ) from e

    def _perform_filtered_search(
        self,
        archive: Archive,
        query: str,
        namespace: Optional[str],
        content_type: Optional[str],
        limit: int,
        offset: int,
    ) -> Tuple[str, int]:
        """Perform filtered search operation.

        Returns:
            (result_text, total_filtered) — caller uses total_filtered to decide
            whether the response is safe to cache. ``total_filtered`` is 0 for
            both the unfiltered no-results and the post-filter no-matches cases.
        """
        # Create searcher and execute search
        query_obj = Query().set_query(query)
        searcher = Searcher(archive)
        search = searcher.search(query_obj)

        # Get total results
        total_results = search.getEstimatedMatches()

        if total_results == 0:
            return f'No search results found for "{query}"', 0

        # Stream raw results in batches and filter as we go, stopping once
        # we have enough filtered matches to satisfy offset+limit or we
        # exceed a generous scan cap. This avoids the previous "first 1000
        # hits" cliff where a rare filter (e.g. image/png on an HTML corpus)
        # returned 0 even when matches existed deeper in the result list.
        BATCH_SIZE = 500
        MAX_SCAN = 10000  # bound memory and CPU for pathological queries
        target_filtered = offset + limit
        filtered_results: List[Tuple[str, Any, str, str]] = []
        scanned = 0
        scan_cap_hit = False

        while scanned < total_results and len(filtered_results) < target_filtered:
            if scanned >= MAX_SCAN:
                scan_cap_hit = True
                break
            batch_end = min(scanned + BATCH_SIZE, total_results, MAX_SCAN)
            batch = list(search.getResults(scanned, batch_end - scanned))
            scanned = batch_end
            if not batch:
                break

            for entry_id in batch:
                try:
                    entry = archive.get_entry_by_path(entry_id)

                    entry_namespace = ""
                    if "/" in entry.path:
                        entry_namespace = entry.path.split("/", 1)[0]
                    elif entry.path:
                        entry_namespace = entry.path[0]

                    if namespace and entry_namespace != namespace:
                        continue

                    content_mime = ""
                    if content_type:
                        try:
                            content_mime = entry.get_item().mimetype or ""
                            if not content_mime.startswith(content_type):
                                continue
                        except Exception:  # nosec B112 - intentional filter skip
                            continue

                    filtered_results.append(
                        (entry_id, entry, entry_namespace, content_mime)
                    )

                except Exception as e:
                    logger.warning(f"Error filtering search result {entry_id}: {e}")
                    continue

        # Preserve the legacy "results_capped" semantics for the message —
        # true if there are more raw results we haven't scanned.
        results_capped = scan_cap_hit or scanned < total_results
        raw_fetch_limit = scanned  # what we actually scanned
        total_filtered = len(filtered_results)

        filters_applied = []
        if namespace:
            filters_applied.append(f"namespace={namespace}")
        if content_type:
            filters_applied.append(f"content_type={content_type}")
        filter_text = (
            f" (filters: {', '.join(filters_applied)})" if filters_applied else ""
        )

        if total_filtered == 0:
            return f'No filtered matches for "{query}"{filter_text}', 0

        if offset >= total_filtered:
            return (
                f'Found {total_filtered} filtered matches for "{query}"{filter_text}, '
                f"but offset {offset} exceeds total results."
            ), total_filtered

        paginated_results = filtered_results[offset : offset + limit]

        # Collect detailed results, reusing the entries already fetched above.
        results = []
        for i, (entry_id, entry, entry_namespace, content_mime) in enumerate(
            paginated_results
        ):
            try:
                title = entry.title or "Untitled"
                snippet = self._get_entry_snippet(entry)

                # When content_type wasn't filtered, mimetype hasn't been read yet.
                if not content_type:
                    try:
                        content_mime = entry.get_item().mimetype or ""
                    except Exception as e:
                        logger.debug(
                            f"Could not get mimetype for entry {entry_id}: {e}"
                        )

                results.append(
                    {
                        "path": entry_id,
                        "title": title,
                        "snippet": snippet,
                        "namespace": entry_namespace,
                        "content_type": content_mime,
                    }
                )
            except Exception as e:
                logger.warning(
                    f"Error processing filtered search result {entry_id}: {e}"
                )
                results.append(
                    {
                        "path": entry_id,
                        "title": f"Entry {offset + i + 1}",
                        "snippet": f"(Error getting entry details: {e})",
                        "namespace": "unknown",
                        "content_type": "unknown",
                    }
                )

        capped_note = (
            f" (filtered from first {raw_fetch_limit} of "
            f"~{total_results} unfiltered hits)"
            if results_capped
            else ""
        )
        result_text = (
            f'Found {total_filtered} filtered matches for "{query}"{filter_text}, '
            f"showing {offset + 1}-{offset + len(results)}{capped_note}:\n\n"
        )

        for i, result in enumerate(results):
            result_text += f"## {offset + i + 1}. {result['title']}\n"
            result_text += f"Path: {result['path']}\n"
            result_text += f"Namespace: {result['namespace']}\n"
            result_text += f"Content Type: {result['content_type']}\n"
            result_text += f"Snippet: {result['snippet']}\n\n"

        # Pagination footer — mirrors _perform_search so callers have a
        # consistent way to detect and navigate additional pages.
        has_more = (offset + len(results)) < total_filtered
        result_text += "---\n"
        result_text += (
            f"**Pagination**: Showing {offset + 1}-{offset + len(results)} "
            f"of {total_filtered}\n"
        )
        if has_more:
            next_cursor = PaginationCursor.create_next_cursor(
                offset, limit, total_filtered, query
            )
            result_text += f"**Next cursor**: `{next_cursor}`\n"
            result_text += (
                f"**Hint**: Use offset={offset + limit} to get the next page\n"
            )
        else:
            result_text += "**End of results**\n"

        return result_text, total_filtered

    def get_search_suggestions(
        self, zim_file_path: str, partial_query: str, limit: int = 10
    ) -> str:
        """Get search suggestions and auto-complete for partial queries.

        Args:
            zim_file_path: Path to the ZIM file
            partial_query: Partial search query
            limit: Maximum number of suggestions to return

        Returns:
            JSON string containing search suggestions

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If suggestion generation fails
        """
        # Validate parameters
        if limit < 1 or limit > 50:
            raise OpenZimMcpArchiveError("Limit must be between 1 and 50")
        if not partial_query or len(partial_query.strip()) < 2:
            return json.dumps(
                {"suggestions": [], "message": "Query too short for suggestions"}
            )

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"suggestions:{validated_path}:{partial_query}:{limit}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached suggestions for: {partial_query}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result = self._generate_search_suggestions(
                    archive, partial_query, limit
                )

            # Cache the result
            self.cache.set(cache_key, result)
            # Parse result to get actual count for accurate logging
            try:
                result_data = json.loads(result)
                actual_count = result_data.get(
                    "count", len(result_data.get("suggestions", []))
                )
            except (json.JSONDecodeError, TypeError):
                actual_count = "unknown"
            logger.info(f"Generated {actual_count} suggestions for: {partial_query}")
            return result

        except Exception as e:
            logger.error(f"Suggestion generation failed for {partial_query}: {e}")
            raise OpenZimMcpArchiveError(f"Suggestion generation failed: {e}") from e

    def _generate_search_suggestions(
        self, archive: Archive, partial_query: str, limit: int
    ) -> str:
        """Generate search suggestions based on partial query.

        Errors during iteration of individual entries are logged and skipped
        (per-entry isolation). Errors that escape the per-entry try/except
        propagate so callers can avoid caching a sentinel response — a
        transient libzim failure in this path was previously locked into the
        suggestions cache for the full TTL.
        """
        logger.info(
            f"Starting suggestion generation for query: '{partial_query}', "
            f"limit: {limit}"
        )
        suggestions = []
        partial_lower = partial_query.lower().strip()

        # Strategy 1: Use search functionality as fallback since direct entry
        # iteration may not work reliably with all ZIM file structures.
        suggestions = self._get_suggestions_from_search(archive, partial_query, limit)

        if suggestions:
            logger.info(f"Found {len(suggestions)} suggestions using search fallback")
            result = {
                "partial_query": partial_query,
                "suggestions": suggestions,
                "count": len(suggestions),
            }
            return json.dumps(result, indent=2, ensure_ascii=False)

        # Strategy 2: Try direct entry iteration (original approach but improved)
        title_matches: List[Dict[str, Any]] = []

        # Sample a subset of entries to avoid performance issues
        sample_size = min(archive.entry_count, 5000)
        step = max(1, archive.entry_count // sample_size)

        logger.info(
            f"Archive info: entry_count={archive.entry_count}, "
            f"sample_size={sample_size}, step={step}"
        )

        entries_processed = 0
        entries_with_content = 0

        for entry_id in range(0, archive.entry_count, step):
            try:
                entry = archive._get_entry_by_id(entry_id)
                title = entry.title or ""
                path = entry.path or ""

                entries_processed += 1

                # Log first few entries for debugging
                if entries_processed <= 5:
                    logger.debug(f"Entry {entry_id}: title='{title}', path='{path}'")

                # Skip entries without meaningful titles
                if not title.strip() or len(title.strip()) < 2:
                    continue

                # Skip system/metadata entries (common patterns)
                if (
                    path.startswith("M/")
                    or path.startswith("X/")
                    or path.startswith("-/")
                    or title.startswith("File:")
                    or title.startswith("Category:")
                    or title.startswith("Template:")
                ):
                    continue

                entries_with_content += 1

                title_lower = title.lower()

                # Prioritize titles that start with the query
                if title_lower.startswith(partial_lower):
                    title_matches.append(
                        {
                            "suggestion": title,
                            "path": path,
                            "type": "title_start_match",
                            "score": 100,
                        }
                    )
                    logger.debug(f"Found start match: '{title}'")
                # Then titles that contain the query
                elif partial_lower in title_lower:
                    title_matches.append(
                        {
                            "suggestion": title,
                            "path": path,
                            "type": "title_contains_match",
                            "score": 50,
                        }
                    )
                    logger.debug(f"Found contains match: '{title}'")

                # Stop if we have enough matches
                if len(title_matches) >= limit * 2:
                    logger.info(
                        f"Found enough matches ({len(title_matches)}), "
                        "stopping search"
                    )
                    break

            except Exception as e:
                logger.warning(
                    f"Error processing entry {entry_id} for suggestions: {e}"
                )
                continue

        logger.info(
            f"Processing complete: processed={entries_processed}, "
            f"with_content={entries_with_content}, matches={len(title_matches)}"
        )

        # Sort by score and title length (prefer shorter, more relevant titles)
        title_matches.sort(key=lambda x: (-x["score"], len(x["suggestion"])))

        # Take the best matches
        for match in title_matches[:limit]:
            suggestions.append(
                {
                    "text": match["suggestion"],
                    "path": match["path"],
                    "type": match["type"],
                }
            )

        result = {
            "partial_query": partial_query,
            "suggestions": suggestions[:limit],
            "count": len(suggestions[:limit]),
        }

        return json.dumps(result, indent=2, ensure_ascii=False)

    def _get_suggestions_from_search(
        self, archive: Archive, partial_query: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Get suggestions by using the search functionality as fallback."""
        suggestions: list[dict[str, str]] = []

        try:
            # Use the working search functionality to find relevant articles
            from libzim import Query, Searcher

            # Create a search query - try both exact and wildcard approaches
            query_obj = Query().set_query(partial_query)
            searcher = Searcher(archive)
            search = searcher.search(query_obj)

            total_results = search.getEstimatedMatches()
            logger.debug(f"Search found {total_results} matches for '{partial_query}'")

            if total_results == 0:
                return suggestions

            # Get a reasonable number of search results to extract titles from
            # Get more results to filter from
            max_results = min(total_results, limit * 5)
            result_entries = list(search.getResults(0, max_results))

            seen_titles = set()

            for entry_id in result_entries:
                try:
                    entry = archive.get_entry_by_path(entry_id)
                    title = entry.title or ""
                    path = entry.path or ""

                    if not title.strip() or title in seen_titles:
                        continue

                    # Skip system/metadata entries
                    if (
                        title.startswith("File:")
                        or title.startswith("Category:")
                        or title.startswith("Template:")
                        or title.startswith("User:")
                        or title.startswith("Wikipedia:")
                        or title.startswith("Help:")
                    ):
                        continue

                    seen_titles.add(title)
                    title_lower = title.lower()
                    partial_lower = partial_query.lower()

                    # Prioritize titles that start with the query
                    if title_lower.startswith(partial_lower):
                        suggestions.append(
                            {"text": title, "path": path, "type": "search_start_match"}
                        )
                    # Then titles that contain the query
                    elif partial_lower in title_lower:
                        suggestions.append(
                            {
                                "text": title,
                                "path": path,
                                "type": "search_contains_match",
                            }
                        )

                    # Stop when we have enough suggestions
                    if len(suggestions) >= limit:
                        break

                except Exception as e:
                    logger.warning(f"Error processing search result {entry_id}: {e}")
                    continue

            # Sort suggestions to prioritize better matches
            suggestions.sort(
                key=lambda x: (
                    (
                        0 if x["type"] == "search_start_match" else 1
                    ),  # Start matches first
                    len(x["text"]),  # Shorter titles first
                )
            )

            return suggestions[:limit]

        except Exception as e:
            logger.error(f"Error in search-based suggestions: {e}")
            return []

    def get_article_structure(self, zim_file_path: str, entry_path: str) -> str:
        """Extract article structure including headings, sections, and key metadata.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'

        Returns:
            JSON string containing article structure

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If structure extraction fails
        """
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"structure:{validated_path}:{entry_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached structure for: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result = self._extract_article_structure(archive, entry_path)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(f"Extracted structure for: {entry_path}")
            return result

        except Exception as e:
            logger.error(f"Structure extraction failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Structure extraction failed: {e}") from e

    def _extract_article_structure(self, archive: Archive, entry_path: str) -> str:
        """Extract structure from article content."""
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
            if mime_type.startswith("text/html"):
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

            return json.dumps(structure, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Error extracting structure for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(
                f"Failed to extract article structure: {e}"
            ) from e

    def extract_article_links(self, zim_file_path: str, entry_path: str) -> str:
        """Extract internal and external links from an article.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'

        Returns:
            JSON string containing extracted links

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If link extraction fails
        """
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"links:{validated_path}:{entry_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached links for: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result = self._extract_article_links(archive, entry_path)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(f"Extracted links for: {entry_path}")
            return result

        except Exception as e:
            logger.error(f"Link extraction failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Link extraction failed: {e}") from e

    def _extract_article_links(self, archive: Archive, entry_path: str) -> str:
        """Extract links from article content."""
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
            if mime_type.startswith("text/html"):
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

            return json.dumps(links_data, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Error extracting links for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Failed to extract article links: {e}") from e

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
        from .constants import DEFAULT_MAX_BINARY_SIZE

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
            with zim_archive(validated_path) as archive:
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
        if cached_result:
            logger.debug(f"Returning cached summary for: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result = self._extract_entry_summary(archive, entry_path, max_words)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(f"Extracted summary for: {entry_path}")
            return result

        except Exception as e:
            logger.error(f"Summary extraction failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Summary extraction failed: {e}") from e

    def _resolve_entry_with_fallback(
        self, archive: Archive, entry_path: str
    ) -> Tuple[Any, str]:
        """Resolve an entry by direct path, falling back to search.

        Returns (entry, resolved_path). Raises OpenZimMcpArchiveError cleanly
        (without an implicit __context__ chain to a transient direct-access
        error) if neither direct access nor search yields a result.
        """
        # Suppress the transient direct-access error chain so callers see a
        # clean "not found" message rather than a chained exception with the
        # underlying archive error as context.
        with suppress(Exception):
            return archive.get_entry_by_path(entry_path), entry_path
        actual_path = self._find_entry_by_search(archive, entry_path)
        if actual_path:
            return archive.get_entry_by_path(actual_path), actual_path
        raise OpenZimMcpArchiveError(
            f"Entry not found: '{entry_path}'. "
            f"Try using search_zim_file() to find available entries."
        ) from None

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
        if cached_result:
            logger.debug(f"Returning cached TOC for: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result = self._extract_table_of_contents(archive, entry_path)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(f"Extracted TOC for: {entry_path}")
            return result

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

            if not mime_type.startswith("text/html"):
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
        from .content_processor import resolve_heading_id

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

    # ------------------------------------------------------------------
    # Convenience tools: walk_namespace, search_all
    # ------------------------------------------------------------------

    def walk_namespace(
        self,
        zim_file_path: str,
        namespace: str,
        cursor: int = 0,
        limit: int = 200,
    ) -> str:
        """Walk every entry in a namespace by entry ID, with cursor pagination.

        Unlike browse_namespace (which samples), this iterates the archive
        deterministically from ``cursor`` onward and returns up to ``limit``
        entries that belong to the requested namespace. Pair the returned
        ``next_cursor`` with a follow-up call to walk the rest. Set to None
        when iteration is complete.

        Args:
            zim_file_path: Path to the ZIM file
            namespace: Namespace to walk (C, M, W, X, A, I, etc.)
            cursor: Entry ID to resume from (default 0; use the value from
                ``next_cursor`` of the previous call)
            limit: Maximum entries to return per page (1–500, default 200)

        Returns:
            JSON containing entries in the namespace, the next cursor, and
            ``done: true`` if iteration finished
        """
        if limit < 1 or limit > 500:
            return (
                "**Parameter Validation Error**\n\n"
                f"**Issue**: limit must be between 1 and 500 (provided: {limit})\n"
                "**Example**: Use `limit=200` for a typical page."
            )
        if cursor < 0:
            cursor = 0

        validated = self.path_validator.validate_path(zim_file_path)
        validated = self.path_validator.validate_zim_file(validated)

        try:
            with zim_archive(validated) as archive:
                total = archive.entry_count
                has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)
                entries: List[Dict[str, Any]] = []
                entry_id = cursor
                while entry_id < total and len(entries) < limit:
                    try:
                        entry = archive._get_entry_by_id(entry_id)
                        path = entry.path
                        if (
                            self._extract_namespace_from_path(path, has_new_scheme)
                            == namespace
                        ):
                            entries.append(
                                {
                                    "path": path,
                                    "title": entry.title or path,
                                }
                            )
                    except Exception as e:
                        logger.debug(f"walk_namespace: entry {entry_id} skipped: {e}")
                    entry_id += 1

                done = entry_id >= total
                next_cursor = None if done else entry_id
                # scanned_through_id reflects the last ID we examined regardless
                # of whether it matched the filter. None if we never entered the
                # loop (cursor was already past the end).
                scanned_through_id = entry_id - 1 if entry_id > cursor else None
                result = {
                    "namespace": namespace,
                    "cursor": cursor,
                    "limit": limit,
                    "returned_count": len(entries),
                    "scanned_count": entry_id - cursor,
                    "next_cursor": next_cursor,
                    "done": done,
                    "scanned_through_id": scanned_through_id,
                    "total_entries": total,
                    "entries": entries,
                }
                return json.dumps(result, indent=2, ensure_ascii=False)
        except OpenZimMcpArchiveError:
            raise
        except Exception as e:
            raise OpenZimMcpArchiveError(f"walk_namespace failed: {e}") from e

    def search_all(
        self,
        query: str,
        limit_per_file: int = 5,
    ) -> str:
        """Search every ZIM file in allowed directories and return merged results.

        Useful when the model doesn't know which ZIM file holds the
        information it needs. Skips files that can't be searched (corrupt,
        no full-text index) without aborting the rest.

        Args:
            query: Search query
            limit_per_file: Maximum hits to return per ZIM file (1–50, default 5)

        Returns:
            JSON with per-file result groups and a flat ``hits`` list sorted
            by file then rank
        """
        if not query or not query.strip():
            raise OpenZimMcpValidationError(
                "Input is empty or contains only whitespace/control characters"
            )
        if limit_per_file < 1 or limit_per_file > 50:
            return (
                "**Parameter Validation Error**\n\n"
                f"**Issue**: limit_per_file must be between 1 and 50 "
                f"(provided: {limit_per_file})"
            )

        files = self.list_zim_files_data()
        per_file: List[Dict[str, Any]] = []
        for file_info in files:
            path = file_info.get("path")
            if not path:
                continue
            try:
                result_text = self.search_zim_file(path, query, limit_per_file, 0)
                # Real result text begins with "Found N matches..." while
                # empty results begin with "No search results found...". We
                # can't filter on `**` because real search snippets contain
                # bold markdown for emphasis. Match on the leading prefix.
                stripped = result_text.lstrip()
                has_hits = stripped.startswith("Found ")
                per_file.append(
                    {
                        "zim_file_path": path,
                        "name": file_info.get("name"),
                        "result": result_text,
                        "has_hits": has_hits,
                    }
                )
            except Exception as e:
                logger.debug(f"search_all: skipped {path}: {e}")
                per_file.append(
                    {
                        "zim_file_path": path,
                        "name": file_info.get("name"),
                        "error": str(e),
                    }
                )

        return json.dumps(
            {
                "query": query,
                "files_searched": len(files),
                "files_with_hits": sum(1 for r in per_file if r.get("has_hits")),
                "files_searched_successfully": sum(
                    1 for r in per_file if "result" in r
                ),
                "files_failed": sum(1 for r in per_file if "error" in r),
                "per_file": per_file,
            },
            indent=2,
            ensure_ascii=False,
        )

    def find_entry_by_title(
        self,
        zim_file_path: str,
        title: str,
        cross_file: bool = False,
        limit: int = 10,
    ) -> str:
        """Resolve a title or partial title to one or more entry paths.

        Implementation order:
          1. Direct path probe in C/ namespace for normalized title (fast path).
          2. libzim suggestion search (title-indexed) — primary fallback.
          3. Return ranked list with score.
        """
        if not title or not title.strip():
            raise OpenZimMcpValidationError(
                "Input is empty or contains only whitespace/control characters"
            )
        if limit < 1 or limit > 50:
            return (
                "**Parameter Validation Error**\n\n"
                f"**Issue**: limit must be between 1 and 50 (provided: {limit})"
            )

        if cross_file:
            files = [f["path"] for f in self.list_zim_files_data() if f.get("path")]
        else:
            validated = self.path_validator.validate_path(zim_file_path)
            validated = self.path_validator.validate_zim_file(validated)
            files = [str(validated)]

        aggregate_results: List[Dict[str, Any]] = []
        fast_path_hit = False

        for file_path in files:
            try:
                with zim_archive(file_path) as archive:
                    # Fast path: C/<normalized_title>
                    normalized = title.replace(" ", "_")
                    candidate = f"C/{normalized}"
                    if archive.has_entry_by_path(candidate):
                        try:
                            entry = archive.get_entry_by_path(candidate)
                            aggregate_results.append(
                                {
                                    "path": entry.path,
                                    "title": entry.title or candidate,
                                    "score": 1.0,
                                    "zim_file": file_path,
                                }
                            )
                            fast_path_hit = True
                            if not cross_file:
                                break
                            continue
                        except Exception as e:
                            logger.debug(
                                f"find_entry_by_title fast-path read failed: {e}"
                            )

                    # Fallback: libzim suggestion search (title-indexed).
                    # Note: ``Archive.suggest()`` does not exist; the public
                    # API is ``SuggestionSearcher(archive).suggest(text)``.
                    try:
                        suggestion_search = SuggestionSearcher(archive).suggest(title)
                        total = suggestion_search.getEstimatedMatches()
                        if total > 0:
                            for path in suggestion_search.getResults(0, limit):
                                try:
                                    entry = archive.get_entry_by_path(path)
                                    aggregate_results.append(
                                        {
                                            "path": entry.path,
                                            "title": entry.title or path,
                                            "score": 0.8,
                                            "zim_file": file_path,
                                        }
                                    )
                                except Exception as e:
                                    logger.debug(
                                        f"find_entry_by_title suggestion read "
                                        f"failed for {path}: {e}"
                                    )
                    except Exception as e:
                        if not cross_file:
                            raise
                        logger.debug(
                            f"find_entry_by_title suggest() failed for "
                            f"{file_path}: {e}"
                        )
            except Exception as e:
                if not cross_file:
                    raise
                logger.debug(f"find_entry_by_title: skipped {file_path}: {e}")

        return json.dumps(
            {
                "query": title,
                "results": aggregate_results[:limit],
                "fast_path_hit": fast_path_hit,
                "files_searched": len(files),
            },
            indent=2,
            ensure_ascii=False,
        )

    def get_related_articles(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 10,
    ) -> str:
        """Find articles related to entry_path via outbound links."""
        if limit < 1 or limit > 100:
            return (
                "**Parameter Validation Error**\n\n"
                f"**Issue**: limit must be between 1 and 100 (provided: {limit})"
            )

        result: Dict[str, Any] = {"entry_path": entry_path}

        try:
            links_json = self.extract_article_links(zim_file_path, entry_path)
            links_data = json.loads(links_json)
            seen: set[str] = set()
            outbound: List[Dict[str, Any]] = []
            for link in links_data.get("internal_links", []):
                target = self._resolve_link_to_entry_path(
                    link.get("url", ""), entry_path
                )
                if not target or target in seen or target == entry_path:
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
        return resolved
