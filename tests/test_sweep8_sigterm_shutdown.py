"""SIGTERM must flush the cache the way a graceful stop does.

Python's default SIGTERM disposition kills the process without unwinding, so
the ``atexit`` hook ``OpenZimMcpCache`` registers for its persistence file
never ran. Every ``docker stop`` / pod eviction / systemd restart therefore
threw the cache away and forced the next start to be cold, which is the
opposite of what ``SHUTDOWN_GRACE_SECONDS`` was documented to preserve.

The HTTP transport was no safer despite uvicorn's graceful shutdown: uvicorn
restores the previous handler and re-raises the signal to report the right
exit status, and with the default disposition restored that re-raise killed
the process just the same.
"""

from __future__ import annotations

import signal
from typing import Any

import pytest

from openzim_mcp import main as main_mod


class TestTerminationHandler:
    def test_handler_raises_system_exit_with_conventional_status(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main_mod._raise_system_exit(signal.SIGTERM, None)
        assert excinfo.value.code == 128 + int(signal.SIGTERM)

    def test_install_registers_for_sigterm(self) -> None:
        previous = signal.getsignal(signal.SIGTERM)
        try:
            main_mod.install_termination_handler()
            assert signal.getsignal(signal.SIGTERM) is main_mod._raise_system_exit
        finally:
            signal.signal(signal.SIGTERM, previous)

    def test_install_is_quiet_when_signal_registration_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``signal.signal`` rejects a non-main thread; an embedding harness
        that calls ``main`` off-thread must keep working."""

        def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise ValueError("signal only works in main thread")

        monkeypatch.setattr(signal, "signal", refuse)
        main_mod.install_termination_handler()  # must not raise


class TestFlushAndExit:
    def test_persists_the_cache_then_exits_with_the_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        exited: list[int] = []

        class FakeCache:
            def shutdown(self) -> None:
                calls.append("shutdown")

        class FakeServer:
            cache = FakeCache()

        monkeypatch.setattr(main_mod.os, "_exit", lambda code: exited.append(code))
        main_mod._flush_and_exit(FakeServer(), 143)  # type: ignore[arg-type]

        assert calls == ["shutdown"], "the cache flush must happen before exiting"
        assert exited == [143]

    def test_exits_even_when_the_flush_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken persistence path must not turn a stop into a hang."""
        exited: list[int] = []

        class ExplodingCache:
            def shutdown(self) -> None:
                raise OSError("disk full")

        class FakeServer:
            cache = ExplodingCache()

        monkeypatch.setattr(main_mod.os, "_exit", lambda code: exited.append(code))
        main_mod._flush_and_exit(FakeServer(), 143)  # type: ignore[arg-type]

        assert exited == [143]
