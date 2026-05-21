"""Shared fixtures + marker registration for ml tests."""

from __future__ import annotations

import importlib.util

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_reranker: test requires the [reranker] extra to be installed",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip @requires_reranker tests when fastembed is not importable."""
    if importlib.util.find_spec("fastembed") is not None:
        return
    skip_marker = pytest.mark.skip(reason="requires [reranker] extra")
    for item in items:
        if item.get_closest_marker("requires_reranker") is not None:
            item.add_marker(skip_marker)
