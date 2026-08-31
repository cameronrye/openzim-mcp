import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { sortDocsForNav } from '../lib/docs-order';
import { VERSION } from './llms.txt';

/**
 * `/llms-full.txt` — the whole documentation corpus as one plain-text file.
 *
 * `llms.txt` is an index: it links out. This is the other half of the
 * convention — every page's Markdown inline, in reading order, so an agent can
 * take the corpus in a single fetch instead of nineteen.
 *
 * Both are generated from the same content collection and the same ordering
 * module the sidebar uses, so neither can fall behind a page that was added,
 * renamed, or moved between groups.
 *
 * `VERSION` is imported rather than restated: it carries the
 * `x-release-please-version` marker in `llms.txt.ts`, which is the file
 * registered in `release-please-config.json`. A second stamped literal here
 * would be a second thing to keep in step, which is the failure this whole
 * sweep has been about.
 */

const SITE = 'https://cameronrye.github.io/openzim-mcp';

export const GET: APIRoute = async () => {
  const docs = sortDocsForNav(await getCollection('docs'));

  const pages = docs
    .map((doc) => {
      const canonical = `${SITE}/docs/${doc.id === 'index' ? '' : doc.id + '/'}`;
      return `${'='.repeat(78)}
# ${doc.data.title}

> ${doc.data.summary}

Group: ${doc.data.group}
Source: ${canonical}
Markdown: ${SITE}/docs/${doc.id}.md

${doc.body ?? ''}`;
    })
    .join('\n\n');

  const body = `# OpenZIM MCP Server — full documentation

> Knowledge that works offline. OpenZIM MCP is a Model Context Protocol server that gives any
> AI model structured, secure access to ZIM archives — Wikipedia, Wiktionary, MedlinePlus, the
> Stack Exchange dumps — with no internet connection.

Version: ${VERSION}
Documentation: ${SITE}/
Index (links only): ${SITE}/llms.txt
Source: https://github.com/cameronrye/openzim-mcp

This file contains every documentation page in reading order. Each page is also available on its
own at ${SITE}/docs/<slug>.md.

${pages}
`;

  return new Response(body, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
};
