"""Shared stdio MCP subprocess helpers for live tests.

Both ``test_live_canonical_queries.py`` and ``test_live_phase_c_primitives.py``
spawn an openzim-mcp stdio subprocess and exchange JSON-RPC messages with it.
The bookkeeping (send, recv, spawn, initialize, shutdown) is identical in
both — kept here in one place to avoid drift.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def send_msg(proc: subprocess.Popen, msg: Dict[str, Any]) -> None:
    """Write a JSON-RPC message to the child's stdin."""
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def recv_until(proc: subprocess.Popen, msg_id: int) -> Dict[str, Any]:
    """Read JSON-RPC frames from the child until one matches ``msg_id``."""
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


def spawn_stdio(zim_dir: Path) -> subprocess.Popen:
    """Launch ``openzim-mcp`` in advanced/stdio mode, pipes attached."""
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
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
    )


def initialize(proc: subprocess.Popen, *, client_name: str = "live-test") -> None:
    """Drive the MCP ``initialize`` handshake to completion."""
    send_msg(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": "0"},
            },
        },
    )
    recv_until(proc, 0)
    send_msg(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})


def shutdown(proc: subprocess.Popen) -> None:
    """Best-effort teardown: close stdin, then wait/terminate; close streams."""
    try:
        if proc.stdin is not None:
            with contextlib.suppress(Exception):
                proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=3)
    finally:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()


def structured(result: Dict[str, Any]) -> Dict[str, Any]:
    """Unwrap a tool payload from either envelope slot.

    No tool advertises an ``outputSchema``, so nothing arrives in
    ``structuredContent`` and every payload is JSON in a text block (see
    ``openzim_mcp.tool_schemas``). Reading only ``structuredContent``
    silently yields ``{}``, which turns every downstream assertion into a
    comparison against an empty dict rather than a failure anyone can read.
    """
    inner = result.get("structuredContent")
    if isinstance(inner, dict) and inner:
        unwrapped = inner.get("result", inner)
        return unwrapped if isinstance(unwrapped, dict) else {}
    for block in result.get("content") or []:
        text = block.get("text") if isinstance(block, dict) else None
        if not isinstance(text, str):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            unwrapped = parsed.get("result", parsed)
            return unwrapped if isinstance(unwrapped, dict) else parsed
    return {}


def dispatch_failure(result: Dict[str, Any]) -> Optional[str]:
    """Return the message when ``result`` is a dispatch-level failure.

    Two different things arrive as ``isError``. A *domain* error — no such
    entry, unknown section id — carries a JSON ``ToolErrorPayload`` body
    that callers are meant to inspect and sometimes tolerate. A *dispatch*
    failure — a tool name the server does not serve, an argument its schema
    rejects — carries a bare string instead.

    The distinction matters because these tests funnel an unparseable
    payload into ``pytest.skip``. Without it a renamed tool reads as "this
    archive lacks the data", so the module keeps reporting green while
    testing nothing: exactly how ``get_section``/``walk_namespace`` went on
    being called for a whole release after the surface became ``zim_*``.
    """
    if not result.get("isError"):
        return None
    if structured(result):
        return None
    for block in result.get("content") or []:
        text = block.get("text") if isinstance(block, dict) else None
        if isinstance(text, str) and text.strip():
            return text
    return "tool call failed with an empty error body"


def call_tool(
    proc: subprocess.Popen, msg_id: int, tool: str, **args: Any
) -> Dict[str, Any]:
    """Issue a generic ``tools/call`` and return the structured ``result`` block.

    Raises ``AssertionError`` on a dispatch failure so a stale tool name
    fails loudly here instead of being mistaken for missing archive data
    further down. Domain errors pass through untouched.
    """
    send_msg(
        proc,
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        },
    )
    resp = recv_until(proc, msg_id)
    if "error" in resp and "result" not in resp:
        raise AssertionError(
            f"tools/call {tool!r} failed at the protocol level: {resp['error']}"
        )
    result = resp.get("result", {})
    failure = dispatch_failure(result)
    if failure is not None:
        raise AssertionError(f"tools/call {tool!r} was not dispatched: {failure}")
    return result
