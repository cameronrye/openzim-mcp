"""The oversize-binary refusal must not send the caller round in a circle.

Audit residue on the v3.3.1 field report's fid 123. The ceiling shipped;
the advice pointing past it did not, so the two halves now contradict each
other and a caller who obeys each in turn cycles forever:

    1. zim_get(binary=True) on a 51 MB entry
       -> "raise max_content_length to at least 53820567 to fetch the bytes"
    2. zim_get(binary=True, max_content_length=53820567)
       -> "`max_content_length` is capped at 25,000,000 bytes"
    3. zim_get(binary=True, max_content_length=25000000)
       -> step 1's message again, naming 53820567 again

Step 2 does name a real exit ("read the file outside the MCP surface"), so
a caller is not strictly trapped — but the instruction that starts the loop
is the server's own, and it is the one that has to stop being given.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.defaults import CONTENT
from openzim_mcp.security import PathValidator
from openzim_mcp.tools.zim_get import MAX_BINARY_CONTENT_LENGTH
from openzim_mcp.zim_operations import ZimOperations

CEILING = MAX_BINARY_CONTENT_LENGTH


def _meta(size: int) -> Dict[str, Any]:
    return {
        "entry_path": "I/big.mp4",
        "title": "big.mp4",
        "mime_type": "video/mp4",
        "size": size,
    }


@pytest.fixture
def format_binary(tmp_path) -> Any:
    """The real ``ZimOperations`` method, not a re-implementation of it."""
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        tool_mode="advanced",
        cache=CacheConfig(enabled=False),
    )
    validator = PathValidator(config.allowed_directories)
    ops = ZimOperations(
        config,
        validator,
        OpenZimMcpCache(config.cache),
        ContentProcessor(),
    )
    return ops._format_binary_response


# ---------------------------------------------------------------------------
# Over the ceiling: the number named must be one the surface will accept
# ---------------------------------------------------------------------------


def test_an_entry_past_the_ceiling_is_not_told_to_raise_the_cap(format_binary):
    """The entry can never be fetched as base64, whatever the caller passes."""
    oversize = CEILING + 28_820_567
    out = format_binary(_meta(oversize), True, CONTENT.MAX_BINARY_SIZE, None)

    assert out["truncated"] is True
    message = out["message"]
    # Negative: the instruction that opens the loop is gone...
    assert str(oversize) not in message, message
    assert "raise max_content_length" not in message, message
    # ...and positive: the caller is told why, and where the real exit is.
    assert f"{CEILING:,}" in message, message
    assert "outside the MCP surface" in message, message


def test_the_size_is_still_reported_so_the_refusal_is_checkable(format_binary):
    """Dropping the bad instruction must not drop the fact behind it."""
    out = format_binary(_meta(CEILING + 1), True, CONTENT.MAX_BINARY_SIZE, None)

    assert "51" in out["message"] or "MB" in out["message"], out["message"]
    assert out["size"] == CEILING + 1


# ---------------------------------------------------------------------------
# Under the ceiling: the original advice was correct and must survive
# ---------------------------------------------------------------------------


def test_an_entry_within_the_ceiling_still_gets_the_working_instruction(
    format_binary,
):
    """Control. Most oversize entries ARE reachable by raising the cap, and
    that advice is the useful half of this message — a fix that silenced it
    everywhere would trade a loop for a dead end."""
    reachable = CONTENT.MAX_BINARY_SIZE + 5_000_000
    assert reachable < CEILING, "fixture must sit under the ceiling"

    out = format_binary(_meta(reachable), True, CONTENT.MAX_BINARY_SIZE, None)

    assert out["truncated"] is True
    assert f"raise max_content_length to at least {reachable}" in out["message"]
    assert "outside the MCP surface" not in out["message"]


def test_the_boundary_entry_is_reachable(format_binary):
    """An entry of exactly the ceiling can be fetched, so it keeps the
    raise-the-cap advice. Off-by-one here would refuse a legal fetch."""
    out = format_binary(_meta(CEILING), True, CONTENT.MAX_BINARY_SIZE, None)

    assert f"raise max_content_length to at least {CEILING}" in out["message"]


def test_the_advice_the_message_gives_is_one_the_tool_accepts(format_binary):
    """The property behind all of the above, stated once.

    Whatever number the message names, feeding it back must not be refused
    by ``zim_get``'s own ceiling check — which is exactly what step 2 of the
    loop does today.
    """
    import re

    for size in (
        CONTENT.MAX_BINARY_SIZE + 1,
        CEILING - 1,
        CEILING,
        CEILING + 1,
        CEILING * 3,
    ):
        message = format_binary(_meta(size), True, CONTENT.MAX_BINARY_SIZE, None)[
            "message"
        ]
        named = re.search(r"raise max_content_length to at least (\d+)", message)
        if named is None:
            continue
        assert int(named.group(1)) <= CEILING, (
            f"size={size}: the message names {named.group(1)}, which "
            f"`zim_get` refuses as over the {CEILING} binary ceiling — "
            "obeying it lands the caller back here"
        )
