# Docs Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the README ⟷ Wiki ⟷ marketing-page tri-source with a single canonical Astro site at gh-pages, slim the README to a project card (~250 lines), refresh the bespoke landing page for v2.0.0, and retire the GitHub Wiki via redirect stubs.

**Architecture:** One Astro project lives in the existing `website/` folder. The bespoke landing page becomes `src/pages/index.astro` (verbatim port + v1→v2 content refresh). A dynamic `[...slug].astro` route renders MDX from `src/content/docs/` with a hand-rolled `DocsLayout.astro` (sidebar + TOC + breadcrumbs + prev/next). One GitHub Actions workflow runs `npm run build` and deploys `dist/` to the `gh-pages` branch via `peaceiris/actions-gh-pages`. The wiki repo's pages are rewritten as redirect stubs; the wiki feature is left enabled for ~30 days then disabled in a follow-up chore.

**Tech Stack:** Astro 4.x, `@astrojs/mdx`, `@astrojs/sitemap`, shiki (code highlighting, ships with Astro), TypeScript (Astro config + content-collection schema), GitHub Actions, `peaceiris/actions-gh-pages@v4`, `lychee` (linkcheck), Node 20+, `npm`.

**Spec:** See [`docs/specs/2026-05-27-docs-consolidation-design.md`](../specs/2026-05-27-docs-consolidation-design.md) for the upstream design rationale, the per-page refresh effort audit, and the explicit non-goals.

---

## File Structure

**Created in PR 1:**

```
website/package.json                  # Astro deps
website/package-lock.json             # locked deps
website/astro.config.mjs              # site + integrations config
website/tsconfig.json                 # extends astro/tsconfigs/strict
website/src/pages/index.astro         # ported landing
website/src/pages/docs/[...slug].astro # docs route
website/src/content/config.ts         # Zod schema for docs collection
website/src/content/docs/index.mdx    # placeholder Introduction (real content in PR 2)
website/src/layouts/LandingLayout.astro
website/src/layouts/DocsLayout.astro  # sidebar + TOC + breadcrumbs + prev/next
website/src/components/ThemeToggle.astro
website/src/components/Sidebar.astro
website/src/components/TableOfContents.astro
website/src/components/Breadcrumbs.astro
website/src/components/PrevNext.astro
website/src/styles/global.css         # ported from website/assets/*.css
website/public/robots.txt             # moved from website/
website/public/humans.txt             # moved + version bumped
website/public/llms.txt               # moved verbatim
website/public/.well-known/...        # moved verbatim
website/public/assets/...             # moved verbatim
.github/workflows/site.yml            # build + deploy
```

**Deleted in PR 1:**

```
website/index.html                    # superseded by src/pages/index.astro
website/sitemap.xml                   # @astrojs/sitemap regenerates
website/validate.py                   # replaced by `astro check`
website/assets/                       # contents relocated to public/assets/
website/.well-known/                  # contents relocated to public/.well-known/
website/robots.txt                    # relocated to public/
website/humans.txt                    # relocated to public/
website/llms.txt                      # relocated to public/
```

**Created in PR 2:**

```
website/src/content/docs/introduction.mdx
website/src/content/docs/installation.mdx
website/src/content/docs/quick-start.mdx
website/src/content/docs/api-reference.mdx
website/src/content/docs/configuration.mdx
website/src/content/docs/resources-prompts-subscriptions.mdx
website/src/content/docs/llm-integration-patterns.mdx
website/src/content/docs/smart-retrieval.mdx
website/src/content/docs/http-and-docker-deployment.mdx
website/src/content/docs/performance-optimization.mdx
website/src/content/docs/security-best-practices.mdx
website/src/content/docs/worked-examples.mdx
website/src/content/docs/troubleshooting.mdx
website/src/content/docs/faq.mdx
website/src/content/docs/architecture-overview.mdx
```

**Deleted in PR 2:**

```
docs/deployment.md                    # merged into http-and-docker-deployment.mdx
website/src/content/docs/index.mdx    # placeholder; replaced by introduction.mdx
```

**Modified in PR 2:**

```
README.md                             # update all wiki links → /docs/<slug>/
CONTRIBUTING.md                       # append "Release process" section
SECURITY.md                           # update any wiki links
website/public/llms.txt               # update any wiki links → /docs/<slug>/
```

**Modified in PR 3:**

```
README.md                             # 1,806 → ~250 lines, project-card shape
CONTRIBUTING.md                       # append Development + Testing sections
```

**Modified externally in PR 4 (separate wiki repo, not this repo):**

```
<wiki>/Home.md                        → redirect stub
<wiki>/Installation-Guide.md          → redirect stub
<wiki>/Quick-Start-Tutorial.md        → redirect stub
<wiki>/API-Reference.md               → redirect stub
<wiki>/Configuration-Guide.md         → redirect stub
<wiki>/Resources-Prompts-Subscriptions.md → redirect stub
<wiki>/LLM-Integration-Patterns.md    → redirect stub
<wiki>/Smart-Retrieval-System-Guide.md → redirect stub
<wiki>/HTTP-and-Docker-Deployment.md  → redirect stub
<wiki>/Performance-Optimization-Guide.md → redirect stub
<wiki>/Security-Best-Practices.md     → redirect stub
<wiki>/Troubleshooting-Guide.md       → redirect stub
<wiki>/FAQ.md                         → redirect stub
<wiki>/Architecture-Overview.md       → redirect stub
<wiki>/Release-System-Guide.md        → redirect stub (to CONTRIBUTING anchor)
```

---

## Pre-flight

### Task 0: Preserve gh-pages rollback target

**Files:** None (git operation on remote).

- [ ] **Step 1: Tag the current `gh-pages` HEAD on origin so PR 1 can be rolled back in <60s if the deploy goes wrong.**

```bash
git fetch origin gh-pages
git tag -a gh-pages-pre-astro origin/gh-pages -m "Pre-Astro gh-pages HEAD; rollback target for PR 1"
git push origin gh-pages-pre-astro
```

- [ ] **Step 2: Verify the tag exists on origin.**

```bash
git ls-remote --tags origin gh-pages-pre-astro
```

Expected: one line ending in `refs/tags/gh-pages-pre-astro`. If missing, repeat Step 1 — PR 1 must not merge until this tag exists.

---

## Phase 1 — PR 1: Astro scaffold + landing port + CI deploy

**Branch:** `docs/astro-scaffold` (off `main`).
**PR title:** `docs: Astro scaffold + landing v1→v2 refresh + gh-pages workflow`.
**Exit gate:** `https://cameronrye.github.io/openzim-mcp/` loads with refreshed landing; `/docs/` renders the placeholder; `/llms.txt`, `/.well-known/*`, `/robots.txt` still resolve at same URLs; `npm run build` and `astro check` clean.

### Task 1.1: Create the branch and initialize the Astro project

**Files:** `website/package.json`, `website/astro.config.mjs`, `website/tsconfig.json`, `.gitignore`.

- [ ] **Step 1: Branch off main.**

```bash
git checkout main && git pull --ff-only
git checkout -b docs/astro-scaffold
```

- [ ] **Step 2: Initialize Astro in `website/`. Use non-interactive flags so no prompts block.**

```bash
cd website
npm create astro@latest . -- --template minimal --no-install --no-git --skip-houston --typescript strict
```

Expected: creates `package.json`, `astro.config.mjs`, `tsconfig.json`, `src/pages/index.astro` (Astro's stub). The existing `index.html`, `assets/`, `robots.txt`, etc. remain untouched (in this folder root) — they will be relocated in Task 1.3.

- [ ] **Step 3: Install dependencies and add MDX + sitemap integrations.**

```bash
cd website
npm install
npm install @astrojs/mdx @astrojs/sitemap
```

- [ ] **Step 4: Replace `astro.config.mjs` with the project's configuration.**

```js
// website/astro.config.mjs
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
});
```

- [ ] **Step 5: Append Astro build artifacts to `.gitignore`.**

Edit the repo-root `.gitignore` and append:

```
# Astro (website/)
website/node_modules/
website/dist/
website/.astro/
```

- [ ] **Step 6: Verify the install + config compile.**

```bash
cd website && npx astro check && cd ..
```

Expected: `0 errors, 0 warnings`. If errors mention missing `@astrojs/check`, run `cd website && npm install @astrojs/check typescript --save-dev && npx astro check`.

- [ ] **Step 7: Commit the scaffold.**

```bash
git add website/package.json website/package-lock.json website/astro.config.mjs website/tsconfig.json .gitignore
git commit -m "docs(site): scaffold Astro project under website/

Adds package.json, astro.config.mjs with mdx+sitemap integrations,
tsconfig (strict), and .gitignore entries for node_modules/dist/.astro."
```

### Task 1.2: Relocate static assets into `public/`

**Files:** moves only — `website/{robots.txt,humans.txt,llms.txt,.well-known/,assets/}` → `website/public/`.

- [ ] **Step 1: Create `public/` and move files preserving git history.**

```bash
cd website
mkdir -p public
git mv robots.txt public/robots.txt
git mv humans.txt public/humans.txt
git mv llms.txt public/llms.txt
git mv .well-known public/.well-known
git mv assets public/assets
cd ..
```

- [ ] **Step 2: Bump `humans.txt` version line to 2.0.0.**

Read `website/public/humans.txt` to find the current version line (e.g., `Last update: ...` or a `Version:` line). Update both to 2026-05-27 and 2.0.0.

- [ ] **Step 3: Delete the hand-edited sitemap and validator (replaced by Astro's sitemap integration and `astro check`).**

```bash
cd website
git rm sitemap.xml validate.py
cd ..
```

- [ ] **Step 4: Verify `npm run build` succeeds and `dist/llms.txt`, `dist/robots.txt`, `dist/.well-known/` exist.**

```bash
cd website && npm run build && \
  test -f dist/llms.txt && test -f dist/robots.txt && test -d dist/.well-known && \
  echo "OK" && cd ..
```

Expected: `OK`. If files missing, re-check `public/` paths.

- [ ] **Step 5: Commit.**

```bash
git add -A website/
git commit -m "docs(site): move robots/humans/llms/.well-known/assets into public/

Bumps humans.txt to v2.0.0. Deletes hand-edited sitemap.xml (Astro
regenerates) and validate.py (replaced by astro check)."
```

### Task 1.3: Port `index.html` into `src/pages/index.astro` (verbatim shell)

**Files:** `website/src/pages/index.astro`, `website/src/layouts/LandingLayout.astro`, `website/src/styles/global.css`.

The goal of this task is a verbatim visual port — same HTML, same CSS, no v1→v2 content changes yet. Content refresh happens in Task 1.5.

- [ ] **Step 1: Read the existing `website/index.html` end-to-end. Note the inline `<style>` block (if any), inline `<script>` blocks, and the structure: `<header class="nav">`, `<main>`, `<footer>`.**

- [ ] **Step 2: Create `src/layouts/LandingLayout.astro` containing the `<!doctype html>`, `<head>` (meta, OG, JSON-LD), and `<body>` shell with `<slot />` where `<main>` sits.**

```astro
---
// website/src/layouts/LandingLayout.astro
export interface Props {
  title: string;
  description: string;
}
const { title, description } = Astro.props;
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <meta name="description" content={description} />
    <link rel="stylesheet" href={`${import.meta.env.BASE_URL}/assets/styles.css`} />
    <!-- copy OG, Twitter, JSON-LD breadcrumb, favicon link tags from index.html verbatim here -->
  </head>
  <body>
    <slot />
  </body>
</html>
```

- [ ] **Step 3: Create `src/pages/index.astro` that wraps the existing `<header>`, `<main>`, `<footer>` markup in `<LandingLayout>`.**

```astro
---
// website/src/pages/index.astro
import LandingLayout from '../layouts/LandingLayout.astro';
---
<LandingLayout title="OpenZIM MCP — Knowledge that works offline" description="OpenZIM MCP gives AI models structured, secure access to ZIM archives — Wikipedia, MedlinePlus, Stack Exchange dumps — offline.">
  <!-- Paste <header class="nav">…</header> from index.html here -->
  <!-- Paste <main id="main">…</main> from index.html here -->
  <!-- Paste <footer class="footer">…</footer> from index.html here -->
</LandingLayout>
```

The actual content is copy-pasted from `index.html` lines 140–700 (approximately). Preserve every attribute, every SVG, every inline `<script>`.

- [ ] **Step 4: Move the inline `<style>` block (if any) from `index.html` to `src/styles/global.css`. Reference it from `LandingLayout.astro` via the `<link rel="stylesheet" href="...">` above OR via an Astro `<style is:global>` block in the layout.**

If `index.html` references `assets/styles.css` (or similar) by `<link>` already, no action needed — the file is already in `public/assets/`.

- [ ] **Step 5: Move inline `<script>` blocks from `index.html` to the bottom of `index.astro`, preserving them as `<script is:inline>` so Astro doesn't try to bundle/optimize them (they reference DOM IDs from the markup above).**

- [ ] **Step 6: Delete `website/index.html` (verbatim content now lives in `index.astro`).**

```bash
cd website && git rm index.html && cd ..
```

- [ ] **Step 7: Run the dev server and verify the landing renders identically to the old static page.**

```bash
cd website && npm run dev
```

Open `http://localhost:4321/openzim-mcp/`. Compare visually against the production site at `https://cameronrye.github.io/openzim-mcp/` (or a fresh `git stash && git checkout main` + open `website/index.html` directly). They should be pixel-for-pixel identical except the URL.

- [ ] **Step 8: Verify the production build matches.**

```bash
cd website && npm run build && \
  test -f dist/index.html && \
  grep -q 'class="nav"' dist/index.html && \
  grep -q 'id="hero"' dist/index.html && \
  echo "OK" && cd ..
```

Expected: `OK`.

- [ ] **Step 9: Commit.**

```bash
git add -A website/
git commit -m "docs(site): port index.html to src/pages/index.astro

Verbatim shell port: HTML structure, CSS, inline JS preserved. v1→v2
content refresh happens in the next commit. Deletes website/index.html
(superseded by the .astro page)."
```

### Task 1.4: Build the docs route + placeholder Introduction

**Files:** `website/src/content/config.ts`, `website/src/content/docs/index.mdx`, `website/src/pages/docs/[...slug].astro`, `website/src/layouts/DocsLayout.astro`, `website/src/components/{Sidebar,TableOfContents,Breadcrumbs,PrevNext}.astro`.

This builds the docs scaffolding with ONE placeholder page so URLs resolve immediately. Real content lands in PR 2.

- [ ] **Step 1: Create the content collection schema.**

```ts
// website/src/content/config.ts
import { defineCollection, z } from 'astro:content';

const docs = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    summary: z.string(),
    group: z.enum(['Get started', 'Reference', 'Guides', 'Operations']),
    sidebar_order: z.number(),
  }),
});

export const collections = { docs };
```

- [ ] **Step 2: Create the placeholder Introduction page.**

```mdx
---
title: Documentation
summary: OpenZIM MCP documentation — migration in progress.
group: Get started
sidebar_order: 1
---

# Documentation

Full documentation is migrating here from the GitHub wiki — coming in PR 2.

In the meantime, see:

- The [README](https://github.com/cameronrye/openzim-mcp#readme) for install + quick start.
- The [CHANGELOG](https://github.com/cameronrye/openzim-mcp/blob/main/CHANGELOG.md) for v1 → v2 migration notes.
```

Save as `website/src/content/docs/index.mdx`.

- [ ] **Step 3: Create the four sub-components.**

```astro
---
// website/src/components/Sidebar.astro
import { getCollection } from 'astro:content';

const allDocs = await getCollection('docs');
const groups: Record<string, typeof allDocs> = {};
for (const doc of allDocs.sort((a, b) => a.data.sidebar_order - b.data.sidebar_order)) {
  (groups[doc.data.group] ??= []).push(doc);
}
const orderedGroups = ['Get started', 'Reference', 'Guides', 'Operations'];
const { currentSlug } = Astro.props;
---
<nav class="docs-sidebar" aria-label="Documentation">
  {orderedGroups.map((g) =>
    groups[g] && (
      <section>
        <h3>{g}</h3>
        <ul>
          {groups[g].map((d) => (
            <li>
              <a
                href={`${import.meta.env.BASE_URL}/docs/${d.slug === 'index' ? '' : d.slug + '/'}`}
                aria-current={d.slug === currentSlug ? 'page' : undefined}
              >{d.data.title}</a>
            </li>
          ))}
        </ul>
      </section>
    )
  )}
</nav>
```

```astro
---
// website/src/components/Breadcrumbs.astro
const { group, title } = Astro.props;
---
<nav class="docs-breadcrumbs" aria-label="Breadcrumb">
  <a href={`${import.meta.env.BASE_URL}/`}>OpenZIM MCP</a> ›
  <a href={`${import.meta.env.BASE_URL}/docs/`}>Docs</a> ›
  <span>{group}</span> ›
  <span aria-current="page">{title}</span>
</nav>
```

```astro
---
// website/src/components/TableOfContents.astro
const { headings } = Astro.props; // from MDX render output
---
<aside class="docs-toc" aria-label="On this page">
  <h4>On this page</h4>
  <ul>
    {headings.filter((h) => h.depth >= 2 && h.depth <= 3).map((h) => (
      <li class={`toc-h${h.depth}`}>
        <a href={`#${h.slug}`}>{h.text}</a>
      </li>
    ))}
  </ul>
</aside>
```

```astro
---
// website/src/components/PrevNext.astro
import { getCollection } from 'astro:content';

const allDocs = (await getCollection('docs')).sort(
  (a, b) => a.data.sidebar_order - b.data.sidebar_order,
);
const { currentSlug } = Astro.props;
const idx = allDocs.findIndex((d) => d.slug === currentSlug);
const prev = idx > 0 ? allDocs[idx - 1] : null;
const next = idx < allDocs.length - 1 ? allDocs[idx + 1] : null;
---
<nav class="docs-prevnext" aria-label="Page navigation">
  {prev && <a class="prev" href={`${import.meta.env.BASE_URL}/docs/${prev.slug === 'index' ? '' : prev.slug + '/'}`}>← {prev.data.title}</a>}
  {next && <a class="next" href={`${import.meta.env.BASE_URL}/docs/${next.slug === 'index' ? '' : next.slug + '/'}`}>{next.data.title} →</a>}
</nav>
```

- [ ] **Step 4: Create the docs layout that composes the components.**

```astro
---
// website/src/layouts/DocsLayout.astro
import Sidebar from '../components/Sidebar.astro';
import Breadcrumbs from '../components/Breadcrumbs.astro';
import TableOfContents from '../components/TableOfContents.astro';
import PrevNext from '../components/PrevNext.astro';

export interface Props {
  title: string;
  description: string;
  group: string;
  slug: string;
  headings: Array<{ depth: number; slug: string; text: string }>;
}
const { title, description, group, slug, headings } = Astro.props;
const repoEditUrl = `https://github.com/cameronrye/openzim-mcp/blob/main/website/src/content/docs/${slug === 'index' ? 'index' : slug}.mdx`;
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title} — OpenZIM MCP docs</title>
    <meta name="description" content={description} />
    <link rel="stylesheet" href={`${import.meta.env.BASE_URL}/assets/styles.css`} />
  </head>
  <body>
    <div class="docs-shell">
      <Sidebar currentSlug={slug} />
      <main class="docs-main">
        <Breadcrumbs group={group} title={title} />
        <article><slot /></article>
        <PrevNext currentSlug={slug} />
        <p><a href={repoEditUrl}>Edit this page on GitHub →</a></p>
      </main>
      <TableOfContents headings={headings} />
    </div>
  </body>
</html>
```

- [ ] **Step 5: Create the dynamic docs route.**

```astro
---
// website/src/pages/docs/[...slug].astro
import { getCollection } from 'astro:content';
import DocsLayout from '../../layouts/DocsLayout.astro';

export async function getStaticPaths() {
  const docs = await getCollection('docs');
  return docs.map((doc) => ({
    params: { slug: doc.slug === 'index' ? undefined : doc.slug },
    props: { doc },
  }));
}

const { doc } = Astro.props;
const { Content, headings } = await doc.render();
---
<DocsLayout
  title={doc.data.title}
  description={doc.data.summary}
  group={doc.data.group}
  slug={doc.slug}
  headings={headings}
>
  <Content />
</DocsLayout>
```

- [ ] **Step 6: Append minimal docs CSS to `website/public/assets/styles.css` so the docs shell isn't unstyled.**

Append the following rules (keep them scoped — do not modify any landing-page rules):

```css
.docs-shell { display: grid; grid-template-columns: 240px 1fr 200px; gap: 2rem; max-width: 1200px; margin: 0 auto; padding: 2rem 1rem; }
.docs-sidebar { font-size: 0.9rem; }
.docs-sidebar h3 { margin-top: 1.5rem; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; }
.docs-sidebar ul { list-style: none; padding-left: 0; }
.docs-sidebar a[aria-current="page"] { font-weight: 600; }
.docs-toc { font-size: 0.85rem; position: sticky; top: 2rem; align-self: start; }
.docs-toc .toc-h3 { padding-left: 1rem; }
.docs-breadcrumbs { font-size: 0.85rem; opacity: 0.7; margin-bottom: 1rem; }
.docs-prevnext { display: flex; justify-content: space-between; margin-top: 3rem; padding-top: 1rem; border-top: 1px solid currentColor; }
@media (max-width: 900px) { .docs-shell { grid-template-columns: 1fr; } .docs-toc { display: none; } }
```

- [ ] **Step 7: Verify the docs route renders.**

```bash
cd website && npm run build && \
  test -f dist/docs/index.html && \
  grep -q 'Documentation' dist/docs/index.html && \
  echo "OK" && cd ..
```

Expected: `OK`.

- [ ] **Step 8: Commit.**

```bash
git add -A website/
git commit -m "docs(site): add docs collection scaffolding + placeholder Introduction

Hand-rolled DocsLayout with sidebar/TOC/breadcrumbs/prev-next
components (no Starlight, per spec). Content collection schema
(zod) enforces group + sidebar_order. Real wiki content migrates
in PR 2."
```

### Task 1.5: Refresh the landing page from v1 to v2

**Files:** `website/src/pages/index.astro` only.

Now apply the v1→v2 content changes called out in the spec.

- [ ] **Step 1: Update the primary nav.**

Find `<a href="#v1" class="nav__link">v1.0</a>` (currently around index.html line 164) and change to:

```html
<a href="#v2" class="nav__link">v2.0</a>
```

Find the "Docs" nav slot. If there is no docs link in the nav, add one between "What" and "Try":

```html
<a href="/openzim-mcp/docs/" class="nav__link">Docs</a>
```

- [ ] **Step 2: Update the Schema.org BreadcrumbList JSON-LD.**

In the `<head>` (was around index.html line 110), change the third ListItem from `"name": "v1.0", "item": "https://cameronrye.github.io/openzim-mcp/#v1"` to:

```json
{ "@type": "ListItem", "position": 3, "name": "v2.0", "item": "https://cameronrye.github.io/openzim-mcp/#v2" }
```

- [ ] **Step 3: Rebuild the `<section id="v1">` block as a v2.0 release section.**

Delete the entire `<section id="v1" class="section v1" data-reveal>…</section>` block (was index.html lines 319–428, ~110 lines, four v1 feature cards). Replace it with a new `<section id="v2" class="section v2" data-reveal>` containing three headline cards:

```html
<section id="v2" class="section v2" data-reveal>
  <div class="container">
    <span class="v2__watermark" aria-hidden="true">2.0</span>
    <header class="section__header">
      <span class="eyebrow">The 2.0 release</span>
      <h2>Eight tools. Same surface area.</h2>
      <p>v2.0.0 collapses the 22-tool advanced mode into 8 consolidated tools — schema text drops from ~36KB to ~23.5KB, clearing the <a href="https://www.mmntm.net/articles/mcp-context-tax">MCP Tax</a> pain band for small-model dispatch.</p>
    </header>

    <ul class="v2__cards">
      <li class="v2__card">
        <span class="v2__card-dot" aria-hidden="true"></span>
        <h3>8-tool advanced surface</h3>
        <p><code>zim_query</code>, <code>zim_search</code>, <code>zim_get</code>, <code>zim_get_section</code>, <code>zim_browse</code>, <code>zim_metadata</code>, <code>zim_links</code>, <code>zim_health</code>. Every v1 operation still reachable via a mode parameter.</p>
        <pre><code>{
  "name": "zim_search",
  "arguments": {
    "zim_file_path": "wiki.zim",
    "query": "evolution",
    "mode": "fulltext"
  }
}</code></pre>
      </li>

      <li class="v2__card">
        <span class="v2__card-dot" aria-hidden="true"></span>
        <h3>Simple mode unchanged</h3>
        <p>The natural-language <code>zim_query</code> tool is identical to v1.2.0. Small-model clients see one tool; large-model clients can opt into the 8-tool surface with <code>--mode advanced</code>.</p>
        <pre><code>openzim-mcp /data/zim/
# simple mode (default): one tool

openzim-mcp --mode advanced /data/zim/
# advanced mode: 8 tools</code></pre>
      </li>

      <li class="v2__card">
        <span class="v2__card-dot" aria-hidden="true"></span>
        <h3>Dispatch quality validated</h3>
        <p>300-probe dispatch eval on Qwen-2.5-7B-Instruct (small-model deployment target). Gate decision baked into the release; drift between gate output and shipped constants is caught by a consistency test in CI.</p>
        <pre><code>tests/dispatch_eval/gate_0b_decision.json
tests/test_phase_f_gate_decision_consistency.py</code></pre>
      </li>
    </ul>
  </div>
</section>
```

Add minimal CSS for the `.v2` classes by copying the existing `.v1` rules from `public/assets/styles.css` and renaming `v1` → `v2`. (Use Find & Replace within the .v1 block only — do not touch other class names.)

- [ ] **Step 4: Move the four former v1 feature cards (Streamable HTTP, batch retrieval, per-entry resources, resource subscriptions) into the existing `<section id="what">` features section as standing capabilities.**

Find `<section id="what">` (around index.html line 244). Inside its feature list, add four new list items mirroring the prose from the deleted v1 cards. Frame them as "what OpenZIM MCP does today," not "what's new in v1."

- [ ] **Step 5: Refresh the `<section id="try">` use-tabs code samples.**

Find the "use" tab JSON-RPC code samples (around index.html lines 482-545). Two specific changes:

- Replace `"name": "search_zim_file"` with `"name": "zim_search"` and add `"mode": "fulltext"` to the arguments.
- Replace `"name": "browse_namespace"` with `"name": "zim_browse"` and add `"mode": "page"` to the arguments.

Then add a third tab labeled "Natural language" showing the simple-mode `zim_query` call:

```json
{
  "name": "zim_query",
  "arguments": {
    "query": "summarize the article on Photosynthesis"
  }
}
```

Wire it into the tab button group above (the existing `tab-use-search` / `tab-use-browse` / `tab-use-subscribe` pattern at lines 482-484): add `<button class="tabs__btn" role="tab" id="tab-use-nl" data-tab="use-nl" aria-selected="false" aria-controls="use-nl">Natural language</button>` and the matching `<div class="tabs__panel" id="use-nl" role="tabpanel" aria-labelledby="tab-use-nl" hidden>` panel.

- [ ] **Step 6: Build and visually verify.**

```bash
cd website && npm run dev
```

Open `http://localhost:4321/openzim-mcp/`. Verify:
- Nav shows `v2.0` not `v1.0`, and includes a `Docs` link.
- Scrolling to `#v2` lands on the new "The 2.0 release" section with three cards.
- The "Try" section's use tabs show `zim_search`/`zim_browse` and a new "Natural language" tab.
- `<section id="what">` features include the four former v1 capabilities as standing items.
- Page navigates to `/docs/` without 404.

- [ ] **Step 7: Verify build.**

```bash
cd website && npm run build && \
  grep -q 'id="v2"' dist/index.html && \
  ! grep -q 'id="v1"' dist/index.html && \
  grep -q 'zim_search' dist/index.html && \
  ! grep -q 'search_zim_file' dist/index.html && \
  echo "OK" && cd ..
```

Expected: `OK`. (If `search_zim_file` is matched, it means a code sample wasn't updated — find and fix.)

- [ ] **Step 8: Commit.**

```bash
git add website/src/pages/index.astro website/public/assets/styles.css
git commit -m "docs(site): refresh landing page from v1.0 to v2.0

- Rebuilds <section id=\"v1\"> (The 1.0 release) as <section id=\"v2\">
  with three v2.0.0 headline cards: 8-tool surface, simple mode
  unchanged, dispatch quality validated.
- Moves the four former v1 feature cards (HTTP, batch, per-entry
  resources, subscriptions) into the features section as standing
  capabilities.
- Updates 'Try' tabs to use the v2 8-tool surface (zim_search,
  zim_browse) and adds a 'Natural language' tab showing zim_query.
- Updates nav link, Schema.org breadcrumb position 3 to v2.0.
- Adds 'Docs' to primary nav."
```

### Task 1.6: Add the deployment workflow

**Files:** `.github/workflows/site.yml`.

- [ ] **Step 1: Create the workflow.**

```yaml
# .github/workflows/site.yml
name: Deploy site

on:
  push:
    branches: [main]
    paths:
      - 'website/**'
      - '.github/workflows/site.yml'
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: site-deploy
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-24.04
    defaults:
      run:
        working-directory: website
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: website/package-lock.json
      - run: npm ci
      - run: npx astro check
      - run: npm run build
      - uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: website/dist
          publish_branch: gh-pages
          force_orphan: false
          user_name: github-actions[bot]
          user_email: 41898282+github-actions[bot]@users.noreply.github.com
```

- [ ] **Step 2: Validate workflow syntax locally.**

```bash
gh workflow view --yaml .github/workflows/site.yml 2>&1 | head -3 || \
  (yamllint .github/workflows/site.yml 2>&1 | head -10; true)
```

Expected: no syntax errors. If `gh workflow view` doesn't recognize the file (it's not pushed yet), `yamllint` or just visual inspection of the YAML suffices.

- [ ] **Step 3: Commit.**

```bash
git add .github/workflows/site.yml
git commit -m "ci(site): add Astro build + gh-pages deploy workflow

Triggers on pushes to main that touch website/** or the workflow
itself. Runs astro check + npm run build, then peaceiris/actions-gh-pages
publishes website/dist/ to the gh-pages branch."
```

### Task 1.7: Open PR 1 and watch the first deploy

- [ ] **Step 1: Push the branch.**

```bash
git push -u origin docs/astro-scaffold
```

- [ ] **Step 2: Open the PR.**

```bash
gh pr create \
  --title "docs: Astro scaffold + landing v1→v2 refresh + gh-pages workflow" \
  --body "$(cat <<'EOF'
First of four staged PRs implementing the docs consolidation spec
(docs/specs/2026-05-27-docs-consolidation-design.md).

Scope:
- Initializes Astro 4.x project in website/ with mdx + sitemap.
- Ports website/index.html to src/pages/index.astro verbatim, then
  applies the v1.0 → v2.0 content refresh (new v2 release section,
  v2 8-tool code samples in Try tabs, Docs nav link).
- Hand-rolled docs scaffold (DocsLayout + sidebar/TOC/breadcrumbs/
  prev-next components, content collection schema) with one
  placeholder Introduction page. Real docs migrate in PR 2.
- New .github/workflows/site.yml deploys website/dist/ to gh-pages.
- Relocates robots.txt, humans.txt, llms.txt, .well-known/, assets/
  into website/public/.
- Deletes website/index.html (superseded), website/sitemap.xml
  (auto-generated now), website/validate.py (astro check replaces).

Rollback target: tag gh-pages-pre-astro (created in pre-flight Task 0).

Exit gate:
- [ ] / loads with refreshed v2 landing
- [ ] /docs/ renders the placeholder
- [ ] /llms.txt, /.well-known/*, /robots.txt still resolve at same URLs
- [ ] npm run build and astro check clean

Spec: docs/specs/2026-05-27-docs-consolidation-design.md
EOF
)" \
  --base main
```

- [ ] **Step 3: Watch CI. Once merged, monitor the `Deploy site` workflow run.**

```bash
gh run watch --exit-status
```

- [ ] **Step 4: Verify the live site after deploy.**

```bash
sleep 30 && \
  curl -fsSL https://cameronrye.github.io/openzim-mcp/ | grep -q 'id="v2"' && \
  curl -fsSL https://cameronrye.github.io/openzim-mcp/docs/ | grep -q 'Documentation' && \
  curl -fsSL https://cameronrye.github.io/openzim-mcp/llms.txt | head -1 && \
  curl -fsSL https://cameronrye.github.io/openzim-mcp/robots.txt | head -1 && \
  echo "DEPLOYED OK"
```

Expected: `DEPLOYED OK`. If any URL 404s, roll back:

```bash
# Emergency rollback (under 60s):
git push --force-with-lease origin gh-pages-pre-astro:gh-pages
```

---

## Phase 2 — PR 2: Migrate wiki content into the docs collection

**Branch:** `docs/migrate-wiki-content` (off `main`, after PR 1 merges).
**PR title:** `docs: migrate wiki content into Astro docs collection (15 pages)`.
**Exit gate:** All 15 docs pages render; `npm run build` clean; `lychee` linkcheck passes on `dist/`; no `*/wiki/*` links remain in README/CONTRIBUTING/SECURITY/website/llms.txt.

### Task 2.0: Pull current wiki content into a working folder

**Files:** `/tmp/openzim-mcp.wiki/` (clone target, not committed to repo).

- [ ] **Step 1: Branch off main.**

```bash
git checkout main && git pull --ff-only
git checkout -b docs/migrate-wiki-content
```

- [ ] **Step 2: Clone the wiki repo so source content is available locally.**

```bash
mkdir -p /tmp && cd /tmp && \
  rm -rf openzim-mcp.wiki && \
  git clone --depth 1 https://github.com/cameronrye/openzim-mcp.wiki.git && \
  cd /Volumes/rye/Developer/openzim-mcp
ls /tmp/openzim-mcp.wiki/*.md | wc -l
```

Expected: `15`.

### Task 2.1: The per-page refresh workflow (apply to each page in Task 2.2)

This is the canonical procedure. Tasks 2.2.1 through 2.2.15 below each invoke this workflow with page-specific inputs.

**Refresh standard (5 rules, repeated from the spec for engineers reading out of order):**

1. Use v2 8-tool names in all examples. v1 names only appear in: the API-reference migration table, the FAQ entry ("v1 code, what changed?"), and CHANGELOG links.
2. Default examples to simple mode (`zim_query`). Add an advanced-mode sibling example only on pages about specific advanced tools.
3. Pick one notation per page: MCP JSON-RPC framing (`{"name": "...", "arguments": {...}}`) OR Python pseudo-call. No mixing within a page.
4. Add the v1.x footer note where load-bearing only: `*v1.x is in maintenance through 2026-11-27. See [CHANGELOG](https://github.com/cameronrye/openzim-mcp/blob/main/CHANGELOG.md) for the v1 → v2 migration table.*`
5. Pin every page to v2.0.0. No "as of v1.x". No "in upcoming v2.5" forward-references except tied to a tracked issue (e.g., #199).

**Per-page steps (apply each time):**

- [ ] **Step A: Read the source wiki page.**

```bash
cat /tmp/openzim-mcp.wiki/<SOURCE>.md
```

- [ ] **Step B: Create the destination MDX file with the required frontmatter.**

```mdx
---
title: <TITLE>
summary: <ONE-LINE SUMMARY (~140 chars)>
group: <Get started | Reference | Guides | Operations>
sidebar_order: <NUMBER>
---

<BODY>
```

- [ ] **Step C: Port body content from the wiki page, applying the 5 refresh rules.**

For each occurrence of a legacy v1 tool name, replace it per the v1 → v2 map in the spec / CHANGELOG. Strip leading `# Page Title` if present (frontmatter handles the title). Normalize relative wiki links: `[Foo](Bar-Page)` → `[Foo](/docs/bar-page/)`.

- [ ] **Step D: Add page-specific changes per the per-page notes in Task 2.2.**

- [ ] **Step E: Build to verify the page renders and frontmatter validates.**

```bash
cd website && npm run build 2>&1 | grep -iE "error|warn" || echo "CLEAN" && cd ..
```

Expected: `CLEAN`. If a Zod schema validation error fires, fix frontmatter; if MDX parse error, fix bad markdown/JSX in the body.

- [ ] **Step F: Commit one page at a time (15 small commits is easier to review than one giant one).**

```bash
git add website/src/content/docs/<SLUG>.mdx
git commit -m "docs(site): migrate <SOURCE>.md to docs/<SLUG>.mdx

Refreshes for v2.0.0 8-tool surface: <ONE-LINE CHANGE SUMMARY>."
```

### Task 2.2: Per-page migration index

Apply the Task 2.1 workflow to each of the 15 pages below. Per-page notes call out beyond-the-baseline work.

| # | Source (wiki) | Destination MDX | group | sidebar_order | Per-page notes |
| --- | --- | --- | --- | --- | --- |
| 1 | `Home.md` | `introduction.mdx` | Get started | 1 | Replace placeholder. Becomes the /docs/ landing. Strip the wiki-only `## Quick Navigation` link list — sidebar handles nav. Keep the v2 banner and the "v1.x in maintenance" footer note. |
| 2 | `Installation-Guide.md` | `installation.mdx` | Get started | 2 | Already v2-current; verify all examples use 8-tool surface. Convert `pip install` and `uv tool install` examples to side-by-side fenced blocks. |
| 3 | `Quick-Start-Tutorial.md` | `quick-start.mdx` | Get started | 3 | Refresh 5-min tour: start with simple-mode `zim_query`, then show one advanced example (`zim_search` + `zim_get`). Verify the test-ZIM-file download URL is still live. |
| 4 | `API-Reference.md` | `api-reference.mdx` | Reference | 1 | Already v2-current. Embed the v1 → v2 migration table inline (copy from CHANGELOG.md `## Migrating from v1.x → v2`) rather than just linking — engineers searching for a v1 tool name should find the row on this page. |
| 5 | `Configuration-Guide.md` | `configuration.mdx` | Reference | 2 | Just rewritten for v2; light scrub. Tables of env vars and CLI flags should be sorted alphabetically per group for predictability. |
| 6 | `Resources-Prompts-Subscriptions.md` | `resources-prompts-subscriptions.mdx` | Reference | 3 | 13 v1 refs in code samples; rewrite to v2. Cover the three MCP prompts (`/research`, `/summarize`, `/explore`) and three resource templates (`zim://files`, `zim://{name}`, `zim://{name}/entry/{path}`) plus subscriptions. |
| 7 | `LLM-Integration-Patterns.md` | `llm-integration-patterns.mdx` | Guides | 1 | **Heavy.** Every code sample needs the 8-tool rewrite. Highest-leverage page for users. After rewriting, scan for "v1.x" / "pre-v2" phrasing and flatten to present tense. |
| 8 | `Smart-Retrieval-System-Guide.md` | `smart-retrieval.mdx` | Guides | 2 | **Heavy.** Page explains fallback behavior through v1 examples. Rewrite the fallback walkthrough using `zim_get` (single mode) — fallback semantics are unchanged, just the tool name. |
| 9 | `HTTP-and-Docker-Deployment.md` + `docs/deployment.md` | `http-and-docker-deployment.mdx` | Guides | 3 | **Merge.** The wiki page covers the protocol/auth/CORS; `docs/deployment.md` is more deployment-recipe-flavored. Dedupe by section: keep the wiki's protocol prose, fold the repo's deployment-recipe sections at the bottom under "Deployment patterns". Delete `docs/deployment.md` from the repo in the same commit. |
| 10 | `Performance-Optimization-Guide.md` | `performance-optimization.mdx` | Guides | 4 | **Heavy.** 23 v1 refs. Benchmark tables stay (the numbers are still directionally correct) but add a caveat: `*Benchmark numbers captured against v1.x's 22-tool surface in 2026-04. Tool-name dispatch overhead is unchanged in v2; per-call latency numbers remain representative.*` |
| 11 | `Security-Best-Practices.md` | `security-best-practices.mdx` | Guides | 5 | 8 v1 refs in examples; rewrite. Verify the bearer-token + CORS examples align with v2 transport behavior (no functional change). |
| 12 | _(new — from README Examples block)_ | `worked-examples.mdx` | Guides | 6 | Migrate the five case studies (Taxonomy, Protein, Ant, Video game, Protein-redux) from README lines 977–1517. Rewrite every legacy tool name to v2. Group as five `## Case study: <Topic>` sections with a top-of-page table of contents (auto-generated by the TOC component). |
| 13 | `Troubleshooting-Guide.md` | `troubleshooting.mdx` | Operations | 1 | Just rewritten for v2; light scrub. |
| 14 | `FAQ.md` | `faq.mdx` | Operations | 2 | Scrub 2 stale refs. Add 3–5 v2-era questions: "What changed from v1?", "Simple vs Advanced mode — which do I want?", "What's the MCP Tax and why does the 8-tool surface help?", "My v1 client code references `search_zim_file` — how do I migrate?", "When is v1.x EOL?" |
| 15 | `Architecture-Overview.md` | `architecture-overview.mdx` | Operations | 3 | 11 v1 refs. Replace the 22-tool surface diagram with the 8-tool surface + mode dispatch. If there's an ASCII or Mermaid diagram, redraw with the 8 consolidated tools at the top layer and the v1 operations as call-out annotations on the relevant tool. |

After all 15 commits, the next task verifies the whole batch.

### Task 2.3: Verify all 15 docs pages render and the sidebar is correctly ordered

- [ ] **Step 1: Build and check page count.**

```bash
cd website && npm run build && \
  ls dist/docs/*/index.html | wc -l && \
  ls dist/docs/*/index.html | sort && \
  cd ..
```

Expected: 15 lines (one per slug). Verify each expected slug appears (`introduction`, `installation`, `quick-start`, `api-reference`, `configuration`, `resources-prompts-subscriptions`, `llm-integration-patterns`, `smart-retrieval`, `http-and-docker-deployment`, `performance-optimization`, `security-best-practices`, `worked-examples`, `troubleshooting`, `faq`, `architecture-overview`).

- [ ] **Step 2: Visually inspect the sidebar.**

```bash
cd website && npm run dev
```

Open `http://localhost:4321/openzim-mcp/docs/introduction/`. Verify the sidebar shows four groups in this order: Get started (3 items), Reference (3), Guides (6 — including Worked examples last), Operations (3 — Troubleshooting, FAQ, Architecture overview). Click each link; each loads without 404.

- [ ] **Step 3: Run linkcheck against the built site.**

```bash
cd website && npm run build && \
  npx --yes linkinator dist/ --recurse --skip "^https?://(localhost|cameronrye\.github\.io)" 2>&1 | tail -20
```

Expected: `0 broken` (or just internal-link findings; cross-check any external 404s on a case-by-case basis). The skip pattern excludes the live deploy URL because the new pages aren't deployed yet.

If a broken internal link surfaces, find and fix in the corresponding MDX file, then re-run.

### Task 2.4: Merge `docs/deployment.md` content + delete the file

Already done as part of Task 2.2 row 9 (HTTP & Docker deployment), but explicitly confirm:

- [ ] **Step 1: Confirm `docs/deployment.md` is gone.**

```bash
test ! -f docs/deployment.md && echo "OK — file removed"
```

Expected: `OK — file removed`.

- [ ] **Step 2: Confirm the merged content lives at `website/src/content/docs/http-and-docker-deployment.mdx`.**

```bash
grep -c "deployment" website/src/content/docs/http-and-docker-deployment.mdx
```

Expected: a small non-zero number (the word appears in headings and prose).

### Task 2.5: Append "Release process" section to CONTRIBUTING.md

**Files:** `CONTRIBUTING.md`, `/tmp/openzim-mcp.wiki/Release-System-Guide.md`.

- [ ] **Step 1: Read the wiki source.**

```bash
cat /tmp/openzim-mcp.wiki/Release-System-Guide.md
```

- [ ] **Step 2: Append a new "Release process" section to the end of `CONTRIBUTING.md`.**

The section should summarize (not verbatim-copy) the wiki content: release-please configuration, the manual-tag fallback path, the create-then-publish flow for immutable releases. Cap at ~80 lines. Use a stable anchor: `## Release process` (so PR 4's `Release-System-Guide.md` stub can deep-link to `#release-process`).

- [ ] **Step 3: Verify the anchor by building docs (Astro doesn't render CONTRIBUTING.md, but GitHub uses the slug `release-process`).**

```bash
grep -q "^## Release process" CONTRIBUTING.md && echo "OK"
```

Expected: `OK`.

- [ ] **Step 4: Commit.**

```bash
git add CONTRIBUTING.md
git commit -m "docs(contributing): add Release process section

Summarizes the release-please workflow and the manual-tag fallback
previously documented in the Release-System-Guide wiki page. The
wiki page becomes a redirect stub in PR 4."
```

### Task 2.6: Update cross-references in README / CONTRIBUTING / SECURITY / llms.txt

**Files:** `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `website/public/llms.txt`.

PR 2's job is content move, not README restructure. README stays huge for now; we just rewrite its links from wiki URLs to `/docs/<slug>/` URLs so links resolve once PR 2 lands.

- [ ] **Step 1: Find every wiki-URL reference across the four files.**

```bash
grep -nE "github\.com/cameronrye/openzim-mcp/wiki|github\.com/cameronrye/openzim-mcp\.wiki" \
  README.md CONTRIBUTING.md SECURITY.md website/public/llms.txt
```

- [ ] **Step 2: Replace each. The mapping is:**

| Wiki URL fragment | New URL |
| --- | --- |
| `/wiki/Home` | `/docs/introduction/` |
| `/wiki/Installation-Guide` | `/docs/installation/` |
| `/wiki/Quick-Start-Tutorial` | `/docs/quick-start/` |
| `/wiki/API-Reference` | `/docs/api-reference/` |
| `/wiki/Configuration-Guide` | `/docs/configuration/` |
| `/wiki/Resources-Prompts-Subscriptions` | `/docs/resources-prompts-subscriptions/` |
| `/wiki/LLM-Integration-Patterns` | `/docs/llm-integration-patterns/` |
| `/wiki/Smart-Retrieval-System-Guide` | `/docs/smart-retrieval/` |
| `/wiki/HTTP-and-Docker-Deployment` | `/docs/http-and-docker-deployment/` |
| `/wiki/Performance-Optimization-Guide` | `/docs/performance-optimization/` |
| `/wiki/Security-Best-Practices` | `/docs/security-best-practices/` |
| `/wiki/Troubleshooting-Guide` | `/docs/troubleshooting/` |
| `/wiki/FAQ` | `/docs/faq/` |
| `/wiki/Architecture-Overview` | `/docs/architecture-overview/` |
| `/wiki/Release-System-Guide` | `/blob/main/CONTRIBUTING.md#release-process` |

Each new docs URL is relative to `https://cameronrye.github.io/openzim-mcp` (full URL: `https://cameronrye.github.io/openzim-mcp/docs/installation/`, etc.).

- [ ] **Step 3: Re-grep to confirm no wiki URLs remain.**

```bash
grep -nE "github\.com/cameronrye/openzim-mcp/wiki|github\.com/cameronrye/openzim-mcp\.wiki" \
  README.md CONTRIBUTING.md SECURITY.md website/public/llms.txt || echo "OK — no wiki refs left"
```

Expected: `OK — no wiki refs left`.

- [ ] **Step 4: Commit.**

```bash
git add README.md CONTRIBUTING.md SECURITY.md website/public/llms.txt
git commit -m "docs: repoint wiki URLs to /docs/<slug>/ in README, CONTRIBUTING, SECURITY, llms.txt

Wiki migration lands in this PR; wiki itself gets redirect stubs in PR 4.
After this commit, no canonical content link in this repo points at /wiki/."
```

### Task 2.7: Open PR 2

- [ ] **Step 1: Push and open the PR.**

```bash
git push -u origin docs/migrate-wiki-content
gh pr create \
  --title "docs: migrate wiki content into Astro docs collection (15 pages)" \
  --body "$(cat <<'EOF'
Second of four PRs implementing the docs consolidation spec
(docs/specs/2026-05-27-docs-consolidation-design.md).

Scope:
- 15 MDX pages in website/src/content/docs/ (14 from wiki, 1 new
  worked-examples.mdx from README).
- Sidebar nav (4 groups, 15 entries) wired via the content
  collection schema.
- Merges docs/deployment.md into http-and-docker-deployment.mdx and
  deletes the standalone file.
- Adds 'Release process' section to CONTRIBUTING.md.
- Repoints wiki URLs in README, CONTRIBUTING, SECURITY, llms.txt
  to /docs/<slug>/ URLs.

Exit gate:
- [ ] All 15 docs pages render under /docs/<slug>/.
- [ ] npm run build clean.
- [ ] Linkcheck clean.
- [ ] No github.com/.../wiki/ links remain in README/CONTRIBUTING/
      SECURITY/llms.txt.

Spec: docs/specs/2026-05-27-docs-consolidation-design.md
EOF
)" \
  --base main
```

- [ ] **Step 2: After merge, verify deployed pages.**

```bash
sleep 30 && \
  for slug in introduction installation quick-start api-reference configuration resources-prompts-subscriptions llm-integration-patterns smart-retrieval http-and-docker-deployment performance-optimization security-best-practices worked-examples troubleshooting faq architecture-overview; do
    code=$(curl -sLo /dev/null -w "%{http_code}" "https://cameronrye.github.io/openzim-mcp/docs/$slug/")
    echo "$code  $slug"
  done
```

Expected: every line shows `200`. Any other code → investigate that page.

---

## Phase 3 — PR 3: Slim README to project card

**Branch:** `docs/slim-readme` (off `main`, after PR 2 merges).
**PR title:** `docs: slim README to ~250-line project card; relocate Dev/Test prose to CONTRIBUTING.md`.
**Exit gate:** README is 200–300 lines; every section is in the spec's §"README shape" list or removed; all links resolve.

### Task 3.1: Append Development + Testing sections to CONTRIBUTING.md

**Files:** `CONTRIBUTING.md`, `README.md` (read-only for source).

- [ ] **Step 1: Branch off main.**

```bash
git checkout main && git pull --ff-only
git checkout -b docs/slim-readme
```

- [ ] **Step 2: Read the README's Development section (around lines 566-686) and Testing section (around lines 1659-1706).**

- [ ] **Step 3: Append both sections to `CONTRIBUTING.md` under existing structure (or create `## Development` and `## Testing` headings if missing).**

If the user's CLAUDE.md global rules apply: no AI attribution, write as if you are the developer.

- [ ] **Step 4: Commit.**

```bash
git add CONTRIBUTING.md
git commit -m "docs(contributing): import Development + Testing sections from README

Prep for README slim-down in the next commit. Content moves verbatim
from README sections, lightly edited for the contributor-doc context
(removes badges, install steps that belong in README)."
```

### Task 3.2: Rewrite README

**Files:** `README.md`.

This is one big rewrite — the README ends up at ~250 lines from ~1,806. Approach: write the new content into a scratch file, diff against the old to ensure nothing load-bearing is lost, then replace.

- [ ] **Step 1: Sketch the new structure into `README.md.new` based on the spec's §"README shape".**

The 13 sections from the spec, in order:
1. Logo + name + tagline (unchanged, ~3 lines)
2. Badges trimmed to 2 rows (drop the 4-badge social row: issues/PRs/contributors/stars)
3. One-paragraph pitch (~5 lines)
4. v2.0.0 callout (4-line banner linking to docs site and CHANGELOG)
5. Install (uv + pip + Docker one-liner, ~15 lines)
6. Quick start (simple-mode 5-line example + MCP client config block, ~30 lines)
7. What's in v2.0.0 (4 bullets, ~20 lines, links into docs site for depth)
8. Modes (Simple vs Advanced, ~25 lines)
9. Documentation (table linking the four sidebar groups, ~20 lines)
10. Project status (v2.0.0 GA, v1.x maintenance to 2026-11-27, CHANGELOG link, ~5 lines)
11. Contributing (link to CONTRIBUTING.md, ~3 lines)
12. Security (link to SECURITY.md, ~3 lines)
13. License + acknowledgments (trimmed, ~10 lines)

- [ ] **Step 2: Move `README.md.new` into place.**

```bash
mv README.md.new README.md
```

- [ ] **Step 3: Verify line count is in target range.**

```bash
wc -l README.md
```

Expected: 200–300. If under 200, you've cut something load-bearing (likely Quick start or Modes); if over 300, prune.

- [ ] **Step 4: Verify every section from the spec's section list is present.**

```bash
grep -cE "^## " README.md
```

Expected: ~10–12 H2 sections (the spec has 13 logical sections; some compose under one H2).

- [ ] **Step 5: Verify all dropped sections are actually gone.**

```bash
grep -cE "What's new in v0\.9\.0|What's new in v1\.0\.0|What's new in v1\.1\.0|What's new in v1\.2\.0|What's new in v2\.0\.0a1|What's new in v2\.0\.0a2" README.md
```

Expected: `0`.

```bash
grep -cE "^## (Examples|Configuration|Security Features|Performance Features|Testing|Monitoring|Development|API Reference)$" README.md
```

Expected: `0` (these all moved to docs or CONTRIBUTING).

- [ ] **Step 6: Run linkcheck on the new README.**

```bash
npx --yes linkinator README.md --markdown --skip "^https?://localhost" 2>&1 | tail -10
```

Expected: `0 broken`. Fix any.

- [ ] **Step 7: Commit.**

```bash
git add README.md
git commit -m "docs(readme): slim from 1,806 to ~250 lines (project card shape)

- Drops 7 stacked 'What's new in vX' sections (content already in CHANGELOG).
- Drops Examples block (moved to docs/worked-examples in PR 2).
- Drops long-form Configuration / Security / Performance / Monitoring /
  Versioning prose (moved to docs site in PR 2).
- Drops Development + Testing prose (moved to CONTRIBUTING.md in the
  previous commit).
- Drops the full API Reference long form (moved to docs in PR 2).
- Trims badges from 4 rows to 2 (drops issues/PRs/contributors/stars row).
- Adds v2.0.0 callout, Modes section, Project status section,
  Documentation link table per the consolidation spec."
```

### Task 3.3: Open PR 3

- [ ] **Step 1: Push and open the PR.**

```bash
git push -u origin docs/slim-readme
gh pr create \
  --title "docs: slim README to ~250-line project card; relocate Dev/Test prose to CONTRIBUTING.md" \
  --body "$(cat <<'EOF'
Third of four PRs implementing the docs consolidation spec
(docs/specs/2026-05-27-docs-consolidation-design.md).

Scope:
- Slims README from 1,806 to ~250 lines (project-card shape).
- Drops 7 'What's new in vX' sections, Examples block, long-form
  Configuration/Security/Performance/Monitoring/Testing/Development/
  Versioning/API Reference sections. All content is already in
  CHANGELOG, docs site (PR 2), or CONTRIBUTING.md.
- Imports Development + Testing sections into CONTRIBUTING.md.

Exit gate:
- [ ] README is 200–300 lines.
- [ ] Every README section is in the spec's README shape list or
      explicitly removed.
- [ ] All README links resolve (linkcheck).

Spec: docs/specs/2026-05-27-docs-consolidation-design.md
EOF
)" \
  --base main
```

---

## Phase 4 — PR 4: Retire the GitHub wiki (redirect stubs only)

**Branch:** the wiki repo's `master` branch — NOT a branch in the main repo. This is a one-off push to the separate wiki git repo. Document the action in a follow-up commit / GitHub issue rather than a PR.
**Exit gate:** all 15 wiki pages serve redirect stubs; Google sitemap covers the new canonical URLs.

### Task 4.1: Generate redirect stubs for all 15 wiki pages

**Files:** `/tmp/openzim-mcp.wiki/*.md` (working clone, pushed back to `origin/master`).

- [ ] **Step 1: Refresh the wiki clone (it may have been updated since PR 2's Task 2.0).**

```bash
cd /tmp/openzim-mcp.wiki && git pull --ff-only && cd /Volumes/rye/Developer/openzim-mcp
```

- [ ] **Step 2: Rewrite each of the 15 pages to a single-stanza redirect stub. Use the same canonical-URL mapping table from PR 2 Task 2.6.**

Template (use this exact body, swapping `<NEW_URL>` per page):

```markdown
# This page has moved

The OpenZIM MCP wiki has been retired. This page now lives at:

<NEW_URL>

For the full documentation site, see https://cameronrye.github.io/openzim-mcp/docs/
```

Mapping (re-stated here so engineers reading out of order have it):

| Wiki page | NEW_URL |
| --- | --- |
| `Home.md` | `https://cameronrye.github.io/openzim-mcp/docs/introduction/` |
| `Installation-Guide.md` | `https://cameronrye.github.io/openzim-mcp/docs/installation/` |
| `Quick-Start-Tutorial.md` | `https://cameronrye.github.io/openzim-mcp/docs/quick-start/` |
| `API-Reference.md` | `https://cameronrye.github.io/openzim-mcp/docs/api-reference/` |
| `Configuration-Guide.md` | `https://cameronrye.github.io/openzim-mcp/docs/configuration/` |
| `Resources-Prompts-Subscriptions.md` | `https://cameronrye.github.io/openzim-mcp/docs/resources-prompts-subscriptions/` |
| `LLM-Integration-Patterns.md` | `https://cameronrye.github.io/openzim-mcp/docs/llm-integration-patterns/` |
| `Smart-Retrieval-System-Guide.md` | `https://cameronrye.github.io/openzim-mcp/docs/smart-retrieval/` |
| `HTTP-and-Docker-Deployment.md` | `https://cameronrye.github.io/openzim-mcp/docs/http-and-docker-deployment/` |
| `Performance-Optimization-Guide.md` | `https://cameronrye.github.io/openzim-mcp/docs/performance-optimization/` |
| `Security-Best-Practices.md` | `https://cameronrye.github.io/openzim-mcp/docs/security-best-practices/` |
| `Troubleshooting-Guide.md` | `https://cameronrye.github.io/openzim-mcp/docs/troubleshooting/` |
| `FAQ.md` | `https://cameronrye.github.io/openzim-mcp/docs/faq/` |
| `Architecture-Overview.md` | `https://cameronrye.github.io/openzim-mcp/docs/architecture-overview/` |
| `Release-System-Guide.md` | `https://github.com/cameronrye/openzim-mcp/blob/main/CONTRIBUTING.md#release-process` |

- [ ] **Step 3: Verify each file is now the stub (not the old content).**

```bash
cd /tmp/openzim-mcp.wiki && \
  for f in *.md; do
    head -1 "$f" | grep -q "^# This page has moved$" || echo "STILL HAS OLD CONTENT: $f"
  done && echo "(empty above = all 15 files are stubs)"
```

Expected: only the trailing `(empty above = all 15 files are stubs)` line. If any "STILL HAS OLD CONTENT" lines print, rewrite those.

- [ ] **Step 4: Commit and push to the wiki repo.**

```bash
cd /tmp/openzim-mcp.wiki && \
  git add -A && \
  git commit -m "docs(wiki): retire wiki — every page now redirects to the docs site

The OpenZIM MCP wiki has been consolidated into the Astro docs site at
https://cameronrye.github.io/openzim-mcp/docs/. Every wiki page is now
a single-stanza redirect stub. The wiki feature stays enabled for ~30
days so external bookmarks land softly; it will be disabled in a
follow-up chore." && \
  git push origin master
```

- [ ] **Step 5: Verify the redirects are live.**

```bash
sleep 5 && \
  for slug in Home Installation-Guide Quick-Start-Tutorial API-Reference Configuration-Guide Resources-Prompts-Subscriptions LLM-Integration-Patterns Smart-Retrieval-System-Guide HTTP-and-Docker-Deployment Performance-Optimization-Guide Security-Best-Practices Troubleshooting-Guide FAQ Architecture-Overview Release-System-Guide; do
    body=$(curl -fsSL "https://github.com/cameronrye/openzim-mcp/wiki/$slug")
    echo "$body" | grep -q "This page has moved" && echo "OK  $slug" || echo "FAIL $slug"
  done
```

Expected: 15 `OK` lines.

### Task 4.2: File the follow-up chore for has_wiki disable (~30 days out)

**Files:** none — file a GitHub issue.

- [ ] **Step 1: Open an issue scheduled for ~30 days after PR 4 lands.**

```bash
gh issue create \
  --title "chore(wiki): disable has_wiki after redirect-stub grace period" \
  --body "$(cat <<'EOF'
Background: PR 4 of the docs consolidation effort
(docs/plans/2026-05-27-docs-consolidation.md) retired the GitHub wiki by
rewriting every page as a redirect stub. The wiki feature is left
ENABLED for ~30 days so external bookmarks and stale Google results
land on the redirect stubs rather than 404ing immediately.

Action (when this issue is worked, ~2026-06-27 onward):

1. Verify search engines have re-indexed the new canonical URLs at
   https://cameronrye.github.io/openzim-mcp/docs/<slug>/ — sample one
   query like 'openzim-mcp installation guide' and check the top
   result is the docs site, not the wiki.

2. Disable the wiki feature:

   gh api -X PATCH repos/cameronrye/openzim-mcp -f has_wiki=false

3. Verify the Wiki tab is gone from the repo settings page.

4. Close this issue.
EOF
)" \
  --label chore
```

- [ ] **Step 2: Note the issue number for the consolidation spec retrospective.**

---

## Self-review

After writing the plan, the author (me) verified each section:

- **Spec coverage:** Each section of the spec maps to at least one task. Architecture → Tasks 1.1–1.6. Information architecture → Task 2.2 table. Per-page refresh → Tasks 2.1 (workflow) + 2.2 (index). Landing page refresh → Task 1.5. README shape → Tasks 3.1 + 3.2. PR sequencing → the four phase headers. Risks → covered by Task 0 (rollback tag), explicit `gh-pages-pre-astro` mention in Task 1.7, the 30-day-grace pattern in Tasks 4.1/4.2.
- **Placeholder scan:** No "TBD"/"TODO"/"fill in details" in any task. Per-page workflow (Task 2.1) intentionally provides a template with explicit per-page deltas in Task 2.2 — this is template + index, not a placeholder.
- **Type consistency:** Component names match between Task 1.4 (creation) and the import in `DocsLayout.astro` (`Sidebar`, `Breadcrumbs`, `TableOfContents`, `PrevNext`). Content-collection field names match between `config.ts` and the per-page frontmatter (`title`, `summary`, `group`, `sidebar_order`). Slug list matches between Tasks 2.2, 2.3, and 2.6.

The plan is ready to execute.
