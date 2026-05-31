"""Regression tests for the post-a12 beta-test sweep (a13 fixes).

The post-a12 live sweep against the 118 GB Wikipedia ZIM surfaced 8
defects across three passes:

- D1 (Pass 1): orphan-bullet sub-rows chained the previous row's full
  label as their parent (``France``: ``• President — • Prime
  Minister``); the virtual-parent extractor was taking the trailing
  ``split(" — ", 1)[-1]`` instead of the original parent ``[0]``.
- D2 (Pass 1): ``list_namespaces`` reported M=13 while ``walk
  namespace M`` and ``metadata for`` reported M=12 — the M1
  ``is_human_readable_metadata_key`` predicate had been plumbed to
  two of three reporting surfaces.
- D3 / D4 (Pass 1): chained-intent splitter missed bare-topic chains
  (``Biology; Chemistry`` → silently resolved to ``Computational_
  Biology_&_Chemistry``) and single-imperative-prefix chains (``tell
  me about Photosynthesis and then about DNA`` → full-text search on
  the literal phrase).
- D5 (Pass 1): the H2 canonical-splice / H3 list-demote gate fell
  back to the legacy ``search_with_filters`` whenever the top BM25
  result was a token-prefix "strong match" — but the matcher returned
  True for any candidate that extended the topic
  (``Berlin`` → ``Berlin_(disambiguation)``), so the splice never
  fired for any namespace-C archive and ``search for Berlin in
  namespace C`` rendered ``List_of_songs_about_Berlin`` at rank #1
  with the canonical absent.
- D6 (Pass 1): the L2 trailing-connector / trailing-punctuation trim
  used a ``for/else`` structure that only entered the punctuation
  branch when no connector matched; ``tell me about DNA, and then …``
  stripped the ``and`` but left the trailing ``,``.
- D7 (Pass 2): block-level ``<br>``-separated cell values (population
  rank rows, demonyms, HDI rows) joined with a single space, so
  ``5th in Europe 1st in Germany`` read as one phrase to a small LLM.
- D8 (Pass 3): four not-found error paths (``show structure of`` /
  ``summary of`` / ``get article`` / ``links in``) used a legacy
  unstructured template (``**Error Processing Query** …
  Troubleshooting: … Check server logs``) with no intent telemetry
  comment and Python helper-name leakage (``search_zim_file()`` /
  ``browse_namespace()``). ``articles related to`` had already been
  modernised; the other four hadn't.

Each test below pins one of those failures.
"""

from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.simple_tools import SimpleToolsHandler

# ---------------------------------------------------------------------------
# D1: orphan-bullet sub-row parent chaining
# ---------------------------------------------------------------------------


FRANCE_STYLE_INFOBOX_HTML = """
<table class="infobox">
  <tr><th colspan="2">France</th></tr>
  <tr><th class="infobox-header" colspan="2">Government</th></tr>
  <tr><th>• President</th><td>Emmanuel Macron</td></tr>
  <tr class="mergedtoprow"><th>• Prime Minister</th><td>Sébastien Lecornu</td></tr>
  <tr class="mergedtoprow"><th>• President of the Senate</th><td>Gérard Larcher</td></tr>
</table>
"""


@pytest.fixture
def processor() -> ContentProcessor:
    """ContentProcessor with default (advanced-mode) config — matches
    the fixture used in ``test_content_processor_infobox.py``."""
    return ContentProcessor()


class TestD1OrphanBulletParent:
    """a13 D1 (post-a12): consecutive bullet-prefixed continuation
    rows used to chain the PREVIOUS row's full label as the virtual
    parent for the next bullet, producing patterns like
    ``• President — • Prime Minister``. The virtual-parent extractor
    now uses ``split(" — ", 1)[0]`` (the original parent) instead of
    ``[-1]`` (the trailing segment), so consecutive bullet rows
    consistently anchor to the same parent ("Government").
    """

    def test_consecutive_bullet_rows_anchor_to_original_parent(self, processor):
        soup = BeautifulSoup(FRANCE_STYLE_INFOBOX_HTML, "html.parser")
        rows = processor.extract_infobox(soup)
        labels = [r["label"] for r in rows]
        # Each bullet row anchors to the original section header
        # ``Government``, not the previous bullet's label.
        assert "Government — • President" in labels
        assert "Government — • Prime Minister" in labels
        assert "Government — • President of the Senate" in labels
        # The chained shapes that motivated the fix are absent.
        assert "• President — • Prime Minister" not in labels
        assert "• Prime Minister — • President of the Senate" not in labels


# ---------------------------------------------------------------------------
# D2: list_namespaces uses the shared metadata-key predicate
# ---------------------------------------------------------------------------


class TestD2ListNamespacesMetadataPredicate:
    """a13 D2 (post-a12): ``list_namespaces`` aggregated the raw
    ``archive.metadata_keys`` count (13, including the
    ``Illustration_48x48@1`` binary blob) while ``walk namespace M``
    and ``metadata for`` both ran through
    ``is_human_readable_metadata_key`` and reported 12. The fix
    plumbs the predicate to ``_add_new_scheme_metadata_namespace``
    so all three surfaces agree.
    """

    def test_list_namespaces_filters_illustration_keys(self):
        from openzim_mcp.zim.namespace import _NamespaceMixin

        archive = MagicMock()
        archive.metadata_keys = [
            "Title",
            "Description",
            "Language",
            "Date",
            "Illustration_48x48@1",
        ]
        namespaces: dict = {}
        _NamespaceMixin._add_new_scheme_metadata_namespace(archive, namespaces)
        # 4 human-readable keys; Illustration is filtered out.
        assert namespaces["M"]["total"] == 4
        assert namespaces["M"]["sampled_count"] == 4
        sample_keys = {s["title"] for s in namespaces["M"]["sample_entries"]}
        assert "Illustration_48x48@1" not in sample_keys
        assert sample_keys == {"Title", "Description", "Language", "Date"}

    def test_list_namespaces_handles_empty_metadata(self):
        """When the predicate filters out every key, ``M`` should
        not appear at all — same as the empty-``metadata_keys``
        case the original guard already covered."""
        from openzim_mcp.zim.namespace import _NamespaceMixin

        archive = MagicMock()
        archive.metadata_keys = ["Illustration_48x48@1", "Illustration_96x96@1"]
        namespaces: dict = {}
        _NamespaceMixin._add_new_scheme_metadata_namespace(archive, namespaces)
        assert "M" not in namespaces


# ---------------------------------------------------------------------------
# D3 / D4: chained-intent splitter handles bare topics and single-prefix forms
# ---------------------------------------------------------------------------


class TestD3D4ChainedIntentExtensions:
    """a13 D3 / D4 (post-a12): the splitter required an operation
    verb on BOTH sides of the connector. ``Biology; Chemistry`` (bare
    topics, ``;`` connector) and ``tell me about Photosynthesis and
    then about DNA`` (left has verb, right is a continuation phrase)
    both silently fell through to topic-fetch / full-text search.
    D3 detects bare-topic chains on strong connectors and wraps both
    halves with ``tell me about``. D4 re-prefixes the right half with
    the left's verb when the right starts with a continuation token.
    """

    @pytest.fixture
    def handler(self):
        zim_ops = MagicMock()
        return SimpleToolsHandler(zim_ops)

    @pytest.mark.parametrize(
        "query, expected_left, expected_right",
        [
            (
                "Biology; Chemistry",
                "tell me about Biology",
                "tell me about Chemistry",
            ),
            (
                "DNA then Photosynthesis",
                "tell me about DNA",
                "tell me about Photosynthesis",
            ),
            (
                "Berlin and then Munich",
                "tell me about Berlin",
                "tell me about Munich",
            ),
        ],
    )
    def test_d3_bare_topic_chains_detected(
        self, handler, query, expected_left, expected_right
    ):
        out = handler.handle_zim_query(query, "/test/wiki.zim")
        assert "Chained Operations Detected" in out
        assert f"`{expected_left}`" in out
        assert f"`{expected_right}`" in out

    def test_d4_single_imperative_prefix_continuation(self, handler):
        out = handler.handle_zim_query(
            "tell me about Photosynthesis and then about DNA", "/test/wiki.zim"
        )
        assert "Chained Operations Detected" in out
        assert "`tell me about Photosynthesis`" in out
        assert "`tell me about DNA`" in out

    @pytest.mark.parametrize(
        "topic_with_then",
        [
            # The connector token is INSIDE the topic name; not a chain.
            "tell me about then and now",
            "tell me about Now and Then",
            # Long-prose query — the bare-topic D3 path must NOT
            # wrap arbitrary prose around a connector.
            "search for the rise and fall of Rome",
        ],
    )
    def test_d3_d4_do_not_overtrigger(self, handler, topic_with_then):
        """The D3 bare-topic branch must not wrap an incomplete-verb
        half (``tell me about`` with no topic content) with another
        ``tell me about``, and prose queries that happen to contain
        ``and`` or ``then`` must pass through unchanged."""
        out = handler.handle_zim_query(topic_with_then, "/test/wiki.zim")
        assert "Chained Operations Detected" not in out


# ---------------------------------------------------------------------------
# D5: filtered-search canonical-splice early-return uses exact path match
# ---------------------------------------------------------------------------


class TestD5FilteredSearchCanonicalSplice:
    """a13 D5 (post-a12): the canonical-splice early-return at the
    top of the filtered-search results loop checked
    ``is_strong_title_match`` against the BM25 top hit. That matcher
    returns True for any candidate that extends the topic via prefix
    (``Berlin_(disambiguation)`` extends ``Berlin``), so the splice
    silently fell back to the legacy ``search_with_filters`` path
    whenever a disambig or list-shaped variant of the topic
    out-ranked the canonical. New-scheme Wikipedia archives nearly
    always show this shape: ``search for Berlin in namespace C``
    returned ``[List_of_songs_about_Berlin, Berlin_(disambiguation),
    Timeline_of_Berlin]`` with the canonical ``Berlin`` absent. The
    fix tightens the early-return to fire only when the top result's
    path equals the canonical path exactly — so the splice/reorder
    logic runs in every other shape.
    """

    def test_gate_no_longer_uses_loose_title_match(self):
        """The tightened gate uses exact path equality, not the
        loose ``is_strong_title_match`` predicate. Locks the fix
        against regression by asserting the call site no longer
        invokes the matcher for the early-return decision.
        """
        import inspect

        from openzim_mcp.zim.search import _SearchMixin

        # Read the source of the splice method and look for the
        # specific gate shape: ``top_path == canonical_path``. The
        # pre-fix shape used ``is_strong_title_match(query, ...)`` in
        # the same block; the post-fix shape uses path equality.
        # Tier-3 refactor: the gate moved verbatim into the extracted
        # ``_splice_canonical_into_filtered`` helper, so inspect both the
        # dispatcher and the splice body to keep locking the invariant.
        src = inspect.getsource(
            _SearchMixin.search_with_filters_with_canonical_splice
        ) + inspect.getsource(_SearchMixin._splice_canonical_into_filtered)
        # New gate present.
        assert "top_path == canonical_path" in src
        # Old gate removed from the splice path (the predicate is
        # still imported for other callers, but the splice no longer
        # uses it for the early-return).
        # Match the specific call shape rather than the bare symbol —
        # the import line ``from … import …, is_strong_title_match``
        # remains in the file.
        assert "is_strong_title_match(\n                query," not in src
        assert "is_strong_title_match(query," not in src

    def test_canonical_with_extends_topic_top_no_longer_loosely_matches(self):
        """Sanity check on the underlying matcher: the predicate the
        old gate used WAS True for ``(Berlin, Berlin_(disambiguation))``
        — that's why the splice silently dropped through for any
        topic with a disambig page. Anchors the fix's motivation.
        """
        from openzim_mcp.title_promotion import is_strong_title_match

        # Pre-fix the gate fired on this — proving the gate was the
        # wrong predicate.
        assert is_strong_title_match(
            "Berlin", "Berlin_(disambiguation)", "Berlin (disambiguation)"
        )


# ---------------------------------------------------------------------------
# D6: L2 trim is iterative — strips connector AND trailing punctuation
# ---------------------------------------------------------------------------


class TestD6IterativeChainedIntentTrim:
    """a13 D6 (post-a12): the L2 trim used ``for/else`` so a single
    pass stripped either a trailing connector word OR trailing
    ``;,`` — never both. ``tell me about DNA, and then tell me about
    Photosynthesis`` split on ``then`` to left=``tell me about DNA,
    and``, the loop stripped the trailing ``and`` but the ``else``
    branch never ran, so the trailing comma stayed. Looping until
    stable strips both in any order.
    """

    @pytest.fixture
    def handler(self):
        zim_ops = MagicMock()
        return SimpleToolsHandler(zim_ops)

    def test_trailing_comma_after_connector_stripped(self, handler):
        out = handler.handle_zim_query(
            "tell me about DNA, and then tell me about Photosynthesis",
            "/test/wiki.zim",
        )
        assert "Chained Operations Detected" in out
        # The left op renders cleanly — no trailing comma, no
        # orphan ``and``.
        assert "`tell me about DNA`" in out
        assert "`tell me about DNA,`" not in out
        assert "`tell me about DNA, and`" not in out
        assert "`tell me about DNA and`" not in out

    def test_trailing_semicolon_then_connector_stripped(self, handler):
        # Constructed shape: ``X; and then Y`` would trip both the
        # ``;`` connector match AND a trailing ``and`` from the
        # left half if the split landed there. Verify the iterative
        # trim handles a contrived sequence where both an orphan
        # connector and a punctuation tail are present.
        out = handler.handle_zim_query(
            "tell me about Berlin, or then tell me about Munich",
            "/test/wiki.zim",
        )
        assert "Chained Operations Detected" in out
        assert "`tell me about Berlin`" in out
        assert "`tell me about Berlin,`" not in out
        assert "`tell me about Berlin, or`" not in out


# ---------------------------------------------------------------------------
# D7: block-level cell separator upgraded from " " to "; "
# ---------------------------------------------------------------------------


D7_INFOBOX_HTML = """
<table class="infobox">
  <tr><th colspan="2">São Paulo</th></tr>
  <tr><th>Rank</th><td>1st in the Americas<br>1st in Brazil</td></tr>
</table>
"""


class TestD7InfoboxBlockSeparator:
    """a13 D7 (post-a12): block-level ``<br>``-separated cell values
    used to join with a bare space (``5th in Europe 1st in Germany``)
    — a downstream small LLM tokenises the merged form as a single
    phrase. The block-cell joiner now emits ``; `` between block
    boundaries so the value reads as two distinct items.
    """

    def test_block_separated_cell_uses_semicolon_separator(self, processor):
        soup = BeautifulSoup(D7_INFOBOX_HTML, "html.parser")
        rows = {r["label"]: r["value"] for r in processor.extract_infobox(soup)}
        assert rows["Rank"] == "1st in the Americas; 1st in Brazil"

    def test_inline_spans_still_concatenate_directly(self, processor):
        """The D7 separator change must NOT affect inline-span groups
        that the a11 second-pass fix introduced — number formatting
        and coordinate templates rely on bare concatenation across
        inline spans.
        """
        html = """
        <table class="infobox">
          <tr><th colspan="2">Berlin</th></tr>
          <tr><th>Population</th><td><span>3</span><span>,</span><span>913</span></td></tr>
          <tr><th>Coord</th><td>52<span>°</span>31<span>′</span>N</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        rows = {r["label"]: r["value"] for r in processor.extract_infobox(soup)}
        assert rows["Population"] == "3,913"
        assert rows["Coord"] == "52°31′N"


# ---------------------------------------------------------------------------
# D8: not-found error responses are modernised on all 4 surfaces
# ---------------------------------------------------------------------------


class TestD8ModernisedNotFoundErrors:
    """a13 D8 (post-a12): ``get article`` / ``summary of`` / ``links
    in`` / ``show structure of`` for an unknown entry path used to
    propagate the backend exception up to the top-level
    ``handle_zim_query`` ``except`` block, which emitted a generic
    ``**Error Processing Query** … Troubleshooting: 1. Check ZIM
    file path … 4. Check server logs`` template with no
    ``<!-- intent=... cert=... -->`` telemetry and Python helper
    name leakage in the error body. Each handler now catches the
    backend exception and renders a structured ``Article not found:
    `path`` shape with suggestion / find-titled / search recovery
    commands and the outer telemetry decoration applies.
    """

    @pytest.fixture
    def handler(self):
        zim_ops = MagicMock()
        return SimpleToolsHandler(zim_ops)

    def _stub_backend(self, handler, method_name):
        """Make the underlying backend method raise an "entry not
        found" exception that includes a Python helper-name leak.
        """
        err = Exception(
            "Entry not found: 'Nonexistent_xyz'. "
            "Try using search_zim_file() to find available entries."
        )
        getattr(handler.zim_operations, method_name).side_effect = err
        # The natural-language path resolver also probes the title
        # index — make it return ``None`` so we exercise the
        # not-found path on the literal entry_path.
        handler.zim_operations.find_entry_by_title_data = MagicMock(
            return_value={"results": []}
        )

    @pytest.mark.parametrize(
        "query, method_name, op_label",
        [
            ("get article Nonexistent_xyz", "get_zim_entry", "get article"),
            ("summary of Nonexistent_xyz", "get_entry_summary", "summary of"),
            ("links in Nonexistent_xyz", "extract_article_links", "links in"),
            (
                "show structure of Nonexistent_xyz",
                "get_article_structure",
                "show structure of",
            ),
        ],
    )
    def test_not_found_response_is_structured(
        self, handler, query, method_name, op_label
    ):
        self._stub_backend(handler, method_name)
        out = handler.handle_zim_query(query, "/test/wiki.zim")
        # Title carries the article path (lowercased by Sub-D-2 Rule 1).
        assert "**Article not found: `nonexistent_xyz`**" in out
        # Recovery block lists the three concrete next-step commands.
        assert "suggestions for nonexistent_xyz" in out
        assert "find article titled nonexistent_xyz" in out
        assert "search for nonexistent_xyz" in out
        # Legacy template artifacts are gone.
        assert "**Error Processing Query**" not in out
        assert "Check server logs" not in out
        # Python helper-name leak from the backend is scrubbed.
        assert "search_zim_file()" not in out
        # Outer telemetry decoration applied (the handler returned a
        # string, so the top-level ``handle_zim_query`` appended the
        # intent comment).
        assert "<!-- intent=" in out
        assert "cert=" in out
