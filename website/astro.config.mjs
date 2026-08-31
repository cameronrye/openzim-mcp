import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';
import { rehypeHeadingIds } from '@astrojs/markdown-remark';

/**
 * Wrap every `<table>` in a horizontally scrollable container.
 *
 * MDX emits a bare `<table>`, and a wide one (the configuration reference has
 * rows with 54-character env var names) widens its grid track and scrolls the
 * whole page sideways on a phone. CSS alone cannot fix that without giving up
 * `width: 100%`, so the wrapper is added at build time.
 *
 * Hand-rolled rather than pulling in `unist-util-visit` + `hast-util-*`: it is
 * a depth-first walk over a plain tree, and the site's dependency surface is
 * audited on every PR.
 */
function rehypeScrollableTables() {
  return (tree) => {
    const walk = (node) => {
      if (!node || !Array.isArray(node.children)) return;
      for (let i = 0; i < node.children.length; i++) {
        const child = node.children[i];
        if (child.type === 'element' && child.tagName === 'table') {
          node.children[i] = {
            type: 'element',
            tagName: 'div',
            properties: { className: ['docs-table-scroll'], tabIndex: 0, role: 'region' },
            children: [child],
          };
          continue; // the table itself contains no nested tables worth wrapping
        }
        walk(child);
      }
    };
    walk(tree);
  };
}

/**
 * Add a clickable anchor to every h2-h4 in the docs.
 *
 * Two things make this less obvious than it looks.
 *
 * Astro applies `rehypeHeadingIds` AFTER the user's `rehypePlugins`, so at the
 * point this runs no heading has an id yet — a plugin reading
 * `node.properties.id` finds nothing on all 414 content headings and silently
 * adds no anchors at all. `rehypeHeadingIds` is idempotent (it assigns an id
 * only when one is missing), so it is re-run as the first entry below and
 * Astro's own later pass leaves the ids alone. Importing it costs no new
 * dependency: `@astrojs/markdown-remark` is already installed, hoisted as an
 * exact dependency of `@astrojs/mdx` and the sole peer of `astro`.
 *
 * And the anchor's visible text is indexed. Without `data-pagefind-ignore`
 * every page fragment picks up tokens like "Resources#" and "validation#".
 *
 * The page `<h1>` comes from DocsLayout rather than the markdown pipeline, so
 * it never reaches this plugin — matching the table of contents, which also
 * starts at depth 2.
 */
function rehypeHeadingAnchors() {
  const wanted = new Set(['h2', 'h3', 'h4']);
  return (tree) => {
    const walk = (node) => {
      if (!node || !Array.isArray(node.children)) return;
      for (const child of node.children) {
        if (
          child.type === 'element' &&
          wanted.has(child.tagName) &&
          typeof child.properties?.id === 'string'
        ) {
          child.properties.className = [
            ...(child.properties.className ?? []),
            'heading-linked',
          ];
          child.children.push({
            type: 'element',
            tagName: 'a',
            properties: {
              className: ['heading-anchor'],
              href: `#${child.properties.id}`,
              'aria-label': 'Link to this section',
              'data-pagefind-ignore': true,
            },
            children: [{ type: 'text', value: '#' }],
          });
          continue;
        }
        walk(child);
      }
    };
    walk(tree);
  };
}

export default defineConfig({
  site: 'https://cameronrye.github.io',
  base: '/openzim-mcp',
  trailingSlash: 'always',
  integrations: [mdx(), sitemap()],
  build: {
    format: 'directory',
  },
  markdown: {
    rehypePlugins: [rehypeHeadingIds, rehypeScrollableTables, rehypeHeadingAnchors],
    shikiConfig: {
      // Dual-theme: light tokens are inline; dark tokens emit CSS vars that
      // styles.css activates under [data-theme="dark"].
      themes: { light: 'github-light', dark: 'github-dark' },
    },
  },
});
