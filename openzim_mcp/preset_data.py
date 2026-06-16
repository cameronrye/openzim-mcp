"""Loader + resolver for v2.5 #17 archive-type presets.

Presets are data (``openzim_mcp/data/presets.toml``), keyed by detected
archive type, with an optional operator override file (deep-merged per
type) plus per-archive pins. Mirrors the ``query_rewrite_data`` loader:
stdlib ``tomllib`` (Python >=3.12), ``lru_cache``, ``importlib.resources``
for bundled data. Files are read as explicit UTF-8 then parsed with
``tomllib.loads`` (sidesteps the Windows cp1252 trap).
"""

from __future__ import annotations

import functools
import logging
import tomllib
from importlib import resources
from pathlib import Path
from typing import Dict, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openzim_mcp.archive_types import detect_archive_type

logger = logging.getLogger(__name__)

SummaryStyle = Literal["first_section", "q_and_a", "gloss", "transcript"]


class ArchivePreset(BaseModel):
    """Per-type behavior overrides. All fields optional; a missing field
    inherits the global default. ``extra='forbid'`` turns a typo in the
    TOML into a load-time error rather than a silently-ignored key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snippet_length: Optional[int] = Field(default=None, ge=100)
    max_paragraphs: Optional[int] = Field(default=None, ge=1)
    summary_style: Optional[SummaryStyle] = None


class ArchivePin(ArchivePreset):
    """A per-archive override keyed by M/Name. ``type`` forces a detected
    type (overriding the confidence gate); the inherited fields override
    individual preset values for that one archive."""

    type: Optional[str] = None


class PresetSet(BaseModel):
    """The fully-resolved preset universe for a process."""

    model_config = ConfigDict(extra="forbid")

    by_type: Dict[str, ArchivePreset] = Field(default_factory=dict)
    pins: Dict[str, ArchivePin] = Field(default_factory=dict)


def _read_bundled() -> str:
    return (
        resources.files("openzim_mcp.data")
        .joinpath("presets.toml")
        .read_text(encoding="utf-8")
    )


def _parse_doc(
    doc: Mapping[str, object],
) -> Tuple[Dict[str, ArchivePreset], Dict[str, ArchivePin]]:
    """Validate the ``[preset.*]`` / ``[archive.*]`` tables into models.

    A malformed individual table is logged and skipped so one bad entry
    doesn't blow up the whole load.
    """
    by_type: Dict[str, ArchivePreset] = {}
    pins: Dict[str, ArchivePin] = {}
    presets_raw = doc.get("preset", {})
    pins_raw = doc.get("archive", {})
    if isinstance(presets_raw, dict):
        for key, body in presets_raw.items():
            try:
                by_type[str(key)] = ArchivePreset(**body)
            except (ValidationError, TypeError) as e:
                logger.warning("preset_data: bad [preset.%s] dropped: %s", key, e)
    if isinstance(pins_raw, dict):
        for key, body in pins_raw.items():
            try:
                pins[str(key)] = ArchivePin(**body)
            except (ValidationError, TypeError) as e:
                logger.warning("preset_data: bad [archive.%s] dropped: %s", key, e)
    return by_type, pins


def _merge(base: Optional[ArchivePreset], overlay: Mapping[str, object]) -> dict:
    """Field-level overlay: base fields, overridden by any key in overlay.

    Callers must pass overlay with None values already excluded
    (``model_dump(exclude_none=True)``) so base fields the overlay leaves
    unset are preserved.
    """
    merged: dict = base.model_dump(exclude_none=True) if base is not None else {}
    merged.update(overlay)
    return merged


@functools.lru_cache(maxsize=8)
def load_presets(override_path: Optional[Path]) -> PresetSet:
    """Load the bundled presets, deep-merging an optional operator override.

    ``override_path=None`` loads the bundled defaults only. An unreadable or
    malformed override file logs a warning and falls back to the bundled
    defaults (never raises at server startup).
    """
    by_type, pins = _parse_doc(tomllib.loads(_read_bundled()))

    if override_path is not None:
        try:
            text = Path(override_path).read_text(encoding="utf-8")
            o_by_type, o_pins = _parse_doc(tomllib.loads(text))
        except (OSError, tomllib.TOMLDecodeError) as e:
            logger.warning(
                "preset_data: override %s unreadable (%s); using bundled defaults",
                override_path,
                e,
            )
            o_by_type, o_pins = {}, {}
        for t, op in o_by_type.items():
            by_type[t] = ArchivePreset(
                **_merge(by_type.get(t), op.model_dump(exclude_none=True))
            )
        for n, op in o_pins.items():
            base = pins.get(n)
            merged = _merge(base, op.model_dump(exclude_none=True))
            pins[n] = ArchivePin(**merged)

    return PresetSet(by_type=by_type, pins=pins)


def resolve_preset(
    presets: PresetSet,
    archive_type: str,
    confidence: str,
    archive_name: str,
) -> Optional[ArchivePreset]:
    """Resolve the effective preset for an archive.

    A per-archive pin (keyed by M/Name) wins and forces application even
    below ``high`` confidence. Otherwise a type preset applies only at
    ``high`` confidence. Returns ``None`` (generic behavior) when nothing
    applies.
    """
    pin = presets.pins.get(archive_name)
    if pin is not None:
        forced_type = pin.type or archive_type
        base = presets.by_type.get(forced_type)
        overlay = pin.model_dump(exclude_none=True, exclude={"type"})
        merged = _merge(base, overlay)
        return ArchivePreset(**merged) if merged else None

    if confidence != "high":
        return None
    return presets.by_type.get(archive_type)


def resolve_preset_from_entries(
    entries: Mapping[str, object],
    override_path: Optional[Path],
) -> Tuple[Optional[ArchivePreset], Optional[str]]:
    """Return ``(preset, applied_type)`` from already-extracted M-namespace entries.

    The single resolution path shared by the metadata, search, and summary
    callers — they differ only in how they SOURCE ``entries`` (cached
    metadata response vs an already-open archive handle). ``override_path``
    is forwarded to ``load_presets`` (cached, cheap). Returns ``(None, None)``
    when no preset applies; never raises on odd inputs.
    """
    if not isinstance(entries, dict):
        entries = {}
    atype, confidence = detect_archive_type(entries)
    name = entries.get("Name", "")
    if not isinstance(name, str):
        name = ""
    presets = load_presets(override_path)
    preset = resolve_preset(presets, atype, confidence, name)
    if preset is None:
        return None, None
    pin = presets.pins.get(name)
    effective_type: str = (pin.type or atype) if pin is not None else atype
    return preset, effective_type
