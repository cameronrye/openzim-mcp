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
    # that a two-entity query should land on mention "asthma and" too.
    ("A/Asthma", "Asthma", "Asthma is a long-term disease of the airways."),
    ("A/COPD", "COPD", "In COPD, as in asthma and bronchitis, the airways narrow."),
    (
        "A/Emphysema",
        "Emphysema",
        "Emphysema, like asthma and bronchitis, causes shortness of breath.",
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
