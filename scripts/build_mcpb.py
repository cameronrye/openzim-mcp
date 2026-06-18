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
import hashlib
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

# Max seconds for the whole tool-capture handshake (initialize + tools/list).
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
    if sys.platform == "win32":
        # The handshake below waits on the server's stdout via select(), which
        # on Windows accepts sockets only — not pipe handles — and raises
        # WinError 10038. Fail fast with a clear message. The *bundle* this
        # script produces is still cross-platform (it just launches uvx); only
        # this build host must be POSIX.
        raise SystemExit(
            "build_mcpb: build host must be macOS/Linux — the stdio tool-capture "
            "handshake uses select() on a pipe, which is unsupported on Windows. "
            "The produced .mcpb bundle is itself cross-platform."
        )
    with tempfile.TemporaryDirectory(prefix="openzim_mcp_build_") as zim_dir:
        env = {
            **os.environ,
            "OPENZIM_MCP_TOOL_MODE": "advanced",
            # Quiet the server's stderr during capture. The level is read from
            # OPENZIM_MCP_LOGGING__LEVEL (env_prefix OPENZIM_MCP_, nested
            # delimiter __); a bare LOG_LEVEL is silently ignored.
            "OPENZIM_MCP_LOGGING__LEVEL": "ERROR",
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
                # communicate() drains stdout/stderr while waiting, so the child
                # can't wedge on a full pipe during shutdown.
                proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()

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

    # One shared budget for the whole handshake, so initialize + tools/list
    # together are bounded by HANDSHAKE_TIMEOUT_S (not 2x it).
    deadline = _monotonic() + timeout_s

    def send(obj: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def read_id(target_id: int) -> dict:
        assert proc.stdout is not None
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


def _fixed_date_time() -> tuple[int, int, int, int, int, int]:
    """A constant zip entry timestamp so two builds of one commit match byte-for-byte.

    Honors ``SOURCE_DATE_EPOCH`` when set, else the zip epoch (1980-01-01).
    Without this, ``writestr`` stamps wall-clock time and ``write`` inherits the
    file mtime, both of which vary between builds and break hash verification.
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        import time

        return time.gmtime(int(epoch))[:6]  # type: ignore[return-value]
    return (1980, 1, 1, 0, 0, 0)


def _add_entry(zf: zipfile.ZipFile, arcname: str, data: bytes, date_time) -> None:
    """Add one file with a pinned timestamp + mode, for a reproducible archive."""
    info = zipfile.ZipInfo(arcname, date_time=date_time)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16  # -rw-r--r--
    zf.writestr(info, data)


def pack(manifest: dict, output: Path) -> Path:
    """Write a plain zip with manifest.json at the root + the server shim.

    Plain zip (not ``mcpb pack``) preserves the ``inputSchema``/``outputSchema``
    keys in ``tools`` that ``mcpb validate`` would reject. Every entry is stamped
    with a fixed timestamp/mode (see ``_fixed_date_time``) so rebuilding the same
    commit yields a byte-identical ``.mcpb``.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    date_time = _fixed_date_time()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        _add_entry(zf, "manifest.json", manifest_bytes, date_time)
        for path in sorted((BUNDLE_SRC / "server").rglob("*")):
            if path.is_file():
                arcname = str(path.relative_to(BUNDLE_SRC))
                _add_entry(zf, arcname, path.read_bytes(), date_time)
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

    # Emit a `shasum -a 256 -c`-compatible sidecar so a release downloader can
    # verify the asset they fetched matches what CI built.
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_name(output.name + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n", encoding="utf-8")

    print(f"build_mcpb: wrote {output} ({size_kb:.1f} KB)")
    print(f"build_mcpb: sha256 {digest}")
    print(f"build_mcpb: wrote {checksum}")
    print(
        f"build_mcpb: publish with -> smithery mcp publish {output} -n rye/openzim-mcp"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
