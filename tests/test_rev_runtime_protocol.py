"""Regression tests for the runtime/protocol review of the v3 field-fix branch.

Each test pins a defect the field-fix branch introduced or left standing in
the stdio frame layer, the HTTP sessionless gate, the validation worker pool
and the directory health probe.
"""

import json
from pathlib import Path
from typing import Any

from mcp_types import INVALID_REQUEST

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
