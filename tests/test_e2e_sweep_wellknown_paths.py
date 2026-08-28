"""``W/`` paths that browse advertises must not dead-end in ``zim_get``.

``zim_browse(namespace="W")`` and ``zim_metadata`` both publish
``W/mainPage`` and ``W/favicon`` on new-scheme archives — synthetic rows
resolved through libzim's well-known-entry APIs, because the literal paths
are not entries. ``zim_get`` knew nothing about them, so it answered
Resource Not Found and advised "use browsing tools to explore available
content" — the tool that had just handed the caller the path.

``M/<key>`` rows from the same browse surface resolve fine, because
``_smart_retrieve_entry`` routes them to the metadata API. This is the
sibling route for ``W/``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openzim_mcp.exceptions import OpenZimMcpEntryNotFoundError


@pytest.fixture
def ops(tmp_path):
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import CacheConfig, ContentConfig, OpenZimMcpConfig
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator
    from openzim_mcp.zim_operations import ZimOperations

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=4, ttl_seconds=60),
        content=ContentConfig(max_content_length=5000, snippet_length=200),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=200),
    )


def _archive_with_main_page() -> MagicMock:
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.has_illustration.return_value = True

    landing = MagicMock()
    landing.path = "iep.utm.edu/"
    landing.title = "Internet Encyclopedia of Philosophy"
    landing.is_redirect = False

    archive.main_entry = landing
    archive.get_entry_by_path.return_value = landing
    return archive


class TestMainPageIsFetchable:
    def test_w_main_page_resolves_to_the_real_entry(self, ops):
        archive = _archive_with_main_page()
        built: list[str] = []

        def _build(actual_path):
            built.append(actual_path)
            return ({"path": actual_path, "content": "landing"}, True, actual_path)

        result, content_ok = ops._smart_retrieve_entry(
            archive,
            "W/mainPage",
            "/zim/iep.zim",
            build=_build,
            fetch_metadata=lambda: ({}, False),
        )
        # Resolved through main_entry, not looked up as a literal path.
        assert built == ["iep.utm.edu/"]
        assert content_ok is True
        assert result["content"] == "landing"

    def test_ordinary_paths_are_untouched(self, ops):
        """Positive control: the W route must not shadow normal lookups."""
        archive = _archive_with_main_page()
        built: list[str] = []

        def _build(actual_path):
            built.append(actual_path)
            return ({"path": actual_path, "content": "x"}, True, actual_path)

        ops._smart_retrieve_entry(
            archive,
            "iep.utm.edu/stoicism/",
            "/zim/iep.zim",
            build=_build,
            fetch_metadata=lambda: ({}, False),
        )
        assert built == ["iep.utm.edu/stoicism/"]


class TestFaviconIsServedAsBytes:
    """The illustration has no entry path, but it does have bytes.

    ``get_illustration_item`` returns an Item with the same
    size/mimetype/content surface the binary route already serves, so the
    path browse advertises is now fetchable rather than a 404.
    """

    def test_text_route_points_at_the_binary_one(self, ops):
        archive = _archive_with_main_page()
        with pytest.raises(OpenZimMcpEntryNotFoundError) as exc_info:
            ops._smart_retrieve_entry(
                archive,
                "W/favicon",
                "/zim/iep.zim",
                build=lambda p: ({}, True, p),
                fetch_metadata=lambda: ({}, False),
            )
        message = str(exc_info.value)
        assert "binary=True" in message
        # The circular advice is what made the old message useless.
        assert "Use browsing tools" not in message

    def test_missing_illustration_says_so(self, ops):
        archive = _archive_with_main_page()
        archive.get_illustration_item.side_effect = RuntimeError("no illustration")
        with pytest.raises(OpenZimMcpEntryNotFoundError) as exc_info:
            ops._resolve_well_known_illustration(archive)
        assert "illustration" in str(exc_info.value).lower()

    def test_no_illustration_is_not_promised_to_the_text_caller(self, ops):
        """Don't send the caller to a retry that cannot succeed.

        The text branch matched on the path string alone, so an archive
        carrying no illustration was told "it's an image, fetch it with
        binary=True" — and the binary call then reported there was nothing
        there. Two round trips to learn the first answer was false.
        """
        archive = _archive_with_main_page()
        archive.has_illustration.return_value = False
        with pytest.raises(OpenZimMcpEntryNotFoundError) as exc_info:
            ops._smart_retrieve_entry(
                archive,
                "W/favicon",
                "/zim/iep.zim",
                build=lambda p: ({}, True, p),
                fetch_metadata=lambda: ({}, False),
            )
        message = str(exc_info.value)
        assert "binary=True" not in message
        assert "no illustration" in message.lower()

    def test_gate_asks_for_the_size_actually_served(self, ops):
        """``has_illustration()`` means "any size"; the fetch uses 48.

        An archive whose only illustration is some other size would pass a
        bare ``has_illustration()`` and then fail the 48-px fetch, putting
        the two surfaces right back into disagreement.
        """
        archive = _archive_with_main_page()
        archive.has_illustration.return_value = True
        with pytest.raises(OpenZimMcpEntryNotFoundError):
            ops._smart_retrieve_entry(
                archive,
                "W/favicon",
                "/zim/iep.zim",
                build=lambda p: ({}, True, p),
                fetch_metadata=lambda: ({}, False),
            )
        archive.has_illustration.assert_called_with(48)


class TestWellKnownPathsResolveOnEverySurface:
    """One tool must not answer contradictorily an argument apart.

    The rewrite first landed only in ``_smart_retrieve_entry``, which backs
    the plain-body and batch surfaces. ``view=toc``/``summary``/``structure``,
    ``zim_get_section`` and ``zim_links`` resolve entries through a second,
    independent ladder that knew nothing about ``W/``, so ``W/mainPage``
    returned the article for one call and Resource Not Found for the next.
    """

    def test_shared_rewrite_helper_resolves_main_page(self, ops):
        from openzim_mcp.zim.content import rewrite_well_known_path

        archive = _archive_with_main_page()
        assert rewrite_well_known_path(archive, "W/mainPage") == "iep.utm.edu/"

    def test_shared_helper_passes_ordinary_paths_through(self, ops):
        from openzim_mcp.zim.content import rewrite_well_known_path

        archive = _archive_with_main_page()
        assert (
            rewrite_well_known_path(archive, "iep.utm.edu/stoicism/")
            == "iep.utm.edu/stoicism/"
        )

    def test_shared_helper_ignores_old_scheme_archives(self, ops):
        from openzim_mcp.zim.content import rewrite_well_known_path

        archive = _archive_with_main_page()
        archive.has_new_namespace_scheme = False
        assert rewrite_well_known_path(archive, "W/mainPage") == "W/mainPage"


class TestRootedSpellingResolves:
    """``/W/mainPage`` must behave like ``W/mainPage``.

    The binary surface normalizes at its boundary, so ``/W/favicon``
    resolved while ``/W/mainPage`` 404'd — a divergence inside one tool on
    the same synthetic path, because the ``W/`` check sits above the ladder
    whose un-rooting recovery would otherwise have caught it.
    """

    def test_leading_slash_still_resolves(self, ops):
        from openzim_mcp.zim.content import rewrite_well_known_path

        archive = _archive_with_main_page()
        assert rewrite_well_known_path(archive, "/W/mainPage") == "iep.utm.edu/"
