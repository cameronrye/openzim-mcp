"""Transport and server-state defects found by driving the released binary.

Each class names the reported behaviour it pins. The signal tests drive a real
``python -m openzim_mcp`` subprocess because the defect they cover lives in the
interaction between the signal disposition, the stdio transport's non-daemon
reader thread and interpreter finalization — none of which exist in-process.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import pytest
from starlette.testclient import TestClient

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.http_app import serve_streamable_http
from openzim_mcp.server import OpenZimMcpServer

_INITIALIZE = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "signal-test", "version": "1"},
        },
    }
)


def _serving_stdio_process(
    tmp_path: Path,
) -> "tuple[subprocess.Popen[bytes], Path]":
    """A real stdio server, past ``initialize`` and blocked reading stdin."""
    (tmp_path / "sample.zim").write_bytes(b"placeholder")
    stderr_path = tmp_path / "server.stderr"
    with stderr_path.open("wb") as stderr:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "openzim_mcp",
                "--mode",
                "advanced",
                "--transport",
                "stdio",
                str(tmp_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            env=os.environ.copy(),
        )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write((_INITIALIZE + "\n").encode())
    proc.stdin.flush()
    answer = proc.stdout.readline()
    assert b'"result"' in answer, answer
    proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    proc.stdin.flush()
    # Let the transport settle back onto its blocking stdin read before the
    # signal lands; that read is the thread the old SIGINT path hung on.
    time.sleep(0.5)
    return proc, stderr_path


class TestStopSignalsUnwindTheStdioServer:
    """fid 131 — Ctrl-C on the documented manual run left an unkillable process.

    ``install_termination_handler`` covered SIGTERM only. SIGINT kept Python's
    default disposition, whose ``KeyboardInterrupt`` unwinds the loop and then
    parks interpreter finalization on the stdio transport's non-daemon stdin
    reader thread — forever. The observed behaviour was "STILL ALIVE after 40s
    -> SIGKILL", with stderr ending at "Starting OpenZIM MCP server", and
    SIGKILL is the one exit that skips the cache flush.
    """

    @pytest.mark.parametrize(
        "signal_name",
        ["SIGINT", "SIGHUP"],
    )
    def test_signal_exits_promptly_through_the_flush_path(
        self, tmp_path: Path, signal_name: str
    ) -> None:
        signum = getattr(signal, signal_name)
        proc, stderr_path = _serving_stdio_process(tmp_path)
        try:
            proc.send_signal(signum)
            try:
                returncode = proc.wait(timeout=20)
            except subprocess.TimeoutExpired:  # pragma: no cover - the defect
                pytest.fail(
                    f"{signal_name} did not stop the stdio server within 20s; "
                    f"stderr:\n{stderr_path.read_text()}"
                )
        finally:
            if proc.poll() is None:  # pragma: no cover - cleanup only
                proc.kill()
                proc.wait()

        stderr = stderr_path.read_text()
        # 128+signum is produced only by _raise_system_exit -> main's
        # `except SystemExit` -> _flush_and_exit(code) -> os._exit(code). A
        # process killed by the signal reports a negative returncode, and the
        # default SIGINT disposition would exit 1 (or hang).
        assert returncode == 128 + int(signum), (
            f"{signal_name} did not reach the cache-flush exit path "
            f"(returncode {returncode}); stderr:\n{stderr}"
        )
        assert "OpenZIM MCP server stopped" in stderr, stderr

    def test_sigterm_still_exits_the_same_way(self, tmp_path: Path) -> None:
        """The signal that already worked must keep working."""
        proc, stderr_path = _serving_stdio_process(tmp_path)
        try:
            proc.send_signal(signal.SIGTERM)
            returncode = proc.wait(timeout=20)
        finally:
            if proc.poll() is None:  # pragma: no cover - cleanup only
                proc.kill()
                proc.wait()
        assert returncode == 128 + int(signal.SIGTERM)
        assert "OpenZIM MCP server stopped" in stderr_path.read_text()


class TestTerminationHandlerRegistration:
    """The disposition each stop signal is left with, without spawning."""

    def test_every_stop_signal_gets_the_unwinding_handler(self) -> None:
        from openzim_mcp import main as main_mod

        stop_signals = main_mod._termination_signals()
        assert int(signal.SIGTERM) in stop_signals
        assert int(signal.SIGINT) in stop_signals

        previous: dict[int, Any] = {
            signum: signal.getsignal(signum) for signum in stop_signals
        }
        try:
            main_mod.install_termination_handler()
            for signum in stop_signals:
                assert (
                    signal.getsignal(signum) is main_mod._raise_system_exit
                ), f"signal {signum} kept its default disposition"
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)


def _one_shot_stdio_frames(
    tmp_path: Path, frames: "list[str]"
) -> "list[dict[str, Any]]":
    """Pipe ``frames`` then EOF into a real stdio server; what it wrote back."""
    (tmp_path / "sample.zim").write_bytes(b"placeholder")
    stderr_path = tmp_path / "server.stderr"
    with stderr_path.open("wb") as stderr:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "openzim_mcp",
                "--mode",
                "advanced",
                "--transport",
                "stdio",
                str(tmp_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            env=os.environ.copy(),
        )
    try:
        stdout, _ = proc.communicate(
            "".join(frame + "\n" for frame in frames).encode(), timeout=60
        )
    finally:
        if proc.poll() is None:  # pragma: no cover - cleanup only
            proc.kill()
            proc.wait()
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


# --------------------------------------------------------------------------
# HTTP transport — driven through the production-wired app
# --------------------------------------------------------------------------

_HANDSHAKE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _build_http_client(tmp_path: Path) -> "tuple[TestClient, OpenZimMcpServer]":
    """The real app ``serve_streamable_http`` hands uvicorn, gates and all."""
    (tmp_path / "sample.zim").write_bytes(b"placeholder")
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], transport="http")
    server = OpenZimMcpServer(config)
    captured: dict[str, Any] = {}
    serve_streamable_http(
        server, runner=lambda app, host, port: captured.update(app=app)
    )
    # A loopback base URL: the default ``testserver`` Host is turned away by
    # the DNS-rebinding gate (421) before the request reaches the SDK.
    return TestClient(captured["app"], base_url="http://127.0.0.1"), server


@pytest.fixture
def mcp_session(tmp_path: Path) -> Iterator["tuple[TestClient, str]"]:
    """An open streamable-HTTP session on the production-wired app."""
    client, _server = _build_http_client(tmp_path)
    with client:
        opened = client.post("/mcp", headers=_HANDSHAKE_HEADERS, content=_INITIALIZE)
        assert opened.status_code == 200, opened.text
        session_id = opened.headers["mcp-session-id"]
        client.post(
            "/mcp",
            headers={**_HANDSHAKE_HEADERS, "Mcp-Session-Id": session_id},
            content='{"jsonrpc":"2.0","method":"notifications/initialized"}',
        )
        yield client, session_id


def _open_get_stream(
    client: TestClient, headers: "dict[str, str]"
) -> "tuple[int | None, str, list[BaseException]]":
    """Open the SSE GET stream on the real app; report how it answered.

    ``TestClient`` runs an ASGI app to completion before handing back a
    response, and the MCP GET stream never completes on its own, so the
    request is driven directly — through the app's own middleware stack, on
    the portal's event loop where the session manager lives, so this is the
    production wiring and not a stub. The client hangs up shortly after the
    response starts, which is what a real ``EventSource`` close looks like.
    """
    import anyio

    async def drive() -> "tuple[int | None, str, list[BaseException]]":
        started: "dict[str, Any]" = {}
        failures: "list[BaseException]" = []
        first_receive = True

        async def receive() -> "dict[str, Any]":
            nonlocal first_receive
            if first_receive:
                # The empty body of a GET. Withholding it blocks the SDK's
                # handler before it can answer at all, which would make every
                # value of the header look equally broken.
                first_receive = False
                return {"type": "http.request", "body": b"", "more_body": False}
            # Then hang up, the way an EventSource close reaches the server.
            await anyio.sleep(0.3)
            return {"type": "http.disconnect"}

        async def send(message: "dict[str, Any]") -> None:
            if message["type"] == "http.response.start":
                started.setdefault("status", message["status"])
                started.setdefault("headers", message.get("headers", []))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/mcp",
            "raw_path": b"/mcp",
            "root_path": "",
            "query_string": b"",
            "headers": [
                (name.lower().encode(), value.encode())
                for name, value in {"host": "127.0.0.1", **headers}.items()
            ],
            "client": ("127.0.0.1", 45678),
            "server": ["127.0.0.1", 80],
            "extensions": {"http.response.debug": {}},
            # The lifespan state ``TestClient`` hands every request it makes.
            "state": client.app_state.copy(),
        }
        with anyio.move_on_after(20):
            try:
                await client.app(scope, receive, send)  # type: ignore[operator]
            except BaseException as exc:  # noqa: BLE001 - the 500 arrives here
                if not isinstance(exc, anyio.get_cancelled_exc_class()):
                    failures.append(exc)
                else:
                    raise
        content_type = ""
        for name, value in started.get("headers", []):
            if name.lower() == b"content-type":
                content_type = value.decode()
        return started.get("status"), content_type, failures

    return client.portal.call(drive)  # type: ignore[union-attr,arg-type]


def _sse_payload(text: str) -> "dict[str, Any] | None":
    """The JSON-RPC payload inside the SDK's one-event SSE response."""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :])
    return None


class TestUnusableRequestIdsAreAnswered:
    """fid 107 — a non-(str | non-bool int) id was swallowed on every transport.

    The SDK's adapter types the id as ``str | int``, so every other shape
    validates as a *notification* and vanishes. Over HTTP the transport made
    it worse than silence: ``202 Accepted`` with an empty body told the client
    the server had taken a request it would never answer. ``id: null`` — the
    single shape ``sdk_compat`` was written to catch — fell through here too,
    because the guard lived only in the stdio reader.
    """

    UNUSABLE = [
        pytest.param("3.0", "3.0", id="whole-number-as-float"),
        pytest.param("1.5", "1.5", id="fractional"),
        pytest.param("1e21", "1e+21", id="past-2^53"),
        pytest.param("true", "true", id="boolean"),
        pytest.param("[1]", "[1]", id="array"),
        pytest.param('{"a":1}', '{"a": 1}', id="object"),
        pytest.param("null", "null", id="null"),
    ]

    @pytest.mark.parametrize(("raw_id", "quoted"), UNUSABLE)
    def test_http_answers_instead_of_202_and_drop(
        self, mcp_session: "tuple[TestClient, str]", raw_id: str, quoted: str
    ) -> None:
        client, session_id = mcp_session
        response = client.post(
            "/mcp",
            headers={**_HANDSHAKE_HEADERS, "Mcp-Session-Id": session_id},
            content='{"jsonrpc":"2.0","id":%s,"method":"ping"}' % raw_id,
        )

        assert response.status_code != 202, (
            "the transport accepted a request it will never answer: "
            f"{response.status_code} {response.text!r}"
        )
        assert response.status_code == 400, response.text
        body = response.json()
        assert body["id"] is None
        assert body["error"]["code"] == -32600
        message = body["error"]["message"]
        assert "a request id must be a string or an integer" in message
        assert quoted in message, message

    def test_http_still_answers_a_usable_id(
        self, mcp_session: "tuple[TestClient, str]"
    ) -> None:
        """The positive half: a well-formed ping is served, not gated."""
        client, session_id = mcp_session
        response = client.post(
            "/mcp",
            headers={**_HANDSHAKE_HEADERS, "Mcp-Session-Id": session_id},
            content='{"jsonrpc":"2.0","id":77,"method":"ping"}',
        )

        assert response.status_code == 200, response.text
        payload = _sse_payload(response.text)
        assert payload is not None and payload["id"] == 77, response.text
        assert "result" in payload

    @pytest.mark.parametrize(("raw_id", "quoted"), UNUSABLE)
    def test_stdio_answers_instead_of_dropping(
        self, tmp_path: Path, raw_id: str, quoted: str
    ) -> None:
        """The same judgement on the transport that already had half of it."""
        responses = _one_shot_stdio_frames(
            tmp_path,
            [
                _INITIALIZE,
                '{"jsonrpc":"2.0","method":"notifications/initialized"}',
                '{"jsonrpc":"2.0","id":%s,"method":"ping"}' % raw_id,
                '{"jsonrpc":"2.0","id":42,"method":"ping"}',
            ],
        )

        rejections = [
            r
            for r in responses
            if "error" in r and "request id must be" in r["error"]["message"]
        ]
        assert len(rejections) == 1, responses
        assert rejections[0]["id"] is None
        assert rejections[0]["error"]["code"] == -32600
        assert quoted in rejections[0]["error"]["message"]
        # Paired positive: the frame after it is still served normally.
        served = [r for r in responses if r.get("id") == 42]
        assert served and "result" in served[0], responses


class TestResumeHeaderOpensAFreshStream:
    """fid 108 — GET with any non-empty ``Last-Event-ID`` was a 500 + traceback.

    The SDK returns straight out of ``_replay_events``, which is
    ``if not event_store: return``. This server configures none, so the ASGI
    app answered nothing and Starlette raised ``No response returned.``. The
    header is advertised in ``CORS_ALLOW_HEADERS`` so browser clients can
    resume a dropped stream, and a 500 tells every proxy and health checker
    the server faulted.
    """

    @pytest.mark.parametrize(
        "header_value", ["1", "0", "abc", "1_2", ""], ids=lambda v: repr(v)
    )
    def test_get_stream_opens(
        self, mcp_session: "tuple[TestClient, str]", header_value: str
    ) -> None:
        client, session_id = mcp_session
        headers = {"Accept": "text/event-stream", "Mcp-Session-Id": session_id}
        if header_value:
            headers["Last-Event-ID"] = header_value

        status, content_type, failures = _open_get_stream(client, headers)

        assert not failures, (
            f"Last-Event-ID={header_value!r} raised out of the ASGI app: "
            f"{failures!r}"
        )
        assert (
            status == 200
        ), f"Last-Event-ID={header_value!r} faulted the server: {status}"
        assert content_type.startswith("text/event-stream"), content_type


class TestMalformedFramesShareOneVocabulary:
    """fid 109 — HTTP answered ``-32602`` plus a 1.2 KB pydantic union dump.

    ``-32602`` is "Invalid params", which is wrong twice over: the frame never
    reached params, and a client branching on the code retries the params.
    stdio already classified these three shapes into ``-32600`` with one
    actionable sentence each; HTTP now says the same thing.
    """

    CASES = [
        pytest.param(
            '[{"jsonrpc":"2.0","id":8,"method":"ping"}]',
            "JSON-RPC batches are not supported by MCP",
            None,
            id="batch-array",
        ),
        pytest.param(
            '"hello"',
            "a JSON-RPC message must be an object",
            None,
            id="bare-string",
        ),
        pytest.param(
            '{"id":9,"method":"ping"}',
            "not a JSON-RPC 2.0 request, notification or response",
            9,
            id="missing-jsonrpc",
        ),
    ]

    @pytest.mark.parametrize(("body", "expected_message", "echoed_id"), CASES)
    def test_http_matches_the_stdio_wording(
        self,
        mcp_session: "tuple[TestClient, str]",
        body: str,
        expected_message: str,
        echoed_id: "int | None",
    ) -> None:
        client, session_id = mcp_session
        response = client.post(
            "/mcp",
            headers={**_HANDSHAKE_HEADERS, "Mcp-Session-Id": session_id},
            content=body,
        )

        assert response.status_code == 400, response.text
        payload = response.json()
        assert payload["error"]["code"] == -32600, payload
        assert expected_message in payload["error"]["message"], payload
        assert payload["id"] == echoed_id, payload
        # The pydantic dump is what made the old body useless to a reader.
        assert "errors.pydantic.dev" not in response.text
        assert len(response.content) < 400, len(response.content)

    @pytest.mark.parametrize(("body", "expected_message", "echoed_id"), CASES)
    def test_stdio_says_the_same(
        self,
        tmp_path: Path,
        body: str,
        expected_message: str,
        echoed_id: "int | None",
    ) -> None:
        responses = _one_shot_stdio_frames(
            tmp_path,
            [
                _INITIALIZE,
                '{"jsonrpc":"2.0","method":"notifications/initialized"}',
                body,
            ],
        )
        errors = [r for r in responses if "error" in r]
        matched = [r for r in errors if expected_message in r["error"]["message"]]
        assert matched, responses
        # The HTTP half checks the code and the echoed id; this one asserted
        # only a substring, so stdio could have answered the right sentence
        # under the wrong code and nothing would have said so.
        assert matched[0]["error"]["code"] == -32600, matched[0]
        assert matched[0].get("id") == echoed_id, matched[0]

    @pytest.mark.parametrize(("body", "expected_message", "echoed_id"), CASES)
    def test_the_two_transports_send_the_same_sentence(
        self,
        mcp_session: "tuple[TestClient, str]",
        tmp_path: Path,
        body: str,
        expected_message: str,
        echoed_id: "int | None",
    ) -> None:
        """The property this class is named for, actually asserted.

        Audit residue on fid 109: the two halves above each checked their own
        transport against an independently chosen substring and were never
        compared to each other, so the wordings could drift apart silently —
        proven by replacing the shared ``_BATCH_UNSUPPORTED`` constant in the
        HTTP branch with a divergent sentence and watching all six pass. One
        vocabulary is the whole point: a client that learns a rejection on
        stdio must recognise the same rejection over HTTP.
        """
        client, session_id = mcp_session
        http = client.post(
            "/mcp",
            headers={**_HANDSHAKE_HEADERS, "Mcp-Session-Id": session_id},
            content=body,
        ).json()

        responses = _one_shot_stdio_frames(
            tmp_path,
            [
                _INITIALIZE,
                '{"jsonrpc":"2.0","method":"notifications/initialized"}',
                body,
            ],
        )
        stdio = next(
            r
            for r in responses
            if "error" in r and expected_message in r["error"]["message"]
        )

        assert http["error"]["message"] == stdio["error"]["message"], (
            http["error"]["message"],
            stdio["error"]["message"],
        )
        assert http["error"]["code"] == stdio["error"]["code"]
        assert http["id"] == stdio.get("id")


class TestTrailingSlashEndpointIsServed:
    """fid 113 — ``/mcp/`` was a bodyless 307 real MCP clients do not follow.

    The official SDK client died with ``Unexpected content type: `` (empty
    value), naming neither the URL nor the redirect, while the same client
    worked one character away.
    """

    def test_initialize_over_the_trailing_slash_url(self, tmp_path: Path) -> None:
        client, _server = _build_http_client(tmp_path)
        with client:
            response = client.post(
                "/mcp/",
                headers=_HANDSHAKE_HEADERS,
                content=_INITIALIZE,
                follow_redirects=False,
            )

        assert response.status_code == 200, (
            f"/mcp/ answered {response.status_code}; "
            f"location={response.headers.get('location')!r}"
        )
        assert response.headers.get("mcp-session-id")
        payload = _sse_payload(response.text)
        assert payload is not None and "result" in payload, response.text

    @pytest.mark.parametrize("path", ["//mcp", "/MCP", "/mcp/x"])
    def test_neighbouring_paths_still_404(self, tmp_path: Path, path: str) -> None:
        """Only the one trailing slash is canonicalised, nothing wider."""
        client, _server = _build_http_client(tmp_path)
        with client:
            response = client.post(
                path,
                headers=_HANDSHAKE_HEADERS,
                content=_INITIALIZE,
                follow_redirects=False,
            )
        assert response.status_code == 404, response.status_code


# --------------------------------------------------------------------------
# Server state — the zim_health payload and the cache behind it
# --------------------------------------------------------------------------

# The first bytes of a real ZIM file: ``has_zim_signature`` reads exactly
# this, so a stub archive is enough to be counted as a loadable one.
_ZIM_SIGNATURE = b"\x5a\x49\x4d\x04"


def _stub_archive(path: Path) -> Path:
    path.write_bytes(_ZIM_SIGNATURE + b"\x00" * 64)
    return path


def _health(server: OpenZimMcpServer) -> "dict[str, Any]":
    """The ``zim_health`` payload the tool layer serves, through its own path."""
    import asyncio

    from openzim_mcp.async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)
    return dict(asyncio.run(ops.get_health_data(server))["health"])


def _server_on(directories: "list[str]", **cache_env: Any) -> OpenZimMcpServer:
    config = OpenZimMcpConfig(allowed_directories=directories, **cache_env)
    return OpenZimMcpServer(config)


class TestArchivesAreCountedOnce:
    """fid 12 — ``zim_files_found: 2`` for a single archive.

    Listing a directory twice, or a parent alongside its child, is an ordinary
    editing mistake in a hand-maintained client config. The health report then
    contradicted itself inside one response: ``zim_files_found: 2`` beside a
    ``loaded_archives`` list with one entry.
    """

    def test_same_directory_twice(self, tmp_path: Path) -> None:
        _stub_archive(tmp_path / "one.zim")
        server = _server_on([str(tmp_path), str(tmp_path)])

        health = _health(server)

        assert health["health_checks"]["zim_files_found"] == 1
        # Paired positive: the directory really was probed, twice.
        assert health["health_checks"]["directories_accessible"] == 2

    def test_parent_and_child_directory(self, tmp_path: Path) -> None:
        deep = tmp_path / "deep"
        deep.mkdir()
        _stub_archive(deep / "one.zim")
        server = _server_on([str(tmp_path), str(deep)])

        health = _health(server)

        assert health["health_checks"]["zim_files_found"] == 1
        assert health["health_checks"]["directories_accessible"] == 2

    def test_two_real_archives_are_still_two(self, tmp_path: Path) -> None:
        """The positive half: de-duplication must not collapse distinct files."""
        _stub_archive(tmp_path / "one.zim")
        _stub_archive(tmp_path / "two.zim")
        server = _server_on([str(tmp_path), str(tmp_path)])

        assert _health(server)["health_checks"]["zim_files_found"] == 2

    def test_a_duplicated_directory_does_not_double_its_warnings(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "garbage.zim").write_bytes(b"not a zim file at all")
        server = _server_on([str(tmp_path), str(tmp_path)])

        health = _health(server)

        signature_warnings = [
            w for w in health["warnings"] if "missing ZIM signature" in w
        ]
        assert len(signature_warnings) == 1, health["warnings"]


class TestFullCacheIsNamedAsFull:
    """fid 127 — the only cache advice blamed the caller for a capacity limit.

    A cache pinned at ``max_size`` and evicting drew "consider issuing
    repeated queries against the same ZIM files". A client that obeys that
    re-issues a query whose entry has already been evicted and misses again;
    capacity is the knob, and the report never mentioned it.
    """

    def test_full_cache_recommends_capacity_not_repetition(
        self, tmp_path: Path
    ) -> None:
        _stub_archive(tmp_path / "one.zim")
        server = _server_on([str(tmp_path)], cache={"max_size": 4})
        for index in range(60):
            server.cache.get(f"absent-{index}")
        for index in range(8):
            server.cache.set(f"key-{index}", {"payload": index})

        stats = server.cache.stats()
        assert stats["size"] == stats["max_size"] == 4, stats
        recommendations = _health(server)["recommendations"]

        assert any(
            "Cache is full" in line and "MAX_SIZE" in line for line in recommendations
        ), recommendations
        assert not any(
            "issuing repeated" in line for line in recommendations
        ), recommendations

    def test_a_cache_with_room_still_gets_the_hit_rate_advice(
        self, tmp_path: Path
    ) -> None:
        """The positive half: the existing advice is suppressed only when full."""
        _stub_archive(tmp_path / "one.zim")
        server = _server_on([str(tmp_path)], cache={"max_size": 500})
        for index in range(60):
            server.cache.get(f"absent-{index}")

        recommendations = _health(server)["recommendations"]

        assert any(
            "issuing repeated" in line for line in recommendations
        ), recommendations
        assert not any("Cache is full" in line for line in recommendations)


class TestBrokenPersistenceIsReported:
    """fid 133 — an unwritable cache directory was silent everywhere it counted.

    ``XDG_CACHE_HOME`` was read only inside a branch guarded by ``if
    configured_path:``, and ``persistence_path`` carries a ``default_factory``
    that is never falsy — so the branch, the parent ``mkdir`` and the
    "persistence will be disabled" fallback were all unreachable. An operator
    who redirected the cache under Docker got the old path anyway, and when it
    was read-only the only signal was a WARNING on stderr at process exit,
    while ``zim_health`` said ``Server is running optimally``.
    """

    def test_xdg_cache_home_is_honoured_for_the_default_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.config import CacheConfig

        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
        cache = OpenZimMcpCache(CacheConfig(persistence_enabled=True))
        try:
            path = Path(cache.stats()["persistence_path"])
        finally:
            cache.shutdown()

        assert path.parent == xdg, path
        assert path.name.startswith("openzim-mcp-"), path

    def test_an_explicit_path_still_wins_over_xdg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The positive half: XDG only rebases the untouched default."""
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.config import CacheConfig

        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        chosen = tmp_path / "chosen" / "snapshot"
        cache = OpenZimMcpCache(
            CacheConfig(persistence_enabled=True, persistence_path=str(chosen))
        )
        try:
            path = Path(cache.stats()["persistence_path"])
        finally:
            cache.shutdown()

        assert path == chosen.with_name(chosen.name + ".json"), path

    def test_health_says_so_when_the_cache_directory_is_unusable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_archive(tmp_path / "one.zim")
        # A regular file where the cache directory should be: ``mkdir`` fails
        # for every uid, so this reproduces the read-only-container shape
        # without depending on the test user's privileges.
        blocked = tmp_path / "blocked"
        blocked.write_bytes(b"not a directory")
        monkeypatch.setenv("XDG_CACHE_HOME", str(blocked))

        server = _server_on([str(tmp_path)], cache={"persistence_enabled": True})
        health = _health(server)

        assert health["status"] == "warning", health["status"]
        assert any(
            "Cache persistence is not working" in w for w in health["warnings"]
        ), health["warnings"]
        assert "Server is running optimally" not in health["recommendations"]

    def test_a_writable_cache_directory_raises_no_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The positive half: the warning is about a real failure, not noise."""
        _stub_archive(tmp_path / "one.zim")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "writable"))

        health = _health(
            _server_on([str(tmp_path)], cache={"persistence_enabled": True})
        )

        assert health["status"] == "healthy", health
        assert not any("Cache persistence" in w for w in health["warnings"]), health[
            "warnings"
        ]


class TestAnIdlePeerKeepsAWarmSnapshot:
    """fid 132 — an idle second server deleted another instance's warm cache.

    Two MCP clients on one desktop each spawn their own stdio server with
    identical default config, so they share one default snapshot path.
    Whichever one the user happened not to query saved nothing at exit and
    unlinked the other's file, so the accelerator did nothing at all for the
    multi-client setup it is aimed at.
    """

    def test_an_empty_save_leaves_a_peers_snapshot_alone(self, tmp_path: Path) -> None:
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.config import CacheConfig

        shared = str(tmp_path / "shared")
        config = CacheConfig(persistence_enabled=True, persistence_path=shared)

        warm = OpenZimMcpCache(config)
        warm.set("query:plato", {"answer": "warm"})
        warm.shutdown()
        snapshot = Path(warm.stats()["persistence_path"])
        assert snapshot.exists(), "the warm instance never wrote its snapshot"
        written = snapshot.read_bytes()

        idle = OpenZimMcpCache(CacheConfig(**config.model_dump()))
        idle._cache.clear()  # nothing was ever cached in this instance
        idle.shutdown()

        assert snapshot.exists(), "an idle peer deleted the warm snapshot"
        assert snapshot.read_bytes() == written

        reloaded = OpenZimMcpCache(CacheConfig(**config.model_dump()))
        try:
            assert reloaded.get("query:plato") == {"answer": "warm"}
        finally:
            reloaded.shutdown()

    def test_an_instance_still_clears_the_snapshot_it_wrote_itself(
        self, tmp_path: Path
    ) -> None:
        """The positive half: the hygiene the unlink existed for is intact."""
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.config import CacheConfig

        config = CacheConfig(
            persistence_enabled=True, persistence_path=str(tmp_path / "own")
        )
        cache = OpenZimMcpCache(config)
        cache.set("query:plato", {"answer": "warm"})
        cache._save_to_disk()
        snapshot = Path(cache.stats()["persistence_path"])
        assert snapshot.exists()

        cache.delete("query:plato")
        cache.shutdown()

        assert not snapshot.exists(), "its own emptied snapshot was left behind"


class TestUnknownToolGetsAnEnvelope:
    """fid 110 — an unknown tool name returned four words of plain text.

    ``instructions.py`` promises every client that a rejection arrives as
    ``isError`` with a JSON body carrying ``error``, ``operation`` and a
    ``message`` describing how to correct the call, and the argument path one
    line away delivers exactly that (difflib suggestion included). The tool
    *name* path returned ``Unknown tool: zim_search`` — no envelope, no
    did-you-mean, and in simple mode no hint that ``zim_query`` exists, which
    is precisely where a small model is most likely to be wrong.
    """

    @staticmethod
    def _call(server: OpenZimMcpServer, name: str) -> "dict[str, Any]":
        import asyncio

        result = asyncio.run(server.mcp.call_tool(name, {}))
        assert result.is_error, result
        text = "".join(block.text for block in result.content if hasattr(block, "text"))
        return json.loads(text)

    def test_simple_mode_points_at_the_only_tool_there_is(self, tmp_path: Path) -> None:
        _stub_archive(tmp_path / "one.zim")
        server = _server_on([str(tmp_path)], tool_mode="simple")

        body = self._call(server, "zim_search")

        assert body["error"] is True
        assert body["operation"] == "unknown_tool"
        assert "zim_search" in body["message"]
        assert "zim_query" in body["message"]
        assert body["available_tools"] == ["zim_query"]

    @pytest.mark.parametrize(
        "absent", ["zim_get", "zim_health", "zim_metadata", "search"]
    )
    def test_simple_mode_never_names_a_tool_the_client_cannot_call(
        self, tmp_path: Path, absent: str
    ) -> None:
        _stub_archive(tmp_path / "one.zim")
        server = _server_on([str(tmp_path)], tool_mode="simple")

        body = self._call(server, absent)

        assert body["available_tools"] == ["zim_query"]
        assert absent not in body["available_tools"]

    def test_advanced_mode_suggests_the_typo_target(self, tmp_path: Path) -> None:
        _stub_archive(tmp_path / "one.zim")
        server = _server_on([str(tmp_path)], tool_mode="advanced")

        body = self._call(server, "zim_serch")

        assert body["operation"] == "unknown_tool"
        assert body["closest_match"] == "zim_search"
        assert "zim_search" in body["message"]
        assert "zim_health" in body["available_tools"]

    def test_a_real_tool_still_runs(self, tmp_path: Path) -> None:
        """The positive half: the gate rejects only names that do not exist."""
        import asyncio

        _stub_archive(tmp_path / "one.zim")
        server = _server_on([str(tmp_path)], tool_mode="advanced")

        result = asyncio.run(server.mcp.call_tool("zim_health", {}))

        assert not result.is_error, result


class TestNothingClaimsStreamResumptionWorks:
    """fid 108's audit residue — the fix falsified text it left behind.

    ``UnsupportedResumeHeaderMiddleware`` strips ``Last-Event-ID``
    unconditionally, so resumption is now a deliberate, permanent, silent
    no-op. Before the fix a client that believed the docs got a loud 500;
    after it, the same client gets a silently fresh stream. Five places
    still told a reader otherwise, including a comment in the very file the
    fix edits and the docstring of the test the finding named as unable to
    see the defect.
    """

    #: Prose that asserts the header does something it does not do.
    CLAIMS = (
        "resume a dropped stream",
        "resume dropped streams",
        "resume interrupted streams",
        "resume an interrupted stream",
    )

    def _sources(self):
        repo = Path(__file__).resolve().parent.parent
        for pattern in ("openzim_mcp/**/*.py", "tests/**/*.py"):
            yield from repo.glob(pattern)
        yield from (repo / "website/src/content/docs").glob("*.mdx")
        yield repo / "README.md"

    def test_no_file_says_last_event_id_resumes_anything(self) -> None:
        offenders = []
        for path in self._sources():
            if not path.is_file():
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if "Last-Event-ID" not in line:
                    continue
                for claim in self.CLAIMS:
                    if claim in line:
                        offenders.append(f"{path.name}:{lineno}: {claim!r}")

        assert not offenders, (
            "Last-Event-ID is stripped by UnsupportedResumeHeaderMiddleware "
            "and this server keeps no event store, so nothing resumes: "
            + "; ".join(offenders)
        )

    def test_the_header_is_still_allowed_by_cors(self) -> None:
        """Paired with the test above so "says nothing about it" cannot be
        satisfied by removing the header from the allow-list — a browser
        client that sends it must not be blocked, it just must not be
        promised a resume."""
        from openzim_mcp.http_app import CORS_ALLOW_HEADERS

        assert any(
            h.lower() == "last-event-id" for h in CORS_ALLOW_HEADERS
        ), CORS_ALLOW_HEADERS
