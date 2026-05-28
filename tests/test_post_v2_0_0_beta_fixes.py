r"""Regression tests for the post-v2.0.0 beta-test sweep.

The post-v2.0.0 live-MCP sweep against the 2-archive remote
(``zim.owl-atlas.ts.net`` carrying Wikipedia + SuperUser SE) surfaced
FOUR user-facing defects in the Phase F simple-mode surface. All four
share a common pattern: the v2.0.0 cut consolidated the dispatcher and
intent-parser plumbing for the 8-tool advanced surface but kept the
simple-mode dispatcher gates and entry-path extractors narrower than the
docstring contract advertises.

Defects span THREE surfaces:

* **D-A — ``search_all`` intent trips the no-zim-file gate.** The
  ``handle_zim_query`` dispatcher at ``simple_tools.py:902-912`` requires
  a resolved ``zim_file_path`` for every intent EXCEPT ``list_files``.
  ``search_all`` (parsed from ``search all files for <terms>``) is
  semantically cross-archive — ``_handle_search_all`` ignores the
  ``zim_file_path`` argument and iterates every loaded archive
  internally. When two or more archives are loaded and the caller omits
  the path (as the docstring recommends), the gate fires
  ``no_zim_file_specified`` BEFORE the handler runs, blocking the
  intended cross-archive search. Live impact on the 2-archive remote:
  ``search all files for kernel`` → ``**No ZIM File Specified**`` instead
  of the cross-archive hit list.

* **D-B — ``metadata for <file>`` doesn't extract the filename hint.**
  The intent regex matches ``metadata for X`` and routes to the
  ``metadata`` intent, but no extractor pulls the trailing filename out
  of the query. With 2+ archives loaded, ``_auto_select_zim_file()``
  returns ``None`` and the gate fires ``no_zim_file_specified`` even
  though the caller named the target file in the query body. The fix:
  add ``_extract_metadata`` that captures the filename hint into
  ``params["metadata_target"]`` and have the dispatcher resolve the hint
  to a real path before the gate fires.

* **D-C / D-D — bare intent-keyword forms drop the entry-path tail.**
  Five simple-mode intents (``structure`` / ``summary`` / ``toc`` /
  ``links`` / ``get_article``) share ``_extract_entry_path_keyworded``
  in ``intent_parser.py:181-220``. The shared extractor anchors on
  ``article|entry|page|of|for|in|from|to`` keywords; without one of
  those anchors the extractor silently returns and the handler falls to
  ``Missing Article Path``. Live impact on the 2-archive remote:

  - ``structure Photosynthesis`` → ``Missing Article Path`` (D-D)
  - ``summary Photosynthesis`` → ``Missing Article Path`` (D-D)
  - ``summarize Photosynthesis`` → ``Missing Article Path`` (D-D)
  - ``overview Photosynthesis`` → ``Missing Article Path`` (D-D)
  - ``outline Photosynthesis`` → ``Missing Article Path`` (D-D)
  - ``sections Photosynthesis`` → ``Missing Article Path`` (D-D)
  - ``toc Photosynthesis`` → ``Missing Article Path`` (D-D)
  - ``contents Photosynthesis`` → ``Missing Article Path`` (D-D)
  - ``show structure Photosynthesis`` → ``Missing Article Path`` (D-D)
  - ``table of contents Photosynthesis`` → ``Cannot find entry`` from
    the backend (D-C; the extractor anchors on ``of`` in ``table of``,
    yielding ``entry_path="contents Photosynthesis"`` — a wrong path
    that escalates past the missing-arg guard into a backend error).

  Fix: enhance ``_extract_entry_path_keyworded`` with TWO additions:
  (a) when the canonical-keyword tail starts with ``contents``, peel
  that prefix so ``table of contents X`` resolves to ``X``; (b) when no
  canonical-keyword anchor is found, fall back to a leading
  intent-keyword strip so ``structure X`` / ``summary X`` / ``toc X``
  resolve to ``X``.

* **D-E — empty-quoted titles / entry paths silently resolve to the
  ``Empty_string`` article.** Pass-2 of the sweep surfaced a separate
  defect class: when a caller types ``""`` (literal empty-quote pair)
  as an entry path or title, several extractors capture the literal
  2-char ``""`` value, the handler treats it as non-empty (``.strip()``
  removes whitespace, not quotes), the backend's title-promotion path
  resolves the empty input to ``Empty_string`` at score 1.00, and the
  user gets a silent-wrong response. Affected:

  - ``find article titled ""`` → ``Empty_string`` at score 1.00
    (find_by_title)
  - ``articles related to ""`` → links from ``Empty_string`` (related)
  - ``structure of ""`` → structure of ``Empty_string``
    (entry_path_keyworded keyword-branch tail)
  - ``links in ""`` → links from ``Empty_string``
    (entry_path_keyworded keyword-branch tail)
  - ``get article ""`` → ``Empty_string`` article body
    (entry_path_keyworded keyword-branch tail)

  Fix: add ``_strip_quote_pair`` helper that peels a single surrounding
  matched quote-pair (covering ASCII ``'`` / ``"`` plus Unicode smart
  quotes via the existing ``_QUOTE_CHARS`` set). Apply at the tail of
  ``_extract_find_by_title`` / ``_extract_related`` / the keyword-branch
  arm of ``_extract_entry_path_keyworded``. Empty result → don't set
  the param, letting the handler's missing-arg guard fire.

  Bonus regression upside: ``find article titled "World War II"`` now
  scores 1.00 instead of 0.95 (the quote-stripped lookup is an exact
  title match instead of fuzzy).

The post-v2.0.0 sweep is run from the same ``mcp__openzim-mcp__zim_query``
surface that the b-series sweeps used. v2.0.0 ships a stable Phase F
surface (22→8 tool collapse) so this is the first sweep against the
post-rc1 GA cut.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

# ===========================================================================
# D-A — search_all gate bypass
# ===========================================================================


class TestSearchAllGateBypass:
    """Cross-archive search must NOT trip the no-zim-file gate.

    ``_handle_search_all`` ignores the ``zim_file_path`` arg — it iterates
    every loaded archive via ``zim_operations.search_all_data`` (compact
    mode) or ``search_all`` (legacy mode). The dispatcher gate must mirror
    the ``list_files`` bypass for symmetry: both intents are
    archive-agnostic.
    """

    def _make_handler(self, archive_count: int) -> Any:
        """Build a SimpleToolsHandler with N stubbed archives and a
        no-op ``_handle_search_all`` sentinel so we can prove the
        dispatcher reached the handler rather than the gate.
        """
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock_ops = MagicMock()
        mock_ops.list_zim_files_data.return_value = [
            {"path": f"/data/zim_{i}.zim", "name": f"zim_{i}.zim"}
            for i in range(archive_count)
        ]
        mock_ops.list_zim_files.return_value = f"Found {archive_count} ZIM files."
        mock_ops.search_all_data.return_value = {
            "results": [],
            "_meta": {"chars": 0, "truncated": False, "tokens_est": 0},
        }
        mock_ops.search_all.return_value = "no-op search_all result"

        return SimpleToolsHandler(mock_ops)

    def test_search_all_bypasses_gate_with_two_archives(self) -> None:
        """``search all files for X`` must reach ``_handle_search_all``
        when 2+ archives are loaded and ``zim_file_path`` is omitted.
        """
        handler = self._make_handler(archive_count=2)
        result = handler.handle_zim_query(query="search all files for kernel")
        # Pre-fix: result contains "No ZIM File Specified" /
        # ``intent=no_zim_file_specified``. Post-fix: result is the
        # search_all body (or stub render) with ``intent=search_all``.
        assert "no_zim_file_specified" not in result, (
            f"search_all must bypass the no-zim-file gate; pre-fix dispatcher "
            f"returned the gate error.\n\nGot:\n{result}"
        )
        assert "**No ZIM File Specified**" not in result, (
            f"search_all must bypass the no-zim-file gate; pre-fix dispatcher "
            f"returned the gate error.\n\nGot:\n{result}"
        )

    def test_search_all_still_works_with_one_archive(self) -> None:
        """Regression guard: single-archive case still works (auto-select
        gives a path, handler runs as before)."""
        handler = self._make_handler(archive_count=1)
        result = handler.handle_zim_query(query="search all files for kernel")
        assert "no_zim_file_specified" not in result


# ===========================================================================
# D-B — metadata filename hint extraction
# ===========================================================================


class TestMetadataFilenameHintExtraction:
    """``metadata for X.zim`` must extract the filename hint into params
    so the dispatcher can resolve it against ``zim_operations`` when no
    ``zim_file_path`` is passed.
    """

    def test_metadata_for_filename_extracts_hint(self) -> None:
        """``metadata for wikipedia_en_all_maxi_2026-02.zim`` →
        ``params['metadata_target']`` carries the filename."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "metadata for wikipedia_en_all_maxi_2026-02.zim"
        )
        assert intent == "metadata"
        assert params.get("metadata_target") == "wikipedia_en_all_maxi_2026-02.zim", (
            f"Pre-fix params had no metadata_target field; got " f"params={params!r}"
        )

    def test_metadata_about_filename_extracts_hint(self) -> None:
        """``metadata about X.zim`` — same shape, different preposition."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "metadata about superuser.com_en_all_2026-02.zim"
        )
        assert intent == "metadata"
        assert params.get("metadata_target") == "superuser.com_en_all_2026-02.zim"

    def test_info_for_filename_extracts_hint(self) -> None:
        """``info for X.zim`` — alternate verb same target."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "info for wikipedia_en_all_maxi_2026-02.zim"
        )
        assert intent == "metadata"
        assert params.get("metadata_target") == "wikipedia_en_all_maxi_2026-02.zim"

    def test_bare_metadata_intent_no_hint(self) -> None:
        """``metadata`` alone — no filename to extract, the hint stays
        absent and the existing gate behaviour kicks in.
        """
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("metadata for")
        # The intent should still classify as metadata; the hint is
        # absent.
        assert intent == "metadata"
        assert not params.get("metadata_target")


class TestMetadataHintDispatcherResolution:
    """End-to-end: when ``metadata for X.zim`` is called against a
    multi-archive server with no ``zim_file_path``, the dispatcher must
    resolve the filename hint to a real archive path before the
    no-zim-file gate fires.
    """

    def _make_handler(self) -> Any:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        archives = [
            {
                "path": "/data/wikipedia_en_all_maxi_2026-02.zim",
                "name": "wikipedia_en_all_maxi_2026-02.zim",
            },
            {
                "path": "/data/superuser.com_en_all_2026-02.zim",
                "name": "superuser.com_en_all_2026-02.zim",
            },
        ]
        mock_ops = MagicMock()
        mock_ops.list_zim_files_data.return_value = archives
        mock_ops.list_zim_files.return_value = "Found 2 ZIM files."
        mock_ops.get_zim_metadata.return_value = '{"_meta": {}, "title": "wikipedia"}'
        return SimpleToolsHandler(mock_ops), mock_ops

    def test_metadata_hint_resolves_to_real_path(self) -> None:
        """``metadata for wikipedia_en_all_maxi_2026-02.zim`` with no
        ``zim_file_path`` must reach ``get_zim_metadata`` with the
        resolved path."""
        handler, mock_ops = self._make_handler()
        result = handler.handle_zim_query(
            query="metadata for wikipedia_en_all_maxi_2026-02.zim"
        )
        assert "no_zim_file_specified" not in result, (
            f"Pre-fix the gate fired; post-fix the metadata hint must "
            f"resolve to /data/wikipedia_en_all_maxi_2026-02.zim before "
            f"the gate. Got:\n{result}"
        )
        mock_ops.get_zim_metadata.assert_called_once()
        called_with_path = mock_ops.get_zim_metadata.call_args[0][0]
        assert called_with_path == "/data/wikipedia_en_all_maxi_2026-02.zim"

    def test_metadata_hint_for_second_archive(self) -> None:
        """Same shape against the second archive — proves the resolver
        picks the matching archive, not always the first."""
        handler, mock_ops = self._make_handler()
        result = handler.handle_zim_query(
            query="metadata for superuser.com_en_all_2026-02.zim"
        )
        assert "no_zim_file_specified" not in result
        mock_ops.get_zim_metadata.assert_called_once()
        called_with_path = mock_ops.get_zim_metadata.call_args[0][0]
        assert called_with_path == "/data/superuser.com_en_all_2026-02.zim"

    def test_metadata_unknown_filename_falls_to_gate(self) -> None:
        """``metadata for nonexistent.zim`` doesn't match a loaded
        archive — fall through to the existing no-zim-file gate so the
        operator sees a clear error rather than a silent wrong-archive."""
        handler, _mock_ops = self._make_handler()
        result = handler.handle_zim_query(query="metadata for nonexistent.zim")
        assert "no_zim_file_specified" in result


# ===========================================================================
# D-C / D-D — bare-verb-prefix entry-path extraction
# ===========================================================================


class TestBareVerbPrefixEntryPathExtraction:
    """The shared ``_extract_entry_path_keyworded`` must also handle
    bare-verb-prefix forms — queries where the intent keyword itself
    (``structure``/``summary``/``toc``/etc.) acts as the of/for anchor
    without an explicit ``of``/``for``.

    Pre-fix, only quoted strings or ``article``/``entry``/``page``/
    ``of``/``for``/``in``/``from``/``to`` anchors triggered extraction.
    Bare ``structure X`` queries fell through to the handler's
    ``Missing Article Path`` guard. ``table of contents X`` was worse —
    it anchored on ``of`` (from ``table of``) and produced a wrong
    entry_path ``contents X`` that escalated past the missing-arg guard
    into a backend ``Cannot find entry`` error.
    """

    # --- D-D direct bare-verb forms ---

    def test_structure_bare_form(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("structure Photosynthesis")
        assert intent == "structure"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_outline_bare_form(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("outline Photosynthesis")
        assert intent == "structure"  # 'outline' routes to structure
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_sections_bare_form(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("sections Photosynthesis")
        assert intent == "structure"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_summary_bare_form(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("summary Photosynthesis")
        assert intent == "summary"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_summarize_bare_form(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("summarize Photosynthesis")
        assert intent == "summary"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_overview_bare_form(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("overview Photosynthesis")
        assert intent == "summary"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_brief_bare_form(self) -> None:
        """``brief X`` — ``brief`` is in the summary intent regex
        ``(summary|summarize|summarise|overview|brief)``; the fallback
        prefix set must cover the same verbs."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("brief Photosynthesis")
        assert intent == "summary"
        assert params.get("entry_path") == "photosynthesis"

    def test_toc_bare_form(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("toc Photosynthesis")
        assert intent == "toc"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_contents_bare_form(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("contents Photosynthesis")
        assert intent == "toc"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_show_structure_bare_form(self) -> None:
        """``show structure X`` (preamble + verb + entity) — same
        defect class, common natural phrasing."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "show structure Photosynthesis"
        )
        assert intent == "structure"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    # --- D-C the dangerous case: anchor mis-fires on "of" in "table of" ---

    def test_table_of_contents_bare_form(self) -> None:
        """The DANGEROUS D-C case: pre-fix ``table of contents X``
        anchored on ``of`` (from ``table of``) and yielded
        ``entry_path="contents X"``. Backend then failed with
        ``Cannot find entry``. Post-fix: the ``contents `` prefix is
        peeled from the tail.
        """
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "table of contents Photosynthesis"
        )
        assert intent == "toc"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis", (
            f"Pre-fix the extractor anchored on 'of' in 'table of', leaving "
            f"entry_path='contents Photosynthesis' which the backend rejects "
            f"as Cannot find entry. Post-fix the 'contents ' prefix must be "
            f"peeled. Got entry_path={params.get('entry_path')!r}"
        )

    # --- Regression guards: existing canonical forms must still work ---

    def test_structure_of_form_unchanged(self) -> None:
        """``structure of X`` — the canonical form must still resolve
        via the ``of`` anchor as before."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("structure of Photosynthesis")
        assert intent == "structure"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_summary_of_form_unchanged(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("summary of Photosynthesis")
        assert intent == "summary"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_toc_of_form_unchanged(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("toc of Photosynthesis")
        assert intent == "toc"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_contents_of_form_unchanged(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("contents of Photosynthesis")
        assert intent == "toc"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_table_of_contents_for_form_unchanged(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "table of contents for Biology"
        )
        assert intent == "toc"
        assert params.get("entry_path") == "biology"  # Sub-D-2 Rule 1

    def test_get_article_form_unchanged(self) -> None:
        """``get article X`` — anchors on ``article`` keyword,
        unrelated to the new fallback. Pre-fix and post-fix must
        agree."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("get article Photosynthesis")
        assert intent == "get_article"
        # Sub-D-2 Rule 1 lowercases the query upstream of extraction;
        # downstream ``find_title_match`` resolves the lowercase tail to
        # the canonical title path. So the extractor-level param is
        # lowercase here.
        assert params.get("entry_path") == "photosynthesis"

    def test_quoted_form_unchanged(self) -> None:
        """Quoted entry — extractor's first branch, unchanged."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            'structure of "C/Photosynthesis"'
        )
        assert intent == "structure"
        # Quoted form preserves case (the quoted-match branch runs before
        # any lowercasing-affected logic touches the captured value).
        # But Sub-D-2 Rule 1 still lowercases the QUERY before quoted_match
        # runs, so the captured value will be lowercased too.
        assert params.get("entry_path") == "c/photosynthesis"

    def test_multi_word_entity_bare_form(self) -> None:
        """``structure United States`` — multi-token entity follows the
        bare verb. The fallback must capture the full tail."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("structure United States")
        assert intent == "structure"
        # Sub-D-2 Rule 1 lowercases.
        assert params.get("entry_path") == "united states"


# ===========================================================================
# Source-level invariant: extractor and parser must agree on the canonical
# verb set used in the leading-prefix fallback. Pin the verb set in the
# parser-side intent regex against the extractor-side fallback regex so a
# future contributor who widens one and forgets the other gets a clear
# diff signal.
# ===========================================================================


class TestEntryPathExtractorVerbSetCanonicalPin:
    """The fallback strip in ``_extract_entry_path_keyworded`` must cover
    every intent verb that routes through that extractor without an
    explicit of/for anchor. Drift between the parser's intent regex and
    the extractor's fallback strip is the post-v2.0.0 D-D bug shape."""

    def test_fallback_strip_covers_structure_intent_verbs(self) -> None:
        """Every structure-routed verb (`structure`, `outline`,
        `sections`, `headings`) must be peelable as a leading prefix."""
        from openzim_mcp.intent_parser import _LEADING_INTENT_KEYWORDS_RE

        # All five verbs must match when followed by an entity.
        verbs_with_args = [
            "structure Photosynthesis",
            "outline Photosynthesis",
            "sections Photosynthesis",
            "section Photosynthesis",  # singular
            "headings Photosynthesis",
        ]
        for q in verbs_with_args:
            match = _LEADING_INTENT_KEYWORDS_RE.match(q)
            assert match is not None, (
                f"Leading-prefix regex must match {q!r}; missing verb in "
                f"the canonical set will leave the extractor unable to "
                f"peel the prefix."
            )
            assert q[match.end() :].strip() == "Photosynthesis"

    def test_fallback_strip_covers_summary_intent_verbs(self) -> None:
        """Every summary-routed verb (`summary`, `summarize`,
        `summarise`, `overview`, `brief`) must be peelable."""
        from openzim_mcp.intent_parser import _LEADING_INTENT_KEYWORDS_RE

        verbs_with_args = [
            "summary Photosynthesis",
            "summarize Photosynthesis",
            "summarise Photosynthesis",
            "overview Photosynthesis",
            "brief Photosynthesis",
        ]
        for q in verbs_with_args:
            match = _LEADING_INTENT_KEYWORDS_RE.match(q)
            assert match is not None, f"Leading-prefix regex must match {q!r}."

    def test_fallback_strip_covers_toc_intent_verbs(self) -> None:
        """`toc`, `contents`, `table of contents` all peelable."""
        from openzim_mcp.intent_parser import _LEADING_INTENT_KEYWORDS_RE

        for q in (
            "toc Photosynthesis",
            "contents Photosynthesis",
            "table of contents Photosynthesis",
        ):
            match = _LEADING_INTENT_KEYWORDS_RE.match(q)
            assert match is not None, f"Leading-prefix regex must match {q!r}."


# ===========================================================================
# D-E — empty-quoted titles / entry paths silent-resolve to Empty_string
# ===========================================================================


class TestEmptyQuotedInputDoesNotResolveToEmptyStringArticle:
    """Pass-2 of the sweep: ``find article titled ""`` and siblings
    silently resolved to the ``Empty_string`` Wikipedia article at
    score 1.00. The extractor captured the 2-char literal ``""``, the
    handler's ``.strip()`` only trimmed whitespace, and the backend's
    title-promotion fuzzy-matched the empty input to ``Empty_string``.

    The fix peels a single surrounding matched quote-pair from the
    captured value and drops the param entirely when the result is
    empty/whitespace. Affected extractors:
    ``_extract_find_by_title`` (title), ``_extract_related``
    (entry_path), ``_extract_entry_path_keyworded`` keyword-branch
    (entry_path).
    """

    def test_find_by_title_empty_double_quotes_unset(self) -> None:
        """``find article titled ""`` must NOT carry a title param,
        so the handler's missing-arg guard fires."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent('find article titled ""')
        assert intent == "find_by_title"
        assert not params.get("title"), (
            f"Pre-fix params['title'] was the literal 2-char '\"\"' which "
            f"the backend fuzzy-matched to Empty_string. Post-fix the "
            f"quote-pair-empty title must drop entirely. "
            f"Got title={params.get('title')!r}"
        )

    def test_find_by_title_empty_single_quotes_unset(self) -> None:
        """``find article titled ''`` — same shape, single-quote pair."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("find article titled ''")
        assert intent == "find_by_title"
        assert not params.get("title")

    def test_find_by_title_quoted_whitespace_unset(self) -> None:
        """``find article titled "  "`` — non-empty between quotes but
        only whitespace. Same expected behaviour as empty quotes."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent('find article titled "  "')
        assert intent == "find_by_title"
        assert not params.get("title")

    def test_find_by_title_quoted_real_title_strips_quotes(self) -> None:
        """``find article titled "World War II"`` — quotes peeled,
        title stored cleanly. Regression upside: backend's title
        promotion scores exact-match 1.00 instead of fuzzy-quote 0.95."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            'find article titled "World War II"'
        )
        assert intent == "find_by_title"
        # Sub-D-2 Rule 1 lowercases.
        assert params.get("title") == "world war ii", (
            f"Quote-strip must remove surrounding quote pair so the "
            f"backend gets the bare title. Got "
            f"{params.get('title')!r}"
        )

    def test_find_by_title_bare_title_unchanged(self) -> None:
        """``find article titled World War II`` (no quotes) — regression
        guard, the quote-strip must only fire on a matched quote pair."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "find article titled World War II"
        )
        assert intent == "find_by_title"
        assert params.get("title") == "world war ii"

    def test_related_empty_double_quotes_unset(self) -> None:
        """``articles related to ""`` — same shape via related
        extractor."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent('articles related to ""')
        assert intent == "related"
        assert not params.get("entry_path"), (
            f"Pre-fix params['entry_path']=='\"\"' silent-matched "
            f"Empty_string in the backend. Got "
            f"{params.get('entry_path')!r}"
        )

    def test_structure_of_empty_quotes_unset(self) -> None:
        """``structure of ""`` — keyword-branch tail of
        ``_extract_entry_path_keyworded`` captured ``""`` and the
        backend resolved it to ``Empty_string``."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent('structure of ""')
        assert intent == "structure"
        assert not params.get("entry_path"), (
            f"Pre-fix the keyword-branch tail was the literal '\"\"' "
            f"which the natural-language path resolver fuzzy-matched "
            f"to Empty_string. Got {params.get('entry_path')!r}"
        )

    def test_get_article_empty_quotes_unset(self) -> None:
        """``get article ""`` — same shape, get_article intent."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent('get article ""')
        assert intent == "get_article"
        assert not params.get("entry_path")

    def test_links_in_empty_quotes_unset(self) -> None:
        """``links in ""`` — same shape, links intent."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent('links in ""')
        assert intent == "links"
        assert not params.get("entry_path")

    def test_summary_of_quoted_real_topic_strips_quotes(self) -> None:
        """``summary of "Photosynthesis"`` — regression guard: the
        keyword-branch tail must peel quotes when the value is
        non-empty. Pre-existing quoted-match branch already handled
        this; just confirm post-fix behaviour is unchanged."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent('summary of "Photosynthesis"')
        assert intent == "summary"
        assert params.get("entry_path") == "photosynthesis"

    def test_structure_of_unquoted_bare_topic_unchanged(self) -> None:
        """``structure of Photosynthesis`` — regression guard, no quote
        pair present, behaviour identical to pre-fix."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("structure of Photosynthesis")
        assert intent == "structure"
        assert params.get("entry_path") == "photosynthesis"

    def test_strip_quote_pair_helper_direct(self) -> None:
        """Direct unit test of the helper — covers ASCII single/double
        quotes plus Unicode smart quotes from the existing
        ``_QUOTE_CHARS`` set."""
        from openzim_mcp.intent_parser import _strip_quote_pair

        # Stripped:
        assert _strip_quote_pair('"hello"') == "hello"
        assert _strip_quote_pair("'hello'") == "hello"
        assert _strip_quote_pair("“hello”") == "hello"  # curly double
        assert _strip_quote_pair("‘hello’") == "hello"  # curly single

        # Empty / whitespace-only quoted:
        assert _strip_quote_pair('""') == ""
        assert _strip_quote_pair("''") == ""
        assert _strip_quote_pair('"  "') == ""

        # Unmatched: preserve verbatim
        assert _strip_quote_pair("hello") == "hello"
        assert _strip_quote_pair('"hello') == '"hello'
        assert _strip_quote_pair('hello"') == 'hello"'
        # Single character — not a quote pair, preserve
        assert _strip_quote_pair('"') == '"'
        # Mixed quote characters — STILL strip since both endpoints
        # are in the quote set (covers ``"foo'`` and similar
        # LLM-generated mismatched pairs).
        assert _strip_quote_pair("\"hello'") == "hello"
