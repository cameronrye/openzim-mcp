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
* ``ZimOperations`` — coordinator class that mixes in
  ``_SearchMixin``/``_ContentMixin``/``_StructureMixin``/``_NamespaceMixin``
  for the bulk of the surface. Methods that don't fit a single domain
  (file listing, archive metadata, main-page lookup) live directly on
  the class here.
"""

import logging
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Generator, List, Optional, Tuple, cast

import libzim  # type: ignore[import-untyped]
from libzim.reader import Archive  # type: ignore[import-untyped]
from libzim.search import (  # type: ignore[import-untyped]
    Query,
    Searcher,
)
from libzim.suggestion import (  # type: ignore[import-untyped]
    SuggestionSearcher,
)

from openzim_mcp.archive_types import detect_archive_type
from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.constants import DEFAULT_MAIN_PAGE_TRUNCATION
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.defaults import CONTENT
from openzim_mcp.exceptions import (
    ArchiveOpenTimeoutError,
    OpenZimMcpArchiveError,
)
from openzim_mcp.meta import attach_meta
from openzim_mcp.preset_data import ArchivePreset, load_presets, resolve_preset
from openzim_mcp.security import PathValidator
from openzim_mcp.timeout_utils import run_with_timeout
from openzim_mcp.zim._ops_base import _ArchiveAccessMixin, _json
from openzim_mcp.zim.content import _ContentMixin
from openzim_mcp.zim.namespace import _NamespaceMixin
from openzim_mcp.zim.redirects import resolve_redirect_chain
from openzim_mcp.zim.search import _SearchMixin
from openzim_mcp.zim.structure import _StructureMixin

if TYPE_CHECKING:
    from openzim_mcp.tool_schemas import (
        ArchiveValidationResponse,
        EntryResponse,
        ListZimFilesResponse,
        ZimMetadataResponse,
    )

__all__ = [
    "ARCHIVE_OPEN_TIMEOUT",
    "Archive",
    "MAX_REDIRECT_DEPTH",
    "Query",
    "Searcher",
    "SuggestionSearcher",
    "ZimOperations",
    "configure_libzim_caches",
    "zim_archive",
]


# Timeout for opening ZIM archives (seconds)
ARCHIVE_OPEN_TIMEOUT = 30.0

# Maximum redirect chain length before bailing out. See
# ``ContentDefaults.MAX_REDIRECT_DEPTH`` in ``defaults.py``.
MAX_REDIRECT_DEPTH = CONTENT.MAX_REDIRECT_DEPTH

# Per-entry preview cap for ``_extract_zim_metadata``. Wikipedia ZIMs
# store ``M/Title`` as a full HTML document (~1 MB) rather than the
# archive's bare title string; without a cap, that single value dwarfs
# every other metadata field AND blows past the per-call response
# budget. 800 chars is enough to surface the actual title for archives
# that store it plain, AND a clear "[truncated, …]" marker for the
# pathological HTML-template case.
_METADATA_PREVIEW_CAP = 800


# Cheap heuristic: a value with one of these markers in its first ~200
# bytes is HTML and needs ``_extract_metadata_text`` to surface the
# real value. Anything else (Date, Tags, Counter, ...) is plain text
# and goes through unchanged.
_HTML_MARKERS = ("<!doctype html", "<html", "<head", "<title>")


# Optional per-archive dirent-cache size (number of cached dirents), applied
# to every archive opened via ``zim_archive``. ``None`` leaves libzim's
# default (512) untouched. The cluster cache, by contrast, is a *process*
# global tuned directly via ``libzim.set_cluster_cache_max_size`` — see
# ``configure_libzim_caches``. Stored at module scope because ``zim_archive``
# is a module-level function with no access to server config.
_LIBZIM_DIRENT_CACHE_MAX_COUNT: Optional[int] = None


def configure_libzim_caches(
    cluster_cache_max_size_bytes: Optional[int] = None,
    dirent_cache_max_count: Optional[int] = None,
) -> None:
    """Apply optional libzim cache tuning.

    libzim exposes two read-side caches with *different* units and scopes:

    * The cluster cache is sized in **bytes** and is a **process-global**
      setting (``libzim.set_cluster_cache_max_size``); the default is 16 MiB.
    * The dirent cache is sized as a **count of dirents** and is a
      **per-archive** property (``Archive.dirent_cache_max_size``); the
      default is 512. It is applied per-open in ``zim_archive`` from the
      module-level ``_LIBZIM_DIRENT_CACHE_MAX_COUNT`` set here.

    ``None`` for either argument leaves libzim's default in place.
    """
    global _LIBZIM_DIRENT_CACHE_MAX_COUNT
    if cluster_cache_max_size_bytes is not None:
        try:
            libzim.set_cluster_cache_max_size(cluster_cache_max_size_bytes)
            logger.info(
                "libzim cluster cache max size set to %d bytes (process-global)",
                cluster_cache_max_size_bytes,
            )
        except Exception as e:  # pragma: no cover — defensive across versions
            logger.debug("set_cluster_cache_max_size unavailable: %s", e)
    # Guard on None so a caller tuning only the cluster cache doesn't clobber
    # a dirent count another caller already set — ``None`` means "leave as-is",
    # not "reset to default" (symmetric with the cluster branch above).
    if dirent_cache_max_count is not None:
        _LIBZIM_DIRENT_CACHE_MAX_COUNT = dirent_cache_max_count


def _parse_counter_metadata(counter_str: str) -> Dict[str, int]:
    """Parse an ``M/Counter`` value into a ``{mimetype: count}`` mapping.

    The ``Counter`` metadata value is a ``;``-separated list of
    ``mimetype=count`` pairs (e.g. ``"text/html=123;image/png=45"``).
    Malformed pairs — missing ``=`` or a non-integer count — are skipped
    rather than failing the whole parse; metadata is best-effort.
    """
    breakdown: Dict[str, int] = {}
    for pair in counter_str.split(";"):
        if "=" not in pair:
            continue
        mime, _, count_str = pair.partition("=")
        mime = mime.strip()
        try:
            breakdown[mime] = int(count_str.strip())
        except ValueError:
            logger.debug("Skipping malformed Counter pair: %r", pair)
    return breakdown


def _extract_metadata_text(raw: str) -> str:
    """Distil an M-namespace value down to its readable text.

    Wikipedia (and other MediaWiki-derived) ZIMs wrap each metadata
    field in a full HTML document — the literal title string ``"en"``
    arrives as ``<!DOCTYPE html><html …><head>…<title>en</title>…``
    plus a body. ``_METADATA_PREVIEW_CAP`` alone can't recover from
    this: the cap clips inside the boilerplate prefix, every field
    looks identical, and the caller never sees the real value.

    Strategy:
      1. If the content doesn't look like HTML, return as-is.
      2. Parse via BeautifulSoup. Prefer ``<title>`` text (often the
         exact field value on Wikipedia-flavour exports). Fall back
         to visible ``<body>`` text with scripts/styles stripped.
      3. Collapse whitespace runs so multi-line HTML doesn't bleed
         into the preview.
      4. If parsing fails, return the raw input — the cap path will
         still produce a (less useful but honest) preview.
    """
    if not raw:
        return raw
    head = raw[:200].lstrip().lower()
    if not any(marker in head for marker in _HTML_MARKERS):
        return raw
    try:
        from bs4 import BeautifulSoup  # imported lazily; only needed for HTML metadata
    except Exception:
        return raw
    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception:
        return raw
    # Prefer the body's visible text — on Wikipedia ZIMs the body
    # carries the actual field value (``en``, ``Wikipedia``,
    # ``The Free Encyclopedia``, ...), while ``<title>`` typically
    # echoes the M-key name (``Title``, ``Date``, ``Language``).
    # Strip script/style first so injected analytics don't leak
    # into the preview.
    for noise in soup(("script", "style", "noscript")):
        noise.decompose()
    body = soup.find("body")
    if body is not None:
        body_text = " ".join(body.get_text(separator=" ", strip=True).split())
        if body_text:
            return body_text
    # No body / empty body — fall back to <title>, then to all-text.
    title = soup.find("title")
    if title is not None:
        title_text = " ".join(title.get_text(separator=" ", strip=True).split())
        if title_text:
            return title_text
    return " ".join(soup.get_text(separator=" ", strip=True).split())


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
        archive = _zim_ops_shim.Archive(str(file_path))
        # Apply the optional per-archive dirent-cache size (count of
        # dirents). ``None`` leaves libzim's default. Guarded so a binding
        # that predates the settable property degrades silently.
        if _LIBZIM_DIRENT_CACHE_MAX_COUNT is not None:
            try:
                archive.dirent_cache_max_size = _LIBZIM_DIRENT_CACHE_MAX_COUNT
            except Exception as e:  # pragma: no cover — defensive across versions
                logger.debug("dirent_cache_max_size unavailable: %s", e)
        return archive

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


class ZimOperations(
    _ArchiveAccessMixin, _SearchMixin, _ContentMixin, _StructureMixin, _NamespaceMixin
):
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
        # Apply optional libzim cache tuning from config. Only touches
        # process/global libzim state when at least one knob is set, so
        # the default configuration leaves libzim's behaviour unchanged.
        cluster_bytes = config.cache.libzim_cluster_cache_max_size_bytes
        dirent_count = config.cache.libzim_dirent_cache_max_count
        if cluster_bytes is not None or dirent_count is not None:
            configure_libzim_caches(
                cluster_cache_max_size_bytes=cluster_bytes,
                dirent_cache_max_count=dirent_count,
            )
        logger.info("ZimOperations initialized")

    def _scan_zim_files(self) -> List[Dict[str, Any]]:  # NOSONAR(python:S3776)
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
        # Cache key bumped to v2b (Phase B) so v1.x cached per-file list
        # entries don't leak through if the inner shape ever drifts. Today
        # the per-file dict shape (name/path/directory/size/size_bytes/
        # modified) is unchanged; the v2b rename happens one layer up in
        # ``list_zim_files_summary_data`` (files→results, count→total).
        cache_key = "zim_files_list_data_v2b"
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

    def list_zim_files_summary_data(
        self, name_filter: Optional[str] = None
    ) -> "ListZimFilesResponse":
        """Structured ``list_zim_files`` payload.

        Wraps :py:meth:`list_zim_files_data` with the directories metadata
        that the legacy markdown-header string variant carries in its
        prose preamble, so MCP clients consuming the structured output
        get the same context without reparsing a header.

        v2 Phase B contract: the response carries the canonical pagination
        keys (``results`` / ``next_cursor`` / ``total`` / ``done`` /
        ``page_info``) plus the tool-specific ``directories_count`` and
        ``name_filter`` fields. ``list_zim_files`` is non-paginated — every
        matching file in the allowed directories is returned in a single
        call — so ``next_cursor`` is always ``None`` and ``done`` is
        always ``True``. The contract is applied for uniformity with the
        other list-shaped responses.

        Returns:
            ``ListZimFilesResponse``-shaped dict carrying ``results`` (the
            per-file dicts with name/path/directory/size/size_bytes/modified
            — formerly ``files``), ``next_cursor`` (always ``None``),
            ``total`` (the count, formerly ``count``), ``done`` (always
            ``True``), ``page_info``, plus ``directories_count``,
            ``name_filter``, and the ``_meta`` envelope.
        """
        files_list = self.list_zim_files_data(name_filter=name_filter)
        payload: Dict[str, Any] = {
            "name_filter": name_filter or "",
            "directories_count": len(self.config.allowed_directories),
            "results": files_list,
            "next_cursor": None,
            "total": len(files_list),
            "done": True,
            "page_info": {
                "offset": 0,
                "limit": len(files_list),
                "returned_count": len(files_list),
            },
        }
        return cast("ListZimFilesResponse", attach_meta(payload))

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
        result_text += _json(all_zim_files)
        return result_text

    def get_zim_metadata_data(self, zim_file_path: str) -> "ZimMetadataResponse":
        """Structured variant of ``get_zim_metadata``.

        Returns the metadata dict directly (not a JSON string) so MCP
        tools can hand it straight to FastMCP's structured-content path.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If metadata retrieval fails
        """
        # Validate and resolve file path
        validated_path = self._validate_zim_path(zim_file_path)

        # Distinct cache key from the legacy string variant so the two
        # don't collide on shared cache backends. Bumped to v2c when the
        # shape gained uuid / is_multipart / has_*_index / counter_breakdown
        # so pre-upgrade cached responses (old shape) don't leak through.
        cache_key = f"metadata_data:v2c:{validated_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached metadata dict for: {validated_path}")
            return cast("ZimMetadataResponse", cached_result)

        # Late-bound lookup so test patches against
        # ``openzim_mcp.zim_operations.zim_archive`` apply here too.
        import openzim_mcp.zim_operations as _zim_ops_shim

        try:
            with _zim_ops_shim.zim_archive(validated_path) as archive:
                metadata = self._extract_zim_metadata(archive)

            # Detect archive type from the M-namespace dict and surface it
            # in _meta only (never the public body). detect_archive_type is
            # pure + cheap; this does not call _archive_type (no recursion).
            entries = metadata.get("metadata_entries", {})
            if not isinstance(entries, dict):
                entries = {}
            atype, confidence = detect_archive_type(entries)

            # Attach _meta before caching so cold and warm reads return
            # bit-identical responses (Phase B #12).
            with_meta = attach_meta(
                metadata, detected_type=atype, detection_confidence=confidence
            )
            self.cache.set(cache_key, with_meta)
            logger.info(f"Retrieved metadata for: {validated_path}")
            return cast("ZimMetadataResponse", with_meta)

        except Exception as e:
            logger.error(f"Metadata retrieval failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Metadata retrieval failed: {e}") from e

    def get_zim_metadata(self, zim_file_path: str) -> str:
        """Legacy JSON-string variant of ``get_zim_metadata_data``.

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            JSON string containing ZIM metadata

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If metadata retrieval fails
        """
        return _json(self.get_zim_metadata_data(zim_file_path))

    def get_archive_validation_data(
        self, zim_file_path: str
    ) -> "ArchiveValidationResponse":
        """Validate a single ZIM archive and report its integrity + state.

        Runs ``Archive.check()`` (the native MD5 verification) and reports
        checksum availability, index capabilities, and identity. This is the
        per-archive diagnostic behind ``zim_health(zim_file_path=...)`` —
        distinct from the server-state report ``zim_health`` returns with no
        argument.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If validation fails
        """
        validated_path = self._validate_zim_path(zim_file_path)

        # Include a file-identity (mtime:size) token so an in-place ZIM
        # replacement invalidates the cached verdict. ``is_valid`` is an
        # integrity assertion derived from the file's bytes — serving it
        # stale after the file changed would be exactly backwards for a
        # diagnostic tool. Mirrors the bundle / namespace / content caches.
        from openzim_mcp.bundle import archive_stat_token

        cache_key = (
            f"validation_data:{validated_path}:{archive_stat_token(validated_path)}"
        )
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached validation for: {validated_path}")
            return cast("ArchiveValidationResponse", cached_result)

        import openzim_mcp.zim_operations as _zim_ops_shim

        try:
            with _zim_ops_shim.zim_archive(validated_path) as archive:
                has_checksum = bool(archive.has_checksum)
                data: Dict[str, Any] = {
                    "path": str(validated_path),
                    "name": validated_path.name,
                    # ``check()`` verifies the archive's internal checksum
                    # over the whole file — the authoritative integrity test.
                    "is_valid": bool(archive.check()),
                    "has_checksum": has_checksum,
                    "checksum": archive.checksum if has_checksum else None,
                    "has_fulltext_index": bool(archive.has_fulltext_index),
                    "has_title_index": bool(archive.has_title_index),
                    "uuid": str(archive.uuid),
                    "is_multipart": bool(archive.is_multipart),
                }

            with_meta = attach_meta(data)
            self.cache.set(cache_key, with_meta)
            logger.info(f"Validated archive: {validated_path}")
            return cast("ArchiveValidationResponse", with_meta)

        except Exception as e:
            logger.error(f"Validation failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Validation failed: {e}") from e

    def _extract_zim_metadata(self, archive: Archive) -> Dict[str, Any]:
        """Extract metadata from ZIM archive."""
        # Basic archive information
        metadata: Dict[str, Any] = {
            "entry_count": archive.entry_count,
            "all_entry_count": archive.all_entry_count,
            "article_count": archive.article_count,
            "media_count": archive.media_count,
        }

        # Archive identity + index capabilities (native libzim reader fields).
        # ``uuid`` is a ``uuid.UUID`` object — stringify for JSON. These are
        # intrinsic, cheap reads and let callers know up front whether
        # search/suggest will work without provoking an exception.
        metadata["uuid"] = str(archive.uuid)
        metadata["is_multipart"] = bool(archive.is_multipart)
        metadata["has_fulltext_index"] = bool(archive.has_fulltext_index)
        metadata["has_title_index"] = bool(archive.has_title_index)

        # Try to get metadata from M namespace
        metadata_entries = {}
        try:
            # DD1 (beta, second pass): new-scheme ZIM archives serve
            # ``M/<key>`` via ``archive.get_metadata_item`` — the
            # entry-by-path API silently strips the ``M/`` prefix and
            # resolves to the C-namespace article with that name,
            # which is why ``metadata for <file>`` returned 172 KB
            # Wikipedia article bodies for Title / Description /
            # Language. (D7 fixed this for the per-entry
            # ``get article M/Title`` surface; this fix extends the
            # same routing to the aggregator.) On old-scheme archives
            # fall back to ``get_entry_by_path`` since the M namespace
            # actually lives on the entry surface there.
            has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)
            common_metadata = self._discover_metadata_keys(archive, has_new_scheme)
            for meta_key in common_metadata:
                try:
                    value = (
                        self._read_new_scheme_metadata_value(archive, meta_key)
                        if has_new_scheme
                        else self._read_old_scheme_metadata_value(archive, meta_key)
                    )
                    if value is not None:
                        metadata_entries[meta_key] = value
                except Exception as e:
                    # Entry doesn't exist or can't be read - expected for optional
                    logger.debug(f"Metadata 'M/{meta_key}' not available: {e}")

        except Exception as e:
            logger.warning(f"Error extracting metadata entries: {e}")

        if metadata_entries:
            metadata["metadata_entries"] = metadata_entries
            # Parse the ``M/Counter`` field (``mimetype=count;...``) into a
            # structured breakdown so callers can answer "how many
            # images/articles" without walking the archive.
            counter_raw = metadata_entries.get("Counter")
            if counter_raw:
                breakdown = _parse_counter_metadata(counter_raw)
                if breakdown:
                    metadata["counter_breakdown"] = breakdown

        return metadata

    def _archive_type(self, validated_path: Path) -> Tuple[str, str, str]:
        """Return ``(archive_type, confidence, name)`` for an archive.

        Reads the cached metadata response and runs the pure classifier.
        Deterministic and cheap; recomputed per call (the metadata read is
        cached, the classifier is a handful of string ops).
        """
        meta = self.get_zim_metadata_data(str(validated_path))
        entries = meta.get("metadata_entries", {})
        if not isinstance(entries, dict):
            entries = {}
        atype, confidence = detect_archive_type(entries)
        name = entries.get("Name", "")
        return atype, confidence, name if isinstance(name, str) else ""

    def _resolve_archive_preset(
        self, validated_path: Path
    ) -> Tuple[Optional[ArchivePreset], Optional[str]]:
        """Return ``(preset, applied_type)`` for an archive.

        ``preset`` is ``None`` (generic behavior) when detection confidence
        is below ``high`` and no per-archive pin forces a type.
        ``applied_type`` is the detected type when a preset applies, else
        ``None``.
        """
        atype, confidence, name = self._archive_type(validated_path)
        presets = load_presets(self.config.presets_override_path)
        preset = resolve_preset(presets, atype, confidence, name)
        return preset, (atype if preset is not None else None)

    def _discover_metadata_keys(
        self, archive: Archive, has_new_scheme: bool
    ) -> List[str]:
        """Build the ordered list of M-namespace keys to probe.

        Starts from the conventional hardcoded list (so the most common
        keys lead) and, for new-scheme archives, appends any extra keys
        the archive exposes via ``archive.metadata_keys``.
        """
        # Common metadata entries in M namespace.
        # A11 F6 (post-a10, second pass): for new-scheme
        # archives, enumerate ``archive.metadata_keys`` directly
        # instead of probing a hardcoded list — that's exactly
        # what ``walk namespace M`` does, and using the same
        # source guarantees the two operations agree on the set.
        # Filter out illustration keys (binary, can't surface as
        # text). The hardcoded list is retained as the old-scheme
        # fallback since ``metadata_keys`` is a new-scheme API.
        common_metadata = [
            "Title",
            "Description",
            "Long_Description",
            "Language",
            "Creator",
            "Publisher",
            "Date",
            "Source",
            "License",
            "Relation",
            "Flavour",
            "Tags",
            "Counter",
            "Name",
            "Scraper",
        ]

        if has_new_scheme:
            try:
                # A11 post-a11 M1: shared filter — see
                # ``zim.namespace.is_human_readable_metadata_key``.
                # Walk-namespace M and metadata-for must agree on
                # what counts as metadata; sharing the predicate
                # guarantees that.
                from openzim_mcp.zim.namespace import (
                    is_human_readable_metadata_key,
                )

                discovered = [
                    k
                    for k in (getattr(archive, "metadata_keys", []) or [])
                    if is_human_readable_metadata_key(k)
                ]
            except Exception as e:
                logger.debug(f"metadata_keys read failed: {e}")
                discovered = []
            # Stable order: start with the conventional list (so
            # the most common keys lead), then append any extras
            # the archive exposes that aren't in the list. This
            # keeps the previous response shape for archives
            # whose key set exactly matches the conventional
            # list and gracefully extends for archives that
            # carry custom keys.
            extras = [k for k in discovered if k not in common_metadata]
            common_metadata = common_metadata + extras
        return common_metadata

    def _read_new_scheme_metadata_value(
        self, archive: Archive, meta_key: str
    ) -> Optional[str]:
        """Read a single new-scheme ``M/<meta_key>`` value.

        New-scheme archives serve metadata via ``get_metadata_item`` as
        plain text (no HTML wrapper). Returns the (possibly capped) value,
        or ``None`` to skip the key (missing item / empty content).
        """
        try:
            item = archive.get_metadata_item(meta_key)
        except Exception as e:
            logger.debug(f"get_metadata_item failed for {meta_key}: {e}")
            return None
        if item is None:
            return None
        content = bytes(item.content).decode("utf-8", errors="replace").strip()
        if not content:
            return None
        # New-scheme metadata is plain text — Title is
        # ``"Wikipedia"``, Date is ``"2026-02-15"``.
        # Skip the HTML-extraction step entirely.
        if len(content) > _METADATA_PREVIEW_CAP:
            return (
                f"{content[:_METADATA_PREVIEW_CAP].rstrip()}… "
                f"[truncated, {len(content):,} chars total]"
            )
        return content

    def _read_old_scheme_metadata_value(
        self, archive: Archive, meta_key: str
    ) -> Optional[str]:
        """Read a single old-scheme ``M/<meta_key>`` value.

        Old-scheme archives expose the M namespace on the entry surface
        (``get_entry_by_path``). Resolves redirects (bounded best-effort
        walk), distils any HTML wrapper to readable text, and caps /
        annotates the result. Returns the value, or ``None`` to skip.
        """
        entry = archive.get_entry_by_path(f"M/{meta_key}")
        if not entry:
            return None
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
            return None
        item = entry.get_item()
        content = bytes(item.content).decode("utf-8", errors="replace").strip()
        if not content:
            return None
        return self._format_metadata_html_value(content)

    def _format_metadata_html_value(self, content: str) -> str:
        """Distil an old-scheme metadata value's HTML wrapper + cap it.

        D4 / Op2 (v2.0.0a9): Wikipedia ZIMs store ``M/Title``,
        ``M/Description``, ``M/Language`` etc. as full HTML documents
        (~1 MB each) rather than bare strings. The original a7 fix capped
        to 800 chars but every value then leads with the SAME 800 chars of
        ``<!DOCTYPE html>…<title>X</title>`` boilerplate — the actual field
        value lives buried past the cap in ``<body>``. Extract the readable
        text (preferring the ``<title>`` element, then ``<body>`` text)
        before the cap so the response surfaces the actual archive title /
        description / language instead of identical HTML prefixes.
        """
        extracted = _extract_metadata_text(content)
        original_chars = len(content)
        if len(extracted) > _METADATA_PREVIEW_CAP:
            preview = extracted[:_METADATA_PREVIEW_CAP].rstrip()
            return f"{preview}… [truncated, {original_chars:,} chars total]"
        elif extracted != content:
            # The field was HTML — record the
            # extracted text alongside an indicator
            # of the source-document size so the
            # caller knows the value was distilled
            # from a larger HTML wrapper.
            return (
                f"{extracted}"
                if original_chars <= len(extracted) + 16
                else (f"{extracted} [extracted from {original_chars:,}-char HTML]")
            )
        else:
            return content

    def get_main_page(self, zim_file_path: str, *, compact: bool = False) -> str:
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
        validated_path = self._validate_zim_path(zim_file_path)

        # Check cache
        cache_key = f"main_page:{validated_path}:compact={compact}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached main page for: {validated_path}")
            return cached_result  # type: ignore[no-any-return]

        # Late-bound lookup so test patches against
        # ``openzim_mcp.zim_operations.zim_archive`` apply here too.
        import openzim_mcp.zim_operations as _zim_ops_shim

        try:
            with _zim_ops_shim.zim_archive(validated_path) as archive:
                result, content_ok = self._get_main_page_content(
                    archive, compact=compact
                )

            # Don't cache error sentinels: a transient failure (e.g. MIME
            # processing error) should not be locked in for the TTL.
            if content_ok:
                self.cache.set(cache_key, result)
            logger.info(f"Retrieved main page for: {validated_path}")
            return result

        except Exception as e:
            logger.error(f"Main page retrieval failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Main page retrieval failed: {e}") from e

    def _get_main_page_content(  # NOSONAR(python:S3776)
        self, archive: Archive, *, compact: bool = False
    ) -> Tuple[str, bool]:
        """Get main page content from archive.

        Returns:
            (text, content_ok) — ``content_ok`` is False when the body holds an
            error sentinel produced by a fallback path (MIME processing or
            outer exception), so the caller can skip caching it.
        """

        # Most ZIM files generated by Kiwix tools point W/mainPage at the
        # canonical article via a redirect. libzim raises RuntimeError if
        # get_item() is called on a redirect entry, so walk the chain (cycle
        # detection + shared MAX_REDIRECT_DEPTH cap) before any caller reaches
        # get_item(). The shared resolver raises OpenZimMcpArchiveError on
        # cycle/depth-exceeded — a targeted diagnostic instead of an opaque
        # libzim RuntimeError surfaced via get_item().
        def _follow_redirect(entry: Any) -> Any:
            return resolve_redirect_chain(entry, context="in main-page lookup")

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
                        bytes(item.content), item.mimetype, compact=compact
                    )

                    # Truncate content for main page display. ``paginatable
                    # = False`` because ``_handle_main_page`` doesn't
                    # thread ``content_offset`` — point the caller at
                    # ``get article`` for the rest (A11 third pass).
                    content = self.content_processor.truncate_content(
                        content, DEFAULT_MAIN_PAGE_TRUNCATION, paginatable=False
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
                                bytes(item.content), item.mimetype, compact=compact
                            )
                            content = self.content_processor.truncate_content(
                                content,
                                DEFAULT_MAIN_PAGE_TRUNCATION,
                                paginatable=False,
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

    def get_main_page_data(
        self, zim_file_path: str, *, compact: bool = False
    ) -> "EntryResponse":
        """Structured variant of ``get_main_page``.

        Returns the entry dict directly (path/title/content/content_type)
        so MCP tools can hand it to FastMCP's structured-content path.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If main page retrieval fails
        """
        validated_path = self._validate_zim_path(zim_file_path)

        # Cache key distinct from the legacy text cache so old persisted
        # entries (which hold strings) don't collide with the new dict shape.
        cache_key = f"main_page_data:{validated_path}:compact={compact}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached main page dict for: {validated_path}")
            return cast("EntryResponse", cached_result)

        # Late-bound lookup so test patches against
        # ``openzim_mcp.zim_operations.zim_archive`` apply here too.
        import openzim_mcp.zim_operations as _zim_ops_shim

        try:
            with _zim_ops_shim.zim_archive(validated_path) as archive:
                payload, content_ok = self._get_main_page_data_content(
                    archive, compact=compact
                )
        except Exception as e:
            logger.error(f"Main page retrieval failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Main page retrieval failed: {e}") from e

        truncated = bool(payload.pop("_truncated", False))
        total_chars = payload.pop("_total_chars", None)
        # main_page is not paginable so no ``content_chars`` is supplied;
        # ``more_at_offset`` is intentionally omitted on a truncated
        # response (callers can't follow-up with a content_offset here).
        with_meta = attach_meta(
            payload,
            truncated=truncated,
            total_chars=total_chars,
        )
        if content_ok:
            self.cache.set(cache_key, with_meta)
        logger.info(f"Retrieved main page data for: {validated_path}")
        return cast("EntryResponse", with_meta)

    def _get_main_page_data_content(  # NOSONAR(python:S3776)
        self, archive: Archive, *, compact: bool = False
    ) -> Tuple[Dict[str, Any], bool]:
        """Build the main-page dict payload from an open archive.

        Mirrors ``_get_main_page_content`` but emits a structured dict
        rather than formatted markdown. Same redirect-handling and
        fallback-paths logic.

        Returns:
            ``(payload, content_ok)`` — ``content_ok`` is False when MIME
            processing raised; the caller must skip caching it.
        """

        def _follow_redirect(entry: Any) -> Any:
            return resolve_redirect_chain(entry, context="in main-page lookup")

        def _build(entry_obj: Any) -> Tuple[Dict[str, Any], bool]:
            title = entry_obj.title or "Main Page"
            path = entry_obj.path
            try:
                item = entry_obj.get_item()
                mime_type = item.mimetype or ""
                content = self.content_processor.process_mime_content(
                    bytes(item.content), mime_type, compact=compact
                )
                total_length = len(content)
                truncated_content = self.content_processor.truncate_content(
                    content, DEFAULT_MAIN_PAGE_TRUNCATION, paginatable=False
                )
                was_truncated = len(truncated_content) < total_length
                payload: Dict[str, Any] = {
                    "path": path,
                    "title": title,
                    "content": truncated_content,
                }
                if mime_type:
                    payload["content_type"] = mime_type
                if was_truncated:
                    payload["_truncated"] = True
                    payload["_total_chars"] = total_length
                return payload, True
            except Exception as e:
                logger.warning(f"Error getting main page content: {e}")
                return (
                    {
                        "path": path,
                        "title": title,
                        "content": f"(Error retrieving content: {e})",
                    },
                    False,
                )

        try:
            if hasattr(archive, "main_entry") and archive.main_entry:
                main_entry = _follow_redirect(archive.main_entry)
                return _build(main_entry)

            # Fallback: try common main page paths. Entry-zero is NOT a
            # candidate (libzim's internal ordering doesn't map to the
            # ZIM main-page pointer), so we only probe named paths.
            main_page_paths = ["W/mainPage", "A/Main_Page", "A/index"]
            for path in main_page_paths:
                try:
                    entry = archive.get_entry_by_path(path)
                    if entry:
                        entry = _follow_redirect(entry)
                        payload, ok = _build(entry)
                        if ok:
                            return payload, True
                except Exception:  # nosec B112 - intentional fallback
                    continue

            # No main page found — structural property of the archive,
            # safe to cache.
            return (
                {
                    "path": "",
                    "title": "Main Page",
                    "content": (
                        "No main page found in this ZIM file. "
                        "The archive may not have a designated main page entry."
                    ),
                },
                True,
            )

        except Exception as e:
            logger.error(f"Error getting main page: {e}")
            return (
                {
                    "path": "",
                    "title": "Main Page",
                    "content": f"Error retrieving main page: {e}",
                },
                False,
            )

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
            return resolve_redirect_chain(entry, context=f"starting at {entry_path}")

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
