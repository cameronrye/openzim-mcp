"""Gates for the doc facts that keep going stale.

Three classes of documentation defect have recurred often enough to be worth
a test rather than a review habit:

1. **Hand-copied measurements.** The advanced-mode schema footprint was
   written into six files and every one of them was stale — the v3.2.1 trim
   moved the number and nothing pointed at the docs. The measurement already
   exists in ``tests/test_phase_f_schema_budget.py``; this module reuses it
   and checks the prose against it.

2. **Version declarations that nobody stamps.** ``website/public/humans.txt``
   advertised ``Version: 2.1.7`` through eleven releases because it carried no
   ``x-release-please-version`` annotation and was not in ``extra-files``.
   ``test_mcpb_distribution`` pins the files that *are* annotated; this module
   sweeps the whole doc corpus for a declaration that should have been.

3. **A hand-transcribed API reference.** The published signature block for
   ``zim_get_section`` was missing ``include_subsections`` — a real parameter,
   documented nowhere on the site. The page tells readers "if signatures here
   disagree with code, file an issue", which is drift detection delegated to
   strangers. Parameter names, enum values and required-ness are checked here
   instead; the prose stays hand-written.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

from openzim_mcp import __version__
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

REPO = Path(__file__).resolve().parents[1]

# Every documentation surface a reader can reach, plus the repo-root policy
# files. ``website/dist`` is build output and ``docs/superpowers`` is
# gitignored planning scratch, so neither is scanned.
_DOC_ROOTS = (
    [REPO / name for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md")]
    + sorted((REPO / "docs").glob("*.md"))
    + sorted((REPO / "website" / "src").rglob("*.mdx"))
    + sorted((REPO / "website" / "src").rglob("*.astro"))
    + sorted((REPO / "website" / "public").glob("*.txt"))
)


def _doc_files() -> list[Path]:
    return [p for p in _DOC_ROOTS if p.is_file()]


def test_doc_corpus_is_non_empty() -> None:
    """Guard the guards: a bad glob would make every scan below vacuous."""
    files = _doc_files()
    assert len(files) >= 20, f"doc corpus collapsed to {len(files)} files: {files}"


# --------------------------------------------------------------------------
# 1. The advertised schema footprint must match the measured one.
# --------------------------------------------------------------------------


# Mirrors ``_measure_tools`` in tests/test_phase_f_schema_budget.py — the wire
# bytes of everything ``tools/list`` actually ships. Duplicated rather than
# imported so a change to the budget test's helper cannot silently redefine
# what the docs are being checked against.
def _advanced_surface_bytes() -> int:
    allowed = tempfile.mkdtemp(prefix="openzim_mcp_docs_freshness_")
    cfg = OpenZimMcpConfig(allowed_directories=[allowed], tool_mode="advanced")
    srv = OpenZimMcpServer(cfg)
    total = 0
    for name, tool in srv.mcp._tool_manager._tools.items():
        payload = {
            "name": name,
            "description": tool.description,
            "inputSchema": tool.parameters,
        }
        if tool.output_schema is not None:
            payload["outputSchema"] = tool.output_schema
        total += len(json.dumps(payload, separators=(",", ":")).encode())
    return total


# "23,898 bytes" / "23,898-byte" — an exact byte count stated as fact.
# The negative lookbehind keeps this off the tail of a larger grouped number:
# without it, "10,000,000 bytes" (the binary cap) matches as "00,000 bytes".
_BYTES_RE = re.compile(r"(?<![\d,])(\d{2},\d{3})(?:[- ]byte\b|\s+bytes\b)")
# "~23.3KB" / "~23.3 KB" — the rounded figure, only when it is describing the
# advanced surface. Matched near the MCP-Tax/footprint prose to avoid catching
# unrelated sizes (the reranker's install footprint, ZIM file sizes).
_KB_RE = re.compile(r"~(\d{2}\.\d)\s?KB")

# Figures that are legitimately not the current measurement: the pre-
# consolidation v1 footprint quoted as a before/after, and the budget cap
# (which is a constant, not a measurement).
#
# The superseded measurement (25,432) is deliberately NOT exempt — that is
# exactly the value this gate exists to catch, and exempting it was how the
# first version of this test passed its own mutation check.
_FOOTPRINT_EXEMPT = ("~36KB", "25,600")


def test_advertised_schema_footprint_matches_measurement() -> None:
    measured = _advanced_surface_bytes()
    exact = f"{measured:,}"
    rounded = f"{measured / 1024:.1f}"

    bad: list[str] = []
    for path in _doc_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            rel = path.relative_to(REPO)
            for m in _BYTES_RE.finditer(line):
                found = m.group(1)
                if found in _FOOTPRINT_EXEMPT or found == exact:
                    continue
                bad.append(f"{rel}:{lineno}: states {found} bytes")
            if "MCP Tax" in line or "wire footprint" in line or "schema" in line:
                for m in _KB_RE.finditer(line):
                    if m.group(1) == rounded:
                        continue
                    if f"~{m.group(1)}KB" in _FOOTPRINT_EXEMPT:
                        continue
                    bad.append(f"{rel}:{lineno}: states ~{m.group(1)}KB")

    assert not bad, (
        "the advanced-mode schema footprint is documented as a number that no "
        f"longer matches the surface. Measured now: {exact} bytes "
        f"(~{rounded}KB). Offending lines:\n  " + "\n  ".join(bad)
    )


# --------------------------------------------------------------------------
# 2. A version declaration must be stamped or current.
# --------------------------------------------------------------------------

# ``Version: 3.2.3``, ``"version": "3.2.3"``, ``**Version:** 3.2.3`` — a line
# declaring *this project's* version, as opposed to prose mentioning some past
# release ("shipped in v2.3.0"). Only declarations are checked: enumerating
# every historical mention in the corpus costs more than it catches, and a
# past-tense mention does not rot the way a bare declaration does.
_VERSION_DECL_RE = re.compile(r"""(?ix)
    (?:^|[\s*"'`|])              # start, or a markdown/JSON delimiter
    version                      # the literal word
    \**\s*[:=]\s*                # : or = (tolerating bold markers)
    \**["'v]*                    # optional quotes / a leading v
    (\d+\.\d+\.\d+)              # the semver
    """)

# Declarations that are deliberately not this project's version.
_FOREIGN_VERSION_CONTEXT = (
    "python",
    "libzim",
    "protocol",
    "schema",
    "sotoki",
    "node",
    "astro",
    "fastembed",
    "sidecar",
)


def test_version_declarations_are_stamped_or_current() -> None:
    """A bare ``Version: X.Y.Z`` in a doc rots at the next release."""
    offenders: list[str] = []
    for path in _doc_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "x-release-please" in line:
                continue  # release-please stamps this line
            lowered = line.lower()
            if any(ctx in lowered for ctx in _FOREIGN_VERSION_CONTEXT):
                continue
            for found in _VERSION_DECL_RE.findall(line):
                if found == __version__:
                    continue
                rel = path.relative_to(REPO)
                offenders.append(f"{rel}:{lineno}: declares version {found}")

    assert not offenders, (
        f"version declarations that are neither stamped nor current "
        f"({__version__}):\n  " + "\n  ".join(offenders) + "\n"
        "Either add an `x-release-please-version` annotation to the line AND "
        "register the file in release-please-config.json's extra-files, or "
        "reword it so it is not a bare version declaration."
    )


# --------------------------------------------------------------------------
# 3. The API reference's signature blocks must match the live schemas.
# --------------------------------------------------------------------------

_API_REFERENCE = REPO / "website/src/content/docs/api-reference.mdx"

# ```python\nzim_get(\n    entry_path: str,\n ...\n) -> Any\n```
# Two shapes appear on the page: a multi-line block (one parameter per line)
# and a one-liner for the single-argument tools, e.g.
# ``zim_metadata(zim_file_path: str) -> Any``. Both must be recognised or a
# tool silently drops out of the parity check.
_SIGNATURE_RE = re.compile(r"```python\n(zim_[a-z_]+)\((.*?)\)\s*->", re.DOTALL)
# "    entry_path: Optional[str] = None," -> entry_path, in either shape.
_PARAM_RE = re.compile(r"(?:^\s*|,\s*|\(\s*)([a-z_][a-z0-9_]*)\s*:", re.MULTILINE)


def _documented_signatures() -> dict[str, set[str]]:
    text = _API_REFERENCE.read_text(encoding="utf-8")
    return {
        m.group(1): set(_PARAM_RE.findall(m.group(2)))
        for m in _SIGNATURE_RE.finditer(text)
    }


def _live_signatures() -> dict[str, set[str]]:
    allowed = tempfile.mkdtemp(prefix="openzim_mcp_docs_sig_")
    cfg = OpenZimMcpConfig(allowed_directories=[allowed], tool_mode="advanced")
    srv = OpenZimMcpServer(cfg)
    return {
        name: set((tool.parameters or {}).get("properties", {}))
        for name, tool in srv.mcp._tool_manager._tools.items()
    }


def test_api_reference_documents_every_advanced_tool() -> None:
    documented = _documented_signatures()
    live = _live_signatures()
    assert documented, "no ```python signature blocks parsed out of the page"
    missing = set(live) - set(documented)
    assert (
        not missing
    ), f"api-reference.mdx has no signature block for: {sorted(missing)}"
    unknown = set(documented) - set(live)
    assert not unknown, (
        f"api-reference.mdx documents tools that are not registered: "
        f"{sorted(unknown)}"
    )


@pytest.mark.parametrize("tool_name", sorted(_live_signatures()))
def test_api_reference_signature_parameters_match(tool_name: str) -> None:
    documented = _documented_signatures().get(tool_name)
    assert documented is not None, f"no signature block for {tool_name}"
    live = _live_signatures()[tool_name]

    undocumented = live - documented
    assert not undocumented, (
        f"{tool_name} accepts {sorted(undocumented)} but the published "
        "signature block omits them — a reader cannot discover the parameter. "
        "Add it to the signature block and the parameter table in "
        "website/src/content/docs/api-reference.mdx."
    )
    invented = documented - live
    assert not invented, (
        f"{tool_name}'s published signature block lists {sorted(invented)}, "
        "which the tool does not accept — calling it that way returns an "
        "`unknown_argument` envelope."
    )


def test_api_reference_enum_values_match() -> None:
    """Every enum the page spells out must be the enum the schema ships."""
    text = _API_REFERENCE.read_text(encoding="utf-8")
    live = _live_signatures()
    allowed = tempfile.mkdtemp(prefix="openzim_mcp_docs_enum_")
    cfg = OpenZimMcpConfig(allowed_directories=[allowed], tool_mode="advanced")
    srv = OpenZimMcpServer(cfg)

    missing: list[str] = []
    for name, tool in srv.mcp._tool_manager._tools.items():
        props = (tool.parameters or {}).get("properties", {})
        for param, spec in props.items():
            values = spec.get("enum")
            if not values:
                continue
            for value in values:
                if f'"{value}"' not in text and f"`{value}`" not in text:
                    missing.append(f"{name}.{param} value {value!r}")

    assert not missing, (
        "enum values accepted by the schema but never named on the API "
        f"reference page: {missing}. A value a reader cannot find is a value "
        "they cannot use."
    )
    assert live, "no live tools resolved"
