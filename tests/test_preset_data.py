"""Unit tests for the archive-type preset data layer (v2.5 #17)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from openzim_mcp.preset_data import (
    ArchivePreset,
    load_presets,
    resolve_preset,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    # load_presets is lru_cached on the override path; clear between tests
    # so override files written to tmp paths are re-read.
    load_presets.cache_clear()


class TestBundledDefaults:
    def test_bundled_has_wikipedia_and_stackexchange(self) -> None:
        presets = load_presets(None)
        assert presets.by_type["wikipedia"].summary_style == "first_section"
        assert presets.by_type["stackexchange"].summary_style == "q_and_a"

    def test_bundled_has_no_wiktionary_or_ted(self) -> None:
        presets = load_presets(None)
        assert "wiktionary" not in presets.by_type
        assert "ted" not in presets.by_type


class TestResolve:
    def test_high_confidence_applies_type_preset(self) -> None:
        presets = load_presets(None)
        preset = resolve_preset(presets, "stackexchange", "high", "x")
        assert preset is not None
        assert preset.summary_style == "q_and_a"

    def test_medium_confidence_returns_none(self) -> None:
        presets = load_presets(None)
        assert resolve_preset(presets, "stackexchange", "medium", "x") is None

    def test_unknown_type_high_returns_none(self) -> None:
        presets = load_presets(None)
        assert resolve_preset(presets, "wiktionary", "high", "x") is None


class TestOverrideAndPins:
    def test_override_deep_merges_per_type(self, tmp_path: Path) -> None:
        override = tmp_path / "ov.toml"
        override.write_text(
            "[preset.stackexchange]\nmax_paragraphs = 5\n", encoding="utf-8"
        )
        presets = load_presets(override)
        se = presets.by_type["stackexchange"]
        assert se.max_paragraphs == 5  # from override
        assert se.summary_style == "q_and_a"  # inherited from bundled

    def test_pin_forces_type_past_confidence_gate(self, tmp_path: Path) -> None:
        override = tmp_path / "ov.toml"
        override.write_text(
            '[archive."my.zim"]\ntype = "stackexchange"\n', encoding="utf-8"
        )
        presets = load_presets(override)
        # confidence is "none" but the pin forces application.
        preset = resolve_preset(presets, "generic", "none", "my.zim")
        assert preset is not None
        assert preset.summary_style == "q_and_a"

    def test_pin_field_override_wins(self, tmp_path: Path) -> None:
        override = tmp_path / "ov.toml"
        override.write_text(
            '[archive."my.zim"]\ntype = "stackexchange"\n'
            'summary_style = "first_section"\n',
            encoding="utf-8",
        )
        presets = load_presets(override)
        preset = resolve_preset(presets, "generic", "none", "my.zim")
        assert preset is not None
        assert preset.summary_style == "first_section"

    def test_unreadable_override_falls_back_to_bundled(self, tmp_path: Path) -> None:
        presets = load_presets(tmp_path / "does-not-exist.toml")
        assert presets.by_type["stackexchange"].summary_style == "q_and_a"

    def test_unknown_key_is_rejected(self, tmp_path: Path) -> None:
        # extra="forbid" turns a typo into a load-time error that the loader
        # logs and skips — so the bad type is simply absent, not silently
        # accepted with a junk field.
        override = tmp_path / "ov.toml"
        override.write_text(
            "[preset.stackexchange]\nsnippptt_length = 999\n", encoding="utf-8"
        )
        presets = load_presets(override)
        # bad override for the type is dropped; bundled default survives.
        assert presets.by_type["stackexchange"].summary_style == "q_and_a"

    def test_malformed_toml_override_falls_back_to_bundled(
        self, tmp_path: Path
    ) -> None:
        override = tmp_path / "bad.toml"
        override.write_text("this is not = valid = toml [[[", encoding="utf-8")
        presets = load_presets(override)
        assert presets.by_type["stackexchange"].summary_style == "q_and_a"

    def test_override_can_introduce_new_type(self, tmp_path: Path) -> None:
        override = tmp_path / "ov.toml"
        override.write_text(
            '[preset.wiktionary]\nsummary_style = "first_section"\n',
            encoding="utf-8",
        )
        presets = load_presets(override)
        assert presets.by_type["wiktionary"].summary_style == "first_section"
        # high-confidence resolve now yields the newly-introduced type preset
        preset = resolve_preset(presets, "wiktionary", "high", "x")
        assert preset is not None
        assert preset.summary_style == "first_section"


def test_archive_preset_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ArchivePreset(bogus=1)  # type: ignore[call-arg]
