"""Intent-parsing sweep: filler gating, chain detection, keyword routing.

Every test drives ``SimpleToolsHandler.handle_zim_query`` end to end against
a real libzim archive built for the purpose (or the climate-change fixture),
so the parser, the gates and the dispatcher all run for real and the
assertions are on what a caller actually gets back.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from libzim.writer import Creator

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.zim_operations import ZimOperations
from tests.conftest_v2_fixtures import _HtmlItem

# (path, title, lead paragraph). Each lead carries a phrase no other article
# shares, so a test can tell WHICH article a response rendered.
_ARTICLES = [
    ("A/Stress", "Stress", "Stress is the body's response to a demand or threat."),
    ("A/Being", "Being", "Being is the most general concept of metaphysics."),
    # Traps: titles that collide with conversational filler. Answering the
    # filler with one of these bodies is the failure the gates exist for.
    ("A/You", "You", "You is a psychological thriller television series."),
    ("A/Try_Again", "Try Again", "Try Again is a song recorded by Aaliyah."),
    ("A/Both", "Both", "Both is a single released by a Danish pop duo."),
    ("A/Test", "Test", "A test is an assessment of knowledge or skill."),
    ("A/Help", "Help", "Help is the fifth studio album by the Beatles."),
    # Lung conditions. Full-text search wants every query term, so the two
    # that a two-entity query should land on mention "asthma and" too, and
    # the aspect-list leads carry their query's words the way real
    # MedlinePlus pages do.
    (
        "A/Asthma",
        "Asthma",
        "Asthma is a long-term disease of the airways; the causes, symptoms"
        " and treatments of asthma vary.",
    ),
    (
        "A/Diabetes",
        "Diabetes",
        "Diabetes is a disease of high blood sugar; signs, symptoms and"
        " treatment of diabetes differ by type.",
    ),
    ("A/COPD", "COPD", "In COPD, as in asthma and bronchitis, the airways narrow."),
    (
        "A/Emphysema",
        "Emphysema",
        "Emphysema, like asthma and bronchitis, causes shortness of breath.",
    ),
    # Titles that carry an intent keyword. ``Time`` is the trap the
    # ``brief`` keyword used to summarise in place of the book.
    (
        "A/Brief_psychotic_disorder",
        "Brief psychotic disorder",
        "Brief psychotic disorder is a sudden, short-lived psychotic episode.",
    ),
    (
        "A/The_Structure_of_Scientific_Revolutions",
        "The Structure of Scientific Revolutions",
        "The Structure of Scientific Revolutions is a 1962 book by Thomas Kuhn.",
    ),
    (
        "A/A_Brief_History_of_Time",
        "A Brief History of Time",
        "A Brief History of Time is a cosmology book Stephen Hawking wrote"
        " for readers who are new to physics.",
    ),
    ("A/Time", "Time", "Time is the continued sequence of existence and events."),
    (
        "A/Stomach",
        "Stomach",
        "The stomach is a muscular organ; the contents of the stomach pass"
        " on to the small intestine.",
    ),
    (
        "A/Insomnia",
        "Insomnia",
        "Insomnia is a common sleep disorder, and some suggestions for"
        " treating insomnia start with a regular bedtime.",
    ),
]


def _page(title: str, lead: str) -> str:
    return f"<html><body><h1>{title}</h1><p>{lead}</p></body></html>"


@pytest.fixture(scope="module")
def sweep_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("intent-sweep") / "intent_sweep.zim"
    with Creator(out).config_indexing(True, "eng") as creator:
        for path, title, lead in _ARTICLES:
            creator.add_item(_HtmlItem(path, title, _page(title, lead)))
        creator.set_mainpath("A/Stress")
    return out


def _handler_for(zim: Path) -> SimpleToolsHandler:
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(zim.parent)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=2000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    ops = ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )
    return SimpleToolsHandler(ops)


@pytest.fixture(scope="module")
def handler(sweep_zim: Path) -> SimpleToolsHandler:
    return _handler_for(sweep_zim)


@pytest.fixture(scope="module")
def climate_zim() -> Path:
    # Module-scoped, so it cannot take the function-scoped
    # ``real_content_zim_files``; same lookup as ``zim_test_data_dir``.
    base = os.environ.get("ZIM_TEST_DATA_DIR")
    root = (
        Path(base)
        if base
        else Path(__file__).parent.parent / "test_data" / "zim-testing-suite"
    )
    zim = root / "withns" / "wikipedia_en_climate_change_mini_2024-06.zim"
    if not zim.is_file():
        pytest.skip("wikipedia_climate ZIM fixture not available")
    return zim


@pytest.fixture(scope="module")
def climate(climate_zim: Path) -> SimpleToolsHandler:
    return _handler_for(climate_zim)


def _ask(handler: SimpleToolsHandler, zim: Path, query: str) -> str:
    out = handler.handle_zim_query(query, str(zim))
    assert isinstance(out, str), out
    return out


# ---------------------------------------------------------------------------
# 1. Real topics refused as "conversational filler"
# ---------------------------------------------------------------------------


class TestFramedContentNounsAreNotFiller:
    """``tell me about stress`` and ``what is being`` came back as the
    filler playbook: the extracted-topic gate tested the topic against the
    whole filler vocabulary, and ``stress`` / ``being`` are in it (as
    LLM-passthrough meta-talk, ``stress test this tool``). A topic the
    caller put inside an explicit topic frame is a topic ask; only the
    function words and conversational responses may refuse it there.
    """

    @pytest.mark.parametrize(
        ("query", "lead"),
        [
            ("tell me about stress", "the body's response to a demand"),
            ("what is being", "the most general concept of metaphysics"),
        ],
    )
    def test_a_framed_content_noun_reaches_its_article(
        self, handler: SimpleToolsHandler, sweep_zim: Path, query: str, lead: str
    ) -> None:
        out = _ask(handler, sweep_zim, query)
        assert "intent=meta_only_guidance" not in out, out[:400]
        assert "intent=tell_me_about" in out, out[-300:]
        assert lead in out, out[:600]


class TestConversationalFillerIsStillRefused:
    """The narrow fix must not reopen the traps the gates were built for:
    ``who are you`` extracts the topic ``you`` (D-T2), and the bare
    passthroughs land on titles that collide with them (the Aaliyah
    ``Try Again`` body). Each trap article is in the archive, so a gate
    that let one through would answer with its body."""

    @pytest.mark.parametrize(
        ("query", "trap"),
        [
            ("who are you", "psychological thriller"),
            ("try again", "recorded by Aaliyah"),
            ("do both", "Danish pop duo"),
            ("test", "assessment of knowledge"),
            ("help", "studio album by the Beatles"),
        ],
    )
    def test_filler_gets_the_playbook_not_a_colliding_article(
        self, handler: SimpleToolsHandler, sweep_zim: Path, query: str, trap: str
    ) -> None:
        out = _ask(handler, sweep_zim, query)
        assert "intent=meta_only_guidance" in out, out[:400]
        assert "tell me about <topic>" in out
        assert trap not in out, out[:600]

    def test_framed_what_is_wrong_stays_filler(
        self, climate: SimpleToolsHandler, climate_zim: Path
    ) -> None:
        """``right`` / ``wrong`` are nouns too, but framed alone they are
        the conversational ``what is wrong?`` — and this archive answers
        that with the "Not Evil Just Wrong" film article."""
        out = _ask(climate, climate_zim, "what is wrong")
        assert "intent=meta_only_guidance" in out, out[:400]
        assert "Not Evil Just Wrong" not in out, out[:400]


# ---------------------------------------------------------------------------
# 4. The short-acronym rule never fired on live queries
# ---------------------------------------------------------------------------


class TestShortAcronymHalvesCountOnLiveQueries:
    """``_is_substantive_topic`` accepts a short ALL-CAPS half (``COPD``,
    ``HTTP``), but Rule 1 lowercases the query before the topic is
    extracted, so on a live call the rule only ever saw ``copd`` and
    ``http``. Its tests passed because they called the helper directly
    with uppercase input."""

    def test_the_half_dropped_beside_an_acronym_is_named(
        self, handler: SimpleToolsHandler, sweep_zim: Path
    ) -> None:
        out = _ask(handler, sweep_zim, "tell me about asthma and COPD")
        assert "the airways narrow" in out, out[:400]
        assert "Returned the article for `COPD`" in out, out[-400:]
        assert "query separately with `tell me about asthma`" in out

    def test_a_chain_of_acronyms_is_rejected_in_typed_case(
        self, handler: SimpleToolsHandler, sweep_zim: Path
    ) -> None:
        out = _ask(handler, sweep_zim, "tell me about TCP/IP and HTTP and HTTPS")
        assert "No search results found" not in out, out[:400]
        assert "intent=multi_entity_chain_rejected" in out, out[:400]
        for half in ("TCP/IP", "HTTP", "HTTPS"):
            assert f"`tell me about {half}`" in out, out[:600]


# ---------------------------------------------------------------------------
# 2. An attribute list of one topic rejected as several entities
# ---------------------------------------------------------------------------


class TestAspectListOfOneTopicIsNotAChain:
    """``the causes, symptoms and treatments of asthma`` split on its
    connectors into three substantive halves and got "Multi-Entity Chain
    Detected", with follow-ups ``tell me about the causes`` and ``tell me
    about symptoms``. The ``of asthma`` in the last part applies to every
    part: it is one topic's aspects, not three topics."""

    @pytest.mark.parametrize(
        ("query", "lead"),
        [
            (
                "what are the causes, symptoms and treatments of asthma",
                "long-term disease of the airways",
            ),
            (
                "tell me about signs, symptoms and treatment of diabetes",
                "disease of high blood sugar",
            ),
        ],
    )
    def test_an_aspect_list_reaches_the_topic(
        self, handler: SimpleToolsHandler, sweep_zim: Path, query: str, lead: str
    ) -> None:
        out = _ask(handler, sweep_zim, query)
        assert "Multi-Entity Chain Detected" not in out, out[:400]
        assert "intent=tell_me_about" in out, out[-300:]
        assert lead in out, out[:600]

    @pytest.mark.parametrize(
        ("query", "entities"),
        [
            # Same shape, but the earlier parts are names, not aspects.
            (
                "tell me about Plato, Aristotle and the philosophy of mind",
                ("Plato", "Aristotle", "the philosophy of mind"),
            ),
            # Bare common nouns with no shared ``of X`` to apply to.
            (
                "tell me about asthma, emphysema and bronchitis",
                ("asthma", "emphysema", "bronchitis"),
            ),
        ],
    )
    def test_a_real_entity_list_is_still_rejected(
        self,
        handler: SimpleToolsHandler,
        sweep_zim: Path,
        query: str,
        entities: tuple,
    ) -> None:
        out = _ask(handler, sweep_zim, query)
        assert "intent=multi_entity_chain_rejected" in out, out[:400]
        for entity in entities:
            assert f"`tell me about {entity}`" in out, out[:600]

    def test_a_two_entity_query_keeps_its_dropped_half_note(
        self, handler: SimpleToolsHandler, sweep_zim: Path
    ) -> None:
        out = _ask(handler, sweep_zim, "tell me about asthma and emphysema")
        assert "causes shortness of breath" in out, out[:400]
        assert "query separately with `tell me about asthma`" in out, out[-400:]


# ---------------------------------------------------------------------------
# 3. Keywords inside topics hijacked the intent
# ---------------------------------------------------------------------------


class TestKeywordsInsideTopicsDoNotHijack:
    """The structure / toc / summary / suggestions keywords matched
    anywhere in the query at 0.85-0.95 and outranked ``tell me about``;
    ``file`` and ``home page`` did the same for the archive list and the
    archive's front page. Each query below names a topic that merely
    contains the keyword."""

    @pytest.mark.parametrize(
        ("query", "hijacked_to", "lead"),
        [
            # Was ``summary`` with no entry path: "Missing Article Path".
            (
                "what is brief psychotic disorder",
                "summary",
                "a sudden, short-lived psychotic episode",
            ),
            # Was ``structure`` of "scientific revolutions": not found.
            (
                "tell me about The Structure of Scientific Revolutions",
                "structure",
                "a 1962 book by Thomas Kuhn",
            ),
            # Was ``toc`` of "the stomach".
            (
                "what are the contents of the stomach",
                "toc",
                "pass on to the small intestine",
            ),
            # Was an empty autocomplete for "treating insomnia".
            (
                "what are some suggestions for treating insomnia",
                "suggestions",
                "start with a regular bedtime",
            ),
        ],
    )
    def test_a_framed_topic_keeps_its_keyword(
        self,
        handler: SimpleToolsHandler,
        sweep_zim: Path,
        query: str,
        hijacked_to: str,
        lead: str,
    ) -> None:
        out = _ask(handler, sweep_zim, query)
        assert f"intent={hijacked_to} " not in out, out[-300:]
        assert "intent=tell_me_about" in out, out[-300:]
        assert lead in out, out[:600]

    def test_brief_inside_a_title_is_not_a_summary_verb(
        self, handler: SimpleToolsHandler, sweep_zim: Path
    ) -> None:
        """``who wrote A Brief History of Time`` summarised "Time"."""
        out = _ask(handler, sweep_zim, "who wrote A Brief History of Time")
        assert "intent=summary" not in out, out[-300:]
        assert "continued sequence of existence" not in out, out[:600]
        assert "A Brief History of Time" in out, out[:600]
        assert "intent=search" in out, out[-300:]

    def test_file_format_is_not_the_archive_list(
        self, climate: SimpleToolsHandler, climate_zim: Path
    ) -> None:
        out = _ask(climate, climate_zim, "what file format do climate models use")
        assert "intent=list_files" not in out, out[-300:]
        assert climate_zim.name not in out, out[:600]
        assert "intent=search" in out, out[-300:]
        assert "what file format do climate models use" in out, out[:300]

    def test_another_sites_home_page_is_not_the_archive_front_page(
        self, climate: SimpleToolsHandler, climate_zim: Path
    ) -> None:
        out = _ask(climate, climate_zim, "what is the home page of the IPCC")
        assert "intent=main_page" not in out, out[-300:]
        assert "intent=tell_me_about" in out, out[-300:]
        # Searched as the topic it is.
        assert 'matches for "the home page of the ipcc"' in out, out[:600]

    @pytest.mark.parametrize(
        ("query", "intent", "expect"),
        [
            # The commands themselves still route, lead-ins included.
            ("summary of Stress", "summary", "the body's response"),
            ("brief Stress", "summary", "the body's response"),
            ("please give me a short summary of Stress", "summary", "Stress"),
            ("show structure of Being", "structure", "Being"),
            ("what sections are in Being", "structure", "Being"),
            ("table of contents for Being", "toc", "Being"),
            ("suggestions for stre", "suggestions", "A/Stress"),
            ("show main page", "main_page", "the body's response"),
            ("show the main page of this archive", "main_page", "the body's"),
            ("list files", "list_files", "intent_sweep.zim"),
        ],
    )
    def test_the_keyword_commands_still_route(
        self,
        handler: SimpleToolsHandler,
        sweep_zim: Path,
        query: str,
        intent: str,
        expect: str,
    ) -> None:
        out = _ask(handler, sweep_zim, query)
        assert f"intent={intent} " in out, out[-300:]
        assert expect in out, out[:600]


# ---------------------------------------------------------------------------
# 5. Turkish dotted İ broke case restoration
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def unindexed_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """No full-text index, so nothing downstream can recover a path the
    parser lowercased — the shape of the wikibooks_be fixture that
    ``_restore_nonascii_case`` was written for."""
    out = tmp_path_factory.mktemp("intent-sweep-unindexed") / "unindexed.zim"
    istanbul = (
        "<html><body><h1>İstanbul</h1><p>İstanbul spans two continents.</p>"
        "<h2 id='tarihce'>Tarihçe</h2>"
        "<p>Byzantion was founded on the Bosphorus.</p></body></html>"
    )
    with Creator(out).config_indexing(False, "eng") as creator:
        creator.add_item(
            _HtmlItem(
                "A/İzmir",
                "İzmir",
                _page("İzmir", "İzmir is a metropolitan city on the Aegean coast."),
            )
        )
        creator.add_item(_HtmlItem("A/İstanbul", "İstanbul", istanbul))
        creator.set_mainpath("A/İzmir")
    return out


class TestDottedCapitalIKeepsTheTypedCase:
    """``İ`` lowercases to ``i`` + U+0307, so the lowercased query is
    longer than the typed one and ``_restore_nonascii_case`` gave up on
    the whole query: ``get article A/İzmir`` looked up ``a/i̇zmir``, which
    an archive without a search index cannot recover."""

    def test_a_path_with_a_dotted_capital_i_is_fetched(
        self, unindexed_zim: Path
    ) -> None:
        out = _ask(_handler_for(unindexed_zim), unindexed_zim, "get article A/İzmir")
        assert "Article not found" not in out, out[:400]
        assert "metropolitan city on the Aegean coast" in out, out[:400]

    def test_every_param_of_the_query_keeps_its_case(self, unindexed_zim: Path) -> None:
        # Two non-ASCII params, and the one holding the İ is mid-query, so
        # the restored slice must be measured without the U+0307 or it
        # takes in the following space.
        out = _ask(
            _handler_for(unindexed_zim),
            unindexed_zim,
            "get article A/İstanbul section Tarihçe",
        )
        assert "Article not found" not in out, out[:400]
        assert "Byzantion was founded on the Bosphorus" in out, out[:400]
