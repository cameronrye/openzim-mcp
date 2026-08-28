"""A URL-shaped ``entry_path`` gets told what to strip.

The server instructions state entry paths are "archive-relative (e.g.
'A/Aspirin'), never URLs", but the not-found error for
``https://en.wikipedia.org/wiki/Aspirin`` gave the generic five
troubleshooting steps and never mentioned the scheme and host, so the
caller's most natural wrong guess got no correction.
"""

from __future__ import annotations

import pytest

from openzim_mcp.error_messages import url_shaped_path_hint


class TestHintFires:
    @pytest.mark.parametrize(
        "path",
        [
            "https://en.wikipedia.org/wiki/Aspirin",
            "http://iep.utm.edu/epistemo/",
            "HTTPS://EXAMPLE.ORG/x",
        ],
    )
    def test_url_gets_a_hint(self, path):
        hint = url_shaped_path_hint(path)
        assert hint
        assert "archive-relative" in hint

    def test_hint_keeps_the_host_in_the_suggested_path(self):
        """zimit/warc2zim archives file entries UNDER the host.

        ``iep.utm.edu/stoicism/`` resolves; ``stoicism/`` does not, so a
        hint that says to drop the host sends the caller to a second 404.
        """
        hint = url_shaped_path_hint("https://iep.utm.edu/stoicism/")
        assert "'iep.utm.edu/stoicism/'" in hint
        assert "and host" not in hint


class TestHintStaysQuiet:
    @pytest.mark.parametrize(
        "path",
        [
            "A/Aspirin",
            "medlineplus.gov/druginfo/meds/a682878.html",
            "C/Some_Article",
            "",
            "M/Title",
        ],
    )
    def test_ordinary_entry_path_gets_no_hint(self, path):
        assert url_shaped_path_hint(path) == ""
