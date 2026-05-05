"""Namespace-related methods for ``ZimOperations``.

This mixin handles namespace listing, browsing, and walking — anything
that surfaces or iterates over the archive's namespace structure.

``zim_archive`` and ``PaginationCursor`` are accessed through
``openzim_mcp.zim_operations`` so existing test patches against the
shim's symbols continue to work without changes.
"""

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from libzim.reader import Archive  # type: ignore[import-untyped]

import openzim_mcp.zim_operations as _zim_ops_mod
from openzim_mcp.constants import (
    NAMESPACE_MAX_ENTRIES,
    NAMESPACE_MAX_SAMPLE_SIZE,
    NAMESPACE_SAMPLE_ATTEMPTS_MULTIPLIER,
)
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


# Human-readable description per ZIM namespace letter; surfaced in the
# ``list_namespaces`` JSON response.
_NAMESPACE_DESCRIPTIONS = {
    "C": "User content entries (articles, main content)",
    "M": "ZIM metadata (title, description, language, etc.)",
    "W": "Well-known entries (MainPage, Favicon, navigation)",
    "X": "Search indexes and full-text search data",
    "A": "Legacy content namespace (older ZIM files)",
    "I": "Images and media files",
    "-": "Layout and template files",
}

# Minimum sampled hits required before we project a per-namespace total
# from the sampling ratio. Below this we report the lower-bound (sampled +
# probed) instead of fabricating numbers from single-hit projections.
_NAMESPACE_PROJECTION_MIN_SAMPLES = 3


class _NamespaceMixin:
    """Namespace listing / browsing / walking methods for ZimOperations."""

    if TYPE_CHECKING:
        config: "OpenZimMcpConfig"
        path_validator: "PathValidator"
        cache: "OpenZimMcpCache"
        content_processor: "ContentProcessor"

    def list_namespaces_data(self, zim_file_path: str) -> Dict[str, Any]:
        """Structured variant of ``list_namespaces``.

        Returns the same payload as ``list_namespaces`` but as a Python
        dict, so MCP tool functions can hand it straight to FastMCP's
        structured-output path without the json.dumps + re-parse round
        trip the legacy string variant required.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If namespace listing fails
        """
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Cache key distinct from the legacy string cache so old persisted
        # entries (which hold strings) don't collide with the new dict shape.
        cache_key = f"namespaces_data:{validated_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached namespaces dict for: {validated_path}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result = self._list_archive_namespaces(archive)

            self.cache.set(cache_key, result)
            logger.info(f"Listed namespaces for: {validated_path}")
            return result

        except Exception as e:
            logger.error(f"Namespace listing failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Namespace listing failed: {e}") from e

    def list_namespaces(self, zim_file_path: str) -> str:
        """Legacy JSON-string variant of ``list_namespaces_data``.

        Retained so ``SimpleToolsHandler`` (which composes natural-language
        responses out of these strings) keeps working unchanged. New
        callers should prefer ``list_namespaces_data``.
        """
        return json.dumps(
            self.list_namespaces_data(zim_file_path),
            indent=2,
            ensure_ascii=False,
        )

    def _list_archive_namespaces(self, archive: Archive) -> Dict[str, Any]:
        """List namespaces in the archive.

        For small archives (entry_count <= NAMESPACE_MAX_SAMPLE_SIZE) iterate
        every entry by ID so the namespace inventory is exhaustive. For larger
        archives, fall back to random sampling and return estimated counts.
        Random sampling on small entry pools collides heavily, leaving
        namespaces undiscovered and counts wildly off.
        """
        namespaces: Dict[str, Dict[str, Any]] = {}
        seen_entries: set[str] = set()
        has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)
        logger.debug(f"Archive uses new namespace scheme: {has_new_scheme}")

        total_entries = archive.entry_count
        full_iteration = total_entries <= NAMESPACE_MAX_SAMPLE_SIZE

        record = self._make_namespace_recorder(namespaces, seen_entries)

        if full_iteration:
            self._iterate_all_entries(archive, total_entries, record)
            self._finalise_full_iteration(namespaces)
        else:
            self._sample_entries(archive, total_entries, seen_entries, record)
            self._probe_known_namespaces(archive, seen_entries, record)
            self._finalise_sampled(namespaces, total_entries)

        result = {
            "total_entries": total_entries,
            "sampled_entries": len(seen_entries),
            "has_new_namespace_scheme": has_new_scheme,
            "is_total_authoritative": full_iteration,
            "discovery_method": "full_iteration" if full_iteration else "sampling",
            "namespaces": namespaces,
        }
        return result

    def _make_namespace_recorder(
        self, namespaces: Dict[str, Dict[str, Any]], seen_entries: set[str]
    ) -> Any:
        """Build a closure that registers one entry into the namespaces map.

        Tracks sampled vs probed separately because probed entries are
        deterministic existence proofs and do NOT carry the
        sampling-frequency signal needed for ratio extrapolation.
        """

        def _record(path: str, title: str, is_probe: bool = False) -> None:
            if path in seen_entries:
                return
            seen_entries.add(path)
            namespace = self._extract_namespace_from_path(path)
            ns_info = namespaces.setdefault(
                namespace,
                {
                    "count": 0,
                    "description": _NAMESPACE_DESCRIPTIONS.get(
                        namespace, f"Namespace '{namespace}'"
                    ),
                    "sample_entries": [],
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

        return _record

    @staticmethod
    def _iterate_all_entries(archive: Archive, total_entries: int, record: Any) -> None:
        """Walk every entry id (small-archive path)."""
        logger.debug(
            f"Iterating all {total_entries} entries for exhaustive "
            f"namespace listing"
        )
        for entry_id in range(total_entries):
            try:
                entry = archive._get_entry_by_id(entry_id)
                record(entry.path, entry.title or "")
            except Exception as e:
                logger.debug(f"Error reading entry {entry_id}: {e}")

    @staticmethod
    def _finalise_full_iteration(namespaces: Dict[str, Dict[str, Any]]) -> None:
        """Collapse internal counters into the public shape after full scan."""
        for ns_info in namespaces.values():
            ns_info["sampled_count"] = ns_info["count"]
            ns_info["estimated_total"] = ns_info["count"]
            ns_info.pop("_probed_count", None)
            ns_info.pop("_sampled_count", None)

    @staticmethod
    def _sample_entries(
        archive: Archive, total_entries: int, seen_entries: set[str], record: Any
    ) -> None:
        """Random-sample up to NAMESPACE_MAX_SAMPLE_SIZE distinct entries."""
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
                    record(entry.path, entry.title or "", is_probe=False)
                except Exception as e:
                    logger.debug(f"Error sampling entry: {e}")
        except Exception as e:
            logger.warning(f"Error during namespace sampling: {e}")

    def _probe_known_namespaces(
        self, archive: Archive, seen_entries: set[str], record: Any
    ) -> None:
        """Probe canonical paths to surface namespaces missed by sampling.

        Random sampling on a large archive will silently miss minority
        namespaces (e.g. M, W, X, I when A holds 99%+ of entries). Trying
        canonical paths in each common namespace surfaces them
        deterministically.
        """
        for canonical_path in self._get_known_namespace_probes():
            try:
                if (
                    archive.has_entry_by_path(canonical_path)
                    and canonical_path not in seen_entries
                ):
                    try:
                        entry = archive.get_entry_by_path(canonical_path)
                        record(entry.path, entry.title or "", is_probe=True)
                    except Exception as e:
                        logger.debug(
                            f"Error reading canonical entry {canonical_path}: {e}"
                        )
            except Exception as e:
                logger.debug(f"Error probing canonical path {canonical_path}: {e}")

    @staticmethod
    def _finalise_sampled(
        namespaces: Dict[str, Dict[str, Any]], total_entries: int
    ) -> None:
        """Project per-namespace totals from sample counts.

        We extrapolate ONLY the randomly-sampled count via sampling ratio —
        probed entries are confirmed-present-but-frequency-unknown, so they
        only contribute a lower-bound floor. Project only when we have
        enough sampled signal to make a stable estimate; below the
        threshold, single-hit projections vary by 100%+ and effectively
        manufacture numbers.
        """
        sampled_only_count = sum(v["_sampled_count"] for v in namespaces.values())
        sampling_ratio = (
            sampled_only_count / total_entries if sampled_only_count else 0.0
        )
        for ns_info in namespaces.values():
            sampled = ns_info["_sampled_count"]
            probed = ns_info["_probed_count"]
            if sampling_ratio > 0 and sampled >= _NAMESPACE_PROJECTION_MIN_SAMPLES:
                estimated_from_sample = int(sampled / sampling_ratio)
            else:
                estimated_from_sample = 0
            estimated_total = max(estimated_from_sample, sampled + probed)

            ns_info["sampled_count"] = sampled
            ns_info["probed_count"] = probed
            ns_info["estimated_total"] = estimated_total
            ns_info["count"] = estimated_total
            ns_info.pop("_probed_count", None)
            ns_info.pop("_sampled_count", None)

    def _extract_namespace_from_path(self, path: str) -> str:
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

        return self._canonicalise_namespace(namespace)

    @staticmethod
    def _canonicalise_namespace(namespace: str) -> str:
        """Map a raw namespace token to its canonical short form.

        Handles single-char prefixes (case-insensitive — ZIM archives
        canonically use uppercase but tooling and user input may pass
        lowercase) and the long-form aliases ("content", "metadata", etc.)
        used by some new-scheme archives. Long-form matching is also
        case-insensitive so that callers passing ``CONTENT`` or
        ``Metadata`` get the same result as ``content`` / ``metadata``.
        """
        if len(namespace) == 1 and namespace.isalpha():
            # Single character namespace (typical for both old and new schemes)
            return namespace.upper()
        # Long-form aliases — match case-insensitively so callers don't
        # get silent zero-result responses for ``CONTENT`` etc.
        lower = namespace.lower()
        if lower == "content":
            return "C"
        if lower == "metadata":
            return "M"
        if lower in ("wellknown", "well-known"):
            return "W"
        if lower in ("search", "index"):
            return "X"
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

        # Canonicalise user input (e.g. "c" -> "C", "content" -> "C") so
        # the comparison against ``_extract_namespace_from_path`` (which
        # always returns the canonical form) does not silently miss every
        # entry when callers pass lowercase or long-form names.
        namespace = self._canonicalise_namespace(namespace.strip())

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
            with _zim_ops_mod.zim_archive(validated_path) as archive:
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

    def _browse_namespace_entries(  # NOSONAR(python:S3776)
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
            next_cursor = _zim_ops_mod.PaginationCursor.create_next_cursor(
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
        total_entries = archive.entry_count

        # Full iteration is exhaustive and far more accurate than sampling for
        # small archives. The threshold mirrors _list_archive_namespaces.
        if total_entries <= NAMESPACE_MAX_SAMPLE_SIZE:
            entries = self._enumerate_namespace_entries(
                archive, namespace, total_entries
            )
            return sorted(entries), True

        sampled, seen = self._sample_namespace_entries(archive, namespace)
        self._extend_with_pattern_probes(archive, namespace, sampled, seen)
        return sorted(sampled), False

    def _enumerate_namespace_entries(
        self, archive: Archive, namespace: str, total_entries: int
    ) -> List[str]:
        """Walk every entry id and keep those that fall under ``namespace``."""
        logger.debug(
            f"Iterating all {total_entries} entries to enumerate namespace "
            f"'{namespace}'"
        )
        seen: set[str] = set()
        results: List[str] = []
        for entry_id in range(total_entries):
            try:
                entry = archive._get_entry_by_id(entry_id)
                path = entry.path
                if path in seen:
                    continue
                seen.add(path)
                if self._extract_namespace_from_path(path) == namespace:
                    results.append(path)
            except Exception as e:
                logger.debug(f"Error reading entry {entry_id}: {e}")
        logger.info(
            f"Found {len(results)} entries in namespace '{namespace}' via full "
            f"iteration of {total_entries} entries"
        )
        return results

    def _sample_namespace_entries(
        self, archive: Archive, namespace: str
    ) -> Tuple[List[str], set[str]]:
        """Sample random entries until ``NAMESPACE_MAX_ENTRIES`` matches found."""
        total_entries = archive.entry_count
        max_samples = min(NAMESPACE_MAX_SAMPLE_SIZE * 2, total_entries)
        max_attempts = max_samples * NAMESPACE_SAMPLE_ATTEMPTS_MULTIPLIER
        logger.debug(f"Sampling for entries in namespace '{namespace}'")

        results: List[str] = []
        seen: set[str] = set()
        attempts = 0
        while len(results) < NAMESPACE_MAX_ENTRIES and attempts < max_attempts:
            attempts += 1
            try:
                path = archive.get_random_entry().path
                if path in seen:
                    continue
                seen.add(path)
                if self._extract_namespace_from_path(path) == namespace:
                    results.append(path)
            except Exception as e:
                logger.debug(f"Error sampling entry: {e}")

        logger.info(
            f"Found {len(results)} entries in namespace '{namespace}' "
            f"after {attempts} samples"
        )
        return results, seen

    def _extend_with_pattern_probes(
        self,
        archive: Archive,
        namespace: str,
        results: List[str],
        seen: set[str],
    ) -> None:
        """Append entries from canonical-pattern probes to the sampled list.

        The pattern list contains both namespace-prefixed paths (e.g.
        ``C/index.html``) and bare paths (e.g. ``index.html``); the latter
        live in *some other* namespace, so we must verify membership before
        appending.
        """
        for pattern in self._get_common_namespace_patterns(namespace):
            try:
                if (
                    archive.has_entry_by_path(pattern)
                    and pattern not in seen
                    and self._extract_namespace_from_path(pattern) == namespace
                ):
                    results.append(pattern)
                    seen.add(pattern)
            except Exception as e:
                logger.debug(f"Error checking pattern {pattern}: {e}")

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

        # Canonicalise user input (e.g. "c" -> "C") so the comparison
        # against ``_extract_namespace_from_path`` (canonical form) does
        # not silently iterate to completion with zero matches.
        if namespace:
            namespace = self._canonicalise_namespace(namespace.strip())

        validated = self.path_validator.validate_path(zim_file_path)
        validated = self.path_validator.validate_zim_file(validated)

        try:
            with _zim_ops_mod.zim_archive(validated) as archive:
                total = archive.entry_count
                entries: List[Dict[str, Any]] = []
                entry_id = cursor
                while entry_id < total and len(entries) < limit:
                    try:
                        entry = archive._get_entry_by_id(entry_id)
                        path = entry.path
                        if self._extract_namespace_from_path(path) == namespace:
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
