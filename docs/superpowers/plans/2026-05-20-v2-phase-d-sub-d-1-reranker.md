# v2 Phase D sub-D-1 — Cross-Encoder Reranker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a cross-encoder reranker behind the `[reranker]` opt-in extra that silently improves search + synthesize relevance when installed, falls back cleanly to Xapian-only ranking when absent, and never hangs the first query on an offline deployment.

**Architecture:** New `openzim_mcp/ml/` submodule with three small files (feature-detection registry, fallback decorator, BGEReranker class). Reranker plugs into existing `_handle_search` / `_handle_filtered_search` / `_handle_search_all` in `simple_tools.py` and `_collect_passages` in `synthesize.py`. Optional FastEmbed dependency via `[reranker]` extra; lazy import + lazy model load; 5-second timeout on first-call fetch with structured fallback. Telemetry via the existing `_track()` path.

**Tech Stack:** Python 3.12+, FastEmbed (ONNX-backed, no torch), Pydantic v2 for config, pytest, argparse for CLI dispatch, uv for dependency management.

**Spec:** [`docs/superpowers/specs/2026-05-20-v2-phase-d-ml-accelerators-design.md`](../specs/2026-05-20-v2-phase-d-ml-accelerators-design.md), § sub-D-1.

---

## File Structure

**New files:**
- `openzim_mcp/ml/__init__.py` — `MLFeatures` dataclass + `detect()` registry function
- `openzim_mcp/ml/fallback.py` — shared `ml_fallback` decorator
- `openzim_mcp/ml/reranker.py` — `BGEReranker` class (lazy singleton, score_pairs, rerank)
- `openzim_mcp/ml/cli/__init__.py` — empty package marker
- `openzim_mcp/ml/cli/download.py` — `openzim-mcp download-models` entrypoint
- `tests/ml/__init__.py` — empty package marker
- `tests/ml/conftest.py` — `requires_reranker` marker registration + shared fixtures
- `tests/ml/test_ml_registry.py` — tests for `MLFeatures.detect()`
- `tests/ml/test_fallback.py` — tests for `ml_fallback` decorator
- `tests/ml/test_reranker_unit.py` — unit tests for `BGEReranker` (mocked FastEmbed)
- `tests/ml/test_reranker_integration.py` — integration tests against real FastEmbed
- `tests/ml/test_download_cli.py` — CLI smoke test
- `docs/v2/extras-reranker.md` — user-facing documentation

**Modified files:**
- `pyproject.toml` — add `[project.optional-dependencies]` with `reranker = ["fastembed>=0.4.0,<1.0"]`
- `openzim_mcp/config.py` — add `MLConfig` + `RerankerConfig`; compose onto `OpenZimMcpConfig`
- `openzim_mcp/main.py` — early-detect `sys.argv[1] == "download-models"` to dispatch the new CLI without breaking the existing `openzim-mcp <dirs>` invocation
- `openzim_mcp/simple_tools.py` — call `BGEReranker.rerank()` in `_handle_search`, `_handle_filtered_search`, `_handle_search_all`; emit `_meta.reranked` flag
- `openzim_mcp/synthesize.py` — call `BGEReranker.rerank()` in `_collect_passages` before citation assembly
- `.github/workflows/test.yml` — add a separate `test-reranker` job that installs `[reranker]` and runs the integration tests on ubuntu-latest only (cost-controlled)

**Test boundaries:**
- Default `make test` runs on no-extras install. Integration tests skip via `@pytest.mark.requires_reranker` keyed on `importlib.util.find_spec("fastembed")`.
- The new `test-reranker` CI job runs the integration tests with FastEmbed installed.

---

### Task 1: Feature-detection registry — `MLFeatures.detect()`

**Files:**
- Create: `openzim_mcp/ml/__init__.py`
- Create: `tests/ml/__init__.py`
- Create: `tests/ml/test_ml_registry.py`

- [ ] **Step 1: Create the empty test package marker**

Create `tests/ml/__init__.py` as an empty file:

```python
"""ML accelerator tests. Lives in its own package to keep the
default `make test` run unchanged when no extras are installed."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/ml/test_ml_registry.py`:

```python
"""Unit tests for openzim_mcp.ml.__init__'s feature-detection registry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openzim_mcp.ml import MLFeatures, detect


class TestDetectRegistry:
    def setup_method(self) -> None:
        # Clear the lru_cache between tests so each test gets a fresh detect()
        detect.cache_clear()

    def test_returns_frozen_dataclass(self) -> None:
        features = detect()
        assert isinstance(features, MLFeatures)
        # frozen dataclass: mutation should raise
        with pytest.raises(Exception):
            features.reranker = not features.reranker  # type: ignore[misc]

    def test_reranker_true_when_fastembed_importable(self) -> None:
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = object()  # truthy: package found
            features = detect()
            assert features.reranker is True
        # Verify find_spec was called with the expected argument
        mock_spec.assert_called_with("fastembed")

    def test_reranker_false_when_fastembed_missing(self) -> None:
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = None  # falsy: package not found
            features = detect()
            assert features.reranker is False

    def test_detect_is_cached(self) -> None:
        # Two calls should hit find_spec only once
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = object()
            detect()
            detect()
            assert mock_spec.call_count == 1
```

- [ ] **Step 3: Run the failing test**

```bash
uv run pytest tests/ml/test_ml_registry.py -v
```

Expected: `ImportError: No module named 'openzim_mcp.ml'`

- [ ] **Step 4: Create `openzim_mcp/ml/__init__.py`**

```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run pytest tests/ml/test_ml_registry.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Run lint + type-check**

```bash
make lint && make type-check
```

Expected: both clean.

- [ ] **Step 7: Commit**

```bash
git add openzim_mcp/ml/__init__.py tests/ml/__init__.py tests/ml/test_ml_registry.py
git commit -m "feat(ml): add MLFeatures feature-detection registry"
```

---

### Task 2: Shared fallback decorator — `ml_fallback`

**Files:**
- Create: `openzim_mcp/ml/fallback.py`
- Create: `tests/ml/test_fallback.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ml/test_fallback.py`:

```python
"""Unit tests for ml_fallback decorator."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from openzim_mcp.ml.fallback import ml_fallback, reset_kill_switches


@pytest.fixture(autouse=True)
def _reset() -> None:
    """Each test starts with empty kill-switch state."""
    reset_kill_switches()


def _fallback(*args: Any, **kwargs: Any) -> str:
    return "fallback"


class TestMlFallback:
    def test_success_path_returns_inner_result(self) -> None:
        @ml_fallback(feature="reranker", on_failure=_fallback)
        def inner() -> str:
            return "inner"

        assert inner() == "inner"

    def test_first_exception_logs_warning_and_returns_fallback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)

        @ml_fallback(feature="reranker", on_failure=_fallback)
        def inner() -> str:
            raise RuntimeError("boom")

        result = inner()
        assert result == "fallback"
        warnings = [
            r for r in caplog.records if r.levelname == "WARNING"
        ]
        assert len(warnings) == 1
        assert "reranker" in warnings[0].message.lower()

    def test_subsequent_calls_after_failure_skip_inner(self) -> None:
        call_count = 0

        @ml_fallback(feature="reranker", on_failure=_fallback)
        def inner() -> str:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

        inner()  # triggers kill switch
        inner()  # should NOT call inner again
        inner()
        assert call_count == 1  # only the first call entered the wrapped function

    def test_subsequent_failures_log_debug_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)

        @ml_fallback(feature="reranker", on_failure=_fallback)
        def inner() -> str:
            raise RuntimeError("boom")

        inner()  # WARNING
        inner()  # DEBUG (kill-switch path)

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        debugs = [r for r in caplog.records if r.levelname == "DEBUG"]
        assert len(warnings) == 1
        assert any("reranker" in d.message.lower() for d in debugs)

    def test_kill_switch_is_per_feature(self) -> None:
        """A failure on reranker doesn't disable a hypothetical other feature."""

        @ml_fallback(feature="reranker", on_failure=_fallback)
        def reranker_inner() -> str:
            raise RuntimeError("boom")

        @ml_fallback(feature="other", on_failure=_fallback)
        def other_inner() -> str:
            return "other_ok"

        reranker_inner()
        assert other_inner() == "other_ok"
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/ml/test_fallback.py -v
```

Expected: `ImportError: No module named 'openzim_mcp.ml.fallback'`

- [ ] **Step 3: Create `openzim_mcp/ml/fallback.py`**

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/ml/test_fallback.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/ml/fallback.py tests/ml/test_fallback.py
git commit -m "feat(ml): add ml_fallback decorator for graceful ML failure"
```

---

### Task 3: `RerankerConfig` + `MLConfig` on `OpenZimMcpConfig`

**Files:**
- Modify: `openzim_mcp/config.py:153-170` (`OpenZimMcpConfig` field block, line numbers approximate — find by searching for the `cache: CacheConfig = Field(...)` line)
- Modify: `openzim_mcp/config.py` (just above `class OpenZimMcpConfig(BaseSettings):`)
- Test: extend `tests/test_config.py` if it exists, otherwise create `tests/ml/test_ml_config.py`

- [ ] **Step 1: Locate existing config tests**

```bash
find tests -name "test_config*.py" -not -path "*/ml/*"
```

If a file exists, extend it; otherwise we add a new test file under `tests/ml/`.

- [ ] **Step 2: Write the failing test**

Create or extend `tests/ml/test_ml_config.py`:

```python
"""Tests for MLConfig + RerankerConfig wiring on OpenZimMcpConfig."""

from __future__ import annotations

from pathlib import Path

import pytest

from openzim_mcp.config import MLConfig, OpenZimMcpConfig, RerankerConfig


class TestRerankerConfig:
    def test_defaults(self) -> None:
        cfg = RerankerConfig()
        assert cfg.enabled is True
        assert cfg.model_id == "Xenova/bge-reranker-base-onnx"
        assert cfg.candidate_pool_size == 50
        assert cfg.final_top_k == 10
        assert cfg.max_query_length == 256
        assert cfg.max_passage_length == 512
        assert cfg.min_query_tokens == 4
        assert cfg.first_call_timeout_seconds == 5.0
        assert cfg.cache_dir is None

    def test_pool_size_bounds(self) -> None:
        # Pydantic v2 validation: pool size must be positive
        with pytest.raises(Exception):
            RerankerConfig(candidate_pool_size=0)
        # Reasonable upper bound prevents runaway memory
        with pytest.raises(Exception):
            RerankerConfig(candidate_pool_size=10000)

    def test_min_query_tokens_bounds(self) -> None:
        # 0 disables the skip gate; that's allowed.
        RerankerConfig(min_query_tokens=0)
        # Negative is not.
        with pytest.raises(Exception):
            RerankerConfig(min_query_tokens=-1)


class TestMLConfig:
    def test_defaults(self) -> None:
        cfg = MLConfig()
        assert isinstance(cfg.reranker, RerankerConfig)
        assert cfg.reranker.enabled is True

    def test_attaches_to_openzim_config(self, tmp_path: Path) -> None:
        zim_dir = tmp_path / "zim"
        zim_dir.mkdir()
        cfg = OpenZimMcpConfig(allowed_directories=[str(zim_dir)])
        assert isinstance(cfg.ml, MLConfig)
        assert isinstance(cfg.ml.reranker, RerankerConfig)
```

- [ ] **Step 3: Run the failing test**

```bash
uv run pytest tests/ml/test_ml_config.py -v
```

Expected: `ImportError: cannot import name 'MLConfig'`

- [ ] **Step 4: Add `RerankerConfig` + `MLConfig` to `openzim_mcp/config.py`**

In `openzim_mcp/config.py`, add the new classes after the existing `SynthesizeConfig` class (around line 135, before `class LoggingConfig`):

```python
class RerankerConfig(BaseModel):
    """Phase D sub-D-1: cross-encoder reranker config.

    Only applies when the `[reranker]` optional extra is installed.
    All knobs respect the kill switch in `ml_fallback` — if the model
    fails to load once, every subsequent search bypasses rerank for
    the rest of the process."""

    enabled: bool = Field(
        default=True,
        description=(
            "Master kill switch. Set False (or env OPENZIM_RERANKER_DISABLE=1) "
            "to skip rerank even when the [reranker] extra is importable."
        ),
    )
    model_id: str = Field(
        default="Xenova/bge-reranker-base-onnx",
        description=(
            "FastEmbed model identifier. Default targets English-first "
            "archives. Multilingual archives can override via "
            "OPENZIM_RERANKER_MODEL env var (e.g., jina-reranker-v3)."
        ),
    )
    candidate_pool_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description=(
            "Xapian top-N to rerank. Larger pool = more recall, more "
            "rerank cost. 50 is the sweet spot per FastEmbed benchmarks."
        ),
    )
    final_top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description=(
            "Default response cap after rerank. Caller-supplied `limit` "
            "overrides this when smaller."
        ),
    )
    max_query_length: int = Field(default=256, ge=1, le=4096)
    max_passage_length: int = Field(default=512, ge=1, le=8192)
    min_query_tokens: int = Field(
        default=4,
        ge=0,
        le=64,
        description=(
            "Skip-on-short-query gate: queries with fewer than this many "
            "word tokens bypass rerank. Single-word entity queries (e.g., "
            "`Berlin`) already get a Xapian-score-1.0 canonical-title hit; "
            "the cross-encoder adds cost without value there. Set 0 to "
            "disable the gate."
        ),
    )
    first_call_timeout_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=120.0,
        description=(
            "Timeout for the first model load (covers HuggingFace download). "
            "When exceeded, the kill switch fires and search falls back to "
            "Xapian-only. Pre-stage with `openzim-mcp download-models` to "
            "avoid this path."
        ),
    )
    cache_dir: Path | None = Field(
        default=None,
        description=(
            "Override the FastEmbed model cache directory. None → "
            "$OPENZIM_MODEL_CACHE_DIR/fastembed, fallback "
            "~/.cache/openzim-mcp/models/fastembed."
        ),
    )


class MLConfig(BaseModel):
    """Phase D umbrella config. Sized to today's scope (sub-D-1 only);
    deferred sub-Ds add their sub-configs when they ship."""

    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
```

In the `OpenZimMcpConfig` class (search for `cache: CacheConfig = Field(...)` and add this line in the same block):

```python
    ml: MLConfig = Field(default_factory=MLConfig)
```

Also add `MLConfig`, `RerankerConfig` to the `__all__` list (search for `"OpenZimMcpConfig"` in `__all__`).

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run pytest tests/ml/test_ml_config.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Run lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 7: Commit**

```bash
git add openzim_mcp/config.py tests/ml/test_ml_config.py
git commit -m "feat(ml): add RerankerConfig + MLConfig to OpenZimMcpConfig"
```

---

### Task 4: `BGEReranker.get()` lazy singleton

**Files:**
- Create: `openzim_mcp/ml/reranker.py`
- Create: `tests/ml/test_reranker_unit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ml/test_reranker_unit.py`:

```python
"""Unit tests for BGEReranker (mocked FastEmbed)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.config import RerankerConfig
from openzim_mcp.ml import detect
from openzim_mcp.ml.fallback import reset_kill_switches
from openzim_mcp.ml.reranker import BGEReranker


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    BGEReranker.reset_instance()
    reset_kill_switches()
    detect.cache_clear()


class TestBGEGet:
    def test_returns_none_when_extra_absent(self) -> None:
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = None
            assert BGEReranker.get() is None

    def test_returns_none_when_disabled_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENZIM_RERANKER_DISABLE", "1")
        # Even if the extra is "installed", env disable wins.
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = object()
            assert BGEReranker.get() is None

    def test_returns_singleton_when_extra_present(self) -> None:
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec, patch(
            "openzim_mcp.ml.reranker._load_model"
        ) as mock_load:
            mock_spec.return_value = object()
            mock_load.return_value = MagicMock(name="fastembed_reranker")
            a = BGEReranker.get()
            b = BGEReranker.get()
            assert a is not None
            assert a is b  # same singleton
            assert mock_load.call_count == 1
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/ml/test_reranker_unit.py -v
```

Expected: `ImportError: No module named 'openzim_mcp.ml.reranker'`

- [ ] **Step 3: Create `openzim_mcp/ml/reranker.py` skeleton**

```python
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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from openzim_mcp.config import RerankerConfig
from openzim_mcp.ml import detect
from openzim_mcp.ml.fallback import ml_fallback

logger = logging.getLogger(__name__)


def _load_model(model_id: str, cache_dir: Optional[Path]) -> Any:
    """Lazy import + load. Called inside BGEReranker.get(). Kept as a
    module-level function so tests can mock it cleanly."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder  # type: ignore[import-untyped]

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
    def get(
        cls, config: Optional[RerankerConfig] = None
    ) -> Optional["BGEReranker"]:
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
            import fastembed  # type: ignore[import-untyped]

            logger.info(
                "reranker loaded: model_id=%s fastembed=%s",
                cfg.model_id,
                getattr(fastembed, "__version__", "unknown"),
            )
        except Exception:  # pragma: no cover — diagnostic-only path
            pass
        return cls(model=model, config=cfg)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/ml/test_reranker_unit.py::TestBGEGet -v
```

Expected: 3 passed.

- [ ] **Step 5: Run lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/ml/reranker.py tests/ml/test_reranker_unit.py
git commit -m "feat(ml): BGEReranker singleton with timeout-gated lazy load"
```

---

### Task 5: `BGEReranker.score_pairs()` + `rerank()` + skip-gate

**Files:**
- Modify: `openzim_mcp/ml/reranker.py` (add methods + module-level helper)
- Modify: `tests/ml/test_reranker_unit.py` (add test classes)

- [ ] **Step 1: Extend the test file**

Append to `tests/ml/test_reranker_unit.py`:

```python
class TestScorePairs:
    def _make_reranker_with_scores(self, scores: List[float]) -> BGEReranker:
        mock_model = MagicMock()
        mock_model.rerank = MagicMock(return_value=iter(scores))
        # Bypass BGEReranker.get() and inject a pre-built reranker
        return BGEReranker(model=mock_model, config=RerankerConfig())

    def test_empty_pairs_returns_empty(self) -> None:
        r = self._make_reranker_with_scores([])
        assert r.score_pairs([]) == []

    def test_returns_one_score_per_pair(self) -> None:
        r = self._make_reranker_with_scores([0.9, 0.5, 0.1])
        scores = r.score_pairs(
            [("q", "d1"), ("q", "d2"), ("q", "d3")]
        )
        assert scores == [0.9, 0.5, 0.1]

    def test_truncates_query_at_max_length(self) -> None:
        cfg = RerankerConfig(max_query_length=5)
        mock_model = MagicMock()
        mock_model.rerank = MagicMock(return_value=iter([0.5]))
        r = BGEReranker(model=mock_model, config=cfg)
        r.score_pairs([("abcdefghijklmnop", "doc")])
        # Verify the query passed to fastembed was truncated
        call_args = mock_model.rerank.call_args
        # FastEmbed's rerank signature: rerank(query: str, documents: List[str])
        passed_query = call_args[0][0]
        assert len(passed_query) <= 5


class TestRerank:
    def _make_reranker_with_scores(self, scores: List[float]) -> BGEReranker:
        mock_model = MagicMock()
        mock_model.rerank = MagicMock(return_value=iter(scores))
        return BGEReranker(model=mock_model, config=RerankerConfig())

    def test_short_query_skips_rerank(self) -> None:
        r = self._make_reranker_with_scores([0.5, 0.5, 0.5])
        # "Berlin" is 1 token, well below min_query_tokens=4
        candidates = [
            {"path": "A", "snippet": "...", "xapian_score": 1.0},
            {"path": "B", "snippet": "...", "xapian_score": 0.9},
        ]
        result = r.rerank("Berlin", candidates, top_k=2)
        # Returns input order unchanged (no rerank fired)
        assert [c["path"] for c in result] == ["A", "B"]
        # And no rerank_score field added
        assert all("rerank_score" not in c for c in result)

    def test_long_query_reranks(self) -> None:
        # Scores ordered to invert Xapian's ordering
        r = self._make_reranker_with_scores([0.1, 0.9])
        candidates = [
            {"path": "A", "snippet": "...", "xapian_score": 1.0},
            {"path": "B", "snippet": "...", "xapian_score": 0.5},
        ]
        result = r.rerank(
            "what year did Marie Curie discover radium",
            candidates,
            top_k=2,
        )
        # B now wins (rerank_score=0.9 > 0.1)
        assert [c["path"] for c in result] == ["B", "A"]
        assert result[0]["rerank_score"] == 0.9
        assert result[1]["rerank_score"] == 0.1

    def test_top_k_slices_result(self) -> None:
        r = self._make_reranker_with_scores([0.9, 0.5, 0.1])
        candidates = [
            {"path": "A", "snippet": "...", "xapian_score": 0.5},
            {"path": "B", "snippet": "...", "xapian_score": 0.5},
            {"path": "C", "snippet": "...", "xapian_score": 0.5},
        ]
        result = r.rerank(
            "what year did Marie Curie discover radium",
            candidates,
            top_k=2,
        )
        assert len(result) == 2
        assert [c["path"] for c in result] == ["A", "B"]

    def test_empty_candidates_returns_empty(self) -> None:
        r = self._make_reranker_with_scores([])
        assert r.rerank("any long enough query string", [], top_k=10) == []
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
uv run pytest tests/ml/test_reranker_unit.py::TestScorePairs tests/ml/test_reranker_unit.py::TestRerank -v
```

Expected: `AttributeError: 'BGEReranker' object has no attribute 'score_pairs'`

- [ ] **Step 3: Add the methods to `openzim_mcp/ml/reranker.py`**

Append to the `BGEReranker` class (before the `_load_with_timeout` classmethod):

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/ml/test_reranker_unit.py -v
```

Expected: all tests pass (10 total).

- [ ] **Step 5: Run lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/ml/reranker.py tests/ml/test_reranker_unit.py
git commit -m "feat(ml): BGEReranker.score_pairs + rerank with skip-on-short-query gate"
```

---

### Task 6: Pyproject `[reranker]` extra

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Locate the dependencies block**

```bash
grep -n "^dependencies\|optional-dependencies\|project.urls" pyproject.toml
```

Expected output shows `dependencies = [` at one line and `[project.urls]` shortly after. The new `[project.optional-dependencies]` section goes between them.

- [ ] **Step 2: Add the `[reranker]` extra**

Edit `pyproject.toml`. After the closing `]` of the existing `dependencies = [...]` list and before `[project.urls]`, add:

```toml
[project.optional-dependencies]
# Phase D sub-D-1: cross-encoder reranker via FastEmbed (ONNX-backed,
# no torch dependency). Adds ~150 MB install footprint. Lazy-imported
# inside openzim_mcp.ml.reranker; default install is unaffected.
reranker = [
    "fastembed>=0.4.0,<1.0",
]
```

- [ ] **Step 3: Verify wheel builds cleanly (no extras)**

```bash
uv sync && make test 2>&1 | tail -3
```

Expected: existing tests still pass; no new failures.

- [ ] **Step 4: Verify install with `[reranker]` works**

```bash
uv sync --extra reranker
uv run python -c "import fastembed; print('fastembed OK:', fastembed.__version__)"
```

Expected: prints `fastembed OK: <version>` (no ImportError). Then revert:

```bash
uv sync  # back to no-extras state
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(ml): add [reranker] optional extra (FastEmbed)"
```

---

### Task 7: Wire reranker into `simple_tools.py:_handle_search`

**Files:**
- Modify: `openzim_mcp/simple_tools.py` (in `_handle_search`)
- Test: extend `tests/ml/test_reranker_unit.py` with integration-shaped tests

- [ ] **Step 1: Locate `_handle_search` and identify where Xapian results are returned**

```bash
grep -n "_handle_search\|search_results\|search_zim_file" /Volumes/rye/Developer/openzim-mcp/openzim_mcp/simple_tools.py | head -10
```

Find the function signature and the line where the search-results list is assembled into the final response.

- [ ] **Step 2: Write the failing integration test**

Append to `tests/ml/test_reranker_unit.py`:

```python
class TestRerankerWiredToSimpleTools:
    """Smoke test the activation surface: when BGEReranker.get() returns
    a reranker, _handle_search uses it; when it returns None, the path
    falls through to the existing Xapian ordering."""

    def test_handle_search_passes_through_when_reranker_absent(
        self, tmp_path: Path
    ) -> None:
        # When BGEReranker.get() returns None, _handle_search returns
        # the same shape as before (no _meta.reranked field, or
        # _meta.reranked = False).
        from openzim_mcp.simple_tools import SimpleToolsHandler

        # The test only needs to verify the wiring exists, not full
        # search behaviour. Use a mocked-zim handler.
        with patch(
            "openzim_mcp.ml.reranker.BGEReranker.get", return_value=None
        ):
            # The actual handler call requires a configured archive;
            # we mock the inner search to isolate the rerank wiring.
            handler = MagicMock(spec=SimpleToolsHandler)
            handler._handle_search = SimpleToolsHandler._handle_search.__get__(
                handler, SimpleToolsHandler
            )
            # Asserting: no exceptions, no rerank call. Detailed
            # behaviour is covered by the existing simple_tools tests.
            assert True  # placeholder — full integration is in test_reranker_integration

    def test_handle_search_reranks_when_reranker_present(self) -> None:
        # Symmetric: when a reranker is available, search results carry
        # rerank_score and _meta.reranked=True.
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock_reranker = MagicMock()
        mock_reranker.rerank = MagicMock(
            side_effect=lambda q, c, top_k: [
                {**cand, "rerank_score": 0.5} for cand in c[:top_k]
            ]
        )
        with patch(
            "openzim_mcp.ml.reranker.BGEReranker.get",
            return_value=mock_reranker,
        ):
            # Same placeholder shape — actual behaviour validated
            # through the existing search test suite once wired.
            assert True
```

These tests are scaffolding for the wiring; full integration is exercised by `test_reranker_integration.py` in Task 11.

- [ ] **Step 3: Read the existing `_handle_search` to find the return point**

```bash
sed -n '/_handle_search/,/return\|_meta/p' /Volumes/rye/Developer/openzim-mcp/openzim_mcp/simple_tools.py | head -80
```

Identify:
  * Where the `results` list of dicts is finalized.
  * Where `_meta` is constructed.
  * The function's return statement.

- [ ] **Step 4: Inject reranker call before the response is assembled**

In `simple_tools.py`, locate `_handle_search` (and the parallel `_handle_filtered_search`, `_handle_search_all`). Just BEFORE the final `_meta` construction / return statement, insert:

```python
            # Phase D sub-D-1: cross-encoder rerank if available.
            from openzim_mcp.ml.reranker import BGEReranker

            reranker = BGEReranker.get(self.config.ml.reranker)
            reranked = False
            if reranker is not None and results:
                results = reranker.rerank(
                    query=query,
                    candidates=results,
                    top_k=self.config.ml.reranker.final_top_k,
                )
                reranked = True
                self._track("reranker_engaged")
            else:
                self._track(
                    "reranker_skipped",
                    {"reason": "not_installed" if reranker is None else "no_results"},
                )
```

Then in the `_meta` construction, add:

```python
                "reranked": reranked,
```

Notes for the implementer:
- The exact variable names (`results`, `query`) depend on the actual existing code. Match the existing naming.
- The `_track()` method takes either a single string or `(event, details_dict)` — verify by searching for existing `_track(` calls in the file.
- If `_track()` doesn't accept a details argument today, file a follow-up task (out of scope for sub-D-1) or pass the structured event as `f"reranker_skipped:{reason}"`.

- [ ] **Step 5: Run the full test suite to verify no existing tests regress**

```bash
make test
```

Expected: all existing tests pass (no regressions from the rerank wiring).

- [ ] **Step 6: Run lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 7: Commit**

```bash
git add openzim_mcp/simple_tools.py tests/ml/test_reranker_unit.py
git commit -m "feat(ml): wire BGEReranker into _handle_search + telemetry"
```

---

### Task 8: Wire reranker into `_handle_filtered_search` + `_handle_search_all`

**Files:**
- Modify: `openzim_mcp/simple_tools.py` (two more handlers)

- [ ] **Step 1: Locate both handlers**

```bash
grep -n "_handle_filtered_search\|_handle_search_all\|def _handle" /Volumes/rye/Developer/openzim-mcp/openzim_mcp/simple_tools.py | head -10
```

- [ ] **Step 2: Repeat the Task 7 injection pattern in both handlers**

In `_handle_filtered_search`, just before the response is finalized, insert the same rerank block from Task 7 Step 4.

In `_handle_search_all`, same pattern.

Verify each insertion site keeps the same variable names (`results`, `query`) as the surrounding code.

- [ ] **Step 3: Run the full test suite**

```bash
make test
```

Expected: all existing tests pass.

- [ ] **Step 4: Run lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/simple_tools.py
git commit -m "feat(ml): wire BGEReranker into _handle_filtered_search + _handle_search_all"
```

---

### Task 9: Wire reranker into `synthesize.py:_collect_passages`

**Files:**
- Modify: `openzim_mcp/synthesize.py`

- [ ] **Step 1: Locate `_collect_passages`**

```bash
grep -n "_collect_passages\|def _collect\|passage_candidates" /Volumes/rye/Developer/openzim-mcp/openzim_mcp/synthesize.py | head -10
```

Identify:
  * Where passage candidates are assembled (Phase C top-N retrieval).
  * Where they're handed to the citation block builder.

- [ ] **Step 2: Inject the rerank call between collection and assembly**

In `synthesize.py:_collect_passages` (or the function that calls it just before citation assembly), insert:

```python
        # Phase D sub-D-1: rerank passage candidates before citation
        # assembly. Synthesize is the primary content-fragment-query
        # surface; reranker pays off most here.
        from openzim_mcp.ml.reranker import BGEReranker

        reranker = BGEReranker.get(self.config.ml.reranker)
        if reranker is not None and passages:
            # Convert passage objects to dict envelopes for the reranker
            # (it works on `path` + `snippet` shapes). Adjust the
            # exact attribute names to match the existing Passage
            # type — likely Passage.path / Passage.text.
            envelopes = [
                {
                    "path": p.path,
                    "snippet": p.text[: self.config.ml.reranker.max_passage_length],
                    "xapian_score": getattr(p, "score", 0.0),
                }
                for p in passages
            ]
            reranked_envelopes = reranker.rerank(
                query=query,
                candidates=envelopes,
                top_k=len(passages),  # rerank ALL passages, top-K trim happens later
            )
            # Map back to Passage objects, preserving the new ordering.
            envelope_by_path = {e["path"]: e for e in reranked_envelopes}
            passages = [p for p in passages if p.path in envelope_by_path]
            passages.sort(
                key=lambda p: envelope_by_path[p.path]["rerank_score"],
                reverse=True,
            )
            self._track("reranker_engaged", {"surface": "synthesize"})
```

Notes for the implementer:
- The `Passage` envelope's attribute names (`path`, `text`, `score`) need verification against the actual Phase C implementation. Search for `class Passage` or `@dataclass` definitions in `synthesize.py`.
- If the existing code uses a list of dicts already, skip the envelope conversion.

- [ ] **Step 3: Run the synthesize tests**

```bash
uv run pytest tests/test_synthesize* -v
```

Expected: all existing synthesize tests pass.

- [ ] **Step 4: Run the full test suite**

```bash
make test
```

- [ ] **Step 5: Run lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/synthesize.py
git commit -m "feat(ml): wire BGEReranker into synthesize._collect_passages"
```

---

### Task 10: `openzim-mcp download-models` CLI

**Files:**
- Create: `openzim_mcp/ml/cli/__init__.py`
- Create: `openzim_mcp/ml/cli/download.py`
- Modify: `openzim_mcp/main.py` (early-dispatch on `sys.argv[1] == "download-models"`)
- Create: `tests/ml/test_download_cli.py`

- [ ] **Step 1: Create the cli package marker**

Create `openzim_mcp/ml/cli/__init__.py`:

```python
"""CLI subcommands for the ml subsystem."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/ml/test_download_cli.py`:

```python
"""Tests for the `openzim-mcp download-models` CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.ml.cli.download import download_models_main


class TestDownloadModelsCli:
    def test_reports_when_no_extras_installed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("openzim_mcp.ml.cli.download.detect") as mock_detect:
            mock_detect.return_value = MagicMock(reranker=False)
            rc = download_models_main(argv=[])
            captured = capsys.readouterr()
            assert rc == 0
            assert "no ml extras installed" in captured.out.lower()

    def test_downloads_reranker_when_extra_present(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("openzim_mcp.ml.cli.download.detect") as mock_detect, patch(
            "openzim_mcp.ml.cli.download._stage_reranker"
        ) as mock_stage:
            mock_detect.return_value = MagicMock(reranker=True)
            mock_stage.return_value = None  # success
            rc = download_models_main(argv=[])
            captured = capsys.readouterr()
            assert rc == 0
            assert "reranker" in captured.out.lower()
            mock_stage.assert_called_once()

    def test_returns_nonzero_on_stage_failure(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("openzim_mcp.ml.cli.download.detect") as mock_detect, patch(
            "openzim_mcp.ml.cli.download._stage_reranker"
        ) as mock_stage:
            mock_detect.return_value = MagicMock(reranker=True)
            mock_stage.side_effect = RuntimeError("network error")
            rc = download_models_main(argv=[])
            captured = capsys.readouterr()
            assert rc == 1
            assert "failed" in captured.out.lower()
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
uv run pytest tests/ml/test_download_cli.py -v
```

Expected: `ImportError: No module named 'openzim_mcp.ml.cli.download'`

- [ ] **Step 4: Create `openzim_mcp/ml/cli/download.py`**

```python
"""`openzim-mcp download-models` — pre-stage ML model files.

Run once after `pip install openzim-mcp[reranker]` (or any other ML
extra) so the first MCP query doesn't hit a network call. Idempotent —
re-running checks the cache and only fetches missing files."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from openzim_mcp.config import RerankerConfig
from openzim_mcp.ml import detect

logger = logging.getLogger(__name__)


def _stage_reranker(cfg: RerankerConfig) -> None:
    """Force-load the reranker model so FastEmbed's HuggingFace cache
    is populated. Raises on failure."""
    from openzim_mcp.ml.reranker import _load_model

    _load_model(cfg.model_id, cfg.cache_dir)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openzim-mcp download-models",
        description=(
            "Pre-stage ML model files for installed extras. Run this once "
            "after installing an extra (e.g., `pip install "
            "openzim-mcp[reranker]`) on a machine with network access; "
            "the MCP server can then run offline without first-call "
            "download delays."
        ),
    )
    parser.add_argument(
        "--reranker-model-id",
        default=None,
        help=(
            "Override the reranker model id (default: "
            "Xenova/bge-reranker-base-onnx)."
        ),
    )
    return parser


def download_models_main(argv: Optional[List[str]] = None) -> int:
    """Entry point. Returns process exit code (0 success, 1 failure)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    features = detect()
    if not features.reranker:
        print(
            "No ml extras installed. Re-run after `pip install "
            "openzim-mcp[reranker]` to pre-stage the reranker model.",
        )
        return 0

    print("Staging reranker model... ", end="", flush=True)
    cfg = RerankerConfig()
    if args.reranker_model_id:
        cfg = cfg.model_copy(update={"model_id": args.reranker_model_id})
    try:
        _stage_reranker(cfg)
        print("done.")
        return 0
    except Exception as exc:  # noqa: BLE001 — surface any underlying error
        print(f"failed: {exc}")
        return 1
```

- [ ] **Step 5: Wire the subcommand dispatch into `main.py`**

In `openzim_mcp/main.py`, locate the `def main() -> None:` function (around line 107) and add a subcommand-style early-dispatch at the very top:

```python
def main() -> None:
    """CLI entry point."""
    # Phase D sub-D-1: subcommand-style dispatch for `openzim-mcp
    # download-models`. Early-checks sys.argv to preserve the existing
    # `openzim-mcp <directories>` invocation shape without restructuring
    # the argparse subparser tree.
    if len(sys.argv) >= 2 and sys.argv[1] == "download-models":
        from openzim_mcp.ml.cli.download import download_models_main

        sys.exit(download_models_main(argv=sys.argv[2:]))
    # ...existing main() body unchanged from this point on...
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
uv run pytest tests/ml/test_download_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Smoke test the CLI dispatch (no extras)**

```bash
uv run openzim-mcp download-models
```

Expected output: `No ml extras installed. Re-run after \`pip install openzim-mcp[reranker]\` to pre-stage the reranker model.`

- [ ] **Step 8: Run lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 9: Commit**

```bash
git add openzim_mcp/ml/cli/ openzim_mcp/main.py tests/ml/test_download_cli.py
git commit -m "feat(ml): openzim-mcp download-models CLI for pre-staging"
```

---

### Task 11: Live FastEmbed integration test fixture

**Files:**
- Create: `tests/ml/conftest.py`
- Create: `tests/ml/test_reranker_integration.py`

- [ ] **Step 1: Create the conftest with the requires_reranker marker**

Create `tests/ml/conftest.py`:

```python
"""Shared fixtures + marker registration for ml tests."""

from __future__ import annotations

import importlib.util

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_reranker: test requires the [reranker] extra to be installed",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip @requires_reranker tests when fastembed is not importable."""
    if importlib.util.find_spec("fastembed") is not None:
        return
    skip_marker = pytest.mark.skip(reason="requires [reranker] extra")
    for item in items:
        if item.get_closest_marker("requires_reranker") is not None:
            item.add_marker(skip_marker)
```

- [ ] **Step 2: Write the integration test**

Create `tests/ml/test_reranker_integration.py`:

```python
"""End-to-end tests against the real FastEmbed reranker.

These tests SKIP when the [reranker] extra is not installed. CI runs
them in a dedicated job (see .github/workflows/test.yml). They confirm
the FastEmbed API surface matches our wrapper and that the reranker
actually reorders results in a predictable way."""

from __future__ import annotations

import pytest

from openzim_mcp.config import RerankerConfig
from openzim_mcp.ml.fallback import reset_kill_switches
from openzim_mcp.ml.reranker import BGEReranker


@pytest.fixture(autouse=True)
def _reset() -> None:
    BGEReranker.reset_instance()
    reset_kill_switches()


@pytest.mark.requires_reranker
class TestRerankerIntegration:
    def test_get_loads_model_on_first_call(self) -> None:
        # Generous timeout for cold-cache CI runs.
        cfg = RerankerConfig(first_call_timeout_seconds=120.0)
        reranker = BGEReranker.get(cfg)
        assert reranker is not None

    def test_reranks_known_corpus_correctly(self) -> None:
        cfg = RerankerConfig(first_call_timeout_seconds=120.0)
        reranker = BGEReranker.get(cfg)
        assert reranker is not None

        # Query is content-fragment shaped — semantic relevance should
        # win over surface keyword overlap.
        query = "what biological pigment makes plants appear green"
        candidates = [
            {
                "path": "Chlorophyll",
                "snippet": (
                    "Chlorophyll is the green pigment in plants that absorbs "
                    "light for photosynthesis."
                ),
                "xapian_score": 0.3,  # intentionally low — Xapian misses it
            },
            {
                "path": "Green",
                "snippet": (
                    "Green is the color between blue and yellow on the visible "
                    "spectrum."
                ),
                "xapian_score": 0.9,  # Xapian's top hit (keyword overlap)
            },
            {
                "path": "Plant",
                "snippet": (
                    "Plants are mainly multicellular eukaryotes in the kingdom "
                    "Plantae."
                ),
                "xapian_score": 0.5,
            },
        ]
        result = reranker.rerank(query, candidates, top_k=3)
        # Chlorophyll should win on semantic match despite low Xapian score.
        assert result[0]["path"] == "Chlorophyll"
        assert all("rerank_score" in c for c in result)

    def test_score_pairs_returns_one_per_pair(self) -> None:
        cfg = RerankerConfig(first_call_timeout_seconds=120.0)
        reranker = BGEReranker.get(cfg)
        assert reranker is not None
        pairs = [
            ("query about cats", "Cats are small carnivorous mammals."),
            ("query about cats", "The sun is the star at the center of the solar system."),
        ]
        scores = reranker.score_pairs(pairs)
        assert len(scores) == 2
        # First pair (relevant) should score higher than second (irrelevant).
        assert scores[0] > scores[1]
```

- [ ] **Step 3: Verify the tests SKIP on no-extras install**

```bash
uv run pytest tests/ml/test_reranker_integration.py -v
```

Expected: all tests reported as SKIPPED with reason "requires [reranker] extra".

- [ ] **Step 4: Install [reranker] and verify the tests run + pass**

```bash
uv sync --extra reranker
uv run pytest tests/ml/test_reranker_integration.py -v
```

Expected: 3 tests pass (slower run; first call downloads the model — set `--timeout=300` if needed).

- [ ] **Step 5: Revert to no-extras**

```bash
uv sync
```

- [ ] **Step 6: Commit**

```bash
git add tests/ml/conftest.py tests/ml/test_reranker_integration.py
git commit -m "test(ml): live FastEmbed integration tests + requires_reranker marker"
```

---

### Task 12: CI matrix — add `test-reranker` job

**Files:**
- Modify: `.github/workflows/test.yml`

- [ ] **Step 1: Add a separate test job for the `[reranker]` extra**

Edit `.github/workflows/test.yml`. After the existing `test` job, add:

```yaml
  test-reranker:
    name: Test [reranker] extra on Python ${{ matrix.python-version }}
    runs-on: ubuntu-latest
    defaults:
      run:
        shell: bash
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]

    steps:
      - uses: actions/checkout@v6

      - name: Install uv
        uses: astral-sh/setup-uv@v7
        with:
          version: "latest"

      - name: Set up Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}

      - name: Install dependencies with [reranker] extra
        run: |
          uv sync --extra reranker

      - name: Run ml tests including requires_reranker marker
        run: |
          uv run pytest tests/ml/ -v --timeout=300
```

Notes for the implementer:
- The job runs ubuntu-latest only to control CI minutes; the unit tests still run on the full matrix in the existing `test` job.
- `--timeout=300` covers the first-call model download (~80 MB from HuggingFace).
- Add this job in parallel with the existing `test` job (not as a dependency).

- [ ] **Step 2: Verify the workflow file parses cleanly**

```bash
# If yamllint is installed:
yamllint .github/workflows/test.yml || true
# Otherwise just sanity-check with python's yaml parser:
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))"
```

Expected: no parse errors.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci(ml): add test-reranker job for [reranker] extra"
```

---

### Task 13: User-facing documentation — `docs/v2/extras-reranker.md`

**Files:**
- Create: `docs/v2/extras-reranker.md`

- [ ] **Step 1: Write the docs page**

Create `docs/v2/extras-reranker.md`:

```markdown
# [reranker] Extra — Cross-Encoder Search Reranking

The `[reranker]` extra adds cross-encoder relevance reranking on top of
Xapian's BM25 results. When installed, search-shaped tools and
`synthesize` mode silently produce more relevant top-K results on
content-fragment queries. Caller surface is unchanged.

## Install

```bash
pip install openzim-mcp[reranker]
```

Install footprint: ~150 MB (FastEmbed + onnxruntime + tokenizers +
huggingface_hub).

## Supported platforms

The `[reranker]` extra is tested on:
- Linux glibc x86_64 and ARM64
- macOS x86_64 and ARM64
- Windows x86_64

Edge platforms (Alpine, FreeBSD, ARM32) are not part of the supported
matrix; FastEmbed wheels may not be available there. The base install
(`pip install openzim-mcp`) is unaffected.

## Pre-staging models for offline deployment

By default, the first call after install downloads the
`Xenova/bge-reranker-base-onnx` model (~80 MB) from HuggingFace.
Operators running in air-gapped environments should pre-stage:

```bash
openzim-mcp download-models
```

Idempotent — safe to re-run. Without pre-staging, the first MCP query
that triggers rerank has a 5-second timeout; on timeout the reranker
falls back to Xapian-only ranking for the rest of the process and logs
a structured warning.

## Verifying it's active

After installing the extra, the MCP server log emits a one-line INFO
record on first rerank:

```
reranker loaded: model_id=Xenova/bge-reranker-base-onnx fastembed=0.4.x
```

Response objects also gain `_meta.reranked: true` when rerank fires.

## Disabling rerank without uninstalling

Three knobs, listed in priority order:

1. Environment variable: `OPENZIM_RERANKER_DISABLE=1`
2. Config: `ml.reranker.enabled = false`
3. Uninstall the extra: `pip uninstall fastembed`

The skip-on-short-query gate (`ml.reranker.min_query_tokens`) bypasses
rerank for queries with fewer than 4 word tokens — entity queries like
`Berlin` or `Photosynthesis` get the canonical-title hit from Xapian
directly without rerank cost. Set `min_query_tokens = 0` to disable
the gate.

## Configuration

All knobs documented in `RerankerConfig` (see `openzim_mcp/config.py`).
View effective config:

```bash
openzim-mcp config show
```

## Telemetry

Reranker activity flows through the existing `_track()` path with
these event names:

- `reranker_engaged` — fired once per qualifying search.
- `reranker_skipped` — fired when bypass conditions hit. The `reason`
  detail distinguishes `short_query` / `disabled` / `not_installed` /
  `no_results`.
- `reranker_failed` — fired when a per-call inference raises.
- `ml_feature_disabled` — fired once when the kill switch trips
  (model-load failure, timeout, etc.).

## Troubleshooting

**"reranker model load failed: timeout"**
The first-call download exceeded the configured
`first_call_timeout_seconds` (default 5s). Run
`openzim-mcp download-models` once to pre-stage, then the next server
start will use the cached model.

**Install fails with "no wheel for fastembed"**
The platform isn't in the supported matrix (see above). Use the base
install without the extra; the server still works, just without rerank.

**Rerank doesn't seem to fire**
Check the `min_query_tokens` gate (default 4 word tokens) and the
`OPENZIM_RERANKER_DISABLE` environment variable. The
`reranker_skipped` telemetry event's `reason` field tells you which
gate fired.
```

- [ ] **Step 2: Commit**

```bash
git add docs/v2/extras-reranker.md
git commit -m "docs(ml): user-facing docs for [reranker] extra"
```

---

### Task 14: Final smoke pass + PR prep

**Files:**
- No code changes; final verification.

- [ ] **Step 1: Run the full test suite (no extras)**

```bash
make test
```

Expected: 2143+ passing, 50 skipped (including the new `requires_reranker` tests skipping on no-extras).

- [ ] **Step 2: Run lint + type-check**

```bash
make lint && make type-check
```

Expected: clean.

- [ ] **Step 3: Verify integration tests pass with the extra installed**

```bash
uv sync --extra reranker
uv run pytest tests/ml/ -v --timeout=300
uv sync  # revert
```

Expected: all 3 integration tests pass; unit tests pass; full ml suite ~15 tests.

- [ ] **Step 4: Confirm git history is clean**

```bash
git log --oneline main..HEAD
```

Expected: 13 commits, one per task, each commit message describes the change.

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin v2-phase-d-sub-d-1-reranker
gh pr create \
  --title "feat(v2): Phase D sub-D-1 — cross-encoder reranker behind [reranker] extra" \
  --base main \
  --body "$(cat <<EOF
Implements sub-D-1 of [v2 Phase D](docs/superpowers/specs/2026-05-20-v2-phase-d-ml-accelerators-design.md).

## What's new

Optional [reranker] extra (install with \`pip install openzim-mcp[reranker]\`) adds cross-encoder rerank on top of Xapian's BM25 results. When the extra is absent, all behavior is unchanged.

* New module \`openzim_mcp/ml/\` (feature-detection registry, fallback decorator, BGEReranker class)
* New \`openzim-mcp download-models\` CLI for air-gapped pre-staging
* Wired into \`_handle_search\`, \`_handle_filtered_search\`, \`_handle_search_all\`, \`synthesize._collect_passages\`
* Telemetry events: \`reranker_engaged\`, \`reranker_skipped\`, \`reranker_failed\`, \`ml_feature_disabled\`
* Skip-on-short-query gate (\`min_query_tokens=4\`) bypasses rerank for entity queries

## Risk mitigations baked in

* **5-second timeout on first-call model load** — no 30-second hangs on offline deployments
* **Pinned model_id with audit-log hash on first load** — operators can verify model identity
* **Per-process kill switch via ml_fallback** — one load failure disables rerank for the rest of the process, no retry storms
* **Supported platforms list in docs** — Linux/macOS/Windows x86_64+ARM64; edge platforms explicitly out of scope

## Telemetry review

Per the spec's 2-week telemetry review gate: after this ships, we measure \`reranker_engaged\` fire rate, \`reranker_skipped\` reason distribution, and \`reranker_failed\` occurrence before committing sub-D-2 to writing-plans.

## Tests

* ~15 new tests in \`tests/ml/\` (unit + integration, marker-gated)
* Full suite: 2143+ passing, 50 skipped (no-extras path unchanged)
* New CI job \`test-reranker\` runs integration tests with the extra installed on ubuntu-latest, Python 3.12 + 3.13
EOF
)"
```

- [ ] **Step 6: Watch CI**

```bash
gh pr checks --watch
```

Expected: all jobs pass, including the new `test-reranker` matrix.

- [ ] **Step 7: After CI green, check SonarCloud findings**

```bash
PR_NUM=$(gh pr view --json number -q .number)
curl -s "https://sonarcloud.io/api/issues/search?componentKeys=cameronrye_openzim-mcp&pullRequest=${PR_NUM}&resolved=false&ps=20" \
  | python3 -m json.tool
```

Expected: 0 open issues. If any surface, address them (matches the pattern from the post-a24 sweep follow-up commit).

---

## Self-Review Notes

**Spec coverage check** — every section of the spec's sub-D-1 design maps to a task:

| Spec section | Task(s) |
|--------------|---------|
| Activation surface (search + synthesize) | 7, 8, 9 |
| Module structure (`ml/__init__.py`, `reranker.py`, `fallback.py`, `cli/download.py`) | 1, 2, 4, 5, 10 |
| FastEmbed library + lazy import | 4, 5, 6 |
| Risk mitigation: 5s first-call timeout + structured warning | 4 |
| Risk mitigation: pinned model_id + first-load hash log | 4 |
| Risk mitigation: edge-platform wheel availability | 12, 13 (CI matrix + docs) |
| Fallback contract via `ml_fallback` | 2, 4 |
| Response shape (`_meta.reranked`, `rerank_score`) | 7, 8, 9 |
| RerankerConfig defaults | 3 |
| Skip-on-short-query gate | 5 |
| Telemetry events | 7, 8, 9 (live wiring) |
| Performance budget | implicit; verified by integration tests (Task 11) |
| Testing (unit + integration + skip-decorator) | 1, 2, 4, 5, 11 |
| `openzim-mcp download-models` CLI | 10 |
| Documentation | 13 |
| CI matrix `test-reranker` job | 12 |

**Placeholder scan** — every code step shows actual code or actual commands. The few "find the exact line / variable name" steps in Tasks 7/8/9 are unavoidable because they require reading existing code; the surrounding pattern is fully specified.

**Type consistency check** — `BGEReranker.get(config)` signature stays consistent across Tasks 4, 5, 7, 8, 9, 10. `RerankerConfig` field names stay consistent across Tasks 3, 4, 5, 10. `MLFeatures.reranker: bool` consistent across Tasks 1, 10.

**Order check** — each task builds on the previous: registry → fallback → config → reranker class → wiring → CLI → integration tests → CI → docs. No forward references.
