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
from typing import Any, Dict


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


def call_tool(
    proc: subprocess.Popen, msg_id: int, tool: str, **args: Any
) -> Dict[str, Any]:
    """Issue a generic ``tools/call`` and return the structured ``result`` block."""
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
    return resp.get("result", {})
