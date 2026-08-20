"""The HTTP server must be able to shut down while a stream is open.

``uvicorn.Config`` leaves ``timeout_graceful_shutdown`` at ``None`` — wait
forever. On SIGTERM uvicorn stops accepting, then blocks in "Waiting for
connections to close" until every connection ends, and only *then* runs the
ASGI lifespan shutdown.

A ``subscriptions/listen`` request is served by an SSE loop that emits
keepalive pings and ends only on client disconnect; a listen handler never
completes on its own. So one subscribed client made the process
unkillable by SIGTERM/SIGINT: ``docker stop`` burned its full grace period
and then SIGKILLed, and SIGKILL skips ``atexit`` — taking the cache
persistence handler registered in ``OpenZimMcpCache.__init__`` with it, so
the warm cache was silently lost on every restart.

The watcher shares the fate: ``lifespan_with_watcher``'s
``finally: await watcher.stop()`` sits behind that same lifespan shutdown.
"""

from __future__ import annotations

from typing import Any

from openzim_mcp import http_app


class _FakeServer:
    def __init__(self, config: Any) -> None:
        self.config = config

    def run(self) -> None:
        return None


def test_default_runner_bounds_graceful_shutdown(monkeypatch: Any) -> None:
    """The uvicorn config must carry a finite ``timeout_graceful_shutdown``."""
    captured: dict = {}

    class _FakeConfig:
        def __init__(self, app: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

    import uvicorn

    monkeypatch.setattr(uvicorn, "Config", _FakeConfig)
    monkeypatch.setattr(uvicorn, "Server", _FakeServer)

    http_app._default_uvicorn_runner(object(), "127.0.0.1", 8000)  # type: ignore[arg-type]

    timeout = captured.get("timeout_graceful_shutdown")
    assert timeout is not None, (
        "timeout_graceful_shutdown left at uvicorn's None default: an open "
        "subscriptions/listen stream makes SIGTERM hang forever"
    )
    assert isinstance(timeout, int)
    assert 0 < timeout < 10, (
        "grace period must fit inside Docker's 10s default stop timeout so "
        "`docker stop` reaches lifespan shutdown instead of SIGKILLing"
    )


def test_default_runner_still_passes_host_and_port(monkeypatch: Any) -> None:
    """Regression guard: the bind arguments must survive the added kwarg."""
    captured: dict = {}

    class _FakeConfig:
        def __init__(self, app: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

    import uvicorn

    monkeypatch.setattr(uvicorn, "Config", _FakeConfig)
    monkeypatch.setattr(uvicorn, "Server", _FakeServer)

    http_app._default_uvicorn_runner(object(), "0.0.0.0", 9123)  # type: ignore[arg-type]

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9123
