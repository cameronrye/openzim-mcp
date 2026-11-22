"""Regressions from the 2026-11 sweep of the HTTP server, its config and limits.

Each class pins one defect that reproduced against ``main`` at e945188 —
in-process through the production-wired ASGI app wherever the defect lives on
the wire — and names the inputs that exposed it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from openzim_mcp import http_app
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpConfigurationError
from openzim_mcp.server import OpenZimMcpServer

_MODERN = "2026-07-28"
_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": _MODERN,
    "io.modelcontextprotocol/clientCapabilities": {},
}


def _http_app(directory: Path, **overrides: Any) -> Tuple[OpenZimMcpServer, Any]:
    """The production-wired streamable-HTTP app, captured instead of served."""
    settings: Dict[str, Any] = dict(
        allowed_directories=[str(directory)],
        transport="http",
        host="127.0.0.1",
        port=8791,
    )
    settings.update(overrides)
    server = OpenZimMcpServer(OpenZimMcpConfig(**settings))
    captured: List[Any] = []
    http_app.serve_streamable_http(
        server, runner=lambda app, host, port: captured.append(app)
    )
    return server, captured[0]


def _modern_request(
    method: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    name: Optional[str] = None,
    request_id: int = 1,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """A stateless 2026-07-28 POST: the JSON-RPC body and the headers it needs."""
    body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {**(params or {}), "_meta": _MODERN_META},
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": _MODERN,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return body, headers


class TestBindAllKeepsTheOriginCheck:
    """A bind-all host with no allowed hosts dropped the Origin check too.

    The SDK runs its Host and Origin checks under one flag. A server bound to
    ``0.0.0.0`` with no ``OPENZIM_MCP_ALLOWED_HOSTS`` turns that flag off,
    because a direct-IP ``Host`` varies by interface and any allow-list would
    421 every client — and with it went the Origin check, which nothing about
    the bind makes unknowable. On the documented Docker-bridge/LAN mode
    (``OPENZIM_MCP_INSECURE_DISABLE_AUTH=1``) a DNS-rebinding page at
    ``http://evil.example:8000`` was answered 200 with tool output.
    """

    # (cors_origins, Origin header or None, expected status)
    _CASES = [
        ([], "http://evil.example:8000", 403),
        ([], None, 200),
        (["https://app.example"], "https://app.example", 200),
        (["https://app.example"], "https://evil.example", 403),
        # The SDK's ``:*`` wildcard-port form, which a loopback bind honours.
        (["http://localhost:*"], "http://localhost:5173", 200),
    ]

    @staticmethod
    def _status(
        tmp_path: Path, host: str, cors_origins: List[str], origin: Optional[str]
    ) -> int:
        overrides: Dict[str, Any] = {"host": host, "cors_origins": cors_origins}
        if host == "0.0.0.0":  # noqa: S104 - exercising the bind-all branch
            overrides["insecure_disable_auth"] = True
            # A rebinding page's Host is its own name: nothing checks it here.
            base_url = "http://evil.example:8000"
        else:
            base_url = "http://127.0.0.1:8791"
        server, app = _http_app(tmp_path, **overrides)
        body, headers = _modern_request("tools/list")
        if origin is not None:
            headers["Origin"] = origin
        with TestClient(app, base_url=base_url) as client:
            response = client.post("/mcp", json=body, headers=headers)
        if response.status_code == 403:
            assert response.text == "Invalid Origin header", response.text
        else:
            assert "result" in response.json(), response.text
        return response.status_code

    @pytest.mark.parametrize("cors_origins, origin, expected", _CASES)
    def test_bind_all_answers_an_origin_on_its_merits(
        self,
        tmp_path: Path,
        cors_origins: List[str],
        origin: Optional[str],
        expected: int,
    ) -> None:
        assert (
            self._status(tmp_path, "0.0.0.0", cors_origins, origin)  # noqa: S104
            == expected
        )

    @pytest.mark.parametrize("cors_origins, origin, expected", _CASES)
    def test_the_verdict_matches_a_loopback_bind(
        self,
        tmp_path: Path,
        cors_origins: List[str],
        origin: Optional[str],
        expected: int,
    ) -> None:
        """On loopback the SDK checks Origin itself; the two must agree."""
        assert self._status(tmp_path, "127.0.0.1", cors_origins, origin) == expected


class TestABlankTokenIsNoTokenEverywhere:
    """The startup check and the auth middleware disagreed on a blank token.

    Config validation refuses ``OPENZIM_MCP_AUTH_TOKEN=""``, but
    ``model_copy`` skips validators, and ``instructions.py`` already treats a
    ``model_copy`` as a real way to build a config. ``check_safe_startup``
    counted any non-``None`` token as set, while the middleware normalises a
    blank one to "no auth" — so ``0.0.0.0`` with ``SecretStr("")`` started
    without the INSECURE warning and then served every caller.
    """

    @staticmethod
    def _bind_all(tmp_path: Path, **overrides: Any) -> OpenZimMcpConfig:
        return OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)],
            transport="http",
            host="0.0.0.0",  # noqa: S104 - exercising the bind-all branch
            auth_token="s3cret",
            **overrides,
        )

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    def test_startup_refuses_a_bind_all_server_whose_token_is_blank(
        self, tmp_path: Path, blank: str
    ) -> None:
        config = self._bind_all(tmp_path).model_copy(
            update={"auth_token": SecretStr(blank)}
        )
        with pytest.raises(OpenZimMcpConfigurationError, match="requires auth"):
            http_app.check_safe_startup(config)

    def test_the_real_token_it_was_copied_from_still_starts(
        self, tmp_path: Path
    ) -> None:
        http_app.check_safe_startup(self._bind_all(tmp_path))

    def test_with_the_escape_hatch_a_blank_token_gets_the_insecure_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Blank is unset, so the acknowledged no-auth mode says so out loud."""
        config = self._bind_all(tmp_path, insecure_disable_auth=True).model_copy(
            update={"auth_token": SecretStr("")}
        )
        with caplog.at_level("WARNING", logger="openzim_mcp.http_app"):
            http_app.check_safe_startup(config)
        assert any("INSECURE" in r.getMessage() for r in caplog.records)


class TestATokenNoClientCanSendIsRefused:
    """A token with surrounding whitespace locked every client out.

    ``openssl rand -hex 32 > token`` writes a trailing newline, and a
    Kubernetes Secret made from that file hands it to the server verbatim.
    The HTTP parser strips the whitespace around a header value, so the
    presented ``Bearer <hex>`` can never equal ``<hex>\\n`` and every request
    got a 401, with nothing at startup to say why. A control character
    inside the token is the same lockout: a header cannot carry one.
    """

    @staticmethod
    def _load(tmp_path: Path, token: str) -> OpenZimMcpConfig:
        return OpenZimMcpConfig(allowed_directories=[str(tmp_path)], auth_token=token)

    @pytest.mark.parametrize("token", ["s3cret\n", "s3cret\r\n", " s3cret", "s3cret "])
    def test_surrounding_whitespace_is_refused_at_load(
        self, tmp_path: Path, token: str
    ) -> None:
        with pytest.raises(OpenZimMcpConfigurationError, match="trailing whitespace"):
            self._load(tmp_path, token)

    @pytest.mark.parametrize("token", ["s3\x00cret", "s3\x1b[0mcret", "s3\ncret"])
    def test_a_control_character_is_refused_at_load(
        self, tmp_path: Path, token: str
    ) -> None:
        with pytest.raises(OpenZimMcpConfigurationError, match="control character"):
            self._load(tmp_path, token)

    def test_the_variable_read_from_a_token_file_is_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENZIM_MCP_AUTH_TOKEN", "0123abcd\n")
        with pytest.raises(OpenZimMcpConfigurationError) as excinfo:
            OpenZimMcpConfig(allowed_directories=[str(tmp_path)])
        assert "OPENZIM_MCP_AUTH_TOKEN" in str(excinfo.value)

    @pytest.mark.parametrize("token", ["s3cret", "0123abcd" * 8, "a-b_c.d~e+f/g="])
    def test_a_token_a_client_can_send_still_loads(
        self, tmp_path: Path, token: str
    ) -> None:
        loaded = self._load(tmp_path, token).auth_token
        assert loaded is not None and loaded.get_secret_value() == token


@pytest.fixture
def small_zim_dir(tmp_path: Path, zim_test_data_dir: Optional[Path]) -> Path:
    """A directory holding the test suite's ``withns/small.zim``, alone."""
    source = zim_test_data_dir / "withns" / "small.zim" if zim_test_data_dir else None
    if source is None or not source.exists():
        pytest.skip("withns/small.zim fixture not available")
    shutil.copyfile(source, tmp_path / "small.zim")
    return tmp_path


def _post(
    client: TestClient,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """One modern request; the JSON-RPC response it was answered with."""
    body, headers = _modern_request(method, params, name=name)
    response = client.post("/mcp", json=body, headers=headers)
    assert response.status_code == 200, response.text
    payload: Dict[str, Any] = response.json()
    return payload


class TestResourceReadsAreRateLimited:
    """``resources/read`` never touched the rate limiter.

    Only the tool wrappers called ``enforce_rate_limit``. With a burst of 1
    the second ``zim_get`` came back ``rate_limited`` and then
    ``resources/read zim://small/entry/A%2Fmain.html`` served the same entry
    20 times out of 20: the resource surface was an unmetered side door to
    every archive read the tools meter.
    """

    _URIS = [
        "zim://small/entry/A%2Fmain.html",
        "zim://small",
        "zim://files",
    ]

    @staticmethod
    def _client(directory: Path) -> TestClient:
        _server, app = _http_app(
            directory,
            tool_mode="advanced",
            # One token, and none back for the length of the test.
            rate_limit={"burst_size": 1, "requests_per_second": 0.001},
        )
        return TestClient(app, base_url="http://127.0.0.1:8791")

    @staticmethod
    def _read(client: TestClient, uri: str) -> Dict[str, Any]:
        return _post(client, "resources/read", {"uri": uri}, name=uri)

    @staticmethod
    def _assert_rate_limited(payload: Dict[str, Any]) -> None:
        assert "error" in payload, payload
        error = payload["error"]
        assert error["code"] == -32603, error
        assert error["data"]["operation"] == "rate_limited", error
        assert "rate limit exceeded" in error["message"].lower(), error

    @pytest.mark.parametrize("uri", _URIS)
    def test_a_read_past_the_burst_is_refused(
        self, small_zim_dir: Path, uri: str
    ) -> None:
        with self._client(small_zim_dir) as client:
            first = self._read(client, uri)
            second = self._read(client, uri)
        assert first["result"]["contents"], first
        self._assert_rate_limited(second)

    @pytest.mark.parametrize(
        "uri, operation",
        [
            ("zim://small/entry/A%2Fmain.html", "get_entry"),
            ("zim://small", "get_metadata"),
            ("zim://files", "zim_files"),
        ],
    )
    def test_a_per_operation_limit_reaches_the_read_it_names(
        self, small_zim_dir: Path, uri: str, operation: str
    ) -> None:
        """Keyed like the tool counterpart, so an operator's override applies."""
        _server, app = _http_app(
            small_zim_dir,
            tool_mode="advanced",
            rate_limit={
                "per_operation_limits": {
                    operation: {"burst_size": 1, "requests_per_second": 0.001}
                }
            },
        )
        with TestClient(app, base_url="http://127.0.0.1:8791") as client:
            first = self._read(client, uri)
            second = self._read(client, uri)
        assert first["result"]["contents"], first
        self._assert_rate_limited(second)
        assert f"'{operation}'" in second["error"]["message"], second

    def test_the_resource_surface_is_no_side_door_past_a_rate_limited_tool(
        self, small_zim_dir: Path
    ) -> None:
        """The reported sequence: the tool is refused, so the read must be too."""
        arguments = {
            "zim_file_path": str(small_zim_dir / "small.zim"),
            "entry_path": "A/main.html",
        }
        call = {"name": "zim_get", "arguments": arguments}
        with self._client(small_zim_dir) as client:
            served = _post(client, "tools/call", call, name="zim_get")
            refused = _post(client, "tools/call", call, name="zim_get")
            read = self._read(client, "zim://small/entry/A%2Fmain.html")
        assert served["result"]["isError"] is False, served
        refused_body = json.loads(refused["result"]["content"][0]["text"])
        assert refused_body["operation"] == "rate_limited", refused_body
        self._assert_rate_limited(read)


class TestForwardedForMintsNoBucket:
    """``X-Forwarded-For`` handed every caller a fresh rate-limit bucket.

    Without a token the limiter keys a client on ``request.client.host``, and
    uvicorn's ``proxy_headers`` default rewrites that from ``X-Forwarded-For``
    whenever the peer is ``127.0.0.1`` — which, on the default loopback bind,
    is every peer. So any caller could name a new address per request and
    never be limited. Nothing here reads a forwarded header on purpose.
    """

    @staticmethod
    def _served_config(monkeypatch: pytest.MonkeyPatch) -> Any:
        """The real ``uvicorn.Config`` the default runner builds, unserved."""
        import uvicorn

        built: List[Any] = []

        class _NoServe:
            def __init__(self, config: Any) -> None:
                built.append(config)

            def run(self) -> None:
                return None

        monkeypatch.setattr(uvicorn, "Server", _NoServe)
        app = http_app.build_starlette_app(object())  # type: ignore[arg-type]
        http_app._default_uvicorn_runner(app, "127.0.0.1", 8000)
        return built[0]

    def test_the_served_app_reads_no_forwarded_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        config = self._served_config(monkeypatch)
        config.load()

        assert config.proxy_headers is False
        assert not isinstance(config.loaded_app, ProxyHeadersMiddleware)
        # Paired positive: the bind still reaches uvicorn as given.
        assert (config.host, config.port) == ("127.0.0.1", 8000)

    def test_uvicorns_own_default_would_have_read_them(self) -> None:
        """The control: the probe above can see the middleware when it is there."""
        import uvicorn
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        config = uvicorn.Config(http_app.build_starlette_app(object()))  # type: ignore[arg-type]
        config.load()
        assert isinstance(config.loaded_app, ProxyHeadersMiddleware)


class TestHealthKeepsTheCacheDirectoryPrivate:
    """``zim_health`` over HTTP leaked the cache directory in two places.

    The report masks ``persistence_path`` for a network client, but not
    ``persistence_error`` — nor the warning built from it — and that message
    named the directory twice: once on its own and again inside the
    ``OSError`` text. A remote client learned the server account's home
    layout from a cache it can never use.
    """

    @staticmethod
    def _unusable_cache_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        # A regular file in the way makes ``mkdir`` fail for every uid, the
        # way a read-only container's home does.
        blocker = tmp_path / "not-a-dir"
        blocker.write_bytes(b"x")
        cache_home = blocker / "secret-user-home" / ".cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
        return cache_home

    @staticmethod
    def _mkdir_reason(directory: Path) -> str:
        """The reason this OS gives for the ``mkdir`` the cache attempts.

        POSIX says "Not a directory"; Windows reports the file in the way as
        "Cannot create a file when that file already exists".
        """
        with pytest.raises(OSError) as refused:
            directory.mkdir(parents=True, exist_ok=True)
        return str(refused.value.strerror)

    @staticmethod
    def _health(tmp_path: Path, transport: str) -> Dict[str, Any]:
        import asyncio

        from openzim_mcp.async_operations import AsyncZimOperations

        archives = tmp_path / "zims"
        archives.mkdir()
        server = OpenZimMcpServer(
            OpenZimMcpConfig(
                allowed_directories=[str(archives)],
                transport=transport,
                cache={"persistence_enabled": True},
            )
        )
        ops = AsyncZimOperations(server.zim_operations)
        payload: Dict[str, Any] = asyncio.run(ops.get_health_data(server))
        server.cache.shutdown()
        return payload

    def test_a_network_client_is_not_told_where_the_cache_lives(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache_home = self._unusable_cache_home(tmp_path, monkeypatch)
        payload = self._health(tmp_path, "http")
        health = payload["health"]

        serialized = json.dumps(payload)
        assert "secret-user-home" not in serialized, health["cache_performance"]
        assert str(tmp_path / "not-a-dir") not in serialized
        # Paired positive: the failure is still reported, with its reason.
        warning = next(
            w for w in health["warnings"] if "Cache persistence is not working" in w
        )
        assert self._mkdir_reason(cache_home) in warning, warning

    def test_a_local_operator_still_gets_the_directory_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On stdio the path is the operator's to fix, so it stays — once."""
        cache_home = self._unusable_cache_home(tmp_path, monkeypatch)
        error = self._health(tmp_path, "stdio")["health"]["cache_performance"][
            "persistence_error"
        ]
        assert error.count(str(cache_home)) == 1, error
        assert "secret-user-home" in error, error
        assert "[Errno" not in error and "[WinError" not in error, error
        assert self._mkdir_reason(cache_home) in error, error

    def test_a_failed_save_names_its_file_once(self, tmp_path: Path) -> None:
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.config import CacheConfig

        blocker = tmp_path / "not-a-dir"
        blocker.write_bytes(b"x")
        target = blocker / "cache" / "snapshot"
        cache = OpenZimMcpCache(
            CacheConfig(persistence_enabled=True, persistence_path=str(target))
        )
        cache.set("key", {"value": 1})
        cache.shutdown()  # the save, which cannot create the directory

        error = cache.stats()["persistence_error"]
        assert error.count(str(target)) == 1, error
        assert "[Errno" not in error and "[WinError" not in error, error
        assert self._mkdir_reason(target.parent) in error, error


class TestSimpleModeOffersNoSubscriptions:
    """Simple mode advertised resource subscriptions it has nothing to serve.

    Resources are registered only in advanced mode, so a simple-mode server's
    ``resources/list`` is empty. Over HTTP it built the subscription bus
    anyway: ``server/discover`` said ``resources: {listChanged: true,
    subscribe: true}``, ``subscriptions/listen`` was acknowledged, and a
    directory watcher polled every five seconds to announce changes to
    resources no client could list or read.
    """

    @staticmethod
    def _capabilities(app: Any) -> Dict[str, Any]:
        with TestClient(app, base_url="http://127.0.0.1:8791") as client:
            payload = _post(client, "server/discover")
        capabilities: Dict[str, Any] = payload["result"]["capabilities"]
        return capabilities

    def test_listen_is_method_not_found(self, tmp_path: Path) -> None:
        from tests.test_stateless_http import _drive

        server, app = _http_app(tmp_path)
        assert server.config.tool_mode == "simple"
        body, headers = _modern_request(
            "subscriptions/listen", {"notifications": {"resourcesListChanged": True}}
        )
        with TestClient(app, base_url="http://127.0.0.1:8791") as client:
            exchange = _drive(client, "POST", headers, json.dumps(body).encode())
        assert not exchange.is_event_stream, "a listen stream was acknowledged"
        assert json.loads(exchange.body)["error"]["code"] == -32601, exchange.body
        assert server.subscription_bus is None

    def test_discover_advertises_no_subscription(self, tmp_path: Path) -> None:
        _server, app = _http_app(tmp_path)
        resources = self._capabilities(app).get("resources") or {}
        assert not resources.get("subscribe"), resources
        assert not resources.get("listChanged"), resources

    def test_no_watcher_polls_for_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import openzim_mcp.subscriptions as subscriptions

        built: List[str] = []
        real = subscriptions.MtimeWatcher

        def counting(*args: Any, **kwargs: Any) -> Any:
            built.append("watcher")
            return real(*args, **kwargs)

        monkeypatch.setattr(subscriptions, "MtimeWatcher", counting)
        _http_app(tmp_path)
        assert built == []
        # Paired positive: the counter sees the advanced server's watcher.
        _http_app(tmp_path, tool_mode="advanced")
        assert built == ["watcher"]

    def test_advanced_mode_still_offers_them(self, tmp_path: Path) -> None:
        server, app = _http_app(tmp_path, tool_mode="advanced")
        assert server.subscription_bus is not None
        resources = self._capabilities(app)["resources"]
        assert resources["subscribe"] is True and resources["listChanged"] is True


class TestAuthFailuresCannotWriteToTheTerminal:
    """An unauthenticated caller could put terminal escapes into the log.

    The auth-failure line logged the percent-decoded request path and the
    client address verbatim, so ``GET /mcp%1B%5B2J%1B%5B31mAUTH-OK`` cleared
    an operator's terminal and printed a red ``AUTH-OK`` — from a request
    that needed no token to send, on the one log line meant for spotting
    attacks.
    """

    @staticmethod
    def _app() -> Any:
        from unittest.mock import MagicMock

        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        config = MagicMock()
        config.auth_token = SecretStr("topsecret")

        async def protected(request: Any) -> PlainTextResponse:
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/mcp", protected)])
        app.add_middleware(http_app.BearerTokenAuthMiddleware, config=config)
        return app

    @pytest.mark.asyncio
    async def test_the_failure_line_carries_no_control_characters(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import httpx

        transport = httpx.ASGITransport(
            app=self._app(), client=("10.0.0.9\x1b[0m", 5555)
        )
        with caplog.at_level("WARNING", logger="openzim_mcp.http_app"):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://127.0.0.1"
            ) as client:
                response = await client.get("/mcp%1B%5B2J%1B%5B31mAUTH-OK%07")
        assert response.status_code == 401

        lines = [
            r.getMessage() for r in caplog.records if "auth failure" in r.getMessage()
        ]
        assert len(lines) == 1, lines
        assert not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in lines[0]), lines
        # Paired positive: the line still says who failed, where, and why.
        assert "missing_or_wrong_scheme" in lines[0]
        assert "10.0.0.9" in lines[0] and "AUTH-OK" in lines[0], lines


class TestHealthPathsTolerateATrailingSlash:
    """``/healthz/`` answered 401 on a server with a token.

    Auth runs ahead of routing and matched the exempt paths exactly, so the
    probe URL a person types with a trailing slash — which the router would
    redirect to ``/healthz`` — was refused as unauthenticated instead, and
    the Host/Origin gate refused it the same way. One trailing slash is
    tolerated now; nothing else is opened.
    """

    @staticmethod
    def _client(tmp_path: Path, base_url: str = "http://127.0.0.1:8791") -> Any:
        _server, app = _http_app(tmp_path, auth_token="s3cret")
        return TestClient(app, base_url=base_url, follow_redirects=False)

    @pytest.mark.parametrize("path", ["/healthz/", "/readyz/"])
    def test_one_trailing_slash_reaches_the_probe_without_a_token(
        self, tmp_path: Path, path: str
    ) -> None:
        with self._client(tmp_path) as client:
            redirected = client.get(path)
            assert redirected.status_code == 307, redirected.text
            assert redirected.headers["location"].endswith(path.rstrip("/"))
            assert client.get(redirected.headers["location"]).status_code == 200

    @pytest.mark.parametrize(
        "path", ["/healthz//", "/healthz/x", "/healthzx", "//healthz", "/", "/mcp/"]
    )
    def test_every_other_path_still_needs_the_token(
        self, tmp_path: Path, path: str
    ) -> None:
        with self._client(tmp_path) as client:
            assert client.get(path).status_code == 401, path

    def test_the_host_gate_lets_it_through_too(self, tmp_path: Path) -> None:
        """A probe addressed by pod IP is not refused for its Host either."""
        with self._client(tmp_path, base_url="http://10.1.2.3:8000") as client:
            assert client.get("/healthz/").status_code == 307
            # Paired negative: past the token, the gate still refuses that Host.
            refused = client.get(
                "/healthz//", headers={"Authorization": "Bearer s3cret"}
            )
            assert refused.status_code == 421, refused.text


class TestTheRefillRateMustBeFinite:
    """``requests_per_second=nan`` turned rate limiting off.

    The validator refused ``v <= 0``, which is false for NaN, so NaN loaded;
    the bucket's refill then computed ``min(capacity, tokens + elapsed * nan)``,
    which ``min`` answers with ``capacity``, and every acquire succeeded.
    ``inf`` did the same through ``elapsed * inf``. Every other float in the
    config is bounded on both sides, which pydantic already enforces for NaN.
    """

    @pytest.mark.parametrize("rate", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_rate_is_refused(self, rate: float) -> None:
        from pydantic import ValidationError

        from openzim_mcp.rate_limiter import RateLimitConfig

        with pytest.raises(ValidationError, match="finite"):
            RateLimitConfig(requests_per_second=rate)

    @pytest.mark.parametrize("raw", ["nan", "inf", "Infinity"])
    def test_the_environment_variable_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        from pydantic import ValidationError

        monkeypatch.setenv("OPENZIM_MCP_RATE_LIMIT__REQUESTS_PER_SECOND", raw)
        with pytest.raises(ValidationError, match="finite"):
            OpenZimMcpConfig(allowed_directories=[str(tmp_path)])

    def test_a_per_operation_rate_is_held_to_the_same_rule(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``json.loads`` reads a bare ``NaN``, so the override path takes one."""
        from pydantic import ValidationError

        monkeypatch.setenv(
            "OPENZIM_MCP_RATE_LIMIT__PER_OPERATION_LIMITS",
            '{"search": {"requests_per_second": NaN, "burst_size": 2}}',
        )
        with pytest.raises(ValidationError, match="finite"):
            OpenZimMcpConfig(allowed_directories=[str(tmp_path)])

    # Slow enough that no scheduling stall between the two calls refills it.
    @pytest.mark.parametrize("rate", [0.001, 0.5])
    def test_a_finite_positive_rate_still_limits(self, rate: float) -> None:
        from openzim_mcp.exceptions import OpenZimMcpRateLimitError
        from openzim_mcp.rate_limiter import RateLimitConfig, RateLimiter

        limiter = RateLimiter(RateLimitConfig(requests_per_second=rate, burst_size=1))
        limiter.check_rate_limit("get_entry", client_id="c")
        with pytest.raises(OpenZimMcpRateLimitError):
            limiter.check_rate_limit("get_entry", client_id="c")


class TestAPerOperationEntryCannotSayDisabled:
    """A per-operation ``enabled: false`` loaded and was then ignored.

    Every entry is a whole ``RateLimitConfig``, so it accepts ``enabled``,
    but the limiter consults only the global flag: ``{"search": {"enabled":
    false, ...}}`` kept enforcing that entry's bucket. The documented
    overrides are ``requests_per_second`` and ``burst_size``, and "disabled"
    could mean either dropping the operation's own bucket or exempting it
    from limiting altogether, so the setting is refused rather than guessed.
    """

    def test_enabled_false_in_an_entry_is_refused(self) -> None:
        from pydantic import ValidationError

        from openzim_mcp.rate_limiter import RateLimitConfig

        with pytest.raises(ValidationError, match="enabled=false") as excinfo:
            RateLimitConfig(
                per_operation_limits={"search": {"enabled": False, "burst_size": 2}}
            )
        assert "'search'" in str(excinfo.value)

    def test_the_environment_variable_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic import ValidationError

        monkeypatch.setenv(
            "OPENZIM_MCP_RATE_LIMIT__PER_OPERATION_LIMITS",
            '{"search": {"enabled": false, "requests_per_second": 4, "burst_size": 8}}',
        )
        with pytest.raises(ValidationError, match="enabled=false"):
            OpenZimMcpConfig(allowed_directories=[str(tmp_path)])

    @pytest.mark.parametrize("extra", [{}, {"enabled": True}])
    def test_a_bucket_override_still_loads_and_limits(
        self, extra: Dict[str, Any]
    ) -> None:
        """Paired positive: what an entry is for still works, and so does a
        redundant ``enabled: true``, which is what every entry does anyway."""
        from openzim_mcp.exceptions import OpenZimMcpRateLimitError
        from openzim_mcp.rate_limiter import RateLimitConfig, RateLimiter

        limiter = RateLimiter(
            RateLimitConfig(
                per_operation_limits={
                    "search": {"requests_per_second": 0.001, "burst_size": 2, **extra}
                }
            )
        )
        limiter.check_rate_limit("search", client_id="c")
        with pytest.raises(OpenZimMcpRateLimitError, match="Per-operation"):
            limiter.check_rate_limit("search", client_id="c")


# JSON text spelling the key ``id`` with escapes. Built from ``chr(92)`` (a
# backslash) so the source never holds a backslash-u sequence an editor could
# turn into the character it names.
_BS = chr(92)
_ESCAPED_ID_KEYS = [
    f'"{_BS}u0069d"',
    f'"i{_BS}u0064"',
    f'"{_BS}u0069{_BS}u0064"',
]


class TestTheStdioNullIdGuardReadsEscapedKeys:
    """An ``id`` key spelt with JSON escapes slipped past the stdio guard.

    The guard skipped any line without the substring ``"id"`` before parsing
    it, but ``"\\u0069d"`` decodes to the same key. With a null value the SDK
    then read the frame as a notification and dropped it, so the client
    waited forever — while the HTTP guard, which always parses, answered the
    same bytes with ``-32600``.
    """

    @staticmethod
    def _line(key: str, value: str = "null") -> str:
        return '{"jsonrpc":"2.0",%s:%s,"method":"ping"}' % (key, value)

    @pytest.mark.parametrize("key", _ESCAPED_ID_KEYS)
    def test_an_escaped_key_is_judged_as_the_key_it_decodes_to(self, key: str) -> None:
        from openzim_mcp.sdk_compat import (
            invalid_request_id_rejection_for_line,
            rejection_for_http_body,
        )

        line = self._line(key)
        assert json.loads(line)["id"] is None  # what the SDK will read
        rejection = invalid_request_id_rejection_for_line(line)
        assert rejection is not None, line
        assert rejection.error.code == -32600
        # The two transports now give the same bytes the same answer.
        http = rejection_for_http_body(line.encode())
        assert http is not None and http.error.message == rejection.error.message

    @pytest.mark.parametrize(
        "line",
        [
            '{"jsonrpc":"2.0","method":"notifications/initialized"}',
            '{"jsonrpc":"2.0","id":7,"method":"ping"}',
            # A backslash with no id at all: parsed now, and still let through.
            '{"jsonrpc":"2.0","method":"note","params":{"text":"a %s b"}}' % (_BS * 2),
            '{"jsonrpc":"2.0",%s:7,"method":"ping"}' % _ESCAPED_ID_KEYS[0],
        ],
    )
    def test_a_usable_or_absent_id_still_passes(self, line: str) -> None:
        from openzim_mcp.sdk_compat import invalid_request_id_rejection_for_line

        assert invalid_request_id_rejection_for_line(line) is None, line

    def test_stdio_answers_the_frame_instead_of_dropping_it(
        self, tmp_path: Path
    ) -> None:
        from tests.test_fr_transport_state import _INITIALIZE, _one_shot_stdio_frames

        responses = _one_shot_stdio_frames(
            tmp_path,
            [
                _INITIALIZE,
                '{"jsonrpc":"2.0","method":"notifications/initialized"}',
                self._line(_ESCAPED_ID_KEYS[0]),
                '{"jsonrpc":"2.0","id":42,"method":"ping"}',
            ],
        )
        rejections = [
            r
            for r in responses
            if "error" in r and "request id must be" in r["error"]["message"]
        ]
        assert len(rejections) == 1, responses
        assert rejections[0]["id"] is None and rejections[0]["error"]["code"] == -32600
        # Paired positive: the frame after it is still served normally.
        served = [r for r in responses if r.get("id") == 42]
        assert served and "result" in served[0], responses
