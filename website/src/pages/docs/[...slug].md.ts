import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollection } from 'astro:content';

/**
 * `/docs/<slug>.md` — one page's Markdown source, without the site shell.
 *
 * The HTML route beside this one wraps every page in a sidebar, a table of
 * contents, breadcrumbs, a prev/next footer and three blocks of JSON-LD. That
 * shell is most of the bytes and none of the content, so an agent fetching a
 * doc page to answer a question pays for markup it will discard. `llms.txt`
 * advertises this route so the cheap path is discoverable rather than folklore.
 *
 * The body is the collection entry's own source, so it cannot drift from the
 * rendered page — there is no second copy to keep in step.
 */

export const getStaticPaths: GetStaticPaths = async () => {
  const docs = await getCollection('docs');
  return docs.map((doc) => ({ params: { slug: doc.id }, props: { doc } }));
};

export const GET: APIRoute = ({ props }) => {
  const { doc } = props as { doc: Awaited<ReturnType<typeof getCollection<'docs'>>>[number] };
  const site = 'https://cameronrye.github.io/openzim-mcp';
  const canonical = `${site}/docs/${doc.id === 'index' ? '' : doc.id + '/'}`;

  const body = `# ${doc.data.title}

> ${doc.data.summary}

Source: ${canonical}

---

${doc.body ?? ''}
`;

  return new Response(body, {
    headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
  });
};
