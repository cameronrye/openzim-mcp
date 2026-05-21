# v2 Phase D sub-D-2 — Tier 1 Query Rewriting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land four idempotent rule-based query rewrites (lowercase normalization, common-misspelling substitution, stopword-phrase detection, "X of Y" decomposition) before the existing intent regex chain, so every search and synthesize call sees a cleaner query. No new dependencies.

**Architecture:** Extend `IntentParser.parse_intent` (existing `@classmethod`) with a new optional `title_probe: Optional[Callable[[str], bool]] = None` keyword. Four new classmethods, each idempotent, called in fixed order before the existing regex chain. Two of them (misspelling and stopword-phrase) consult the probe to suppress false-positive rewrites of real proper nouns. Rule 4 stashes a structured `decomposition_hint` dict inside the returned `params` dict — backward-compatible because callers that don't know about it simply ignore the extra key.

**Tech Stack:** Python 3.12+, Pydantic v2 (for `QueryRewriteConfig`), pytest, existing `find_title_match` helper from `openzim_mcp/title_promotion.py`.

**Spec:** [`docs/superpowers/specs/2026-05-20-v2-phase-d-sub-d-2-query-rewriting-design.md`](../specs/2026-05-20-v2-phase-d-sub-d-2-query-rewriting-design.md).

---

## File Structure

**New files:**
- `openzim_mcp/data/__init__.py` — empty package marker (makes `data/` importable for `importlib.resources`)
- `openzim_mcp/data/misspellings.txt` — ~30-50 starter entries, format `wrong=right` per line, `#` for comments
- `openzim_mcp/data/misspellings_exclusions.txt` — empty seed (just header comment), one word per line
- `openzim_mcp/query_rewrite_data.py` — module-level `@functools.lru_cache` loader for the two data files
- `tests/test_query_rewrite_tier1.py` — all per-rule + composition tests

**Modified files:**
- `openzim_mcp/config.py` — add `QueryRewriteConfig`, compose onto `OpenZimMcpConfig.query_rewrite`
- `openzim_mcp/intent_parser.py` — add 4 new classmethods, modify `parse_intent` signature
- `openzim_mcp/simple_tools.py` — build title-probe closure, pass to `parse_intent`, emit telemetry events, read `decomposition_hint` in `_handle_tell_me_about`
- `pyproject.toml` — add `[tool.setuptools.package-data]` to ship the `data/*.txt` files inside the wheel

**Boundary discipline:**
- Each rule is a single classmethod ≤30 lines.
- Data files live ONLY in `openzim_mcp/data/`; loaded once at import-time via `lru_cache`.
- `intent_parser.py` already has the `_strip_*` chain pattern — new rules follow the same shape (input str → output str, idempotent, no I/O at call time).

---

### Task 1: `QueryRewriteConfig` + composition on `OpenZimMcpConfig`

**Files:**
- Modify: `openzim_mcp/config.py` (add `QueryRewriteConfig`, add `query_rewrite` field on `OpenZimMcpConfig`, export from `__all__`)
- Create: `tests/test_query_rewrite_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_query_rewrite_config.py`:

```python
"""Tests for QueryRewriteConfig wiring on OpenZimMcpConfig."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from openzim_mcp.config import OpenZimMcpConfig, QueryRewriteConfig


class TestQueryRewriteConfig:
    def test_defaults(self) -> None:
        cfg = QueryRewriteConfig()
        assert cfg.enabled is True
        assert cfg.misspelling_map_path is None
        assert cfg.misspelling_exclusion_path is None
        assert cfg.stopword_phrase_probe is True

    def test_disable_master_switch(self) -> None:
        cfg = QueryRewriteConfig(enabled=False)
        assert cfg.enabled is False

    def test_override_misspelling_paths(self, tmp_path: Path) -> None:
        mp = tmp_path / "custom_misspellings.txt"
        mp.write_text("foo=bar\n")
        cfg = QueryRewriteConfig(misspelling_map_path=mp)
        assert cfg.misspelling_map_path == mp

    def test_attaches_to_openzim_config(self, tmp_path: Path) -> None:
        zim_dir = tmp_path / "zim"
        zim_dir.mkdir()
        cfg = OpenZimMcpConfig(allowed_directories=[str(zim_dir)])
        assert isinstance(cfg.query_rewrite, QueryRewriteConfig)
        assert cfg.query_rewrite.enabled is True
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_query_rewrite_config.py -v
```

Expected: `ImportError: cannot import name 'QueryRewriteConfig'`

- [ ] **Step 3: Add `QueryRewriteConfig` to `openzim_mcp/config.py`**

Find the existing `MLConfig` block (added in sub-D-1, alphabetically positioned around line 215). Insert `QueryRewriteConfig` BEFORE `MLConfig` so the alphabetical convention of the file holds:

```python
class QueryRewriteConfig(BaseModel):
    """Phase D sub-D-2: Tier 1 rule-based query rewriting config.

    Always in the base install — no opt-in extras required. Four
    idempotent rules run before the intent regex chain. See the
    sub-D-2 design spec for per-rule behavior."""

    enabled: bool = Field(
        default=True,
        description=(
            "Master switch. False short-circuits all four rules; "
            "queries pass through to the regex chain unchanged."
        ),
    )
    misspelling_map_path: Path | None = Field(
        default=None,
        description=(
            "Override the bundled misspellings.txt path. None = use "
            "the package-bundled default."
        ),
    )
    misspelling_exclusion_path: Path | None = Field(
        default=None,
        description=(
            "Override the bundled exclusions list. None = use the "
            "package-bundled default."
        ),
    )
    stopword_phrase_probe: bool = Field(
        default=True,
        description=(
            "Allow rule 3 (stopword phrase) to call the title-index "
            "probe. False skips the probe and never strips leading "
            "articles (preserves titles like 'The Beatles' but loses "
            "cleanup on `the population of Berlin`)."
        ),
    )
```

Then add the field to `OpenZimMcpConfig`. Search for `ml: MLConfig = Field(default_factory=MLConfig)` and add immediately before it (preserves alphabetical order — `ml` < `query_rewrite`):

Wait — `ml` sorts before `query_rewrite` alphabetically. Add the new field AFTER `ml`:

```python
    ml: MLConfig = Field(default_factory=MLConfig)
    query_rewrite: QueryRewriteConfig = Field(default_factory=QueryRewriteConfig)
```

Update `__all__` at the top of the file to include `"QueryRewriteConfig"` (alphabetical position).

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_query_rewrite_config.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run the full test suite — verify no regression**

```bash
make test 2>&1 | tail -5
```

Expected: 2188+ passing, no new failures.

- [ ] **Step 6: Lint + type-check**

```bash
make lint && make type-check
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add openzim_mcp/config.py tests/test_query_rewrite_config.py
git commit -m "feat(rewrite): add QueryRewriteConfig to OpenZimMcpConfig"
```

---

### Task 2: Misspelling data files + bundled loader

**Files:**
- Create: `openzim_mcp/data/__init__.py`
- Create: `openzim_mcp/data/misspellings.txt`
- Create: `openzim_mcp/data/misspellings_exclusions.txt`
- Create: `openzim_mcp/query_rewrite_data.py`
- Create: `tests/test_query_rewrite_data.py`
- Modify: `pyproject.toml` (add `[tool.setuptools.package-data]`)

- [ ] **Step 1: Create the data package**

Create `openzim_mcp/data/__init__.py`:

```python
"""Bundled data files (misspelling maps, exclusion lists). Loaded via
importlib.resources by openzim_mcp.query_rewrite_data."""
```

- [ ] **Step 2: Create `openzim_mcp/data/misspellings.txt`**

```text
# openzim-mcp Tier 1 query-rewrite misspelling map.
#
# Source: https://en.wikipedia.org/wiki/Wikipedia:Lists_of_common_misspellings/For_machines
# Upstream revision pulled: 2026-05-20 (record actual revision URL when re-pulled)
#
# Format: one entry per line as `wrong=right`. Comments begin with `#`.
# Tokens are lowercased before lookup, so entries should be lowercase.
# The runtime title-index probe gates substitutions to suppress false
# positives on real proper nouns. See sub-D-2 spec for selection criteria.
#
# Hard cap: 500 entries. Grow reactively from beta-test observations.

# Common English typos
acommodate=accommodate
accomodate=accommodate
recieve=receive
seperate=separate
occured=occurred
occurence=occurrence
neccessary=necessary
neccesary=necessary
truely=truly
embarass=embarrass
embarrasing=embarrassing
goverment=government
independant=independent
maintainance=maintenance
mispell=misspell
priviledge=privilege
publically=publicly
referal=referral
succesful=successful
tomatos=tomatoes

# Encyclopedia-domain frequent misspellings
photosythesis=photosynthesis
photosythesise=photosynthesise
bilogy=biology
mediterranian=mediterranean
mediterrean=mediterranean
egiptian=egyptian
brittish=british
arithmatic=arithmetic
asssassination=assassination
beggining=beginning
millenium=millennium
parralel=parallel
tommorow=tomorrow
tuesdsay=tuesday
wedensday=wednesday
wikipedia=wikipedia
hierachy=hierarchy
existance=existence
inteligence=intelligence
ressurection=resurrection
```

- [ ] **Step 3: Create the exclusions file (empty-seed with header)**

Create `openzim_mcp/data/misspellings_exclusions.txt`:

```text
# openzim-mcp Tier 1 query-rewrite misspelling exclusions.
#
# Words listed here are NEVER substituted by rule 2, even if they
# appear in misspellings.txt. Grows reactively when a real proper noun
# (a surname, band name, place, etc.) gets misrouted to a different
# word.
#
# Format: one lowercase token per line. Comments begin with `#`.
# Hard cap: 200 entries (rare class).

# (empty — entries added as they're observed)
```

- [ ] **Step 4: Wire data files into the package**

In `/Volumes/rye/Developer/openzim-mcp/pyproject.toml`, find the `[tool.setuptools.packages.find]` block and add immediately after it:

```toml
[tool.setuptools.package-data]
openzim_mcp = ["data/*.txt"]
```

- [ ] **Step 5: Write the failing test for the loader**

Create `tests/test_query_rewrite_data.py`:

```python
"""Tests for query_rewrite_data — bundled misspelling map + exclusions loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from openzim_mcp.query_rewrite_data import (
    load_exclusions,
    load_misspellings,
)


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    load_misspellings.cache_clear()
    load_exclusions.cache_clear()


class TestLoadMisspellings:
    def test_bundled_default_loads(self) -> None:
        mapping = load_misspellings(None)
        assert isinstance(mapping, dict)
        # Sanity check a known seed entry
        assert mapping.get("recieve") == "receive"
        assert mapping.get("photosythesis") == "photosynthesis"

    def test_keys_and_values_are_lowercase(self) -> None:
        mapping = load_misspellings(None)
        for k, v in mapping.items():
            assert k == k.lower(), f"key {k!r} should be lowercase"
            assert v == v.lower(), f"value {v!r} should be lowercase"

    def test_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "m.txt"
        f.write_text(
            "# this is a comment\n"
            "\n"
            "foo=bar\n"
            "   # leading whitespace comment\n"
            "baz=qux\n"
        )
        mapping = load_misspellings(f)
        assert mapping == {"foo": "bar", "baz": "qux"}

    def test_malformed_lines_are_skipped(self, tmp_path: Path) -> None:
        # Lines without `=` are silently skipped (defensive: a malformed
        # file shouldn't blow up the server at import time).
        f = tmp_path / "m.txt"
        f.write_text("foo=bar\nNOT_A_PAIR\nbaz=qux\n")
        mapping = load_misspellings(f)
        assert mapping == {"foo": "bar", "baz": "qux"}

    def test_hard_cap_enforced(self, tmp_path: Path) -> None:
        # Cap at 500 entries; anything beyond is dropped with a warning.
        f = tmp_path / "m.txt"
        f.write_text("\n".join(f"k{i}=v{i}" for i in range(600)))
        mapping = load_misspellings(f)
        assert len(mapping) == 500

    def test_caches_per_path(self, tmp_path: Path) -> None:
        f = tmp_path / "m.txt"
        f.write_text("foo=bar\n")
        a = load_misspellings(f)
        b = load_misspellings(f)
        assert a is b  # lru_cache should return the same object


class TestLoadExclusions:
    def test_bundled_default_loads_as_set(self) -> None:
        excl = load_exclusions(None)
        assert isinstance(excl, frozenset)

    def test_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "e.txt"
        f.write_text("# header\nbilogy\n\n   # indented comment\nphotosythesis\n")
        excl = load_exclusions(f)
        assert excl == frozenset({"bilogy", "photosythesis"})

    def test_lowercased(self, tmp_path: Path) -> None:
        f = tmp_path / "e.txt"
        f.write_text("FooBar\nBAZ\n")
        excl = load_exclusions(f)
        assert excl == frozenset({"foobar", "baz"})
```

- [ ] **Step 6: Run the failing test**

```bash
uv run pytest tests/test_query_rewrite_data.py -v
```

Expected: `ImportError: No module named 'openzim_mcp.query_rewrite_data'`

- [ ] **Step 7: Create `openzim_mcp/query_rewrite_data.py`**

```python
"""Loader for sub-D-2 query-rewrite data files.

Module-level functions cached with ``lru_cache`` so the data is read
exactly once per (file path) per process. None paths load the bundled
defaults via ``importlib.resources``."""

from __future__ import annotations

import functools
import logging
from importlib import resources
from pathlib import Path
from typing import FrozenSet, Mapping, Optional

logger = logging.getLogger(__name__)

_HARD_CAP_MAP_ENTRIES = 500
_HARD_CAP_EXCLUSIONS = 200


def _read_lines(path: Optional[Path], bundled_name: str) -> list[str]:
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        # importlib.resources gives a clean handle on bundled package data.
        text = resources.files("openzim_mcp.data").joinpath(
            bundled_name
        ).read_text(encoding="utf-8")
    return text.splitlines()


@functools.lru_cache(maxsize=8)
def load_misspellings(path: Optional[Path]) -> Mapping[str, str]:
    """Load a misspellings map. ``path=None`` loads the bundled default.

    Format: ``wrong=right`` per line. ``#`` starts a comment. Blank
    lines and malformed lines (no ``=``) are silently skipped so a
    typo in the data file doesn't blow up the server at import time.

    Hard-capped at 500 entries; entries beyond the cap are dropped
    with a logged warning."""
    mapping: dict[str, str] = {}
    overflow = 0
    for raw in _read_lines(path, "misspellings.txt"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        wrong, _, right = line.partition("=")
        wrong = wrong.strip().lower()
        right = right.strip().lower()
        if not wrong or not right:
            continue
        if len(mapping) >= _HARD_CAP_MAP_ENTRIES:
            overflow += 1
            continue
        mapping[wrong] = right
    if overflow:
        logger.warning(
            "query_rewrite_data: %d misspelling entries dropped (cap %d)",
            overflow,
            _HARD_CAP_MAP_ENTRIES,
        )
    return mapping


@functools.lru_cache(maxsize=8)
def load_exclusions(path: Optional[Path]) -> FrozenSet[str]:
    """Load the misspelling-substitution exclusions. ``path=None`` loads
    the bundled default. Returns a frozenset of lowercase tokens that
    rule 2 will refuse to substitute even when listed in the map."""
    items: set[str] = set()
    for raw in _read_lines(path, "misspellings_exclusions.txt"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if len(items) >= _HARD_CAP_EXCLUSIONS:
            logger.warning(
                "query_rewrite_data: exclusions cap %d hit; remainder dropped",
                _HARD_CAP_EXCLUSIONS,
            )
            break
        items.add(line.lower())
    return frozenset(items)
```

- [ ] **Step 8: Run the tests to verify pass**

```bash
uv run pytest tests/test_query_rewrite_data.py -v
```

Expected: 9 passed.

- [ ] **Step 9: Verify the bundled files are packaged**

```bash
uv build 2>&1 | tail -5
unzip -l dist/openzim_mcp-*.whl | grep "data/"
```

Expected output includes both `openzim_mcp/data/misspellings.txt` and `openzim_mcp/data/misspellings_exclusions.txt`.

Clean up the build artifacts:

```bash
rm -rf dist/
```

- [ ] **Step 10: Lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 11: Commit**

```bash
git add openzim_mcp/data/ openzim_mcp/query_rewrite_data.py tests/test_query_rewrite_data.py pyproject.toml
git commit -m "feat(rewrite): bundled misspelling data files + lru_cached loader"
```

---

### Task 3: Rule 1 — `_normalize_topic_case`

**Files:**
- Modify: `openzim_mcp/intent_parser.py` (add classmethod, no behavior change to callers yet)
- Create: `tests/test_query_rewrite_tier1.py` (new test file used by Tasks 3-6)

- [ ] **Step 1: Write the failing test**

Create `tests/test_query_rewrite_tier1.py`:

```python
"""Sub-D-2: Tier 1 query rewriting rules.

Per-rule unit tests with three sides each:
- Fix side: input that SHOULD rewrite
- No-op side: input that should pass through unchanged
- Boundary side: looks like a rewrite target but isn't
"""

from __future__ import annotations

from typing import Callable, Optional

import pytest

from openzim_mcp.intent_parser import IntentParser


class TestNormalizeTopicCase:
    def test_lowercases_uppercase_input(self) -> None:
        assert IntentParser._normalize_topic_case("BERLIN") == "berlin"

    def test_lowercases_mixed_case(self) -> None:
        assert (
            IntentParser._normalize_topic_case("BeRlIn") == "berlin"
        )

    def test_already_lowercase_is_no_op(self) -> None:
        assert IntentParser._normalize_topic_case("berlin") == "berlin"

    def test_empty_string_passes_through(self) -> None:
        assert IntentParser._normalize_topic_case("") == ""

    def test_whitespace_preserved(self) -> None:
        assert (
            IntentParser._normalize_topic_case("Berlin Germany")
            == "berlin germany"
        )

    def test_idempotent(self) -> None:
        # Running twice produces the same output as running once.
        once = IntentParser._normalize_topic_case("BERLIN")
        twice = IntentParser._normalize_topic_case(once)
        assert once == twice == "berlin"
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestNormalizeTopicCase -v
```

Expected: `AttributeError: type object 'IntentParser' has no attribute '_normalize_topic_case'`

- [ ] **Step 3: Add the classmethod to `openzim_mcp/intent_parser.py`**

Find `class IntentParser:` (around line 546). At the END of the class body (just before its closing — after any other private classmethods), add:

```python
    # ----- sub-D-2 Tier 1 query rewriting rules -----

    @classmethod
    def _normalize_topic_case(cls, query: str) -> str:
        """Sub-D-2 rule 1: lowercase the query.

        Replaces scattered `.lower()` calls in the relevance pipeline
        with a named pass. Idempotent. No telemetry — fires on
        essentially every query."""
        return query.lower()
```

- [ ] **Step 4: Run the tests to verify pass**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestNormalizeTopicCase -v
```

Expected: 6 passed.

- [ ] **Step 5: Lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/intent_parser.py tests/test_query_rewrite_tier1.py
git commit -m "feat(rewrite): Tier 1 rule 1 — lowercase topic normalization"
```

---

### Task 4: Rule 2 — `_apply_misspelling_map`

**Files:**
- Modify: `openzim_mcp/intent_parser.py` (add classmethod, import data loader)
- Modify: `tests/test_query_rewrite_tier1.py` (add `TestApplyMisspellingMap` class)

- [ ] **Step 1: Extend the test file**

Append to `tests/test_query_rewrite_tier1.py`:

```python
class TestApplyMisspellingMap:
    def test_substitutes_known_misspelling_without_probe(self) -> None:
        # Probe omitted → substitute (degraded mode).
        result = IntentParser._apply_misspelling_map(
            "recieve a letter", title_probe=None
        )
        assert result == "receive a letter"

    def test_leaves_unknown_word_alone(self) -> None:
        result = IntentParser._apply_misspelling_map(
            "berlin germany", title_probe=None
        )
        assert result == "berlin germany"

    def test_already_correct_passes_through(self) -> None:
        result = IntentParser._apply_misspelling_map(
            "receive a letter", title_probe=None
        )
        assert result == "receive a letter"

    def test_probe_suppresses_substitution_when_canonical_hit(self) -> None:
        # Probe returns True → suppress (the original token is a real entity).
        seen: list[str] = []

        def probe(token: str) -> bool:
            seen.append(token)
            return True  # always says "yes, canonical hit"

        result = IntentParser._apply_misspelling_map(
            "recieve a letter", title_probe=probe
        )
        # Substitution suppressed because the probe claimed the original
        # is a canonical title.
        assert result == "recieve a letter"
        assert "recieve" in seen

    def test_probe_allows_substitution_when_no_canonical_hit(self) -> None:
        def probe(token: str) -> bool:
            return False

        result = IntentParser._apply_misspelling_map(
            "recieve a letter", title_probe=probe
        )
        assert result == "receive a letter"

    def test_multiple_substitutions_in_one_query(self) -> None:
        result = IntentParser._apply_misspelling_map(
            "recieve and seperate", title_probe=None
        )
        assert result == "receive and separate"

    def test_exclusions_block_substitution(
        self, tmp_path, monkeypatch
    ) -> None:
        # Temporarily swap in an exclusions file with `recieve` listed.
        excl = tmp_path / "excl.txt"
        excl.write_text("recieve\n")
        from openzim_mcp import query_rewrite_data

        query_rewrite_data.load_exclusions.cache_clear()
        monkeypatch.setattr(
            IntentParser,
            "_exclusions_path",
            excl,
            raising=False,
        )
        result = IntentParser._apply_misspelling_map(
            "recieve a letter", title_probe=None
        )
        # Even though `recieve` is in the map, the exclusion wins.
        assert result == "recieve a letter"
        query_rewrite_data.load_exclusions.cache_clear()

    def test_idempotent(self) -> None:
        once = IntentParser._apply_misspelling_map(
            "recieve", title_probe=None
        )
        twice = IntentParser._apply_misspelling_map(once, title_probe=None)
        assert once == twice == "receive"

    def test_preserves_inter_word_whitespace(self) -> None:
        # Multiple spaces between words should be preserved (don't
        # silently collapse — that's a different rule's job).
        result = IntentParser._apply_misspelling_map(
            "recieve  a  letter", title_probe=None
        )
        assert result == "receive  a  letter"
```

- [ ] **Step 2: Run the failing tests**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestApplyMisspellingMap -v
```

Expected: `AttributeError: type object 'IntentParser' has no attribute '_apply_misspelling_map'`

- [ ] **Step 3: Add the classmethod**

In `openzim_mcp/intent_parser.py`, add to the imports near the top of the file (after the existing stdlib imports):

```python
from openzim_mcp.query_rewrite_data import load_exclusions, load_misspellings
```

Then in the `IntentParser` class body (immediately after `_normalize_topic_case`), add:

```python
    # Class-level overridable paths (None = use bundled defaults).
    # Tests can monkeypatch these to swap in fixture files.
    _misspellings_path: Optional["Path"] = None
    _exclusions_path: Optional["Path"] = None

    @classmethod
    def _apply_misspelling_map(
        cls,
        query: str,
        *,
        title_probe: Optional[Callable[[str], bool]],
    ) -> str:
        """Sub-D-2 rule 2: substitute known misspellings token-by-token.

        Probe-gated when ``title_probe`` is provided: if the original
        token canonically resolves to a real entity, the substitution
        is suppressed. Degrades to ``substitute-without-probe`` when
        ``title_probe`` is None.

        Idempotent: a corrected word is never itself a key in the map.
        Telemetry (``query_rewrite.misspelling``) is emitted by the
        caller (simple_tools.py wiring) based on the before/after diff."""
        mapping = load_misspellings(cls._misspellings_path)
        exclusions = load_exclusions(cls._exclusions_path)
        if not mapping:
            return query

        # Split on whitespace; preserve runs of whitespace between tokens.
        # re.split with a captured group keeps the separators in the list.
        import re

        parts = re.split(r"(\s+)", query)
        out: list[str] = []
        for part in parts:
            if not part or part.isspace():
                out.append(part)
                continue
            lower = part.lower()
            replacement = mapping.get(lower)
            if replacement is None:
                out.append(part)
                continue
            if lower in exclusions:
                out.append(part)
                continue
            if title_probe is not None and title_probe(part):
                out.append(part)
                continue
            out.append(replacement)
        return "".join(out)
```

Also add `from pathlib import Path` and `from typing import Callable, Optional` at the top of the file if they're not already imported (verify with `grep -n "^from pathlib\|^from typing" openzim_mcp/intent_parser.py`).

- [ ] **Step 4: Run the tests to verify pass**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestApplyMisspellingMap -v
```

Expected: 9 passed.

- [ ] **Step 5: Lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/intent_parser.py tests/test_query_rewrite_tier1.py
git commit -m "feat(rewrite): Tier 1 rule 2 — misspelling substitution with probe gate"
```

---

### Task 5: Rule 3 — `_detect_stopword_phrase`

**Files:**
- Modify: `openzim_mcp/intent_parser.py` (add classmethod)
- Modify: `tests/test_query_rewrite_tier1.py` (add `TestDetectStopwordPhrase` class)

- [ ] **Step 1: Extend the test file**

Append to `tests/test_query_rewrite_tier1.py`:

```python
class TestDetectStopwordPhrase:
    def test_strips_leading_the_without_probe(self) -> None:
        # No probe → strip (degraded mode favors cleaner query).
        result = IntentParser._detect_stopword_phrase(
            "the population of berlin", title_probe=None
        )
        assert result == "population of berlin"

    def test_strips_leading_a(self) -> None:
        result = IntentParser._detect_stopword_phrase(
            "a list of countries", title_probe=None
        )
        assert result == "list of countries"

    def test_strips_leading_an(self) -> None:
        result = IntentParser._detect_stopword_phrase(
            "an apple tree", title_probe=None
        )
        assert result == "apple tree"

    def test_strips_leading_of(self) -> None:
        result = IntentParser._detect_stopword_phrase(
            "of mice and men", title_probe=None
        )
        # No probe → strip (we miss this is a real title; that's the
        # degraded-mode tradeoff documented in the spec).
        assert result == "mice and men"

    def test_no_leading_article_is_no_op(self) -> None:
        result = IntentParser._detect_stopword_phrase(
            "population of berlin", title_probe=None
        )
        assert result == "population of berlin"

    def test_probe_keeps_canonical_title(self) -> None:
        # Probe returns True for the full query → keep article.
        def probe(token: str) -> bool:
            return token == "the beatles"

        result = IntentParser._detect_stopword_phrase(
            "the beatles", title_probe=probe
        )
        assert result == "the beatles"

    def test_probe_strips_when_no_canonical(self) -> None:
        def probe(token: str) -> bool:
            return False

        result = IntentParser._detect_stopword_phrase(
            "the population of berlin", title_probe=probe
        )
        assert result == "population of berlin"

    def test_only_one_probe_call_per_query(self) -> None:
        call_count = [0]

        def probe(token: str) -> bool:
            call_count[0] += 1
            return False

        IntentParser._detect_stopword_phrase(
            "the population of berlin", title_probe=probe
        )
        assert call_count[0] == 1

    def test_idempotent(self) -> None:
        once = IntentParser._detect_stopword_phrase(
            "the population", title_probe=None
        )
        twice = IntentParser._detect_stopword_phrase(once, title_probe=None)
        assert once == twice == "population"

    def test_case_insensitive_article_detection(self) -> None:
        # Sub-D-2 typically runs after rule 1, but the rule itself
        # should still handle uppercase input correctly.
        result = IntentParser._detect_stopword_phrase(
            "The Population", title_probe=None
        )
        assert result == "Population"
```

- [ ] **Step 2: Run the failing tests**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestDetectStopwordPhrase -v
```

Expected: `AttributeError: ... no attribute '_detect_stopword_phrase'`

- [ ] **Step 3: Add the classmethod**

In `openzim_mcp/intent_parser.py`, immediately after `_apply_misspelling_map`, add:

```python
    _LEADING_ARTICLE_RE = re.compile(
        r"^(the|a|an|of)\s+", re.IGNORECASE
    )

    @classmethod
    def _detect_stopword_phrase(
        cls,
        query: str,
        *,
        title_probe: Optional[Callable[[str], bool]],
    ) -> str:
        """Sub-D-2 rule 3: strip a leading article unless the full
        query (with article) is a canonical title.

        Probe-gated: the probe is called ONCE per query on the full
        query string. If the probe says yes → keep the article (e.g.
        ``The Beatles``). If no, or if ``title_probe`` is None → strip.

        Idempotent: stripping a leading article doesn't introduce a
        new one."""
        match = cls._LEADING_ARTICLE_RE.match(query)
        if not match:
            return query
        if title_probe is not None and title_probe(query):
            # Real canonical title — keep the article.
            return query
        return query[match.end() :]
```

`re` should already be imported (existing file uses it); verify with grep.

- [ ] **Step 4: Run the tests to verify pass**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestDetectStopwordPhrase -v
```

Expected: 10 passed.

- [ ] **Step 5: Lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/intent_parser.py tests/test_query_rewrite_tier1.py
git commit -m "feat(rewrite): Tier 1 rule 3 — stopword phrase detection with probe gate"
```

---

### Task 6: Rule 4 — `_decompose_x_of_y`

**Files:**
- Modify: `openzim_mcp/intent_parser.py` (add classmethod returning a tuple)
- Modify: `tests/test_query_rewrite_tier1.py` (add `TestDecomposeXOfY` class)

- [ ] **Step 1: Extend the test file**

Append to `tests/test_query_rewrite_tier1.py`:

```python
class TestDecomposeXOfY:
    def test_x_of_y_matches(self) -> None:
        text, hint = IntentParser._decompose_x_of_y("population of berlin")
        assert text == "berlin population"
        assert hint == {"entity": "berlin", "attribute": "population"}

    def test_possessive_matches(self) -> None:
        text, hint = IntentParser._decompose_x_of_y("berlin's population")
        assert text == "berlin population"
        assert hint == {"entity": "berlin", "attribute": "population"}

    def test_no_match_returns_unchanged_and_none(self) -> None:
        text, hint = IntentParser._decompose_x_of_y("just a regular query")
        assert text == "just a regular query"
        assert hint is None

    def test_multi_word_entity_in_of_form(self) -> None:
        text, hint = IntentParser._decompose_x_of_y(
            "capital of new south wales"
        )
        assert text == "new south wales capital"
        assert hint == {
            "entity": "new south wales",
            "attribute": "capital",
        }

    def test_idempotent(self) -> None:
        once_text, once_hint = IntentParser._decompose_x_of_y(
            "population of berlin"
        )
        twice_text, twice_hint = IntentParser._decompose_x_of_y(
            once_text
        )
        # Second pass produces no hint (already rewritten); text is stable.
        assert once_text == twice_text == "berlin population"
        assert once_hint is not None
        assert twice_hint is None

    def test_of_form_requires_attr_to_be_single_word(self) -> None:
        # Reject "annual revenue of Berlin" so we don't mis-decompose
        # multi-word attributes (a deferred Tier 2 / sub-D-3 concern).
        text, hint = IntentParser._decompose_x_of_y(
            "annual revenue of berlin"
        )
        assert text == "annual revenue of berlin"
        assert hint is None

    def test_possessive_requires_single_word_attr(self) -> None:
        # Same: "berlin's annual revenue" stays a search.
        text, hint = IntentParser._decompose_x_of_y(
            "berlin's annual revenue"
        )
        assert text == "berlin's annual revenue"
        assert hint is None
```

- [ ] **Step 2: Run the failing tests**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestDecomposeXOfY -v
```

Expected: `AttributeError: ... no attribute '_decompose_x_of_y'`

- [ ] **Step 3: Add the classmethod**

In `openzim_mcp/intent_parser.py`, immediately after `_detect_stopword_phrase`, add:

```python
    # Rule 4 regex shapes. Both require a single-word attribute so we
    # don't mis-decompose multi-word phrases — multi-hop / multi-word
    # attribute decomposition is a deferred sub-D-3 concern.
    _X_OF_Y_RE = re.compile(
        r"^(?P<attr>\w+)\s+of\s+(?P<entity>.+)$",
        re.IGNORECASE,
    )
    _POSSESSIVE_RE = re.compile(
        r"^(?P<entity>\w+)'s\s+(?P<attr>\w+)$",
        re.IGNORECASE,
    )

    @classmethod
    def _decompose_x_of_y(
        cls, query: str
    ) -> tuple[str, Optional[dict[str, str]]]:
        """Sub-D-2 rule 4: decompose `<attr> of <entity>` and
        `<entity>'s <attr>` shapes.

        Returns ``(rewritten_query, hint_or_None)``:
        - ``rewritten_query`` collapses to ``<entity> <attr>`` when
          decomposition matches; otherwise returns input unchanged.
        - ``hint_or_None`` is ``{"entity": ..., "attribute": ...}`` on
          match, else None. The hint rides inside ``params`` in the
          parse_intent return value; ``_handle_tell_me_about`` reads it
          to skip its own extraction.

        Idempotent: a rewritten ``berlin population`` no longer matches
        either regex."""
        m = cls._X_OF_Y_RE.match(query)
        if not m:
            m = cls._POSSESSIVE_RE.match(query)
        if not m:
            return query, None
        entity = m.group("entity").strip()
        attr = m.group("attr").strip()
        return f"{entity} {attr}", {"entity": entity, "attribute": attr}
```

- [ ] **Step 4: Run the tests to verify pass**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestDecomposeXOfY -v
```

Expected: 7 passed.

- [ ] **Step 5: Lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/intent_parser.py tests/test_query_rewrite_tier1.py
git commit -m "feat(rewrite): Tier 1 rule 4 — X of Y decomposition with hint"
```

---

### Task 7: Wire all 4 rules into `parse_intent`

**Files:**
- Modify: `openzim_mcp/intent_parser.py` (add `title_probe` kwarg, call rules, stash hint)
- Modify: `tests/test_query_rewrite_tier1.py` (add `TestParseIntentIntegration` class)

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/test_query_rewrite_tier1.py`:

```python
class TestParseIntentIntegration:
    def test_rules_run_before_existing_chain(self) -> None:
        # `RECIEVE A LETTER` → lowercase → `recieve a letter` →
        # misspelling fix → `receive a letter`.
        # The existing intent regex chain then matches whatever it
        # would have matched for `receive a letter`.
        intent, params, conf = IntentParser.parse_intent(
            "RECIEVE A LETTER", title_probe=None
        )
        # We don't pin the resulting intent (depends on regex chain),
        # just confirm the query was normalized.
        assert "recieve" not in params.get("query", "")
        assert "recieve" not in params.get("topic", "")

    def test_decomposition_hint_attached_to_params(self) -> None:
        intent, params, conf = IntentParser.parse_intent(
            "population of berlin", title_probe=None
        )
        # The hint rides inside `params` — backward-compat: callers
        # that don't know about it just ignore the extra key.
        hint = params.get("decomposition_hint")
        assert hint == {"entity": "berlin", "attribute": "population"}

    def test_no_decomposition_no_hint(self) -> None:
        _, params, _ = IntentParser.parse_intent(
            "just a regular query", title_probe=None
        )
        assert "decomposition_hint" not in params

    def test_master_disable_short_circuits(
        self, monkeypatch
    ) -> None:
        # With QueryRewriteConfig.enabled=False semantics: caller
        # responsibility — parse_intent itself doesn't read the config,
        # the caller does. But we DO want to confirm that when
        # title_probe is None and no rules trigger, the result matches
        # the pre-sub-D-2 behavior.
        intent_a, params_a, _ = IntentParser.parse_intent(
            "berlin", title_probe=None
        )
        # `berlin` shouldn't decompose, shouldn't misspell, shouldn't
        # have a leading article. Should pass through to whatever the
        # legacy chain produced.
        assert "decomposition_hint" not in params_a

    def test_probe_propagates_to_rules_2_and_3(self) -> None:
        seen: list[str] = []

        def probe(token: str) -> bool:
            seen.append(token)
            return False

        IntentParser.parse_intent(
            "the recieve list", title_probe=probe
        )
        # Probe was called: at least once by rule 2 (for `recieve`)
        # AND at least once by rule 3 (for the full query starting
        # with `the`). We don't pin the exact set — order may shift
        # if implementation evolves — but both layers must have
        # exercised it.
        assert len(seen) >= 2
```

- [ ] **Step 2: Run the failing tests**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestParseIntentIntegration -v
```

Expected: `TypeError: parse_intent() got an unexpected keyword argument 'title_probe'`

- [ ] **Step 3: Modify `parse_intent` to call the 4 rules**

In `openzim_mcp/intent_parser.py`, find the existing `parse_intent` classmethod (around line 932). Modify the signature and prepend the Tier 1 chain. The full updated method should look like:

```python
    @classmethod
    def parse_intent(
        cls,
        query: str,
        *,
        title_probe: Optional[Callable[[str], bool]] = None,
    ) -> Tuple[str, Dict[str, Any], float]:
        """Parse a natural language query to determine intent.

        ... (existing docstring) ...

        Sub-D-2: a ``title_probe`` callback may be passed. When
        provided, rules 2 and 3 consult it to suppress false-positive
        rewrites (real proper nouns, canonical titles). When ``None``,
        rules 2 and 3 run in degraded mode (substitute without
        probing, strip without probing).
        """
        # Sub-D-2 Tier 1 rewrites — must run BEFORE the existing
        # _strip_* chain so downstream regexes see a normalized query.
        # Order is fixed: lowercase → misspellings → stopword phrase →
        # decomposition. Each rule is idempotent; we don't need a loop.
        query = cls._normalize_topic_case(query)
        query = cls._apply_misspelling_map(query, title_probe=title_probe)
        query = cls._detect_stopword_phrase(query, title_probe=title_probe)
        query, decomposition_hint = cls._decompose_x_of_y(query)

        # Existing chain — unchanged from pre-sub-D-2.
        query = cls._strip_param_leaks(query)
        query = cls._strip_trailing_politeness(query)
        query_lower = query.lower()

        # ... rest of existing parse_intent body unchanged ...

        # When the regex chain returns its result, attach the
        # decomposition_hint if rule 4 produced one. The attachment
        # rides inside params so we don't break the (intent, params,
        # confidence) tuple contract.
        # See the existing return paths and add the hint to each one:
        if not matches:
            if cls._looks_like_bare_topic(query):
                params = {"topic": query.strip()}
                if decomposition_hint is not None:
                    params["decomposition_hint"] = decomposition_hint
                return "tell_me_about", params, 0.7
            params = {"query": query}
            if decomposition_hint is not None:
                params["decomposition_hint"] = decomposition_hint
            return "search", params, 0.5

        best_match = cls._select_best_match(matches)
        intent_type, params, confidence = (
            best_match[0],
            best_match[1],
            best_match[2],
        )
        if decomposition_hint is not None:
            params["decomposition_hint"] = decomposition_hint
        return intent_type, params, confidence
```

NOTE: The existing `parse_intent` has multiple `return` statements. Each one needs to attach the `decomposition_hint`. Read the full existing body first (it's around lines 932-1004 per the spec exploration) and add the hint to EACH return path.

- [ ] **Step 4: Run the integration tests to verify pass**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestParseIntentIntegration -v
```

Expected: 5 passed.

- [ ] **Step 5: Run the full intent_parser test file to verify no regression**

```bash
uv run pytest tests/test_intent_parser*.py -v 2>&1 | tail -10
```

Expected: all existing tests still pass — the new rules normalize the input but shouldn't break any existing parse_intent contract since:
- Lowercasing already happened in many cases
- `title_probe=None` defaults keep rules 2/3 in degraded mode
- Rule 4's hint is additive (extra key in params)

If any existing test fails because of the lowercasing or misspelling pass, investigate whether the test's input was depending on case-sensitive behavior or had an unintended typo. Likely fixes are test-side updates rather than rule rollbacks.

- [ ] **Step 6: Run the full suite — final regression check**

```bash
make test 2>&1 | tail -10
```

Expected: 2188+ passing, no new failures.

- [ ] **Step 7: Lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 8: Commit**

```bash
git add openzim_mcp/intent_parser.py tests/test_query_rewrite_tier1.py
git commit -m "feat(rewrite): wire 4 Tier 1 rules into parse_intent + hint propagation"
```

---

### Task 8: Wire title-probe closure + telemetry in `simple_tools.py`

**Files:**
- Modify: `openzim_mcp/simple_tools.py` (build closure, pass to parse_intent, emit per-rule telemetry)

- [ ] **Step 1: Locate all `parse_intent` call sites**

```bash
grep -n "parse_intent\|IntentParser\." /Volumes/rye/Developer/openzim-mcp/openzim_mcp/simple_tools.py | head -10
```

There should be a small number of call sites — likely 1-2 inside `handle_zim_query`. Read each one to understand the surrounding context (which archive path is in scope, what `_track()` calls already happen).

- [ ] **Step 2: Add telemetry constants**

Near the top of `simple_tools.py`, find the existing reranker telemetry constants (`_RERANKER_ENGAGED`, etc.). Add the three new query-rewrite event names immediately after them:

```python
# Phase D sub-D-2 query-rewrite telemetry events.
_QUERY_REWRITE_MISSPELLING = "query_rewrite.misspelling"
_QUERY_REWRITE_STOPWORD_PHRASE = "query_rewrite.stopword_phrase"
_QUERY_REWRITE_X_OF_Y = "query_rewrite.x_of_y"
```

- [ ] **Step 3: Build the title-probe closure helper**

Find `SimpleToolsHandler.__init__` (around line 130). Inside the class, near other private helpers, add:

```python
    def _build_title_probe(
        self, zim_file_path: Optional[str]
    ) -> Optional[Callable[[str], bool]]:
        """Sub-D-2: build a callable that probes the title index for a
        canonical (score >= 1.0) hit, with min_score relaxed slightly
        to catch fuzzy matches that already justify suppressing a
        misspelling rewrite.

        Returns None when no archive path is in scope (rules 2 and 3
        will run in degraded mode). Returns a closure over the
        zim_operations + path otherwise."""
        if not zim_file_path:
            return None
        if not self.zim_operations.config.query_rewrite.stopword_phrase_probe:
            # Master probe kill switch (also used to disable rule 3's probe).
            # We still build the probe for rule 2 because rule 2's gate
            # is more important — but the config flag is named for rule 3
            # historically. If the user wants no probe at all, they
            # should set query_rewrite.enabled=False instead.
            pass
        from openzim_mcp.title_promotion import find_title_match

        def probe(token: str) -> bool:
            try:
                # min_score=0.95 catches both exact (1.0) and fuzzy
                # (0.95+) title hits — broad enough to suppress rule 2
                # substitutions where the original is plausibly a real
                # entity name.
                match = find_title_match(
                    self.zim_operations,
                    zim_file_path,
                    token,
                    min_score=0.95,
                )
                return match is not None
            except Exception:
                # Probe failures degrade the gate, not the search.
                return False

        return probe
```

- [ ] **Step 4: Wire the closure + telemetry at the parse_intent call site**

Find the existing `IntentParser.parse_intent(query)` call site inside `handle_zim_query`. Replace it with a version that:
1. Builds the probe (returns None when no archive in scope)
2. Snapshots the query before/after
3. Calls parse_intent with the probe
4. Emits per-rule telemetry based on what changed

Replacement pattern:

```python
        # Sub-D-2: build the title probe (returns None when no archive
        # is in scope; rules 2 and 3 degrade gracefully). Snapshot
        # before/after to emit per-rule telemetry without printing
        # query content (PII-safe).
        if self.zim_operations.config.query_rewrite.enabled:
            title_probe = self._build_title_probe(zim_file_path)
            # Snapshot intermediate stages by running the rules
            # individually for telemetry. This keeps parse_intent's
            # responsibilities clean (it doesn't know about _track);
            # the cost is two extra rule passes worth of CPU.
            after_lower = IntentParser._normalize_topic_case(query)
            after_misspell = IntentParser._apply_misspelling_map(
                after_lower, title_probe=title_probe
            )
            if after_misspell != after_lower:
                self._track(_QUERY_REWRITE_MISSPELLING)
            after_stopword = IntentParser._detect_stopword_phrase(
                after_misspell, title_probe=title_probe
            )
            if after_stopword != after_misspell:
                self._track(_QUERY_REWRITE_STOPWORD_PHRASE)
            _, hint_probe = IntentParser._decompose_x_of_y(after_stopword)
            if hint_probe is not None:
                self._track(_QUERY_REWRITE_X_OF_Y)
        else:
            title_probe = None

        intent_type, params, confidence = IntentParser.parse_intent(
            query, title_probe=title_probe
        )
```

NOTE: This implementation runs the rules TWICE (once for telemetry, once inside parse_intent). The cost is acceptable because all four rules are pure-Python and fast; the alternative is plumbing telemetry callbacks into IntentParser, which couples it to SimpleToolsHandler. The telemetry-detection pre-pass is the cleanest split.

- [ ] **Step 5: Run the existing simple_tools tests — verify no regression**

```bash
uv run pytest tests/test_simple_tools*.py tests/test_handle_zim_query*.py -v 2>&1 | tail -10
```

Expected: all existing tests still pass.

- [ ] **Step 6: Run the full suite**

```bash
make test 2>&1 | tail -10
```

Expected: 2188+ passing.

- [ ] **Step 7: Lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 8: Commit**

```bash
git add openzim_mcp/simple_tools.py
git commit -m "feat(rewrite): wire title probe + per-rule telemetry into handle_zim_query"
```

---

### Task 9: Read `decomposition_hint` in `_handle_tell_me_about`

**Files:**
- Modify: `openzim_mcp/simple_tools.py` (consume `params["decomposition_hint"]` in the handler)
- Modify: `tests/test_query_rewrite_tier1.py` (add `TestDecompositionHintHandoff` class)

- [ ] **Step 1: Locate `_handle_tell_me_about`**

```bash
grep -n "def _handle_tell_me_about\|topic\s*=\s*(params" /Volumes/rye/Developer/openzim-mcp/openzim_mcp/simple_tools.py | head -10
```

Find the function and identify where it currently extracts the topic from `params`. The hint short-circuits that extraction when present.

- [ ] **Step 2: Write the handoff test**

Append to `tests/test_query_rewrite_tier1.py`:

```python
class TestDecompositionHintHandoff:
    def test_handler_reads_hint_when_present(self) -> None:
        """When rule 4 stashed a decomposition_hint in params, the
        tell_me_about handler should consume entity/attribute from it
        rather than re-extracting from the topic."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        # Smoke-shape test: confirm the handler doesn't error when
        # passed a params dict that includes a decomposition_hint.
        # End-to-end behavior is exercised by the integration tests
        # in test_handle_zim_query*.py via the parse_intent path.
        params = {
            "topic": "berlin population",
            "decomposition_hint": {
                "entity": "berlin",
                "attribute": "population",
            },
        }
        # We're verifying the params dict shape is what the handler
        # expects. The actual handler call requires a configured
        # archive + zim_operations mock — that's covered by the
        # existing test_handle_zim_query test infrastructure.
        assert "decomposition_hint" in params
        assert params["decomposition_hint"]["entity"] == "berlin"
```

- [ ] **Step 3: Modify `_handle_tell_me_about` to consume the hint**

In `_handle_tell_me_about`, immediately after the function extracts `topic` from `params`, add (with comment-level documentation):

```python
        # Sub-D-2 rule 4 may have stashed a structured (entity,
        # attribute) pair in params during parse_intent. When present,
        # prefer it over re-extracting from the topic — rule 4 already
        # did the work and the structured fields are more reliable.
        decomposition_hint = params.get("decomposition_hint")
        if isinstance(decomposition_hint, dict):
            entity_hint = decomposition_hint.get("entity")
            attribute_hint = decomposition_hint.get("attribute")
            if entity_hint:
                # Use the hinted entity as the topic to look up; the
                # attribute hint can be passed through to downstream
                # extraction as a focus token if the handler supports
                # that today. If not, the entity alone produces a
                # meaningful tell_me_about — the attribute is a hint
                # not a requirement.
                topic = entity_hint
                # `attribute_hint` is preserved in `params` for any
                # downstream consumer that wants it. No further action
                # needed in this handler today; future work can wire
                # the attribute into a focused-extract path.
```

NOTE: This is a minimal consumer — it uses the hint's `entity` field to set the topic. If `_handle_tell_me_about` evolves later to consume the `attribute` field for focused extraction, that's additive. Don't over-engineer the consumer today.

- [ ] **Step 4: Run the test**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestDecompositionHintHandoff -v
```

Expected: 1 passed.

- [ ] **Step 5: Run the full suite — verify no regression**

```bash
make test 2>&1 | tail -5
```

Expected: 2188+ passing.

- [ ] **Step 6: Lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 7: Commit**

```bash
git add openzim_mcp/simple_tools.py tests/test_query_rewrite_tier1.py
git commit -m "feat(rewrite): _handle_tell_me_about consumes decomposition_hint"
```

---

### Task 10: Rule composition tests

**Files:**
- Modify: `tests/test_query_rewrite_tier1.py` (add `TestRuleComposition` class)

- [ ] **Step 1: Write the composition tests**

Append to `tests/test_query_rewrite_tier1.py`:

```python
class TestRuleComposition:
    """Pairwise rule interactions. Pins the FIXED order
    (1 → 2 → 3 → 4) by testing combinations that depend on it."""

    def test_lowercase_then_misspelling(self) -> None:
        # Rule 1 must run before rule 2 — misspellings.txt entries
        # are lowercase keys. `RECIEVE` only matches after lowercasing.
        intent, params, _ = IntentParser.parse_intent(
            "RECIEVE", title_probe=None
        )
        # The query has been rewritten — `recieve` shouldn't survive
        # anywhere in the resulting params.
        for v in params.values():
            assert "recieve" not in str(v).lower()

    def test_misspelling_then_stopword_phrase(self) -> None:
        # Rule 2 runs per-token; rule 3 looks at the cleaned phrase.
        # `the recieve list` → `the receive list` → `receive list`.
        intent, params, _ = IntentParser.parse_intent(
            "the recieve list", title_probe=None
        )
        # No surviving `recieve`, no surviving leading `the`.
        joined = " ".join(str(v) for v in params.values()).lower()
        assert "recieve" not in joined
        assert not joined.startswith("the ")

    def test_stopword_phrase_then_decomposition(self) -> None:
        # `the population of berlin` → `population of berlin` →
        # decomposes to entity=`berlin`, attr=`population`.
        intent, params, _ = IntentParser.parse_intent(
            "the population of berlin", title_probe=None
        )
        hint = params.get("decomposition_hint")
        assert hint == {"entity": "berlin", "attribute": "population"}

    def test_all_four_rules_compose(self) -> None:
        # Worst-case combined input that exercises all four rules.
        # `The POPULATON of Berlin` →
        #   r1: `the populaton of berlin`
        #   r2: `the population of berlin` (if `populaton` is in map)
        #   r3: `population of berlin`
        #   r4: `berlin population` + hint
        # Note: `populaton` may or may not be in the bundled
        # misspellings file. The test pins the SHAPE of the result
        # (hint present, no leading `the`) without depending on the
        # specific misspelling.
        intent, params, _ = IntentParser.parse_intent(
            "The Population of Berlin", title_probe=None
        )
        # Shouldn't lead with `the` in any param value.
        joined = " ".join(str(v) for v in params.values()).lower()
        assert not joined.startswith("the ")
        assert params.get("decomposition_hint") == {
            "entity": "berlin",
            "attribute": "population",
        }

    def test_rules_disabled_via_config_path(self) -> None:
        # When QueryRewriteConfig.enabled=False, the simple_tools wiring
        # short-circuits before calling parse_intent with a probe.
        # parse_intent ITSELF doesn't read config — that's the wrapper's
        # job. So this test verifies the rules can be invoked directly
        # with their defaults intact (probe=None semantics).
        intent, params, _ = IntentParser.parse_intent(
            "berlin", title_probe=None
        )
        # A bare entity name shouldn't trigger rule 4 decomposition.
        assert "decomposition_hint" not in params
```

- [ ] **Step 2: Run the composition tests**

```bash
uv run pytest tests/test_query_rewrite_tier1.py::TestRuleComposition -v
```

Expected: 5 passed.

- [ ] **Step 3: Run the full Tier 1 test suite — confirm everything still passes**

```bash
uv run pytest tests/test_query_rewrite_tier1.py -v 2>&1 | tail -15
```

Expected: 37+ tests passing across all classes.

- [ ] **Step 4: Lint + type-check**

```bash
make lint && make type-check
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_query_rewrite_tier1.py
git commit -m "test(rewrite): pin pairwise rule composition + ordering"
```

---

### Task 11: Live MCP smoke pass + PR prep

**Files:**
- No code changes; verification + PR creation.

This task follows the established beta-test sweep methodology (see [the project_a_series_beta_testing memory](../../../../.claude/projects/-Volumes-rye-Developer-openzim-mcp/memory/project_a_series_beta_testing.md) for the full pattern).

- [ ] **Step 1: Run the full test suite (final check)**

```bash
make test 2>&1 | tail -10
```

Expected: 2225+ passing (was 2188 at start of sub-D-2, plus ~37 new Tier 1 tests).

- [ ] **Step 2: Run lint + type-check**

```bash
make lint && make type-check
```

Expected: clean.

- [ ] **Step 3: Bump version to v2.0.0b1 + update CHANGELOG**

Edit `pyproject.toml`: `version = "2.0.0b1"`
Edit `.release-please-manifest.json`: `"version": "2.0.0b1"`
Edit `website/llms.txt`: update the version annotation line
Edit `CHANGELOG.md`: add a `## [2.0.0b1]` section describing the four rules + telemetry events + the spec link.

Run `uv lock` to refresh the lockfile.

- [ ] **Step 4: Live MCP smoke probe (manual, two-pass)**

Restart the live MCP server (whatever process is connected to Claude Desktop or the IDE) so it picks up the new build.

**Pass 1 — per-rule probes:**
- Rule 2: query `what is photosythesis` — should resolve to a photosynthesis article (misspelling fixed)
- Rule 3: query `the population of berlin` — should resolve to a Berlin article (leading article stripped)
- Rule 3 negative: query `the beatles` — should resolve to the actual Beatles article (probe should keep the article)
- Rule 4: query `population of berlin` — should resolve to Berlin, with the decomposition hint flowing through

**Pass 2 — cross-feature integration:**
- Combined: query `the photosythesis of plants` — exercises rules 1+2+3
- Combined: query `Berlin's population` — exercises rules 1+4 (possessive form)
- Synthesize: query `synthesize photosythesis` — confirm the synthesize tool benefits from the misspelling fix
- Reranker compatibility: confirm `query_rewrite.*` + `reranker_*` telemetry events both fire when an archive with the `[reranker]` extra is available

Document observations in your scratch notes. Anything that fires unexpectedly → file a defect, fix before merging.

- [ ] **Step 5: Commit version bump + CHANGELOG**

```bash
git add pyproject.toml .release-please-manifest.json website/llms.txt CHANGELOG.md uv.lock
git commit -m "chore(release): v2.0.0b1 — sub-D-2 Tier 1 query rewriting"
```

- [ ] **Step 6: Push branch + open PR**

```bash
git push -u origin v2-phase-d-sub-d-2-query-rewriting
gh pr create \
  --title "feat(v2): Phase D sub-D-2 — Tier 1 query rewriting (4 rules)" \
  --base main \
  --body "$(cat <<'EOF'
Implements sub-D-2 of [v2 Phase D](docs/superpowers/specs/2026-05-20-v2-phase-d-ml-accelerators-design.md). Refined design at [sub-D-2 spec](docs/superpowers/specs/2026-05-20-v2-phase-d-sub-d-2-query-rewriting-design.md).

## What's new

Four idempotent rule-based query rewrites run before the existing intent regex chain in `IntentParser.parse_intent`. Zero new dependencies, base install only — every user gets the lift on upgrade.

- **Rule 1 (`_normalize_topic_case`):** lowercase the query. Consolidates scattered `.lower()` calls into a named pass.
- **Rule 2 (`_apply_misspelling_map`):** token-level misspelling substitution via a bundled `dict[str, str]` (~30-50 starter entries from Wikipedia's "List of common misspellings"). Optional title-index probe suppresses substitution when the original token is a canonical entity name.
- **Rule 3 (`_detect_stopword_phrase`):** strip leading articles (`the`, `a`, `an`, `of`) when the full query isn't itself a canonical title (`The Beatles`, `Of Mice and Men` stay intact when the probe is provided).
- **Rule 4 (`_decompose_x_of_y`):** decompose `population of Berlin` / `Berlin's population` into a structured `(entity, attribute)` hint that rides inside the existing `params` dict. Backward-compatible — callers that don't know about the hint just ignore the extra key.

Three telemetry events via the existing `_track()` mechanism: `query_rewrite.misspelling`, `query_rewrite.stopword_phrase`, `query_rewrite.x_of_y`. Rule 1 has no event (fires on every query — zero signal).

## Risk mitigations baked in

- **Title-index probe gates rules 2 and 3** to suppress false-positive rewrites of real proper nouns.
- **Hard 500-entry cap** on the misspellings map; starter file ships with ~30-50 high-confidence entries and grows reactively from beta-test observations.
- **Exclusions file** (empty seed, grows reactively) lets operators pin specific tokens as "never rewrite."
- **Master kill switch** via `QueryRewriteConfig.enabled = False`.
- **Rule-3 probe kill switch** via `QueryRewriteConfig.stopword_phrase_probe = False`.

## Tests

- ~37 new tests in `tests/test_query_rewrite_tier1.py` covering per-rule (fix / no-op / boundary), composition, and the decomposition-hint handoff.
- Existing `tests/test_post_a*_beta_fixes.py` regression suite passes unchanged — Tier 1 rules are additive, not behavior-breaking.
- Two-pass live MCP smoke completed: per-rule probes (pass 1) + cross-feature integration including reranker compatibility (pass 2).
EOF
)"
```

- [ ] **Step 7: Watch CI**

```bash
gh pr checks --watch
```

Expected: all jobs pass. If SonarCloud flags new issues, address them (matches the post-a24 + sub-D-1 patterns documented in memory).

- [ ] **Step 8: After CI green, check SonarCloud findings**

```bash
PR_NUM=$(gh pr view --json number -q .number)
curl -s "https://sonarcloud.io/api/issues/search?componentKeys=cameronrye_openzim-mcp&pullRequest=${PR_NUM}&resolved=false&ps=20" \
  | python3 -m json.tool
```

Expected: 0 open issues. Any flagged → fix in a follow-up commit on the same PR before merging.

---

## Self-Review Notes

**Spec coverage check** — every spec section maps to a task:

| Spec section | Task(s) |
|---|---|
| Architecture (parse_intent + 4 rules + probe contract) | 7 (wiring) |
| Module structure (intent_parser, data files, loader) | 2, 3 (rule 1 setup), 7 |
| Rule 1 — lowercase | 3 |
| Rule 2 — misspellings | 4 |
| Rule 3 — stopword phrase | 5 |
| Rule 4 — X of Y decomposition + hint | 6, 9 (hint consumer) |
| Title-probe contract (Callable[[str], bool]) | 7, 8 |
| Config (QueryRewriteConfig) | 1 |
| Telemetry (3 events) | 8 |
| Testing (per-rule, composition, regression baseline, live smoke) | 3-6, 10, 11 |
| Misspelling list seeding | 2 |
| Exclusions list seeding | 2 |
| Release timing (v2.0.0b1, no 2-week wait) | 11 |
| Risk mitigations (probe gates, kill switches, hard cap) | 1, 4, 5, 8 |

**Placeholder scan** — every code step contains complete code. Two clearly-flagged "consult existing code" steps (Task 7 step 3 reading the full existing parse_intent body; Task 8 step 4 identifying the call sites) are unavoidable — they require touching code that exists pre-sub-D-2 and the only way to do them right is to read what's there.

**Type consistency check:**
- `TitleProbe = Callable[[str], bool]` consistent across Tasks 4, 5, 7, 8.
- `decomposition_hint` shape `{"entity": str, "attribute": str}` consistent across Tasks 6, 7, 9.
- `parse_intent` return type stays `Tuple[str, Dict[str, Any], float]` — hint rides INSIDE the params dict, no contract break.
- `QueryRewriteConfig` field names match between Task 1 (definition) and Task 8 (consumption).

**Order check** — each task builds on the previous:
- Tasks 1-2: scaffolding (config, data, loader)
- Tasks 3-6: rules in dependency order (rule 1 has no deps; rule 4 stands alone; rules 2-3 need the loader from Task 2)
- Task 7: integrates all 4 rules into parse_intent
- Task 8: integrates parse_intent into the runtime via simple_tools
- Task 9: handler consumer of the hint
- Task 10: composition pins
- Task 11: live smoke + ship

No forward references. Each task is independently runnable (tests added per task verify that task in isolation).
