"""Post-a14 sweep self-audit: ``find_entry_by_title_data`` must dedupe
results that collapse to the same canonical path after the F3 redirect-
chain fix.

Pre-F3 behavior: each suggestion emitted its own path. Multiple
redirects to the same canonical (``Berlin``, ``Berlin (city)``,
``Berlin (disambiguation)`` → ``Berlin``) produced distinct results.

Post-F3 behavior (defective): the redirect chain is followed before
``path`` is reported, so multiple suggestions collapse to the same
canonical path — but ``aggregate_results`` had no dedup step, so the
response now carries duplicate rows for the same article.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


def _ctx(value):
    class _C:
        def __enter__(self):
            return value

        def __exit__(self, *a):
            return False

    return _C()


def test_find_entry_by_title_dedupes_after_redirect_chain_collapse(
    test_config: OpenZimMcpConfig, monkeypatch
) -> None:
    """Two suggestions (one canonical, one redirect to the same
    canonical) must produce ONE row in the results, not two."""
    server = OpenZimMcpServer(test_config)

    # Set up: archive has a canonical "Biology" entry and a "Bilogy"
    # redirect that follows to "Biology". The suggester returns both.
    canonical = MagicMock()
    canonical.path = "Biology"
    canonical.title = "Biology"
    canonical.is_redirect = False

    redirect = MagicMock()
    redirect.path = "Bilogy"
    redirect.title = "Bilogy"
    redirect.is_redirect = True
    redirect.get_redirect_entry.return_value = canonical

    mock_archive = MagicMock()
    mock_archive.has_entry_by_path.return_value = False  # Fast path miss
    # Lowercase query "biology" cannot exact-match the capitalized title
    # "Biology" via libzim's case-sensitive title index, so the native
    # title probe stays out of the way and the suggestion path is exercised.
    mock_archive.has_entry_by_title.return_value = False

    # Suggestion search returns BOTH paths.
    mock_suggest = MagicMock()
    mock_suggest.getEstimatedMatches.return_value = 2
    mock_suggest.getResults.return_value = ["Bilogy", "Biology"]
    mock_searcher = MagicMock()
    mock_searcher.suggest.return_value = mock_suggest

    def get_entry_by_path(path: str):
        if path == "Bilogy":
            return redirect
        if path == "Biology":
            return canonical
        raise RuntimeError(f"no entry at {path!r}")

    mock_archive.get_entry_by_path.side_effect = get_entry_by_path

    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive",
        lambda *a, **kw: _ctx(mock_archive),
    )
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.SuggestionSearcher",
        lambda _archive: mock_searcher,
    )

    server.zim_operations.path_validator = MagicMock()
    server.zim_operations.path_validator.validate_path.return_value = "/zim/test.zim"
    server.zim_operations.path_validator.validate_zim_file.return_value = (
        "/zim/test.zim"
    )

    result_json = server.zim_operations.find_entry_by_title(
        "/zim/test.zim", "biology", cross_file=False, limit=10
    )
    result = json.loads(result_json)

    paths = [r["path"] for r in result["results"]]
    # Both suggestions collapse to "Biology" canonically; results must
    # carry only one Biology row.
    assert paths.count("Biology") == 1, (
        f"Expected exactly one 'Biology' row after redirect-chain "
        f"collapse, got {paths.count('Biology')} in {paths!r}"
    )
