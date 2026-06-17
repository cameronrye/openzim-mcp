#!/usr/bin/env python3
"""Build the OpenZIM MCP MCPB (``.mcpb``) bundle for Smithery / Claude Desktop.

A ``.mcpb`` is a zip with ``manifest.json`` at its root (the format formerly
called ``.dxt``). This script assembles a *self-describing* bundle:

  1. Reads the single-source version from ``pyproject.toml`` and stamps it into
     the manifest (both the top-level ``version`` and the ``uvx openzim-mcp@<v>``
     launch argument), so the bundle can never drift from the released package.
  2. Captures the **live** tool schemas — it spawns the server in ``advanced``
     mode over stdio, calls ``tools/list``, and writes each tool's
     ``name``/``description``/``inputSchema``/``outputSchema`` into the
     manifest's ``tools`` array. These are the schemas Smithery and Glama score
     listings on.
  3. Packs a **plain zip** — deliberately NOT ``mcpb pack``. The MCPB manifest
     schema only allows ``{name, description}`` per tool, so ``mcpb pack``/
     ``mcpb validate`` strip the ``inputSchema``/``outputSchema`` keys. A
     ``.mcpb`` is just a zip, so plain-zipping preserves the rich schemas.

The bundle is a uvx *launcher* (``command: uvx``, ``args: openzim-mcp@<v> ...``)
rather than a vendored environment: ``uvx`` resolves the platform-correct native
``libzim`` wheel from PyPI at run time, keeping one cross-platform bundle far
under the registry's 25 MB cap. The trade-off is that the host needs ``uv``.

Usage:
    uv run python scripts/build_mcpb.py [--output DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - spawns this project's own server, fixed argv
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST_TEMPLATE = REPO / "packaging" / "mcpb" / "manifest.json"
BUNDLE_SRC = REPO / "packaging" / "mcpb"
PYPI_NAME = "openzim-mcp"

# The advanced surface registers exactly these tools (see
# ``openzim_mcp/tools/__init__.py``). The bundle ships ``advanced`` mode, so a
# correct build must capture all of them. ``tests/test_mcpb_distribution.py``
# pins this against the live server, so adding/removing a tool fails CI here.
EXPECTED_TOOL_COUNT = 8

# Variable substitution the host (Claude Desktop / Smithery) performs at launch.
HANDSHAKE_TIMEOUT_S = 120


def package_version() -> str:
    """Single source of truth: ``[project].version`` in pyproject.toml."""
    with (REPO / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def capture_tools(timeout_s: int = HANDSHAKE_TIMEOUT_S) -> list[dict]:
    """Spawn the server in advanced mode and return its live ``tools/list``.

    Returns each tool verbatim from the MCP SDK (``name``, ``description``,
    ``inputSchema``, and ``outputSchema`` when present) so the manifest carries
    the exact JSON Schemas Smithery scores.
    """
    with tempfile.TemporaryDirectory(prefix="openzim_mcp_build_") as zim_dir:
        env = {
            **os.environ,
            "OPENZIM_MCP_TOOL_MODE": "advanced",
            "LOG_LEVEL": "error",
        }
        proc = subprocess.Popen(  # nosec B603 - sys.executable + fixed module
            [sys.executable, "-m", "openzim_mcp", zim_dir],
            cwd=REPO,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            tools = _handshake_list_tools(proc, timeout_s)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    if len(tools) != EXPECTED_TOOL_COUNT:
        names = sorted(t.get("name", "?") for t in tools)
        raise SystemExit(
            f"build_mcpb: expected {EXPECTED_TOOL_COUNT} tools in advanced mode, "
            f"captured {len(tools)}: {names}. A tool registration regression must "
            f"break the build, not ship a short/wrong manifest."
        )
    return tools


def _handshake_list_tools(proc: subprocess.Popen, timeout_s: int) -> list[dict]:
    """Minimal MCP stdio handshake: initialize -> initialized -> tools/list."""
    import select

    def send(obj: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def read_id(target_id: int) -> dict:
        assert proc.stdout is not None
        deadline = _monotonic() + timeout_s
        while True:
            remaining = deadline - _monotonic()
            if remaining <= 0:
                raise SystemExit(f"build_mcpb: timed out waiting for id={target_id}")
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                continue
            line = proc.stdout.readline()
            if not line:
                err = proc.stderr.read() if proc.stderr else ""
                raise SystemExit(
                    f"build_mcpb: server exited before id={target_id}\n{err[-2000:]}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip any non-JSON log noise on stdout
            if msg.get("id") == target_id:
                return msg

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "build_mcpb", "version": "0"},
            },
        }
    )
    read_id(1)
    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    resp = read_id(2)
    return resp.get("result", {}).get("tools", [])


def _monotonic() -> float:
    import time

    return time.monotonic()


def build_manifest(version: str, tools: list[dict]) -> dict:
    """Stamp the version + launch arg and inject the captured tool schemas."""
    manifest = json.loads(MANIFEST_TEMPLATE.read_text(encoding="utf-8"))
    manifest["version"] = version
    manifest["server"]["mcp_config"]["args"] = [
        f"{PYPI_NAME}@{version}",
        "${user_config.allowed_directories}",
    ]
    manifest["tools"] = tools
    return manifest


def pack(manifest: dict, output: Path) -> Path:
    """Write a plain zip with manifest.json at the root + the server shim.

    Plain zip (not ``mcpb pack``) preserves the ``inputSchema``/``outputSchema``
    keys in ``tools`` that ``mcpb validate`` would reject.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        for path in sorted((BUNDLE_SRC / "server").rglob("*")):
            if path.is_file():
                zf.write(path, str(path.relative_to(BUNDLE_SRC)))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the OpenZIM MCP .mcpb bundle")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "dist",
        help="Output directory for the .mcpb (default: ./dist)",
    )
    args = parser.parse_args()

    version = package_version()
    print(f"build_mcpb: version {version} (from pyproject.toml)")
    print("build_mcpb: capturing live tool schemas (advanced mode)...")
    tools = capture_tools()
    print(f"build_mcpb: captured {len(tools)} tools: {[t['name'] for t in tools]}")

    manifest = build_manifest(version, tools)
    output = args.output / f"{PYPI_NAME}-{version}.mcpb"
    pack(manifest, output)
    size_kb = output.stat().st_size / 1024
    print(f"build_mcpb: wrote {output} ({size_kb:.1f} KB)")
    print(
        f"build_mcpb: publish with -> smithery mcp publish {output} -n rye/openzim-mcp"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
