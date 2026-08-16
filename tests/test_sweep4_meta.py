"""Regression tests for the sweep-4 ``_meta`` envelope findings.

Each class pins one verified finding; the docstrings name the failure the
fix closes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp import meta
from openzim_mcp.async_operations import AsyncZimOperations

# The five cl100k_base special-token literals. tiktoken's default
# ``disallowed_special="all"`` raises on each of them.
SPECIAL_LITERALS = [
    "<|endoftext|>",
    "<|endofprompt|>",
    "<|fim_prefix|>",
    "<|fim_middle|>",
    "<|fim_suffix|>",
]


class TestSpecialTokenLiteralsAreOrdinaryText:
    """``_raw_tokens_est`` tokenized with tiktoken's default
    ``disallowed_special="all"``, so any payload containing one of the five
    cl100k_base special-token literals raised ``ValueError`` out of a
    best-effort budgeting helper — hard-failing every dict-returning tool
    whose response or echoed query held the literal.
    """

    @pytest.mark.parametrize("literal", SPECIAL_LITERALS)
    def test_raw_tokens_est_counts_literal_as_text(self, literal: str) -> None:
        assert meta._raw_tokens_est(f"a {literal} b") == 8

    @pytest.mark.parametrize("literal", SPECIAL_LITERALS)
    def test_tokens_est_returns_int_for_literal(self, literal: str) -> None:
        assert meta.tokens_est(f"a {literal} b") == 8

    def test_attach_meta_on_article_body_with_literal(self) -> None:
        payload: Dict[str, Any] = {
            "path": "C/GPT-2",
            "title": "GPT-2",
            "content": (
                "The model uses a special token <|endoftext|> to mark "
                "document boundaries."
            ),
        }
        result = meta.attach_meta(payload)
        assert result["_meta"]["tokens_est"] > 0
        assert result["_meta"]["chars"] > 0

    def test_build_meta_on_echoed_query_with_literal(self) -> None:
        envelope = meta.build_meta(rendered='{"query": "<|endoftext|>"}')
        assert envelope["tokens_est"] > 0

    def test_tokenizer_failure_degrades_to_omitted_estimate(self) -> None:
        """A tokenizer that raises must not fail the tool call — the helper
        reports "couldn't estimate" and ``build_meta`` omits ``tokens_est``.
        """
        broken = MagicMock()
        broken.encode.side_effect = RuntimeError("boom")
        with patch.object(meta, "_get_encoder", return_value=broken):
            assert meta._raw_tokens_est("some text") is None
            assert meta.tokens_est("some text") == 0
            assert "tokens_est" not in meta.build_meta(rendered="some text")


@pytest.fixture
def mock_zim_ops() -> MagicMock:
    """A ``ZimOperations`` shaped well enough for the combined wrappers."""
    ops = MagicMock()
    ops.get_zim_metadata_data.return_value = {
        "entry_count": 10,
        "metadata_entries": {"Name": "wikipedia_en", "Title": "Wikipedia"},
        "uuid": "abc",
        "is_multipart": False,
        "has_fulltext_index": True,
        "has_title_index": True,
        "_meta": {
            "chars": 1053,
            "truncated": False,
            "tokens_est": 376,
            "detected_type": "wikipedia",
            "detection_confidence": "high",
        },
    }
    ops.list_namespaces_data.return_value = {
        "namespaces": {
            "A": {"total": 8, "is_authoritative": True, "description": "articles"},
        },
    }
    ops.list_zim_files_data.return_value = [
        {"name": "wiki.zim", "path": "/data/wiki.zim", "size_bytes": 1_000_000_000},
    ]
    return ops


@pytest.fixture
def async_ops(mock_zim_ops: MagicMock) -> AsyncZimOperations:
    return AsyncZimOperations(mock_zim_ops)


class TestCombinedResponsesCarryMetaEnvelope:
    """``get_archive_metadata_data`` and ``get_health_data`` hand-wrote
    ``"_meta": {}``, so two of the eight advanced tools shipped no
    chars/tokens_est/truncated budget signal — and ``zim_metadata``
    additionally overwrote the archive-type annotations the source
    metadata response had already computed.
    """

    @pytest.mark.asyncio
    async def test_archive_metadata_meta_is_populated(
        self, async_ops: AsyncZimOperations
    ) -> None:
        result = await async_ops.get_archive_metadata_data("/data/wiki.zim")
        envelope = result["_meta"]
        assert envelope["chars"] > 0
        assert envelope["tokens_est"] > 0
        assert envelope["truncated"] is False

    @pytest.mark.asyncio
    async def test_archive_metadata_forwards_type_detection(
        self, async_ops: AsyncZimOperations
    ) -> None:
        result = await async_ops.get_archive_metadata_data("/data/wiki.zim")
        assert result["_meta"]["detected_type"] == "wikipedia"
        assert result["_meta"]["detection_confidence"] == "high"

    @pytest.mark.asyncio
    async def test_archive_metadata_without_type_detection(
        self, async_ops: AsyncZimOperations, mock_zim_ops: MagicMock
    ) -> None:
        """A source response with no detection annotations must not emit
        null-valued ones."""
        mock_zim_ops.get_zim_metadata_data.return_value = {
            "metadata_entries": {"Name": "wiki"},
            "_meta": {"chars": 12, "truncated": False},
        }
        result = await async_ops.get_archive_metadata_data("/data/wiki.zim")
        assert "detected_type" not in result["_meta"]
        assert "detection_confidence" not in result["_meta"]
        assert result["_meta"]["chars"] > 0

    @pytest.mark.asyncio
    async def test_archive_metadata_chars_measure_combined_body(
        self, async_ops: AsyncZimOperations
    ) -> None:
        """``chars`` reflects the combined payload, not the source
        response it was assembled from."""
        result = await async_ops.get_archive_metadata_data("/data/wiki.zim")
        assert result["_meta"]["chars"] != 1053

    @pytest.mark.asyncio
    async def test_health_meta_is_populated(
        self, async_ops: AsyncZimOperations
    ) -> None:
        server = MagicMock()
        with (
            patch(
                "openzim_mcp.server_state._build_health_report",
                return_value={"status": "healthy", "server_name": "test"},
            ),
            patch(
                "openzim_mcp.server_state._build_configuration_report",
                return_value={"configuration": {"server_name": "test"}},
            ),
        ):
            result = await async_ops.get_health_data(server)
        envelope = result["_meta"]
        assert envelope["chars"] > 0
        assert envelope["tokens_est"] > 0
        assert envelope["truncated"] is False

    @pytest.mark.asyncio
    async def test_health_meta_excludes_itself_from_char_count(
        self, async_ops: AsyncZimOperations
    ) -> None:
        """The envelope measures the body it describes; a second attach
        must not grow ``chars`` by the first envelope's own size."""
        server = MagicMock()
        with (
            patch(
                "openzim_mcp.server_state._build_health_report",
                return_value={"status": "healthy"},
            ),
            patch(
                "openzim_mcp.server_state._build_configuration_report",
                return_value={},
            ),
        ):
            first = await async_ops.get_health_data(server)
            second = await async_ops.get_health_data(server)
        assert first["_meta"]["chars"] == second["_meta"]["chars"]

    @pytest.mark.asyncio
    async def test_health_meta_on_a_real_server(self, tmp_path: Path) -> None:
        """End-to-end over the real state builders: the assembled payload
        renders through the tokenizer rather than tripping over a value
        json.dumps can't serialize."""
        from openzim_mcp.config import OpenZimMcpConfig
        from openzim_mcp.server import OpenZimMcpServer

        server = OpenZimMcpServer(OpenZimMcpConfig(allowed_directories=[str(tmp_path)]))
        result = await server.async_zim_operations.get_health_data(server)
        assert result["_meta"]["chars"] > 0
        assert result["_meta"]["tokens_est"] > 0


class TestCombinedResponsesSurviveSpecialLiterals:
    """Cross-check: the combined wrappers now render through the tokenizer,
    so a special-token literal in archive metadata must not fail the call.
    """

    @pytest.mark.asyncio
    async def test_metadata_with_special_literal(
        self, async_ops: AsyncZimOperations, mock_zim_ops: MagicMock
    ) -> None:
        mock_zim_ops.get_zim_metadata_data.return_value = {
            "metadata_entries": {"Description": "docs about <|endoftext|>"},
            "_meta": {},
        }
        result = await async_ops.get_archive_metadata_data("/data/wiki.zim")
        assert result["_meta"]["tokens_est"] > 0


def test_special_literal_set_is_the_one_we_guard_against() -> None:
    """Pins the assumption behind ``SPECIAL_LITERALS``: if cl100k_base ever
    grows a sixth literal, this test names it rather than letting an
    untested code path ship."""
    encoder = meta._get_encoder()
    if encoder is None:  # pragma: no cover — sandboxed env without a BPE cache
        pytest.skip("tokenizer unavailable")
    literals: List[str] = sorted(encoder.special_tokens_set)
    assert literals == sorted(SPECIAL_LITERALS)
