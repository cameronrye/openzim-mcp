"""Regressions from the 2026-11 sweep of the HTTP server, its config and limits.

Each class pins one defect that reproduced against ``main`` at e945188 —
in-process through the production-wired ASGI app wherever the defect lives on
the wire — and names the inputs that exposed it.
"""

from __future__ import annotations

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
