"""Gate 0a — promotion-extraction parity diff-test.

For each probe in ``b1_b13_probes.jsonl``, run BOTH the legacy instance method
(``SimpleToolsHandler._promote_topic_via_title_index``) and the new module-level
function (``topic_preprocessing.promote_topic_via_title_index``). Assert
byte-identical resolved entry paths.

## Fixture choice

The plan template referenced ``configured_server`` and ``zim_archives`` fixtures,
but neither exists in this repo's conftest. Rather than introduce new global
fixtures (which would couple this dispatch-eval-only test to a heavyweight
pytest surface), we follow the post-b1…b12 sweep convention: instantiate a
``SimpleToolsHandler`` directly against a real ``ZimOperations`` instance built
from a Wikipedia ZIM whose path is supplied via the ``OZM_DISPATCH_EVAL_ZIM``
environment variable. When the env var is absent or points at a missing file,
the entire module skips — A3's contract is that it runs locally against
Cameron's live Wikipedia ZIM, NOT in CI.

The module-level skip means the ``--collect-only`` step still shows the
parametrized cases (one per probe), but execution flips to a SKIP outcome
when the live ZIM isn't present. This preserves the RED signal at the
import line (``promote_topic_via_title_index is not None``) for the case
where Cameron runs the test BEFORE Task A4 lands the extraction.

## Signatures verified against the codebase

- ``SimpleToolsHandler.__init__(zim_operations)`` (simple_tools.py:160)
- ``SimpleToolsHandler._promote_topic_via_title_index(self, zim_file_path, topic)``
  (simple_tools.py:3896-3898) — note order: zim_file_path BEFORE topic, NOT
  topic-first as the plan template wrote it. This file uses the actual order.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from openzim_mcp.simple_tools import SimpleToolsHandler

# Will be filled in once Task A4 lands the extraction. Until then,
# the parity assertion fails at the import-presence check (RED).
try:
    from openzim_mcp.topic_preprocessing import (  # type: ignore[import-not-found]
        promote_topic_via_title_index,
    )
except ImportError:
    promote_topic_via_title_index = None  # type: ignore[assignment]


_PROBES_PATH = Path(__file__).resolve().parent / "data" / "b1_b13_probes.jsonl"


def _load_probes() -> list[dict]:
    """Load the b1→b13 probe set committed alongside this test."""
    return [
        json.loads(line)
        for line in _PROBES_PATH.read_text().splitlines()
        if line.strip()
    ]


def _live_zim_path() -> Path | None:
    """Return the live Wikipedia ZIM path from ``OZM_DISPATCH_EVAL_ZIM``,
    or ``None`` when the env var is unset or points at a missing file.
    """
    raw = os.environ.get("OZM_DISPATCH_EVAL_ZIM")
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def _have_live_zim() -> bool:
    """Module-level skip guard mirroring the b-series live-Wikipedia convention."""
    return _live_zim_path() is not None


@pytest.fixture(scope="module")
def live_handler() -> SimpleToolsHandler:
    """Build a ``SimpleToolsHandler`` bound to the live Wikipedia ZIM.

    Skips the whole module if ``OZM_DISPATCH_EVAL_ZIM`` is missing — this
    diff-test is for local execution against Cameron's Wikipedia archive,
    not CI.
    """
    zim_path = _live_zim_path()
    if zim_path is None:
        pytest.skip(
            "OZM_DISPATCH_EVAL_ZIM unset or missing — A3 parity diff-test "
            "requires a real Wikipedia ZIM; run locally only."
        )

    # Lazy imports so collection still succeeds in CI even when libzim /
    # the full config surface aren't fully wired for this test.
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import (
        CacheConfig,
        ContentConfig,
        LoggingConfig,
        OpenZimMcpConfig,
    )
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator
    from openzim_mcp.zim_operations import ZimOperations

    config = OpenZimMcpConfig(
        allowed_directories=[str(zim_path.parent)],
        tool_mode="advanced",
        cache=CacheConfig(enabled=True, max_size=64, ttl_seconds=300),
        content=ContentConfig(max_content_length=200_000, snippet_length=400),
        logging=LoggingConfig(level="INFO"),
    )
    path_validator = PathValidator(config.allowed_directories)
    cache = OpenZimMcpCache(config.cache)
    content_processor = ContentProcessor(snippet_length=config.content.snippet_length)
    zim_ops = ZimOperations(
        config=config,
        path_validator=path_validator,
        cache=cache,
        content_processor=content_processor,
    )
    return SimpleToolsHandler(zim_ops)


@pytest.mark.skipif(
    not _have_live_zim(),
    reason=(
        "OZM_DISPATCH_EVAL_ZIM unset or missing — A3 parity diff-test runs "
        "against a real Wikipedia ZIM only (local execution)."
    ),
)
@pytest.mark.parametrize(
    "probe",
    _load_probes(),
    ids=lambda p: p["probe_id"],
)
def test_promotion_parity(probe: dict, live_handler: SimpleToolsHandler) -> None:
    """Old method and new module-level function resolve byte-identical paths."""
    assert promote_topic_via_title_index is not None, (
        "topic_preprocessing.promote_topic_via_title_index missing — "
        "Task A4 (extraction) has not landed yet. RED phase expected."
    )

    zim_file_path = str(_live_zim_path())
    topic = probe["topic"]

    # Signature: ``_promote_topic_via_title_index(self, zim_file_path, topic)``
    # — verified against simple_tools.py:3896-3898.
    old_result = live_handler._promote_topic_via_title_index(zim_file_path, topic)
    new_result = promote_topic_via_title_index(
        zim_operations=live_handler.zim_operations,
        zim_file_path=zim_file_path,
        topic=topic,
    )
    assert old_result == new_result, (
        f"divergence on {probe['probe_id']}: "
        f"old={old_result!r} new={new_result!r}"
    )
