r"""Regression tests for the sweep-4 query-parsing defect family.

Five defects, all reachable from the public ``zim_query`` tool:

* **Q1 — quadratic politeness strip on the raw query.**
  ``_TRAILING_POLITENESS_RE`` led with ``(?:^|\s+|...)``, a greedy
  repeat whose tail is a failing alternation, so it backtracks
  O(n^2) over a whitespace run. ``parse_intent`` collapses runs
  before stripping, but ``_normalize_and_validate_query_params``
  strips the RAW handler argument, bypassing the mitigation:
  ``search for<4000 spaces>berlin`` (under the 4096 front-door cap)
  burned 2.1s of GIL-held CPU and returned an error envelope
  instead of Berlin results.

* **Q2 — the politeness strip eats the only operand.**
  The alternation carries ordinary words (``tack``, ``cheers``,
  ``merci``), and nothing stopped the strip from consuming the
  query's last topic-bearing token: ``tell me about tack`` parsed
  with ``topic=''`` and ``what is a tack`` collapsed to the
  determiner ``a`` — a confident lookup of an unrelated article.

* **Q3 — batch entry-path extractor truncates on ``(`` / ``@``.**
  ``_extract_get_zim_entries`` allowed only ``[\w\-./%]`` after the
  namespace letter, so ``A/Mercury_(planet)`` became ``A/Mercury_``
  while the sibling single-entry extractor handled the same token
  correctly.

* **Q4 — ``search_all`` extractor narrower than its intent regex.**
  The intent pattern makes the target noun optional, so it fires on
  ``search across all files for X``; the extractor's prefix sub
  demands ``files``/``zims``/``for`` in the very next slot, so the
  sub silently no-ops and the whole command sentence is searched.

* **Q5 — ``query_rewrite`` data-path overrides never reach the
  loader.** ``misspelling_map_path`` / ``misspelling_exclusion_path``
  were accepted by pydantic and read by nobody; the bundled data
  files were used regardless, with no warning.
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.intent_parser import (
    IntentParser,
    _extract_entry_path_keyworded,
    _extract_get_zim_entries,
    _extract_search_all,
)
from openzim_mcp.simple_tools import SimpleToolsHandler


def _handler(tmp_path: Path, **config_kwargs: Any) -> Tuple[Any, MagicMock]:
    """Build a handler over a mock backend carrying a REAL config."""
    mock = MagicMock()
    mock.config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], **config_kwargs)
    mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
    return SimpleToolsHandler(mock), mock


# ===========================================================================
# Q1 — whitespace-run blowup in the trailing-politeness strip
# ===========================================================================


class TestQ1PolitenessStripLinearOnWhitespaceRuns:
    """The leading atom must be fixed-width so a long whitespace run
    cannot backtrack. ``safe_regex_sub`` cannot bound the cost itself:
    CPython's ``re`` holds the GIL for the whole match."""

    def test_strip_is_linear_over_a_long_whitespace_run(self) -> None:
        query = "search for" + " " * 4000 + "berlin"
        start = time.perf_counter()
        out = IntentParser._strip_trailing_politeness(query)
        elapsed = time.perf_counter() - start
        # Nothing to strip — the query ends in a topic word.
        assert out == query
        assert elapsed < 0.5, f"politeness strip took {elapsed:.3f}s"

    def test_whitespace_run_query_returns_results_not_an_error(
        self, tmp_path: Path
    ) -> None:
        """End to end: 4016 chars is under the 4096 front-door cap, so
        the handler must dispatch the search rather than blow its regex
        budget and emit ``**Error Processing Query**``."""
        handler, mock = _handler(tmp_path)
        query = "search for" + " " * 4000 + "berlin"
        start = time.perf_counter()
        out = handler.handle_zim_query(query, zim_file_path="/x.zim")
        elapsed = time.perf_counter() - start
        assert "Error Processing Query" not in str(out)
        assert mock.search_zim_file.call_args is not None
        assert mock.search_zim_file.call_args[0][1] == "berlin"
        assert elapsed < 1.0, f"handle_zim_query took {elapsed:.3f}s"

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("search for biology please", "search for biology"),
            ("search for biology, ta", "search for biology"),
            ("search for biology please, ta", "search for biology"),
            ("search for biology  cheers", "search for biology"),
            ("biology,  ta", "biology"),
            ("cantata", "cantata"),
            ("thanks giving", "thanks giving"),
        ],
    )
    def test_fixed_width_leading_atom_preserves_behavior(
        self, raw: str, expected: str
    ) -> None:
        assert IntentParser._strip_trailing_politeness(raw) == expected


# ===========================================================================
# Q2 — the strip must not consume the query's only operand
# ===========================================================================


class TestQ2PolitenessStripKeepsSoleTopic:
    """``tack`` / ``cheers`` / ``merci`` are real article topics as well
    as politeness tokens. Peeling one is right when other operands
    survive (``biology tack`` -> ``biology``), wrong when it leaves the
    intent with nothing but its own verb phrase."""

    @pytest.mark.parametrize(
        "query, expected_topic",
        [
            ("tell me about tack", "tack"),
            ("tell me about cheers", "cheers"),
            ("describe cheers", "cheers"),
            ("what is a tack", "a tack"),
            ("tell me about the tack", "the tack"),
            ("tell me about merci", "merci"),
        ],
    )
    def test_sole_topic_survives_parse(self, query: str, expected_topic: str) -> None:
        intent, params, _conf = IntentParser.parse_intent(
            query, query_rewrite_enabled=False
        )
        assert intent == "tell_me_about"
        assert params.get("topic") == expected_topic

    def test_handler_does_not_reject_a_politeness_word_topic(
        self, tmp_path: Path
    ) -> None:
        handler, _mock = _handler(tmp_path)
        out = str(handler.handle_zim_query("tell me about tack", "/x.zim"))
        assert "Topic Required" not in out

    @pytest.mark.parametrize(
        "query", ["what is a tack", "tell me about a tack", "tell me about the tack"]
    )
    def test_stopword_residue_never_becomes_the_topic(self, query: str) -> None:
        """The severe shape: the strip left a bare determiner as the
        topic, which resolved to a confident, unrelated article."""
        _intent, params, _conf = IntentParser.parse_intent(
            query, query_rewrite_enabled=False
        )
        assert params.get("topic") not in ("", "a", "an", "the")

    @pytest.mark.parametrize(
        "query, expected_query",
        [
            # Other operands survive the strip — peeling stays correct.
            ("search for biology tack", "biology"),
            ("search for biology cheers", "biology"),
            ("search for biology please", "biology"),
        ],
    )
    def test_trailing_politeness_still_peeled_when_operands_remain(
        self, query: str, expected_query: str
    ) -> None:
        _intent, params, _conf = IntentParser.parse_intent(
            query, query_rewrite_enabled=False
        )
        assert params.get("query") == expected_query

    def test_unambiguous_politeness_still_empties_the_topic(
        self, tmp_path: Path
    ) -> None:
        """``please`` is never a topic, so ``tell me about please``
        must keep firing the A11-B2 guard."""
        handler, _mock = _handler(tmp_path)
        out = str(handler.handle_zim_query("tell me about please", "/x.zim"))
        assert "Topic Required" in out

    @pytest.mark.parametrize(
        "query",
        ["search for cheers", "search for ta", "search for pls"],
    )
    def test_search_terms_required_guard_unchanged(
        self, tmp_path: Path, query: str
    ) -> None:
        """The A11-B4 guard reads the raw query through the unguarded
        strip; post-a21 P1-D8 pins this and must not regress."""
        handler, _mock = _handler(tmp_path)
        out = str(handler.handle_zim_query(query, "/x.zim"))
        assert "Search Terms Required" in out


# ===========================================================================
# Q3 — batch entry-path extractor character class
# ===========================================================================


class TestQ3BatchEntryPathPunctuation:
    """The batch extractor must tolerate the same path shapes the
    single-entry sibling already does."""

    @pytest.mark.parametrize(
        "query, expected",
        [
            (
                "get entries A/Mercury_(planet) and A/Venus",
                ["A/Mercury_(planet)", "A/Venus"],
            ),
            (
                "get entries M/Illustration_48x48@1 and A/Berlin",
                ["M/Illustration_48x48@1", "A/Berlin"],
            ),
            ("fetch multiple A/C++ and A/Foo", ["A/C++", "A/Foo"]),
            (
                "get entries A/Murphy's_law and A/Sod's_law",
                ["A/Murphy's_law", "A/Sod's_law"],
            ),
        ],
    )
    def test_punctuated_paths_survive(self, query: str, expected: List[str]) -> None:
        params: Dict[str, Any] = {}
        _extract_get_zim_entries(query, params)
        assert params.get("entries") == expected

    @pytest.mark.parametrize(
        "path",
        ["A/Mercury_(planet)", "M/Illustration_48x48@1", "A/Berlin_(disambiguation)"],
    )
    def test_batch_and_single_extractors_agree(self, path: str) -> None:
        batch: Dict[str, Any] = {}
        _extract_get_zim_entries(f"get entries {path} and A/Venus", batch)
        single: Dict[str, Any] = {}
        _extract_entry_path_keyworded(f"get article {path}", single)
        assert batch.get("entries", [None])[0] == single.get("entry_path") == path

    @pytest.mark.parametrize(
        "query, expected",
        [
            # An unbalanced closer belongs to the prose, not the path.
            ("get entries (see A/Foo) and A/Bar", ["A/Foo", "A/Bar"]),
            # Sentence punctuation still peels.
            ("get entries A/Bar. and A/Baz", ["A/Bar", "A/Baz"]),
            # M7: the namespace letter must stand alone.
            ("get entries A/Foo and/or B/Bar", ["A/Foo", "B/Bar"]),
        ],
    )
    def test_existing_trimming_preserved(self, query: str, expected: List[str]) -> None:
        params: Dict[str, Any] = {}
        _extract_get_zim_entries(query, params)
        assert params.get("entries") == expected


# ===========================================================================
# Q4 — search_all extractor / intent-pattern lockstep
# ===========================================================================


_SEARCH_ALL_VARIANTS = [
    "search all files for photosynthesis",
    "search all zims for photosynthesis",
    "search across files for photosynthesis",
    "search every file for photosynthesis",
    "search everything for photosynthesis",
    "search everywhere for photosynthesis",
    "search across all files for photosynthesis",
    "search all the files for photosynthesis",
    "search all of the files for photosynthesis",
    "search all my files for photosynthesis",
    "search all loaded zims for photosynthesis",
    "search all archives for photosynthesis",
    "search across archives for photosynthesis",
    "search all files photosynthesis",
    "search everywhere photosynthesis",
    # "zim" qualifying a head noun: the cue noun alternation matched the
    # qualifier and stopped, leaving the head noun in the search terms.
    "search all zim files for photosynthesis",
    "search all zim file for photosynthesis",
    "search all zim archives for photosynthesis",
    "search all .zim files for photosynthesis",
    "search across all zim files for photosynthesis",
]


class TestQ4SearchAllExtractorMatchesIntentPattern:
    """Every phrasing the ``search_all`` INTENT_PATTERN accepts must have
    its cue fully stripped by ``_extract_search_all`` — otherwise the
    whole command sentence becomes the cross-archive search terms."""

    @pytest.mark.parametrize("query", _SEARCH_ALL_VARIANTS)
    def test_cue_is_fully_stripped(self, query: str) -> None:
        params: Dict[str, Any] = {}
        _extract_search_all(query, params)
        assert params["query"] == "photosynthesis"

    @pytest.mark.parametrize("query", _SEARCH_ALL_VARIANTS)
    def test_parse_intent_dispatches_bare_terms(self, query: str) -> None:
        intent, params, _conf = IntentParser.parse_intent(
            query, query_rewrite_enabled=False
        )
        assert intent == "search_all"
        assert params.get("query") == "photosynthesis"

    def test_degenerate_no_terms_falls_back_to_the_raw_query(self) -> None:
        """``search all files`` carries no terms; keep today's raw-query
        fallback rather than dispatching an empty search."""
        params: Dict[str, Any] = {}
        _extract_search_all("search all files", params)
        assert params["query"] == "search all files"


# ===========================================================================
# Q5 — query_rewrite data-path overrides
# ===========================================================================


class TestQ5QueryRewriteDataPathOverrides:
    """``misspelling_map_path`` / ``misspelling_exclusion_path`` must
    reach the loader, not merely sit on the config object."""

    def test_custom_misspelling_map_is_applied(self, tmp_path: Path) -> None:
        map_path = tmp_path / "mis.txt"
        map_path.write_text("zzqqxx=climate\n", encoding="utf-8")
        handler, mock = _handler(
            tmp_path,
            query_rewrite={"misspelling_map_path": str(map_path)},
        )
        handler.handle_zim_query("search for zzqqxx", zim_file_path="/x.zim")
        assert mock.search_zim_file.call_args[0][1] == "climate"

    def test_custom_exclusion_list_suppresses_a_bundled_rewrite(
        self, tmp_path: Path
    ) -> None:
        excl_path = tmp_path / "excl.txt"
        excl_path.write_text("photosythesis\n", encoding="utf-8")
        handler, mock = _handler(
            tmp_path,
            query_rewrite={"misspelling_exclusion_path": str(excl_path)},
        )
        handler.handle_zim_query("search for photosythesis", zim_file_path="/x.zim")
        assert mock.search_zim_file.call_args[0][1] == "photosythesis"

    def test_override_also_drives_the_rewrite_telemetry(self, tmp_path: Path) -> None:
        """The per-rule telemetry probe runs the rules a second time; it has
        to read the same data files the parse itself will."""
        map_path = tmp_path / "mis.txt"
        map_path.write_text("zzqqxx=climate\n", encoding="utf-8")
        handler, _mock = _handler(
            tmp_path,
            query_rewrite={"misspelling_map_path": str(map_path)},
        )
        handler.handle_zim_query("search for zzqqxx", zim_file_path="/x.zim")
        assert handler._telemetry["query_rewrite.misspelling"] == 1

    def test_bundled_defaults_still_apply_without_an_override(
        self, tmp_path: Path
    ) -> None:
        handler, mock = _handler(tmp_path)
        handler.handle_zim_query("search for photosythesis", zim_file_path="/x.zim")
        assert mock.search_zim_file.call_args[0][1] == "photosynthesis"

    def test_nonexistent_override_is_rejected_at_config_time(
        self, tmp_path: Path
    ) -> None:
        """A typo'd path used to be stored and silently ignored; once the
        loader honors it, a bad path must fail loudly at startup."""
        with pytest.raises(ValueError):
            OpenZimMcpConfig(
                allowed_directories=[str(tmp_path)],
                query_rewrite={"misspelling_map_path": str(tmp_path / "nope.txt")},
            )
