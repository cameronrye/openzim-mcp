"""Unit tests for the shared strict redirect resolver.

The resolver was extracted from seven near-identical inline copies across
content.py / archive.py / resource_tools.py (post-v2.0.5 review sweep). These
tests pin the contract the call sites depend on so a future change to the
shared helper can't silently shift behavior under any of them.
"""

import pytest

from openzim_mcp.defaults import CONTENT
from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.zim.redirects import (
    best_effort_redirect_chain,
    resolve_redirect_chain,
)


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


# ---------------------------------------------------------------------------
# best_effort_redirect_chain — the forgiving sibling that NEVER raises and
# NEVER returns None (backs speculative title-matching + synthetic main-page
# rendering, where a malformed redirect should degrade rather than fail).
# ---------------------------------------------------------------------------


class _BestEffortEntry:
    """Redirect node that can also model a raising or ``None``-returning hop."""

    def __init__(
        self,
        path: str,
        *,
        redirect_to: "_BestEffortEntry | None" = None,
        raises: bool = False,
        returns_none: bool = False,
    ) -> None:
        self.path = path
        self._target = redirect_to
        self._raises = raises
        self._returns_none = returns_none

    @property
    def is_redirect(self) -> bool:
        return self._raises or self._returns_none or self._target is not None

    def get_redirect_entry(self) -> "_BestEffortEntry | None":
        if self._raises:
            raise RuntimeError("redirect fetch failed")
        if self._returns_none:
            return None
        return self._target


def test_best_effort_returns_same_object_on_direct_hit() -> None:
    entry = _BestEffortEntry("C/Article")
    assert best_effort_redirect_chain(entry) is entry


def test_best_effort_follows_chain_to_canonical() -> None:
    target = _BestEffortEntry("C/Canonical")
    mid = _BestEffortEntry("C/Mid", redirect_to=target)
    head = _BestEffortEntry("C/Head", redirect_to=mid)
    assert best_effort_redirect_chain(head) is target


def test_best_effort_returns_last_good_on_cycle_never_raises() -> None:
    # A -> B -> A. Contrast resolve_redirect_chain which RAISES on a cycle;
    # the best-effort walker returns the last good entry (B, the most recent
    # entry that passed the seen-check) and never raises.
    a = _BestEffortEntry("C/A")
    b = _BestEffortEntry("C/B", redirect_to=a)
    a._target = b
    result = best_effort_redirect_chain(a)
    assert result is b


def test_best_effort_returns_entry_when_chain_exceeds_depth() -> None:
    # A non-cyclic chain longer than the cap returns a (still-redirect)
    # entry rather than raising or looping forever.
    tail = _BestEffortEntry("C/tail")
    node = tail
    for i in range(CONTENT.MAX_REDIRECT_DEPTH + 3):
        node = _BestEffortEntry(f"C/r{i}", redirect_to=node)
    result = best_effort_redirect_chain(node)
    assert result is not None


def test_best_effort_returns_last_good_when_hop_raises() -> None:
    mid = _BestEffortEntry("C/Mid", raises=True)
    head = _BestEffortEntry("C/Head", redirect_to=mid)
    # head -> mid (advanced to, last_good); mid's hop raises -> return mid.
    assert best_effort_redirect_chain(head) is mid


def test_best_effort_returns_last_good_on_none_hop_never_none() -> None:
    # post-a14 regression guard: a chain whose next hop is None must yield
    # the prior entry, never None (None crashed every downstream .path).
    mid = _BestEffortEntry("C/Mid", returns_none=True)
    head = _BestEffortEntry("C/Head", redirect_to=mid)
    assert best_effort_redirect_chain(head) is mid


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _BestEffortEntry("C/x", raises=True),
        lambda: _BestEffortEntry("C/x", returns_none=True),
    ],
)
def test_best_effort_never_returns_none(factory) -> None:
    assert best_effort_redirect_chain(factory()) is not None


def test_best_effort_cap_equals_content_max_redirect_depth() -> None:
    # Exactly MAX_REDIRECT_DEPTH redirect hops then a canonical resolves;
    # one more hop does NOT (pins the cap to the CONTENT default rather than
    # a drifting inline literal).
    def _chain(redirect_hops: int) -> _BestEffortEntry:
        node: _BestEffortEntry = _BestEffortEntry("C/Canonical")
        for i in range(redirect_hops):
            node = _BestEffortEntry(f"C/r{i}", redirect_to=node)
        return node

    resolved = best_effort_redirect_chain(_chain(CONTENT.MAX_REDIRECT_DEPTH))
    assert resolved.path == "C/Canonical"
    over = best_effort_redirect_chain(_chain(CONTENT.MAX_REDIRECT_DEPTH + 1))
    assert over.path != "C/Canonical"


def test_search_follow_redirect_chain_delegates_to_helper() -> None:
    # The SearchMixin method is retained as a thin wrapper (preserves the
    # five internal call sites and the monkeypatch in
    # test_find_entry_by_title_characterization). It must return exactly
    # what the shared helper returns.
    from openzim_mcp.zim.search import _SearchMixin

    target = _BestEffortEntry("C/Canonical")
    head = _BestEffortEntry("C/Head", redirect_to=target)
    assert _SearchMixin._follow_redirect_chain(head) is target
