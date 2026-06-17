# Distribution runbook

How `openzim-mcp` gets discovered and installed beyond PyPI. The package is
already on PyPI (`uv tool install openzim-mcp`) and shipped as a multi-arch
Docker image; this is the maintainer playbook for the **MCP registries**.

Two listings, two artifacts, one source of truth (the PyPI release):

| Channel | Artifact | Model |
| --- | --- | --- |
| **Official MCP Registry** (`registry.modelcontextprotocol.io`) | [`server.json`](../server.json) | Points clients at the PyPI package, run via `uvx`. Aggregators (PulseMCP, mcp.so, …) ingest from here — highest-leverage. |
| **Smithery** (`smithery.ai/servers/rye/openzim-mcp`) | `.mcpb` bundle | A local stdio server distributed as an MCPB bundle clients download and run locally. |

Both expose the **advanced 8-tool surface** (`OPENZIM_MCP_TOOL_MODE=advanced`).
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

## 0. On every release (keep versions in lockstep)

`tests/test_mcpb_distribution.py` fails if these drift from `pyproject.toml`:

1. `packaging/mcpb/manifest.json` → `version` and the `openzim-mcp@<v>` launch arg.
2. `server.json` → top-level `version` and `packages[0].version`.

Bump both when the package version changes. (Optional follow-up: add them to the
release-please `extra-files` so the bump is automatic — intentionally not wired
yet to keep the release workflow unchanged.)

---

## 1. Build the `.mcpb` bundle

```bash
uv run python scripts/build_mcpb.py        # -> dist/openzim-mcp-<version>.mcpb
```

The script reads the version from `pyproject.toml`, spawns the server in
advanced mode over stdio to capture the live tool schemas, injects them into the
manifest, and plain-zips the bundle. It fails loudly if the advanced surface is
not exactly the expected tool count (a tool-registration regression must break
the build, not ship a short manifest).

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
The marker was added in this change, so the **first registry publish must target
the first release that ships it** (i.e. the next release, not a version already
on PyPI without the marker).

```bash
# Install the publisher CLI
brew install mcp-publisher
# or download from github.com/modelcontextprotocol/registry/releases/latest

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

1. Land this change (manifest, `server.json`, build script, README marker, guard test).
2. Build + publish/update the Smithery `.mcpb` (§1–§2) — does **not** depend on a release.
3. On the next PyPI release (README marker now live), publish `server.json` to
   the official registry (§3); aggregators follow automatically.
