# Distribution runbook

How `openzim-mcp` gets discovered and installed beyond PyPI. The package is
already on PyPI (`uv tool install openzim-mcp`) and shipped as a multi-arch
Docker image; this is the maintainer playbook for the **MCP registries**.

Two listings, two artifacts, one source of truth (the PyPI release):

| Channel | Artifact | Model |
| --- | --- | --- |
| **Official MCP Registry** (`registry.modelcontextprotocol.io`) | [`server.json`](../server.json) | Points clients at the PyPI package, run via `uvx`. Aggregators (PulseMCP, mcp.so, …) ingest from here — highest-leverage. |
| **Smithery** (`smithery.ai/servers/rye/openzim-mcp`) | `.mcpb` bundle | A local stdio server distributed as an MCPB bundle clients download and run locally. |

Both expose the **advanced 8-tool surface** (`OPENZIM_MCP_TOOL_MODE=advanced`),
as does the Docker image — registry directories launch it with no
configuration, so the image has to name the surface itself.
A guard test, [`tests/test_mcpb_distribution.py`](../tests/test_mcpb_distribution.py),
keeps both artifacts in lockstep with the package version and tool surface.

---

## Why these specific choices

- **Local bundle, not hosted.** openzim-mcp needs each user's own local `.zim`
  files. A Smithery-hosted (or any shared-URL) instance runs on stateless cloud
  and can't reach a user's disk, so the only workable Smithery model is a
  **local stdio** server — an MCPB (`.mcpb`) bundle.
- **uvx launcher, not a vendored env.** The native `libzim` dependency makes a
  self-contained bundle platform-locked and would blow the registry's 25 MB cap.
  The bundle instead launches `uvx openzim-mcp@<version>`, so `uvx` resolves the
  platform-correct `libzim` wheel from PyPI at run time. Trade-off: the host
  needs [`uv`](https://docs.astral.sh/uv/). (Smithery's bundle publisher rejects
  `server.type: "uv"`, so the manifest uses `server.type: "python"` with
  `command: "uvx"`.)
- **Plain zip, not `mcpb pack`.** A `.mcpb` is just a zip with `manifest.json`
  at its root. The MCPB manifest schema only allows `{name, description}` per
  tool, so `mcpb pack`/`mcpb validate` strip the `inputSchema`/`outputSchema`
  keys — exactly the schemas Smithery and Glama score listings on.
  [`scripts/build_mcpb.py`](../scripts/build_mcpb.py) injects the live tool
  schemas and plain-zips to preserve them.

---

## 0. Version lockstep (automated)

release-please bumps these in the release PR automatically, via the `json`
updaters in [`release-please-config.json`](../release-please-config.json)
`extra-files`:

- `packaging/mcpb/manifest.json` → `version`
- `server.json` → `version` and `packages[0].version`

The MCPB launch arg is deliberately **not** in that list: it is the composite
string `openzim-mcp@<v>`, which a `json` updater would clobber to a bare version.
The static template therefore ships an unpinned `openzim-mcp`, and
[`scripts/build_mcpb.py`](../scripts/build_mcpb.py) stamps the exact
`openzim-mcp@<version>` into the shipped bundle at build time.

`tests/test_mcpb_distribution.py` still asserts the static `version` fields equal
`pyproject.toml`, and the release-please `validate-release` job re-checks them at
tag time — so a missed/mis-pathed bump fails loudly before anything publishes.

---

## 1. Build the `.mcpb` bundle

The release workflow ([`.github/workflows/release.yml`](../.github/workflows/release.yml))
builds this automatically and attaches `openzim-mcp-<version>.mcpb` (plus a
`.sha256`) to every GitHub release, so the README's one-click download is always
populated. The bundle is built into a separate directory — never `dist/` — so it
is excluded from the PyPI upload and attached to the GitHub release only.

To build it by hand (e.g. to publish/refresh the Smithery listing between
releases):

```bash
uv run python scripts/build_mcpb.py        # -> dist/openzim-mcp-<version>.mcpb (+ .sha256)
```

The script reads the version from `pyproject.toml`, spawns the server in
advanced mode over stdio to capture the live tool schemas, injects them into the
manifest, and plain-zips the bundle with pinned entry timestamps (rebuilding the
same commit is byte-identical). It fails loudly if the advanced surface is not
exactly the expected tool count (a tool-registration regression must break the
build, not ship a short manifest). The build host must be macOS/Linux — the
stdio handshake uses `select()` on a pipe — but the produced bundle is
cross-platform.

---

## 2. Smithery — publish / update the listing

One-time auth (already done on this machine): `npx @smithery/cli auth login`,
and the `rye` namespace must exist (`npx @smithery/cli namespace list`).

```bash
npx @smithery/cli mcp publish dist/openzim-mcp-<version>.mcpb -n rye/openzim-mcp
# Do NOT pass --config-schema for a bundle (URL-only; hard-errors). The config
# schema is derived from manifest.json's user_config.allowed_directories.
# If publish pauses for OAuth:
npx @smithery/cli mcp publish --resume -n rye/openzim-mcp
```

Verify: `curl https://registry.smithery.ai/servers/rye/openzim-mcp` — the
`connections[0]` should show `runtime: python`, the `configSchema`, and the
listing page enumerates the 8 tools.

---

## 3. Official MCP Registry — `server.json`

**Hard ordering constraint:** the registry validates the *live* PyPI package's
README for an ownership marker — `<!-- mcp-name: io.github.cameronrye/openzim-mcp -->`
in `README.md` (which becomes the PyPI description via `readme = "README.md"`).
That marker must be present **in a published PyPI version** before you publish to
the registry, and `server.json`'s `packages[0].version` must equal that version.
The marker has shipped in every release since v2.5.0, and the first registry
publish (v2.5.1) is done — so the constraint is now satisfied automatically:
`server.json` is auto-bumped by release-please, and a registry re-publish just
needs the matching version to already be live on PyPI.

**Publishing is automated.** `release.yml`'s `publish-registry` job runs after
the PyPI upload on every release: it logs in with `mcp-publisher login
github-oidc` (the Actions OIDC token proves ownership of `io.github.cameronrye/*`,
no stored secret), waits until PyPI serves the new version, then publishes
`server.json`. It is not a dependency of the GitHub release, so a registry
outage cannot block or empty a release. Before this job existed the entry was
advanced by hand and sat at 2.5.1 while PyPI was on 3.0.0.

To backfill a release that shipped before the job (or re-run after a registry
outage), dispatch the release workflow for the existing tag —
`gh workflow run release.yml -f tag=v3.0.0` — or publish by hand:

```bash
# Install the publisher CLI
brew install mcp-publisher
# or download from github.com/modelcontextprotocol/registry/releases/latest

git checkout v3.0.0                # server.json must match the live PyPI version
mcp-publisher validate            # checks ./server.json against the schema
mcp-publisher login github        # device-code OAuth as cameronrye;
                                  # authorizes the io.github.cameronrye/* namespace
mcp-publisher publish             # defaults to ./server.json
mcp-publisher status

# Confirm:
curl "https://registry.modelcontextprotocol.io/v0/servers?search=openzim-mcp"
```

Downstream (no action needed): **PulseMCP** and **mcp.so** ingest from the
official registry (up to ~1 week latency). **Glama** auto-indexes the public
GitHub repo; claim it at glama.ai and tighten tool descriptions to raise its
score (it weights tool-definition quality heavily — the schemas live in the
server's tool definitions).

---

## Recommended sequence

All of this is done and in steady state: the manifest, `server.json`, build
script, README marker, guard test, release-please auto-bump, and `.mcpb`
release-asset wiring have shipped, Smithery is published as `rye/openzim-mcp`,
and the first registry publish went out with v2.5.1. Ongoing maintenance:

1. Re-publish the Smithery `.mcpb` (§1–§2) when the tool surface or manifest
   metadata changes — it does **not** depend on a release.
2. Nothing for the official registry: the release workflow keeps the manifests
   version-locked, publishes `server.json` via OIDC (§3), and attaches the
   `.mcpb` (with its `.sha256`) to each GitHub release for you. Check the
   `publish-registry` job if the registry search API lags a release.
