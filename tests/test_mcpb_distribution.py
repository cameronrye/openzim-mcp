"""Distribution guards for the Smithery / MCP-Registry artifacts.

These tests keep the published distribution artifacts honest and in lockstep
with the package:

  - ``packaging/mcpb/manifest.json`` — the MCPB (``.mcpb``) bundle manifest
    published to Smithery and shipped as the Claude Desktop one-click extension.
  - ``server.json`` — the official MCP Registry manifest (PyPI package).
  - ``scripts/build_mcpb.py`` — the bundle build pipeline.
  - the ``mcp-name:`` ownership marker in ``README.md`` (the PyPI description).
  - the ``x-release-please-version`` annotated version strings in ``README.md``
    and the website copy (stamped by release-please's generic updater).

A tool added to or removed from the advanced surface, or a version bump that
forgets one of these files, must fail here rather than ship a stale/wrong
listing. See ``docs/distribution.md``.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from openzim_mcp import __version__
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

REPO = Path(__file__).resolve().parent.parent
SERVER_NAME = "io.github.cameronrye/openzim-mcp"
PYPI_NAME = "openzim-mcp"


def _load_build_mcpb():
    """Import scripts/build_mcpb.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "build_mcpb", REPO / "scripts" / "build_mcpb.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(
        (REPO / "packaging" / "mcpb" / "manifest.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def server_json() -> dict:
    return json.loads((REPO / "server.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def build_mcpb():
    return _load_build_mcpb()


# --- version lockstep -------------------------------------------------------


def test_manifest_version_matches_package(manifest: dict) -> None:
    assert manifest["version"] == __version__, (
        "packaging/mcpb/manifest.json version is stale — bump it (and server.json) "
        "to match pyproject on every release. See docs/distribution.md."
    )


def test_built_manifest_launch_arg_pins_package_version(build_mcpb) -> None:
    """The *shipped* bundle pins ``openzim-mcp@<version>``.

    build_mcpb.py stamps the exact launch arg from pyproject at build time, so
    we validate the built manifest — the artifact users actually run — not the
    static template (whose arg is intentionally unpinned; see
    ``test_manifest_runtime_and_config``). This keeps the composite ``name@ver``
    string out of the per-release version-lockstep burden (a release-please
    json updater would clobber it to a bare version).
    """
    built = build_mcpb.build_manifest(__version__, [])
    args = built["server"]["mcp_config"]["args"]
    assert args == [f"{PYPI_NAME}@{__version__}", "${user_config.allowed_directories}"]


def test_server_json_versions_match_package(server_json: dict) -> None:
    assert server_json["version"] == __version__
    assert server_json["packages"][0]["version"] == __version__


# Docs whose hardcoded version strings are stamped by release-please's generic
# updater via ``x-release-please-version`` line annotations, mapped to the
# number of annotated lines each file carries. The README and website copy
# drifted through four releases (v2.5.1 survived into the v2.6.x era) before
# these annotations existed; this pins both halves of the contract — the
# annotation is present AND it carried the current version.
_VERSION_ANNOTATED_DOCS = {
    "README.md": 1,
    "website/public/llms.txt": 1,
    "website/src/content/docs/index.mdx": 2,
    "website/src/content/docs/http-and-docker-deployment.mdx": 5,
    "website/src/pages/index.astro": 2,  # + 1 date-only annotation, not counted
}


def test_doc_version_annotations_are_current() -> None:
    for rel_path, expected_count in _VERSION_ANNOTATED_DOCS.items():
        lines = (REPO / rel_path).read_text(encoding="utf-8").splitlines()
        annotated = [ln for ln in lines if "x-release-please-version" in ln]
        assert len(annotated) == expected_count, (
            f"{rel_path}: expected {expected_count} x-release-please-version "
            f"annotations, found {len(annotated)} — update _VERSION_ANNOTATED_DOCS "
            "if you added/removed a stamped version string."
        )
        stale = [ln.strip() for ln in annotated if __version__ not in ln]
        assert not stale, (
            f"{rel_path}: annotated lines missing current version {__version__} "
            f"(release-please generic updater failed to stamp them?): {stale}"
        )


# Versions these docs mention as HISTORY (support-window prose, "since
# vX.Y.Z" notes, superseded image tags) rather than as "the current
# release". Every other ``vX.Y.Z`` literal in an annotated doc must be the
# current version — otherwise it is an unannotated current-version claim,
# which is exactly the drift these annotations exist to prevent. The hero
# "Latest release" stat on the landing page sat at v2.5.1 through four
# releases because nothing checked this.
#
# THIS SET IS PART OF CUTTING A RELEASE. The moment the version bumps, every
# doc line that describes the *previous* release in the past tense stops being
# a current-version claim and starts being history — so it lands here, or the
# release job's test gate fails on the tag, after release-please has already
# created the tag and the GitHub release. That is what happened taking 3.0.0
# to 3.1.0: three lines describing what v3.0.0 broke ("**v3.0.0 is a breaking
# release for HTTP subscription clients**", the FAQ link, the changelog
# pointer) reddened the release with the tag already pushed.
_HISTORICAL_VERSIONS = {"1.0.0", "1.2.0", "2.0.0", "2.5.0", "2.6.0", "3.0.0"}

# ``v`` immediately followed by a semver, not preceded by a word char or dot
# (so SVG path data like ``a4 4 0 0 0-2.526 5.77`` can't match).
_V_SEMVER_RE = re.compile(r"(?<![\w.])v(\d+\.\d+\.\d+)\b")


def test_no_unannotated_current_version_claims() -> None:
    """A hardcoded version that is neither stamped nor declared historical."""
    offenders = []
    for rel_path in _VERSION_ANNOTATED_DOCS:
        for lineno, line in enumerate(
            (REPO / rel_path).read_text(encoding="utf-8").splitlines(), 1
        ):
            if "x-release-please" in line:
                continue
            for found in _V_SEMVER_RE.findall(line):
                if found == __version__ or found in _HISTORICAL_VERSIONS:
                    continue
                offenders.append(f"{rel_path}:{lineno}: v{found}")
    assert not offenders, (
        "unannotated version strings that are neither the current version "
        f"({__version__}) nor a declared historical reference: {offenders}. "
        "Either annotate the line with x-release-please-version (and register "
        "the file in release-please-config.json), derive it from an already-"
        "annotated constant, or add the version to _HISTORICAL_VERSIONS if it "
        "is deliberately referring to a past release."
    )


def test_annotated_docs_registered_with_release_please() -> None:
    """An annotation only works if the file is listed in extra-files."""
    config = json.loads(
        (REPO / "release-please-config.json").read_text(encoding="utf-8")
    )
    generic_paths = {
        entry["path"]
        for entry in config["packages"]["."]["extra-files"]
        if entry.get("type") == "generic"
    }
    missing = set(_VERSION_ANNOTATED_DOCS) - generic_paths
    assert not missing, (
        f"files carry x-release-please annotations but are not registered as "
        f"generic extra-files in release-please-config.json: {sorted(missing)}"
    )


# --- MCPB manifest structural invariants ------------------------------------


def test_manifest_runtime_and_config(manifest: dict) -> None:
    server = manifest["server"]
    assert server["type"] == "python"
    assert server["entry_point"] == "server/main.py"
    mcp_config = server["mcp_config"]
    assert mcp_config["command"] == "uvx"
    # The static template's launch arg is intentionally UNPINNED ("openzim-mcp",
    # no @version). build_mcpb.py stamps the exact openzim-mcp@<version> at build
    # time (see test_built_manifest_launch_arg_pins_package_version); keeping the
    # template unpinned removes it from the per-release version-lockstep burden.
    assert mcp_config["args"] == [PYPI_NAME, "${user_config.allowed_directories}"]
    # The bundle ships the advanced 8-tool surface.
    assert mcp_config["env"]["OPENZIM_MCP_TOOL_MODE"] == "advanced"
    cfg = manifest["user_config"]["allowed_directories"]
    assert cfg["type"] == "directory"
    assert cfg["required"] is True
    assert cfg["multiple"] is True


def test_dockerfile_registers_the_advanced_tool_surface() -> None:
    """The image must advertise all 8 tools, like the other packaged channels.

    Registry directories launch this image with no configuration, so whatever
    the Dockerfile sets is what the world sees in the listing. The code default
    is ``simple`` (one tool), which once left the Glama listing advertising
    ``zim_query`` alone. The .mcpb bundle and server.json both pin ``advanced``;
    this keeps the container from drifting back out of that set.
    """
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "ENV OPENZIM_MCP_TOOL_MODE=advanced" in dockerfile


def test_manifest_static_template_identity(manifest: dict) -> None:
    """Guard the static-template fields build_manifest does NOT overwrite.

    ``tools`` is injected at build time from the live server, so the committed
    template must ship empty (a stale hand-edited tools array would otherwise be
    the fallback if anyone zipped the template directly). ``name`` and
    ``manifest_version`` pass through build_manifest unchanged.
    """
    assert manifest["tools"] == []
    assert manifest["name"] == PYPI_NAME
    assert manifest["manifest_version"] == "0.3"


# --- server.json (MCP Registry) invariants ----------------------------------


def test_server_json_pypi_package(server_json: dict) -> None:
    assert server_json["name"] == SERVER_NAME
    assert len(server_json["description"]) <= 100  # registry hard limit
    pkg = server_json["packages"][0]
    assert pkg["registryType"] == "pypi"
    assert pkg["identifier"] == PYPI_NAME
    assert pkg["runtimeHint"] == "uvx"
    assert pkg["transport"]["type"] == "stdio"


def test_server_json_requires_positional_zim_directory(server_json: dict) -> None:
    args = server_json["packages"][0]["packageArguments"]
    positional = [a for a in args if a.get("type") == "positional"]
    assert positional, "server.json must declare a positional ZIM-directory argument"
    arg = positional[0]
    assert arg["isRequired"] is True
    assert arg["format"] == "filepath"


def test_server_json_validates_against_registry_schema(server_json: dict) -> None:
    """server.json must validate against the exact MCP Registry schema it
    declares, so a malformed doc (missing required field, disallowed extra key,
    malformed packageArguments/environmentVariables entry) fails here in CI
    rather than at ``mcp-publisher`` time after the release is already cut. The
    schema is vendored (pinned) so the check stays offline and deterministic.
    """
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = REPO / "tests" / "fixtures" / "mcp_server_schema_2025-12-11.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # The vendored copy must be the schema server.json points at; otherwise the
    # pin has silently drifted and we'd be validating against the wrong version.
    assert server_json["$schema"] == schema["$id"]
    jsonschema.Draft7Validator(schema).validate(server_json)


# --- ownership marker (PyPI description) ------------------------------------


def test_readme_has_ownership_marker_matching_server_json(server_json: dict) -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    match = re.search(r"mcp-name:\s*(\S+)", readme)
    assert match, (
        "README.md must carry an `mcp-name: <server-name>` marker so the MCP "
        "Registry can verify PyPI package ownership."
    )
    assert match.group(1) == server_json["name"]


# --- build pipeline guards --------------------------------------------------


def test_build_script_plain_zips_and_captures_live_schemas() -> None:
    src = (REPO / "scripts" / "build_mcpb.py").read_text(encoding="utf-8")
    assert "zipfile.ZipFile" in src, "bundle must be built as a plain zip"
    assert "tools/list" in src, "build must capture live tool schemas"


def test_build_pipeline_preserves_rich_tool_schemas(build_mcpb, tmp_path) -> None:
    """The packed bundle keeps inputSchema/outputSchema — the keys ``mcpb pack``
    would strip and the exact schemas Smithery scores. Proven by packing a tool
    that carries both and reading them back out of the zip."""
    import zipfile

    fake_tools = [
        {
            "name": "zim_query",
            "description": "d",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
            "outputSchema": {"type": "object"},
        }
    ]
    manifest = build_mcpb.build_manifest("9.9.9", fake_tools)
    out = build_mcpb.pack(manifest, tmp_path / "out.mcpb")

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        packed = json.loads(zf.read("manifest.json"))
    assert "manifest.json" in names and "server/main.py" in names
    assert packed["version"] == "9.9.9"
    assert packed["server"]["mcp_config"]["args"][0] == f"{PYPI_NAME}@9.9.9"
    tool = packed["tools"][0]
    assert tool["inputSchema"]["properties"]["q"]["type"] == "string"
    assert tool["outputSchema"] == {"type": "object"}


def test_build_expected_count_matches_advanced_surface(build_mcpb, tmp_path) -> None:
    """The build's expected tool count must equal what advanced mode registers.

    Adding/removing a tool changes the live surface and breaks this test,
    forcing ``EXPECTED_TOOL_COUNT`` (and the shipped manifest) to be updated.
    """
    cfg = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode="advanced")
    server = OpenZimMcpServer(cfg)
    registered = set(server.mcp._tool_manager._tools)
    assert len(registered) == build_mcpb.EXPECTED_TOOL_COUNT
    assert "zim_query" in registered


def test_capture_tools_rejects_wrong_tool_count(build_mcpb, monkeypatch) -> None:
    """A handshake regression that yields the wrong number of tools must break
    the build (SystemExit), never ship a short/wrong manifest. Hermetic: the
    real server spawn and the stdio handshake are stubbed out, so this covers the
    count-mismatch guard branch without spawning a subprocess.
    """

    class _FakeProc:
        def terminate(self) -> None: ...

        def communicate(self, timeout=None):
            return ("", "")

        def kill(self) -> None: ...

    monkeypatch.setattr(build_mcpb.subprocess, "Popen", lambda *a, **k: _FakeProc())
    monkeypatch.setattr(
        build_mcpb,
        "_handshake_list_tools",
        lambda proc, timeout_s: [{"name": f"t{i}"} for i in range(7)],
    )
    with pytest.raises(SystemExit):
        build_mcpb.capture_tools()


@pytest.mark.live
def test_capture_tools_live_matches_advanced_surface(build_mcpb) -> None:
    """End-to-end: spawn the real server over stdio and capture ``tools/list``.

    Exercises the initialize/initialized/tools/list handshake that the unit
    tests stub out — the most failure-prone path in build_mcpb.py — and would
    catch an SDK response-shape regression. Marked ``live`` so it is deselected
    from the default suite (run via ``make test-live``); the release pipeline
    also exercises this path when it builds the .mcpb.
    """
    tools = build_mcpb.capture_tools()
    names = {t["name"] for t in tools}
    assert len(tools) == build_mcpb.EXPECTED_TOOL_COUNT
    assert "zim_query" in names
    assert all("inputSchema" in t for t in tools)
