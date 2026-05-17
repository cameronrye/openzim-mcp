"""Regression tests for the post-a15 beta-test sweep (a16 fixes).

The post-a15 live sweep against the 118 GB Wikipedia ZIM surfaced
four user-facing defects:

- D4 (Pass 1): ``tell me about Mercury`` — Mercury is a disambiguation
  page (no canonical article at the bare title), so the resolver
  picked it as canonical and the
  ``_handle_tell_me_about`` footer logic then appended ``_May also
  refer to: Mercury_Monterey — use tell me about <full title>_``,
  naming one random extends-topic sibling while the body itself
  enumerates dozens of disambig entries. Two cooperating bugs: the
  ``_is_disambig_lead`` detection had a 400-char cap on ``pre_h2``
  and Mercury's pre-H2 is 628 chars (the "most commonly refers to"
  preamble plus three top-level entries push it over), so the
  disambig-page case never triggered the existing suppression logic;
  AND the trailing footer block in ``_handle_tell_me_about`` didn't
  check whether the resolved body was itself a disambig page.

- D5 (Pass 1): ``could you tell me about Photosynthesis`` parsed with
  ``topic = "could you tell me about Photosynthesis"`` — the leading
  modal "could you" / "can you" / "would you" / "will you" didn't
  match the verb-prefix regex and the whole query fell through to
  the ``topic = query.strip()`` fallback. Article still resolved via
  the tail-probe entity rescue, but the parsed topic is wrong.

- D6 (Pass 1): ``find article titled M/Title`` returned 0 hits even
  though ``get article M/Title`` succeeds — the title index only
  stores titles (M/Title's title is "Title"), and the handler passed
  the path straight through with no signal to the caller that the
  wrong tool was in use.

- D7 (Pass 1): ``walk namespace A`` against a new-scheme archive
  returned a response missing the ``namespace_entry_count`` field
  that walk-M / walk-W include — schema inconsistency in the
  short-circuit at ``namespace.py:1554``. Downstream consumers had
  to special-case "missing" vs "zero".

Each test pins one defect; failures here mean a regression on the
specific bug.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler

# ---------------------------------------------------------------------------
# D5: politeness lead-in ("could you / can you / would you / will you")
# ---------------------------------------------------------------------------


class TestD5PolitenessLeadIn:
    """D5: the verb-prefix regex anchors at ``^\\s*`` and never matched
    a leading modal ("could you tell me about X"). Fix strips the
    modal scaffold before the verb regex sees the query.
    """

    @pytest.fixture
    def parser(self) -> IntentParser:
        return IntentParser()

    @pytest.mark.parametrize(
        "query",
        [
            "could you tell me about Photosynthesis",
            "Could You Tell Me About Photosynthesis",
            "can you tell me about Photosynthesis",
            "would you tell me about Photosynthesis",
            "will you tell me about Photosynthesis",
            "could you please tell me about Photosynthesis",
            "can you describe Photosynthesis",
            "would you explain Photosynthesis",
            "could we tell me about Photosynthesis",  # weird but tolerated
        ],
    )
    def test_modal_lead_in_stripped(self, parser: IntentParser, query: str) -> None:
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "tell_me_about"
        assert params["topic"] == "Photosynthesis"

    def test_modal_lead_in_with_trailing_politeness(self, parser: IntentParser) -> None:
        # Both ends should strip: leading "could you", trailing "please".
        intent, params, _ = IntentParser.parse_intent(
            "could you tell me about Photosynthesis please"
        )
        assert intent == "tell_me_about"
        assert params["topic"] == "Photosynthesis"

    def test_no_modal_unchanged(self, parser: IntentParser) -> None:
        # Sanity: queries that never had a modal lead-in still work.
        intent, params, _ = IntentParser.parse_intent("tell me about Photosynthesis")
        assert intent == "tell_me_about"
        assert params["topic"] == "Photosynthesis"


# ---------------------------------------------------------------------------
# D6: find_by_title namespace-path redirect
# ---------------------------------------------------------------------------


class TestD6FindByTitleNamespacePathRedirect:
    """D6: ``find article titled M/Title`` returned silent 0 hits.
    Fix detects the ``[A-Z]/...`` namespace-prefix shape and redirects
    the caller to ``get article`` upfront, before the doomed backend
    call.
    """

    @pytest.fixture
    def handler(self) -> SimpleToolsHandler:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        # If the redirect fires, these never get called — make them
        # explode if they do, so accidental call surfaces clearly.
        mock.find_entry_by_title_data.side_effect = AssertionError(
            "find_entry_by_title_data should not be called for namespace paths"
        )
        mock.find_entry_by_title.side_effect = AssertionError(
            "find_entry_by_title should not be called for namespace paths"
        )
        return SimpleToolsHandler(mock)

    @pytest.mark.parametrize(
        "title",
        ["M/Title", "M/Counter", "A/Photosynthesis", "W/mainPage"],
    )
    def test_namespace_path_returns_redirect(
        self, handler: SimpleToolsHandler, title: str
    ) -> None:
        out = handler.handle_zim_query(
            f"find article titled {title}",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Namespace Path, Not a Title" in out
        assert f"get article {title}" in out
        # Suggests the title-only fallback too.
        assert f"find article titled {title[2:]}" in out

    def test_real_title_unaffected(self) -> None:
        # ``find article titled Photosynthesis`` (no namespace prefix)
        # must still hit the backend.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.find_entry_by_title_data.return_value = {
            "query": "Photosynthesis",
            "results": [{"path": "Photosynthesis", "title": "Photosynthesis"}],
            "total": 1,
        }
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "find article titled Photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        assert "Namespace Path, Not a Title" not in out
        # Backend was called.
        mock.find_entry_by_title_data.assert_called_once()

    def test_lowercase_first_char_not_redirected(self) -> None:
        # ``find article titled a/b`` doesn't look like a namespace
        # path (namespaces are uppercase) — let the backend handle it.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.find_entry_by_title.return_value = "no hits"
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "find article titled a/b",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Namespace Path, Not a Title" not in out


# ---------------------------------------------------------------------------
# D7: walk_namespace empty new-scheme namespace schema
# ---------------------------------------------------------------------------


class TestD7WalkNamespaceEmptySchema:
    """D7: the new-scheme non-C/M/W short-circuit at
    ``namespace.py:1554`` returned an empty result without
    ``namespace_entry_count``, while walk-M / walk-W include the
    field. Fix passes ``namespace_entry_count=0``.
    """

    def test_empty_new_scheme_namespace_has_zero_count(self) -> None:
        # Hit the build path directly — the surrounding archive setup
        # is irrelevant to the schema-shape assertion.
        from openzim_mcp.zim.namespace import _NamespaceMixin

        result = _NamespaceMixin._build_walk_result(
            namespace="A",
            scan_at=0,
            limit=200,
            entries=[],
            scanned_count=0,
            scanned_through_id=None,
            done=True,
            next_cursor=None,
            archive_entry_count=27_199_904,
            namespace_entry_count=0,
        )
        assert "namespace_entry_count" in result
        assert result["namespace_entry_count"] == 0
        # Sibling fields still present.
        assert result["namespace"] == "A"
        assert result["results"] == []
        assert result["done"] is True
        assert result["archive_entry_count"] == 27_199_904

    def test_build_walk_result_omits_field_when_none(self) -> None:
        # Sanity: the helper's existing contract (omit when None) is
        # preserved for callers that legitimately don't know the
        # namespace total (e.g. mid-scan C iteration on old-scheme
        # archives).
        from openzim_mcp.zim.namespace import _NamespaceMixin

        result = _NamespaceMixin._build_walk_result(
            namespace="C",
            scan_at=0,
            limit=200,
            entries=[],
            scanned_count=0,
            scanned_through_id=None,
            done=True,
            next_cursor=None,
            archive_entry_count=100,
            namespace_entry_count=None,
        )
        assert "namespace_entry_count" not in result

    def test_short_circuit_call_site_passes_zero(self) -> None:
        """Source-level assertion: the short-circuit branch for new-
        scheme non-C/M/W namespaces must pass
        ``namespace_entry_count=0`` to ``_build_walk_result``. Live-
        sweep mocking of libzim is too brittle for a single-bug test,
        so we pin the fix at the call site.
        """
        from pathlib import Path

        src = (
            Path(__file__).parent.parent / "openzim_mcp" / "zim" / "namespace.py"
        ).read_text()
        # Find the ``has_new_scheme and namespace != "C"`` short-circuit
        # block and confirm the next ``_build_walk_result`` call inside
        # it sets ``namespace_entry_count=0``.
        marker = 'has_new_scheme and namespace != "C"'
        idx = src.find(marker)
        assert idx != -1, "short-circuit branch not found"
        block = src[idx : idx + 1500]
        assert "_build_walk_result(" in block
        assert "namespace_entry_count=0" in block, (
            "post-a15 D7 fix missing: the new-scheme non-C/M/W "
            "short-circuit no longer passes namespace_entry_count=0, "
            "regressing the schema-consistency contract surfaced by "
            "walk namespace A against Wikipedia."
        )


# ---------------------------------------------------------------------------
# D4: disambig page detection (long preamble) + footer suppression
# ---------------------------------------------------------------------------


# Mercury-shaped pre-H2 body: > 400 chars, ends with "may also refer
# to:" right before the first ## section. Synthesized to reproduce
# the exact failure mode the live sweep surfaced.
MERCURY_STYLE_PRE_H2 = (
    'Look up _**[Mercury](https://en.wiktionary.org/wiki/Mercury "wiktionary:'
    'Mercury")**_ or _**[mercury](https://en.wiktionary.org/wiki/mercury '
    '"wiktionary:mercury")**_ in Wiktionary, the free dictionary.\n\n'
    "**Mercury** most commonly refers to: \n\n"
    '  * [Mercury (planet)](Mercury_\\(planet\\) "Mercury \\(planet\\)"), '
    "the closest planet to the Sun\n"
    '  * [Mercury (element)](Mercury_\\(element\\) "Mercury \\(element\\)"), '
    "a chemical element\n"
    '  * [Mercury (mythology)](Mercury_\\(mythology\\) "Mercury '
    '\\(mythology\\)"), a Roman deity\n\n'
    "**Mercury** or **The Mercury** may also refer to:"
)


class TestD4DisambigDetectionLongPreamble:
    """D4 part 1: ``_is_disambig_lead`` used to bail out at
    ``len(pre_h2) >= 400`` and missed pages like Mercury whose
    pre-H2 carries a 'most commonly refers to' preamble. Fix checks
    only the trailing 400 chars.
    """

    def test_mercury_style_long_preamble_detected(self) -> None:
        assert len(MERCURY_STYLE_PRE_H2) > 400
        assert SimpleToolsHandler._is_disambig_lead(MERCURY_STYLE_PRE_H2)

    def test_short_disambig_lead_still_detected(self) -> None:
        # Existing behaviour preserved for short Martin-style pages.
        short = "**Martin** may refer to:"
        assert SimpleToolsHandler._is_disambig_lead(short)

    def test_non_disambig_long_body_not_misdetected(self) -> None:
        # A long pre-H2 that doesn't end with the trigger phrase
        # must still return False — the tail-window check shouldn't
        # false-positive on text that mentions "may refer to" earlier
        # in the body.
        not_disambig = (
            "Photosynthesis is a system of biological processes by which " * 20
        ) + "the chloroplast houses the reaction centers."
        assert len(not_disambig) > 400
        assert not SimpleToolsHandler._is_disambig_lead(not_disambig)

    def test_mentions_phrase_earlier_but_not_at_tail_rejected(self) -> None:
        # Defense against false positive: a body that mentions "may
        # refer to" earlier but ends differently shouldn't trigger.
        body = (
            "The phrase 'may refer to' is sometimes used in legal "
            "documents. " * 30
            + "However, photosynthesis is a biological process unrelated "
            "to such usage."
        )
        assert len(body) > 400
        assert not SimpleToolsHandler._is_disambig_lead(body)


class TestD4DisambigFooterSuppression:
    """D4 part 2: when the resolved article body IS itself a
    disambiguation page (Mercury-style), the trailing
    ``_Note: this topic also has a disambiguation page_`` and
    ``_May also refer to: <one extends-topic sibling>_`` footers are
    misleading — the body already lists every alternative. Fix
    detects the case and suppresses both footers.
    """

    @pytest.fixture
    def make_handler(self):
        def factory(
            *, article_body: str, search_results: list, title_index: dict | None = None
        ):
            mock = MagicMock()
            mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
            mock.search_zim_file_data.return_value = {"results": search_results}
            mock.get_zim_entry.return_value = article_body
            mock.config.meta.footer_enabled = False
            mock.find_entry_by_title_data.return_value = (
                {"results": [title_index]} if title_index else {"results": []}
            )
            mock.get_article_structure_data.return_value = {"sections": []}
            return SimpleToolsHandler(mock), mock

        return factory

    def test_disambig_body_suppresses_extends_topic_footer(
        self, make_handler: Any
    ) -> None:
        # Mercury-style disambig page as canonical, with one sibling
        # extends-topic match (Mercury_Monterey). The misleading
        # "_May also refer to: Mercury_Monterey_" footer must be
        # dropped because the body already enumerates dozens of
        # alternates.
        disambig_body = (
            f"# Mercury\n\n{MERCURY_STYLE_PRE_H2}\n\n"
            "## Companies\n"
            "  * [Mercury Communications](Mercury_Communications)\n"
            "## Computing\n"
            "  * [Mercury (programming language)](Mercury_(programming_language))\n"
        )
        handler, _ = make_handler(
            article_body=disambig_body,
            search_results=[
                {"path": "Mercury", "title": "Mercury", "score": 100},
                {
                    "path": "Mercury_Monterey",
                    "title": "Mercury Monterey",
                    "score": 50,
                },
            ],
            title_index={"path": "Mercury", "title": "Mercury", "score": 1.0},
        )
        out = handler.handle_zim_query(
            "tell me about Mercury",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "_Source: `Mercury`_" in out
        # The misleading footer must be absent.
        assert "May also refer to" not in out
        assert "Mercury_Monterey — use" not in out
        # But the body content is still there.
        assert "may also refer to" in out.lower()  # from the body itself
        assert "Mercury (programming language)" in out

    def test_disambig_body_suppresses_twin_note_footer(self, make_handler: Any) -> None:
        # When the resolved disambig body is paired with a twin
        # disambig path (rare but possible), suppress that footer too —
        # the twin redirects to the same kind of content.
        disambig_body = (
            f"# Java\n\n{MERCURY_STYLE_PRE_H2.replace('Mercury', 'Java')}\n\n"
            "## Computing\n  * [Java (programming language)](Java_(programming_language))\n"
        )
        handler, _ = make_handler(
            article_body=disambig_body,
            search_results=[
                {"path": "Java", "title": "Java", "score": 100},
                {
                    "path": "Java_(disambiguation)",
                    "title": "Java (disambiguation)",
                    "score": 80,
                },
            ],
            title_index={"path": "Java", "title": "Java", "score": 1.0},
        )
        out = handler.handle_zim_query(
            "tell me about Java",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "_Source: `Java`_" in out
        # The note footer that points to the (disambiguation) twin is
        # redundant when the body itself is the disambig page.
        assert "this topic also has a disambiguation page" not in out

    def test_canonical_article_still_gets_footers(self, make_handler: Any) -> None:
        # Sanity: canonical-article path (e.g., Berlin) keeps its
        # disambig-twin "Note" footer. The fix must not regress this.
        canonical_body = (
            "# Berlin\n\n"
            "Berlin is the capital of Germany. " * 50
            + "\n\n## History\n\nBerlin was first documented in the 13th century. " * 10
        )
        handler, _ = make_handler(
            article_body=canonical_body,
            search_results=[
                {"path": "Berlin", "title": "Berlin", "score": 100},
                {
                    "path": "Berlin_(disambiguation)",
                    "title": "Berlin (disambiguation)",
                    "score": 80,
                },
            ],
            title_index={"path": "Berlin", "title": "Berlin", "score": 1.0},
        )
        out = handler.handle_zim_query(
            "tell me about Berlin",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "_Source: `Berlin`_" in out
        # Canonical article: the disambig-twin footer fires because
        # the body is NOT a disambig page.
        assert "this topic also has a disambiguation page" in out
