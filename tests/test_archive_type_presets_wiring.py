"""End-to-end detection + preset wiring (v2.5 #17)."""

from pathlib import Path

import pytest
from libzim.writer import Creator

from tests.conftest_v2_fixtures import _HtmlItem, make_zim_ops


def _build_zim(out: Path, *, scraper: str, name: str) -> Path:
    with Creator(out).config_indexing(True, "eng") as creator:
        creator.add_item(
            _HtmlItem(
                "C/Q1",
                "How do I X?",
                "<html><body><h1>How do I X?</h1>"
                "<p>Question body para one.</p>"
                "<p>Question body para two.</p>"
                "<h2>Answer</h2><p>The accepted answer text.</p></body></html>",
            )
        )
        creator.set_mainpath("C/Q1")
        creator.add_metadata("Scraper", scraper)
        creator.add_metadata("Name", name)
        creator.add_metadata("Title", name)
    return out


@pytest.fixture(scope="module")
def se_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("se") / "superuser.com_en_all.zim"
    return _build_zim(out, scraper="sotoki 2.1.0", name="superuser.com_en_all")


def test_metadata_surfaces_detected_type(se_zim: Path) -> None:
    ops = make_zim_ops(str(se_zim.parent))
    resp = ops.get_zim_metadata_data(str(se_zim))
    assert resp["_meta"]["detected_type"] == "stackexchange"
    assert resp["_meta"]["detection_confidence"] == "high"
    # The reserved keys never leak into the public body.
    assert "_detected_type" not in resp
    assert "detected_type" not in resp


def test_resolve_archive_preset_returns_se_preset(se_zim: Path) -> None:
    ops = make_zim_ops(str(se_zim.parent))
    preset, applied = ops._resolve_archive_preset(Path(str(se_zim)))
    assert applied == "stackexchange"
    assert preset is not None
    assert preset.summary_style == "q_and_a"


@pytest.fixture(scope="module")
def plain_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("plain") / "wikipedia_en_test.zim"
    with Creator(out).config_indexing(True, "eng") as creator:
        creator.add_item(
            _HtmlItem(
                "C/Photosynthesis",
                "Photosynthesis",
                "<html><body><h1>Photosynthesis</h1>"
                "<p>Para one about photosynthesis.</p>"
                "<p>Para two photosynthesis detail.</p>"
                "<p>Para three photosynthesis more.</p>"
                "<p>Para four photosynthesis extra.</p></body></html>",
            )
        )
        creator.set_mainpath("C/Photosynthesis")
        creator.add_metadata("Name", "wikipedia_en_test")
    return out


def test_search_snippet_generic_path_unchanged(plain_zim: Path) -> None:
    # No override file -> Name-only "wikipedia" detection is MEDIUM, so no
    # preset applies -> generic snippet (default max_paragraphs=2).
    ops = make_zim_ops(str(plain_zim.parent))
    resp = ops.search_zim_file_data(str(plain_zim), "photosynthesis")
    assert resp["results"], "expected a hit"
    assert resp["_meta"].get("preset_applied") is None


def test_search_snippet_uses_pinned_preset(tmp_path: Path, plain_zim: Path) -> None:
    from openzim_mcp.preset_data import load_presets

    load_presets.cache_clear()
    override = tmp_path / "ov.toml"
    # Pin this archive to stackexchange (max_paragraphs=3 from bundled),
    # forcing a preset regardless of detection.
    override.write_text(
        '[archive."wikipedia_en_test"]\ntype = "stackexchange"\n', encoding="utf-8"
    )
    ops = make_zim_ops(str(plain_zim.parent))
    ops.config.presets_override_path = override
    resp = ops.search_zim_file_data(str(plain_zim), "photosynthesis")
    assert resp["results"], "expected a hit"
    assert resp["_meta"]["preset_applied"] == "stackexchange"
    load_presets.cache_clear()
