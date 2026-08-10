"""List-endpoint ordering determinism — pin the wire order clients cache on.

Issue #360 Phase 0 (safe on the pinned ``mcp`` 1.x SDK; carries into the v2 port).

The 2026-07-28 MCP revision adds a SHOULD that servers return tools from
``tools/list`` in a deterministic order, so clients can cache list results and
so the serialized tool block stays byte-identical between requests — which is
what earns LLM prompt-cache hits. The same revision makes list results formally
cacheable (``ttlMs`` / ``cacheScope``), so a list whose order wobbles turns
every cache entry into a miss.

openzim-mcp satisfies this today by construction: ``register_phase_f_tools``
registers into FastMCP's insertion-ordered manager dicts in a fixed literal
order, and the surface varies only with the server-side ``tool_mode`` config —
never per connection or per request. Nothing enforces it, though. Swapping the
registration tuple for a set literal, sorting the managers, or registering
conditionally would silently break client caching with no other test failing.

These tests pin the exact sequence returned by the public ``list_*`` coroutines
— the code path that answers ``tools/list``, ``resources/list``,
``resources/templates/list``, and ``prompts/list`` — rather than the private
``_tool_manager._tools`` dict the other suites read, so the guarantee survives
an SDK-internal refactor.

Scope note: *membership* (which tools exist in each mode) is already covered by
``tests/test_phase_f_migration.py``; this file is only about *order*.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

# The advertised order is the registration order in
# openzim_mcp/tools/__init__.py: zim_query first (it is the whole simple-mode
# surface and the primary entry point in advanced mode), then the seven
# specialist tools. Changing this literal is a client-visible protocol change:
# it invalidates cached tools/list results and cold-starts prompt caches.
EXPECTED_ADVANCED_TOOLS = [
    "zim_query",
    "zim_search",
    "zim_get",
    "zim_get_section",
    "zim_browse",
    "zim_metadata",
    "zim_links",
    "zim_health",
]

EXPECTED_SIMPLE_TOOLS = ["zim_query"]

EXPECTED_RESOURCES = ["zim://files"]

EXPECTED_RESOURCE_TEMPLATES = ["zim://{name}", "zim://{name}/entry/{path}"]

EXPECTED_PROMPTS = ["research", "summarize", "explore"]


def _server(tool_mode: str, directory: Path) -> OpenZimMcpServer:
    """Build a server whose only configured directory is ``directory``.

    No archive is opened: every ``list_*`` call answers from the registration
    tables alone, so these tests need no ZIM fixtures — just a real directory
    for config validation to accept.
    """
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(directory)],
            tool_mode=tool_mode,
        )
    )


class TestToolsListOrder:
    """``tools/list`` returns a fixed sequence in each tool mode."""

    @pytest.mark.asyncio
    async def test_advanced_mode_exact_order(self, temp_dir: Path) -> None:
        tools = await _server("advanced", temp_dir).mcp.list_tools()

        assert [t.name for t in tools] == EXPECTED_ADVANCED_TOOLS, (
            "tools/list order changed. This is client-visible: it invalidates "
            "cached list results and cold-starts LLM prompt caches. Update "
            "EXPECTED_ADVANCED_TOOLS only alongside a deliberate, changelogged "
            "reordering of register_phase_f_tools."
        )

    @pytest.mark.asyncio
    async def test_simple_mode_exact_order(self, temp_dir: Path) -> None:
        tools = await _server("simple", temp_dir).mcp.list_tools()

        assert [t.name for t in tools] == EXPECTED_SIMPLE_TOOLS

    @pytest.mark.asyncio
    async def test_order_is_stable_across_repeated_calls(self, temp_dir: Path) -> None:
        """Repeated calls on one server must not reshuffle.

        Catches an ordering derived from mutable per-call state (a cache that
        reorders on access, a generator consumed once and re-materialized).
        """
        server = _server("advanced", temp_dir)

        first = [t.name for t in await server.mcp.list_tools()]
        second = [t.name for t in await server.mcp.list_tools()]
        third = [t.name for t in await server.mcp.list_tools()]

        assert first == second == third == EXPECTED_ADVANCED_TOOLS

    @pytest.mark.asyncio
    async def test_order_is_stable_across_server_instances(
        self, temp_dir: Path
    ) -> None:
        """Two servers built from equivalent config advertise the same order.

        In-process only — see ``TestToolsListOrderAcrossProcesses`` for the
        stronger guarantee.
        """
        first = [t.name for t in await _server("advanced", temp_dir).mcp.list_tools()]
        second = [t.name for t in await _server("advanced", temp_dir).mcp.list_tools()]

        assert first == second == EXPECTED_ADVANCED_TOOLS


# Probe program for the cross-process check. Runs in a fresh interpreter and
# prints the advertised tool order on a sentinel-prefixed stdout line (server
# logging goes to stderr, but parsing a sentinel keeps this robust if that
# ever changes).
_ORDER_PROBE = """
import asyncio
import json
import tempfile

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


async def main():
    server = OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[tempfile.mkdtemp()], tool_mode="advanced"
        )
    )
    tools = await server.mcp.list_tools()
    print("ORDER:" + json.dumps([t.name for t in tools]))


asyncio.run(main())
"""


def _tool_order_in_fresh_process(hash_seed: str) -> List[str]:
    """Return ``tools/list`` order from a new interpreter at ``hash_seed``."""
    # Fixed argv, no shell, no caller-supplied input. Inherit the environment
    # and override PYTHONHASHSEED, so an ambient value in the developer's or
    # CI's shell cannot mask the variation being probed. Inheriting rather than
    # replacing keeps this portable: a stripped environment breaks the child on
    # Windows, which needs SYSTEMROOT and friends to start Python at all.
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}

    proc = subprocess.run(
        [sys.executable, "-c", _ORDER_PROBE],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    assert proc.returncode == 0, (
        f"order probe failed (PYTHONHASHSEED={hash_seed}, "
        f"rc={proc.returncode})\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

    for line in proc.stdout.splitlines():
        if line.startswith("ORDER:"):
            order: List[str] = json.loads(line[len("ORDER:") :])
            return order

    raise AssertionError(
        f"order probe printed no ORDER: line\nstdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )


class TestToolsListOrderAcrossProcesses:
    """The order must be identical in every server process, not just this one.

    This is the guard the in-process tests cannot provide. Set iteration order
    is *stable within* a process but varies *between* processes: sets of module
    objects (the registration loop's ``for module in (...)``) order by ``id()``,
    which moves with each process's memory layout, and sets of tool-name strings
    order by a per-process randomized hash seed. Either regression would leave
    every in-process assertion above green while real deployments served a
    different tool order on each restart — silently defeating the client-side
    caching the 2026-07-28 revision is built around.

    Two spawns plus the parent pytest process give three independent processes,
    with hash randomization both disabled and enabled. Each spawn re-imports the
    package, so this is the slowest part of the file — still well under a second
    once the import cache is warm.
    """

    @pytest.mark.parametrize("hash_seed", ["0", "12345"])
    def test_fresh_process_reports_expected_order(self, hash_seed: str) -> None:
        assert _tool_order_in_fresh_process(hash_seed) == EXPECTED_ADVANCED_TOOLS


class TestResourceAndPromptListOrder:
    """The other cacheable list endpoints are pinned too.

    ``resources/list``, ``resources/templates/list``, and ``prompts/list`` all
    become ``CacheableResult``s under the 2026-07-28 revision (issue #360 Phase
    4 assigns them long TTLs, since they are registration-static). They deserve
    the same ordering guarantee as ``tools/list``.
    """

    @pytest.mark.asyncio
    async def test_resources_exact_order(self, temp_dir: Path) -> None:
        resources = await _server("advanced", temp_dir).mcp.list_resources()

        assert [str(r.uri) for r in resources] == EXPECTED_RESOURCES

    @pytest.mark.asyncio
    async def test_resource_templates_exact_order(self, temp_dir: Path) -> None:
        templates = await _server("advanced", temp_dir).mcp.list_resource_templates()

        assert [t.uriTemplate for t in templates] == EXPECTED_RESOURCE_TEMPLATES

    @pytest.mark.asyncio
    async def test_prompts_exact_order(self, temp_dir: Path) -> None:
        prompts = await _server("advanced", temp_dir).mcp.list_prompts()

        assert [p.name for p in prompts] == EXPECTED_PROMPTS

    @pytest.mark.asyncio
    async def test_simple_mode_registers_no_resources_or_prompts(
        self, temp_dir: Path
    ) -> None:
        """Simple mode is tools-only; the other lists stay empty.

        Pinned because it is the one place the *lists themselves* vary with
        config: the 2026-07-28 rule is that they must not vary per connection,
        which server-side ``tool_mode`` does not.
        """
        server = _server("simple", temp_dir)

        assert await server.mcp.list_resources() == []
        assert await server.mcp.list_resource_templates() == []
        assert await server.mcp.list_prompts() == []
