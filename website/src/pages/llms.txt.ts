import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { GROUP_ORDER, sortDocsForNav } from '../lib/docs-order';

/**
 * `/llms.txt` — the machine-readable index, generated at build time.
 *
 * This used to be a hand-maintained file in `public/`. It drifted the way
 * every hand-maintained copy in this repo drifts: it was still advertising the
 * v2.0.0 tool consolidation as news on a v3.2.3 release, and its only link
 * section listed six URLs, not one of which was a documentation page — so an
 * agent that fetched it got a decent API summary and no route into the docs.
 *
 * The half that goes stale is now derived. The `## Documentation` index below
 * is built from the same content collection and the same ordering module the
 * sidebar and the prev/next footer use, so a new page appears here the moment
 * it appears in the nav, carrying the `summary` its own frontmatter declares.
 *
 * The half that cannot be derived from the collection — the tool surface, the
 * error contract, the encoding rules — stays written out, because it describes
 * the Python server and Astro cannot reach it. Two Python gates cover that
 * half instead: `test_llms_txt_lists_the_live_tool_surface` in
 * `tests/test_docs_freshness.py` fails if the tool names here stop matching
 * the registered tools, and this file is in the doc corpus the version and
 * schema-footprint gates sweep.
 */

const SITE = 'https://cameronrye.github.io/openzim-mcp';

const VERSION = '3.2.3'; // x-release-please-version

/** The eight advanced-mode tools, in registration order. Gated in Python. */
const TOOLS: Array<[name: string, blurb: string]> = [
  [
    'zim_query',
    'Natural-language entry point, and the only tool simple mode registers. ' +
      'Parses the request, picks the operation, and renders the result. ' +
      '`synthesize=True` runs a multi-archive search/fusion/citation pipeline.',
  ],
  [
    'zim_search',
    'Full-text / title / suggest search. `mode="fulltext" | "title" | "suggest"`; ' +
      '`cross_file=True` fans out serially across archives under an aggregate time budget.',
  ],
  [
    'zim_get',
    'Single / batch / binary / main-page entry fetch. Branches: `entry_path` (single), ' +
      '`entry_paths` (batch), `main_page=True`, `binary=True`, `view="summary" | "toc" | "structure"`. ' +
      'The single-entry branch returns a dict, not rendered markdown.',
  ],
  ['zim_get_section', 'Section-level fetch by section id, with `include_subsections`.'],
  [
    'zim_browse',
    'Namespace listing. `mode="page"` is a sampled overview (limit 1-200); ' +
      '`mode="walk"` is deterministic cursor-paginated iteration (limit 1-500).',
  ],
  ['zim_metadata', 'Archive metadata plus namespace inventory. Metadata keys are capitalised as libzim emits them: `Title`, `Language`, `Creator`, `Publisher`, `Date`, `Flavour`.'],
  [
    'zim_links',
    'Outbound / inbound / related links. `direction="inbound"` ("what links here") needs ' +
      'the sidecar built by `openzim-mcp build link-graph <archive>.zim`; v3.0.0 invalidated 2.x sidecars.',
  ],
  ['zim_health', 'Server health, resolved configuration, and loaded archives in one call. Advanced mode only.'],
];

const PROMPTS: Array<[string, string]> = [
  ['/research <topic>', 'Search across all archives, then drill into top hits'],
  ['/summarize <zim_file_path> <entry_path>', 'TOC + summary + key links'],
  ['/explore <zim_file_path>', 'High-level briefing of one archive'],
];

function docsIndex(docs: Awaited<ReturnType<typeof getCollection<'docs'>>>): string {
  const sorted = sortDocsForNav(docs);
  const lines: string[] = [];
  for (const group of GROUP_ORDER) {
    const inGroup = sorted.filter((d) => d.data.group === group);
    if (inGroup.length === 0) continue;
    lines.push(`### ${group}`, '');
    for (const doc of inGroup) {
      const href = `${SITE}/docs/${doc.id === 'index' ? '' : doc.id + '/'}`;
      lines.push(`- [${doc.data.title}](${href}): ${doc.data.summary}`);
    }
    lines.push('');
  }
  return lines.join('\n').trimEnd();
}

export const GET: APIRoute = async () => {
  const docs = await getCollection('docs');

  const body = `# OpenZIM MCP Server

> Knowledge that works offline. OpenZIM MCP is a Model Context Protocol server that gives any
> AI model structured, secure access to ZIM archives — Wikipedia, Wiktionary, MedlinePlus, the
> Stack Exchange dumps — with no internet connection. Retrieval only: it reads local archives
> and never writes to them.

- Version: ${VERSION}
- License: MIT
- Python: 3.12+
- Repository: https://github.com/cameronrye/openzim-mcp
- Documentation: ${SITE}/
- PyPI: https://pypi.org/project/openzim-mcp/

## Documentation

${docsIndex(docs)}

## Installation

\`\`\`bash
uv tool install openzim-mcp     # isolated CLI install (recommended)
pip install openzim-mcp         # or into the current environment
\`\`\`

Get one real archive to try it against (13.6 MB):

\`\`\`bash
mkdir -p ~/zim-files
curl -fsSL -o ~/zim-files/wikipedia_en_climate_change_mini_2024-06.zim \\
  https://raw.githubusercontent.com/openzim/zim-testing-suite/main/data/withns/wikipedia_en_climate_change_mini_2024-06.zim
\`\`\`

## Quick start

\`\`\`bash
openzim-mcp ~/zim-files                              # simple mode (the default): zim_query only
openzim-mcp --mode advanced ~/zim-files              # all ${TOOLS.length} tools
openzim-mcp --transport http --host 127.0.0.1 --port 8000 ~/zim-files
openzim-mcp --version
\`\`\`

The server takes **directories**, not individual files. The published Docker image sets
\`OPENZIM_MCP_TOOL_MODE=advanced\`, so a container registers the full surface with no flag.

## MCP configuration

\`\`\`json
{
  "mcpServers": {
    "openzim": {
      "command": "uvx",
      "args": ["openzim-mcp@${VERSION}", "/path/to/zim/files"]
    }
  }
}
\`\`\`

## Core concepts

**ZIM format.** An open format for storing web content offline: Zstandard compression, fast
random access, a built-in full-text index, and namespace organisation. An archive is **sealed** —
its content cannot change without replacing the file, which is why responses cache safely.

**Namespaces.** Two schemes are in circulation. New-scheme archives put all content under \`C\`,
metadata under \`M\`, well-known entries under \`W\`, and search indexes under \`X\`. Old-scheme
archives spread content across \`A\` (articles), \`I\` (images) and \`-\` (layout). You cannot tell
which an archive uses without asking it, so prefer search or \`zim_query\` over guessing a path.

**Entry paths** are archive-relative identifiers (\`C/Climate_change\`, \`A/Climate_change\`), never
URLs. Passed as *tool arguments* they are plain UTF-8 — do not URL-encode them. The one exception
is the entry **resource** template, where \`/\` inside \`{path}\` must be percent-encoded as \`%2F\`.

**Smart retrieval.** When an exact entry lookup misses, \`zim_get\` walks a five-step ladder —
encoding variants, namespace probes, \`M/<key>\` routing, alternate-spelling exact probes, then
search — and caches the mapping it finds. No manual retry is needed.

## Available tools

Simple mode (the default) registers **\`zim_query\` alone**; advanced mode registers all ${TOOLS.length}.
There is no health or configuration intent in simple mode — asking \`zim_query\` about server
health searches the *archive* for that phrase.

${TOOLS.map(([name, blurb]) => `- \`${name}\`: ${blurb}`).join('\n')}

## MCP prompts

${PROMPTS.map(([sig, blurb]) => `- \`${sig}\`: ${blurb}`).join('\n')}

## MCP resources

- \`zim://files\`: index of every available ZIM file; each row carries \`readable\`
- \`zim://{name}\`: overview of one archive (metadata, namespaces, main-page preview)
- \`zim://{name}/entry/{path}\`: one entry with its native MIME type. Percent-encode \`/\` in
  \`{path}\` as \`%2F\` — e.g. \`zim://wikipedia_en/entry/C%2FClimate_change\`

## Common use cases

\`\`\`python
# Ask a question without knowing the path
zim_query(query="what caused the French Revolution")

# Search, then read
zim_search(query="quantum physics", zim_file_path="wikipedia_en.zim", limit=10)
zim_get(zim_file_path="wikipedia_en.zim", entry_path="C/Quantum_mechanics")

# Discover neighbours
zim_links(zim_file_path="wikipedia_en.zim", entry_path="C/Quantum_mechanics", direction="related")

# Front page, autocomplete, inventory, deterministic iteration
zim_get(zim_file_path="wikipedia_en.zim", main_page=True)
zim_search(query="artif", zim_file_path="wikipedia_en.zim", mode="suggest")
zim_metadata(zim_file_path="wikipedia_en.zim")
zim_browse(zim_file_path="wikipedia_en.zim", namespace="C", mode="walk", limit=200)
\`\`\`

## Error handling

- Failures are **returned, not raised**: \`{"error": true, "operation": "<op>", "message": "<text>"}\`
- The \`CallToolResult\` also carries \`isError: true\` for these envelopes
- \`context\` appears only when the tool supplies one; some failures merge self-correction keys
  (\`zim_get_section\` adds \`available_section_ids\` and \`closest_match\`; \`unknown_argument\` adds
  \`accepted_arguments\` and \`closest_matches\`)
- There is no \`status\` key and no \`hint\` key — branch on \`result["error"] is True\`
- No tool advertises an \`outputSchema\`, so nothing arrives in \`structuredContent\`; parse the
  JSON text block in \`content\`
- Enum values typed \`Literal\` are rejected by pydantic before the tool body runs, so they come
  back as \`operation="invalid_argument"\` with an \`invalid_arguments\` key. \`zim_browse.mode\` is
  the one enum that answers under its own name, \`invalid_mode\`
- Partial failures do **not** flag the call: a \`zim_get(entry_paths=[...])\` batch or a
  \`zim_search(cross_file=True)\` fan-out where some rows fail still returns \`isError: false\`.
  Batch rows carry \`success\` plus an \`error\` message string; cross-archive rows carry \`error\`
  (bool) plus \`error_message\` / \`error_operation\`

## Configuration

Environment variables, \`OPENZIM_MCP_\` prefixed, \`__\` for nesting:

\`\`\`bash
export OPENZIM_MCP_TOOL_MODE=advanced          # default simple
export OPENZIM_MCP_TRANSPORT=http              # default stdio
export OPENZIM_MCP_AUTH_TOKEN="…"              # non-loopback HTTP refuses to start without it
export OPENZIM_MCP_CACHE__MAX_SIZE=1000        # default 100
export OPENZIM_MCP_CACHE__TTL_SECONDS=14400    # default 3600
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=200000  # default 100000
export OPENZIM_MCP_LOGGING__LEVEL=INFO
\`\`\`

Full reference: ${SITE}/docs/configuration/

## Links

- Documentation: ${SITE}/
- Source: https://github.com/cameronrye/openzim-mcp
- Changelog: https://github.com/cameronrye/openzim-mcp/blob/main/CHANGELOG.md
- PyPI: https://pypi.org/project/openzim-mcp/
- ZIM format specification: https://openzim.org/wiki/ZIM_file_format
- ZIM archive library: https://library.kiwix.org/
- openZIM project: https://openzim.org/
`;

  return new Response(body, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
};
