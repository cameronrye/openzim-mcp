"""A rejected namespace must not read as an empty one.

Two v3.3.1 field-report items with the same shape as the report's opening
theme — the server computes the right verdict and loses it on the way out.

**fid 52** — ``walk namespace Q`` on an archive whose namespaces are C, M
and W renders::

    # Namespace `Q` — no entries
    ---
    _End of namespace._
    > ~27 tokens

...which is indistinguishable from a real but empty namespace. The data
layer is not at fault: ``walk_namespace_data`` already stamps
``_meta.reason: "bad_namespace"``, the same code ``browse`` uses and the
same code ``meta.format_footer`` already has recovery prose for. The
compact renderer returns a bare markdown string, so the verdict never
reaches the footer step. ``browse namespace Q`` on the same server does
render "Unknown namespace. Ask for `list namespaces` …".

**fid 80** (audit residue) — ``browse`` distinguishes a namespace that is
in the ZIM spec but not on this archive's iterable surface, stamping
``_meta.reason: "namespace_not_iterable"``. Nothing renders it:
``format_footer`` gates recovery prose on a closed set the code was never
added to, so the model-visible output is byte-identical to a plain empty
page and the deliberate signal is inert.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.meta import format_footer
from openzim_mcp.server import OpenZimMcpServer

_MINI = "wikipedia_en_climate_change_mini_2024-06.zim"


def _server(tmp_path: Path, corpus: Optional[Path], mode: str) -> OpenZimMcpServer:
    if corpus is None:
        pytest.skip("ZIM_TEST_DATA_DIR not set")
    source = corpus / "withns" / _MINI
    if not source.exists():
        pytest.skip(f"{_MINI} not in the corpus")
    solo = tmp_path / mode
    solo.mkdir()
    shutil.copy(source, solo / _MINI)
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(solo)],
            tool_mode=mode,
            cache=CacheConfig(enabled=False),
        )
    )


@pytest.fixture
def simple(tmp_path, zim_test_data_dir) -> Any:
    return (
        _server(tmp_path, zim_test_data_dir, "simple")
        .mcp._tool_manager._tools["zim_query"]
        .fn
    )


@pytest.fixture
def advanced(tmp_path, zim_test_data_dir) -> Any:
    return (
        _server(tmp_path, zim_test_data_dir, "advanced")
        .mcp._tool_manager._tools["zim_query"]
        .fn
    )


# ---------------------------------------------------------------------------
# fid 52 — walk must not report a rejection as an empty page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_walking_an_unknown_namespace_says_it_is_unknown(simple):
    out = await simple(query="walk namespace Q")

    assert "Unknown namespace" in out, out
    # Positive: the recovery is one the simple-mode parser actually accepts.
    assert "list namespaces" in out, out
    # Negative: the token-budget footer is what shipped instead.
    assert "~27 tokens" not in out, out


@pytest.mark.asyncio
async def test_the_advice_matches_the_tools_the_caller_has(advanced):
    """Same verdict, advanced vocabulary — the mode-aware split the footer
    already implements for every other reason code."""
    out = await advanced(query="walk namespace Q")

    assert "Unknown namespace" in out, out
    assert "zim_metadata" in out, out
    assert "list namespaces" not in out, out


@pytest.mark.asyncio
async def test_walk_and_browse_now_agree_about_the_same_namespace(simple):
    """fid 52's core complaint: two ways of asking, two different answers."""
    walked = await simple(query="walk namespace Q")
    browsed = await simple(query="browse namespace Q")

    assert "Unknown namespace" in browsed, browsed
    assert "Unknown namespace" in walked, walked


@pytest.mark.asyncio
async def test_a_real_namespace_is_not_labelled_unknown(simple):
    """Control. ``C`` exists on this archive and holds entries; a fix that
    tagged every walk as a rejection would satisfy the tests above."""
    out = await simple(query="walk namespace C")

    assert "Unknown namespace" not in out, out
    assert "- " in out, "expected entry bullets on a populated namespace"


@pytest.mark.asyncio
async def test_a_shape_error_is_still_a_shape_error(simple):
    """Control on the other side: ``walk namespace 9`` was already rejected
    for its token shape, before any archive lookup. That path must not be
    rerouted into the softer namespace verdict."""
    out = await simple(query="walk namespace 9")

    assert "Unknown namespace" not in out, out
    assert "namespace" in out.lower(), out


# ---------------------------------------------------------------------------
# fid 80 — the not-iterable verdict has to render as something
# ---------------------------------------------------------------------------


def test_the_not_iterable_verdict_reaches_the_reader():
    """``browse`` stamps this deliberately; ``format_footer`` dropped it.

    Driven through the real footer renderer with the real reason string,
    against the plain token-budget line it used to fall through to.
    """
    inert = format_footer({"tokens_est": 60}, footer_enabled=True)
    rendered = format_footer(
        {"tokens_est": 60, "reason": "namespace_not_iterable"},
        footer_enabled=True,
    )

    assert rendered != inert, (
        "reason='namespace_not_iterable' renders identically to no reason "
        f"at all: {rendered!r}"
    )
    assert "walk" in rendered.lower(), rendered


def test_the_not_iterable_advice_is_mode_aware():
    """Every other reason code in this set names a tool the caller has."""
    simple_advice = format_footer(
        {"reason": "namespace_not_iterable"}, footer_enabled=True, tool_mode="simple"
    )
    advanced_advice = format_footer(
        {"reason": "namespace_not_iterable"}, footer_enabled=True, tool_mode="advanced"
    )

    assert "zim_browse" not in simple_advice, simple_advice
    assert "zim_browse" in advanced_advice, advanced_advice


def test_not_iterable_and_bad_namespace_do_not_say_the_same_thing():
    """The two codes exist precisely to separate "nothing there" from
    "nothing reachable this way". Collapsing them would render the
    distinction the data layer computes pointless."""
    not_iterable = format_footer(
        {"reason": "namespace_not_iterable"}, footer_enabled=True
    )
    bad = format_footer({"reason": "bad_namespace"}, footer_enabled=True)

    assert not_iterable != bad, not_iterable
