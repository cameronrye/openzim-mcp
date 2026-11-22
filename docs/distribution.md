# Distribution runbook

How `openzim-mcp` gets discovered and installed beyond PyPI. The package is
already on PyPI (`uv tool install openzim-mcp`) and shipped as a multi-arch
Docker image; this is the maintainer playbook for the **MCP Registry** listing
and the **Claude Desktop extension**.

Two channels, two artifacts, one source of truth (the PyPI release):

| Channel | Artifact | Model |
| --- | --- | --- |
| **Official MCP Registry** (`registry.modelcontextprotocol.io`) | [`server.json`](../server.json) | Points clients at the PyPI package, run via `uvx`. Aggregators (PulseMCP, mcp.so, …) ingest from here — highest-leverage. |
| **Claude Desktop extension** (GitHub release asset) | `.mcpb` bundle | A local stdio server packaged as an MCPB bundle users download and double-click. |

Both expose the **advanced 8-tool surface** (`OPENZIM_MCP_TOOL_MODE=advanced`),
as does the Docker image — registry directories launch it with no
configuration, so the image has to name the surface itself.
A guard test, [`tests/test_mcpb_distribution.py`](../tests/test_mcpb_distribution.py),
keeps both artifacts in lockstep with the package version and tool surface.

---

## Why these specific choices

- **Local bundle, not hosted.** openzim-mcp needs each user's own local `.zim`
  files. A hosted (shared-URL) instance runs on stateless cloud and can't reach
  a user's disk, so the server ships as a **local stdio** server — an MCPB
  (`.mcpb`) bundle.
- **uvx launcher, not a vendored env.** The native `libzim` dependency makes a
  self-contained bundle platform-locked: one bundle per OS and architecture.
  The bundle instead launches `uvx openzim-mcp@<version>`, so `uvx` resolves the
  platform-correct `libzim` wheel from PyPI at run time. Trade-off: the host
  needs [`uv`](https://docs.astral.sh/uv/). The manifest declares
  `server.type: "python"` and launches `command: "uvx"`.
- **Plain zip, not `mcpb pack`.** A `.mcpb` is just a zip with `manifest.json`
  at its root. The MCPB manifest schema only allows `{name, description}` per
  tool, so `mcpb pack`/`mcpb validate` strip the `inputSchema`/`outputSchema`
  keys. [`scripts/build_mcpb.py`](../scripts/build_mcpb.py) injects the live
  tool schemas and plain-zips to preserve them. Nothing in this repository
  reads those two keys back; the capture step does fail the build unless the
  advanced surface is exactly 8 tools.

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
populated. The workflow builds the bundle into a separate directory,
`dist-mcpb/`, never `dist/`, so it is excluded from the PyPI upload and
attached to the GitHub release only.

To build it by hand (e.g. to try a manifest change before a release):

```bash
uv run python scripts/build_mcpb.py        # -> dist/openzim-mcp-<version>.mcpb (+ .sha256)
uv run python scripts/build_mcpb.py --output dist-mcpb   # what release.yml runs
```

A hand build defaults to `dist/`, beside the wheel and sdist; pass `--output`
to keep it out of anything that uploads `dist/`.

The script reads the version from `pyproject.toml`, spawns the server in
advanced mode over stdio to capture the live tool schemas, injects them into the
manifest, and plain-zips the bundle with pinned entry timestamps (rebuilding the
same commit is byte-identical). It fails loudly if the advanced surface is not
exactly the expected tool count (a tool-registration regression must break the
build, not ship a short manifest). The build host must be macOS/Linux — the
stdio handshake uses `select()` on a pipe — but the produced bundle is
cross-platform.

---

## 2. Official MCP Registry — `server.json`

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

# Do NOT run `mcp-publisher status` as a check. It MUTATES a version's
# lifecycle state and exits 1 without `--status`, which is why release.yml
# dropped it (a test now forbids re-adding it). Read the entry back instead:

# Confirm:
curl "https://registry.modelcontextprotocol.io/v0/servers?search=openzim-mcp"
```

Downstream (no action needed): **PulseMCP** and **mcp.so** ingest from the
official registry (up to ~1 week latency). **Glama** indexes the public
GitHub repo, and the listing is already claimed through
[`glama.json`](../glama.json). Glama scores the tool definitions the running
server serves, and it builds the [`Dockerfile`](../Dockerfile) with the
classic builder, not BuildKit, so keep that file free of BuildKit-only syntax
(check with `DOCKER_BUILDKIT=0 docker build .`; `docker-publish.yml`'s
`classic-builder` job does the same in CI).

---

## Ongoing maintenance

All of this is done and in steady state: the manifest, `server.json`, build
script, README marker, guard test, release-please auto-bump, and `.mcpb`
release-asset wiring have shipped, and the first registry publish went out
with v2.5.1. Nothing needs doing for the official registry: the release
workflow keeps the manifests version-locked, publishes `server.json` via OIDC
(§2), and attaches the `.mcpb` (with its `.sha256`) to each GitHub release for
you. Check the `publish-registry` job if the registry search API lags a
release.
