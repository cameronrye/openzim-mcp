"""Shared fallback decorator for ML entry points.

When an ML call raises, the decorator logs a WARNING (once per feature),
sets a per-process kill switch for that feature, and routes all future
calls through `on_failure`. Idempotent — second failure for the same
feature logs at DEBUG level only."""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Set, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_disabled_features: Set[str] = set()


def reset_kill_switches() -> None:
    """Clear all kill switches. For tests only."""
    _disabled_features.clear()


def ml_fallback(
    *,
    feature: str,
    on_failure: Callable[..., T],
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: wrap an ML call so failure routes to a pure-Python fallback.

    On the FIRST exception for `feature`:
      * log a structured WARNING naming the feature and the underlying error,
      * set a process-wide kill switch,
      * return `on_failure(*args, **kwargs)`.

    On SUBSEQUENT calls after the kill switch is set:
      * `on_failure(*args, **kwargs)` is called WITHOUT entering the wrapped
        function.

    On SUBSEQUENT exceptions (if a fresh kill-switch had been cleared):
      * log at DEBUG only to avoid log spam.
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            if feature in _disabled_features:
                logger.debug(
                    "ml feature %s kill-switched; routing to fallback", feature
                )
                return on_failure(*args, **kwargs)
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — intentional broad catch
                if feature in _disabled_features:
                    logger.debug(
                        "ml feature %s re-failure suppressed: %s", feature, exc
                    )
                else:
                    logger.warning(
                        "ml feature %s failed (%s); disabling for this process",
                        feature,
                        exc,
                    )
                    _disabled_features.add(feature)
                return on_failure(*args, **kwargs)

        return wrapper

    return decorator
