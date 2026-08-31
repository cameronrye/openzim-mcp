import type { CollectionEntry } from 'astro:content';

/**
 * The sidebar's group order, and the single sort every navigation surface uses.
 *
 * `GROUP_ORDER` must list exactly the values of the `group` enum in
 * `src/content.config.ts`, and the two failure modes differ by surface.
 * `Sidebar.astro` and `llms.txt.ts` iterate this list and filter the
 * collection to it, so a page whose group the schema accepts but this list
 * omits is dropped from them entirely. `PrevNext.astro` and `llms-full.txt.ts`
 * order the whole collection through `sortDocsForNav`, where `docsGroupIndex`
 * returns `GROUP_ORDER.length` for an unknown group, so the same page merely
 * sorts to the end. Vanishing from two surfaces while trailing on two others
 * is not something a build error will tell you about, which is why the set
 * equality is checked by `test_sidebar_group_order_covers_the_schema_enum` in
 * `tests/test_docs_freshness.py`. The order of the list is an editorial choice
 * no test makes for you.
 *
 * All four surfaces read from this module, so a change here moves all four.
 */
export const GROUP_ORDER = [
  'Get started',
  'Concepts',
  'Reference',
  'Operate',
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
