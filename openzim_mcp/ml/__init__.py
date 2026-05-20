"""ML accelerator subsystem for openzim-mcp v2 Phase D.

Three opt-in capabilities (only one shipping in sub-D-1):
  * [reranker] — cross-encoder relevance ranker via FastEmbed

Feature-detection happens here; consumers check `detect()` before
touching any ML code. Lazy-import + lazy-load are enforced by the
per-feature module (e.g., ml.reranker imports `fastembed` inside
`BGEReranker.get()`, not at module level).
"""

from __future__ import annotations

import functools
import importlib.util
from dataclasses import dataclass

__all__ = ["MLFeatures", "detect"]


@dataclass(frozen=True)
class MLFeatures:
    """Snapshot of which ML extras are installed in this process.

    Sized to today's scope. New fields added when their sub-Ds ship —
    no pre-commitment to deferred items (#12, #15)."""

    reranker: bool


@functools.lru_cache(maxsize=1)
def detect() -> MLFeatures:
    """Single source of truth for installed ML extras.

    Cached per process; uses `importlib.util.find_spec` only — no
    imports, no side effects, no model loads."""
    return MLFeatures(
        reranker=importlib.util.find_spec("fastembed") is not None,
    )
