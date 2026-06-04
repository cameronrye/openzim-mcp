"""Pure archive-type classifier for v2.5 #17 archive-type presets.

Reads only the already-extracted M-namespace metadata dict — no libzim
handle, no I/O — so it is trivially unit-testable and cannot raise on a
malformed archive. Detection is deterministic on its inputs.
"""

from __future__ import annotations

from typing import Literal, Mapping, Tuple

ArchiveType = Literal["wikipedia", "wiktionary", "stackexchange", "ted", "generic"]
Confidence = Literal["high", "medium", "none"]

# Stack Exchange "network" sites have their own apex domains; per-site SE
# instances all live under ``*.stackexchange.com``. Plain substring / prefix
# checks only — no regex (ReDoS-safe).
_SE_NETWORK_HOSTS = (
    "stackexchange.com",
    "superuser.com",
    "serverfault.com",
    "askubuntu.com",
    "stackoverflow.com",
    "mathoverflow.net",
)


def _norm(value: object) -> str:
    """Lowercased, stripped string view of a metadata value.

    Returns ``""`` for anything that is not a ``str`` so a malformed
    archive (e.g. ``Name`` accidentally an int) degrades to generic
    instead of raising.
    """
    return value.strip().lower() if isinstance(value, str) else ""


def detect_archive_type(
    metadata_entries: Mapping[str, object],
) -> Tuple[ArchiveType, Confidence]:
    """Classify a ZIM archive from its M-namespace metadata entries.

    Returns ``(type, confidence)``. ``confidence`` is ``"high"`` only when a
    strong, near-unique signal matched (the ``Scraper`` tool); ``"medium"``
    when only a weaker corroborating signal matched (``Name`` prefix,
    ``Creator`` / ``Tags``); ``"none"`` when nothing matched (type
    ``"generic"``). Never raises.
    """
    scraper = _norm(metadata_entries.get("Scraper"))
    name = _norm(metadata_entries.get("Name"))
    title = _norm(metadata_entries.get("Title"))
    creator = _norm(metadata_entries.get("Creator"))
    tags = _norm(metadata_entries.get("Tags"))

    # 1. Scraper — the strongest, near-unique signal.
    if scraper.startswith("sotoki"):
        return ("stackexchange", "high")
    if scraper.startswith("ted2zim"):
        return ("ted", "high")
    if scraper.startswith("mwoffliner"):
        # mwoffliner builds both Wikipedia and Wiktionary; disambiguate on
        # Name/Title, else default to wikipedia (the dominant case).
        if name.startswith("wiktionary") or "wiktionary" in title:
            return ("wiktionary", "high")
        return ("wikipedia", "high")

    # 2. Name prefix — strong but Scraper-less, so only medium.
    if name.startswith("wikipedia"):
        return ("wikipedia", "medium")
    if name.startswith("wiktionary"):
        return ("wiktionary", "medium")
    if name.startswith("ted_") or name.startswith("ted-"):
        return ("ted", "medium")
    if ".stackexchange.com" in name or name.startswith(_SE_NETWORK_HOSTS):
        return ("stackexchange", "medium")

    # 3. Creator / Tags — weak corroboration only.
    if "stack exchange" in creator or "stackexchange" in tags:
        return ("stackexchange", "medium")
    if "wiktionary" in tags or "wiktionary" in creator:
        return ("wiktionary", "medium")
    if "wikipedia" in tags or "wikipedia" in creator:
        return ("wikipedia", "medium")

    return ("generic", "none")
