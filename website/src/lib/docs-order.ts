import type { CollectionEntry } from 'astro:content';

/**
 * The sidebar's group order, and the single sort every navigation surface uses.
 *
 * This lives in its own module because two components need the same answer and
 * had drifted apart: `Sidebar.astro` bucketed pages by group and rendered the
 * buckets in a fixed order, while `PrevNext.astro` sorted the whole collection
 * by `sidebar_order` alone. `sidebar_order` restarts at 1 in every group, so
 * the footer chain interleaved groups — "Quick start" was followed by "API
 * reference" in the sidebar but by whichever other page also happened to carry
 * `sidebar_order: 1`.
 *
 * Keep `GROUP_ORDER` in step with the `group` enum in `src/content.config.ts`:
 * a value in the schema but missing here is silently dropped from the sidebar,
 * and `docsOrderIndex` sorts it to the end.
 */
export const GROUP_ORDER = [
  'Get started',
  'Reference',
  'Guides',
  'Operations',
] as const;

export type DocGroup = (typeof GROUP_ORDER)[number];

type DocEntry = CollectionEntry<'docs'>;

/** Position of a doc's group in the sidebar; unknown groups sort last. */
export function docsGroupIndex(group: string): number {
  const i = (GROUP_ORDER as readonly string[]).indexOf(group);
  return i === -1 ? GROUP_ORDER.length : i;
}

/**
 * Reading order across the whole site: group first, then `sidebar_order`
 * within the group. This is the order the sidebar displays, so it is also the
 * order prev/next must walk.
 */
export function sortDocsForNav(docs: DocEntry[]): DocEntry[] {
  return [...docs].sort((a, b) => {
    const byGroup = docsGroupIndex(a.data.group) - docsGroupIndex(b.data.group);
    return byGroup !== 0 ? byGroup : a.data.sidebar_order - b.data.sidebar_order;
  });
}
