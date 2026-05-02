"""Live cache-persistence test across a server restart.

Covers v1.0 item 5: with ``cache.persistence_enabled=True`` and
``cache.persistence_path=<dir>``, cache entries written by one process
must be loaded back on the next process's startup.

Uses two stdio subprocesses sharing one persistence directory: the
first populates the cache via real tool calls, the second verifies the
entries survive across the kill/respawn boundary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

pytestmark = pytest.mark.live


def _send(proc: subprocess.Popen, msg: Dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def _recv_until(proc: subprocess.Popen, msg_id: int) -> Dict[str, Any]:
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


def _spawn_stdio(zim_dir: Path, env: Dict[str, str]) -> subprocess.Popen:
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
        env=env,
    )


def _initialize(proc: subprocess.Popen) -> None:
    _send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "cache-persistence-test", "version": "0"},
            },
        },
    )
    _recv_until(proc, 0)
    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})


def _call_tool(
    proc: subprocess.Popen, msg_id: int, name: str, args: Dict
) -> Dict[str, Any]:
    _send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        },
    )
    return _recv_until(proc, msg_id)


def _server_health(proc: subprocess.Popen, msg_id: int) -> Dict[str, Any]:
    resp = _call_tool(proc, msg_id, "get_server_health", {})
    text = resp["result"]["content"][0]["text"]
    # The health tool wraps its JSON in a "result" string field.
    parsed_outer = json.loads(text)
    inner = parsed_outer.get("result", text)
    return json.loads(inner) if isinstance(inner, str) else inner


def test_cache_persistence_survives_restart(zim_dir: Path, tmp_path: Path) -> None:
    """Cache entries persisted by run #1 must reload on run #2's startup."""
    # The cache appends .json to the configured path, so pass a basename
    # without an extension and look for "<base>.json" after shutdown.
    persistence_base = tmp_path / "oz-cache"
    persistence_file = persistence_base.with_suffix(".json")

    env = os.environ.copy()
    env["OPENZIM_MCP_CACHE__PERSISTENCE_ENABLED"] = "true"
    env["OPENZIM_MCP_CACHE__PERSISTENCE_PATH"] = str(persistence_base)

    zims = sorted(zim_dir.glob("*.zim"))
    assert zims, "need at least one .zim"
    target = str(zims[0])

    # ---- run #1: populate the cache ----
    proc1 = _spawn_stdio(zim_dir, env)
    try:
        _initialize(proc1)
        # A few real, cacheable tool calls.
        _call_tool(proc1, 1, "list_namespaces", {"zim_file_path": target})
        _call_tool(
            proc1,
            2,
            "search_zim_file",
            {"zim_file_path": target, "query": "philosophy", "limit": 3},
        )
        _call_tool(proc1, 3, "get_zim_metadata", {"zim_file_path": target})
        health1 = _server_health(proc1, 4)
        cache1 = health1["cache_performance"]
        assert cache1["enabled"] is True
        assert cache1["persistence_enabled"] is True
        assert cache1["size"] > 0, f"cache should have entries: {cache1!r}"
        size_before = cache1["size"]
    finally:
        # Close stdin to trigger graceful shutdown so atexit-registered
        # cache-persistence flush actually runs. SIGTERM bypasses atexit.
        if proc1.stdin is not None:
            proc1.stdin.close()
        try:
            proc1.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc1.terminate()
            try:
                proc1.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc1.kill()

    # Persistence flush happens on graceful shutdown.
    assert persistence_file.exists(), (
        f"expected persisted cache at {persistence_file} after server #1 "
        f"shutdown; tmp_path contains: {sorted(tmp_path.iterdir())}"
    )
    assert persistence_file.stat().st_size > 0, "persisted cache file is empty"

    # ---- run #2: same persistence path, expect cache pre-populated ----
    proc2 = _spawn_stdio(zim_dir, env)
    try:
        _initialize(proc2)
        health2 = _server_health(proc2, 1)
        cache2 = health2["cache_performance"]
        assert cache2["persistence_enabled"] is True
        # The exact size may differ slightly (TTL eviction during reload), but
        # it must be > 0 to demonstrate the persisted entries were loaded.
        assert cache2["size"] > 0, (
            f"after restart, cache should be pre-populated from "
            f"{persistence_file}; got: {cache2!r}"
        )
        # Reasonable expectation: most of the entries from run #1 survive.
        assert cache2["size"] >= max(
            1, size_before // 2
        ), f"reload lost too many entries: had {size_before}, got {cache2['size']}"
    finally:
        proc2.terminate()
        try:
            proc2.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc2.kill()
