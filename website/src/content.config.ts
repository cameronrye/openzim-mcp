import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const docs = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/docs' }),
  schema: z.object({
    title: z.string(),
    summary: z.string(),
    group: z.enum(['Get started', 'Reference', 'Guides', 'Operations']),
    sidebar_order: z.number(),
  }),
});

export const collections = { docs };
