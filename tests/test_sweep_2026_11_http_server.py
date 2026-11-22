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
