"""Regression tests for the runtime/protocol review of the v3 field-fix branch.

Each test pins a defect the field-fix branch introduced or left standing in
the stdio frame layer, the HTTP sessionless gate, the validation worker pool
and the directory health probe.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator, Tuple

import pytest
from mcp_types import INVALID_REQUEST
from starlette.testclient import TestClient

from openzim_mcp.server import OpenZimMcpServer
from tests.test_v3_field_fixes_http import (
    INITIALIZE_BODY,
    LEGACY_HEADERS,
    MISSING_SESSION_BODY,
    TOOLS_LIST_BODY,
    _build_client,
    _sessions,
)
from tests.test_v3_field_fixes_protocol import (
    _LEGACY_OPENING,
    _by_id,
    _one_shot_stdio,
)

# --------------------------------------------------------------------------
# stdio: a malformed frame must not answer — or retire — a live request
# --------------------------------------------------------------------------

_HEALTH_CALL = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "zim_health", "arguments": {}},
    }
)
# Same id as the call above, missing the ``jsonrpc`` member: a frame the
# adapter rejects, carrying an id that is still being handled.
_COLLIDING_MALFORMED = json.dumps({"id": 7, "method": "ping"})


def test_malformed_frame_does_not_steal_a_live_request_id(tmp_path: Path) -> None:
    """A rejection echoing an in-flight id answered it twice and dropped the
    real answer: the echo retired the request, so the EOF drain released
    immediately and the dispatcher cancelled the running handler."""
    responses, returncode, stderr = _one_shot_stdio(
        tmp_path, [*_LEGACY_OPENING, _HEALTH_CALL, _COLLIDING_MALFORMED]
    )

    for_seven = _by_id(responses, 7)
    assert len(for_seven) == 1, for_seven
    assert "result" in for_seven[0], for_seven[0]
    assert returncode == 0, stderr


def test_malformed_frame_colliding_with_a_live_id_is_still_rejected(
    tmp_path: Path,
) -> None:
    """The rejection is not dropped, only stripped of the borrowed id."""
    responses, _returncode, _stderr = _one_shot_stdio(
        tmp_path, [*_LEGACY_OPENING, _HEALTH_CALL, _COLLIDING_MALFORMED]
    )

    null_id_errors: list[dict[str, Any]] = [
        r["error"] for r in _by_id(responses, None) if "error" in r
    ]
    assert [e["code"] for e in null_id_errors] == [INVALID_REQUEST], null_id_errors


def test_malformed_frame_still_echoes_a_free_id(tmp_path: Path) -> None:
    """An id nobody is waiting on is echoed, as D56 requires."""
    responses, _returncode, _stderr = _one_shot_stdio(
        tmp_path, [*_LEGACY_OPENING, json.dumps({"id": 9, "method": "ping"})]
    )

    (rejection,) = _by_id(responses, 9)
    assert rejection["error"]["code"] == INVALID_REQUEST


# --------------------------------------------------------------------------
# HTTP: the sessionless gate must answer, not 500 — and only on the MCP path
# --------------------------------------------------------------------------


@pytest.fixture
def gated_client(tmp_path: Path) -> Iterator[Tuple[TestClient, OpenZimMcpServer]]:
    """The production-wired streamable-HTTP app, lifespan running."""
    client, server = _build_client(tmp_path)
    with client:
        yield client, server


def test_deeply_nested_body_is_answered_not_500(
    gated_client: Tuple[TestClient, OpenZimMcpServer],
) -> None:
    """``json.loads`` raises ``RecursionError`` — a ``RuntimeError``, not a
    ``ValueError`` — on a deeply nested body, so it escaped the gate and
    Starlette turned it into a 500 with a traceback."""
    client, server = gated_client

    response = client.post("/mcp", headers=LEGACY_HEADERS, content=b"[" * 200_000)

    assert response.status_code == 400
    assert response.json() == MISSING_SESSION_BODY
    assert _sessions(server) == {}


def test_sessionless_initialize_with_narrow_accept_mints_nothing(
    gated_client: Tuple[TestClient, OpenZimMcpServer],
) -> None:
    """D62 again: the SDK validates ``Accept`` only after it has minted and
    task-started the session, so an ``initialize`` the gate waved through on
    the strength of its body still leaked one per request."""
    client, server = gated_client

    for _ in range(3):
        response = client.post(
            "/mcp",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json=INITIALIZE_BODY,
        )
        assert response.status_code == 406, response.text

    assert _sessions(server) == {}


def test_unknown_path_still_reports_not_found(
    gated_client: Tuple[TestClient, OpenZimMcpServer],
) -> None:
    """The gate ran ahead of Starlette's router, so a typo'd URL was blamed
    on a missing session instead of on the path."""
    client, _server = gated_client

    assert client.get("/").status_code == 404
    assert client.get("/sse").status_code == 404
    typo = client.post("/typo", headers=LEGACY_HEADERS, json=TOOLS_LIST_BODY)
    assert typo.status_code == 404


def test_sessionless_tools_list_is_still_gated(
    gated_client: Tuple[TestClient, OpenZimMcpServer],
) -> None:
    """The path narrowing must not reopen the D62 leak on /mcp itself."""
    client, server = gated_client

    response = client.post("/mcp", headers=LEGACY_HEADERS, json=TOOLS_LIST_BODY)

    assert response.status_code == 400
    assert response.json() == MISSING_SESSION_BODY
    assert _sessions(server) == {}


# --------------------------------------------------------------------------
# Validation worker: an unguarded host __main__ must not break every check
# --------------------------------------------------------------------------

_UNGUARDED_SCRIPT = """\
from pathlib import Path

from openzim_mcp.zim.archive import check_archive_integrity

print("VALID", check_archive_integrity(Path({zim!r})))
"""


def test_integrity_check_survives_an_unguarded_host_main(
    tmp_path: Path, v2_phase_a_zim: Path
) -> None:
    """``spawn`` re-executes the host's ``__main__`` in the worker, so an
    embedding script with no ``if __name__ == "__main__":`` guard killed every
    worker in bootstrap and turned validation into a permanent failure."""
    script = tmp_path / "embed.py"
    script.write_text(_UNGUARDED_SCRIPT.format(zim=str(v2_phase_a_zim)))

    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert "VALID True" in completed.stdout, completed.stdout
