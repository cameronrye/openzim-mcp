"""Test-support helpers for the live reranker suite.

Not a test module (underscore prefix → not collected). Houses the
transient-download-failure classifier so it can be unit-tested in
isolation AND imported by the live test fixture that decides whether a
HuggingFace download failure should skip (transient outage) or fail
(real regression)."""

from __future__ import annotations

import socket
from typing import Iterator, Tuple, Type

# Substrings (matched case-insensitively against the whole exception
# chain) that mark a download/network failure outside our control. Kept
# specific on purpose — `"could not load model"` and `"from any source"`
# are FastEmbed's exact retries-exhausted phrasing, while a genuine
# "model X is not supported" regression contains neither.
_TRANSIENT_MESSAGE_MARKERS: Tuple[str, ...] = (
    "could not download",
    "could not load model",
    "from any source",
    "connection",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "service unavailable",
    "max retries",
    "failed to establish",
    "name resolution",
    "getaddrinfo",
    "network",
    "remote end closed",
    "ssl",
    "502",
    "503",
    "504",
    "429",
)

# Builtin types that are network failures by construction, regardless of
# message. `socket.timeout` aliases `TimeoutError` on 3.10+ but is listed
# explicitly for clarity.
_TRANSIENT_EXC_TYPES: Tuple[Type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    socket.timeout,
)


def _iter_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield ``exc`` and every linked cause/context, guarding cycles.

    FastEmbed often surfaces a generic ``RuntimeError`` whose
    ``__cause__`` is the underlying ``ConnectionError`` — both links must
    be inspected to classify correctly."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def is_transient_download_failure(exc: BaseException) -> bool:
    """True when ``exc`` looks like a transient HuggingFace download /
    network failure (skip the live test) rather than a genuine code or
    API regression (fail the live test)."""
    for link in _iter_exception_chain(exc):
        if isinstance(link, _TRANSIENT_EXC_TYPES):
            return True
        message = str(link).lower()
        if any(marker in message for marker in _TRANSIENT_MESSAGE_MARKERS):
            return True
    return False
