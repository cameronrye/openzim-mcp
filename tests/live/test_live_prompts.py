"""Live MCP-prompts test over stdio JSON-RPC.

Covers v1.0 item 7: ``/research``, ``/summarize``, ``/explore`` MCP prompts
including the v1.0 sanitization fixes (control-char stripping, length cap,
empty-arg ask-for-input fallback).
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import pytest

pytestmark = pytest.mark.live


def _send(proc: subprocess.Popen, msg: Dict[str, Any]) -> None:
    """Write a single JSON-RPC line to the server's stdin."""
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def _recv_until(proc: subprocess.Popen, msg_id: int) -> Dict[str, Any]:
    """Read JSON-RPC lines until we see one with the matching id."""
    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("server stdout closed unexpectedly")
        try:
            resp = json.loads(line)
        except json.JSONDecodeError:
            continue
        if resp.get("id") == msg_id:
            return resp


@pytest.fixture
def stdio_session(zim_dir: Path) -> Iterator[subprocess.Popen]:
    """Spawn ``openzim-mcp --transport stdio`` and complete MCP initialize."""
    cmd = [
        sys.executable,
        "-m",
        "openzim_mcp",
        "--mode",
        "advanced",
        "--transport",
        "stdio",
        str(zim_dir),
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
    )
    try:
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "live-prompts-test", "version": "0"},
                },
            },
        )
        init_resp = _recv_until(proc, 0)
        assert "result" in init_resp, f"initialize failed: {init_resp!r}"
        # Notify initialized (no id, no response).
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        # Close pipe handles explicitly — Popen leaves them open and the
        # GC-time close raises ResourceWarning under -W error.
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()


def _get_prompt(
    proc: subprocess.Popen, msg_id: int, name: str, arguments: Optional[Dict] = None
) -> str:
    """Issue ``prompts/get`` and return the assembled prompt body text."""
    _send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "prompts/get",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )
    resp = _recv_until(proc, msg_id)
    assert "result" in resp, f"prompts/get failed: {resp!r}"
    return resp["result"]["messages"][0]["content"]["text"]


def test_prompts_list_advertises_three_prompts(stdio_session) -> None:
    """``prompts/list`` returns the three named v1.0 prompts."""
    _send(stdio_session, {"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})
    resp = _recv_until(stdio_session, 1)
    names = sorted(p["name"] for p in resp["result"]["prompts"])
    assert names == ["explore", "research", "summarize"]


def test_research_prompt_interpolates_topic(stdio_session) -> None:
    """``research`` prompt body interpolates the ``topic`` argument."""
    body = _get_prompt(stdio_session, 2, "research", {"topic": "Aristotle"})
    assert "Aristotle" in body
    # Should mention search_all and get_entry_summary as part of the workflow.
    assert "search_all" in body
    assert "get_entry_summary" in body


def test_summarize_prompt_interpolates_paths(stdio_session, zim_dir) -> None:
    """``summarize`` prompt interpolates both file and entry path."""
    zims = sorted(zim_dir.glob("*.zim"))
    assert zims, "no ZIMs available for summarize test"
    body = _get_prompt(
        stdio_session,
        3,
        "summarize",
        {"zim_file_path": str(zims[0]), "entry_path": "iep.utm.edu/plato/"},
    )
    assert "iep.utm.edu/plato/" in body
    assert str(zims[0]) in body


def test_explore_prompt_interpolates_zim_file(stdio_session, zim_dir) -> None:
    """``explore`` prompt interpolates the ``zim_file_path`` argument."""
    zims = sorted(zim_dir.glob("*.zim"))
    body = _get_prompt(stdio_session, 4, "explore", {"zim_file_path": str(zims[0])})
    assert str(zims[0]) in body
    assert "get_zim_metadata" in body


def test_research_strips_control_chars(stdio_session) -> None:
    """v1.0 fix: control chars (BEL, NUL) must be stripped from interpolated args."""
    evil = "Aristotle\x07\x00"
    body = _get_prompt(stdio_session, 5, "research", {"topic": evil})
    assert "\x07" not in body and "\x00" not in body


def test_research_empty_topic_asks_for_input(stdio_session) -> None:
    """Empty ``topic`` returns the ask-for-input fallback, not a workflow."""
    body = _get_prompt(stdio_session, 6, "research", {"topic": ""})
    # The ask-for-input fallback should not contain a tool-call workflow.
    assert "search_all" not in body
    # Should mention the prompt name so user knows what to provide.
    assert "research" in body.lower()


def test_research_long_topic_truncated(stdio_session) -> None:
    """Inputs are capped to prevent prompt-injection via huge payloads."""
    huge = "x" * 10_000
    body = _get_prompt(stdio_session, 7, "research", {"topic": huge})
    # The interpolated portion of the body should be far smaller than 10k.
    # (Exact cap is implementation detail; assert it's bounded.)
    assert body.count("x") < 5_000, f"topic not truncated: {body.count('x')} 'x's"
