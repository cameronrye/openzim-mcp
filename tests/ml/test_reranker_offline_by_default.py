"""The reranker must not dial out unless an operator asked it to.

The MCP ``instructions`` payload tells callers this server is retrieval
from local archives, and ``docs/roadmap.md`` states the project is
offline-first ("models load from disk"). Before ``allow_model_download``
existed, a cold FastEmbed cache made the *first* rerank-eligible
``zim_query`` call open connections to huggingface.co and stall for up
to ``first_call_timeout_seconds`` before falling back to Xapian — a
1.1 GB fetch that no caller consented to and that the shipped
instructions denied could happen.

These tests pin the whole contract: the default is offline, the flag
reaches FastEmbed, the escape hatch (`openzim-mcp download-models`)
still downloads, and the instructions no longer make the absolute
never-network claim that this behaviour used to falsify.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, Iterator, List

import pytest

from openzim_mcp.config import RerankerConfig
from openzim_mcp.instructions import ADVANCED_INSTRUCTIONS, SIMPLE_INSTRUCTIONS
from openzim_mcp.ml.fallback import reset_kill_switches
from openzim_mcp.ml.reranker import BGEReranker, _load_model


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    BGEReranker.reset_instance()
    reset_kill_switches()
    yield
    BGEReranker.reset_instance()
    reset_kill_switches()


@pytest.fixture
def no_egress(monkeypatch: pytest.MonkeyPatch) -> List[Any]:
    """Record and refuse every outbound TCP connect.

    Asserting on a recorded list rather than on wall-clock or on a
    firewall makes the test deterministic on a developer machine that
    *does* have a warm cache and *does* have network.
    """
    attempts: List[Any] = []

    def _blocked(address: Any, *args: Any, **kwargs: Any) -> Any:
        attempts.append(address)
        raise OSError("test guard: no outbound connections allowed")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(
        socket.socket,
        "connect",
        lambda self, address, *a, **k: _blocked(address),
    )
    return attempts


def test_reranker_config_defaults_to_no_model_download() -> None:
    """Pin the default itself: this is the whole user-visible contract."""
    assert RerankerConfig().allow_model_download is False


@pytest.mark.requires_reranker
def test_cold_cache_load_makes_no_outbound_connection(
    tmp_path: Path, no_egress: List[Any]
) -> None:
    """A guaranteed-cold cache under the default config must fail fast to
    Xapian-only ranking instead of fetching the model from HuggingFace."""
    cfg = RerankerConfig(cache_dir=tmp_path)
    assert cfg.allow_model_download is False

    assert BGEReranker.get(cfg) is None, "expected graceful Xapian fallback"
    assert no_egress == [], f"reranker dialled out: {no_egress}"


@pytest.mark.requires_reranker
def test_load_model_translates_the_flag_for_fastembed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assert on the kwarg, not on behaviour.

    ``local_files_only`` is the portable switch: FastEmbed has accepted it
    since 0.4.0, our declared floor, whereas ``HF_HUB_OFFLINE`` is only
    honoured by later releases inside the same ``>=0.4.0,<1.0`` range and
    would silently no-op for anyone the lockfile does not pin.
    """
    import fastembed.rerank.cross_encoder as ce

    seen: dict[str, Any] = {}

    class _FakeCrossEncoder:
        def __init__(self, **kwargs: Any) -> None:
            seen.clear()
            seen.update(kwargs)

    monkeypatch.setattr(ce, "TextCrossEncoder", _FakeCrossEncoder)

    _load_model("BAAI/bge-reranker-base", None, allow_download=False)
    assert seen["local_files_only"] is True

    _load_model("BAAI/bge-reranker-base", None, allow_download=True)
    assert seen["local_files_only"] is False


@pytest.mark.requires_reranker
def test_runtime_load_honours_the_config_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loader thread must read the operator's config, not a hardcoded
    default — otherwise the flag exists but changes nothing at runtime."""
    seen: List[bool] = []

    def _fake_load(model_id: str, cache_dir: Any, *, allow_download: bool) -> Any:
        seen.append(allow_download)
        raise RuntimeError("stop before touching fastembed")

    monkeypatch.setattr("openzim_mcp.ml.reranker._load_model", _fake_load)

    BGEReranker.get(RerankerConfig())
    BGEReranker.reset_instance()
    BGEReranker.get(RerankerConfig(allow_model_download=True))

    assert seen == [False, True]


@pytest.mark.requires_reranker
def test_download_models_cli_still_downloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-stage command is the escape hatch the fallback message
    names. If it inherited the offline default it would be inert and the
    advice would be a dead end."""
    from openzim_mcp.ml.cli import download as download_cli

    seen: List[bool] = []

    def _fake_load(model_id: str, cache_dir: Any, **kwargs: Any) -> Any:
        seen.append(bool(kwargs.get("allow_download", True)))
        return object()

    monkeypatch.setattr("openzim_mcp.ml.reranker._load_model", _fake_load)

    download_cli._stage_reranker(RerankerConfig())

    assert seen == [True]


@pytest.mark.requires_reranker
def test_synthesize_rerank_path_makes_no_outbound_connection(
    tmp_path: Path, no_egress: List[Any]
) -> None:
    """`zim_query(synthesize=True)` is where the egress was first noticed;
    pin that it inherits the offline default rather than carrying its own."""
    from openzim_mcp.synthesize import _maybe_rerank_synthesize_passages

    passages: List[Any] = [
        {
            "cite_id": "wiki/A/Aspirin",
            "text_markdown": "Aspirin is a salicylate drug.",
            "rank": 1,
            "score": 0.9,
        },
        {
            "cite_id": "wiki/A/Cat",
            "text_markdown": "The cat is a domestic species.",
            "rank": 2,
            "score": 0.4,
        },
    ]
    hit_keys = [("wiki", "A/Aspirin"), ("wiki", "A/Cat")]

    out_passages, out_keys = _maybe_rerank_synthesize_passages(
        passages,
        hit_keys,
        query="what is aspirin used for",
        top_hits=[],
        reranker_config=RerankerConfig(cache_dir=tmp_path),
    )

    assert out_passages == passages
    assert out_keys == hit_keys
    assert no_egress == [], f"synthesize path dialled out: {no_egress}"


def test_instructions_do_not_promise_absolute_network_isolation() -> None:
    """The [reranker] extra can still fetch a model when an operator opts
    in, so the shipped instructions must not claim the tools *never* reach
    the network. This guard stops the absolute phrasing coming back."""
    for text in (ADVANCED_INSTRUCTIONS, SIMPLE_INSTRUCTIONS):
        assert "never reach" not in text
        assert "never reaches" not in text
