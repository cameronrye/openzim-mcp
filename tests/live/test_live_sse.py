"""Live SSE transport smoke test.

Covers v1.0 item 2: legacy SSE transport (``--transport sse``). FastMCP
exposes the SSE event stream at ``/sse``; we just verify the endpoint
accepts a GET and starts streaming, which is enough to confirm the
transport boots and routes correctly.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.live


def test_sse_endpoint_accepts_get(spawn_live_server) -> None:
    """``GET /sse`` should respond with text/event-stream and start streaming."""
    srv = spawn_live_server(transport="sse")
    # Use a streaming GET so we don't hang waiting for the (long-lived) body.
    with httpx.stream("GET", f"{srv.base_url}/sse", timeout=5) as resp:
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "event-stream" in ct, f"unexpected content-type: {ct!r}"
        # Pull at least one chunk to confirm the stream is live, then stop.
        for chunk in resp.iter_bytes():
            if chunk:
                break


def test_sse_safe_default_refuses_public_bind(zim_dir) -> None:
    """SSE has no auth middleware, so public-host bind must always be refused."""
    from tests.live.conftest import _find_free_loopback_port, expect_failed_startup

    port = _find_free_loopback_port()
    cp = expect_failed_startup(
        zim_dir=zim_dir, transport="sse", host="0.0.0.0", port=port, token=None
    )
    assert cp.returncode != 0
    stderr_raw = cp.stderr.decode(errors="replace")
    stderr_text = stderr_raw.lower()
    # SSE refuses regardless of token (no auth middleware to gate access).
    assert (
        "loopback" in stderr_text
        or "localhost" in stderr_text
        or "127.0.0.1" in stderr_text
        or "host" in stderr_text
    ), f"expected loopback/host hint in stderr, got:\n{stderr_raw}"
