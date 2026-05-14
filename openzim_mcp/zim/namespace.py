"""Namespace-related methods for ``ZimOperations``.

This mixin handles namespace listing, browsing, and walking — anything
that surfaces or iterates over the archive's namespace structure.

``zim_archive`` is accessed through ``openzim_mcp.zim_operations`` so
existing test patches against the shim's symbols continue to work
without changes.
"""

import contextlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

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
from openzim_mcp.meta import attach_meta

if TYPE_CHECKING:
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator
    from openzim_mcp.tool_schemas import (
        BrowseNamespaceResponse,
        ListNamespacesResponse,
        WalkNamespaceResponse,
    )

logger = logging.getLogger(__name__)


def is_human_readable_metadata_key(key: str) -> bool:
    """A11 post-a11 M1: shared filter for ``M/<key>`` metadata entries that
    can surface as text-rendered values.

    ``Illustration_*`` keys are binary PNG payloads (favicon-shaped art)
    that decode-as-utf8 turns into mojibake. Both ``metadata for <file>``
    (the aggregator at :meth:`Archive._extract_zim_metadata`) and
    ``walk namespace M`` should agree on what counts as a human-readable
    metadata key — splitting the filter between the two surfaces produced
    a 12-vs-13 disagreement (aggregator dropped the illustration; walk
    kept it). One predicate, one answer.
    """
    return not key.startswith("Illustration_")


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

# D11 / Op6 (v2.0.0a9): the set of namespace letters defined by the ZIM
# spec — used by ``browse_namespace_data`` to fast-reject unknown
# tokens before the full-iteration fallback wastes cycles scanning a
# 27 M-entry archive for letters that don't exist. New-scheme
# archives are dominated by C; old-scheme add A and I. ``-`` is the
# layout/templates pseudo-namespace.
_KNOWN_NAMESPACE_LETTERS = frozenset({"C", "M", "W", "X", "A", "I", "-"})

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

    def list_namespaces_data(self, zim_file_path: str) -> "ListNamespacesResponse":
        """Structured variant of ``list_namespaces``.

        Returns the same payload as ``list_namespaces`` but as a Python
        dict, so MCP tool functions can hand it straight to FastMCP's
        structured-output path without the json.dumps + re-parse round
        trip the legacy string variant required.

        Phase B v2: this is the one list-shaped result that does NOT carry
        the PaginatedResponse contract — it returns a dict-of-summaries,
        not a list. Top-level keys are ``total_entries`` /
        ``sampled_entries`` / ``has_new_namespace_scheme`` /
        ``is_total_authoritative`` / ``discovery_method`` / ``namespaces``
        plus the universal ``_meta`` envelope.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If namespace listing fails
        """
        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Cache key bumped to v2b (Phase B) so v1.x cached responses (old
        # shape: entry_count key) don't leak through after the rename to ``total``.
        cache_key = f"namespaces_data:v2b:{validated_path}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached namespaces dict for: {validated_path}")
            return cast("ListNamespacesResponse", cached_result)

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result = self._list_archive_namespaces(archive)

            # Attach _meta BEFORE caching so cold and warm reads return
            # bit-identical responses (Phase B #12 fix — re-attaching on
            # each cache hit produced non-deterministic chars/tokens_est).
            with_meta = attach_meta(result)
            self.cache.set(cache_key, with_meta)
            logger.info(f"Listed namespaces for: {validated_path}")
            return cast("ListNamespacesResponse", with_meta)

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

        For new-scheme archives, the iterable surface only contains C
        entries; M is enumerated separately via ``archive.metadata_keys`` and
        W is surfaced via canonical probes.
        """
        namespaces: Dict[str, Dict[str, Any]] = {}
        seen_entries: set[str] = set()
        has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)
        logger.debug(f"Archive uses new namespace scheme: {has_new_scheme}")

        total_entries = archive.entry_count
        full_iteration = total_entries <= NAMESPACE_MAX_SAMPLE_SIZE

        record = self._make_namespace_recorder(
            namespaces, seen_entries, has_new_scheme=has_new_scheme
        )

        if full_iteration:
            self._iterate_all_entries(archive, total_entries, record)
            self._finalise_full_iteration(namespaces)
        else:
            self._sample_entries(archive, total_entries, seen_entries, record)
            self._probe_known_namespaces(archive, seen_entries, record)
            self._finalise_sampled(namespaces, total_entries)

        # In new-scheme archives, M, W, X are reached via dedicated APIs, not
        # via the entry iterator. Surface them explicitly so callers see the
        # archive's real namespace inventory.
        if has_new_scheme:
            self._add_new_scheme_metadata_namespace(archive, namespaces)
            self._add_new_scheme_well_known_namespace(archive, namespaces)

        result = {
            "total_entries": total_entries,
            "sampled_entries": len(seen_entries),
            "has_new_namespace_scheme": has_new_scheme,
            "is_total_authoritative": full_iteration,
            "discovery_method": "full_iteration" if full_iteration else "sampling",
            "namespaces": namespaces,
        }
        return result

    @staticmethod
    def _add_new_scheme_metadata_namespace(
        archive: Archive, namespaces: Dict[str, Dict[str, Any]]
    ) -> None:
        """Populate the M namespace entry from ``archive.metadata_keys``.

        In new-scheme archives the public entry iterator surfaces only C
        entries; metadata is reached through ``Archive.metadata_keys`` and
        ``get_metadata_item``. Without this, list_namespaces would silently
        omit M for every modern archive.
        """
        try:
            raw_keys = list(getattr(archive, "metadata_keys", []) or [])
        except Exception as e:
            logger.debug(f"Unable to read metadata_keys: {e}")
            return
        # a13 D2: filter through the shared predicate so list_namespaces,
        # walk namespace M, and metadata-for agree on the same bucket size.
        # Pre-fix, list_namespaces reported M=13 (raw libzim count, includes
        # the ``Illustration_*`` binary entry) while the other two reported
        # M=12. The a12 M1 fix plumbed the predicate to walk + metadata-for
        # but missed this third surface.
        keys = [k for k in raw_keys if is_human_readable_metadata_key(k)]
        if not keys:
            return
        # ``metadata_keys`` is an exhaustive enumeration of M, so the
        # bucket is authoritative — we know the total without sampling.
        ns_info = {
            "total": len(keys),
            "is_authoritative": True,
            "description": _NAMESPACE_DESCRIPTIONS["M"],
            "sample_entries": [{"path": f"M/{k}", "title": k} for k in keys[:5]],
            "sampled_count": len(keys),
            "estimated_total": len(keys),
            "probed_count": 0,
        }
        namespaces["M"] = ns_info

    @staticmethod
    def _add_new_scheme_well_known_namespace(
        archive: Archive, namespaces: Dict[str, Dict[str, Any]]
    ) -> None:
        """Surface the W namespace via canonical probes (mainPage, favicon).

        New-scheme archives expose well-known entries through dedicated APIs
        (``main_entry``, ``get_illustration_item``); they aren't part of the
        iterable C surface. Probing canonical paths gives a deterministic
        existence proof.
        """
        probes: List[Tuple[str, str]] = []
        # Suppressing exceptions here is intentional: probes are best-effort
        # advertisements of well-known entries. A failed probe simply means
        # we don't surface that path; it must not abort the listing.
        with contextlib.suppress(Exception):
            if getattr(archive, "has_main_entry", False):
                probes.append(("W/mainPage", "mainPage"))
        # ``has_illustration()`` (no size arg) reports whether any
        # illustration is available; preferred over the deprecated
        # ``get_illustration_sizes`` which carries a DeprecationWarning.
        with contextlib.suppress(Exception):
            if archive.has_illustration():
                probes.append(("W/favicon", "favicon"))
        if not probes:
            return
        # Probed-only buckets are authoritative existence proofs but the
        # ``total`` is a lower bound — we know these specific paths exist
        # but not how many other W entries the archive holds. We mark
        # ``is_authoritative=False`` to reflect that the count is not the
        # whole namespace, just confirmed canonical paths.
        namespaces["W"] = {
            "total": len(probes),
            "is_authoritative": False,
            "description": _NAMESPACE_DESCRIPTIONS["W"],
            "sample_entries": [{"path": p, "title": t} for p, t in probes],
            "sampled_count": 0,
            "probed_count": len(probes),
            "estimated_total": len(probes),
        }

    def _make_namespace_recorder(
        self,
        namespaces: Dict[str, Dict[str, Any]],
        seen_entries: set[str],
        has_new_scheme: bool = False,
    ) -> Any:
        """Build a closure that registers one entry into the namespaces map.

        Tracks sampled vs probed separately because probed entries are
        deterministic existence proofs and do NOT carry the
        sampling-frequency signal needed for ratio extrapolation.

        ``has_new_scheme`` is forwarded to the namespace extractor so that
        new-scheme archives don't fabricate first-letter buckets like
        ``F`` from ``favicon.png`` or ``E`` from ``Evolution``.
        """

        def _record(path: str, title: str, is_probe: bool = False) -> None:
            if path in seen_entries:
                return
            seen_entries.add(path)
            namespace = self._extract_namespace_from_path(
                path, has_new_scheme=has_new_scheme
            )
            ns_info = namespaces.setdefault(
                namespace,
                {
                    # ``total`` is the per-namespace count (renamed from
                    # ``count`` in v2 Phase B for consistency with
                    # PaginatedResponse.total). For full-iteration buckets
                    # this is exact; for sampled buckets it is overwritten
                    # with the projected estimate during finalisation.
                    "total": 0,
                    # Set during finalisation: True for full iteration,
                    # False for sampled / probed-only buckets.
                    "is_authoritative": False,
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
            ns_info["total"] += 1
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
            # Full iteration enumerates every entry — the bucket's total
            # is exact and the bucket is authoritative.
            ns_info["sampled_count"] = ns_info["total"]
            ns_info["estimated_total"] = ns_info["total"]
            ns_info["is_authoritative"] = True
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
            ns_info["total"] = estimated_total
            # Sampling-derived counts are projections, not exact totals.
            ns_info["is_authoritative"] = False
            ns_info.pop("_probed_count", None)
            ns_info.pop("_sampled_count", None)

    def _extract_namespace_from_path(
        self, path: str, has_new_scheme: bool = False
    ) -> str:
        """Extract namespace from entry path.

        In **new-scheme** ZIM files, libzim's iterable entry surface
        (``entry_count`` / ``_get_entry_by_id`` / ``get_random_entry``) only
        exposes the C (content) namespace; entry paths carry no namespace
        prefix. So every iterable path is by definition in C, regardless of
        what its first character happens to be — parsing ``favicon.png`` or
        ``Evolution`` as namespace ``F`` / ``E`` is wrong.

        In **old-scheme** ZIMs, paths are namespace-prefixed (``A/Article``,
        ``M/Title``); the first segment is the namespace.

        Callers that have an ``Archive`` in scope must pass
        ``has_new_scheme=archive.has_new_namespace_scheme``. The default
        (``False``) preserves legacy single-arg call sites and keeps the
        canonicaliser-style behaviour used by some unit tests.
        """
        if not path:
            return "Unknown"

        if has_new_scheme:
            # libzim's iterable surface in new-scheme is C-only.
            return "C"

        # Old-scheme: namespace is the first segment before '/' (or, rarely,
        # the first character if no slash is present).
        if "/" in path:
            namespace = path.split("/", 1)[0]
        else:
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

    def browse_namespace_data(
        self,
        zim_file_path: str,
        namespace: str,
        limit: int = 50,
        offset: int = 0,
        *,
        cursor_archive_identity: Optional[str] = None,
    ) -> "BrowseNamespaceResponse":
        """Structured variant of ``browse_namespace``.

        Returns the result dict directly (not a JSON string) so MCP tools
        can hand it straight to FastMCP's structured-content path.

        Phase B contract: top-level ``results`` / ``next_cursor`` /
        ``total`` / ``done`` / ``page_info`` plus the ``namespace`` /
        ``discovery_method`` / ``sampling_based`` /
        ``results_may_be_incomplete`` extras. ``next_cursor`` is encoded
        with ``tool="browse_namespace"`` and state ``{o, l, ns, ai}``.

        ``cursor_archive_identity`` is the ``s.ai`` value decoded from a
        resumed cursor; mismatched archives are rejected so a cursor
        issued for archive A cannot be honoured against archive B.

        Raises:
            OpenZimMcpValidationError: If parameter validation fails (limit,
                offset, or namespace), or if a cursor was issued for a
                different archive.
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If browsing fails
        """
        from openzim_mcp.pagination import (
            Cursor,
            CursorMismatchError,
            archive_identity,
        )

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

        # D11 / Op6 (v2.0.0a9): fast-reject unknown namespaces before the
        # full-iteration fallback wastes cycles scanning a 27M-entry
        # archive for a letter that the ZIM spec doesn't define.
        # Returns a structured ``bad_namespace`` payload so the caller
        # can self-correct via the empty-result footer's recovery hint.
        if namespace not in _KNOWN_NAMESPACE_LETTERS:
            empty_payload: Dict[str, Any] = {
                "namespace": namespace,
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {
                    "offset": offset,
                    "limit": limit,
                    "returned_count": 0,
                },
                "discovery_method": "rejected_unknown_namespace",
                "sampling_based": False,
                "results_may_be_incomplete": False,
            }
            return cast(
                "BrowseNamespaceResponse",
                attach_meta(empty_payload, reason="bad_namespace"),
            )

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Cursor integrity: a cursor issued for archive A must not be
        # honoured when resubmitted against archive B (same guard as
        # walk_namespace / extract_article_links / search_zim_file).
        if cursor_archive_identity is not None:
            try:
                Cursor.verify_archive_identity(
                    cast("Any", {"ai": cursor_archive_identity}),
                    expected=archive_identity(validated_path),
                    tool="browse_namespace",
                )
            except CursorMismatchError as e:
                raise OpenZimMcpValidationError(str(e)) from e

        # Cache key bumped to v2b (Phase B) so v1.x cached responses (old
        # shape: entries/total_in_namespace/...) don't leak through
        # after the upgrade.
        cache_key = f"browse_ns_data:v2b:{validated_path}:{namespace}:{limit}:{offset}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached namespace browse dict for: {namespace}")
            return cast("BrowseNamespaceResponse", cached_result)

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                raw = self._browse_namespace_entries(
                    archive,
                    namespace,
                    limit,
                    offset,
                    archive_path=str(validated_path),
                )

            # ``_browse_namespace_entries`` still returns the legacy inner
            # shape (entries / total_in_namespace / is_total_authoritative / ...). Adapt
            # to the v2 Phase B contract here so internal callers and tests
            # that target the helper aren't forced through the rename.
            entries = raw.get("entries", [])
            total_in_namespace = raw.get("total_in_namespace", 0)
            is_total_authoritative = raw.get("is_total_authoritative", True)
            discovery_method = raw.get("discovery_method", "unknown")
            sampling_based = raw.get("sampling_based", False)
            results_may_be_incomplete = raw.get("results_may_be_incomplete", False)

            returned_count = len(entries)
            last_index = offset + returned_count
            # When the discovery method is sampling-based, ``total_in_namespace``
            # is the size of the sample (capped at ``NAMESPACE_MAX_ENTRIES``),
            # not the true namespace size. Reporting ``done=True`` once the
            # caller has consumed the sample silently truncates pagination —
            # the contract key says "no more pages" but in reality only a
            # fraction of the namespace was returned. When sampling is in
            # play and the page is full, keep emitting ``next_cursor`` so
            # the caller can either continue paging or pivot to
            # ``walk_namespace`` for exhaustive iteration. The
            # ``page_info.total_is_lower_bound`` flag plus the new
            # ``_meta.reason="sample_only"`` give the caller enough signal
            # to interpret the situation correctly.
            sample_exhausted = (
                sampling_based
                and returned_count >= limit
                and last_index >= total_in_namespace
            )
            done = (last_index >= total_in_namespace) and not sample_exhausted
            next_cursor: Optional[str] = None
            if not done:
                from openzim_mcp.pagination import archive_identity

                next_cursor = Cursor.encode(
                    tool="browse_namespace",
                    state={
                        "o": last_index,
                        "l": limit,
                        "ns": namespace,
                        "ai": archive_identity(validated_path),
                    },
                )

            page_info: Dict[str, Any] = {
                "offset": offset,
                "limit": limit,
                "returned_count": returned_count,
            }
            if not is_total_authoritative:
                page_info["total_is_lower_bound"] = True

            payload: Dict[str, Any] = {
                "namespace": namespace,
                "results": entries,
                "next_cursor": next_cursor,
                "total": total_in_namespace,
                "done": done,
                "page_info": page_info,
                "discovery_method": discovery_method,
                "sampling_based": sampling_based,
                "results_may_be_incomplete": results_may_be_incomplete,
            }

            # Op4: ``reason="sample_only"`` flags that the page came from
            # a sampled discovery and ``done`` is conservatively False so
            # the caller knows to either keep paging or pivot to
            # ``walk_namespace`` for exhaustive iteration. The footer
            # renderer surfaces this as actionable prose.
            reason = "sample_only" if sample_exhausted else None
            with_meta = attach_meta(payload, reason=reason)
            self.cache.set(cache_key, with_meta)
            logger.info(
                f"Browsed namespace {namespace}: {limit} entries from offset {offset}"
            )
            return cast("BrowseNamespaceResponse", with_meta)

        except Exception as e:
            logger.error(f"Namespace browsing failed for {namespace}: {e}")
            raise OpenZimMcpArchiveError(f"Namespace browsing failed: {e}") from e

    def browse_namespace(
        self, zim_file_path: str, namespace: str, limit: int = 50, offset: int = 0
    ) -> str:
        """Legacy JSON-string variant of ``browse_namespace_data``.

        Browse entries in a specific namespace with pagination.

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
        return json.dumps(
            self.browse_namespace_data(zim_file_path, namespace, limit, offset),
            indent=2,
            ensure_ascii=False,
        )

    def _browse_namespace_entries(  # NOSONAR(python:S3776)
        self,
        archive: Archive,
        namespace: str,
        limit: int,
        offset: int,
        archive_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Browse entries in a specific namespace using sampling and search.

        ``archive_path`` enables caching the full namespace listing per
        ``(archive_path, namespace)`` so successive page requests do not
        re-scan the archive. When omitted (legacy callers / tests), the
        listing is recomputed every call.
        """
        entries: List[Dict[str, Any]] = []

        # Check if archive uses new namespace scheme
        has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)

        # Fast path: new-scheme + C namespace. Every iterable entry in a
        # new-scheme archive lives under C, so we don't need to enumerate
        # a list of "C entries" — we can pull each page directly from
        # the entry-id range. This avoids the 27M-iteration crash that
        # the legacy "build full list then slice" path triggered on
        # Wikipedia (D2): walking every entry to build a list we
        # immediately slice 50 rows out of is both pathologically slow
        # and memory-hostile. The total is ``archive.entry_count``,
        # which libzim returns in O(1).
        if has_new_scheme and namespace == "C":
            return self._browse_new_scheme_c_paginated(
                archive, namespace, limit, offset
            )
        # Fast path: new-scheme + W namespace. libzim doesn't surface W
        # through the iterable surface, but the well-known entries
        # (mainPage, favicon) ARE reachable by ``has_entry_by_path``.
        # Probing the known paths recovers the W namespace's actual
        # contents (D3) instead of the legacy empty result.
        if has_new_scheme and namespace == "W":
            return self._browse_new_scheme_w_paginated(
                archive, namespace, limit, offset
            )

        # Discover entries in the namespace. The full listing is cached
        # separately from the per-page JSON (cache_key in browse_namespace),
        # so different (limit, offset) pages share one scan. The stat
        # token (st_mtime_ns:st_size) ensures an atomic ZIM replacement
        # invalidates the listing rather than serving the prior
        # snapshot's entries indefinitely until LRU eviction.
        listing_key: Optional[str] = None
        cached_listing: Optional[Tuple[List[str], bool]] = None
        if archive_path is not None:
            from openzim_mcp.bundle import archive_stat_token

            stat_token = archive_stat_token(Path(archive_path))
            listing_key = f"ns_entries:{archive_path}:{stat_token}:{namespace}"
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
                materialised = self._materialise_browse_entry(
                    archive, entry_path, has_new_scheme
                )
                if materialised is not None:
                    entries.append(materialised)
            except Exception as e:
                logger.warning(f"Error processing entry {entry_path}: {e}")
                continue

        # ``next_cursor`` and ``has_more`` are intentionally omitted here.
        # ``browse_namespace_data`` (the sole caller) rebuilds both fields
        # itself using ``Cursor.encode(tool="browse_namespace", ...)``.

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
            # When sampling-based, ``total_in_namespace`` is the size of the
            # sampled listing — the real namespace may contain more entries.
            # Mirror that through a positively-named flag so callers don't
            # have to invert ``is_total_authoritative`` mentally.
            "total_in_namespace_is_lower_bound": not full_iteration,
            "offset": offset,
            "limit": limit,
            "returned_count": len(entries),
            "entries": entries,
            "sampling_based": not full_iteration,
            "discovery_method": "full_iteration" if full_iteration else "sampling",
            "is_total_authoritative": full_iteration,
            "results_may_be_incomplete": results_may_be_incomplete,
        }

        return result

    def _materialise_paths(
        self, archive: Archive, paths: List[str], *, log_label: str
    ) -> List[Dict[str, Any]]:
        """Run ``_materialise_browse_entry`` for each path, swallowing errors.

        Shared between the new-scheme C / W paginators — both materialise
        an already-known list of paths into the row dicts that
        ``browse_namespace_data`` expects. ``log_label`` lets the warning
        path identify which caller (C-range vs W-probe) produced the
        failure for diagnostics.
        """
        out: List[Dict[str, Any]] = []
        for entry_path in paths:
            try:
                materialised = self._materialise_browse_entry(
                    archive, entry_path, has_new_scheme=True
                )
                if materialised is not None:
                    out.append(materialised)
            except Exception as e:
                logger.warning(f"Error processing {log_label} entry {entry_path}: {e}")
                continue
        return out

    @staticmethod
    def _new_scheme_browse_payload(
        *,
        namespace: str,
        total: int,
        offset: int,
        limit: int,
        entries: List[Dict[str, Any]],
        discovery_method: str,
    ) -> Dict[str, Any]:
        """Build the v2 Phase B browse-namespace inner payload shape.

        Both the entry-id-range fast path (C) and the known-path probe
        (W) produce authoritative totals with no sampling — every field
        below is the same between them except ``discovery_method``,
        so factor the dict to one place.
        """
        return {
            "namespace": namespace,
            "total_in_namespace": total,
            "total_in_namespace_is_lower_bound": False,
            "offset": offset,
            "limit": limit,
            "returned_count": len(entries),
            "entries": entries,
            "sampling_based": False,
            "discovery_method": discovery_method,
            "is_total_authoritative": True,
            "results_may_be_incomplete": False,
        }

    def _browse_new_scheme_c_paginated(
        self,
        archive: Archive,
        namespace: str,
        limit: int,
        offset: int,
    ) -> Dict[str, Any]:
        """Page through new-scheme C-namespace entries by entry-id range.

        New-scheme archives store every iterable entry under C, so
        pagination is just ``[offset, offset+limit)`` against the
        entry-id range. The legacy code built a 27M-item list first and
        then sliced — slow, memory-hostile, and triggered "session
        expired" errors on real Wikipedia archives (D2). ``entry_count``
        is the authoritative total; ``done`` falls out naturally from
        ``offset + returned_count >= total``.
        """
        total = int(getattr(archive, "entry_count", 0) or 0)
        page_paths: List[str] = []
        end = min(offset + limit, total)
        for entry_id in range(offset, end):
            try:
                entry = archive._get_entry_by_id(entry_id)
            except Exception as e:
                logger.warning(f"Error reading entry id {entry_id}: {e}")
                continue
            page_paths.append(entry.path)
        return self._new_scheme_browse_payload(
            namespace=namespace,
            total=total,
            offset=offset,
            limit=limit,
            entries=self._materialise_paths(
                archive, page_paths, log_label="C-namespace"
            ),
            discovery_method="entry_id_range",
        )

    # Well-known W-namespace paths in new-scheme archives. The
    # ``has_entry_by_path`` probe is unreliable here — most Wikipedia
    # ZIMs return False for ``W/mainPage`` even when ``archive.main_entry``
    # resolves correctly, because the main page is stored under its
    # canonical C-namespace path and exposed via libzim's well-known-entry
    # APIs rather than as a literal ``W/`` entry. Auxiliary probes
    # (``W/index``, ``W/robots.txt`` etc.) cover archives that DO carry
    # extra well-known entries directly.
    _NEW_SCHEME_W_AUX_CANDIDATES = (
        "W/index",
        "W/robots.txt",
        "W/exception.html",
        "W/404.html",
    )

    def _browse_new_scheme_w_paginated(
        self,
        archive: Archive,
        namespace: str,
        limit: int,
        offset: int,
    ) -> Dict[str, Any]:
        """Enumerate new-scheme W-namespace entries via the same probes
        ``list_namespaces`` uses.

        D2 (v2.0.0a9): the original D3 fix probed
        ``archive.has_entry_by_path("W/mainPage")`` etc., which returns
        False on real Wikipedia archives even when the main entry
        exists — the path isn't a literal entry, it's a well-known
        alias resolved via ``archive.main_entry``. The result was
        ``list_namespaces`` reporting W=2 and ``browse_namespace W``
        reporting empty, with no way for a small model to reconcile.

        This rewrite asks the SAME questions ``list_namespaces`` does
        (``has_main_entry``, ``has_illustration()``) and synthesises
        the corresponding ``W/mainPage`` / ``W/favicon`` rows. Auxiliary
        candidates (``W/index``, ``W/robots.txt``) still get the
        ``has_entry_by_path`` probe because they ARE stored as literal
        entries when present.
        """
        present: List[str] = []
        # Synthetic well-known entries — resolved through libzim's
        # dedicated APIs at materialisation time, not by path lookup.
        try:
            if getattr(archive, "has_main_entry", False):
                present.append("W/mainPage")
        except Exception as e:
            logger.debug(f"has_main_entry probe failed: {e}")
        try:
            if archive.has_illustration():
                present.append("W/favicon")
        except Exception as e:
            logger.debug(f"has_illustration probe failed: {e}")
        # Auxiliary literal W entries — when present they ARE addressable
        # by path. Wikipedia maxi ZIMs rarely carry these but other
        # ZIM flavours (e.g. some scraped sites) do.
        for path in self._NEW_SCHEME_W_AUX_CANDIDATES:
            try:
                if archive.has_entry_by_path(path):
                    present.append(path)
            except Exception as e:
                logger.debug(f"has_entry_by_path probe failed for {path}: {e}")
        return self._new_scheme_browse_payload(
            namespace=namespace,
            total=len(present),
            offset=offset,
            limit=limit,
            entries=self._materialise_paths(
                archive, present[offset : offset + limit], log_label="W-namespace"
            ),
            discovery_method="known_path_probe",
        )

    def _materialise_browse_entry(
        self, archive: Archive, entry_path: str, has_new_scheme: bool
    ) -> Optional[Dict[str, Any]]:
        """Render one browse_namespace row for ``entry_path``.

        New-scheme metadata entries (paths shaped ``M/<key>``) aren't on
        libzim's regular entry surface — they're reached via
        ``archive.get_metadata_item``. Without this branch a new-scheme
        ``browse_namespace('M', ...)`` would error on every row.

        Synthetic ``W/mainPage`` / ``W/favicon`` rows (D2) similarly
        route through dedicated libzim well-known-entry APIs because
        those paths aren't literal entries on most new-scheme archives.
        """
        if has_new_scheme and entry_path.startswith("M/"):
            return self._materialise_new_scheme_metadata_entry(archive, entry_path)
        if has_new_scheme and entry_path == "W/mainPage":
            return self._materialise_new_scheme_main_entry(archive)
        if has_new_scheme and entry_path == "W/favicon":
            return self._materialise_new_scheme_favicon(archive)

        entry = archive.get_entry_by_path(entry_path)
        title = entry.title or entry_path
        preview, content_type = self._render_entry_preview(entry, entry_path)
        return {
            "path": entry_path,
            "title": title,
            "content_type": content_type,
            "preview": preview,
        }

    def _materialise_new_scheme_main_entry(
        self, archive: Archive
    ) -> Optional[Dict[str, Any]]:
        """Render the synthetic ``W/mainPage`` row.

        Resolves through ``archive.main_entry`` (libzim's well-known
        entry API) — the canonical target may live anywhere in C, so
        we render its actual path/title rather than a synthetic
        placeholder. Following the redirect chain is intentional: the
        ``main_entry`` value is typically a redirect to the actual
        landing page.
        """
        try:
            entry = archive.main_entry
        except Exception as e:
            logger.debug(f"main_entry resolution failed: {e}")
            return None
        # Follow the redirect chain so the rendered row points at the
        # actual page rather than the redirect stub.
        hops = 0
        seen: set = set()
        try:
            while getattr(entry, "is_redirect", False) and hops < 10:
                p = getattr(entry, "path", None)
                if p is None or p in seen:
                    break
                seen.add(p)
                entry = entry.get_redirect_entry()
                hops += 1
        except Exception as redirect_err:
            # Best-effort redirect chase: if a hop raises (e.g. a stale
            # redirect entry on a partially-rewritten archive), fall back
            # to the last resolved ``entry`` rather than failing the whole
            # main-page lookup.
            logger.debug(f"main_entry redirect chase aborted: {redirect_err}")
        title = getattr(entry, "title", None) or "Main Page"
        try:
            preview, content_type = self._render_entry_preview(entry, "W/mainPage")
        except Exception:
            preview, content_type = "", "text/html"
        return {
            "path": "W/mainPage",
            "title": title,
            "content_type": content_type,
            "preview": preview,
        }

    @staticmethod
    def _materialise_new_scheme_favicon(
        archive: Archive,
    ) -> Optional[Dict[str, Any]]:
        """Render the synthetic ``W/favicon`` row.

        Pulls the illustration item's mimetype via
        ``archive.get_illustration_item`` without dereferencing the
        bytes — favicons can be tens of KB and rendering them as a
        preview adds nothing useful.
        """
        content_type = "image/png"
        try:
            item = archive.get_illustration_item(48)
            if item and item.mimetype:
                content_type = item.mimetype
        except Exception as e:
            logger.debug(f"get_illustration_item failed: {e}")
        return {
            "path": "W/favicon",
            "title": "favicon",
            "content_type": content_type,
            "preview": "(archive favicon)",
        }

    def _materialise_new_scheme_metadata_entry(
        self, archive: Archive, entry_path: str
    ) -> Optional[Dict[str, Any]]:
        key = entry_path.split("/", 1)[1] if "/" in entry_path else entry_path
        try:
            item = archive.get_metadata_item(key)
        except Exception as e:
            logger.debug(f"get_metadata_item failed for {key}: {e}")
            return None
        content_type = (item.mimetype or "unknown") if item else "unknown"
        preview = ""
        try:
            if item and item.mimetype and item.mimetype.startswith("text/"):
                raw = bytes(item.content)
                preview = self.content_processor.create_snippet(
                    self.content_processor.process_mime_content(raw, item.mimetype),
                    max_paragraphs=1,
                )
            elif item:
                preview = f"({content_type} content)"
        except Exception as e:
            logger.debug(f"metadata preview failed for {key}: {e}")
            preview = "(Preview unavailable)"
        return {
            "path": entry_path,
            "title": key,
            "content_type": content_type,
            "preview": preview,
        }

    def _render_entry_preview(self, entry: Any, entry_path: str) -> Tuple[str, str]:
        """Return (preview_text, content_type) for a regular entry."""
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
            return preview, content_type
        except Exception as e:
            logger.debug(f"Error getting preview for {entry_path}: {e}")
            return "(Preview unavailable)", ""

    def _find_entries_in_namespace(
        self, archive: Archive, namespace: str, has_new_scheme: bool
    ) -> Tuple[List[str], bool]:
        """Find entries in a specific namespace.

        Returns ``(sorted_paths, full_iteration)`` where ``full_iteration`` is
        True when every entry in the archive was inspected (so the result is
        exhaustive). For larger archives, falls back to random sampling and
        returns False — counts/paths are then a lower bound.

        New-scheme dispatch: M is enumerated from ``archive.metadata_keys``
        (full iteration, exhaustive); namespaces other than C/M return empty
        because libzim's iterable surface only exposes C in this scheme.
        """
        if has_new_scheme:
            if namespace == "M":
                paths = self._enumerate_new_scheme_metadata(archive)
                return sorted(paths), True
            if namespace != "C":
                # Other namespaces (W, X, etc.) aren't on the iterable surface;
                # return empty rather than path-prefix-matching them into
                # nonsense buckets.
                return [], True
            # New-scheme + C: every iterable entry is in C, so full iteration
            # is the right call regardless of archive size. Sampling here was
            # wasteful (same per-entry cost) and produced misleading
            # ``total_in_namespace`` values capped at the sample size.
            entries = self._enumerate_namespace_entries(
                archive, namespace, archive.entry_count, has_new_scheme=True
            )
            return sorted(entries), True

        total_entries = archive.entry_count

        # Full iteration is exhaustive and far more accurate than sampling for
        # small archives. The threshold mirrors _list_archive_namespaces.
        if total_entries <= NAMESPACE_MAX_SAMPLE_SIZE:
            entries = self._enumerate_namespace_entries(
                archive, namespace, total_entries, has_new_scheme=has_new_scheme
            )
            return sorted(entries), True

        sampled, seen = self._sample_namespace_entries(
            archive, namespace, has_new_scheme=has_new_scheme
        )
        self._extend_with_pattern_probes(
            archive, namespace, sampled, seen, has_new_scheme=has_new_scheme
        )
        return sorted(sampled), False

    @staticmethod
    def _enumerate_new_scheme_metadata(archive: Archive) -> List[str]:
        """Build M/<key> paths from archive.metadata_keys for new-scheme."""
        try:
            keys = list(getattr(archive, "metadata_keys", []) or [])
        except Exception as e:
            logger.debug(f"Unable to read metadata_keys: {e}")
            return []
        return [f"M/{k}" for k in keys]

    def _enumerate_namespace_entries(
        self,
        archive: Archive,
        namespace: str,
        total_entries: int,
        has_new_scheme: bool = False,
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
                if (
                    self._extract_namespace_from_path(
                        path, has_new_scheme=has_new_scheme
                    )
                    == namespace
                ):
                    results.append(path)
            except Exception as e:
                logger.debug(f"Error reading entry {entry_id}: {e}")
        logger.info(
            f"Found {len(results)} entries in namespace '{namespace}' via full "
            f"iteration of {total_entries} entries"
        )
        return results

    def _sample_namespace_entries(
        self, archive: Archive, namespace: str, has_new_scheme: bool = False
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
                if (
                    self._extract_namespace_from_path(
                        path, has_new_scheme=has_new_scheme
                    )
                    == namespace
                ):
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
        has_new_scheme: bool = False,
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
                    and self._extract_namespace_from_path(
                        pattern, has_new_scheme=has_new_scheme
                    )
                    == namespace
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

    def walk_namespace_data(
        self,
        zim_file_path: str,
        namespace: str,
        cursor_state: Optional[Dict[str, Any]] = None,
        limit: int = 200,
    ) -> "WalkNamespaceResponse":
        """Structured variant of ``walk_namespace``.

        Returns the result dict directly (not a JSON string) so MCP tools
        can hand it straight to FastMCP's structured-content path.

        Phase B contract: top-level ``results`` / ``next_cursor`` (opaque
        str) / ``total`` (always None — walk doesn't know the per-namespace
        total mid-scan) / ``done`` / ``page_info`` plus ``namespace`` /
        ``scanned_count`` / ``scanned_through_id`` / ``archive_entry_count``
        extras. ``next_cursor`` is encoded with ``tool="walk_namespace"``
        and state ``{scan_at, l}``.

        ``cursor_state`` carries the decoded ``s`` dict from a v2 cursor.
        The tool layer is responsible for decoding the opaque wire token;
        this method works with the decoded shape directly so non-tool
        callers (legacy ``walk_namespace`` JSON wrapper, simple_tools)
        don't have to round-trip through base64.

        Raises:
            OpenZimMcpValidationError: If ``limit`` is outside ``1..500``.
        """
        from openzim_mcp.pagination import Cursor

        # Caller-input validation surfaces as OpenZimMcpValidationError so
        # the tool layer can render a targeted validation message and so
        # other call sites (e.g. simple_tools) can distinguish it from
        # archive-access failures.
        if limit < 1 or limit > 500:
            raise OpenZimMcpValidationError(
                f"limit must be between 1 and 500 (provided: {limit})"
            )

        # Decoded cursor state ``s`` for walk_namespace carries
        # ``{scan_at: int, l: int, ns: str, ai: str}``. ``scan_at``/``l``
        # are positional, ``ns``/``ai`` are integrity-check fields added
        # in cursor v2.
        scan_at_raw = (cursor_state or {}).get("scan_at", 0)
        try:
            scan_at = int(scan_at_raw)
        except (TypeError, ValueError):
            scan_at = 0
        if scan_at < 0:
            scan_at = 0

        # Canonicalise user input (e.g. "c" -> "C") so the comparison
        # against ``_extract_namespace_from_path`` (canonical form) does
        # not silently iterate to completion with zero matches.
        if namespace:
            namespace = self._canonicalise_namespace(namespace.strip())

        validated = self.path_validator.validate_path(zim_file_path)
        validated = self.path_validator.validate_zim_file(validated)

        # Cursor integrity: a v2 cursor encodes the namespace it was
        # issued for and the archive identity. Rejecting on mismatch
        # prevents silent wrong-result bugs where a caller resubmits a
        # cursor against a different namespace or different archive
        # (issues Phase B #10, #17, #11 for the equivalent pattern in
        # extract_article_links).
        if cursor_state:
            from openzim_mcp.pagination import Cursor as _CursorClass
            from openzim_mcp.pagination import (
                CursorMismatchError,
                archive_identity,
            )

            cursor_ns = cursor_state.get("ns")
            if cursor_ns is not None and cursor_ns != namespace:
                raise OpenZimMcpValidationError(
                    f"Cursor was issued for namespace {cursor_ns!r}; "
                    f"call passed namespace={namespace!r}. Drop the cursor "
                    f"and start the walk over for the new namespace."
                )
            # H16: always verify ``ai``. The old ``if "ai" in cursor_state``
            # guard skipped the check when a cursor lacked the field — but
            # v=2 cursors always carry ``ai``, so the only way to miss it
            # is a hand-crafted (or v=1, now rejected by Cursor.decode)
            # token. ``verify_archive_identity`` itself raises a clear
            # ``CursorMismatchError`` on absent ``ai``; relying on that
            # makes the cross-archive guard unconditional.
            try:
                _CursorClass.verify_archive_identity(
                    cast("Any", cursor_state),
                    expected=archive_identity(validated),
                    tool="walk_namespace",
                )
            except CursorMismatchError as e:
                raise OpenZimMcpValidationError(str(e)) from e

        try:
            with _zim_ops_mod.zim_archive(validated) as archive:
                has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)

                archive_entry_count = archive.entry_count

                # New-scheme M is sourced from metadata_keys, not the entry
                # iterator (which only surfaces C). Hand the request to a
                # dedicated walker so callers see real metadata entries
                # instead of zero matches after a full archive scan.
                if has_new_scheme and namespace == "M":
                    return cast(
                        "WalkNamespaceResponse",
                        attach_meta(
                            self._walk_new_scheme_metadata(
                                archive,
                                scan_at,
                                limit,
                                archive_entry_count,
                                validated_path=validated,
                            )
                        ),
                    )
                # D8 (beta): symmetric handling for W namespace. The
                # well-known entries (mainPage, favicon) are reachable via
                # ``archive.main_entry`` / ``archive.has_illustration()``
                # — not the iterable surface that ``walk_namespace_data``
                # falls back to below. Without this branch, ``walk
                # namespace W`` returned an empty result while the
                # sibling ``list namespaces`` operation simultaneously
                # advertised W has 2 entries (via the same probes used
                # here in ``_add_new_scheme_well_known_namespace``).
                # The two ops were contradicting each other on the same
                # archive — now they agree.
                if has_new_scheme and namespace == "W":
                    return cast(
                        "WalkNamespaceResponse",
                        attach_meta(
                            self._walk_new_scheme_well_known(
                                archive,
                                scan_at,
                                limit,
                                archive_entry_count,
                                validated_path=validated,
                            )
                        ),
                    )
                # Other-than-C namespaces in new-scheme aren't on the
                # iterable surface; short-circuit so callers don't pay the
                # full-archive scan to discover that.
                if has_new_scheme and namespace != "C":
                    return cast(
                        "WalkNamespaceResponse",
                        attach_meta(
                            self._build_walk_result(
                                namespace=namespace,
                                scan_at=scan_at,
                                limit=limit,
                                entries=[],
                                scanned_count=0,
                                scanned_through_id=None,
                                done=True,
                                next_cursor=None,
                                archive_entry_count=archive_entry_count,
                            )
                        ),
                    )

                entries: List[Dict[str, Any]] = []
                entry_id = scan_at
                while entry_id < archive_entry_count and len(entries) < limit:
                    try:
                        entry = archive._get_entry_by_id(entry_id)
                        path = entry.path
                        if (
                            self._extract_namespace_from_path(
                                path, has_new_scheme=has_new_scheme
                            )
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

                done = entry_id >= archive_entry_count
                # scanned_through_id reflects the last ID we examined regardless
                # of whether it matched the filter. None if we never entered the
                # loop (scan_at was already at/past the end).
                scanned_through_id = entry_id - 1 if entry_id > scan_at else None
                next_cursor: Optional[str] = None
                if not done:
                    from openzim_mcp.pagination import archive_identity

                    next_cursor = Cursor.encode(
                        tool="walk_namespace",
                        state={
                            "scan_at": entry_id,
                            "l": limit,
                            "ns": namespace,
                            "ai": archive_identity(validated),
                        },
                    )

                # A11 post-a11 M3: surface a per-namespace denominator
                # for new-scheme C as well. M / W already plumb their
                # bounded totals (metadata_keys length / well-known
                # probe pair); for new-scheme C the iterable surface
                # IS the C-namespace, so ``archive.entry_count`` is
                # the authoritative count and the renderer can read
                # "of N in namespace C" instead of the misleading
                # "archive total: ~27M" header that the empty-default
                # fall-through produces.
                ns_count_c = (
                    archive_entry_count if has_new_scheme and namespace == "C" else None
                )
                return cast(
                    "WalkNamespaceResponse",
                    attach_meta(
                        self._build_walk_result(
                            namespace=namespace,
                            scan_at=scan_at,
                            limit=limit,
                            entries=entries,
                            scanned_count=entry_id - scan_at,
                            scanned_through_id=scanned_through_id,
                            done=done,
                            next_cursor=next_cursor,
                            archive_entry_count=archive_entry_count,
                            namespace_entry_count=ns_count_c,
                        )
                    ),
                )
        except OpenZimMcpArchiveError:
            raise
        except Exception as e:
            raise OpenZimMcpArchiveError(f"walk_namespace failed: {e}") from e

    @staticmethod
    def _build_walk_result(
        *,
        namespace: str,
        scan_at: int,
        limit: int,
        entries: List[Dict[str, Any]],
        scanned_count: int,
        scanned_through_id: Optional[int],
        done: bool,
        next_cursor: Optional[str],
        archive_entry_count: int,
        namespace_entry_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Assemble the walk_namespace v2 contract result dict.

        Five-key contract (``results`` / ``next_cursor`` / ``total`` /
        ``done`` / ``page_info``) plus walk-specific extras.

        ``total`` is always None: walk_namespace doesn't know the
        per-namespace total mid-scan for the iterable C-namespace path.
        Callers that need a count can use ``browse_namespace`` (sampled)
        or wait for ``done=True``.

        A11 F4 (post-a10 second pass): the M and W well-known walks
        know the bounded total ahead of time (``metadata_keys`` length;
        main_entry / illustration probe pair). Surface it as
        ``namespace_entry_count`` so the renderer can report a per-
        namespace denominator instead of the archive-wide ``of ~27M``
        scale hint that mismatches a 2- or 13-entry namespace.

        ``archive_entry_count`` is the file-level entry count, distinct
        from the (unknown for C, known for M/W) namespace count.
        """
        returned_count = len(entries)
        payload: Dict[str, Any] = {
            "namespace": namespace,
            "results": entries,
            "next_cursor": next_cursor,
            "total": None,
            "done": done,
            "page_info": {
                "offset": scan_at,
                "limit": limit,
                "returned_count": returned_count,
            },
            "scanned_count": scanned_count,
            "scanned_through_id": scanned_through_id,
            "archive_entry_count": archive_entry_count,
        }
        if namespace_entry_count is not None:
            payload["namespace_entry_count"] = namespace_entry_count
        return payload

    @classmethod
    def _walk_new_scheme_metadata(
        cls,
        archive: Archive,
        scan_at: int,
        limit: int,
        archive_entry_count: int,
        *,
        validated_path: "Optional[Path]" = None,
    ) -> Dict[str, Any]:
        """Walk M (metadata) entries in a new-scheme archive via metadata_keys."""
        from openzim_mcp.pagination import Cursor, archive_identity

        try:
            keys = [
                k
                for k in (getattr(archive, "metadata_keys", []) or [])
                # A11 post-a11 M1: same filter the metadata-for aggregator
                # uses (Archive._extract_zim_metadata) so the two surfaces
                # agree on what counts as a metadata key. Without this,
                # walk reported 13 entries (incl. binary illustration)
                # while metadata-for reported 12.
                if is_human_readable_metadata_key(k)
            ]
        except Exception as e:
            logger.debug(f"metadata_keys read failed: {e}")
            keys = []
        total = len(keys)
        start = scan_at
        end = min(start + limit, total)
        entries = [{"path": f"M/{k}", "title": k} for k in keys[start:end]]
        done = end >= total
        next_cursor: Optional[str] = None
        if not done:
            # ``scan_at`` here is an index into ``metadata_keys``, not an
            # entry ID. The cursor's ``ns="M"`` discriminator + the
            # archive's new-scheme bit are enough for the consumer to
            # know which interpretation to use; see #17.
            state: Dict[str, Any] = {"scan_at": end, "l": limit, "ns": "M"}
            if validated_path is not None:
                state["ai"] = archive_identity(validated_path)
            next_cursor = Cursor.encode(
                tool="walk_namespace",
                state=cast("Any", state),
            )
        return cls._build_walk_result(
            namespace="M",
            scan_at=scan_at,
            limit=limit,
            entries=entries,
            scanned_count=end - start,
            scanned_through_id=end - 1 if end > start else None,
            done=done,
            next_cursor=next_cursor,
            archive_entry_count=archive_entry_count,
            # F4: M is bounded by metadata_keys length, so surface
            # the real namespace total to the renderer.
            namespace_entry_count=total,
        )

    @classmethod
    def _walk_new_scheme_well_known(
        cls,
        archive: Archive,
        scan_at: int,
        limit: int,
        archive_entry_count: int,
        *,
        validated_path: "Optional[Path]" = None,
    ) -> Dict[str, Any]:
        """D8 (beta): walk W (well-known) entries via canonical probes.

        Mirrors ``_walk_new_scheme_metadata`` but the source is the
        ``has_main_entry`` / ``has_illustration`` probe pair that
        ``_add_new_scheme_well_known_namespace`` already uses for the
        namespace listing. Keeps the two operations consistent for
        new-scheme archives: ``list namespaces`` says W has 2 entries
        and ``walk namespace W`` now actually surfaces them.
        """
        from openzim_mcp.pagination import Cursor, archive_identity

        probes: List[Tuple[str, str]] = []
        # Same suppress-on-failure semantics as the namespace listing
        # probe; W is informational, never load-bearing.
        with contextlib.suppress(Exception):
            if getattr(archive, "has_main_entry", False):
                probes.append(("W/mainPage", "mainPage"))
        with contextlib.suppress(Exception):
            if archive.has_illustration():
                probes.append(("W/favicon", "favicon"))

        total = len(probes)
        start = scan_at
        end = min(start + limit, total)
        entries = [{"path": p, "title": t} for p, t in probes[start:end]]
        done = end >= total
        next_cursor: Optional[str] = None
        if not done:
            state: Dict[str, Any] = {"scan_at": end, "l": limit, "ns": "W"}
            if validated_path is not None:
                state["ai"] = archive_identity(validated_path)
            next_cursor = Cursor.encode(
                tool="walk_namespace",
                state=cast("Any", state),
            )
        return cls._build_walk_result(
            namespace="W",
            scan_at=scan_at,
            limit=limit,
            entries=entries,
            scanned_count=end - start,
            scanned_through_id=end - 1 if end > start else None,
            done=done,
            next_cursor=next_cursor,
            archive_entry_count=archive_entry_count,
            # F4: W is bounded by the well-known probe pair length.
            namespace_entry_count=total,
        )

    def walk_namespace(
        self,
        zim_file_path: str,
        namespace: str,
        cursor: Optional[Dict[str, Any]] = None,
        limit: int = 200,
    ) -> str:
        """Legacy JSON-string variant of ``walk_namespace_data``.

        Walk every entry in a namespace by entry ID, with cursor pagination.

        Unlike browse_namespace (which samples), this iterates the archive
        deterministically from ``cursor`` onward and returns up to ``limit``
        entries that belong to the requested namespace. Pair the returned
        ``next_cursor`` with a follow-up call to walk the rest. Set to None
        when iteration is complete.

        Args:
            zim_file_path: Path to the ZIM file
            namespace: Namespace to walk (C, M, W, X, A, I, etc.)
            cursor: Decoded cursor-state dict (e.g.
                ``{"scan_at": 42, "l": 200}``). ``None`` starts from the
                beginning. Tool callers should prefer the MCP
                ``walk_namespace`` tool which accepts an opaque wire
                cursor and decodes for you.
            limit: Maximum entries to return per page (1–500, default 200)

        Returns:
            JSON containing entries in the namespace, the next cursor, and
            ``done: true`` if iteration finished

        Raises:
            OpenZimMcpValidationError: If ``limit`` is outside ``1..500``.
        """
        return json.dumps(
            self.walk_namespace_data(
                zim_file_path, namespace, cursor_state=cursor, limit=limit
            ),
            indent=2,
            ensure_ascii=False,
        )
