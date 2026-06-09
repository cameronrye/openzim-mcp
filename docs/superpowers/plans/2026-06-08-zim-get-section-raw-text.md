# `zim_get_section` raw-text path (#18) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `zim_get_section`'s `compact=False` return the unrendered (full-fidelity) section body instead of the compact rendering, which is currently hardcoded.

**Architecture:** Thread a `compact: bool = True` flag down the existing call chain (tool → async wrapper → `get_section_data`/`_get_section_data` → `get_or_build_bundle` → `extract_entry_bundle`) and parameterize the single hardcoded `_render_soup_to_text(content_root, compact=True)` at `bundle.py:336`. The bundle cache key gains a mode token so the two render modes are distinct cache entries. Default `True` keeps every existing caller and the 4 non-section bundle consumers byte-identical.

**Tech Stack:** Python 3.12, pytest, libzim (mocked in tests), BeautifulSoup/html2text via `ContentProcessor`.

**Spec:** [docs/specs/2026-06-08-v2.5-zim-get-section-raw-text-design.md](../../specs/2026-06-08-v2.5-zim-get-section-raw-text-design.md)

---

## Task 1: Parameterize the bundle render mode + cache key

**Files:**

- Modify: `openzim_mcp/bundle.py` (`_bundle_cache_key` lines 66-79, `extract_entry_bundle` lines 280-353, `get_or_build_bundle` lines 356-375)
- Test: `tests/test_bundle.py`

- [ ] **Step 1: Add a table fixture and the failing test**

Add this module-level fixture near `SAMPLE_HTML` in `tests/test_bundle.py` (the 10-row table exceeds the `table_row_threshold=8`, so compact rendering replaces it):

```python
TABLE_HTML = """\
<html><body>
<h1>Data</h1>
<p>Intro paragraph.</p>
<h2>Stats</h2>
<table>
<tr><th>Year</th><th>Label</th></tr>
<tr><td>2001</td><td>alpha</td></tr>
<tr><td>2002</td><td>beta</td></tr>
<tr><td>2003</td><td>gamma</td></tr>
<tr><td>2004</td><td>delta</td></tr>
<tr><td>2005</td><td>epsilon</td></tr>
<tr><td>2006</td><td>zeta</td></tr>
<tr><td>2007</td><td>eta</td></tr>
<tr><td>2008</td><td>theta</td></tr>
<tr><td>2009</td><td>iota</td></tr>
<tr><td>2010</td><td>kappa</td></tr>
</table>
</body></html>
"""


def test_bundle_compact_false_keeps_full_table(cp: ContentProcessor) -> None:
    archive = _make_archive_with_entry(TABLE_HTML, title="Data", entry_path="A/Data")
    raw = extract_entry_bundle(archive, "A/Data", content_processor=cp, compact=False)
    compact = extract_entry_bundle(archive, "A/Data", content_processor=cp, compact=True)
    # compact=False keeps the real table cells; compact=True replaces with a placeholder
    assert "alpha" in raw["rendered_markdown"]
    assert "[Table" not in raw["rendered_markdown"]
    assert "[Table" in compact["rendered_markdown"]
    assert "alpha" not in compact["rendered_markdown"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_bundle.py::test_bundle_compact_false_keeps_full_table -v --no-cov`
Expected: FAIL — `TypeError: extract_entry_bundle() got an unexpected keyword argument 'compact'`.

- [ ] **Step 3: Parameterize `_bundle_cache_key`**

Replace `_bundle_cache_key` (lines 66-79) with:

```python
def _bundle_cache_key(validated_path: "Path", entry_path: str, compact: bool) -> str:
    """Cache key that invalidates when the underlying ZIM is replaced.

    Includes `st_mtime_ns` so an atomic file replacement (a monthly
    Wikipedia ZIM update) causes prior bundles to be reseen as cache
    misses rather than served as stale. `st_size` is included too —
    cheap defence-in-depth against filesystems with low-precision mtime
    or in-place rewrites that preserve the timestamp.

    The `compact` render mode is part of the key: a compact bundle
    (table placeholders) and a raw bundle (full tables) for the same
    entry are distinct entries and must never collide.

    Falls back gracefully when stat() fails (path no longer exists, race
    with replacement): the key drops to the prior shape so the cache
    still works, just without the invalidation guarantee.
    """
    mode = "compact" if compact else "raw"
    return (
        f"{_BUNDLE_KEY_PREFIX}:{validated_path}:"
        f"{archive_stat_token(validated_path)}:{entry_path}:{mode}"
    )
```

- [ ] **Step 4: Parameterize `extract_entry_bundle`**

Change the signature (line 280-285) to add a keyword-only `compact`:

```python
def extract_entry_bundle(
    archive: "Archive",
    entry_path: str,
    *,
    content_processor: "ContentProcessor",
    compact: bool = True,
) -> EntryBundle:
```

Replace the hardcoded render (line 336) and its comment with:

```python
    # Render in the requested mode. ``compact=True`` (the default, used by
    # summary/TOC/structure/synthesize) carries the same table-stripping
    # placeholders that direct ``get_zim_entry`` callers see, so a section
    # slice matches the article-fetch path. ``compact=False`` (the #18
    # raw-text path) keeps full pipe-delimited tables. The infobox is
    # already ``decompose()``d above in both modes.
    rendered = content_processor._render_soup_to_text(content_root, compact=compact)
```

- [ ] **Step 5: Parameterize `get_or_build_bundle`**

Change the signature (lines 356-363) and key/build calls:

```python
def get_or_build_bundle(
    archive: Archive,
    entry_path: str,
    *,
    cache: OpenZimMcpCache,
    validated_path: Path,
    content_processor: ContentProcessor,
    compact: bool = True,
) -> EntryBundle:
    """Cache-aware bundle accessor. Builds on miss; returns cached on hit."""
    key = _bundle_cache_key(validated_path, entry_path, compact)
    cached = cache.get(key)
    if cached is not None:
        logger.debug("Bundle cache hit: %s (compact=%s)", entry_path, compact)
        return cast("EntryBundle", cached)
    logger.debug("Bundle cache miss: %s (compact=%s) — building", entry_path, compact)
    bundle = extract_entry_bundle(
        archive, entry_path, content_processor=content_processor, compact=compact
    )
    cache.set(key, bundle)
    return bundle
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_bundle.py::test_bundle_compact_false_keeps_full_table -v --no-cov`
Expected: PASS.

- [ ] **Step 7: Add a cache-key isolation unit test**

Add to `tests/test_bundle.py`:

```python
def test_bundle_cache_key_distinguishes_compact_mode(tmp_path) -> None:
    from openzim_mcp.bundle import _bundle_cache_key

    p = tmp_path / "x.zim"
    p.touch()
    assert _bundle_cache_key(p, "A/Data", True) != _bundle_cache_key(p, "A/Data", False)
```

Run: `uv run pytest tests/test_bundle.py -k "compact_false or compact_mode" -v --no-cov`
Expected: PASS (both).

- [ ] **Step 8: Run the full bundle test file (no regressions)**

Run: `uv run pytest tests/test_bundle.py -v --no-cov`
Expected: PASS (all existing tests still green — default `compact=True` preserves behaviour).

- [ ] **Step 9: Commit**

```bash
git add openzim_mcp/bundle.py tests/test_bundle.py
git commit -m "feat(bundle): parameterize render mode (compact) with mode-keyed cache"
```

---

## Task 2: Thread `compact` through the data layer

**Files:**

- Modify: `openzim_mcp/zim/structure.py` (`get_section_data` lines 534-573, `_get_section_data` lines 575-597)
- Test: `tests/test_get_section.py`

- [ ] **Step 1: Write the failing test**

Extend the import at `tests/test_get_section.py:20` to add `TABLE_HTML`:

```python
from tests.test_bundle import SAMPLE_HTML, TABLE_HTML, _make_archive_with_entry
```

Add this test (it also covers cache isolation — compact then raw on the same `ops`/cache must return different bodies):

```python
def test_get_section_compact_mode_controls_table_rendering(ops, tmp_path) -> None:
    archive = _make_archive_with_entry(TABLE_HTML, title="Data", entry_path="A/Data")
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        compact = ops.get_section_data(
            zim_path, "A/Data", section_id="stats", compact=True
        )
        raw = ops.get_section_data(
            zim_path, "A/Data", section_id="stats", compact=False
        )
    assert "[Table" in compact["content_markdown"]
    assert "alpha" not in compact["content_markdown"]
    assert "alpha" in raw["content_markdown"]
    assert "[Table" not in raw["content_markdown"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_get_section.py::test_get_section_compact_mode_controls_table_rendering -v --no-cov`
Expected: FAIL — `TypeError: get_section_data() got an unexpected keyword argument 'compact'`.

- [ ] **Step 3: Add `compact` to `get_section_data`**

In `openzim_mcp/zim/structure.py`, change the public `get_section_data` signature (lines 534-542) to add a keyword-only `compact`:

```python
    def get_section_data(
        self,
        zim_file_path: str,
        entry_path: str,
        section_id: str,
        *,
        max_chars: "Optional[int]" = None,
        include_subsections: bool = True,
        compact: bool = True,
    ) -> "Union[GetSectionResponse, ToolErrorPayload]":
```

and forward it in the `_get_section_data` call (lines 562-569):

```python
                return self._get_section_data(
                    archive,
                    validated_path,
                    entry_path,
                    section_id,
                    max_chars,
                    include_subsections=include_subsections,
                    compact=compact,
                )
```

- [ ] **Step 4: Add `compact` to `_get_section_data` and forward to the bundle**

Change the `_get_section_data` signature (lines 575-584) to add keyword-only `compact`:

```python
    def _get_section_data(
        self,
        archive: Archive,
        validated_path: Path,
        entry_path: str,
        section_id: str,
        max_chars: "Optional[int]",
        *,
        include_subsections: bool = True,
        compact: bool = True,
    ) -> "Union[GetSectionResponse, ToolErrorPayload]":
```

and pass `compact` to the bundle call (lines 591-597):

```python
        bundle = get_or_build_bundle(
            archive,
            entry_path,
            cache=self.cache,
            validated_path=validated_path,
            content_processor=self.content_processor,
            compact=compact,
        )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_get_section.py::test_get_section_compact_mode_controls_table_rendering -v --no-cov`
Expected: PASS.

- [ ] **Step 6: Run the full data-layer test file (no regressions)**

Run: `uv run pytest tests/test_get_section.py tests/test_get_section_d5_widen_v2a9.py -v --no-cov`
Expected: PASS (all existing tests green).

- [ ] **Step 7: Commit**

```bash
git add openzim_mcp/zim/structure.py tests/test_get_section.py
git commit -m "feat(structure): forward compact through get_section_data to the bundle"
```

---

## Task 3: Thread `compact` through the async wrapper and tool surface

**Files:**

- Modify: `openzim_mcp/async_operations.py` (`get_section_data` lines 711-728)
- Modify: `openzim_mcp/tools/zim_get_section.py` (call at lines 60-65; module docstring lines 1-18; inline comment lines 54-59)
- Test: `tests/test_zim_get_section.py`

- [ ] **Step 1: Update the dispatch test and add a compact=False forwarding test**

In `tests/test_zim_get_section.py`, change the assertion in `test_dispatches_to_get_section_data` (lines 63-65) to include `compact=True`:

```python
    ops.get_section_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", "History", max_chars=None, compact=True
    )
```

Add a new test:

```python
@pytest.mark.asyncio
async def test_forwards_compact_false(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_section_data={"section": "..."})
    register_zim_get_section(server)
    fn, _ = server._tools_store["zim_get_section"]
    await fn(
        zim_file_path="/x.zim",
        entry_path="A/Cat",
        section_id="History",
        compact=False,
    )
    ops.get_section_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", "History", max_chars=None, compact=False
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_zim_get_section.py -k "dispatches or compact_false" -v --no-cov`
Expected: FAIL — the mock was awaited without `compact` (assertion mismatch).

- [ ] **Step 3: Add `compact` to the async wrapper**

In `openzim_mcp/async_operations.py`, change `get_section_data` (lines 711-728):

```python
    async def get_section_data(
        self,
        zim_file_path: str,
        entry_path: str,
        section_id: str,
        max_chars: Optional[int] = None,
        *,
        include_subsections: bool = True,
        compact: bool = True,
    ) -> "Union[GetSectionResponse, ToolErrorPayload]":
        """Structured variant of ``get_section`` (async)."""
        return await asyncio.to_thread(
            self._ops.get_section_data,
            zim_file_path,
            entry_path,
            section_id,
            max_chars=max_chars,
            include_subsections=include_subsections,
            compact=compact,
        )
```

- [ ] **Step 4: Forward `compact` from the tool and refresh the docs**

In `openzim_mcp/tools/zim_get_section.py`, change the `ops.get_section_data` call (lines 60-65):

```python
            return await ops.get_section_data(
                zim_file_path,
                entry_path,
                section_id,
                max_chars=max_chars,
                compact=compact,
            )
```

Replace the inline comment (lines 54-59) with:

```python
            # `compact` selects render fidelity: True (default) ships the
            # bundle's compact rendering (oversized tables collapsed to
            # `[Table N: ...]` placeholders), matching get_zim_entry;
            # False returns the unrendered section body with full tables
            # (v2.5 #18). `compact_budget` is still a surface-only no-op.
```

Replace the module docstring (lines 1-18) with:

```python
"""zim_get_section — fetch one named section of an article.

Phase F renames Phase C's ``get_section`` to ``zim_get_section`` and
adds ``compact`` / ``compact_budget`` parameters for surface uniformity
with the rest of the family (``zim_query`` / ``zim_get``).

``compact`` is wired at the data layer (v2.5 #18): ``compact=True``
(default) ships the bundle's compact rendering — oversized tables
collapsed to ``[Table N: ...]`` placeholders, matching the
``get_zim_entry`` slice shape — while ``compact=False`` returns the
unrendered section body with full pipe-delimited tables. The lead
section's infobox is not inlined in either mode (the bundle decomposes
it for all consumers); callers wanting the infobox-bearing lead should
use ``zim_get(view="full", compact=False)``. ``compact_budget`` remains
a surface-only no-op.

The data layer (``zim_operations.get_section_data``) and response
shape (``GetSectionResponse``) are unchanged from Phase C.
"""
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_zim_get_section.py -v --no-cov`
Expected: PASS (all 4 tests).

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/async_operations.py openzim_mcp/tools/zim_get_section.py tests/test_zim_get_section.py
git commit -m "feat(zim_get_section): wire compact=False to the raw-text path (#18)"
```

---

## Task 4: Fidelity verification on infobox-bearing content + spec note

This pins the rendering-fidelity contract from the spec: `compact=False` expands tables on real-shaped content (infobox + table), and records the settled decision that the infobox divergence is accepted (the bundle decomposes the infobox for all consumers; we do not change shared bundle behaviour).

**Files:**

- Test: `tests/test_get_section.py`
- Modify: `docs/specs/2026-06-08-v2.5-zim-get-section-raw-text-design.md` (fidelity section)

- [ ] **Step 1: Add the infobox+table fixture and parity test**

Add to `tests/test_bundle.py` (module level), an article with an infobox-style table in the lead and an oversized data table in a body section:

```python
INFOBOX_TABLE_HTML = """\
<html><body>
<h1>Country</h1>
<table class="infobox"><tr><th>Capital</th><td>Metropolis</td></tr></table>
<p>Country is a sovereign state.</p>
<h2>Demographics</h2>
<table>
<tr><th>Year</th><th>Population</th></tr>
<tr><td>2001</td><td>alpha</td></tr>
<tr><td>2002</td><td>beta</td></tr>
<tr><td>2003</td><td>gamma</td></tr>
<tr><td>2004</td><td>delta</td></tr>
<tr><td>2005</td><td>epsilon</td></tr>
<tr><td>2006</td><td>zeta</td></tr>
<tr><td>2007</td><td>eta</td></tr>
<tr><td>2008</td><td>theta</td></tr>
<tr><td>2009</td><td>iota</td></tr>
<tr><td>2010</td><td>kappa</td></tr>
</table>
</body></html>
"""
```

Add to `tests/test_get_section.py` (import `INFOBOX_TABLE_HTML` alongside `TABLE_HTML`):

```python
def test_get_section_compact_false_expands_body_table_with_infobox_present(
    ops, tmp_path
) -> None:
    archive = _make_archive_with_entry(
        INFOBOX_TABLE_HTML, title="Country", entry_path="A/Country"
    )
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        raw = ops.get_section_data(
            zim_path, "A/Country", section_id="demographics", compact=False
        )
    # The body section's oversized table is expanded in raw mode.
    assert "alpha" in raw["content_markdown"]
    assert "[Table" not in raw["content_markdown"]
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run pytest tests/test_get_section.py::test_get_section_compact_false_expands_body_table_with_infobox_present -v --no-cov`
Expected: PASS.

- [ ] **Step 3: Record the fidelity decision in the spec**

In `docs/specs/2026-06-08-v2.5-zim-get-section-raw-text-design.md`, under "Rendering-fidelity contract", replace the paragraph beginning "One known asymmetry to verify and reconcile during implementation:" with the settled decision:

```markdown
**Settled:** the infobox asymmetry is accepted, not reconciled. `extract_entry_bundle` `decompose()`s the infobox before rendering in *both* modes ([bundle.py:328](../../openzim_mcp/bundle.py)) because the infobox field is load-bearing for the summary/structure/synthesize consumers — so a `compact=False` section does not inline the lead infobox, whereas `zim_get(view="full", compact=False)` does. Infoboxes appear only in the lead section; callers wanting the infobox-bearing lead use `zim_get(view="full", compact=False)`. The primary `compact=False` contract — full tables instead of `[Table N: …]` placeholders — holds identically across both paths. We do not change shared bundle behaviour to chase lead-section infobox parity.
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_bundle.py tests/test_get_section.py docs/specs/2026-06-08-v2.5-zim-get-section-raw-text-design.md
git commit -m "test(zim_get_section): pin raw-text fidelity; record infobox decision"
```

---

## Task 5: Full verification

- [ ] **Step 1: Run the focused suite**

Run: `uv run pytest tests/test_bundle.py tests/test_get_section.py tests/test_get_section_d5_widen_v2a9.py tests/test_zim_get_section.py -v --no-cov`
Expected: PASS (all).

- [ ] **Step 2: Run lint + types**

Run: `uv run flake8 openzim_mcp/bundle.py openzim_mcp/zim/structure.py openzim_mcp/async_operations.py openzim_mcp/tools/zim_get_section.py && uv run mypy openzim_mcp/bundle.py openzim_mcp/zim/structure.py openzim_mcp/async_operations.py openzim_mcp/tools/zim_get_section.py`
Expected: clean (no errors).

- [ ] **Step 3: Run the full test suite (no regressions)**

Run: `uv run pytest -q --no-cov`
Expected: all pass (~2949+ passed, the new tests added), 0 failed.

- [ ] **Step 4: Confirm the prototype-parity guard did NOT fire**

Run: `uv run pytest tests/test_phase_f_prototype_parity.py -v --no-cov`
Expected: PASS — no `*_description.md` changed, so the D14b byte/Levenshtein guards are untouched.
