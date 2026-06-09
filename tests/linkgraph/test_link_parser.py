"""The shared internal-link parser returns canonical (target, anchor) edge pairs.

Encodes the REAL classification + canonicalization rules used by
``extract_article_links``'s internal bucket (via ``ContentProcessor``
anchor classification) and ``get_related_articles``'s href resolution
(``_resolve_link_to_entry_path`` + asset-target exclusion). Asserted
invariants:

* internal-only — external (``http(s)://``, protocol-relative ``//``) and
  ``<img>``/``<video>``/etc. media-element sources are excluded;
* asset targets (``.png`` and friends) are excluded even when reached via an
  ``<a href>`` (ZIMIT wraps lead images in anchors);
* hrefs resolve RELATIVE to the source path's directory (posixpath
  semantics) — the same rule ``get_related_articles`` uses;
* a link whose resolved target equals the source path is dropped (no
  self-edges);
* results are deduped, preserving first-appearance order;
* with ``archive=None`` no redirect resolution happens — each surviving
  href is canonicalized only by path normalization.
"""

from __future__ import annotations

from openzim_mcp.zim.structure import _StructureMixin


def test_parse_internal_targets_internal_only_deduped() -> None:
    """Return internal-only canonical paths, deduped, sans external/media/assets."""
    # Source lives in the ``C`` directory; sibling hrefs resolve under ``C/``.
    html = (
        '<a href="Foo">Foo</a>'
        '<a href="Foo">Foo again</a>'  # duplicate -> collapses
        '<a href="https://example.com/x">external</a>'  # external -> excluded
        '<a href="//cdn.example.com/y">protocol-relative</a>'  # external -> excluded
        '<a href="img.png">image-as-anchor</a>'  # asset -> excluded
        '<img src="picture.png" alt="pic">'  # media element -> excluded
        '<a href="#section">anchor</a>'  # bare fragment -> not navigable
        '<a href="Bar">Bar</a>'
    )
    edges = _StructureMixin._parse_internal_link_edges(
        html, source_path="C/Source", archive=None
    )
    # Hrefs resolve relative to dirname("C/Source") == "C".
    assert [t for t, _ in edges] == ["C/Foo", "C/Bar"]


def test_parse_internal_targets_resolves_relative_against_source() -> None:
    """Relative hrefs resolve against the source path's directory (archive=None)."""
    html = '<a href="Other">other</a><a href="../Up">up</a>'
    edges = _StructureMixin._parse_internal_link_edges(
        html, source_path="A/dir/Source", archive=None
    )
    # "Other" -> A/dir/Other ; "../Up" -> A/Up (posixpath normalization).
    assert [t for t, _ in edges] == ["A/dir/Other", "A/Up"]


def test_parse_internal_targets_drops_self_reference() -> None:
    """A link whose resolved target equals the source path is dropped."""
    # "Source" resolves to dirname("C/Source")/Source == "C/Source" (self).
    html = '<a href="Source">self</a><a href="Keep">keep</a>'
    edges = _StructureMixin._parse_internal_link_edges(
        html, source_path="C/Source", archive=None
    )
    assert [t for t, _ in edges] == ["C/Keep"]


def test_parse_internal_targets_empty_html_is_empty_list() -> None:
    """Empty / link-free HTML yields an empty list, not an error."""
    assert (
        _StructureMixin._parse_internal_link_edges(
            "<html><body><p>no links</p></body></html>",
            source_path="C/Source",
            archive=None,
        )
        == []
    )


def test_parse_edges_captures_anchor_text() -> None:
    """Parser returns (target, anchor) pairs; image-only links yield empty anchor."""
    # href "Cat" resolves against dirname("A/Index") == "A" -> "A/Cat"
    html = (
        '<a href="Cat">the cat page</a>'
        '<a href="Dog"><img src="d.png"></a>'  # no visible text -> ''
        '<a href="Cat">cat again</a>'  # dup target -> first anchor kept
    )
    edges = _StructureMixin._parse_internal_link_edges(
        html, source_path="A/Index", archive=None
    )
    assert edges == [("A/Cat", "the cat page"), ("A/Dog", "")]
