<p align="center">
  <img src="https://raw.githubusercontent.com/cameronrye/openzim-mcp/main/website/public/assets/favicon.svg" alt="OpenZIM MCP Logo" width="120" height="120">
</p>

<h1 align="center">OpenZIM MCP Server</h1>

<p align="center">
  <strong>Transform static ZIM archives into dynamic knowledge engines for AI models</strong>
</p>

<p align="center">
  <a href="https://github.com/cameronrye/openzim-mcp/actions/workflows/test.yml"><img src="https://github.com/cameronrye/openzim-mcp/workflows/CI/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/cameronrye/openzim-mcp"><img src="https://codecov.io/gh/cameronrye/openzim-mcp/branch/main/graph/badge.svg" alt="codecov"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/actions/workflows/codeql.yml"><img src="https://github.com/cameronrye/openzim-mcp/workflows/CodeQL%20Security%20Analysis/badge.svg" alt="CodeQL"></a>
  <a href="https://sonarcloud.io/summary/new_code?id=cameronrye_openzim-mcp"><img src="https://sonarcloud.io/api/project_badges/measure?project=cameronrye_openzim-mcp&metric=security_rating" alt="Security Rating"></a>
</p>

<p align="center">
  <a href="https://badge.fury.io/py/openzim-mcp"><img src="https://badge.fury.io/py/openzim-mcp.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/openzim-mcp/"><img src="https://img.shields.io/pypi/pyversions/openzim-mcp" alt="PyPI - Python Version"></a>
  <a href="https://pypi.org/project/openzim-mcp/"><img src="https://img.shields.io/pypi/dm/openzim-mcp" alt="PyPI - Downloads"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="https://glama.ai/mcp/servers/cameronrye/openzim-mcp">
    <img width="380" height="200" src="https://glama.ai/mcp/servers/cameronrye/openzim-mcp/badge" alt="OpenZIM MCP server quality badge">
  </a>
</p>

---

> 🆕 **8-tool advanced surface.** Phase F (v2.0.0) consolidated 22 advanced tools into 8 (`zim_query`, `zim_search`, `zim_get`, `zim_get_section`, `zim_browse`, `zim_metadata`, `zim_links`, `zim_health`). **Recent additions:** archive-type presets that auto-tune retrieval per source (Wikipedia, Stack Exchange, …), inbound link discovery ("what links here"), and native libzim health/introspection. Now listed on [Smithery](https://smithery.ai/servers/rye/openzim-mcp) and the [official MCP Registry](https://registry.modelcontextprotocol.io). [Release notes →](CHANGELOG.md) [Docs →](https://cameronrye.github.io/openzim-mcp/docs/)

**OpenZIM MCP** is a modern, secure, high-performance [Model Context Protocol](https://modelcontextprotocol.io/) server that gives AI models structured, offline access to [ZIM format](https://en.wikipedia.org/wiki/ZIM_(file_format)) knowledge archives — Wikipedia, Wiktionary, Stack Exchange, and the rest of the [Kiwix Library](https://library.kiwix.org/).

Built for research assistants, knowledge chatbots, and content-analysis systems that need *intelligent* access to vast knowledge repositories — not just a raw text dump. Smart navigation by namespace (articles, metadata, media), structure-aware retrieval (sections, tables of contents, related articles), full-text search with suggestions and multi-archive search, and link-graph extraction to map content relationships. Cached, paginated operations keep things responsive across massive archives; comprehensive input validation and path-traversal protection keep things safe.

Streamable HTTP transport, per-entry MCP resources with subscriptions, and dual Simple / Advanced modes ship in v2.0.0.

## Install

```bash
# uv (recommended — isolated CLI tool)
uv tool install openzim-mcp

# pip
pip install openzim-mcp

# Docker (multi-arch image, ghcr.io) — runs as a local stdio MCP server
docker pull ghcr.io/cameronrye/openzim-mcp
docker run -i --rm -v /path/to/zim/files:/data ghcr.io/cameronrye/openzim-mcp
```

The container defaults to **stdio** transport, so `docker run -i` speaks MCP over stdin/stdout — wire it into an MCP client the same way as the binary (see [Quick start](#quick-start)). For the long-running **HTTP** service (bearer auth, CORS, health endpoints), opt in at runtime with `-e OPENZIM_MCP_TRANSPORT=http -e OPENZIM_MCP_HOST=0.0.0.0 -e OPENZIM_MCP_AUTH_TOKEN=… -p 8000:8000`; see [HTTP & Docker deployment](https://cameronrye.github.io/openzim-mcp/docs/http-and-docker-deployment/).

Verify the install:

```bash
openzim-mcp --help
```

Download ZIM files from the [Kiwix Library](https://library.kiwix.org/) into a directory of your choice before running the server.

### Smithery & one-click install

OpenZIM MCP is listed on the [Smithery registry](https://smithery.ai/servers/rye/openzim-mcp) and the [official MCP Registry](https://registry.modelcontextprotocol.io) (as `io.github.cameronrye/openzim-mcp`). Add it to your MCP client with the Smithery CLI:

```bash
npx @smithery/cli mcp add rye/openzim-mcp --client claude
```

For a one-click **Claude Desktop extension**, download the `openzim-mcp-<version>.mcpb` asset (and its `.sha256`) from the [latest release](https://github.com/cameronrye/openzim-mcp/releases/latest) and double-click it. The bundle launches the version-pinned `uvx openzim-mcp@<version>` (so the host needs [uv](https://docs.astral.sh/uv/)) and prompts for your ZIM directory. Maintainer runbook: [docs/distribution.md](docs/distribution.md).

<!-- mcp-name: io.github.cameronrye/openzim-mcp -->

## Quick start

Run the server in Simple mode (default — exposes one natural-language tool, `zim_query`):

```bash
openzim-mcp /path/to/zim/files
```

Wire it into your MCP client. Example for Claude Desktop's `claude_desktop_config.json` (any MCP client that speaks stdio works the same way):

```json
{
  "mcpServers": {
    "openzim-mcp": {
      "command": "openzim-mcp",
      "args": ["/path/to/zim/files"]
    }
  }
}
```

Once the client connects, ask your LLM: *"summarize the article on Photosynthesis"* — `zim_query` dispatches to the right underlying tool automatically.

For full control, run in Advanced mode to expose all 8 specialized tools:

```json
{
  "mcpServers": {
    "openzim-mcp-advanced": {
      "command": "openzim-mcp",
      "args": ["--mode", "advanced", "/path/to/zim/files"]
    }
  }
}
```

For HTTP transport (long-running service with bearer auth, CORS, and health endpoints) see [HTTP & Docker deployment](https://cameronrye.github.io/openzim-mcp/docs/http-and-docker-deployment/).

## Highlights

- **8-tool advanced surface** — `zim_query`, `zim_search`, `zim_get`, `zim_get_section`, `zim_browse`, `zim_metadata`, `zim_links`, `zim_health`. Down from 22; advanced-mode schema drops from ~36KB to ~23.5KB, clearing the [MCP Tax](https://www.mmntm.net/articles/mcp-context-tax) pain band. [API reference →](https://cameronrye.github.io/openzim-mcp/docs/api-reference/)
- **Streamable HTTP transport** — bearer-token auth, CORS, health endpoints, multi-arch Docker image. [HTTP & Docker deployment →](https://cameronrye.github.io/openzim-mcp/docs/http-and-docker-deployment/)
- **Per-entry MCP resources + subscriptions** — `zim://{name}/entry/{path}` with native MIME types; clients subscribe and receive `notifications/resources/updated` when archives change. [Resources, prompts & subscriptions →](https://cameronrye.github.io/openzim-mcp/docs/resources-prompts-subscriptions/)
- **Simple-mode `zim_query`** — one natural-language tool that dispatches to the right operation, tuned for small-model deployment targets. [Quick start →](https://cameronrye.github.io/openzim-mcp/docs/quick-start/)
- **Archive-type presets** — OpenZIM MCP detects the archive type (Wikipedia, Stack Exchange, and more) and auto-tunes retrieval and summarization for it — e.g. Stack Exchange dumps render as clean Q&A instead of vote-score noise. Operators can override the bundled defaults with a TOML file (`OPENZIM_MCP_PRESETS_OVERRIDE_PATH`).
- **Native libzim introspection** — `zim_health(zim_file_path=...)` validates an archive's integrity (`Archive.check()` + checksum), and `zim_metadata` reports archive identity, full-text / title index capabilities, and an `M/Counter` mimetype breakdown. [API reference →](https://cameronrye.github.io/openzim-mcp/docs/api-reference/)
- **Inbound link discovery ("what links here")** — `zim_links(direction="inbound")` returns pages that link to an entry, ranked by linker importance. Requires a pre-built sidecar: `openzim-mcp build link-graph <archive>.zim` (writes `<archive>.zim.linkgraph.sqlite` next to the archive). [API reference →](https://cameronrye.github.io/openzim-mcp/docs/api-reference/)

## Modes

OpenZIM MCP ships two modes; pick one per client.

**Simple mode** (default) exposes a single intelligent tool, `zim_query`, that parses natural-language requests and dispatches to the right underlying operation. Built for small-model deployment targets — the wire footprint is minimal and the dispatch happens server-side, not in the LLM context. Start here unless you have a specific reason not to.

**Advanced mode** exposes all 8 specialized tools (`zim_query`, `zim_search`, `zim_get`, `zim_get_section`, `zim_browse`, `zim_metadata`, `zim_links`, `zim_health`) plus 3 MCP prompts (`/research`, `/summarize`, `/explore`) and per-entry resources. Built for larger models that can reliably dispatch over the full schema, and for clients that want fine-grained control over pagination, namespace browsing, and link-graph extraction.

Rule of thumb: models ≤ 13B parameters benefit from Simple mode; larger models (Claude Sonnet/Opus, GPT-4o-class, Llama 70B+) can dispatch Advanced mode directly. See [LLM integration patterns](https://cameronrye.github.io/openzim-mcp/docs/llm-integration-patterns/) for guidance on choosing.

## Documentation

Full documentation lives at **<https://cameronrye.github.io/openzim-mcp/docs/>**.

| Group | Pages |
| --- | --- |
| [Get started](https://cameronrye.github.io/openzim-mcp/docs/) | Introduction · Installation · Quick start |
| [Reference](https://cameronrye.github.io/openzim-mcp/docs/api-reference/) | API reference · Configuration · Resources, prompts & subscriptions |
| [Guides](https://cameronrye.github.io/openzim-mcp/docs/llm-integration-patterns/) | LLM integration patterns · Smart retrieval · HTTP & Docker deployment · Performance optimization · Security best practices · Worked examples |
| [Operations](https://cameronrye.github.io/openzim-mcp/docs/troubleshooting/) | Troubleshooting · FAQ · Architecture overview |

## Project status

**v2.5.1** is the current release (2026-06-22); v2.0.0 GA shipped 2026-05-27. Per the published support policy — v1.x fixes accepted "until v2.5.0 ships, whichever comes first" — the v1.x maintenance window closed when v2.5.0 shipped (2026-06-18); all active development is now on the 2.x line. Full release history: [CHANGELOG.md](CHANGELOG.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, test commands, code style, and the release process.

## Security

See [SECURITY.md](SECURITY.md) for the vulnerability disclosure policy. No known CVEs.

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgments

- [openZIM](https://openzim.org/) and [Kiwix](https://www.kiwix.org/) for the ZIM format and libzim library
- [Model Context Protocol](https://modelcontextprotocol.io/) for the open client-server protocol
- The open-source community and contributors

---

Made with ❤️ by [Cameron Rye](https://rye.dev)
