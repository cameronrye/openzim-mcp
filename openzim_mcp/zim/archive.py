"""Archive coordinator module.

Holds the ``ZimOperations`` class, the ``zim_archive`` context manager,
and the small set of shared helpers/constants that don't fit a single
domain mixin.

This module is the source of truth for ``ZimOperations`` and the
module-level ZIM-archive primitives. ``openzim_mcp.zim_operations``
re-exports the public names for backward compatibility.

Layout:

* ``zim_archive`` — context manager that opens an archive with a timeout
  and surfaces a consistent error type.
* ``PaginationCursor`` — base64-encoded pagination tokens used across the
  search/browse surfaces.
* ``ZimOperations`` — coordinator class that mixes in
  ``_SearchMixin``/``_ContentMixin``/``_StructureMixin``/``_NamespaceMixin``
  for the bulk of the surface. Methods that don't fit a single domain
  (file listing, archive metadata, main-page lookup) live directly on
  the class here.
"""

import base64
import json
import logging
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from libzim.reader import Archive  # type: ignore[import-untyped]
from libzim.search import (  # type: ignore[import-untyped]  # noqa: F401
    Query,
    Searcher,
)
from libzim.suggestion import (  # type: ignore[import-untyped]  # noqa: F401
    SuggestionSearcher,
)

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.constants import DEFAULT_MAIN_PAGE_TRUNCATION
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.defaults import CONTENT
from openzim_mcp.exceptions import (
    ArchiveOpenTimeoutError,
    OpenZimMcpArchiveError,
)
from openzim_mcp.security import PathValidator
from openzim_mcp.timeout_utils import run_with_timeout
from openzim_mcp.zim.content import _ContentMixin
from openzim_mcp.zim.namespace import _NamespaceMixin
from openzim_mcp.zim.search import _SearchMixin
from openzim_mcp.zim.structure import _StructureMixin

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
    #
    # ``Archive`` is looked up on the ``openzim_mcp.zim_operations`` shim at
    # call time so tests that patch ``openzim_mcp.zim_operations.Archive``
    # see their patch take effect here. Late-binding via attribute lookup
    # also avoids any import cycle when the mixins import this module.
    import openzim_mcp.zim_operations as _zim_ops_shim

    def open_archive() -> Archive:
        return _zim_ops_shim.Archive(str(file_path))

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


class ZimOperations(_SearchMixin, _ContentMixin, _StructureMixin, _NamespaceMixin):
    """Handles all ZIM file operations with caching and security.

    The bulk of the surface is contributed by domain mixins; this class
    holds the constructor and a handful of coordinator methods that
    don't fit a single domain (file listing, archive metadata, main-page
    lookup, and the shared entry-resolution fallback).
    """

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
                # ``Path.glob`` follows symlinks by default, which would let a
                # symlink inside an allowed directory point at a ZIM file
                # outside the allowed tree. Resolve each candidate and check
                # that it still lives under the directory we were told to
                # scan; reject otherwise (without raising — a stray symlink
                # in a watched directory is a misconfiguration, not a fatal
                # error).
                allowed_root = directory.resolve()
                zim_files_in_dir = list(directory.glob("**/*.zim"))
                logger.debug(f"Found {len(zim_files_in_dir)} ZIM files in {directory}")

                for file_path in zim_files_in_dir:
                    # ``is_file()`` follows symlinks, so a symlink to a real
                    # file passes it — verify membership in the allowed
                    # tree before accepting the entry.
                    if not file_path.is_file():
                        continue
                    try:
                        resolved = file_path.resolve()
                    except OSError as e:
                        logger.warning(f"Could not resolve {file_path}: {e}; skipping")
                        continue
                    if not resolved.is_relative_to(allowed_root):
                        logger.warning(
                            f"Skipping {file_path}: resolved path "
                            f"{resolved} is outside allowed root {allowed_root}"
                        )
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
        if cached_result is not None:
            logger.debug(f"Returning cached metadata for: {validated_path}")
            return cached_result  # type: ignore[no-any-return]

        # Late-bound lookup so test patches against
        # ``openzim_mcp.zim_operations.zim_archive`` apply here too.
        import openzim_mcp.zim_operations as _zim_ops_shim

        try:
            with _zim_ops_shim.zim_archive(validated_path) as archive:
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
                        # libzim raises RuntimeError if get_item() is called
                        # on a redirect entry. Resolve the full redirect chain
                        # (with cycle + depth bounds) so a legitimate metadata
                        # redirect doesn't disappear from the response simply
                        # because it points at the canonical key. A bare
                        # ``get_redirect_entry`` only resolves one hop, which
                        # would still raise RuntimeError on a 2-hop chain.
                        seen_meta: set[str] = set()
                        hops = 0
                        while getattr(entry, "is_redirect", False):
                            if hops >= MAX_REDIRECT_DEPTH or entry.path in seen_meta:
                                break
                            seen_meta.add(entry.path)
                            entry = entry.get_redirect_entry()
                            hops += 1
                        if getattr(entry, "is_redirect", False):
                            # Cycle or runaway chain — skip rather than raise,
                            # metadata is best-effort.
                            continue
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
        if cached_result is not None:
            logger.debug(f"Returning cached main page for: {validated_path}")
            return cached_result  # type: ignore[no-any-return]

        # Late-bound lookup so test patches against
        # ``openzim_mcp.zim_operations.zim_archive`` apply here too.
        import openzim_mcp.zim_operations as _zim_ops_shim

        try:
            with _zim_ops_shim.zim_archive(validated_path) as archive:
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

        def _follow_redirect(entry: Any) -> Any:
            # Most ZIM files generated by Kiwix tools point W/mainPage at
            # the canonical article via a redirect. libzim raises
            # RuntimeError if get_item() is called on a redirect entry, so
            # walk the chain (with cycle detection and the shared
            # MAX_REDIRECT_DEPTH cap) before any callers reach get_item().
            # Raise OpenZimMcpArchiveError on cycle/depth-exceeded to match
            # the rest of the codebase's redirect helpers and produce a
            # targeted diagnostic instead of a libzim RuntimeError surfaced
            # via get_item().
            seen: set[str] = set()
            for _ in range(MAX_REDIRECT_DEPTH):
                if not getattr(entry, "is_redirect", False):
                    return entry
                if entry.path in seen:
                    raise OpenZimMcpArchiveError(
                        f"Redirect cycle detected at {entry.path}"
                    )
                seen.add(entry.path)
                entry = entry.get_redirect_entry()
            if getattr(entry, "is_redirect", False):
                raise OpenZimMcpArchiveError(
                    f"Redirect chain too deep (>{MAX_REDIRECT_DEPTH}) "
                    f"in main-page lookup"
                )
            return entry

        try:
            # Try to get main page from archive metadata
            if hasattr(archive, "main_entry") and archive.main_entry:
                main_entry = _follow_redirect(archive.main_entry)
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

            # Fallback: try common main page paths. Entry-zero is NOT a
            # main-page candidate — libzim's internal ordering doesn't map
            # to the ZIM main-page pointer, so serving entry 0 would return
            # an arbitrary article. If main_entry is missing and none of
            # these named paths resolve, the archive simply has no main
            # page, which the caller handles below.
            main_page_paths = ["W/mainPage", "A/Main_Page", "A/index"]

            for path in main_page_paths:
                try:
                    entry = archive.get_entry_by_path(path)

                    if entry:
                        entry = _follow_redirect(entry)
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
                            result += f"Type: Main Page (found at {path})\n"
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

    def _resolve_entry_with_fallback(
        self, archive: Archive, entry_path: str
    ) -> Tuple[Any, str]:
        """Resolve an entry by direct path, falling back to search.

        Returns (entry, resolved_path) with redirects already followed so the
        caller can call ``entry.get_item()`` directly — libzim raises
        RuntimeError when get_item() is invoked on a redirect entry. The
        returned ``resolved_path`` is the post-redirect ``entry.path`` so
        callers that surface it in JSON responses (and downstream
        relative-link resolution in ``get_related_articles``) reflect the
        canonical target rather than the redirect stub.

        Raises OpenZimMcpArchiveError cleanly (without an implicit __context__
        chain to a transient direct-access error) if neither direct access
        nor search yields a result, and also when the redirect chain
        contains a cycle or exceeds ``MAX_REDIRECT_DEPTH`` hops.
        """

        def _follow(entry: Any) -> Any:
            seen: set[str] = set()
            for _ in range(MAX_REDIRECT_DEPTH):
                if not getattr(entry, "is_redirect", False):
                    return entry
                if entry.path in seen:
                    raise OpenZimMcpArchiveError(
                        f"Redirect cycle detected at {entry.path}"
                    )
                seen.add(entry.path)
                entry = entry.get_redirect_entry()
            if getattr(entry, "is_redirect", False):
                raise OpenZimMcpArchiveError(
                    f"Redirect chain too deep (>{MAX_REDIRECT_DEPTH}) "
                    f"starting at {entry_path}"
                )
            return entry

        # Suppress only the transient direct-access lookup error so callers
        # see a clean "not found" message rather than a chained exception
        # with the underlying archive error as context. Redirect errors
        # raised from _follow propagate — they are real failures, not
        # "not found", and falling through to a search fallback would mask
        # malformed-archive bugs.
        entry = None
        with suppress(Exception):
            entry = archive.get_entry_by_path(entry_path)
        if entry is not None:
            resolved = _follow(entry)
            return resolved, resolved.path
        actual_path = self._find_entry_by_search(archive, entry_path)
        if actual_path:
            resolved = _follow(archive.get_entry_by_path(actual_path))
            return resolved, resolved.path
        raise OpenZimMcpArchiveError(
            f"Entry not found: '{entry_path}'. "
            f"Try using search_zim_file() to find available entries."
        ) from None
