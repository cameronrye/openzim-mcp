"""Live Docker image build + run smoke test.

Covers v1.0 item 3: the multi-stage, multi-arch Docker image published
to ``ghcr.io/cameronrye/openzim-mcp``. Builds the image locally, runs
it under HTTP transport with a temp auth token, polls ``/readyz``
through the host port mapping, and asserts the container runs as the
non-root ``appuser``.

Skipped automatically when:
  - the ``docker`` CLI is not on ``PATH``
  - the docker daemon is not reachable
  - the test marker filter excludes ``live`` (default).

Marked with ``docker`` in addition to ``live`` so callers who only
want the fast loopback tests can ``-m 'live and not docker'``.
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Iterator

import httpx
import pytest

from tests.live.conftest import _find_free_loopback_port

pytestmark = [pytest.mark.live, pytest.mark.docker]

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_TAG = "openzim-mcp-livetest:latest"
BUILD_TIMEOUT_SECONDS = 600  # 10 minutes; first build pulls base layers
RUN_READYZ_TIMEOUT_SECONDS = 60


def _docker_available() -> bool:
    """Return True iff the docker CLI is installed AND the daemon answers."""
    if shutil.which("docker") is None:
        return False
    try:
        cp = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    # `docker info` prints "" to stdout and an error to stderr when the
    # daemon is unreachable, but still exits 0 in some configurations.
    return cp.returncode == 0 and bool(cp.stdout.strip())


pytestmark.append(
    pytest.mark.skipif(
        not _docker_available(),
        reason=(
            "docker CLI missing or daemon not reachable; install Docker "
            "Desktop and start it to run this test"
        ),
    )
)


@pytest.fixture(scope="module")
def built_image() -> str:
    """Build the openzim-mcp image once per test module; return the tag."""
    cp = subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "."],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=BUILD_TIMEOUT_SECONDS,
        check=False,
    )
    if cp.returncode != 0:
        pytest.fail(
            f"docker build failed (exit {cp.returncode}):\n"
            f"--- stdout ---\n{cp.stdout.decode(errors='replace')[-2000:]}\n"
            f"--- stderr ---\n{cp.stderr.decode(errors='replace')[-2000:]}"
        )
    return IMAGE_TAG


@pytest.fixture
def running_container(built_image: str, zim_dir: Path) -> Iterator[dict]:
    """Run the image with HTTP transport + temp token; yield container info."""
    container_name = f"oz-mcp-livetest-{uuid.uuid4().hex[:8]}"
    host_port = _find_free_loopback_port()
    token = secrets.token_urlsafe(32)

    cp = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "-p",
            f"127.0.0.1:{host_port}:8000",
            "-v",
            f"{zim_dir}:/data:ro",
            "-e",
            f"OPENZIM_MCP_AUTH_TOKEN={token}",
            built_image,
        ],
        capture_output=True,
        timeout=20,
        check=False,
    )
    if cp.returncode != 0:
        pytest.fail(
            f"docker run failed (exit {cp.returncode}): "
            f"{cp.stderr.decode(errors='replace')}"
        )
    container_id = cp.stdout.decode().strip()
    info = {
        "id": container_id,
        "name": container_name,
        "host_port": host_port,
        "token": token,
        "url": f"http://127.0.0.1:{host_port}",
    }
    try:
        # Wait for /readyz to become 200; surface container logs on timeout.
        deadline = time.monotonic() + RUN_READYZ_TIMEOUT_SECONDS
        last_status: int | None = None
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(f"{info['url']}/readyz", timeout=2)
                last_status = resp.status_code
                if resp.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1.0)
        else:
            logs = subprocess.run(
                ["docker", "logs", "--tail", "100", container_name],
                capture_output=True,
                timeout=10,
                check=False,
            )
            pytest.fail(
                f"container did not become ready within "
                f"{RUN_READYZ_TIMEOUT_SECONDS}s (last /readyz status={last_status}).\n"
                f"--- container logs ---\n"
                f"{logs.stdout.decode(errors='replace')[-2000:]}\n"
                f"{logs.stderr.decode(errors='replace')[-1000:]}"
            )
        yield info
    finally:
        subprocess.run(
            ["docker", "stop", "-t", "5", container_name],
            capture_output=True,
            timeout=15,
            check=False,
        )


def test_container_healthcheck_endpoints(running_container: dict) -> None:
    """``/healthz`` and ``/readyz`` respond 200 from inside the container."""
    healthz = httpx.get(f"{running_container['url']}/healthz", timeout=5)
    assert healthz.status_code == 200
    readyz = httpx.get(f"{running_container['url']}/readyz", timeout=5)
    assert readyz.status_code == 200


def test_container_runs_as_non_root(running_container: dict) -> None:
    """Image must drop privileges to ``appuser`` (uid 10001) per Dockerfile."""
    cp = subprocess.run(
        ["docker", "exec", running_container["name"], "id"],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert cp.returncode == 0, cp.stderr.decode(errors="replace")
    out = cp.stdout.decode()
    assert "uid=10001" in out, f"expected uid=10001 (appuser), got: {out!r}"
    assert "uid=0(" not in out, f"container is running as root: {out!r}"


def test_container_mcp_endpoint_requires_auth(running_container: dict) -> None:
    """``POST /mcp`` without bearer token returns 401 from the container."""
    resp = httpx.post(f"{running_container['url']}/mcp", timeout=5)
    assert resp.status_code == 401


def test_container_mcp_endpoint_accepts_valid_token(
    running_container: dict,
) -> None:
    """``POST /mcp`` with the env-supplied token reaches the MCP handler.

    A valid token must not 401, but we also require the container to NOT
    return 5xx — that would mean the container crashed or misconfigured
    rather than auth-passed. The MCP handshake itself isn't exercised
    here; the streamable-HTTP MCP client tests do that.
    """
    resp = httpx.post(
        f"{running_container['url']}/mcp",
        headers={
            "Authorization": f"Bearer {running_container['token']}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        timeout=10,
    )
    assert (
        resp.status_code != 401
    ), f"valid bearer token was rejected: {resp.status_code} {resp.text[:200]}"
    assert resp.status_code < 500, (
        f"container returned 5xx for an authenticated request — likely "
        f"crashed or misconfigured rather than processing it: "
        f"{resp.status_code} {resp.text[:300]}"
    )


def test_image_has_healthcheck_directive(built_image: str) -> None:
    """``docker inspect`` must show the HEALTHCHECK from the Dockerfile."""
    cp = subprocess.run(
        ["docker", "inspect", built_image],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert cp.returncode == 0
    inspected = json.loads(cp.stdout)
    assert inspected, "docker inspect returned empty array"
    config = inspected[0].get("Config", {})
    healthcheck = config.get("Healthcheck") or {}
    test_field = healthcheck.get("Test") or []
    assert test_field, f"image has no HEALTHCHECK directive: {config!r}"
    # Joined check covers both shell-form and exec-form
    assert "readyz" in " ".join(
        test_field
    ), f"healthcheck doesn't probe /readyz: {test_field!r}"
