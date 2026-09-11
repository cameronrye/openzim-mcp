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

That directory is READ-ONLY to this suite: it is whatever library the
operator happens to keep there. A test that rewrites an archive, or builds a
sidecar beside one, takes ``disposable_corpus`` and gets a writable copy, and
``_zim_dir_stays_read_only`` fails the session if anything in the configured
directory moves.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, List, Optional

import httpx
import pytest


def _find_free_loopback_port() -> int:
    """Bind 127.0.0.1:0 to let the kernel pick an unused port, then close.

    There is a small TOCTOU window between the close here and the
    server's bind; in practice the kernel doesn't recycle ports that
    fast, but on a heavily-contended CI host it could spuriously fail.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def fresh_token() -> str:
    """Generate a fresh bearer token for one live-test invocation."""
    return secrets.token_urlsafe(32)


def _zim_dir() -> Path:
    return Path(os.environ.get("ZIM_TEST_DATA_DIR", str(Path.home() / "Developer/zim")))


def usable_zims(d: Path) -> List[Path]:
    """Return the archives in ``d`` that a test may legitimately assert on.

    Excludes the ``invalid.*`` fixtures. The zim-testing-suite ships
    deliberately-corrupt archives (truncated header, out-of-bounds cluster
    pointer, bad mimetype in dirent) whose whole purpose is to be rejected,
    and they sort ahead of every real archive — so any test that reached
    for ``sorted(...)[0]`` was asserting real behavior against a file
    engineered to have none.
    """
    return [f for f in sorted(d.glob("*.zim")) if not f.name.startswith("invalid.")]


def resolve_zim_dir(d: Path) -> Optional[Path]:
    """Resolve ``d`` to a directory holding usable archives, or None.

    ``ZIM_TEST_DATA_DIR`` is read by two fixture families with different
    layout expectations: ``tests/conftest.py`` wants the zim-testing-suite
    *root* and reaches into ``withns/`` and ``nons/`` itself, while the live
    fixtures want a flat directory of ``.zim`` files. Pointing the variable
    at whichever layout one family wants used to strand the other. Accept
    both by descending into the suite's subdirectories when the directory
    named has no usable archive of its own.
    """
    if not d.is_dir():
        return None
    if usable_zims(d):
        return d
    for sub in ("withns", "nons"):
        candidate = d / sub
        if candidate.is_dir() and usable_zims(candidate):
            return candidate
    return None


@pytest.fixture(scope="session")
def zim_dir() -> Path:
    """Resolve the directory of ZIM files; skip if none present.

    READ-ONLY. This is whatever library the operator pointed
    ``ZIM_TEST_DATA_DIR`` at, defaulting to ``~/Developer/zim``. A test that
    writes to an archive, or beside one, takes ``disposable_corpus`` instead.
    """
    d = _zim_dir()
    resolved = resolve_zim_dir(d)
    if resolved is None:
        pytest.skip(f"No .zim files found in {d}. Set ZIM_TEST_DATA_DIR to override.")
    return resolved


def smallest_usable_zim(d: Path) -> Optional[Path]:
    """The smallest archive in ``d`` a test may assert on, or None."""
    candidates = usable_zims(d)
    return min(candidates, key=lambda f: f.stat().st_size) if candidates else None


def writable_copy(archive: Path, dest_dir: Path) -> Path:
    """Copy ``archive`` into ``dest_dir`` so a test may write to or beside it.

    On APFS this is a clone: instant, and it occupies no extra space until
    something writes. Elsewhere it is a plain copy, which is cheap on the
    archives CI actually ships.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / archive.name
    if sys.platform == "darwin":
        cloned = subprocess.run(
            ["/bin/cp", "-c", str(archive), str(dest)],
            capture_output=True,
            check=False,
        )
        if cloned.returncode == 0:
            return dest
    shutil.copyfile(archive, dest)
    return dest


@pytest.fixture
def disposable_corpus(zim_dir: Path, tmp_path: Path) -> Path:
    """A directory holding a writable copy of the smallest usable archive.

    For the tests that rewrite what they watch, or build a sidecar beside it.
    Pointed at a real library, those tests used to do that in place: same
    bytes, new mtime — which invalidates every cache key derived from the
    file — and a sidecar rebuilt by whichever builder the branch under test
    happened to carry.
    """
    archive = smallest_usable_zim(zim_dir)
    if archive is None:  # pragma: no cover - zim_dir skips first
        pytest.skip(f"no usable .zim files in {zim_dir}")
    corpus = tmp_path / "corpus"
    writable_copy(archive, corpus)
    return corpus


@pytest.fixture(scope="session", autouse=True)
def _zim_dir_stays_read_only() -> Iterator[None]:
    """Fail the session if anything under the configured ZIM directory moved.

    Three runs rewrote an archive or its sidecar in place before this existed
    and nothing noticed, because the bytes were identical and only the mtime
    moved. Compares name, mtime and size of every file in the directory,
    which is what a rewrite-in-place changes and what every cache key derived
    from an archive depends on.
    """
    resolved = resolve_zim_dir(_zim_dir())
    if resolved is None:
        yield
        return

    def snapshot() -> dict:
        return {
            entry.name: (entry.stat().st_mtime_ns, entry.stat().st_size)
            for entry in sorted(resolved.iterdir())
            if entry.is_file()
        }

    before = snapshot()
    try:
        yield
    finally:
        after = snapshot()
        changed = sorted(
            name
            for name in set(before) | set(after)
            if before.get(name) != after.get(name)
        )
        assert not changed, (
            f"the live suite modified {resolved}: {changed}. That directory is "
            "the operator's library, not a fixture — take a copy with the "
            "disposable_corpus fixture instead."
        )


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


def _spawn(  # NOSONAR(python:S3776)
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
        # Open, hand to Popen (which dup2's the fd into the child), then
        # close the parent's handle. Leaving it open leaks one fd per
        # spawned server and triggers ResourceWarning on GC.
        stderr_fp: Any = stderr_path.open("wb")
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL if transport != "stdio" else subprocess.PIPE,
                stdout=subprocess.DEVNULL if transport != "stdio" else subprocess.PIPE,
                stderr=stderr_fp,
                env=env,
            )
        finally:
            stderr_fp.close()
    else:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL if transport != "stdio" else subprocess.PIPE,
            stdout=subprocess.DEVNULL if transport != "stdio" else subprocess.PIPE,
            stderr=subprocess.DEVNULL,
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
    # stdio has no readiness probe — the caller drives the process directly.
    if transport in ("http", "sse"):
        _wait_for_ready(server, proc, cmd, host, port, transport, stderr_path)

    return server


def _wait_for_ready(  # NOSONAR(python:S3776)
    server: "LiveServer",
    proc: subprocess.Popen,
    cmd: List[str],
    host: str,
    port: int,
    transport: str,
    stderr_path: Optional[Path],
) -> None:
    """Block until the server reports ready, or raise on timeout/early exit."""
    deadline = time.monotonic() + 10.0
    last_err: Optional[BaseException] = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stderr_text = (
                stderr_path.read_text() if stderr_path and stderr_path.exists() else ""
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
                    return
            else:  # sse
                with socket.create_connection((host, port), timeout=0.5):
                    return
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


def _terminate(server: LiveServer) -> None:
    """Best-effort shutdown: SIGTERM, then SIGKILL after 3s.

    Swallows the second-stage TimeoutExpired so a single hung server
    can't prevent teardown of subsequent servers in the same fixture.
    """
    proc = server.process
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        # Kernel didn't reap in 2s after SIGKILL is extremely rare; leave
        # the zombie and let pytest session teardown clean up.
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=2)


@pytest.fixture
def mcp_proc(zim_dir: Path) -> Iterator[subprocess.Popen]:
    """Yield an initialized stdio openzim-mcp subprocess; tear down on exit."""
    from tests.live._stdio_helpers import initialize, shutdown, spawn_stdio

    proc = spawn_stdio(zim_dir)
    try:
        initialize(proc)
        yield proc
    finally:
        shutdown(proc)


@pytest.fixture
def spawn_live_server(zim_dir: Path, tmp_path: Path) -> Iterator:
    """Yield a factory that spawns and auto-cleans openzim-mcp subprocesses.

    Each spawned server is torn down at test teardown, so callers don't
    need a ``with`` block::

        def test_x(spawn_live_server):
            srv = spawn_live_server(transport="http", token="secret")
            assert srv.healthz().status_code == 200

    Pass ``zim_dir=`` to serve a different directory — ``disposable_corpus``
    for a test that writes to what the server is watching.
    """
    spawned: List[LiveServer] = []

    def _factory(**kwargs) -> LiveServer:
        served = kwargs.pop("zim_dir", zim_dir)
        srv = _spawn(zim_dir=served, tmp_path=tmp_path, **kwargs)
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
