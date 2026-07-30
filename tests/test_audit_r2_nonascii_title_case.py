"""Regression tests: non-ASCII casing must survive intent parsing.

Tier 1 Rule 1 (``_normalize_topic_case``) lowercases the query before
param extraction, so extracted titles arrive lowercased. For ASCII
titles downstream repair recovers (Xapian title probes, case-variant
path ladders), but non-Latin scripts have no such rescue: on archives
without a title index, ``get article Індыйская кухня`` degraded to
"Article not found" because the extracted entry_path was irreversibly
lowercased to ``індыйская кухня`` while the archive stores
``A/Індыйская_кухня.html``. ``zim_search`` on the identical string
found the article, making the asymmetry a silent wrong answer.

Fix: ``parse_intent`` re-cases non-ASCII string params from the
pre-rewrite query (same recovery ``_recase_from_original`` uses for
guidance text). ASCII params keep Rule 1's lowercase contract.
"""

from pathlib import Path
from typing import Dict, Optional

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.security import PathValidator
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.zim_operations import ZimOperations


class TestParseIntentPreservesNonAsciiCase:
    """Non-ASCII params must keep the caller's typed casing."""

    def test_get_article_cyrillic_title_keeps_typed_case(self) -> None:
        intent, params, _ = IntentParser.parse_intent(
            "get article Індыйская кухня", title_probe=None
        )
        assert intent == "get_article"
        assert params["entry_path"] == "Індыйская кухня"

    def test_get_section_cyrillic_entry_path_keeps_typed_case(self) -> None:
        intent, params, _ = IntentParser.parse_intent(
            "get section ad of Эспэранта/Суфіксы", title_probe=None
        )
        assert intent == "get_section"
        assert params["entry_path"] == "Эспэранта/Суфіксы"

    def test_lowercase_typed_cyrillic_passes_through(self) -> None:
        intent, params, _ = IntentParser.parse_intent(
            "get article індыйская кухня", title_probe=None
        )
        assert intent == "get_article"
        assert params["entry_path"] == "індыйская кухня"

    def test_ascii_entry_path_keeps_rule1_lowercase_contract(self) -> None:
        # Sub-D-2 Rule 1 still lowercases ASCII titles — downstream
        # title probes and case ladders recover those.
        intent, params, _ = IntentParser.parse_intent(
            "get article United States", title_probe=None
        )
        assert intent == "get_article"
        assert params["entry_path"] == "united states"

    def test_mixed_script_title_keeps_typed_case(self) -> None:
        intent, params, _ = IntentParser.parse_intent(
            "get article Über die Alpen", title_probe=None
        )
        assert intent == "get_article"
        assert params["entry_path"] == "Über die Alpen"


class TestZimQueryResolvesNonAsciiTitleOnUnindexedArchive:
    """End-to-end: zim_query must resolve a correctly-typed Cyrillic
    title on an archive without a title index (wikibooks_be has none),
    matching what zim_search already finds for the identical string."""

    @pytest.fixture
    def wikibooks_zim(self, real_content_zim_files: Dict[str, Optional[Path]]) -> Path:
        zim = real_content_zim_files.get("wikibooks")
        if zim is None:
            pytest.skip("wikibooks ZIM fixture not available")
        return zim

    @pytest.fixture
    def handler(self, wikibooks_zim: Path) -> SimpleToolsHandler:
        cfg = OpenZimMcpConfig(
            allowed_directories=[str(wikibooks_zim.parent.parent)],
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

    def test_get_article_with_typed_cyrillic_case_resolves(
        self, handler: SimpleToolsHandler, wikibooks_zim: Path
    ) -> None:
        result = handler.handle_zim_query(
            "get article Індыйская кухня", str(wikibooks_zim)
        )
        assert isinstance(result, str)
        assert "Article not found" not in result, result[:500]
        assert "Індыйская" in result
