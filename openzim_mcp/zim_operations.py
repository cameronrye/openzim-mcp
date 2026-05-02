"""ZIM file operations with proper resource management."""

import base64
import json
import logging
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from libzim.reader import Archive  # type: ignore[import-untyped]
from libzim.search import Query, Searcher  # type: ignore[import-untyped]  # noqa: F401
from libzim.suggestion import (  # type: ignore[import-untyped]  # noqa: F401
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
from .zim.content import _ContentMixin
from .zim.search import _SearchMixin
from .zim.structure import _StructureMixin

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


class ZimOperations(_SearchMixin, _ContentMixin, _StructureMixin):
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
        if cached_result is not None:
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
        if cached_result is not None:
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
            OpenZimMcpValidationError: If parameter validation fails (limit,
                offset, or namespace).
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If browsing fails
        """
        # Validate parameters. These are caller-input errors, distinct from
        # archive-access failures, so they surface as
        # OpenZimMcpValidationError to let the tool layer render a targeted
        # validation message.
        if limit < 1 or limit > 200:
            raise OpenZimMcpValidationError("Limit must be between 1 and 200")
        if offset < 0:
            raise OpenZimMcpValidationError("Offset must be non-negative")
        if not namespace or len(namespace.strip()) == 0:
            raise OpenZimMcpValidationError("Namespace must be a non-empty string")

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"browse_ns:{validated_path}:{namespace}:{limit}:{offset}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached namespace browse for: {namespace}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with zim_archive(validated_path) as archive:
                result = self._browse_namespace_entries(
                    archive,
                    namespace,
                    limit,
                    offset,
                    archive_path=str(validated_path),
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
        self,
        archive: Archive,
        namespace: str,
        limit: int,
        offset: int,
        archive_path: Optional[str] = None,
    ) -> str:
        """Browse entries in a specific namespace using sampling and search.

        ``archive_path`` enables caching the full namespace listing per
        ``(archive_path, namespace)`` so successive page requests do not
        re-scan the archive. When omitted (legacy callers / tests), the
        listing is recomputed every call.
        """
        entries: List[Dict[str, Any]] = []

        # Check if archive uses new namespace scheme
        has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)

        # Discover entries in the namespace. The full listing is cached
        # separately from the per-page JSON (cache_key in browse_namespace),
        # so different (limit, offset) pages share one scan.
        listing_key: Optional[str] = None
        cached_listing: Optional[Tuple[List[str], bool]] = None
        if archive_path is not None:
            listing_key = f"ns_entries:{archive_path}:{namespace}"
            cached_listing = self.cache.get(listing_key)

        if cached_listing is not None:
            namespace_entries, full_iteration = cached_listing
        else:
            namespace_entries, full_iteration = self._find_entries_in_namespace(
                archive, namespace, has_new_scheme
            )
            if listing_key is not None:
                self.cache.set(listing_key, (namespace_entries, full_iteration))

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

    # ------------------------------------------------------------------
    # Convenience tools: walk_namespace
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

        Raises:
            OpenZimMcpValidationError: If ``limit`` is outside ``1..500``.
        """
        # Caller-input validation surfaces as OpenZimMcpValidationError so
        # the tool layer can render a targeted validation message and so
        # other call sites (e.g. simple_tools) can distinguish it from
        # archive-access failures.
        if limit < 1 or limit > 500:
            raise OpenZimMcpValidationError(
                f"limit must be between 1 and 500 (provided: {limit})"
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
