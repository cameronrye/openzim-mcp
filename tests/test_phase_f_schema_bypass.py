"""Defense-in-depth tests — clients that flatten ``oneOf`` must still get
structured errors.

These probes bypass the schema layer by calling the tool function directly
with invalid combinations. The handler's runtime validation must catch them
and return a ``tool_error("invalid_path_combination", ...)`` envelope (or
``"invalid_view"`` for an enum violation).

Coverage is per-combination, not per-branch — at least one probe per distinct
forbidden combination across the four zim_get ``oneOf`` branches. If a future
API change adds a forbidden combination (e.g., a new parameter that locks
others out), this list must be extended.
"""

from __future__ import annotations

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


@pytest.fixture(scope="module")
def phase_f_server() -> OpenZimMcpServer:
    cfg = OpenZimMcpConfig(allowed_directories=["/tmp"], tool_mode="advanced")
    return OpenZimMcpServer(cfg)


# (kwargs passed to zim_get.fn, expected `operation`, expected hint substring
# matched against `message`)
INVALID_ZIM_GET_PROBES = [
    # Mutex paths
    (dict(entry_path="a", entry_paths=["b"]), "invalid_path_combination", "exclusive"),
    # Binary single-only
    (
        dict(binary=True, entry_paths=["a"]),
        "invalid_path_combination",
        "single-entry",
    ),
    # Binary locks view to "full"
    (
        dict(binary=True, entry_path="a", view="summary"),
        "invalid_path_combination",
        "Binary",
    ),
    (
        dict(binary=True, entry_path="a", view="toc"),
        "invalid_path_combination",
        "Binary",
    ),
    (
        dict(binary=True, entry_path="a", view="structure"),
        "invalid_path_combination",
        "Binary",
    ),
    # Binary + main_page conflict
    (
        dict(binary=True, main_page=True, entry_path="a"),
        "invalid_path_combination",
        "main_page",
    ),
    # main_page is path-free
    (
        dict(main_page=True, entry_path="a"),
        "invalid_path_combination",
        "path-free",
    ),
    (
        dict(main_page=True, entry_paths=["a"]),
        "invalid_path_combination",
        "path-free",
    ),
    # main_page locks view to "full"
    (
        dict(main_page=True, view="summary"),
        "invalid_path_combination",
        "main_page",
    ),
    (
        dict(main_page=True, view="toc"),
        "invalid_path_combination",
        "main_page",
    ),
    (
        dict(main_page=True, view="structure"),
        "invalid_path_combination",
        "main_page",
    ),
    # At-least-one-path required
    (dict(view="full"), "invalid_path_combination", "Provide one of"),
    (dict(view="summary"), "invalid_path_combination", "Provide one of"),
    # Invalid view enum (also defense-in-depth — schema enum SHOULD catch
    # this, but a flattening client could still slip a bad value through).
    (
        dict(entry_path="a", view="bogus"),
        "invalid_view",
        "must be one of",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,expected_operation,expected_hint_substring",
    INVALID_ZIM_GET_PROBES,
)
async def test_zim_get_invalid_combinations_surface_structured_error(
    phase_f_server: OpenZimMcpServer,
    kwargs: dict,
    expected_operation: str,
    expected_hint_substring: str,
) -> None:
    tool = phase_f_server.mcp._tool_manager._tools["zim_get"]
    result = await tool.fn(zim_file_path="/tmp/x.zim", **kwargs)
    assert (
        result.get("error") is True
    ), f"expected structured tool_error envelope for kwargs={kwargs}; got {result!r}"
    assert result.get("operation") == expected_operation, (
        f"expected operation={expected_operation!r} for kwargs={kwargs}; "
        f"got {result.get('operation')!r}"
    )
    assert expected_hint_substring in result.get("message", ""), (
        f"expected message to contain {expected_hint_substring!r} for "
        f"kwargs={kwargs}; got message={result.get('message')!r}"
    )


def test_invalid_combination_coverage_matches_branch_matrix() -> None:
    """Sanity check: at least one probe per oneOf-forbidden combination
    across the 4 branches × {entry_path, entry_paths, binary, view, main_page}
    dimensions. If a future branch adds a forbidden combination, the
    parametrize list must grow in lockstep.
    """
    # 13 invalid-combo probes for `invalid_path_combination` + 1 for
    # `invalid_view` enum violation = 14 total. The 13 covers each distinct
    # forbidden shape (matches plan §Task D15 coverage requirement).
    invalid_combo_count = sum(
        1 for _, op, _ in INVALID_ZIM_GET_PROBES if op == "invalid_path_combination"
    )
    assert invalid_combo_count >= 13, (
        f"Expected ≥13 invalid_path_combination probes (one per distinct "
        f"forbidden combination); got {invalid_combo_count}."
    )
