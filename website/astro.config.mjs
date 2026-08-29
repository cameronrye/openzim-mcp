import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';

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

export default defineConfig({
  site: 'https://cameronrye.github.io',
  base: '/openzim-mcp',
  trailingSlash: 'always',
  integrations: [mdx(), sitemap()],
  build: {
    format: 'directory',
  },
  markdown: {
    rehypePlugins: [rehypeScrollableTables],
    shikiConfig: {
      // Dual-theme: light tokens are inline; dark tokens emit CSS vars that
      // styles.css activates under [data-theme="dark"].
      themes: { light: 'github-light', dark: 'github-dark' },
    },
  },
});
