"""Cross-encoder reranker (Phase D sub-D-1).

Lazy singleton wrapping FastEmbed's TextCrossEncoder. The whole module
imports cheaply (no `import fastembed` at top level); the actual library
import lives inside `_load_model`, which only runs when the
`[reranker]` extra is installed AND the user actually hits a rerank
code path."""

from __future__ import annotations

import logging
import os
import queue
import threading
from pathlib import Path
from typing import (
    Any,
    List,
    Optional,
    Sequence,
    Tuple,
)

from openzim_mcp.config import RerankerConfig
from openzim_mcp.ml import detect
from openzim_mcp.ml.fallback import ml_fallback

logger = logging.getLogger(__name__)


def _load_model(
    model_id: str, cache_dir: Optional[Path], *, allow_download: bool = True
) -> Any:
    """Lazy import + load. Called inside BGEReranker.get(). Kept as a
    module-level function so tests can mock it cleanly.

    ``allow_download`` defaults to True because the only callers that omit
    it are the ones whose whole job is to populate the cache (the
    ``openzim-mcp download-models`` CLI and the live-model test fixture).
    The serving path always passes ``cfg.allow_model_download``, which
    defaults to False — see RerankerConfig for why.
    """
    from fastembed.rerank.cross_encoder import (  # type: ignore[import-not-found]
        TextCrossEncoder,
    )

    kwargs: dict[str, Any] = {"model_name": model_id}
    if cache_dir is not None:
        kwargs["cache_dir"] = str(cache_dir)
    # local_files_only is the portable switch: FastEmbed has accepted it
    # since 0.4.0, our declared floor. HF_HUB_OFFLINE would have been
    # simpler but FastEmbed only started honouring it well after 0.4.x, so
    # it would silently no-op across most of the range pyproject.toml admits.
    kwargs["local_files_only"] = not allow_download
    return TextCrossEncoder(**kwargs)


def _rerank_passthrough(
    _self: "BGEReranker",
    query: str,
    candidates: List[dict[str, Any]],
    top_k: int,
) -> List[dict[str, Any]]:
    """Fallback for `BGEReranker.rerank` inference failures.

    Returns candidates sliced to top_k without rerank_score, preserving
    Xapian's original ordering. Matches the skip-on-short-query gate's
    response shape so callers see identical behavior on both bypass paths.
    """
    return candidates[:top_k]


class BGEReranker:
    """Singleton wrapper around FastEmbed's cross-encoder reranker.

    Use `BGEReranker.get(config)` to fetch an instance — returns None
    when the `[reranker]` extra is missing or the kill switch fired.
    Subsequent calls hit the cached instance."""

    _instance: Optional["BGEReranker"] = None
    _instance_lock: threading.Lock = threading.Lock()
    _load_failed: bool = (
        False  # Tripped on first load failure; never cleared except by reset_instance.
    )

    def __init__(self, model: Any, config: RerankerConfig) -> None:
        self._model = model
        self._config = config

    @classmethod
    def reset_instance(cls) -> None:
        """For tests only."""
        with cls._instance_lock:
            cls._instance = None
            cls._load_failed = False

    def score_pairs(self, pairs: Sequence[Tuple[str, str]]) -> List[float]:
        """Batch-score (query, passage) pairs.

        Empty input → empty output. Query and passage are truncated at
        the configured max lengths before being passed to FastEmbed."""
        if not pairs:
            return []
        # Group by query so we make one rerank call per distinct query.
        # In practice all pairs share the same query (rerank is called
        # per search), so this collapses to a single batch.
        by_query: dict[str, List[int]] = {}
        truncated_passages: List[str] = []
        for idx, (q, p) in enumerate(pairs):
            q_trim = q[: self._config.max_query_length]
            p_trim = p[: self._config.max_passage_length]
            by_query.setdefault(q_trim, []).append(idx)
            truncated_passages.append(p_trim)
        scores: List[float] = [0.0] * len(pairs)
        for q, idxs in by_query.items():
            passages = [truncated_passages[i] for i in idxs]
            batch_scores = list(self._model.rerank(q, passages))
            for i, s in zip(idxs, batch_scores):
                scores[i] = float(s)
        return scores

    @ml_fallback(
        feature="reranker_inference",
        on_failure=_rerank_passthrough,
    )
    def rerank(
        self,
        query: str,
        candidates: List[dict[str, Any]],
        top_k: int,
    ) -> List[dict[str, Any]]:
        """Rerank candidate envelopes against `query`, slice top_k.

        Skip rules:
          * Query has fewer than `min_query_tokens` whitespace-separated
            tokens → return candidates unchanged (input order preserved),
            no `rerank_score` added.
          * Empty candidates → empty result.

        On rerank, each candidate gains a `rerank_score: float` field.
        The original `xapian_score` (if present) is preserved."""
        if not candidates:
            return []
        # Skip-on-short-query gate.
        if self._config.min_query_tokens > 0:
            token_count = len(query.split())
            if token_count < self._config.min_query_tokens:
                logger.debug(
                    "reranker skipped: query has %d tokens (min %d)",
                    token_count,
                    self._config.min_query_tokens,
                )
                return candidates[:top_k]
        # Build pairs.
        pairs: List[Tuple[str, str]] = []
        for c in candidates:
            passage = c.get("snippet") or c.get("path", "")
            pairs.append((query, str(passage)))
        scores = self.score_pairs(pairs)
        # Decorate + sort.
        decorated = list(zip(candidates, scores))
        decorated.sort(key=lambda x: x[1], reverse=True)
        result: List[dict[str, Any]] = []
        for cand, score in decorated[:top_k]:
            new_cand = dict(cand)  # shallow copy preserves original envelope
            new_cand["rerank_score"] = float(score)
            result.append(new_cand)
        return result

    @classmethod
    def get(cls, config: Optional[RerankerConfig] = None) -> Optional["BGEReranker"]:
        """Return the singleton, or None if unavailable.

        The first call attempts to import FastEmbed + load the model
        with a `first_call_timeout_seconds` wall-clock cap. On timeout
        or failure, logs a structured WARNING, trips a per-process kill
        switch, and returns None for every subsequent call this process
        makes (the retry storm the spec's Risk Mitigations section
        guarantees is prevented)."""
        # 1. Extra installed?
        if not detect().reranker:
            return None
        # 2. Disabled via env?
        if os.environ.get("OPENZIM_RERANKER_DISABLE") == "1":
            logger.debug("reranker disabled via OPENZIM_RERANKER_DISABLE=1")
            return None
        # 3. Disabled via config?
        cfg = config or RerankerConfig()
        if not cfg.enabled:
            return None
        # 4. Cached instance?
        if cls._instance is not None:
            return cls._instance
        # 5. Kill switch tripped on a prior load failure?
        if cls._load_failed:
            return None
        # 6. Load with timeout.
        with cls._instance_lock:
            if cls._instance is not None:
                return cls._instance
            if cls._load_failed:
                return None
            try:
                cls._instance = cls._load_with_timeout(cfg)
            except Exception as exc:  # noqa: BLE001
                # Two very different situations produce a load failure now,
                # and an operator cannot act without knowing which: "you
                # never staged the model" vs "the staged model is broken /
                # HuggingFace is unreachable". Name the flag in the first
                # case so the fix is one command away.
                if cfg.allow_model_download:
                    remedy = (
                        "Run `openzim-mcp download-models` to pre-stage the "
                        "model offline."
                    )
                else:
                    remedy = (
                        "Model downloads are off by default "
                        "(ml.reranker.allow_model_download=false), so the "
                        "model must already be in the local cache. Run "
                        "`openzim-mcp download-models` on a networked "
                        "machine to stage it, or set "
                        "OPENZIM_MCP_ML__RERANKER__ALLOW_MODEL_DOWNLOAD=true "
                        "to accept first-call egress."
                    )
                logger.warning(
                    (
                        "reranker model load failed: %s. "
                        "Falling back to Xapian-only ranking for this "
                        "process. %s"
                    ),
                    exc,
                    remedy,
                )
                cls._load_failed = True
                return None
            return cls._instance

    @classmethod
    def _load_with_timeout(cls, cfg: RerankerConfig) -> "BGEReranker":
        timeout = cfg.first_call_timeout_seconds
        # A DAEMON thread, not a ThreadPoolExecutor: since Python 3.9 the
        # executor's (non-daemon) workers are joined at interpreter exit, so
        # a timed-out load that was still downloading the model blocked
        # process shutdown until the download finished. The daemon worker
        # still leaks past the timeout (bounding the caller's wait is the
        # point) but can no longer hold the interpreter hostage.
        result_q: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

        def _worker() -> None:
            # Every exit path has to leave exactly one item in the queue: a
            # worker that dies without posting strands the caller on the full
            # timeout for a load that already failed. A raised ``Exception``
            # is relayed verbatim so the caller re-raises the real cause; the
            # ``finally`` covers the BaseException exits (a SystemExit from
            # deep inside the ML stack, an injected KeyboardInterrupt), which
            # must NOT be re-raised in the caller's thread as though the
            # caller itself had been interrupted.
            outcome: "tuple[str, Any]" = (
                "err",
                RuntimeError("reranker model load thread terminated abnormally"),
            )
            try:
                outcome = (
                    "ok",
                    _load_model(
                        cfg.model_id,
                        cfg.cache_dir,
                        allow_download=cfg.allow_model_download,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 — relayed to caller
                outcome = ("err", exc)
            finally:
                result_q.put(outcome)

        threading.Thread(
            target=_worker, name="openzim-reranker-load", daemon=True
        ).start()
        try:
            status, payload = result_q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(
                f"reranker model load exceeded {timeout}s timeout. "
                f"Run `openzim-mcp download-models` to pre-stage."
            ) from None
        if status == "err":
            raise payload
        model = payload
        # First-load audit log: model id + library version.
        try:
            import fastembed  # type: ignore[import-not-found]

            logger.info(
                "reranker loaded: model_id=%s fastembed=%s",
                cfg.model_id,
                getattr(fastembed, "__version__", "unknown"),
            )
        except Exception as exc:  # pragma: no cover — diagnostic-only path
            logger.debug("reranker load-audit log skipped: %s", exc)
        return cls(model=model, config=cfg)
