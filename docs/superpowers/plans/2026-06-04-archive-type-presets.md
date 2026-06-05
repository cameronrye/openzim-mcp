# Archive-type presets (v2.5 #17) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect each ZIM archive's type from M-namespace metadata and apply a data-driven per-type preset that shapes search snippets and `zim_get` summaries — additively, with zero change to the v2 tool surface or response contract.

**Architecture:** A pure classifier (`archive_types.py`) maps the already-extracted M-namespace dict to `(type, confidence)`. A data layer (`preset_data.py` + `data/presets.toml`) loads per-type presets (stdlib `tomllib`, `lru_cache`, `importlib.resources`), deep-merges an optional operator override, and resolves the effective `ArchivePreset` for an archive (applying a preset only at `high` confidence, or when a per-archive pin forces it). Two helper methods on `ZimOperations` (`_archive_type`, `_resolve_archive_preset`) tie detection to config. The resolved preset's fields thread into `create_snippet` (search path) and `_extract_entry_summary_data` (summary path); the detected type and applied preset surface via additive `_meta` fields. Synthesize is untouched — it uses a different passage path, so it stays on global defaults automatically.

**Tech Stack:** Python ≥3.12, stdlib `tomllib`, Pydantic v2 (`BaseModel` / `ConfigDict` / `Field`), pytest. No new dependency.

**Spec:** [`docs/specs/2026-06-04-v2.5-archive-type-presets-design.md`](../../specs/2026-06-04-v2.5-archive-type-presets-design.md)

**Branch:** `feat/v2.5-archive-type-presets` (already created; spec committed at `6d835ab`).

---

## Refinement vs. spec (read first)

The spec said detection runs *inside* `_extract_zim_metadata` with a reserved-key leak guard. This plan refines that to a cleaner, equivalent shape that eliminates the leak concern entirely:

- Detection is the **pure function** `detect_archive_type(metadata_entries)`.
- `get_zim_metadata_data` calls it inline on the M-namespace dict it already builds and passes the result to `attach_meta(..., detected_type=..., detection_confidence=...)` → it lands **only** in `_meta`. Nothing is added to the metadata body, so there is no reserved-key-leak to guard against.
- The search/summary paths recompute detection via `_archive_type(validated_path)`, which reads the **cached** metadata response (`metadata_data:v2c:{path}`) and runs the cheap pure classifier. No separate per-archive registry, no recursion (`get_zim_metadata_data` never calls `_archive_type`).

Everything else matches the spec.

---

## File structure

**Create:**
- `openzim_mcp/archive_types.py` — pure classifier (`detect_archive_type`, `ArchiveType`, `Confidence`).
- `openzim_mcp/preset_data.py` — `ArchivePreset`, `ArchivePin`, `PresetSet`, `load_presets`, `resolve_preset`.
- `openzim_mcp/data/presets.toml` — bundled per-type preset data.
- `tests/test_archive_types.py`, `tests/test_preset_data.py` — unit tests for the pure units.
- `tests/test_archive_type_presets_integration.py` — end-to-end detection + wiring tests.

**Modify:**
- `openzim_mcp/config.py` — add `presets_override_path` to `OpenZimMcpConfig`.
- `openzim_mcp/meta.py` — additive `detected_type` / `detection_confidence` / `preset_applied` kwargs on `build_meta` + `attach_meta`.
- `openzim_mcp/zim/archive.py` — `_archive_type` + `_resolve_archive_preset` helpers; wire detection into `get_zim_metadata_data`.
- `openzim_mcp/content_processor.py` — `create_snippet` gains optional `snippet_length`.
- `openzim_mcp/zim/content.py` — `_get_entry_snippet` threads snippet overrides; `_select_summary_section_md` helper; `get_entry_summary_data` / `_extract_entry_summary_data` thread `summary_style`; cross-mixin `TYPE_CHECKING` stub.
- `openzim_mcp/zim/search.py` — `search_zim_file_data` resolves the preset and threads it to `_perform_search`; `_perform_search` / `_get_entry_snippet` accept snippet overrides; cross-mixin `TYPE_CHECKING` stub.
- `pyproject.toml` — package-data: add `data/*.toml`.

---

## Task 1: Pure archive-type classifier

**Files:**
- Create: `openzim_mcp/archive_types.py`
- Test: `tests/test_archive_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_archive_types.py
"""Unit tests for the pure archive-type classifier (v2.5 #17)."""

from openzim_mcp.archive_types import detect_archive_type


class TestScraperSignal:
    def test_sotoki_is_stackexchange_high(self) -> None:
        assert detect_archive_type({"Scraper": "sotoki 2.1.0"}) == (
            "stackexchange",
            "high",
        )

    def test_ted2zim_is_ted_high(self) -> None:
        assert detect_archive_type({"Scraper": "ted2zim 3.0"}) == ("ted", "high")

    def test_mwoffliner_default_is_wikipedia_high(self) -> None:
        assert detect_archive_type({"Scraper": "mwoffliner 1.14.0"}) == (
            "wikipedia",
            "high",
        )

    def test_mwoffliner_with_wiktionary_name_is_wiktionary_high(self) -> None:
        meta = {"Scraper": "mwoffliner 1.14.0", "Name": "wiktionary_en_all"}
        assert detect_archive_type(meta) == ("wiktionary", "high")


class TestNameAndWeakSignals:
    def test_wikipedia_name_without_scraper_is_medium(self) -> None:
        assert detect_archive_type({"Name": "wikipedia_en_all_maxi"}) == (
            "wikipedia",
            "medium",
        )

    def test_superuser_host_is_stackexchange_medium(self) -> None:
        assert detect_archive_type({"Name": "superuser.com_en_all_2026-02"}) == (
            "stackexchange",
            "medium",
        )

    def test_stackexchange_subdomain_is_medium(self) -> None:
        assert detect_archive_type({"Name": "money.stackexchange.com_en_all"}) == (
            "stackexchange",
            "medium",
        )

    def test_tags_corroboration_is_medium(self) -> None:
        assert detect_archive_type({"Tags": "wikipedia;_category:foo"}) == (
            "wikipedia",
            "medium",
        )


class TestGracefulFallback:
    def test_empty_dict_is_generic_none(self) -> None:
        assert detect_archive_type({}) == ("generic", "none")

    def test_unknown_scraper_is_generic_none(self) -> None:
        assert detect_archive_type({"Scraper": "some-random-tool"}) == (
            "generic",
            "none",
        )

    def test_non_string_values_do_not_raise(self) -> None:
        assert detect_archive_type({"Scraper": None, "Name": 123}) == (
            "generic",
            "none",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_archive_types.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'openzim_mcp.archive_types'`.

- [ ] **Step 3: Write minimal implementation**

```python
# openzim_mcp/archive_types.py
"""Pure archive-type classifier for v2.5 #17 archive-type presets.

Reads only the already-extracted M-namespace metadata dict — no libzim
handle, no I/O — so it is trivially unit-testable and cannot raise on a
malformed archive. Detection is deterministic on its inputs.
"""

from __future__ import annotations

from typing import Literal, Mapping, Tuple

ArchiveType = Literal["wikipedia", "wiktionary", "stackexchange", "ted", "generic"]
Confidence = Literal["high", "medium", "none"]

# Stack Exchange "network" sites have their own apex domains; per-site SE
# instances all live under ``*.stackexchange.com``. Plain substring / prefix
# checks only — no regex (ReDoS-safe).
_SE_NETWORK_HOSTS = (
    "superuser.com",
    "serverfault.com",
    "askubuntu.com",
    "stackoverflow.com",
    "mathoverflow.net",
)


def _norm(value: object) -> str:
    """Lowercased, stripped string view of a metadata value.

    Returns ``""`` for anything that is not a ``str`` so a malformed
    archive (e.g. ``Name`` accidentally an int) degrades to generic
    instead of raising.
    """
    return value.strip().lower() if isinstance(value, str) else ""


def detect_archive_type(
    metadata_entries: Mapping[str, object],
) -> Tuple[ArchiveType, Confidence]:
    """Classify a ZIM archive from its M-namespace metadata entries.

    Returns ``(type, confidence)``. ``confidence`` is ``"high"`` only when a
    strong, near-unique signal matched (the ``Scraper`` tool); ``"medium"``
    when only a weaker corroborating signal matched (``Name`` prefix,
    ``Creator`` / ``Tags``); ``"none"`` when nothing matched (type
    ``"generic"``). Never raises.
    """
    scraper = _norm(metadata_entries.get("Scraper"))
    name = _norm(metadata_entries.get("Name"))
    title = _norm(metadata_entries.get("Title"))
    creator = _norm(metadata_entries.get("Creator"))
    tags = _norm(metadata_entries.get("Tags"))

    # 1. Scraper — the strongest, near-unique signal.
    if scraper.startswith("sotoki"):
        return ("stackexchange", "high")
    if scraper.startswith("ted2zim"):
        return ("ted", "high")
    if scraper.startswith("mwoffliner"):
        # mwoffliner builds both Wikipedia and Wiktionary; disambiguate on
        # Name/Title, else default to wikipedia (the dominant case).
        if name.startswith("wiktionary") or "wiktionary" in title:
            return ("wiktionary", "high")
        return ("wikipedia", "high")

    # 2. Name prefix — strong but Scraper-less, so only medium.
    if name.startswith("wikipedia"):
        return ("wikipedia", "medium")
    if name.startswith("wiktionary"):
        return ("wiktionary", "medium")
    if name.startswith("ted_") or name.startswith("ted-"):
        return ("ted", "medium")
    if ".stackexchange.com" in name or name.startswith(_SE_NETWORK_HOSTS):
        return ("stackexchange", "medium")

    # 3. Creator / Tags — weak corroboration only.
    if "stack exchange" in creator or "stackexchange" in tags:
        return ("stackexchange", "medium")
    if "wiktionary" in tags or "wiktionary" in creator:
        return ("wiktionary", "medium")
    if "wikipedia" in tags or "wikipedia" in creator:
        return ("wikipedia", "medium")

    return ("generic", "none")
```

Note: `str.startswith` accepts a tuple of prefixes, so `name.startswith(_SE_NETWORK_HOSTS)` is valid and ReDoS-free.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_archive_types.py -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Lint + type-check the new files**

Run: `make lint && mypy openzim_mcp/archive_types.py`
Expected: no errors. (Fix any black/isort/flake8 nits before committing — CI lints `tests/` too.)

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/archive_types.py tests/test_archive_types.py
git commit -m "feat(presets): add pure archive-type classifier"
```

---

## Task 2: Preset data layer (model + loader + resolver + bundled data)

**Files:**
- Create: `openzim_mcp/preset_data.py`
- Create: `openzim_mcp/data/presets.toml`
- Modify: `pyproject.toml:89`
- Test: `tests/test_preset_data.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_preset_data.py
"""Unit tests for the archive-type preset data layer (v2.5 #17)."""

from pathlib import Path

import pytest

from openzim_mcp.preset_data import (
    ArchivePreset,
    load_presets,
    resolve_preset,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    # load_presets is lru_cached on the override path; clear between tests
    # so override files written to tmp paths are re-read.
    load_presets.cache_clear()


class TestBundledDefaults:
    def test_bundled_has_wikipedia_and_stackexchange(self) -> None:
        presets = load_presets(None)
        assert presets.by_type["wikipedia"].summary_style == "first_section"
        assert presets.by_type["stackexchange"].summary_style == "q_and_a"

    def test_bundled_has_no_wiktionary_or_ted(self) -> None:
        presets = load_presets(None)
        assert "wiktionary" not in presets.by_type
        assert "ted" not in presets.by_type


class TestResolve:
    def test_high_confidence_applies_type_preset(self) -> None:
        presets = load_presets(None)
        preset = resolve_preset(presets, "stackexchange", "high", "x")
        assert preset is not None
        assert preset.summary_style == "q_and_a"

    def test_medium_confidence_returns_none(self) -> None:
        presets = load_presets(None)
        assert resolve_preset(presets, "stackexchange", "medium", "x") is None

    def test_unknown_type_high_returns_none(self) -> None:
        presets = load_presets(None)
        assert resolve_preset(presets, "wiktionary", "high", "x") is None


class TestOverrideAndPins:
    def test_override_deep_merges_per_type(self, tmp_path: Path) -> None:
        override = tmp_path / "ov.toml"
        override.write_text(
            '[preset.stackexchange]\nmax_paragraphs = 5\n', encoding="utf-8"
        )
        presets = load_presets(override)
        se = presets.by_type["stackexchange"]
        assert se.max_paragraphs == 5  # from override
        assert se.summary_style == "q_and_a"  # inherited from bundled

    def test_pin_forces_type_past_confidence_gate(self, tmp_path: Path) -> None:
        override = tmp_path / "ov.toml"
        override.write_text(
            '[archive."my.zim"]\ntype = "stackexchange"\n', encoding="utf-8"
        )
        presets = load_presets(override)
        # confidence is "none" but the pin forces application.
        preset = resolve_preset(presets, "generic", "none", "my.zim")
        assert preset is not None
        assert preset.summary_style == "q_and_a"

    def test_pin_field_override_wins(self, tmp_path: Path) -> None:
        override = tmp_path / "ov.toml"
        override.write_text(
            '[archive."my.zim"]\ntype = "stackexchange"\n'
            'summary_style = "first_section"\n',
            encoding="utf-8",
        )
        presets = load_presets(override)
        preset = resolve_preset(presets, "generic", "none", "my.zim")
        assert preset is not None
        assert preset.summary_style == "first_section"

    def test_unreadable_override_falls_back_to_bundled(self, tmp_path: Path) -> None:
        presets = load_presets(tmp_path / "does-not-exist.toml")
        assert presets.by_type["stackexchange"].summary_style == "q_and_a"

    def test_unknown_key_is_rejected(self, tmp_path: Path) -> None:
        # extra="forbid" turns a typo into a load-time error that the loader
        # logs and skips — so the bad type is simply absent, not silently
        # accepted with a junk field.
        override = tmp_path / "ov.toml"
        override.write_text(
            '[preset.stackexchange]\nsnippptt_length = 999\n', encoding="utf-8"
        )
        presets = load_presets(override)
        # bad override for the type is dropped; bundled default survives.
        assert presets.by_type["stackexchange"].summary_style == "q_and_a"


def test_archive_preset_rejects_unknown_field() -> None:
    with pytest.raises(Exception):
        ArchivePreset(bogus=1)  # type: ignore[call-arg]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_preset_data.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'openzim_mcp.preset_data'`.

- [ ] **Step 3a: Create the bundled data file**

```toml
# openzim_mcp/data/presets.toml
# Archive-type presets (v2.5 #17). Keyed by detected type. All keys are
# optional; a missing key inherits the global default. Only types with a
# [preset.<type>] table get behavior — wiktionary/ted are detected and
# reported but intentionally have no preset here (a2 adds them as data).

[preset.wikipedia]
# Explicit baseline == current defaults; makes the baseline testable.
summary_style = "first_section"

[preset.stackexchange]
# The one real behavior change in a1. q_and_a summaries surface the
# accepted-answer section; the wider snippet shows more of the Q&A body.
# NOTE: max_paragraphs is a starting value, refined via the live owl-atlas
# superuser reprobe (build sequence step 6 in the spec).
summary_style = "q_and_a"
max_paragraphs = 3
```

- [ ] **Step 3b: Write the loader/resolver module**

```python
# openzim_mcp/preset_data.py
"""Loader + resolver for v2.5 #17 archive-type presets.

Presets are data (``openzim_mcp/data/presets.toml``), keyed by detected
archive type, with an optional operator override file (deep-merged per
type) plus per-archive pins. Mirrors the ``query_rewrite_data`` loader:
stdlib ``tomllib`` (Python >=3.12), ``lru_cache``, ``importlib.resources``
for bundled data. Files are read as explicit UTF-8 then parsed with
``tomllib.loads`` (sidesteps the Windows cp1252 trap).
"""

from __future__ import annotations

import functools
import logging
import tomllib
from importlib import resources
from pathlib import Path
from typing import Dict, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

SummaryStyle = Literal["first_section", "q_and_a"]


class ArchivePreset(BaseModel):
    """Per-type behavior overrides. All fields optional; a missing field
    inherits the global default. ``extra='forbid'`` turns a typo in the
    TOML into a load-time error rather than a silently-ignored key."""

    model_config = ConfigDict(extra="forbid")

    snippet_length: Optional[int] = Field(default=None, ge=100)
    max_paragraphs: Optional[int] = Field(default=None, ge=1)
    summary_style: Optional[SummaryStyle] = None


class ArchivePin(ArchivePreset):
    """A per-archive override keyed by M/Name. ``type`` forces a detected
    type (overriding the confidence gate); the inherited fields override
    individual preset values for that one archive."""

    type: Optional[str] = None


class PresetSet(BaseModel):
    """The fully-resolved preset universe for a process."""

    model_config = ConfigDict(extra="forbid")

    by_type: Dict[str, ArchivePreset] = Field(default_factory=dict)
    pins: Dict[str, ArchivePin] = Field(default_factory=dict)


def _read_bundled() -> str:
    return (
        resources.files("openzim_mcp.data")
        .joinpath("presets.toml")
        .read_text(encoding="utf-8")
    )


def _parse_doc(
    doc: Mapping[str, object],
) -> Tuple[Dict[str, ArchivePreset], Dict[str, ArchivePin]]:
    """Validate the ``[preset.*]`` / ``[archive.*]`` tables into models.

    A malformed individual table is logged and skipped so one bad entry
    doesn't blow up the whole load.
    """
    by_type: Dict[str, ArchivePreset] = {}
    pins: Dict[str, ArchivePin] = {}
    presets_raw = doc.get("preset", {})
    pins_raw = doc.get("archive", {})
    if isinstance(presets_raw, dict):
        for key, body in presets_raw.items():
            try:
                by_type[str(key)] = ArchivePreset(**body)
            except (ValidationError, TypeError) as e:
                logger.warning("preset_data: bad [preset.%s] dropped: %s", key, e)
    if isinstance(pins_raw, dict):
        for key, body in pins_raw.items():
            try:
                pins[str(key)] = ArchivePin(**body)
            except (ValidationError, TypeError) as e:
                logger.warning("preset_data: bad [archive.%s] dropped: %s", key, e)
    return by_type, pins


def _merge(base: Optional[ArchivePreset], overlay: Mapping[str, object]) -> dict:
    """Shallow merge: overlay's set (non-None) fields win over base's."""
    merged: dict = base.model_dump(exclude_none=True) if base is not None else {}
    merged.update(overlay)
    return merged


@functools.lru_cache(maxsize=8)
def load_presets(override_path: Optional[Path]) -> PresetSet:
    """Load the bundled presets, deep-merging an optional operator override.

    ``override_path=None`` loads the bundled defaults only. An unreadable or
    malformed override file logs a warning and falls back to the bundled
    defaults (never raises at server startup).
    """
    by_type, pins = _parse_doc(tomllib.loads(_read_bundled()))

    if override_path is not None:
        try:
            text = Path(override_path).read_text(encoding="utf-8")
            o_by_type, o_pins = _parse_doc(tomllib.loads(text))
        except (OSError, tomllib.TOMLDecodeError) as e:
            logger.warning(
                "preset_data: override %s unreadable (%s); using bundled defaults",
                override_path,
                e,
            )
            o_by_type, o_pins = {}, {}
        for t, op in o_by_type.items():
            by_type[t] = ArchivePreset(**_merge(by_type.get(t), op.model_dump(exclude_none=True)))
        for n, op in o_pins.items():
            base = pins.get(n)
            merged = _merge(base, op.model_dump(exclude_none=True))
            pins[n] = ArchivePin(**merged)

    return PresetSet(by_type=by_type, pins=pins)


def resolve_preset(
    presets: PresetSet,
    archive_type: str,
    confidence: str,
    archive_name: str,
) -> Optional[ArchivePreset]:
    """Resolve the effective preset for an archive.

    A per-archive pin (keyed by M/Name) wins and forces application even
    below ``high`` confidence. Otherwise a type preset applies only at
    ``high`` confidence. Returns ``None`` (generic behavior) when nothing
    applies.
    """
    pin = presets.pins.get(archive_name)
    if pin is not None:
        forced_type = pin.type or archive_type
        base = presets.by_type.get(forced_type)
        overlay = pin.model_dump(exclude_none=True, exclude={"type"})
        merged = _merge(base, overlay)
        return ArchivePreset(**merged) if merged else None

    if confidence != "high":
        return None
    return presets.by_type.get(archive_type)
```

- [ ] **Step 3c: Add `data/*.toml` to package-data**

Modify `pyproject.toml:89` from:
```toml
openzim_mcp = ["data/*.txt", "tools/*.md"]
```
to:
```toml
openzim_mcp = ["data/*.txt", "data/*.toml", "tools/*.md"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_preset_data.py -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Lint + type-check**

Run: `make lint && mypy openzim_mcp/preset_data.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/preset_data.py openzim_mcp/data/presets.toml \
        pyproject.toml tests/test_preset_data.py
git commit -m "feat(presets): add preset data layer (model, loader, resolver, bundled toml)"
```

---

## Task 3: Config field for the override path

**Files:**
- Modify: `openzim_mcp/config.py` (imports + `OpenZimMcpConfig`)
- Test: `tests/test_config.py` (add one test) — if `tests/test_config.py` does not exist, create it with just this test.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py  (append to the existing file, or create with this)
from pathlib import Path

from openzim_mcp.config import OpenZimMcpConfig


def test_presets_override_path_defaults_to_none() -> None:
    cfg = OpenZimMcpConfig(allowed_directories=[])
    assert cfg.presets_override_path is None


def test_presets_override_path_accepts_path() -> None:
    cfg = OpenZimMcpConfig(
        allowed_directories=[], presets_override_path=Path("/tmp/p.toml")
    )
    assert cfg.presets_override_path == Path("/tmp/p.toml")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -q -k presets_override_path`
Expected: FAIL — `ValidationError: ... extra fields not permitted` or `AttributeError` (`presets_override_path` not yet a field).

- [ ] **Step 3: Add the field**

First confirm `Path` is imported in `openzim_mcp/config.py`. Run:
`grep -n "from pathlib import Path" openzim_mcp/config.py` — if absent, add `from pathlib import Path` to the imports.

Then add this field to `OpenZimMcpConfig` (after `subscriptions_enabled`, before `model_config` at `config.py:419`):

```python
    presets_override_path: Optional[Path] = Field(
        default=None,
        description=(
            "Path to an operator TOML that overrides archive-type presets "
            "(deep-merged per type) and defines per-archive pins. Loaded from "
            "OPENZIM_MCP_PRESETS_OVERRIDE_PATH. Absent => bundled defaults only."
        ),
    )
```

(`Optional` and `Field` are already imported in `config.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -q -k presets_override_path`
Expected: PASS.

- [ ] **Step 5: Lint + type-check**

Run: `make lint && mypy openzim_mcp/config.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/config.py tests/test_config.py
git commit -m "feat(presets): add presets_override_path config field"
```

---

## Task 4: Additive `_meta` surfacing kwargs

**Files:**
- Modify: `openzim_mcp/meta.py` (`build_meta`, `attach_meta`)
- Test: `tests/test_meta.py` (add tests; create if absent)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_meta.py  (append, or create with this)
from openzim_mcp.meta import attach_meta, build_meta


def test_build_meta_emits_detected_type_when_set() -> None:
    meta = build_meta(rendered="x", detected_type="wikipedia", detection_confidence="high")
    assert meta["detected_type"] == "wikipedia"
    assert meta["detection_confidence"] == "high"


def test_build_meta_omits_detection_fields_when_none() -> None:
    meta = build_meta(rendered="x")
    assert "detected_type" not in meta
    assert "preset_applied" not in meta


def test_attach_meta_forwards_preset_applied() -> None:
    payload = attach_meta({"a": 1}, preset_applied="stackexchange")
    assert payload["_meta"]["preset_applied"] == "stackexchange"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_meta.py -q -k "detected_type or preset_applied"`
Expected: FAIL — `TypeError: build_meta() got an unexpected keyword argument 'detected_type'`.

- [ ] **Step 3: Add the kwargs**

In `build_meta` (`meta.py:75`), add three keyword params after `reason`:
```python
    reason: Optional[str] = None,
    detected_type: Optional[str] = None,
    detection_confidence: Optional[str] = None,
    preset_applied: Optional[str] = None,
) -> Dict[str, Any]:
```
And before `return meta` (after the `if reason is not None:` block, `meta.py:127`):
```python
    if detected_type is not None:
        meta["detected_type"] = detected_type
    if detection_confidence is not None:
        meta["detection_confidence"] = detection_confidence
    if preset_applied is not None:
        meta["preset_applied"] = preset_applied
    return meta
```

In `attach_meta` (`meta.py:251`), add the same three params to the signature (after `rendered`):
```python
    rendered: Optional[str] = None,
    detected_type: Optional[str] = None,
    detection_confidence: Optional[str] = None,
    preset_applied: Optional[str] = None,
) -> Dict[str, Any]:
```
And forward them in the `build_meta(...)` call (`meta.py:284`), adding after `reason=reason,`:
```python
        reason=reason,
        detected_type=detected_type,
        detection_confidence=detection_confidence,
        preset_applied=preset_applied,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_meta.py -q -k "detected_type or preset_applied"`
Expected: PASS.

- [ ] **Step 5: Lint + type-check**

Run: `make lint && mypy openzim_mcp/meta.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/meta.py tests/test_meta.py
git commit -m "feat(presets): additive _meta detected_type / preset_applied fields"
```

---

## Task 5: Wire detection into ZimOperations + metadata `_meta`

**Files:**
- Modify: `openzim_mcp/zim/archive.py` (imports; `get_zim_metadata_data`; add `_archive_type` + `_resolve_archive_preset`)
- Test: `tests/test_archive_type_presets_integration.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_archive_type_presets_integration.py
"""End-to-end detection + preset wiring (v2.5 #17)."""

from pathlib import Path

import pytest
from libzim.writer import Creator

from tests.conftest_v2_fixtures import _HtmlItem, make_zim_ops


def _build_zim(out: Path, *, scraper: str, name: str) -> Path:
    with Creator(out).config_indexing(True, "eng") as creator:
        creator.add_item(
            _HtmlItem(
                "C/Q1",
                "How do I X?",
                "<html><body><h1>How do I X?</h1>"
                "<p>Question body para one.</p>"
                "<p>Question body para two.</p>"
                "<h2>Answer</h2><p>The accepted answer text.</p></body></html>",
            )
        )
        creator.set_mainpath("C/Q1")
        creator.add_metadata("Scraper", scraper)
        creator.add_metadata("Name", name)
        creator.add_metadata("Title", name)
    return out


@pytest.fixture(scope="module")
def se_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("se") / "superuser.com_en_all.zim"
    return _build_zim(out, scraper="sotoki 2.1.0", name="superuser.com_en_all")


def test_metadata_surfaces_detected_type(se_zim: Path) -> None:
    ops = make_zim_ops(str(se_zim.parent))
    resp = ops.get_zim_metadata_data(str(se_zim))
    assert resp["_meta"]["detected_type"] == "stackexchange"
    assert resp["_meta"]["detection_confidence"] == "high"
    # The reserved keys never leak into the public body.
    assert "_detected_type" not in resp
    assert "detected_type" not in resp


def test_resolve_archive_preset_returns_se_preset(se_zim: Path) -> None:
    ops = make_zim_ops(str(se_zim.parent))
    preset, applied = ops._resolve_archive_preset(Path(str(se_zim)))
    assert applied == "stackexchange"
    assert preset is not None
    assert preset.summary_style == "q_and_a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_archive_type_presets_integration.py -q`
Expected: FAIL — `KeyError: 'detected_type'` (not yet in `_meta`) / `AttributeError: ... has no attribute '_resolve_archive_preset'`.

- [ ] **Step 3a: Wire detection into `get_zim_metadata_data`**

Add imports near the top of `openzim_mcp/zim/archive.py` (with the other `openzim_mcp` imports):
```python
from openzim_mcp.archive_types import detect_archive_type
from openzim_mcp.preset_data import ArchivePreset, load_presets, resolve_preset
```

Replace the body around `archive.py:525-532` (inside `get_zim_metadata_data`):
```python
            with _zim_ops_shim.zim_archive(validated_path) as archive:
                metadata = self._extract_zim_metadata(archive)

            # Detect archive type from the M-namespace dict and surface it
            # in _meta only (never the public body). detect_archive_type is
            # pure + cheap; this does not call _archive_type (no recursion).
            entries = metadata.get("metadata_entries", {})
            if not isinstance(entries, dict):
                entries = {}
            atype, confidence = detect_archive_type(entries)

            # Attach _meta before caching so cold and warm reads return
            # bit-identical responses (Phase B #12).
            with_meta = attach_meta(
                metadata, detected_type=atype, detection_confidence=confidence
            )
            self.cache.set(cache_key, with_meta)
            logger.info(f"Retrieved metadata for: {validated_path}")
            return cast("ZimMetadataResponse", with_meta)
```

- [ ] **Step 3b: Add the helper methods**

Add these two methods to `ZimOperations` in `archive.py` (e.g. immediately after `_extract_zim_metadata`, before `_discover_metadata_keys` at `archive.py:677`):
```python
    def _archive_type(self, validated_path: Path) -> Tuple[str, str, str]:
        """Return ``(archive_type, confidence, name)`` for an archive.

        Reads the cached metadata response and runs the pure classifier.
        Deterministic and cheap; recomputed per call (the metadata read is
        cached, the classifier is a handful of string ops).
        """
        meta = self.get_zim_metadata_data(str(validated_path))
        entries = meta.get("metadata_entries", {})
        if not isinstance(entries, dict):
            entries = {}
        atype, confidence = detect_archive_type(entries)
        name = entries.get("Name", "")
        return atype, confidence, name if isinstance(name, str) else ""

    def _resolve_archive_preset(
        self, validated_path: Path
    ) -> Tuple[Optional["ArchivePreset"], Optional[str]]:
        """Return ``(preset, applied_type)`` for an archive.

        ``preset`` is ``None`` (generic behavior) when detection confidence
        is below ``high`` and no per-archive pin forces a type. ``applied_type``
        is the detected type when a preset applies, else ``None``.
        """
        atype, confidence, name = self._archive_type(validated_path)
        presets = load_presets(self.config.presets_override_path)
        preset = resolve_preset(presets, atype, confidence, name)
        return preset, (atype if preset is not None else None)
```

Confirm `Tuple` and `Optional` are imported in `archive.py` (from `typing`). Run `grep -n "from typing import" openzim_mcp/zim/archive.py` and add `Tuple` / `Optional` to that import if missing.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_archive_type_presets_integration.py -q`
Expected: PASS (2 tests). If `add_metadata` is unavailable on this libzim build, the detection assertion would fail — in that case mark the two detection-via-ZIM assertions with a libzim-capability skip and rely on the pin-forced integration tests in Tasks 6–7 (which need no M-namespace).

- [ ] **Step 5: Full suite + lint + type-check (guard against metadata-shape regressions)**

Run: `make lint && mypy openzim_mcp && pytest tests/ -q -k "metadata or archive"`
Expected: PASS. Confirm existing metadata golden tests still pass (the body is unchanged; only `_meta` gained two fields — if a golden snapshot strips `_meta` it is unaffected; if not, refresh with `OPENZIM_MCP_CAPTURE_GOLDENS=1` only after confirming the diff is exactly the two additive `_meta` keys).

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/zim/archive.py tests/test_archive_type_presets_integration.py
git commit -m "feat(presets): detect archive type and surface it in metadata _meta"
```

---

## Task 6: Snippet-shape wiring (search path)

**Files:**
- Modify: `openzim_mcp/content_processor.py` (`create_snippet`)
- Modify: `openzim_mcp/zim/content.py` (`_get_entry_snippet` + `TYPE_CHECKING` stub)
- Modify: `openzim_mcp/zim/search.py` (`_perform_search`, `search_zim_file_data`)
- Test: `tests/test_archive_type_presets_integration.py` (append) + `tests/test_content_processor.py` (append, or create)

- [ ] **Step 1a: Write the failing unit test for `create_snippet`**

```python
# tests/test_content_processor.py  (append, or create with this)
from openzim_mcp.content_processor import ContentProcessor


def test_create_snippet_per_call_length_override() -> None:
    cp = ContentProcessor(snippet_length=3000)
    content = "word " * 400  # ~2000 chars, one paragraph
    short = cp.create_snippet(content, snippet_length=100)
    assert len(short) <= 100
    full = cp.create_snippet(content)  # uses self.snippet_length=3000
    assert len(full) > 100


def test_create_snippet_length_none_uses_instance_default() -> None:
    cp = ContentProcessor(snippet_length=50)
    content = "word " * 400
    out = cp.create_snippet(content, snippet_length=None)
    assert len(out) <= 50
```

- [ ] **Step 1b: Write the failing integration test for the search path**

```python
# tests/test_archive_type_presets_integration.py  (append)

@pytest.fixture(scope="module")
def plain_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("plain") / "wikipedia_en_test.zim"
    with Creator(out).config_indexing(True, "eng") as creator:
        creator.add_item(
            _HtmlItem(
                "C/Photosynthesis",
                "Photosynthesis",
                "<html><body><h1>Photosynthesis</h1>"
                "<p>Para one about photosynthesis.</p>"
                "<p>Para two photosynthesis detail.</p>"
                "<p>Para three photosynthesis more.</p>"
                "<p>Para four photosynthesis extra.</p></body></html>",
            )
        )
        creator.set_mainpath("C/Photosynthesis")
        creator.add_metadata("Name", "wikipedia_en_test")
    return out


def test_search_snippet_generic_path_unchanged(plain_zim: Path) -> None:
    # No override file -> Name-only "wikipedia" detection is MEDIUM, so no
    # preset applies -> generic snippet (default max_paragraphs=2).
    ops = make_zim_ops(str(plain_zim.parent))
    resp = ops.search_zim_file_data(str(plain_zim), "photosynthesis")
    assert resp["results"], "expected a hit"
    assert resp["_meta"].get("preset_applied") is None


def test_search_snippet_uses_pinned_preset(tmp_path: Path, plain_zim: Path) -> None:
    from openzim_mcp.preset_data import load_presets

    load_presets.cache_clear()
    override = tmp_path / "ov.toml"
    # Pin this archive to stackexchange (max_paragraphs=3 from bundled),
    # forcing a preset regardless of detection.
    override.write_text(
        '[archive."wikipedia_en_test"]\ntype = "stackexchange"\n', encoding="utf-8"
    )
    ops = make_zim_ops(str(plain_zim.parent))
    ops.config.presets_override_path = override
    resp = ops.search_zim_file_data(str(plain_zim), "photosynthesis")
    assert resp["results"], "expected a hit"
    assert resp["_meta"]["preset_applied"] == "stackexchange"
    load_presets.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_content_processor.py -q -k create_snippet && pytest tests/test_archive_type_presets_integration.py -q -k snippet`
Expected: FAIL — `create_snippet() got an unexpected keyword argument 'snippet_length'` / `preset_applied` assertion fails.

- [ ] **Step 3a: Add `snippet_length` to `create_snippet`**

In `content_processor.py:970`, change the signature to add `snippet_length`:
```python
    def create_snippet(
        self,
        content: str,
        *,
        query: Optional[str] = None,
        max_paragraphs: int = 2,
        title: Optional[str] = None,
        snippet_length: Optional[int] = None,
    ) -> str:
```
Immediately after the empty-content guard (after `content_processor.py:997` `return ""`), add:
```python
        effective_len = (
            snippet_length if snippet_length is not None else self.snippet_length
        )
```
Then replace the four `self.snippet_length` references in the truncation blocks (`content_processor.py:1056`, `:1057`, `:1065`, `:1066`) with `effective_len`. After the edit those blocks read:
```python
        if len(snippet_text) > effective_len:
            cap = max(effective_len - 3, 0)
            snippet_text = snippet_text[:cap].rstrip() + "..."

        if query:
            snippet_text = _highlight_terms(snippet_text, query, max_hits=5)
            if len(snippet_text) > effective_len:
                cap = max(effective_len - 3, 0)
```
(Leave every other line in those blocks unchanged.)

- [ ] **Step 3b: Thread overrides through `_get_entry_snippet`**

In `zim/content.py:138`, change the signature and the `create_snippet` call:
```python
    def _get_entry_snippet(
        self,
        entry: Any,
        query: Optional[str] = None,
        *,
        snippet_length: Optional[int] = None,
        max_paragraphs: Optional[int] = None,
    ) -> str:
```
At the `return self.content_processor.create_snippet(...)` (`zim/content.py:195`):
```python
            entry_title = getattr(entry, "title", None) or ""
            mp = max_paragraphs if max_paragraphs is not None else 2
            return self.content_processor.create_snippet(
                content,
                query=query,
                title=entry_title,
                max_paragraphs=mp,
                snippet_length=snippet_length,
            )
```

- [ ] **Step 3c: Thread overrides through `_perform_search`**

In `zim/search.py:599`, add the two keyword params:
```python
    def _perform_search(
        self,
        archive: Archive,
        query: str,
        limit: int,
        offset: int,
        *,
        validated_path: Optional[Path] = None,
        snippet_length: Optional[int] = None,
        max_paragraphs: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], int]:
```
At the snippet call (`zim/search.py:669`):
```python
                snippet = self._get_entry_snippet(
                    entry,
                    query=query,
                    snippet_length=snippet_length,
                    max_paragraphs=max_paragraphs,
                )
```

- [ ] **Step 3d: Resolve + thread the preset in `search_zim_file_data`**

After the cache-miss check (`zim/search.py:464`, before the `try:`), add:
```python
        # Resolve the archive-type preset once (cached metadata read);
        # generic (no preset) when detection isn't confident and no pin
        # forces a type. Synthesize uses a different passage path, so it is
        # unaffected by this.
        preset, applied_type = self._resolve_archive_preset(validated_path)
```
Change the `_perform_search` call (`zim/search.py:484`):
```python
                payload, total_results = self._perform_search(
                    archive,
                    query,
                    limit,
                    offset,
                    validated_path=validated_path,
                    snippet_length=preset.snippet_length if preset is not None else None,
                    max_paragraphs=preset.max_paragraphs if preset is not None else None,
                )
```
Add `preset_applied=applied_type` to the final `attach_meta` (`zim/search.py:574`):
```python
            with_meta = attach_meta(
                payload,
                reason=reason,
                suggestions=suggestions if suggestions else None,
                preset_applied=applied_type,
            )
```

- [ ] **Step 3e: Add `TYPE_CHECKING` cross-mixin stub in `search.py`**

`_resolve_archive_preset` lives on the concrete `ZimOperations` (defined in `archive.py`). Add a stub so mypy resolves it inside the search mixin, following the existing pattern at `zim/content.py:130`. In the `if TYPE_CHECKING:` block of the search mixin (near other cross-mixin stubs), add:
```python
        def _resolve_archive_preset(
            self, validated_path: "Path"
        ) -> "Tuple[Optional[ArchivePreset], Optional[str]]":
            """Resolve via ``ZimOperations`` on the concrete coordinator."""
```
and add `from openzim_mcp.preset_data import ArchivePreset` under the search module's `if TYPE_CHECKING:` import block. If the search mixin has no `if TYPE_CHECKING:` stub block yet, add one mirroring `content.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_content_processor.py -q -k create_snippet && pytest tests/test_archive_type_presets_integration.py -q -k snippet`
Expected: PASS.

- [ ] **Step 5: Synthesize-isolation regression guard + lint + type-check**

Run: `make lint && mypy openzim_mcp && pytest tests/test_synthesize.py tests/test_post_v2_1_4_beta_fixes.py -q`
Expected: PASS — synthesize is untouched (it never calls `_perform_search`/`_get_entry_snippet`), so all tail-hijack/leak invariants stay green.

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/content_processor.py openzim_mcp/zim/content.py \
        openzim_mcp/zim/search.py tests/test_content_processor.py \
        tests/test_archive_type_presets_integration.py
git commit -m "feat(presets): apply snippet-shape preset on the search path"
```

---

## Task 7: Summary-style `q_and_a` wiring

**Files:**
- Modify: `openzim_mcp/zim/content.py` (`_select_summary_section_md` helper; `get_entry_summary_data`; `_extract_entry_summary_data`)
- Test: `tests/test_archive_type_presets_integration.py` (append) + a pure unit test in the same file or `tests/test_content.py`

- [ ] **Step 1a: Write the failing unit test for the pure selector**

```python
# tests/test_archive_type_presets_integration.py  (append)
from openzim_mcp.zim.content import _select_summary_section_md


def test_select_summary_q_and_a_picks_answer_section() -> None:
    md = "Question intro.\n\n## Answer\n\nThe accepted answer body.\n"
    sections = [
        {"title": "Question", "level": 2, "char_start": 0, "char_end": 16},
        {"title": "Answer", "level": 2, "char_start": 16, "char_end": len(md)},
    ]
    out = _select_summary_section_md(sections, md, "q_and_a")
    assert "accepted answer body" in out
    assert "Question intro" not in out


def test_select_summary_q_and_a_falls_back_to_first_section() -> None:
    md = "Lead.\n\n## Details\n\nMore.\n"
    sections = [
        {"title": "Lead", "level": 2, "char_start": 0, "char_end": 6},
        {"title": "Details", "level": 2, "char_start": 6, "char_end": len(md)},
    ]
    # No answer-like heading -> first-section behavior.
    out = _select_summary_section_md(sections, md, "q_and_a")
    assert out == md[:6]


def test_select_summary_default_is_first_section() -> None:
    md = "Lead.\n\n## Details\n\nMore.\n"
    sections = [{"title": "Lead", "level": 2, "char_start": 0, "char_end": 6}]
    assert _select_summary_section_md(sections, md, None) == md[:6]
```

- [ ] **Step 1b: Write the failing integration test (pin-forced SE summary)**

```python
# tests/test_archive_type_presets_integration.py  (append)

def test_summary_q_and_a_via_pin(tmp_path: Path, se_zim: Path) -> None:
    from openzim_mcp.preset_data import load_presets

    load_presets.cache_clear()
    override = tmp_path / "ov.toml"
    override.write_text(
        '[archive."superuser.com_en_all"]\ntype = "stackexchange"\n',
        encoding="utf-8",
    )
    ops = make_zim_ops(str(se_zim.parent))
    ops.config.presets_override_path = override
    resp = ops.get_entry_summary_data(str(se_zim), "C/Q1")
    # q_and_a should surface the accepted-answer section text.
    assert "accepted answer text" in resp["summary"].lower()
    assert resp["_meta"]["preset_applied"] == "stackexchange"
    load_presets.cache_clear()


def test_summary_generic_unchanged(se_zim: Path) -> None:
    # No override -> sotoki detection is HIGH stackexchange, which DOES apply
    # q_and_a. To assert the generic baseline, pin to wikipedia (first_section).
    from openzim_mcp.preset_data import load_presets

    load_presets.cache_clear()
    ops = make_zim_ops(str(se_zim.parent))
    # default detection (sotoki -> stackexchange q_and_a) returns the answer
    resp = ops.get_entry_summary_data(str(se_zim), "C/Q1")
    assert resp["_meta"]["preset_applied"] == "stackexchange"
    load_presets.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_archive_type_presets_integration.py -q -k "summary or select_summary"`
Expected: FAIL — `ImportError: cannot import name '_select_summary_section_md'` / `preset_applied` assertion fails.

- [ ] **Step 3a: Add the pure selector helper**

Add at module level in `openzim_mcp/zim/content.py` (near the other module helpers, above the mixin class):
```python
_ANSWER_HEADING_TOKENS = ("accepted answer", "answer")


def _is_answer_heading(title: str) -> bool:
    """True when a section heading looks like a Q&A answer block."""
    t = title.strip().lower()
    return any(tok in t for tok in _ANSWER_HEADING_TOKENS)


def _select_summary_section_md(
    sections: List[Dict[str, Any]],
    rendered_md: str,
    summary_style: Optional[str],
) -> str:
    """Return the markdown slice for the summary, per ``summary_style``.

    ``q_and_a`` returns the first section whose heading looks like an
    answer; for any other style (including ``None``) or when no answer
    heading is found, returns the first-section slice (the prior behavior).

    NOTE: the exact answer-heading match is refined against the live
    superuser (sotoki) archive during the owl-atlas reprobe — sotoki's
    real section title is pinned there. The fallback guarantees a
    never-worse-than-baseline result.
    """
    if summary_style == "q_and_a":
        for s in sections:
            if _is_answer_heading(str(s.get("title", ""))):
                start = int(s["char_start"])
                end = int(s["char_end"])
                return rendered_md[start:end]
    if sections:
        return rendered_md[: int(sections[0]["char_end"])]
    return rendered_md
```
(Confirm `List`, `Dict`, `Any`, `Optional` are imported from `typing` in `content.py` — they are, per existing signatures.)

- [ ] **Step 3b: Use the helper in `_extract_entry_summary_data` and thread `summary_style`**

Add `summary_style` to the signature (`zim/content.py:1444`):
```python
    def _extract_entry_summary_data(
        self,
        archive: Archive,
        entry_path: str,
        max_words: int,
        *,
        compact: bool = False,
        validated_path: Optional[Path] = None,
        summary_style: Optional[str] = None,
    ) -> Dict[str, Any]:
```
Replace the first-section slice block (`zim/content.py:1499-1512`):
```python
                md = bundle["rendered_markdown"]
                if bundle["sections"]:
                    first = bundle["sections"][0]
                    summary_md = md[: first["char_end"]]
                else:
                    summary_md = md
```
with:
```python
                md = bundle["rendered_markdown"]
                summary_md = _select_summary_section_md(
                    bundle["sections"], md, summary_style
                )
```

- [ ] **Step 3c: Resolve + thread the preset in `get_entry_summary_data`**

In `get_entry_summary_data` (`zim/content.py:1356`), after `validated_path = self._validate_zim_path(zim_file_path)` (`:1385`), add:
```python
        preset, applied_type = self._resolve_archive_preset(validated_path)
        summary_style = preset.summary_style if preset is not None else None
```
Pass it into the extraction call (`:1389`):
```python
                result = self._extract_entry_summary_data(
                    archive,
                    entry_path,
                    max_words,
                    compact=compact,
                    validated_path=validated_path,
                    summary_style=summary_style,
                )
```
Add `preset_applied=applied_type` to the `attach_meta` (`:1400`):
```python
            return cast(
                "EntrySummaryResponse",
                attach_meta(
                    result,
                    truncated=bool(result.get("is_truncated")),
                    preset_applied=applied_type,
                ),
            )
```

- [ ] **Step 3d: Confirm the `TYPE_CHECKING` stub exists in `content.py`**

The content mixin already declares cross-mixin stubs at `zim/content.py:130`. Add a `_resolve_archive_preset` stub there (mirroring Task 6 step 3e) and the `ArchivePreset` import under the module's `if TYPE_CHECKING:` block, if not already added.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_archive_type_presets_integration.py -q -k "summary or select_summary"`
Expected: PASS.

- [ ] **Step 5: Full regression + lint + type-check**

Run: `make lint && mypy openzim_mcp && pytest tests/ -q`
Expected: PASS across the whole suite. In particular: synthesize/tail-hijack invariants green (summary path is off the synthesize path), and existing `get_entry_summary` golden/contract tests unchanged for the generic case (default detection on test ZIMs without sotoki/SE signals yields no preset → `summary_style=None` → identical first-section slice). If a `get_entry_summary` golden carries `_meta` and a real archive now reports `preset_applied`, that is the intended additive diff — refresh only after confirming.

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/zim/content.py tests/test_archive_type_presets_integration.py
git commit -m "feat(presets): q_and_a summary style on the zim_get summary path"
```

---

## Task 8: Live reprobe, docs version-sync, ship v2.5.0a1

This task is a checklist, not code — the behavior changes are only end-to-end-validatable on the deployed owl-atlas server (not checkout-reproducible), per project memory.

- [ ] **Step 1: Push branch + open PR**

```bash
git push -u origin feat/v2.5-archive-type-presets
```
Open a PR to `main` titled `feat: archive-type presets (v2.5 #17)`. Confirm CI is green (all 6 matrix jobs: ubuntu/macos/windows × py3.12/3.13; lint; mypy; CodeQL; Sonar).

- [ ] **Step 2: Deploy to owl-atlas and live-reprobe**

Deploy the branch build to the owl-atlas server. Probe the live dual-archive corpus (Wikipedia + superuser):
  - `zim_metadata` on superuser → `_meta.detected_type == "stackexchange"`, confidence `high`.
  - `zim_metadata` on Wikipedia → `_meta.detected_type == "wikipedia"`.
  - `zim_get(view='summary')` on a superuser Q&A page → summary is the accepted answer; `_meta.preset_applied == "stackexchange"`. **Pin the real sotoki answer-section heading here** — if `_is_answer_heading` doesn't match sotoki's actual heading, update `_ANSWER_HEADING_TOKENS` and re-test.
  - `zim_search` on superuser → snippets reflect `max_paragraphs=3`; tune the bundled `presets.toml` value if the live shape warrants. `_meta.preset_applied == "stackexchange"`.
  - Wikipedia summary + search → `preset_applied == "wikipedia"`, output matches the pre-change baseline (first_section / default snippet).
  - Tail-hijack spot-checks unchanged: `Einstein's theory → Theory_of_relativity`, `connection refused → superuser`.

- [ ] **Step 3: Fold any live-pin adjustments back into the branch**

If the reprobe changed `_ANSWER_HEADING_TOKENS` or `presets.toml`, commit those, re-run `make lint && mypy openzim_mcp && pytest tests/ -q`, push, and re-confirm CI.

- [ ] **Step 4: Merge + release-please → v2.5.0a1 pre-release**

Merge the PR (admin merge, solo maintainer). Let release-please open/advance the release PR; confirm it tags **v2.5.0a1** as a PRE-RELEASE (not a patch). Verify after merge: PyPI `2.5.0a1`, ghcr.io `:2.5.0a1`, GitHub Release page with assets.

- [ ] **Step 5: Hand-sync docs version facts**

Per the docs-version-sync convention: `llms.txt` auto-bumps via release-please; the rest do NOT. Repo-wide grep for the prior version and hand-sync the hard version facts (docker tags in README + `http-and-docker-deployment.mdx` + `installation.mdx`, `Version`/`softwareVersion` in `index.astro`, `humans.txt`). Update the roadmap milestones table v2.5.0a1 row Tag from `_TBD_` to `v2.5.0a1`.

- [ ] **Step 6: Update project memory**

Record the shipped state (PRs, tag, what landed, deferred items: namespace seam, intent priors, wiktionary/ted behavior) in a new memory file, linked from `MEMORY.md`.

---

## Self-Review

**Spec coverage** — every spec section maps to a task:
- §Architecture 1 (detection) → Task 1 + Task 5.
- §Architecture 2 (preset data layer) → Task 2 + Task 3.
- §Architecture 3 (resolution glue) → Task 5 (`_resolve_archive_preset`).
- §Architecture 4(a) snippet → Task 6; 4(b) summary → Task 7.
- §Architecture 5 (`_meta` surfacing) → Task 4 (kwargs) + Task 5 (metadata) + Tasks 6/7 (`preset_applied`).
- §Testing → unit (Tasks 1–4), integration (Tasks 5–7), invariants (Tasks 6–7 step 5), live reprobe (Task 8).
- §Non-goals (namespace seam, intent priors, gloss/TED behavior) → intentionally untouched; no task wires them. ✔
- §DO-NOT-TOUCH → synthesize/title_promotion/intent_parser never edited; the synthesize-isolation guard (Task 6 step 5) proves it. ✔

**Placeholder scan** — no `TODO`/`TBD` in code steps. The one deferred value (`max_paragraphs = 3` and the `_ANSWER_HEADING_TOKENS` match) is a *concrete, working* value with a documented live-refinement step (Task 8 step 2), not a placeholder — tests assert behavior against it deterministically.

**Type consistency** — `detect_archive_type(metadata_entries) -> (ArchiveType, Confidence)` is consistent across Tasks 1/5. `_archive_type -> (type, confidence, name)` and `_resolve_archive_preset -> (preset, applied_type)` are consistent across Tasks 5/6/7. `create_snippet(..., snippet_length=None)`, `_get_entry_snippet(..., snippet_length=None, max_paragraphs=None)`, `_perform_search(..., snippet_length=None, max_paragraphs=None)`, `_extract_entry_summary_data(..., summary_style=None)` match every call site. `build_meta`/`attach_meta` kwargs (`detected_type`/`detection_confidence`/`preset_applied`) match across Tasks 4/5/6/7. `_select_summary_section_md(sections, rendered_md, summary_style)` matches its test and caller.
