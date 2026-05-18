# Empty-Lead Fallback + Subject-Attribute Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `zim_query` from returning a section-headings-only response when an article's lead paragraph is empty (which prompts small models to hallucinate), and route subject-attribute queries like "famous musician from big rapids michigan" to the matching section ("Notable people") instead of the entity's empty lead.

**Architecture:** Two narrow, independent changes inside `openzim_mcp/simple_tools.py`. (1) `_lead_with_toc` gains an empty-lead detector that advances the cut to the second non-wrapper H2 when the lead is too thin to be useful. (2) `_handle_tell_me_about` gains a post-resolution subject-hint check that, when the topic carried a subject word residual to the resolved entity title (`musician`/`actor`/`notable people`/etc.), fetches the matching section via the existing `get_section_data` API and returns its body instead of the (often empty) lead. Both behaviors are compact-mode-only and additive — no existing path changes when the lead is healthy and no subject hint is present.

**Tech Stack:** Python 3.11+, pytest, libzim. Edits in `openzim_mcp/simple_tools.py`. Tests in `tests/test_simple_tools.py` (extend the existing `TestLeadSectionFetchInTellMeAbout` class) and a new `tests/test_subject_attribute_resolution.py`.

**Motivating evidence:** Live-MCP transcript from 2026-05-18 — Qwen3-8B-Q4 user. Every query in the session hit the bare-topic fallback (`cert=0.70`), each resolved to a place article via tail-probing, each got rendered as section headings only because the resolved lead was empty, each prompted hallucination (Wes Anderson directing Walter Mitty, etc.). The fixes here would have turned that session from "tool emits TOC → model hallucinates" into "tool emits Notable people section → model answers correctly."

**Non-goals for this plan:**
- No change to the intent classifier itself — the bare-topic fallback path is preserved verbatim.
- No new disambiguation tactics (recommendation #3 from the review). That's a separate plan.
- No changes to the `<!-- intent=... -->` footer or `~N tokens` footer (#5 from the review).

**Verification methodology note:** This repo runs multi-pass live-MCP beta sweeps (see project memory `project-a-series-beta-testing`). After the plan lands and the unit suite passes, a live-MCP sweep against the 118 GB Wikipedia archive is expected — at minimum, replay the originating session's five queries and confirm no hallucination.

---

## File Structure

- **Modify** `openzim_mcp/simple_tools.py`
  - `_lead_with_toc` at lines 1614-1697 — empty-lead fallback (Task 1)
  - `_handle_tell_me_about` at lines 2546-2938 — subject-attribute resolution call site (Task 2 wiring)
  - New module-level constants `_SUBJECT_HINT_TO_SECTION` and `_SUBJECT_HINT_TOKENS` near the other intent-related constants (search around line 1560 — same neighborhood as `_ARTICLE_H2_RE`)
  - New private methods `_lead_density`, `_advance_cut_to_second_h2`, `_extract_subject_hint`, `_resolve_section_for_subject`, `_render_subject_section`

- **Modify** `tests/test_simple_tools.py`
  - Add three new test methods to the existing `TestLeadSectionFetchInTellMeAbout` class (line 1416) — covers Task 1.

- **Create** `tests/test_subject_attribute_resolution.py`
  - New focused test module — covers Task 2. Mirrors the fixture pattern of `TestLeadSectionFetchInTellMeAbout`.

- **Modify** `CHANGELOG.md`
  - Add a `### Improvements` section under the next-release block.

---

## Task 1: Empty-Lead Fallback in `_lead_with_toc`

**Files:**
- Modify: `openzim_mcp/simple_tools.py:1614-1697` (`_lead_with_toc`)
- Test: `tests/test_simple_tools.py` (extend `TestLeadSectionFetchInTellMeAbout` class around line 1416)

### Subtask 1.1: Lead-density helper

- [ ] **Step 1: Write the failing test**

Add this test method to `TestLeadSectionFetchInTellMeAbout` in `tests/test_simple_tools.py` immediately before `test_non_compact_returns_full_body_unchanged`:

```python
def test_empty_lead_advances_cut_to_second_h2(self, handler, mock_zim_operations):
    """When pre-H2 body is empty (after wrappers/H1 stripping), the cut
    advances to the second non-wrapper H2 so the LLM gets the first
    real section's body instead of just a list of section names.

    Motivating case: ``Big_Rapids,_Michigan`` from the 2026-05-18 live
    transcript — empty lead before "## Notable people", model
    hallucinated when given headings only.
    """
    mock_zim_operations.get_zim_entry.return_value = (
        "# Tiger\nPath: Tiger\nType: text/html\n## Content\n\n"
        "# Tiger\n\n## Other animals\n\nFirst real section content here.\n\n"
        "## Arts, entertainment, and media\n\nSecond section content."
    )
    result = handler.handle_zim_query(
        "tell me about Tiger",
        zim_file_path="/zim/test.zim",
        options={"compact": True, "max_content_length": 8000},
    )
    # First real section's body IS included.
    assert "First real section content here." in result
    # Second section's body is NOT (cut still applied, just at the
    # second H2 instead of the first).
    assert "Second section content." not in result
    # The substitution hedge fires so the LLM knows it's reading a
    # promoted section rather than a true lead.
    assert "Lead was empty" in result
    # TOC still appended.
    assert "Sections in this article" in result
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_simple_tools.py::TestLeadSectionFetchInTellMeAbout::test_empty_lead_advances_cut_to_second_h2 -v
```

Expected: FAIL — current behavior cuts at the first H2 and emits only the TOC.

- [ ] **Step 3: Implement `_lead_density` helper**

In `openzim_mcp/simple_tools.py`, add this static method immediately before `_lead_with_toc` (around line 1613):

```python
@staticmethod
def _lead_density(pre_h2: str) -> int:
    """Count substantive characters in the pre-H2 lead body.

    Strips the ZIM header block (``# Title\nPath: ...\nType: ...\n``)
    and the ``## Content`` wrapper plus the duplicated ``# Title``
    that the renderer emits before the real lead, so the count
    reflects actual lead prose. Used to detect the "empty lead"
    pattern where an article (typically a short city/biography
    article whose infobox got stripped) has no prose before its
    first real H2.
    """
    # Drop the leading metadata block — lines starting with "Path:",
    # "Type:", and the wrapper ``## Content`` heading + blank line.
    stripped = pre_h2
    # Remove any "# X\nPath: ...\nType: ...\n## Content" preamble.
    preamble_re = re.compile(
        r"\A#\s+[^\n]*\nPath:[^\n]*\nType:[^\n]*\n##\s+Content\s*\n+",
        re.MULTILINE,
    )
    stripped = preamble_re.sub("", stripped, count=1)
    # Strip any remaining bare H1 line (the renderer often duplicates
    # the title inside the wrapper).
    stripped = re.sub(r"^#\s+\S[^\n]*\n+", "", stripped, count=1)
    # Whitespace doesn't count.
    return len("".join(stripped.split()))
```

- [ ] **Step 4: Modify `_lead_with_toc` to advance the cut on empty lead**

Replace the body-cut block in `_lead_with_toc` (lines 1671-1680 in the current file) with this expanded version. Find:

```python
        h2_match = self._first_article_h2(body)
        if h2_match:
            pre_h2 = body[: h2_match.start()].rstrip()
            if self._is_disambig_lead(pre_h2):
                clean_cut = False
            else:
                body = pre_h2
                clean_cut = True
        else:
            clean_cut = False
```

Replace with:

```python
        h2_match = self._first_article_h2(body)
        empty_lead_advanced = False
        if h2_match:
            pre_h2 = body[: h2_match.start()].rstrip()
            if self._is_disambig_lead(pre_h2):
                clean_cut = False
            elif self._lead_density(pre_h2) < 80:
                # Empty-lead case: pre-H2 body is essentially just
                # wrappers and the duplicated H1. Advance the cut to
                # the SECOND non-wrapper H2 so the response includes
                # the first real section's prose. Motivating case:
                # ``Big_Rapids,_Michigan`` (2026-05-18 live transcript).
                advanced_body = self._advance_cut_to_second_h2(body)
                if advanced_body is not None:
                    body = advanced_body
                    clean_cut = True
                    empty_lead_advanced = True
                else:
                    # Only one section in the article — no second H2
                    # to advance to. Fall back to whole-body (no cut).
                    clean_cut = False
            else:
                body = pre_h2
                clean_cut = True
        else:
            clean_cut = False
```

- [ ] **Step 5: Add `_advance_cut_to_second_h2` helper**

Add this method immediately after `_first_article_h2` (around line 1580, before `_DISAMBIG_LEAD_PHRASES`):

```python
@classmethod
def _advance_cut_to_second_h2(cls, body: str) -> Optional[str]:
    """Return ``body`` cut at the SECOND non-wrapper H2 instead of the
    first, or ``None`` if the body has fewer than two such H2s.

    Used by ``_lead_with_toc``'s empty-lead fallback: when the
    pre-H2 lead is essentially empty, advancing the cut to the
    second H2 includes the first real section's prose in the
    response, giving the LLM something to ground on instead of
    just a TOC.
    """
    matches = cls._iter_article_h2(body)
    if len(matches) < 2:
        return None
    return body[: matches[1].start()].rstrip()
```

- [ ] **Step 6: Splice the substitution hedge into the assembled output**

Still in `_lead_with_toc`, find the existing hedge block (lines 1688-1693):

```python
        if clean_cut and sections:
            parts.append(
                "\n_Lead section shown. Use `show structure of "
                f"{entry_path}` for the full outline, or `summary of "
                f"{entry_path}` for a longer summary._"
            )
```

Replace with:

```python
        if clean_cut and sections:
            if empty_lead_advanced:
                # First real section was substituted for the empty
                # lead — the LLM needs to know it's reading a promoted
                # section, not the article's true introduction.
                parts.append(
                    "\n_Lead was empty; showing first section instead. "
                    f"Use `show structure of {entry_path}` for the full "
                    f"outline, or `get section <name> of {entry_path}` "
                    "to fetch a specific section._"
                )
            else:
                parts.append(
                    "\n_Lead section shown. Use `show structure of "
                    f"{entry_path}` for the full outline, or `summary of "
                    f"{entry_path}` for a longer summary._"
                )
```

- [ ] **Step 7: Run the new test to verify it passes**

```bash
uv run pytest tests/test_simple_tools.py::TestLeadSectionFetchInTellMeAbout::test_empty_lead_advances_cut_to_second_h2 -v
```

Expected: PASS.

- [ ] **Step 8: Run the existing `TestLeadSectionFetchInTellMeAbout` suite to verify no regressions**

```bash
uv run pytest tests/test_simple_tools.py::TestLeadSectionFetchInTellMeAbout -v
```

Expected: All tests in the class pass (the existing healthy-lead cases must still cut at the first H2 — `_lead_density` returns ≥80 for them).

- [ ] **Step 9: Commit**

```bash
git add openzim_mcp/simple_tools.py tests/test_simple_tools.py
git commit -m "feat(v2): empty-lead fallback in _lead_with_toc

When pre-H2 lead is empty (typical for short city/biography
articles whose infobox got stripped), advance the cut to the
second non-wrapper H2 so the response includes the first real
section's body instead of just a TOC list. Surfaces an explicit
hedge so the caller knows it's reading a promoted section."
```

### Subtask 1.2: Edge cases for `_advance_cut_to_second_h2`

- [ ] **Step 1: Write the failing test**

Add this test method to `TestLeadSectionFetchInTellMeAbout` immediately after the previous one:

```python
def test_empty_lead_with_only_one_section_skips_cut(
    self, handler, mock_zim_operations
):
    """When the article has an empty lead AND only one H2 in the
    body, there's no second H2 to advance to. Fall back to no-cut
    behavior so the single section's content is preserved.
    """
    mock_zim_operations.get_zim_entry.return_value = (
        "# Tiger\nPath: Tiger\nType: text/html\n## Content\n\n"
        "# Tiger\n\n## Only section\n\nOnly section content here."
    )
    mock_zim_operations.get_article_structure_data.return_value = {
        "headings": [
            {"level": 1, "text": "Tiger"},
            {"level": 2, "text": "Content"},
            {"level": 2, "text": "Only section"},
        ]
    }
    result = handler.handle_zim_query(
        "tell me about Tiger",
        zim_file_path="/zim/test.zim",
        options={"compact": True, "max_content_length": 8000},
    )
    # Single section's content IS preserved.
    assert "Only section content here." in result
    # No "Lead was empty" hedge because the cut didn't advance.
    assert "Lead was empty" not in result
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/test_simple_tools.py::TestLeadSectionFetchInTellMeAbout::test_empty_lead_with_only_one_section_skips_cut -v
```

Expected: PASS (the implementation already handles this — `_advance_cut_to_second_h2` returns `None`, falling through to `clean_cut = False`).

- [ ] **Step 3: Add the disambig-page protection test**

Add this test:

```python
def test_disambig_page_with_thin_pre_h2_does_not_advance(
    self, handler, mock_zim_operations
):
    """Disambiguation pages (Mercury, Martin) have thin pre-H2
    content too, but their content IS the disambig list — advancing
    the cut would render two unrelated category dumps. The existing
    ``_is_disambig_lead`` guard must fire BEFORE the empty-lead
    check.
    """
    mock_zim_operations.get_zim_entry.return_value = (
        "# Mercury\nPath: Mercury\nType: text/html\n## Content\n\n"
        "# Mercury\n\n**Mercury** may refer to:\n\n"
        "## Science\n\n- Mercury (element)\n- Mercury (planet)\n\n"
        "## Other\n\n- Mercury (mythology)"
    )
    mock_zim_operations.get_article_structure_data.return_value = {
        "headings": [
            {"level": 1, "text": "Mercury"},
            {"level": 2, "text": "Content"},
            {"level": 2, "text": "Science"},
            {"level": 2, "text": "Other"},
        ]
    }
    result = handler.handle_zim_query(
        "tell me about Mercury",
        zim_file_path="/zim/test.zim",
        options={"compact": True, "max_content_length": 8000},
    )
    # Disambig "may refer to" lead IS preserved.
    assert "may refer to" in result
    # No "Lead was empty" hedge — disambig branch fired first.
    assert "Lead was empty" not in result
    # Both H2 categories should be in the result (disambig keeps
    # the whole body, doesn't cut).
    assert "Science" in result
```

- [ ] **Step 4: Run test**

```bash
uv run pytest tests/test_simple_tools.py::TestLeadSectionFetchInTellMeAbout::test_disambig_page_with_thin_pre_h2_does_not_advance -v
```

Expected: PASS (the `elif self._is_disambig_lead(pre_h2)` branch fires first).

- [ ] **Step 5: Run full simple_tools test file as a regression check**

```bash
uv run pytest tests/test_simple_tools.py -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_simple_tools.py
git commit -m "test(v2): empty-lead fallback edge cases

Cover (a) single-section article (no second H2 to advance to,
must skip the cut), and (b) disambig page with thin pre-H2 (must
not advance — disambig guard fires first)."
```

---

## Task 2: Subject-Attribute Decomposition in `_handle_tell_me_about`

**Files:**
- Modify: `openzim_mcp/simple_tools.py:2546-2938` (`_handle_tell_me_about`) and module-level constants near line 1560
- Test: `tests/test_subject_attribute_resolution.py` (new file)

### Subtask 2.1: Subject-hint vocabulary

- [ ] **Step 1: Add the subject-hint vocabulary as a module-level constant**

In `openzim_mcp/simple_tools.py`, find the existing `_ARTICLE_H2_RE` constant around line 1559 and add this block immediately after it (before the `@classmethod` for `_iter_article_h2` at line 1561):

```python
# Subject-attribute resolution: when the resolved entity's title
# doesn't cover all of the topic's tokens, the residual tokens often
# name a subject category ("musician", "actor", "athlete", etc.).
# Map each subject hint token to a tuple of section-name candidates
# (case-insensitive substring match against H2 text). The first
# section whose name contains any candidate substring wins. Section
# names are taken from Wikipedia's place-article convention; tune as
# new gaps surface in live-MCP probes.
#
# Tuple ordering matters: more-specific candidates first ("Musicians"
# beats "Music" beats "Notable people"), so a music-specific section
# wins over the generic notable-people fallback when both exist.
_SUBJECT_HINT_TO_SECTION: "Dict[str, tuple[str, ...]]" = {
    "musician": ("Musicians", "Music", "Notable people"),
    "musicians": ("Musicians", "Music", "Notable people"),
    "music": ("Music", "Musicians", "Notable people"),
    "actor": ("Actors", "Film", "Notable people"),
    "actors": ("Actors", "Film", "Notable people"),
    "actress": ("Actors", "Film", "Notable people"),
    "athlete": ("Athletes", "Sports", "Notable people"),
    "athletes": ("Athletes", "Sports", "Notable people"),
    "sports": ("Sports", "Athletes", "Notable people"),
    "scientist": ("Scientists", "Science", "Notable people"),
    "scientists": ("Scientists", "Science", "Notable people"),
    "writer": ("Writers", "Literature", "Notable people"),
    "writers": ("Writers", "Literature", "Notable people"),
    "author": ("Authors", "Writers", "Literature", "Notable people"),
    "authors": ("Authors", "Writers", "Literature", "Notable people"),
    "politician": ("Politicians", "Politics", "Government", "Notable people"),
    "politicians": ("Politicians", "Politics", "Government", "Notable people"),
    "people": ("Notable people",),
    "person": ("Notable people",),
    "persons": ("Notable people",),
    "notable": ("Notable people",),
    "famous": ("Notable people",),
}

# Tokens that ALONE (without a co-occurring entity-name token) don't
# trigger subject-attribute resolution. ``famous`` and ``notable`` are
# weak signals by themselves — they amplify a real subject hint
# elsewhere in the residual ("famous musicians from X" → trigger on
# ``musicians``) but shouldn't fire on their own.
_WEAK_SUBJECT_HINTS: "frozenset[str]" = frozenset({"famous", "notable"})
```

- [ ] **Step 2: Verify constant imports if any are missing**

The new constant uses `Dict[str, tuple[str, ...]]` and `frozenset[str]`. Confirm `Dict` and `frozenset` resolve in this module:

```bash
grep -n "^from typing\|^import typing\|Dict\[" openzim_mcp/simple_tools.py | head -5
```

Expected: `Dict` is already imported. If `frozenset` quote-form annotations require any import, replace `"frozenset[str]"` with the form already used elsewhere in this file. (No import needed for Python 3.9+ built-in collection generics.)

- [ ] **Step 3: Commit (constants only — no behavior change yet)**

```bash
git add openzim_mcp/simple_tools.py
git commit -m "feat(v2): add subject-hint vocabulary for tell_me_about

Token-to-section-name mapping for queries like 'famous musician
from big rapids michigan' — residual subject tokens after entity
resolution will route to the matching section. No behavior change
in this commit; wiring follows."
```

### Subtask 2.2: `_extract_subject_hint` helper

- [ ] **Step 1: Write the failing test**

Create new file `tests/test_subject_attribute_resolution.py`:

```python
"""Subject-attribute decomposition for ``tell me about`` queries.

When the resolved entity's title doesn't cover all of the topic's
tokens, the residual tokens often name a subject category (the
``musician`` in ``famous musician from big rapids michigan``).
This module tests the helper that detects that pattern and the
end-to-end routing that fetches the matching section instead of
the (often empty) lead.
"""

from unittest.mock import MagicMock

import pytest

from openzim_mcp.simple_tools import SimpleToolsHandler


class TestExtractSubjectHint:
    """Unit-level coverage of ``_extract_subject_hint`` — the helper
    that pulls a subject token (``musician``, ``actor``, ...) out of
    the residual after entity resolution.
    """

    @pytest.fixture
    def handler(self):
        return SimpleToolsHandler(MagicMock())

    def test_musician_residual_extracts_musician_hint(self, handler):
        """Canonical case: ``famous musician from big rapids michigan``
        with resolved title ``Big Rapids, Michigan`` → residual
        contains ``musician`` → hint = ``musician``.
        """
        hint = handler._extract_subject_hint(
            topic="famous musician from big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint == "musician"

    def test_notable_people_residual_extracts_people_hint(self, handler):
        """``notable people from big rapids michigan`` → hint = ``people``."""
        hint = handler._extract_subject_hint(
            topic="notable people from big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        # Either ``people`` or ``notable`` wins — both map to
        # ``Notable people``. Prefer the stronger ``people`` hint.
        assert hint in {"people", "notable"}

    def test_weak_hint_alone_returns_none(self, handler):
        """``famous`` and ``notable`` are weak hints — they don't
        trigger subject-attribute resolution on their own. ``famous
        big rapids michigan`` with resolved ``Big Rapids, Michigan``
        leaves only ``famous`` in the residual, which doesn't fire.
        """
        hint = handler._extract_subject_hint(
            topic="famous big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint is None

    def test_no_residual_returns_none(self, handler):
        """When the topic is exactly the resolved title (no residual
        tokens), nothing to decompose — return None.
        """
        hint = handler._extract_subject_hint(
            topic="big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint is None

    def test_residual_without_subject_word_returns_none(self, handler):
        """Residual exists but contains no known subject hint
        (``tourism in big rapids michigan`` → ``tourism`` is not in
        the vocabulary).
        """
        hint = handler._extract_subject_hint(
            topic="tourism in big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint is None

    def test_stopwords_in_residual_ignored(self, handler):
        """Filler residual tokens (``from``, ``in``, ``the``, ``of``)
        don't count as subject hints.
        """
        hint = handler._extract_subject_hint(
            topic="actors from big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint == "actors"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_subject_attribute_resolution.py::TestExtractSubjectHint -v
```

Expected: FAIL with `AttributeError: 'SimpleToolsHandler' object has no attribute '_extract_subject_hint'`.

- [ ] **Step 3: Implement `_extract_subject_hint`**

Add this method to `SimpleToolsHandler` immediately after `_fetch_topic_article_body` (around line 2980, before `_coerce_content_offset` at line 2982):

```python
@classmethod
def _extract_subject_hint(
    cls, topic: str, resolved_title: str
) -> Optional[str]:
    """Detect a subject-category hint in the residual of ``topic``
    after the resolved entity's title tokens are removed.

    Used by the subject-attribute decomposition path: when a query
    like ``famous musician from big rapids michigan`` resolves
    (via tail-probing in ``_promote_topic_via_title_index``) to
    the entity ``Big Rapids, Michigan``, the leftover tokens
    (``famous``, ``musician``, ``from``) often name a subject
    category that maps to a section in the resolved article.

    Returns the residual subject token (lowercased) on a strong
    match, or ``None`` when the residual is empty, contains only
    weak hints (``famous`` / ``notable`` alone), or contains no
    known subject vocabulary.

    Token matching is whole-word, case-insensitive, alphanumeric-
    only (matching the tokenization in ``title_promotion``).
    """
    topic_tokens = tuple(_TAIL_TOKEN_RE.findall(topic.lower()))
    title_tokens = set(_TAIL_TOKEN_RE.findall(resolved_title.lower()))
    if not topic_tokens or not title_tokens:
        return None
    residual = [t for t in topic_tokens if t not in title_tokens]
    if not residual:
        return None
    # Strong hints win over weak hints. Scan residual for any token
    # in the subject vocabulary that ISN'T a weak hint first.
    for tok in residual:
        if tok in _SUBJECT_HINT_TO_SECTION and tok not in _WEAK_SUBJECT_HINTS:
            return tok
    # Fall back to weak hints — but only if a weak hint co-occurs
    # with a strong one. (A weak hint alone is too noisy.) Since we
    # checked for strong hints above and returned early, reaching
    # this point means no strong hint exists, so a weak hint alone
    # would fire. Suppress that — return None.
    return None
```

- [ ] **Step 4: Add the `_TAIL_TOKEN_RE` import**

In the same file, find the existing imports from `title_promotion`. If `_TAIL_TOKEN_RE` (or equivalent) isn't already imported, add it:

```bash
grep -n "from openzim_mcp.title_promotion\|_TAIL_TOKEN_RE" openzim_mcp/simple_tools.py | head -5
```

If the existing import is `from openzim_mcp.title_promotion import iter_query_tails, iter_query_windows, ...` then extend it to:

```python
from openzim_mcp.title_promotion import (
    _TAIL_TOKEN_RE,
    iter_query_tails,
    iter_query_windows,
    ...,  # leave the existing exports as-is
)
```

If `_TAIL_TOKEN_RE` is private (single leading underscore) and the linter forbids cross-module access, define a local copy in `simple_tools.py` near the other module-level constants:

```python
# Same alphanumeric-tokenization regex used by title_promotion.
# Duplicated here (not imported) because cross-module access to a
# single-leading-underscore name trips the linter; keep both copies
# in sync if either is edited.
_TOPIC_TOKEN_RE = re.compile(r"[a-z0-9]+")
```

…and use `_TOPIC_TOKEN_RE` in `_extract_subject_hint` instead.

- [ ] **Step 5: Run the unit tests to verify they pass**

```bash
uv run pytest tests/test_subject_attribute_resolution.py::TestExtractSubjectHint -v
```

Expected: PASS (all six tests).

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/simple_tools.py tests/test_subject_attribute_resolution.py
git commit -m "feat(v2): extract subject hint from tell_me_about residual

_extract_subject_hint pulls a subject-category token (musician,
actor, ...) from the residual after the resolved entity's title
tokens are removed. Strong hints win; weak hints (famous, notable)
alone don't fire. Wiring into _handle_tell_me_about follows."
```

### Subtask 2.3: `_resolve_section_for_subject` helper

- [ ] **Step 1: Write the failing test**

Append to `tests/test_subject_attribute_resolution.py`:

```python
class TestResolveSectionForSubject:
    """Unit-level coverage of ``_resolve_section_for_subject`` — the
    helper that picks the best matching H2 from an article's section
    list given a subject hint token.
    """

    @pytest.fixture
    def handler(self):
        return SimpleToolsHandler(MagicMock())

    def test_musician_matches_music_section(self, handler):
        structure = {
            "headings": [
                {"level": 1, "text": "Big Rapids, Michigan", "id": "h1"},
                {"level": 2, "text": "Content", "id": "content"},
                {"level": 2, "text": "History", "id": "history"},
                {"level": 2, "text": "Notable people", "id": "notable"},
            ]
        }
        target = handler._resolve_section_for_subject(structure, "musician")
        assert target is not None
        # Falls through to Notable people (no Music or Musicians
        # section exists in this fixture).
        assert target.get("text") == "Notable people"

    def test_musician_prefers_music_over_notable_people(self, handler):
        structure = {
            "headings": [
                {"level": 1, "text": "Detroit", "id": "h1"},
                {"level": 2, "text": "Content", "id": "content"},
                {"level": 2, "text": "Music", "id": "music"},
                {"level": 2, "text": "Notable people", "id": "notable"},
            ]
        }
        target = handler._resolve_section_for_subject(structure, "musician")
        assert target is not None
        # Music wins because it's the higher-priority candidate.
        assert target.get("text") == "Music"

    def test_no_matching_section_returns_none(self, handler):
        structure = {
            "headings": [
                {"level": 1, "text": "Big Rapids, Michigan", "id": "h1"},
                {"level": 2, "text": "Content", "id": "content"},
                {"level": 2, "text": "Geography", "id": "geo"},
                {"level": 2, "text": "Climate", "id": "climate"},
            ]
        }
        target = handler._resolve_section_for_subject(structure, "musician")
        assert target is None

    def test_unknown_subject_returns_none(self, handler):
        structure = {
            "headings": [
                {"level": 2, "text": "Notable people", "id": "notable"},
            ]
        }
        target = handler._resolve_section_for_subject(structure, "philosopher")
        assert target is None
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_subject_attribute_resolution.py::TestResolveSectionForSubject -v
```

Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement `_resolve_section_for_subject`**

Add this method to `SimpleToolsHandler` immediately after `_extract_subject_hint`:

```python
@classmethod
def _resolve_section_for_subject(
    cls, structure: Dict[str, Any], subject: str
) -> Optional[Dict[str, Any]]:
    """Find the best-matching H2 heading for a subject hint.

    ``structure`` is the dict returned by
    ``zim_operations.get_article_structure_data``. ``subject`` is
    one of the keys in ``_SUBJECT_HINT_TO_SECTION``. Returns the
    heading dict (with ``text`` / ``id`` / ``level`` keys) of the
    first matching section, or ``None`` when none of the
    candidate section names appear as substrings of any H2 in the
    article.

    Matching is case-insensitive substring against the heading
    text. Candidate priority is the tuple order from
    ``_SUBJECT_HINT_TO_SECTION``: a more-specific candidate
    (``Music``) wins over a generic fallback (``Notable people``)
    when both exist.
    """
    if subject not in _SUBJECT_HINT_TO_SECTION:
        return None
    candidates = _SUBJECT_HINT_TO_SECTION[subject]
    if not isinstance(structure, dict):
        return None
    h2s: list = []
    for h in structure.get("headings") or []:
        if not isinstance(h, dict):
            continue
        if h.get("level") != 2:
            continue
        text = (h.get("text") or "").strip()
        if not text or text == "Content":
            continue
        h2s.append(h)
    # Walk candidates in priority order; first H2 whose text
    # contains the candidate substring wins.
    for cand in candidates:
        cand_lower = cand.lower()
        for h in h2s:
            if cand_lower in (h.get("text") or "").lower():
                return h
    return None
```

- [ ] **Step 4: Run the unit tests**

```bash
uv run pytest tests/test_subject_attribute_resolution.py::TestResolveSectionForSubject -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/simple_tools.py tests/test_subject_attribute_resolution.py
git commit -m "feat(v2): resolve section by subject hint

_resolve_section_for_subject walks a subject hint's candidate
section names in priority order and returns the first H2 whose
text contains a candidate substring. Music > Notable people for
the 'musician' hint, etc."
```

### Subtask 2.4: End-to-end integration — `_render_subject_section`

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_subject_attribute_resolution.py`:

```python
class TestEndToEndSubjectAttributeRouting:
    """Integration coverage: a query like ``famous musician from big
    rapids michigan`` should fetch the ``Notable people`` (or
    ``Music``) section of the resolved place article instead of the
    empty lead.
    """

    @pytest.fixture
    def mock_zim_operations(self):
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/zim/test.zim"}]
        # Search resolves "famous musician from big rapids michigan"
        # to Big_Rapids,_Michigan via the title-promotion tail probe.
        mock.search_zim_file_data.return_value = {
            "results": [
                {
                    "path": "Big_Rapids,_Michigan",
                    "title": "Big Rapids, Michigan",
                    "snippet": "...",
                },
            ],
        }
        # find_entry_by_title_data is the title-promotion backend.
        # Stub it to make the tail-probe ``big rapids michigan``
        # resolve to the same path with score 1.0.
        def _find(path, title, **kw):
            t_lower = title.strip().lower()
            if t_lower in {
                "big rapids michigan",
                "big rapids, michigan",
                "michigan",
                "rapids michigan",
            }:
                return {
                    "results": [
                        {
                            "path": "Big_Rapids,_Michigan",
                            "title": "Big Rapids, Michigan",
                            "score": 1.0,
                        }
                    ]
                }
            return {"results": []}
        mock.find_entry_by_title_data.side_effect = _find
        # Article structure includes a Notable people section.
        mock.get_article_structure_data.return_value = {
            "headings": [
                {"level": 1, "text": "Big Rapids, Michigan", "id": "h1"},
                {"level": 2, "text": "Content", "id": "content"},
                {"level": 2, "text": "History", "id": "history"},
                {"level": 2, "text": "Notable people", "id": "notable"},
                {"level": 2, "text": "Education", "id": "education"},
            ]
        }
        # The section-data response carries the actual prose.
        mock.get_section_data.return_value = {
            "section": {"text": "Notable people", "id": "notable", "level": 2},
            "content_markdown": (
                "May Erlewine (born 1983) is an American singer-songwriter "
                "from Big Rapids."
            ),
        }
        # Fallback paths.
        mock.search_zim_file.return_value = "fallback search response"
        mock.get_zim_entry.return_value = (
            "# Big Rapids, Michigan\nPath: Big_Rapids,_Michigan\n"
            "Type: text/html\n## Content\n\n"
            "# Big Rapids, Michigan\n\n"  # empty lead — triggers Task 1 too
            "## History\n\nHistory body.\n\n"
            "## Notable people\n\nNotable people body."
        )
        return mock

    @pytest.fixture
    def handler(self, mock_zim_operations):
        return SimpleToolsHandler(mock_zim_operations)

    def test_subject_query_fetches_notable_people_section(
        self, handler, mock_zim_operations
    ):
        """End-to-end: the ``musician`` subject hint in
        ``famous musician from big rapids michigan`` routes to the
        Notable people section, NOT the empty article lead.
        """
        result = handler.handle_zim_query(
            "famous musician from big rapids michigan",
            zim_file_path="/zim/test.zim",
            options={"compact": True, "max_content_length": 8000},
        )
        # The Notable people section body IS in the response.
        assert "May Erlewine" in result
        # The substitution hedge fires so the LLM knows what it got.
        assert "Notable people" in result
        # The structure-data section was fetched directly via
        # get_section_data.
        mock_zim_operations.get_section_data.assert_called_once()
        called_args = mock_zim_operations.get_section_data.call_args
        # Args order: (zim_file_path, entry_path, section_id, ...)
        # The section_id "notable" came from the structure heading.
        assert called_args[0][2] == "notable" or called_args[1].get(
            "section_id"
        ) == "notable"
```

- [ ] **Step 2: Run integration test to verify it fails**

```bash
uv run pytest tests/test_subject_attribute_resolution.py::TestEndToEndSubjectAttributeRouting -v
```

Expected: FAIL — currently the query produces the empty-lead or default tell_me_about output, not the Notable people section.

- [ ] **Step 3: Wire subject-attribute resolution into `_handle_tell_me_about`**

In `openzim_mcp/simple_tools.py`, find the assembled-result block in `_handle_tell_me_about` (currently around line 2873-2885):

```python
        article_body = self._fetch_topic_article_body(
            zim_file_path, top_path, max_content_length, options
        )
        if article_body is None:
            # Article fetch failed — degrade gracefully to plain search.
            return self.zim_operations.search_zim_file(
                zim_file_path, topic, search_limit, 0
            )
        result = (
            f"# {top_title or topic}\n\n"
            f"_Source: `{top_path}`_\n\n"
            f"{article_body}"
        )
```

Immediately before the `article_body = self._fetch_topic_article_body(...)` call, insert this block:

```python
        # Subject-attribute decomposition (2026-05-18): when the
        # original topic carried a subject category hint
        # (``musician``, ``actor``, ``notable people``, ...) and the
        # resolved entity's article has a section that maps to that
        # hint, return the section body instead of the (often empty)
        # lead. Motivating case: ``famous musician from big rapids
        # michigan`` from the 2026-05-18 live transcript — resolved
        # entity ``Big Rapids, Michigan``, residual hint ``musician``,
        # target section ``Notable people``.
        #
        # Only fires in compact mode AND for content_offset == 0
        # (pagination mid-article doesn't have a "subject section"
        # concept). Skipped when the topic explicitly used a
        # ``tell me about <entity>`` phrasing — that's an unambiguous
        # entity request, not a subject query.
        subject_section_result = self._maybe_render_subject_section(
            zim_file_path=zim_file_path,
            topic=topic,
            top_path=top_path,
            top_title=top_title,
            params=params,
            options=options,
        )
        if subject_section_result is not None:
            return subject_section_result
```

- [ ] **Step 4: Implement `_maybe_render_subject_section`**

Add this method to `SimpleToolsHandler` immediately after `_resolve_section_for_subject`:

```python
def _maybe_render_subject_section(
    self,
    *,
    zim_file_path: str,
    topic: str,
    top_path: str,
    top_title: str,
    params: Dict[str, Any],
    options: Dict[str, Any],
) -> Optional[str]:
    """Try the subject-attribute decomposition path. Returns the
    rendered response string on a successful subject-section match,
    or ``None`` to signal "fall through to the normal lead-fetch
    path."

    Gates:
      (a) ``compact=True`` and ``content_offset == 0`` — both
          required for the section-replacement behavior to make
          sense.
      (b) The topic carries a subject hint residual that doesn't
          appear in the resolved entity's title.
      (c) The resolved article's structure has a section matching
          the subject hint.
      (d) The matched section's content fetches successfully and
          is non-empty.

    Failure at any gate returns ``None`` so the caller's existing
    lead-fetch path runs unchanged.
    """
    if not options.get("compact", False):
        return None
    if self._coerce_content_offset(options.get("content_offset")) != 0:
        return None
    # Skip when the explicit-phrasing path was used — those queries
    # ask for the entity itself, not a subject within it.
    if params.get("explicit_phrasing"):
        return None
    subject = self._extract_subject_hint(topic, top_title or top_path)
    if subject is None:
        return None
    try:
        structure = self.zim_operations.get_article_structure_data(
            zim_file_path, top_path
        )
    except Exception:
        return None
    target = self._resolve_section_for_subject(structure, subject)
    if target is None:
        return None
    section_id = target.get("id") or ""
    if not section_id:
        return None
    try:
        section_payload = self.zim_operations.get_section_data(
            zim_file_path, top_path, section_id, include_subsections=True
        )
    except Exception:
        return None
    if not isinstance(section_payload, dict):
        return None
    if section_payload.get("error"):
        return None
    body_text = section_payload.get("content_markdown") or ""
    if not isinstance(body_text, str):
        return None
    body_text = body_text.strip()
    if not body_text:
        return None
    # Honor max_content_length on the section body.
    max_len = options.get("max_content_length")
    truncated = False
    if isinstance(max_len, int) and max_len > 0 and len(body_text) > max_len:
        body_text = body_text[:max_len]
        truncated = True
    self._track("subject_attribute_section_returned")
    section_text = target.get("text") or section_id
    result = (
        f"# {top_title or topic}\n\n"
        f"_Source: `{top_path}` (section: {section_text})_\n\n"
        f"_Showing **{section_text}** section because your query "
        f"asked about ``{subject}``. Use `tell me about "
        f"{top_path}` for the full article._\n\n"
        f"{body_text}"
    )
    if truncated:
        result = result + (
            f"\n\n_Section truncated at {len(body_text):,} chars. "
            "Re-run with a larger `max_content_length` for more._"
        )
    return result
```

- [ ] **Step 5: Run the integration test**

```bash
uv run pytest tests/test_subject_attribute_resolution.py::TestEndToEndSubjectAttributeRouting -v
```

Expected: PASS.

- [ ] **Step 6: Run the full subject-attribute test module**

```bash
uv run pytest tests/test_subject_attribute_resolution.py -v
```

Expected: All tests pass (the three previous unit-test classes + this integration class).

- [ ] **Step 7: Commit**

```bash
git add openzim_mcp/simple_tools.py tests/test_subject_attribute_resolution.py
git commit -m "feat(v2): wire subject-attribute decomposition into tell_me_about

When a topic carries a subject category hint (musician, actor,
notable people, ...) that maps to a section in the resolved
article, return that section's body instead of the lead. Hedge
text tells the caller what was substituted.

Motivating case: 'famous musician from big rapids michigan' from
the 2026-05-18 live transcript — resolved entity Big Rapids,
Michigan, residual hint musician, target section Notable people."
```

### Subtask 2.5: Gate against the explicit-phrasing path

- [ ] **Step 1: Confirm the explicit-phrasing param exists**

The gate at step 3 of subtask 2.4 checks `params.get("explicit_phrasing")`. Verify this param is set by the intent classifier for explicit `tell me about X` phrasings:

```bash
grep -n "explicit_phrasing\|explicit_match" openzim_mcp/intent_parser.py openzim_mcp/simple_tools.py
```

If the param doesn't exist under that name, either:
- (a) Use the confidence as a proxy: explicit phrasing has `confidence >= 0.85`, bare-topic fallback has `confidence == 0.7`. The handler can stash confidence on `params` upstream.
- (b) Add the param at the intent parser explicit-pattern matches.

The simpler path is (a). In `simple_tools.py`, find the `parse_intent` call (around line 441) and stash confidence on params:

```python
intent, params, confidence = self.intent_parser.parse_intent(query)
if isinstance(params, dict):
    params["_intent_confidence"] = confidence
```

Then in `_maybe_render_subject_section`, replace:

```python
    if params.get("explicit_phrasing"):
        return None
```

with:

```python
    # Skip when the explicit-phrasing path was used (confidence
    # >= 0.85 from the intent parser). Bare-topic fallback hits
    # at confidence 0.7 — that's the path we want to enhance.
    if params.get("_intent_confidence", 0.0) >= 0.85:
        return None
```

- [ ] **Step 2: Write the explicit-phrasing skip test**

Append to `tests/test_subject_attribute_resolution.py`:

```python
    def test_explicit_phrasing_skips_subject_decomposition(
        self, handler, mock_zim_operations
    ):
        """An explicit ``tell me about <entity>`` phrasing (confidence
        0.85+) is an unambiguous entity request — don't decompose it,
        even if a stray subject token like ``musician`` appears in
        the phrasing. The bare-topic fallback at confidence 0.7 is
        the path subject-decomposition should fire on.

        Tests indirectly by re-running the query as 'tell me about
        famous musician from big rapids michigan' — the explicit
        ``tell me about`` verb pushes confidence to 0.85, the
        subject-attribute path is skipped, and the normal lead-fetch
        path runs.
        """
        result = handler.handle_zim_query(
            "tell me about famous musician from big rapids michigan",
            zim_file_path="/zim/test.zim",
            options={"compact": True, "max_content_length": 8000},
        )
        # The hedge from subject-decomposition is NOT present —
        # it didn't fire.
        assert "asked about" not in result
        # get_section_data was NOT called (only the normal article
        # body fetch path runs).
        mock_zim_operations.get_section_data.assert_not_called()
```

- [ ] **Step 3: Run it**

```bash
uv run pytest tests/test_subject_attribute_resolution.py::TestEndToEndSubjectAttributeRouting::test_explicit_phrasing_skips_subject_decomposition -v
```

Expected: PASS.

- [ ] **Step 4: Run full simple_tools + subject test files together**

```bash
uv run pytest tests/test_simple_tools.py tests/test_subject_attribute_resolution.py -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/simple_tools.py tests/test_subject_attribute_resolution.py
git commit -m "feat(v2): gate subject-attribute decomposition on bare-topic confidence

Only the bare-topic fallback path (confidence 0.7) routes through
subject-attribute decomposition. Explicit 'tell me about <entity>'
phrasings (confidence 0.85+) skip it — those are unambiguous
entity requests, not subject queries."
```

---

## Task 3: Regression Sweep + CHANGELOG

**Files:**
- Read-only: full test suite
- Modify: `CHANGELOG.md`

### Subtask 3.1: Full test suite

- [ ] **Step 1: Run the entire test suite**

```bash
uv run pytest -x --tb=short 2>&1 | tail -50
```

Expected: All ~1770+ tests pass. Any failure is a regression that must be diagnosed and fixed before commit. Common regression patterns to watch for:
  - Tests that asserted the section-headings-only output ARE now broken because the cut advanced — investigate whether each test's body fixture is intentionally empty-lead.
  - Tests that called `_handle_tell_me_about` indirectly with topics that incidentally contained subject hint words.

If any test fails:
1. Read the test and the assertion carefully.
2. If the test's intent was to test the OLD empty-lead behavior, update the fixture's body to actually have lead content (most likely the test was relying on the buggy behavior as a side effect).
3. If the test's intent matters as a contract, adjust the implementation gates (e.g., raise the `_lead_density` threshold from 80 to 50).
4. Do NOT just delete failing assertions.

- [ ] **Step 2: Run the linter**

```bash
uv run ruff check openzim_mcp/simple_tools.py tests/test_subject_attribute_resolution.py
```

Expected: clean. Fix any warnings.

- [ ] **Step 3: Run the type checker (if configured)**

```bash
grep -q "mypy\|pyright" pyproject.toml && uv run mypy openzim_mcp/simple_tools.py || echo "no type checker configured"
```

Expected: clean (or "no type checker configured").

### Subtask 3.2: CHANGELOG entry

- [ ] **Step 1: Read the existing CHANGELOG header**

```bash
head -40 CHANGELOG.md
```

- [ ] **Step 2: Add an Unreleased / next-alpha section**

Locate the topmost `## [` heading. If it's a released version (e.g. `## [2.0.0a16]`), add a new section ABOVE it:

```markdown
## [Unreleased]

### Improvements

- **Empty-lead fallback in lead-with-TOC**: when an article's lead
  paragraph is empty (typical for short city/biography articles
  whose infobox stripping leaves nothing before the first H2),
  ``zim_query`` now advances the cut to the second non-wrapper H2
  so the response includes the first real section's body instead
  of just a TOC. Triggered when ``_lead_density(pre_h2) < 80``;
  protected against firing on disambiguation pages.
- **Subject-attribute decomposition for ``tell me about``**: queries
  like ``famous musician from big rapids michigan`` now route to
  the matching section (``Notable people``) of the resolved
  entity's article instead of returning the (often empty) lead.
  Fires when the residual topic tokens after entity resolution
  contain a known subject hint (``musician``, ``actor``,
  ``athlete``, ``people``, …) AND the article has a section that
  maps to that hint. Gated on bare-topic-fallback confidence
  (0.7); explicit ``tell me about <entity>`` phrasings skip it.
```

- [ ] **Step 3: Commit CHANGELOG**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): empty-lead fallback + subject-attribute resolution"
```

### Subtask 3.3: Live-MCP probe (manual, deferred)

This step is not a code task — it's a verification gate that runs against the live deployed MCP server with the production-scale Wikipedia archive. Documenting it here because the methodology note in `project-a-series-beta-testing` requires it as a mandatory pass for every alpha sweep.

- [ ] **Step 1: Restart the MCP server so the new build loads**

(Per the methodology note: the in-session server caches the original alpha and does not pick up source changes.)

- [ ] **Step 2: Replay the originating session's queries against the live archive**

```text
who is a famous musician from big rapids michigan?
who are some notable people from the area?
what can you find about May Erlewine
tell me more about The Secret Life of Walter Mitty
the movie and the music may erlewine did for it
```

- [ ] **Step 3: Confirm**

  - The first two queries return the `Notable people` section of `Big_Rapids,_Michigan` (subject-attribute path fires).
  - The third query — `May Erlewine` is a personal name; explicit `tell me about` not used, but if there's a real biography article, the subject path doesn't fire (no residual subject hint) and the normal lead-fetch path runs.
  - The fourth query (`The Secret Life of Walter Mitty`) returns the disambiguation list as today (no behavior change for that path — that's the work of recommendation #3, out of scope here).
  - No `Unable to connect to server` error on the final query (recommendation #6 — verify the server stays healthy, but a code fix for that is out of scope).

- [ ] **Step 4: If any live probe surfaces a defect**

Add a new test mirroring the failing input pattern, fix the regression, repeat. This is the recurring beta-sweep pattern documented in project memory.

---

## Self-review

After completing the plan above, run this checklist:

**Spec coverage:**
- ✅ Empty-lead fallback (recommendation #1): Task 1.
- ✅ Subject-attribute decomposition (recommendation #2): Task 2.
- ✅ Verification before completion: Task 3.

**Placeholder scan:**
- All code blocks contain literal Python, not `# TODO` markers.
- All `grep` and `pytest` commands are exact.

**Type consistency:**
- `_extract_subject_hint(topic: str, resolved_title: str) -> Optional[str]` — used consistently in step 2.4 step 4.
- `_resolve_section_for_subject(structure: Dict[str, Any], subject: str) -> Optional[Dict[str, Any]]` — used consistently in step 2.4 step 4.
- `_maybe_render_subject_section(*, zim_file_path: str, topic: str, top_path: str, top_title: str, params: Dict[str, Any], options: Dict[str, Any]) -> Optional[str]` — kwargs-only signature, matches the call site in 2.4 step 3.
- `_lead_density(pre_h2: str) -> int` — used consistently in 1.1 step 4.
- `_advance_cut_to_second_h2(body: str) -> Optional[str]` — used consistently in 1.1 step 5.
