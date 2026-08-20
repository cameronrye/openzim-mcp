"""A heading that links to a disambiguated article must still be located.

html2text backslash-escapes parens inside a link target, so
``Mercury (mythology)`` renders as ``[Mercury (mythology)](Mercury_\\(mythology\\)
"Mercury \\(mythology\\)")``. ``_MD_LINK_RE`` stopped at the first ``)`` and left
``Mercury (mythology) "Mercury (mythology)")`` in the reduced text, which
never matches the soup-side ``Naming after Mercury (mythology)``. The heading
was dropped, its section vanished from the bundle, and the preceding
section's slice ran on through it and swallowed its body.

Parenthetical disambiguation is how Wikipedia distinguishes most ambiguous
titles, so this is an ordinary article shape rather than an exotic one.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from openzim_mcp.bundle import (
    _compute_section_offsets,
    _strip_md_inline_decorations,
)
from openzim_mcp.content_processor import _build_headings

_RENDERED_LINK = (
    "Naming after [Mercury (mythology)](Mercury_\\(mythology\\) "
    '"Mercury \\(mythology\\)")'
)


class TestEscapedParensInLinks:
    def test_link_with_escaped_parens_reduces_to_its_visible_text(self) -> None:
        assert (
            _strip_md_inline_decorations(_RENDERED_LINK)
            == "Naming after Mercury (mythology)"
        )

    def test_plain_link_still_reduces(self) -> None:
        assert _strip_md_inline_decorations("See [Orbit](Orbit)") == "See Orbit"

    def test_image_link_still_reduces(self) -> None:
        assert _strip_md_inline_decorations("![Alt](img.png)") == "Alt"


class TestDisambiguatedHeadingYieldsASection:
    def test_section_is_present_and_does_not_merge_into_its_predecessor(self) -> None:
        html = (
            "<h2 id='early'>Early history</h2><p>early body</p>"
            "<h2 id='naming'>Naming after "
            "<a href='Mercury_(mythology)' title='Mercury (mythology)'>"
            "Mercury (mythology)</a></h2><p>naming body</p>"
            "<h2 id='orbit'>Orbit</h2><p>orbit body</p>"
        )
        headings = _build_headings(
            BeautifulSoup(html, "html.parser"), include_line_text=True
        )
        md = (
            "## Early history\n\nearly body\n\n"
            f"## {_RENDERED_LINK}\n\nnaming body\n\n"
            "## Orbit\n\norbit body\n"
        )
        sections = _compute_section_offsets(md, headings)

        assert [s["id"] for s in sections] == ["early", "naming", "orbit"]
        early = sections[0]
        body = md[early["char_start"] : early["char_end"]]
        assert "naming body" not in body, "the dropped section's body merged in"
