"""Cross-encoder reranking for :class:`SimpleToolsHandler`.

Extracted from ``simple_tools.py`` (post-v2.0.5 review sweep) as a mixin,
following the ``zim`` package's split of ``ZimOperations`` across
``_ContentMixin`` / ``_SearchMixin`` / etc.

Holds the Phase D sub-D-1 reranker telemetry event names and the methods
that drive the optional FastEmbed cross-encoder rerank (engaged only when
the ``[reranker]`` extra is installed). The event-name constants live here
rather than in ``simple_tools`` because both the rerank methods AND the core
``_track`` / ``handle_zim_query`` snapshot logic reference them — keeping
them next to the reranker logic and importing back avoids the circular
import that the reverse direction would create.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Names this module deliberately exports to ``simple_tools`` (the reranker
# telemetry contract + the mixin). Declaring it documents the cross-module
# export the docstring describes and tells static analysis these module-level
# constants are intentionally consumed elsewhere — notably
# ``_INFO_LEVEL_TELEMETRY_EVENTS``, whose only reader is ``simple_tools``.
__all__ = [
    "_INFO_LEVEL_TELEMETRY_EVENTS",
    "_RERANKER_ENGAGED",
    "_RERANKER_SKIPPED_NO_RESULTS",
    "_RERANKER_SKIPPED_NOT_INSTALLED",
    "_RERANKER_SKIPPED_PASSTHROUGH",
    "_RerankMixin",
]

# Phase D sub-D-1 reranker telemetry events.
_RERANKER_ENGAGED = "reranker_engaged"
_RERANKER_SKIPPED_NOT_INSTALLED = "reranker_skipped.not_installed"
_RERANKER_SKIPPED_NO_RESULTS = "reranker_skipped.no_results"
_RERANKER_SKIPPED_PASSTHROUGH = "reranker_skipped.passthrough"

# Telemetry events that also emit an INFO log on every increment. The
# in-memory counter is only visible via ``get_server_health`` (advanced
# tool mode); operators running in simple mode have no other way to see
# reranker engagement. Keep this set small — every entry is a per-query
# INFO line.
_INFO_LEVEL_TELEMETRY_EVENTS: "frozenset[str]" = frozenset(
    {
        _RERANKER_ENGAGED,
        _RERANKER_SKIPPED_NOT_INSTALLED,
        _RERANKER_SKIPPED_NO_RESULTS,
        _RERANKER_SKIPPED_PASSTHROUGH,
    }
)


class _RerankMixin:
    """Cross-encoder rerank methods for ``SimpleToolsHandler``.

    The telemetry counter, ``_track`` and ``zim_operations`` are supplied
    by the concrete ``SimpleToolsHandler`` that mixes this in.
    """

    if TYPE_CHECKING:
        from collections import Counter

        from .zim_operations import ZimOperations

        zim_operations: "ZimOperations"
        _telemetry: "Counter[str]"

        def _track(self, event: str) -> None: ...

    def _compute_rerank_state(self, before: Dict[str, int]) -> Optional[str]:
        """Post-b1: compute the per-request reranker engagement state
        from a pre-call snapshot of the four reranker counters.

        Returns one of ``engaged`` / ``skipped:not_installed`` /
        ``skipped:no_results`` / ``skipped:passthrough`` when the
        current request bumped a counter, else ``None`` (non-search
        intent, no rerank attempt). Surfaced as
        ``<!-- reranker=<state> -->`` in the response envelope so
        callers using the simple-tool surface alone (without access
        to ``get_server_health``) can confirm whether D-1's
        cross-encoder rerank actually engaged. Priority order
        favours ``engaged`` then the more specific skip reasons so
        a request that hits both ``no_results`` and ``passthrough``
        (rare; multi-archive partial failure) is summarised
        unambiguously."""
        order = (
            _RERANKER_ENGAGED,
            _RERANKER_SKIPPED_NOT_INSTALLED,
            _RERANKER_SKIPPED_NO_RESULTS,
            _RERANKER_SKIPPED_PASSTHROUGH,
        )
        labels = {
            _RERANKER_ENGAGED: "engaged",
            _RERANKER_SKIPPED_NOT_INSTALLED: "skipped:not_installed",
            _RERANKER_SKIPPED_NO_RESULTS: "skipped:no_results",
            _RERANKER_SKIPPED_PASSTHROUGH: "skipped:passthrough",
        }
        for event in order:
            if self._telemetry.get(event, 0) > before.get(event, 0):
                return labels[event]
        return None

    def _maybe_rerank_compact(
        self,
        *,
        payload: Dict[str, Any],
        query: str,
        limit: Optional[int],
        results_key: str = "results",
    ) -> Dict[str, Any]:
        """Apply cross-encoder rerank to a compact-mode search payload.

        Reads ``payload[results_key]`` as the candidate list, reranks via
        ``BGEReranker.get()``, emits telemetry, and returns the payload with
        the reranked results. No-op when the [reranker] extra is absent
        or the result list is empty.

        Returns the payload (possibly the same dict, with results swapped).
        """
        from openzim_mcp.ml.reranker import BGEReranker

        reranker_cfg = self.zim_operations.config.ml.reranker
        reranker = BGEReranker.get(reranker_cfg)
        candidates = payload.get(results_key, [])

        if reranker is None:
            self._track(_RERANKER_SKIPPED_NOT_INSTALLED)
            return payload
        if not candidates:
            self._track(_RERANKER_SKIPPED_NO_RESULTS)
            return payload

        if limit is not None and limit > 0:
            effective_top_k = min(limit, reranker_cfg.final_top_k)
        else:
            effective_top_k = reranker_cfg.final_top_k

        reranked = reranker.rerank(
            query=query,
            candidates=candidates,
            top_k=effective_top_k,
        )
        payload = {**payload, results_key: reranked}
        if reranked and "rerank_score" in reranked[0]:
            self._track(_RERANKER_ENGAGED)
        else:
            self._track(_RERANKER_SKIPPED_PASSTHROUGH)
        return payload

    @staticmethod
    def _flatten_archive_hits(
        per_file: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Flatten per-archive hits into a single tagged list for global rerank."""
        tagged: List[Dict[str, Any]] = []
        for entry_idx, entry in enumerate(per_file):
            if entry.get("error") or not isinstance(entry.get("result"), dict):
                continue
            for hit in entry["result"].get("results") or []:
                tagged.append({**hit, "_rerank_src_idx": entry_idx})
        return tagged

    @staticmethod
    def _redistribute_reranked_hits(
        per_file: List[Dict[str, Any]],
        reranked_tagged: List[Dict[str, Any]],
    ) -> None:
        """Group reranked tagged hits back into per-archive buckets in place.

        Strips the ``_rerank_src_idx`` tag and updates each entry's ``results``
        + ``has_hits`` fields. Mutates ``per_file``."""
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for hit in reranked_tagged:
            src_idx = hit.get("_rerank_src_idx", -1)
            clean = {k: v for k, v in hit.items() if k != "_rerank_src_idx"}
            grouped.setdefault(src_idx, []).append(clean)
        for entry_idx, entry in enumerate(per_file):
            if entry.get("error") or not isinstance(entry.get("result"), dict):
                continue
            new_hits = grouped.get(entry_idx, [])
            entry["result"] = {**entry["result"], "results": new_hits}
            entry["has_hits"] = bool(new_hits)

    def _maybe_rerank_search_all(
        self,
        *,
        per_file: List[Dict[str, Any]],
        query: str,
    ) -> List[Dict[str, Any]]:
        """Cross-archive rerank for _handle_search_all.

        Flattens hits from all non-error archives into a single candidate list
        (tagged with ``_rerank_src_idx`` to track origin), reranks globally,
        then redistributes back to per-archive buckets in the reranked order.

        Mutates ``per_file`` entries in place and returns the list.
        No-op when the [reranker] extra is absent or there are no candidates.
        """
        from openzim_mcp.ml.reranker import BGEReranker

        reranker_cfg = self.zim_operations.config.ml.reranker
        reranker = BGEReranker.get(reranker_cfg)
        tagged_hits = self._flatten_archive_hits(per_file)

        if reranker is None:
            self._track(_RERANKER_SKIPPED_NOT_INSTALLED)
            return per_file
        if not tagged_hits:
            self._track(_RERANKER_SKIPPED_NO_RESULTS)
            return per_file

        reranked_tagged = reranker.rerank(
            query=query,
            candidates=tagged_hits,
            top_k=reranker_cfg.final_top_k,
        )
        self._redistribute_reranked_hits(per_file, reranked_tagged)
        scored = bool(reranked_tagged and "rerank_score" in reranked_tagged[0])
        self._track(_RERANKER_ENGAGED if scored else _RERANKER_SKIPPED_PASSTHROUGH)
        return per_file
