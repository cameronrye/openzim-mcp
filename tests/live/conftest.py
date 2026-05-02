"""Fixtures for live-server tests.

These tests spawn a real openzim-mcp subprocess and exercise behavior
that can't be reached from in-process unit tests (HTTP transport, SSE
transport, mtime-driven subscription notifications, cache persistence
across a restart, MCP prompts over the wire).

Tests in this directory are tagged ``@pytest.mark.live`` and excluded
from the default ``uv run pytest`` run via ``addopts = -m 'not live'``.
Run them explicitly with ``make test-live`` or ``uv run pytest -m live``.

A ZIM directory must be reachable; set ``ZIM_TEST_DATA_DIR`` to override
the default of ``~/Developer/zim``. The fixtures skip the test if no
``.zim`` files are found there.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

import httpx
import pytest


def _find_free_loopback_port() -> int:
    """Bind 127.0.0.1:0 to let the kernel pick an unused port, then close."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _zim_dir() -> Path:
    return Path(os.environ.get("ZIM_TEST_DATA_DIR", str(Path.home() / "Developer/zim")))


@pytest.fixture(scope="session")
def zim_dir() -> Path:
    """Resolve the directory of ZIM files; skip if none present."""
    d = _zim_dir()
    if not d.is_dir() or not list(d.glob("*.zim")):
        pytest.skip(f"No .zim files found in {d}. Set ZIM_TEST_DATA_DIR to override.")
    return d


@dataclass
class LiveServer:
    """Handle to a running openzim-mcp subprocess."""

    process: subprocess.Popen
    host: str
    port: int
    transport: str  # "http" | "sse" | "stdio"
    token: Optional[str] = None
    stderr_path: Optional[Path] = None
    extra: dict = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        """Return ``http://host:port`` for issuing HTTP requests."""
        return f"http://{self.host}:{self.port}"

    @property
    def auth_headers(self) -> dict:
        """Return a Bearer-auth header dict, or empty if no token configured."""
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def healthz(self, timeout: float = 5.0) -> httpx.Response:
        """Issue ``GET /healthz`` and return the response."""
        return httpx.get(f"{self.base_url}/healthz", timeout=timeout)

    def readyz(self, timeout: float = 5.0) -> httpx.Response:
        """Issue ``GET /readyz`` and return the response."""
        return httpx.get(f"{self.base_url}/readyz", timeout=timeout)


def _spawn(
    *,
    zim_dir: Path,
    transport: str,
    host: str = "127.0.0.1",
    port: Optional[int] = None,
    token: Optional[str] = None,
    cors_origins: Optional[List[str]] = None,
    extra_env: Optional[dict] = None,
    tmp_path: Optional[Path] = None,
    capture_stderr: bool = True,
    extra_args: Optional[List[str]] = None,
) -> LiveServer:
    """Launch openzim-mcp as a subprocess, wait for /healthz, return handle.

    Uses ``sys.executable -m openzim_mcp`` so we exercise the source tree's
    code, not whatever is installed on PATH.
    """
    if port is None:
        port = _find_free_loopback_port()

    env = dict(os.environ)
    if token is not None:
        env["OPENZIM_MCP_AUTH_TOKEN"] = token
    if cors_origins is not None:
        # CORS_ORIGINS is a JSON-encoded list when passed via env (pydantic-settings).
        import json as _json

        env["OPENZIM_MCP_CORS_ORIGINS"] = _json.dumps(cors_origins)
    if extra_env:
        env.update(extra_env)

    cmd = [
        sys.executable,
        "-m",
        "openzim_mcp",
        "--mode",
        "advanced",
        "--transport",
        transport,
        "--host",
        host,
        "--port",
        str(port),
        str(zim_dir),
    ]
    if extra_args:
        cmd.extend(extra_args)

    stderr_path = (tmp_path / f"server-{port}.stderr") if tmp_path else None
    if capture_stderr and stderr_path:
        stderr_fp = stderr_path.open("wb")
    else:
        stderr_fp = subprocess.DEVNULL

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL if transport != "stdio" else subprocess.PIPE,
        stdout=subprocess.DEVNULL if transport != "stdio" else subprocess.PIPE,
        stderr=stderr_fp,
        env=env,
    )

    server = LiveServer(
        process=proc,
        host=host,
        port=port,
        transport=transport,
        token=token,
        stderr_path=stderr_path,
    )

    # Wait for readiness. http transport exposes /healthz; sse uses
    # FastMCP's built-in app which doesn't, so we fall back to a TCP probe.
    if transport in ("http", "sse"):
        deadline = time.monotonic() + 10.0
        last_err: Optional[BaseException] = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stderr_text = (
                    stderr_path.read_text()
                    if stderr_path and stderr_path.exists()
                    else ""
                )
                raise RuntimeError(
                    f"openzim-mcp exited early with code {proc.returncode}.\n"
                    f"Command: {' '.join(cmd)}\n"
                    f"Stderr:\n{stderr_text}"
                )
            try:
                if transport == "http":
                    resp = httpx.get(f"http://{host}:{port}/healthz", timeout=0.5)
                    if resp.status_code == 200:
                        return server
                else:  # sse
                    with socket.create_connection((host, port), timeout=0.5):
                        return server
            except Exception as e:  # pragma: no cover
                last_err = e
            time.sleep(0.1)
        # Timed out — kill and raise.
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        stderr_text = (
            stderr_path.read_text() if stderr_path and stderr_path.exists() else ""
        )
        raise RuntimeError(
            f"openzim-mcp on {host}:{port} did not become ready within 10s.\n"
            f"Last error: {last_err}\nStderr:\n{stderr_text}"
        )

    return server


def _terminate(server: LiveServer) -> None:
    """Best-effort shutdown: SIGTERM, then SIGKILL after 3s."""
    proc = server.process
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


@pytest.fixture
def spawn_live_server(zim_dir: Path, tmp_path: Path) -> Iterator:
    """Yield a factory that spawns and auto-cleans openzim-mcp subprocesses.

    Each spawned server is torn down at test teardown, so callers don't
    need a ``with`` block::

        def test_x(spawn_live_server):
            srv = spawn_live_server(transport="http", token="secret")
            assert srv.healthz().status_code == 200
    """
    spawned: List[LiveServer] = []

    def _factory(**kwargs) -> LiveServer:
        srv = _spawn(zim_dir=zim_dir, tmp_path=tmp_path, **kwargs)
        spawned.append(srv)
        return srv

    try:
        yield _factory
    finally:
        for s in spawned:
            _terminate(s)


def expect_failed_startup(
    *,
    zim_dir: Path,
    transport: str,
    host: str,
    port: int,
    token: Optional[str] = None,
    timeout: float = 5.0,
) -> subprocess.CompletedProcess:
    """Run openzim-mcp and assert it exits within ``timeout`` (e.g. safe-default).

    Returns the CompletedProcess so the test can inspect stderr.
    """
    env = dict(os.environ)
    if token is not None:
        env["OPENZIM_MCP_AUTH_TOKEN"] = token
    cmd = [
        sys.executable,
        "-m",
        "openzim_mcp",
        "--mode",
        "advanced",
        "--transport",
        transport,
        "--host",
        host,
        "--port",
        str(port),
        str(zim_dir),
    ]
    return subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
