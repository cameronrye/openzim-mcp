"""Cross-encoder reranker (Phase D sub-D-1).

Lazy singleton wrapping FastEmbed's TextCrossEncoder. The whole module
imports cheaply (no `import fastembed` at top level); the actual library
import lives inside `_load_model`, which only runs when the
`[reranker]` extra is installed AND the user actually hits a rerank
code path."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import (  # noqa: F401 — List/Sequence/Tuple used by Task 5
    Any,
    List,
    Optional,
    Sequence,
    Tuple,
)

from openzim_mcp.config import RerankerConfig
from openzim_mcp.ml import detect
from openzim_mcp.ml.fallback import ml_fallback  # noqa: F401 — used by Task 5

logger = logging.getLogger(__name__)


def _load_model(model_id: str, cache_dir: Optional[Path]) -> Any:
    """Lazy import + load. Called inside BGEReranker.get(). Kept as a
    module-level function so tests can mock it cleanly."""
    from fastembed.rerank.cross_encoder import (  # type: ignore[import-not-found]
        TextCrossEncoder,
    )

    kwargs: dict[str, Any] = {"model_name": model_id}
    if cache_dir is not None:
        kwargs["cache_dir"] = str(cache_dir)
    return TextCrossEncoder(**kwargs)


class BGEReranker:
    """Singleton wrapper around FastEmbed's cross-encoder reranker.

    Use `BGEReranker.get(config)` to fetch an instance — returns None
    when the `[reranker]` extra is missing or the kill switch fired.
    Subsequent calls hit the cached instance."""

    _instance: Optional["BGEReranker"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self, model: Any, config: RerankerConfig) -> None:
        self._model = model
        self._config = config

    @classmethod
    def reset_instance(cls) -> None:
        """For tests only."""
        with cls._instance_lock:
            cls._instance = None

    @classmethod
    def get(cls, config: Optional[RerankerConfig] = None) -> Optional["BGEReranker"]:
        """Return the singleton, or None if unavailable.

        The first call attempts to import FastEmbed + load the model
        with a `first_call_timeout_seconds` wall-clock cap. On timeout
        or failure, logs a structured WARNING and returns None for
        every subsequent call this process makes."""
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
        # 5. Load with timeout.
        with cls._instance_lock:
            if cls._instance is not None:
                return cls._instance
            try:
                cls._instance = cls._load_with_timeout(cfg)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    (
                        "reranker model load failed: %s. "
                        "Falling back to Xapian-only ranking for this "
                        "process. Run `openzim-mcp download-models` to "
                        "pre-stage the model offline."
                    ),
                    exc,
                )
                return None
            return cls._instance

    @classmethod
    def _load_with_timeout(cls, cfg: RerankerConfig) -> "BGEReranker":
        timeout = cfg.first_call_timeout_seconds
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_load_model, cfg.model_id, cfg.cache_dir)
            try:
                model = future.result(timeout=timeout)
            except FuturesTimeout:
                future.cancel()
                raise TimeoutError(
                    f"reranker model load exceeded {timeout}s timeout. "
                    f"Run `openzim-mcp download-models` to pre-stage."
                )
        # First-load audit log: model id + library version.
        try:
            import fastembed  # type: ignore[import-not-found]

            logger.info(
                "reranker loaded: model_id=%s fastembed=%s",
                cfg.model_id,
                getattr(fastembed, "__version__", "unknown"),
            )
        except Exception:  # pragma: no cover — diagnostic-only path
            pass
        return cls(model=model, config=cfg)
