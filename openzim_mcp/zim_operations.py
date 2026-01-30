"""ZIM file operations with proper resource management."""

import base64
import json
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from libzim.reader import Archive  # type: ignore[import-untyped]
from libzim.search import Query, Searcher  # type: ignore[import-untyped]

from .cache import OpenZimMcpCache
from .config import OpenZimMcpConfig
from .constants import (
    DEFAULT_MAIN_PAGE_TRUNCATION,
    NAMESPACE_MAX_ENTRIES,
    NAMESPACE_MAX_SAMPLE_SIZE,
    NAMESPACE_SAMPLE_ATTEMPTS_MULTIPLIER,
)
from .content_processor import ContentProcessor
from .exceptions import ArchiveOpenTimeoutError, OpenZimMcpArchiveError
from .security import PathValidator
from .timeout_utils import run_with_timeout

# Timeout for opening ZIM archives (seconds)
ARCHIVE_OPEN_TIMEOUT = 30.0


class PaginationCursor:
    """Utility class for creating and parsing pagination cursors.

    Cursors encode pagination state as base64 tokens, making it easy for
    clients to continue from where they left off without tracking offset manually.
    """

    @staticmethod
    def encode(offset: int, limit: int, query: Optional[str] = None) -> str:
        """Encode pagination state into a cursor token.

        Args:
            offset: Current offset position
            limit: Page size
            query: Optional query string for search cursors

        Returns:
            Base64-encoded cursor string
        """
        cursor_data: Dict[str, Any] = {"o": offset, "l": limit}
        if query:
            cursor_data["q"] = query
        json_str = json.dumps(cursor_data, separators=(",", ":"))
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    @staticmethod
    def decode(cursor: str) -> Dict[str, Any]:
        """Decode a cursor token back to pagination state.

        Args:
            cursor: Base64-encoded cursor string

        Returns:
            Dictionary with offset, limit, and optional query

        Raises:
            ValueError: If cursor is invalid
        """
        try:
            json_str = base64.urlsafe_b64decode(cursor.encode()).decode()
            data = json.loads(json_str)
            return {
                "offset": data.get("o", 0),
                "limit": data.get("l", 10),
                "query": data.get("q"),
            }
        except Exception as e:
            raise ValueError(f"Invalid pagination cursor: {e}") from e

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
        return PaginationCursor.encode(next_offset, limit, query)


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
    archive: Optional[Archive] = None
    try:
        # Use timeout to prevent hanging on corrupted or locked files
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

        logger.debug(f"Opened ZIM archive: {file_path}")
        yield archive
    except OpenZimMcpArchiveError:
        # Re-raise our custom errors as-is
        raise
    except Exception as e:
        raise OpenZimMcpArchiveError(f"Failed to open ZIM archive: {file_path}") from e
    finally:
        if archive is not None:
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

    def list_zim_files_data(self) -> List[Dict[str, Any]]:
        """List all ZIM files in allowed directories as structured data.

        Returns:
            List of dictionaries containing ZIM file information.
            Each dict has: name, path, directory, size, size_bytes, modified
        """
        cache_key = "zim_files_list_data"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug("Returning cached ZIM files list data")
            return cached_result  # type: ignore[no-any-return]

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
                    if file_path.is_file():
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
                            logger.warning(
                                f"Error reading file stats for {file_path}: {e}"
                            )

            except Exception as e:
                logger.error(f"Error processing directory {directory}: {e}")

        # Cache the result
        self.cache.set(cache_key, all_zim_files)
        logger.info(f"Listed {len(all_zim_files)} ZIM files")
        return all_zim_files

    def list_zim_files(self) -> str:
        """List all ZIM files in allowed directories.

        Returns:
            JSON string containing the list of ZIM files
        """
        cache_key = "zim_files_list"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug("Returning cached ZIM files list")
            return cached_result  # type: ignore[no-any-return]

        # Get structured data
        all_zim_files = self.list_zim_files_data()

        if not all_zim_files:
            result = "No ZIM files found in allowed directories"
        else:
            result_text = (
                f"Found {len(all_zim_files)} ZIM files in "
                f"{len(self.config.allowed_directories)} directories:\n\n"
            )
            result_text += json.dumps(all_zim_files, indent=2, ensure_ascii=False)
            result = result_text

        # Cache the result
        self.cache.set(cache_key, result)
        return result

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
                result = self._perform_search(archive, query, limit, offset)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.debug(f"Search completed: query='{query}', results found")
            return result

        except Exception as e:
            logger.error(f"Search failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Search operation failed: {e}") from e

    def _perform_search(
        self, archive: Archive, query: str, limit: int, offset: int
    ) -> str:
        """Perform the actual search operation."""
        # Create searcher and execute search
        query_obj = Query().set_query(query)
        searcher = Searcher(archive)
        search = searcher.search(query_obj)

        # Get total results
        total_results = search.getEstimatedMatches()

        if total_results == 0:
            return f'No search results found for "{query}"'

        # Guard against offset exceeding total results (would produce negative count)
        if offset >= total_results:
            return (
                f'Found {total_results} matches for "{query}", '
                f"but offset {offset} exceeds total results."
            )

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
                f"**Hint**: Use offset={offset + limit} to get the next page\n"
            )
        else:
            result_text += "**End of results**\n"

        return result_text

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

        Returns:
            Entry content text with metadata including actual path used

        Raises:
            OpenZimMcpArchiveError: If entry cannot be found via direct access or search

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If entry retrieval fails
        """
        if max_content_length is None:
            max_content_length = self.config.content.max_content_length

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"entry:{validated_path}:{entry_path}:{max_content_length}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Returning cached entry: {entry_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result = self._get_entry_content(
                    archive, entry_path, max_content_length
                )

            # Cache the result
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

    def _get_entry_content(
        self, archive: Archive, entry_path: str, max_content_length: int
    ) -> str:
        """Get the actual entry content with smart retrieval.

        Implements smart retrieval logic:
        1. Try direct entry access first
        2. If direct access fails, fall back to search-based retrieval
        3. Cache successful path mappings for future use
        """
        # Check path mapping cache first
        cache_key = f"path_mapping:{entry_path}"
        cached_actual_path = self.cache.get(cache_key)
        if cached_actual_path:
            logger.debug(
                f"Using cached path mapping: {entry_path} -> {cached_actual_path}"
            )
            try:
                return self._get_entry_content_direct(
                    archive, cached_actual_path, entry_path, max_content_length
                )
            except Exception as e:
                logger.warning(f"Cached path mapping failed: {e}")
                # Clear invalid cache entry and continue with smart retrieval
                self.cache.delete(cache_key)

        # Try direct access first
        try:
            logger.debug(f"Attempting direct entry access: {entry_path}")
            result = self._get_entry_content_direct(
                archive, entry_path, entry_path, max_content_length
            )
            # Cache successful direct access
            self.cache.set(cache_key, entry_path)
            return result
        except Exception as direct_error:
            logger.debug(f"Direct entry access failed for {entry_path}: {direct_error}")

            # Fall back to search-based retrieval
            try:
                logger.info(f"Falling back to search-based retrieval for: {entry_path}")
                actual_path = self._find_entry_by_search(archive, entry_path)
                if actual_path:
                    result = self._get_entry_content_direct(
                        archive, actual_path, entry_path, max_content_length
                    )
                    # Cache successful path mapping
                    self.cache.set(cache_key, actual_path)
                    logger.info(
                        f"Smart retrieval successful: {entry_path} -> {actual_path}"
                    )
                    return result
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
    ) -> str:
        """Get entry content using the actual path from the ZIM file.

        Args:
            archive: ZIM archive instance
            actual_path: The actual path as it exists in the ZIM file
            requested_path: The originally requested path (for display)
            max_content_length: Maximum content length
        """
        entry = archive.get_entry_by_path(actual_path)
        title = entry.title or "Untitled"

        # Get content
        content = ""
        content_type = ""

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
        result_text += "## Content\n\n"
        result_text += content or "(No content)"

        return result_text

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
                result = self._get_main_page_content(archive)

            # Cache the result
            self.cache.set(cache_key, result)
            logger.info(f"Retrieved main page for: {validated_path}")
            return result

        except Exception as e:
            logger.error(f"Main page retrieval failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Main page retrieval failed: {e}") from e

    def _get_main_page_content(self, archive: Archive) -> str:
        """Get main page content from archive."""
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

                    return result

                except Exception as e:
                    logger.warning(f"Error getting main page content: {e}")
                    return (
                        f"# Main Page\n\nPath: {path}\n\n"
                        f"(Error retrieving content: {e})"
                    )

            # Fallback: try common main page paths
            main_page_paths = ["W/mainPage", "A/Main_Page", "A/index", ""]

            for path in main_page_paths:
                try:
                    if path:
                        entry = archive.get_entry_by_path(path)
                    else:
                        # Try to get the first entry as fallback
                        if archive.entry_count > 0:
                            entry = archive.get_entry_by_id(0)
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

                            return result

                        except Exception as e:
                            logger.warning(f"Error getting content for {path}: {e}")
                            continue

                except Exception:  # nosec B112 - intentional fallback
                    # Path doesn't exist, try next
                    continue

            # No main page found
            return (
                "# Main Page\n\nNo main page found in this ZIM file.\n\n"
                "The archive may not have a designated main page entry."
            )

        except Exception as e:
            logger.error(f"Error getting main page: {e}")
            return f"# Main Page\n\nError retrieving main page: {e}"

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
        """List namespaces in the archive using sampling-based discovery."""
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

        # Check if archive uses new namespace scheme
        has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)
        logger.debug(f"Archive uses new namespace scheme: {has_new_scheme}")

        # Use sampling approach since direct iteration is not available
        sample_size = min(NAMESPACE_MAX_SAMPLE_SIZE, archive.entry_count)
        sampled_entries: set[str] = set()  # Track sampled paths to avoid duplicates
        max_sample_attempts = sample_size * NAMESPACE_SAMPLE_ATTEMPTS_MULTIPLIER

        logger.debug(
            f"Sampling {sample_size} entries from {archive.entry_count} total entries"
        )

        try:
            # Sample random entries to discover namespaces
            for _ in range(
                max_sample_attempts
            ):  # Try more samples to account for duplicates
                if len(sampled_entries) >= sample_size:
                    break

                try:
                    entry = archive.get_random_entry()
                    path = entry.path

                    # Skip if we've already sampled this entry
                    if path in sampled_entries:
                        continue
                    sampled_entries.add(path)

                    # Extract namespace based on ZIM format
                    namespace = self._extract_namespace_from_path(path, has_new_scheme)

                    if namespace not in namespaces:
                        namespaces[namespace] = {
                            "count": 0,
                            "description": namespace_descriptions.get(
                                namespace, f"Namespace '{namespace}'"
                            ),
                            "sample_entries": [],
                        }

                    namespaces[namespace]["count"] += 1

                    # Add sample entries (up to 5 per namespace for representation)
                    if len(namespaces[namespace]["sample_entries"]) < 5:
                        title = entry.title or path
                        namespaces[namespace]["sample_entries"].append(
                            {"path": path, "title": title}
                        )

                except Exception as e:
                    logger.debug(f"Error sampling entry: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error during namespace sampling: {e}")

        # Estimate total counts based on sampling ratio
        if sampled_entries:
            sampling_ratio = len(sampled_entries) / archive.entry_count
            for namespace_info in namespaces.values():
                # Estimate total count based on sampling
                estimated_count = int(namespace_info["count"] / sampling_ratio)
                namespace_info["estimated_total"] = estimated_count
                namespace_info["sampled_count"] = namespace_info["count"]
                namespace_info["count"] = estimated_count

        # Build result
        result = {
            "total_entries": archive.entry_count,
            "sampled_entries": len(sampled_entries),
            "has_new_namespace_scheme": has_new_scheme,
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

        # Use sampling approach to find entries in the namespace
        namespace_entries = self._find_entries_in_namespace(
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

        # Build result with pagination cursor
        has_more = total_in_namespace > offset + len(entries)
        next_cursor = None
        if has_more:
            next_cursor = PaginationCursor.create_next_cursor(
                offset, limit, total_in_namespace
            )

        result = {
            "namespace": namespace,
            "total_in_namespace": total_in_namespace,
            "offset": offset,
            "limit": limit,
            "returned_count": len(entries),
            "has_more": has_more,
            "next_cursor": next_cursor,
            "entries": entries,
            "sampling_based": True,
        }

        return json.dumps(result, indent=2, ensure_ascii=False)

    def _find_entries_in_namespace(
        self, archive: Archive, namespace: str, has_new_scheme: bool
    ) -> List[str]:
        """Find entries in a specific namespace using sampling and search strategies."""
        namespace_entries: list[str] = []
        seen_entries = set()

        # Strategy 1: Use random sampling to find entries
        # Use 2x the sample size for namespace browsing to improve coverage
        max_samples = min(NAMESPACE_MAX_SAMPLE_SIZE * 2, archive.entry_count)
        sample_attempts = 0
        max_attempts = max_samples * NAMESPACE_SAMPLE_ATTEMPTS_MULTIPLIER

        logger.debug(f"Searching for entries in namespace '{namespace}' using sampling")

        while (
            len(namespace_entries) < NAMESPACE_MAX_ENTRIES
            and sample_attempts < max_attempts
        ):
            sample_attempts += 1
            try:
                entry = archive.get_random_entry()
                path = entry.path

                # Skip duplicates
                if path in seen_entries:
                    continue
                seen_entries.add(path)

                # Check if entry belongs to target namespace
                entry_namespace = self._extract_namespace_from_path(
                    path, has_new_scheme
                )
                if entry_namespace == namespace:
                    namespace_entries.append(path)

            except Exception as e:
                logger.debug(f"Error sampling entry: {e}")
                continue

        # Strategy 2: Try common path patterns for the namespace
        common_patterns = self._get_common_namespace_patterns(namespace)
        for pattern in common_patterns:
            try:
                if archive.has_entry_by_path(pattern) and pattern not in seen_entries:
                    namespace_entries.append(pattern)
                    seen_entries.add(pattern)
            except Exception as e:
                logger.debug(f"Error checking pattern {pattern}: {e}")
                continue

        logger.info(
            f"Found {len(namespace_entries)} entries in namespace '{namespace}' "
            f"after {sample_attempts} samples"
        )
        return sorted(namespace_entries)  # Sort for consistent pagination

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
                result = self._perform_filtered_search(
                    archive, query, namespace, content_type, limit, offset
                )

            # Cache the result
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
    ) -> str:
        """Perform filtered search operation."""
        # Create searcher and execute search
        query_obj = Query().set_query(query)
        searcher = Searcher(archive)
        search = searcher.search(query_obj)

        # Get total results
        total_results = search.getEstimatedMatches()

        if total_results == 0:
            return f'No search results found for "{query}"'

        # Get all search results first, then filter
        all_results = list(
            search.getResults(0, min(total_results, 1000))
        )  # Limit to prevent memory issues

        # Filter results
        filtered_results = []
        for entry_id in all_results:
            try:
                entry = archive.get_entry_by_path(entry_id)

                # Apply namespace filter
                if namespace:
                    entry_namespace = ""
                    if "/" in entry.path:
                        entry_namespace = entry.path.split("/", 1)[0]
                    elif entry.path:
                        entry_namespace = entry.path[0]

                    if entry_namespace != namespace:
                        continue

                # Apply content type filter
                if content_type:
                    try:
                        item = entry.get_item()
                        if not item.mimetype or not item.mimetype.startswith(
                            content_type
                        ):
                            continue
                    except Exception:  # nosec B112 - intentional filter skip
                        continue

                filtered_results.append(entry_id)

            except Exception as e:
                logger.warning(f"Error filtering search result {entry_id}: {e}")
                continue

        # Apply pagination to filtered results
        total_filtered = len(filtered_results)
        paginated_results = filtered_results[offset : offset + limit]

        # Collect detailed results
        results = []
        for i, entry_id in enumerate(paginated_results):
            try:
                entry = archive.get_entry_by_path(entry_id)
                title = entry.title or "Untitled"

                # Get content snippet
                snippet = self._get_entry_snippet(entry)

                # Get additional metadata
                entry_namespace = ""
                if "/" in entry.path:
                    entry_namespace = entry.path.split("/", 1)[0]
                elif entry.path:
                    entry_namespace = entry.path[0]

                content_mime = ""
                try:
                    item = entry.get_item()
                    content_mime = item.mimetype or ""
                except Exception as e:
                    logger.debug(f"Could not get mimetype for entry {entry_id}: {e}")

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

        # Build result text
        filters_applied = []
        if namespace:
            filters_applied.append(f"namespace={namespace}")
        if content_type:
            filters_applied.append(f"content_type={content_type}")

        filter_text = (
            f" (filters: {', '.join(filters_applied)})" if filters_applied else ""
        )

        result_text = (
            f'Found {total_filtered} filtered matches for "{query}"{filter_text}, '
            f"showing {offset + 1}-{offset + len(results)}:\n\n"
        )

        for i, result in enumerate(results):
            result_text += f"## {offset + i + 1}. {result['title']}\n"
            result_text += f"Path: {result['path']}\n"
            result_text += f"Namespace: {result['namespace']}\n"
            result_text += f"Content Type: {result['content_type']}\n"
            result_text += f"Snippet: {result['snippet']}\n\n"

        return result_text

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
        """Generate search suggestions based on partial query."""
        logger.info(
            f"Starting suggestion generation for query: '{partial_query}', "
            f"limit: {limit}"
        )
        suggestions = []
        partial_lower = partial_query.lower().strip()

        try:
            # Strategy 1: Use search functionality as fallback since direct entry
            # iteration
            # may not work reliably with all ZIM file structures
            suggestions = self._get_suggestions_from_search(
                archive, partial_query, limit
            )

            if suggestions:
                logger.info(
                    f"Found {len(suggestions)} suggestions using search fallback"
                )
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
                    entry = archive.get_entry_by_id(entry_id)
                    title = entry.title or ""
                    path = entry.path or ""

                    entries_processed += 1

                    # Log first few entries for debugging
                    if entries_processed <= 5:
                        logger.debug(
                            f"Entry {entry_id}: title='{title}', path='{path}'"
                        )

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

            # Take the best matches from direct entry iteration
            for match in title_matches[:limit]:
                suggestions.append(
                    {
                        "text": match["suggestion"],
                        "path": match["path"],
                        "type": match["type"],
                    }
                )

        except Exception as e:
            logger.error(f"Error generating suggestions: {e}")
            return json.dumps(
                {"suggestions": [], "error": f"Error generating suggestions: {e}"}
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
            entry = archive.get_entry_by_path(entry_path)
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
                # For plain text, try to extract basic structure
                plain_text = self.content_processor.process_mime_content(
                    bytes(item.content), mime_type
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
            entry = archive.get_entry_by_path(entry_path)
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

        # Cache key for metadata (not data, as that could be large)
        cache_key = f"binary_meta:{validated_path}:{entry_path}"

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
                title = entry.title or "Untitled"
                mime_type = item.mimetype or "application/octet-stream"
                raw_content = bytes(item.content)
                content_size = len(raw_content)

                result: Dict[str, Any] = {
                    "path": entry_path,
                    "title": title,
                    "mime_type": mime_type,
                    "size": content_size,
                    "size_human": self._format_size(content_size),
                }

                # Determine if we should include the data
                if include_data:
                    if content_size <= max_size_bytes:
                        # Encode content as base64
                        encoded_data = base64.b64encode(raw_content).decode("ascii")
                        result["encoding"] = "base64"
                        result["data"] = encoded_data
                        result["truncated"] = False
                    else:
                        # Content too large
                        result["encoding"] = None
                        result["data"] = None
                        result["truncated"] = True
                        result["message"] = (
                            f"Content size ({self._format_size(content_size)}) "
                            f"exceeds max_size_bytes "
                            f"({self._format_size(max_size_bytes)}). "
                            f"Set include_data=False for metadata only, "
                            f"or increase max_size_bytes."
                        )
                else:
                    result["encoding"] = None
                    result["data"] = None
                    result["truncated"] = False
                    result["message"] = "Data not included (include_data=False)"

                # Cache the metadata (without data)
                meta_for_cache = {k: v for k, v in result.items() if k != "data"}
                self.cache.set(cache_key, meta_for_cache)

                logger.info(
                    f"Retrieved binary entry: {entry_path} "
                    f"({mime_type}, {self._format_size(content_size)})"
                )
                return json.dumps(result, indent=2, ensure_ascii=False)

        except OpenZimMcpArchiveError:
            raise
        except Exception as e:
            logger.error(f"Binary entry retrieval failed for {entry_path}: {e}")
            raise OpenZimMcpArchiveError(f"Failed to retrieve binary entry: {e}") from e

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
        # Validate parameters
        if max_words < 10:
            max_words = 10
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

    def _extract_entry_summary(
        self, archive: Archive, entry_path: str, max_words: int
    ) -> str:
        """Extract summary from article content."""
        try:
            # Try direct access first, fall back to search
            try:
                entry = archive.get_entry_by_path(entry_path)
            except Exception:
                actual_path = self._find_entry_by_search(archive, entry_path)
                if actual_path:
                    entry = archive.get_entry_by_path(actual_path)
                    entry_path = actual_path
                else:
                    raise OpenZimMcpArchiveError(
                        f"Entry not found: '{entry_path}'. "
                        f"Try using search_zim_file() to find available entries."
                    )

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
        1. First paragraph after the title/infobox
        2. Content of the first <p> tags
        3. Any text content as fallback
        """
        from bs4 import BeautifulSoup

        result: Dict[str, Any] = {
            "summary": "",
            "word_count": 0,
            "is_truncated": False,
        }

        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove navigation, sidebars, infoboxes, etc.
            unwanted_selectors = [
                "nav",
                "header",
                "footer",
                "aside",
                "script",
                "style",
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
            ]
            for selector in unwanted_selectors:
                for element in soup.select(selector):
                    element.decompose()

            # Try to find the first meaningful paragraphs
            paragraphs = []
            for p in soup.find_all("p"):
                text = p.get_text().strip()
                # Skip very short paragraphs (likely captions or labels)
                if len(text) > 50:
                    paragraphs.append(text)
                    # Collect enough paragraphs to reach max_words
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

        except Exception as e:
            logger.warning(f"Error extracting HTML summary: {e}")
            result["summary"] = "(Error extracting summary)"
            result["error"] = str(e)

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
            # Try direct access first, fall back to search
            try:
                entry = archive.get_entry_by_path(entry_path)
            except Exception:
                actual_path = self._find_entry_by_search(archive, entry_path)
                if actual_path:
                    entry = archive.get_entry_by_path(actual_path)
                    entry_path = actual_path
                else:
                    raise OpenZimMcpArchiveError(
                        f"Entry not found: '{entry_path}'. "
                        f"Try using search_zim_file() to find available entries."
                    )

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
        """
        from bs4 import BeautifulSoup, Tag

        result: Dict[str, Any] = {
            "toc": [],
            "heading_count": 0,
            "max_depth": 0,
        }

        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove unwanted elements
            for selector in ["script", "style", "nav", ".mw-editsection"]:
                for element in soup.select(selector):
                    element.decompose()

            # Find all headings in order
            headings: List[Dict[str, Any]] = []
            for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                if isinstance(heading, Tag):
                    level = int(heading.name[1])
                    text = heading.get_text().strip()
                    heading_id = heading.get("id", "")

                    if text:  # Skip empty headings
                        headings.append(
                            {
                                "level": level,
                                "text": text,
                                "id": heading_id if heading_id else "",
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

        except Exception as e:
            logger.warning(f"Error building hierarchical TOC: {e}")
            result["error"] = str(e)

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
