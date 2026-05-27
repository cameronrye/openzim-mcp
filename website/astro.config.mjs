import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://cameronrye.github.io',
  base: '/openzim-mcp',
  trailingSlash: 'always',
  integrations: [mdx(), sitemap()],
  build: {
    format: 'directory',
  },
  markdown: {
    shikiConfig: {
      // Dual-theme: light tokens are inline; dark tokens emit CSS vars that
      // styles.css activates under [data-theme="dark"].
      themes: { light: 'github-light', dark: 'github-dark' },
    },
  },
});
