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

---

> 🆕 **v2.0.0 — 8-tool advanced surface.** Phase F consolidates 22 advanced tools into 8 (`zim_query`, `zim_search`, `zim_get`, `zim_get_section`, `zim_browse`, `zim_metadata`, `zim_links`, `zim_health`). [Full release notes →](CHANGELOG.md#200--2026-05-27--phase-f-stage-d-ships) [Docs →](https://cameronrye.github.io/openzim-mcp/docs/)

**OpenZIM MCP** is a modern, secure, high-performance [Model Context Protocol](https://modelcontextprotocol.io/) server that gives AI models structured, offline access to [ZIM format](https://en.wikipedia.org/wiki/ZIM_(file_format)) knowledge archives — Wikipedia, Wiktionary, Stack Exchange, and the rest of the [Kiwix Library](https://library.kiwix.org/).

Built for research assistants, knowledge chatbots, and content-analysis systems that need *intelligent* access to vast knowledge repositories — not just a raw text dump. Smart navigation by namespace (articles, metadata, media), structure-aware retrieval (sections, tables of contents, related articles), full-text search with suggestions and multi-archive `search_all`, and link-graph extraction to map content relationships. Cached, paginated operations keep things responsive across massive archives; comprehensive input validation and path-traversal protection keep things safe.

Streamable HTTP transport, per-entry MCP resources with subscriptions, and dual Simple / Advanced modes ship in v2.0.0.

## Install

```bash
# uv (recommended — isolated CLI tool)
uv tool install openzim-mcp

# pip
pip install openzim-mcp

# Docker (multi-arch image, ghcr.io)
docker pull ghcr.io/cameronrye/openzim-mcp:2.0.0
docker run --rm -v /path/to/zim/files:/zim ghcr.io/cameronrye/openzim-mcp:2.0.0 /zim
```

Verify the install:

```bash
openzim-mcp --help
```

Download ZIM files from the [Kiwix Library](https://library.kiwix.org/) into a directory of your choice before running the server.

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

## What's in v2.0.0

- **8-tool advanced surface** — `zim_query`, `zim_search`, `zim_get`, `zim_get_section`, `zim_browse`, `zim_metadata`, `zim_links`, `zim_health`. Down from 22; advanced-mode schema drops from ~36KB to ~23.5KB, clearing the [MCP Tax](https://www.mmntm.net/articles/mcp-context-tax) pain band. [API reference →](https://cameronrye.github.io/openzim-mcp/docs/api-reference/)
- **Streamable HTTP transport** — bearer-token auth, CORS, health endpoints, multi-arch Docker image. [HTTP & Docker deployment →](https://cameronrye.github.io/openzim-mcp/docs/http-and-docker-deployment/)
- **Per-entry MCP resources + subscriptions** — `zim://{name}/entry/{path}` with native MIME types; clients subscribe and receive `notifications/resources/updated` when archives change. [Resources, prompts & subscriptions →](https://cameronrye.github.io/openzim-mcp/docs/resources-prompts-subscriptions/)
- **Simple-mode `zim_query`** — one natural-language tool that dispatches to the right operation, tuned for small-model deployment targets. [Quick start →](https://cameronrye.github.io/openzim-mcp/docs/quick-start/)

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

v2.0.0 GA shipped 2026-05-27. v1.x is in maintenance mode — security fixes, data-corruption fixes, and pre-v2.0.0 crash fixes accepted through 2026-11-27 or until v2.5.0 ships, whichever comes first. Full release history: [CHANGELOG.md](CHANGELOG.md).

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
