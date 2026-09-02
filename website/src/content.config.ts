import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
// `z` from `astro:content` is deprecated; `astro/zod` is the documented
// replacement. It re-exports Zod from the already-declared `astro` package, so
// there is nothing new to install — importing from `zod` directly would have
// meant relying on a hoisted transitive, which is what broke every npm
// Dependabot PR until `@astrojs/markdown-remark` was declared in #409.
import { z } from 'astro/zod';

const docs = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/docs' }),
  schema: z.object({
    title: z.string(),
    summary: z.string(),
    group: z.enum(['Get started', 'Concepts', 'Reference', 'Operate']),
    sidebar_order: z.number(),
  }),
});

export const collections = { docs };
