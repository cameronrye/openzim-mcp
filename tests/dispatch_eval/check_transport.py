"""Gate 0.2 — `oneOf` transport round-trip verification.

Boots the openzim-mcp server with ``OZM_GATE_0_PROBE=1`` so it registers
only the Gate 0 probe tool (Pattern B: Tool.parameters override with a
hand-authored ``oneOf`` schema), then asks each transport for the
``tools/list`` response and walks the response for the literal ``"oneOf"``
key.

Transports covered:
  - in-memory (direct ``Tool.parameters`` inspection — sanity check that the
    env-gated registration block actually fires)
  - stdio JSON-RPC (subprocess ``python -m openzim_mcp /tmp``)
  - HTTP / streamable-http (subprocess ``python -m openzim_mcp --transport http
    /tmp``) — best-effort; documented as unavailable if the subprocess does
    not become reachable in a short window.

Also runs a Pattern C (Pydantic discriminator) probe **in process** to
compare round-trip behaviour between the override path and the discriminator
path — the override path is what's wired into ``server.py``, so wire results
for the discriminator path are derived from FastMCP's in-process serializer
rather than a separate env-gated registration.

Run::

    python tests/dispatch_eval/check_transport.py

Output is JSON on stdout; the verdict markdown lives next to this script.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def _contains_one_of(schema_obj: Any) -> bool:
    """Recursive search for a literal ``"oneOf"`` key anywhere in the schema."""
    if isinstance(schema_obj, dict):
        if "oneOf" in schema_obj:
            return True
        return any(_contains_one_of(v) for v in schema_obj.values())
    if isinstance(schema_obj, list):
        return any(_contains_one_of(item) for item in schema_obj)
    return False


def _find_input_schemas(payload: Any) -> List[Dict[str, Any]]:
    """Pull every ``inputSchema`` object out of a JSON-RPC tools/list response."""
    out: List[Dict[str, Any]] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "inputSchema" in obj and isinstance(obj["inputSchema"], dict):
                out.append(obj["inputSchema"])
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(payload)
    return out


# ----------------------------------------------------------------------
# In-memory check (sanity)
# ----------------------------------------------------------------------


def check_in_memory() -> Dict[str, Any]:
    """Build a server with OZM_GATE_0_PROBE=1 and inspect the registered tool."""
    try:
        os.environ["OZM_GATE_0_PROBE"] = "1"
        # Defer imports until after env var is set — the gate is checked in
        # __init__, so we want a fresh server build.
        from openzim_mcp.config import OpenZimMcpConfig
        from openzim_mcp.server import OpenZimMcpServer

        cfg = OpenZimMcpConfig(allowed_directories=["/tmp"])
        srv = OpenZimMcpServer(cfg)
        tool = srv.mcp._tool_manager._tools["probe_tool"]
        params = tool.parameters

        return {
            "transport": "in-memory",
            "ok": True,
            "tool_names": list(srv.mcp._tool_manager._tools.keys()),
            "parameters": params,
            "contains_oneOf": _contains_one_of(params),
        }
    except Exception as exc:
        return {
            "transport": "in-memory",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "contains_oneOf": False,
        }
    finally:
        os.environ.pop("OZM_GATE_0_PROBE", None)


# ----------------------------------------------------------------------
# stdio JSON-RPC check
# ----------------------------------------------------------------------


def _make_jsonrpc_init_messages() -> List[bytes]:
    """Build the minimum JSON-RPC messages to reach tools/list over stdio.

    MCP spec requires the client to send ``initialize``, then the
    ``notifications/initialized`` notification, before any data request.
    """
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "gate-0.2-probe", "version": "0.0.0"},
        },
    }
    initialized = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }
    tools_list = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }
    return [
        (json.dumps(init) + "\n").encode("utf-8"),
        (json.dumps(initialized) + "\n").encode("utf-8"),
        (json.dumps(tools_list) + "\n").encode("utf-8"),
    ]


def check_stdio() -> Dict[str, Any]:
    """Launch the server as a subprocess in stdio mode and request tools/list."""
    try:
        env = {**os.environ, "OZM_GATE_0_PROBE": "1"}
        # Quiet the startup logger so it doesn't interleave with stdout JSON.
        env.setdefault("OPENZIM_MCP_LOGGING__LEVEL", "ERROR")
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "openzim_mcp",
                "/tmp",
                "--transport",
                "stdio",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(REPO_ROOT),
            env=env,
        )

        # Send all three frames at once, then close stdin.
        payload = b"".join(_make_jsonrpc_init_messages())
        try:
            stdout_bytes, stderr_bytes = proc.communicate(input=payload, timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
            return {
                "transport": "stdio",
                "ok": False,
                "error": "subprocess timed out waiting for tools/list response",
                "stdout_tail": stdout_bytes[-2000:].decode("utf-8", "replace"),
                "stderr_tail": stderr_bytes[-2000:].decode("utf-8", "replace"),
                "contains_oneOf": False,
            }

        # The MCP server speaks line-delimited JSON-RPC on stdout. We sent
        # two requests (initialize + tools/list); parse each non-empty line
        # as JSON and pick out the tools/list response (id == 2).
        responses: List[Dict[str, Any]] = []
        for line in stdout_bytes.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        tools_list_resp = next(
            (r for r in responses if r.get("id") == 2),
            None,
        )

        if tools_list_resp is None:
            return {
                "transport": "stdio",
                "ok": False,
                "error": (
                    "no JSON-RPC response with id==2 (tools/list) found in "
                    "stdout"
                ),
                "all_responses": responses,
                "stderr_tail": stderr_bytes[-2000:].decode("utf-8", "replace"),
                "contains_oneOf": False,
            }

        input_schemas = _find_input_schemas(tools_list_resp)
        return {
            "transport": "stdio",
            "ok": True,
            "tools_list_response": tools_list_resp,
            "input_schemas": input_schemas,
            "contains_oneOf": _contains_one_of(tools_list_resp),
        }
    except Exception as exc:
        return {
            "transport": "stdio",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "contains_oneOf": False,
        }


# ----------------------------------------------------------------------
# HTTP / streamable-http check (best-effort)
# ----------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(host: str, port: int, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def check_http() -> Dict[str, Any]:
    """Best-effort streamable-http transport check.

    Per the spec: HTTP transport unavailability is documented, not blocking.
    """
    proc: Optional[subprocess.Popen[bytes]] = None
    try:
        port = _free_port()
        env = {**os.environ, "OZM_GATE_0_PROBE": "1"}
        env.setdefault("OPENZIM_MCP_LOGGING__LEVEL", "ERROR")
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "openzim_mcp",
                "/tmp",
                "--transport",
                "http",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(REPO_ROOT),
            env=env,
        )

        if not _wait_for_port("127.0.0.1", port, timeout=8.0):
            proc.kill()
            stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
            return {
                "transport": "http (streamable-http)",
                "ok": False,
                "available": False,
                "reason": "subprocess did not bind to port within 8s",
                "stdout_tail": stdout_bytes[-1500:].decode("utf-8", "replace"),
                "stderr_tail": stderr_bytes[-1500:].decode("utf-8", "replace"),
                "contains_oneOf": False,
            }

        # MCP streamable-http requires JSON-RPC POST framing — same shape
        # as the stdio test. Use urllib so we don't add a dependency.
        import urllib.request

        # Open a session: initialize, initialized, tools/list. The
        # streamable-http endpoint expects each POST to /mcp to carry one
        # JSON-RPC envelope; for the simple unauthenticated case the
        # Mcp-Session-Id header is assigned in the response to initialize
        # and replayed on subsequent requests.
        base = f"http://127.0.0.1:{port}/mcp"

        def _post(envelope: Dict[str, Any], session_id: Optional[str]) -> Any:
            data = json.dumps(envelope).encode("utf-8")
            req = urllib.request.Request(
                base,
                data=data,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            if session_id is not None:
                req.add_header("Mcp-Session-Id", session_id)
            try:
                resp = urllib.request.urlopen(req, timeout=8)
            except Exception as exc:
                return {
                    "http_error": True,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            new_sid = resp.headers.get("Mcp-Session-Id")
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8", "replace")
            parsed: Any
            if content_type.startswith("application/json"):
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    parsed = body
            elif content_type.startswith("text/event-stream"):
                # SSE framing: lines like "event: message" / "data: {...}".
                # Pull data lines and try to parse the first JSON object.
                parsed = None
                for line in body.splitlines():
                    if line.startswith("data:"):
                        chunk = line[len("data:") :].strip()
                        try:
                            parsed = json.loads(chunk)
                            break
                        except json.JSONDecodeError:
                            continue
                if parsed is None:
                    parsed = body
            else:
                parsed = body
            return {
                "http_error": False,
                "status": resp.status,
                "content_type": content_type,
                "session_id": new_sid,
                "body_parsed": parsed,
                "body_raw_tail": body[-1500:],
            }

        init_env = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "gate-0.2-probe", "version": "0.0.0"},
            },
        }
        init_result = _post(init_env, session_id=None)
        sid = init_result.get("session_id") if isinstance(init_result, dict) else None

        initialized_env = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        initialized_result = _post(initialized_env, session_id=sid)

        tools_list_env = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
        tools_list_result = _post(tools_list_env, session_id=sid)

        # Pull the tools/list response body.
        tools_body = (
            tools_list_result.get("body_parsed")
            if isinstance(tools_list_result, dict)
            else None
        )
        contains = _contains_one_of(tools_body) if tools_body is not None else False
        input_schemas = (
            _find_input_schemas(tools_body) if tools_body is not None else []
        )

        return {
            "transport": "http (streamable-http)",
            "ok": True,
            "available": True,
            "initialize": init_result,
            "initialized": initialized_result,
            "tools_list": tools_list_result,
            "input_schemas": input_schemas,
            "contains_oneOf": contains,
        }
    except Exception as exc:
        return {
            "transport": "http (streamable-http)",
            "ok": False,
            "available": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "contains_oneOf": False,
        }
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


# ----------------------------------------------------------------------
# Pattern C (Pydantic discriminator) in-process comparison
# ----------------------------------------------------------------------


from pydantic import BaseModel, Field  # noqa: E402


class _CFulltext(BaseModel):
    mode: Literal["fulltext"]
    namespace: Optional[str] = None
    limit: Optional[int] = None


class _CTitle(BaseModel):
    mode: Literal["title"]


class _CSuggest(BaseModel):
    mode: Literal["suggest"]


_CSearchArgs = Union[_CFulltext, _CTitle, _CSuggest]


def check_pattern_c_inprocess() -> Dict[str, Any]:
    """In-process Pattern C check — does the discriminator emit oneOf?"""
    try:
        from mcp.server.fastmcp import FastMCP

        srv = FastMCP("pattern-c-inprocess")

        @srv.tool()
        def probe_c(
            args: _CSearchArgs = Field(..., discriminator="mode"),  # type: ignore[assignment]
        ) -> str:
            """Pattern C in-process probe."""
            return repr(args)

        params = srv._tool_manager._tools["probe_c"].parameters
        return {
            "transport": "in-memory (pattern C — pydantic discriminator)",
            "ok": True,
            "parameters": params,
            "contains_oneOf": _contains_one_of(params),
        }
    except Exception as exc:
        return {
            "transport": "in-memory (pattern C)",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "contains_oneOf": False,
        }


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------


def main() -> None:
    results: Dict[str, Any] = {
        "in_memory_pattern_b": check_in_memory(),
        "stdio_pattern_b": check_stdio(),
        "http_pattern_b": check_http(),
        "in_memory_pattern_c": check_pattern_c_inprocess(),
    }
    results["summary"] = {
        "in_memory_oneOf": results["in_memory_pattern_b"].get("contains_oneOf", False),
        "stdio_oneOf": results["stdio_pattern_b"].get("contains_oneOf", False),
        "http_available": results["http_pattern_b"].get("available", False),
        "http_oneOf": results["http_pattern_b"].get("contains_oneOf", False),
        "pattern_c_oneOf": results["in_memory_pattern_c"].get(
            "contains_oneOf", False
        ),
    }
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
