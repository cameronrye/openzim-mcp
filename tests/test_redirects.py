"""Unit tests for the shared strict redirect resolver.

The resolver was extracted from seven near-identical inline copies across
content.py / archive.py / resource_tools.py (post-v2.0.5 review sweep). These
tests pin the contract the call sites depend on so a future change to the
shared helper can't silently shift behavior under any of them.
"""

import pytest

from openzim_mcp.defaults import CONTENT
from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.zim.redirects import resolve_redirect_chain


class _FakeEntry:
    """Minimal stand-in for a libzim Entry redirect node."""

    def __init__(self, path: str, *, redirect_to: "_FakeEntry | None" = None) -> None:
        self.path = path
        self._target = redirect_to

    @property
    def is_redirect(self) -> bool:
        return self._target is not None

    def get_redirect_entry(self) -> "_FakeEntry":
        assert self._target is not None
        return self._target


def test_returns_same_object_on_direct_hit() -> None:
    """A non-redirect entry is returned unchanged (identity preserved) — the
    binary path relies on ``resolved is entry`` to skip rewriting its path."""
    entry = _FakeEntry("C/Article")
    assert resolve_redirect_chain(entry, context="x") is entry


def test_follows_chain_to_canonical_target() -> None:
    target = _FakeEntry("C/Canonical")
    mid = _FakeEntry("C/Mid", redirect_to=target)
    head = _FakeEntry("C/Head", redirect_to=mid)
    assert resolve_redirect_chain(head, context="x") is target


def test_raises_on_cycle() -> None:
    a = _FakeEntry("C/A")
    b = _FakeEntry("C/B", redirect_to=a)
    a._target = b  # A -> B -> A
    with pytest.raises(OpenZimMcpArchiveError, match="Redirect cycle detected"):
        resolve_redirect_chain(a, context="x")


def test_raises_when_chain_exceeds_depth() -> None:
    # Build a non-cyclic chain longer than the cap so the depth guard (not
    # the cycle guard) fires; context is interpolated into the message.
    tail = _FakeEntry("C/n")
    node = tail
    for i in range(CONTENT.MAX_REDIRECT_DEPTH + 2):
        node = _FakeEntry(f"C/n{i}", redirect_to=node)
    with pytest.raises(OpenZimMcpArchiveError, match="too deep") as exc:
        resolve_redirect_chain(node, context="starting at C/n0")
    assert "starting at C/n0" in str(exc.value)
