# Website v1.0.0 Redesign — Design Spec

**Date:** 2026-05-02
**Status:** Draft for review
**Scope:** Reskin and restructure [website/index.html](../../../website/index.html), [website/assets/styles.css](../../../website/assets/styles.css), and [website/assets/script.js](../../../website/assets/script.js) to celebrate the v1.0.0 milestone with a new visual identity (constellation logo, amber-on-ink palette), a tightened information architecture, and a custom hero illustration. Replaces the existing site in-place; no build pipeline introduced.

---

## Background

The v1.0.0 release ([CHANGELOG.md](../../../CHANGELOG.md)) ships streamable HTTP transport, batch entry retrieval, per-entry MCP resources, and resource subscriptions — a substantial set of milestone features. The existing website ([website/index.html](../../../website/index.html), 1302 lines) was last refreshed for v1.0.0 content in a prior pass ([2026-05-01-v1.0.0-readme-website-update-design.md](2026-05-01-v1.0.0-readme-website-update-design.md)) but its visual identity (blue→emerald gradient, generic SaaS hero, 9 content sections that read as repetitive feature lists) under-celebrates the milestone and reads as stock-template.

This redesign treats v1.0 as a brand moment: new logo, new palette, new IA, new hero illustration. It stays vanilla HTML/CSS/JS with zero JS dependencies — the goal is "next-level" without inheriting build-pipeline overhead.

## Decisions (locked during brainstorming)

1. **Scope:** Option B — reskin + IA restructure. Not a refresh (under-celebrates), not a full rebuild on Astro/11ty (build-pipeline overhead a solo project pays forever).
2. **Brand mood:** Hybrid of *Technical/Signal* (chrome) + *Offline-first explorer* (motif). Reads serious-infra but tells the offline/knowledge story.
3. **Logo:** Constellation — asymmetric 5-dot asterism with thin connecting lines, sitting in a soft square boundary. Reads simultaneously as knowledge graph, star map, and network of MCP tools. Scales from 3-dot favicon to full-screen hero illustration.
4. **Palette:** Amber-on-ink primary.
   - `--ink: #0B0F1A` (background, dark default)
   - `--paper: #F5F1E8` (text on dark / background on light)
   - `--signal: #FFD24A` (warm amber, primary accent — like a star)
   - `--secondary: #5B8DEF` (cold blue, used sparingly for links/state)
   - Light theme inverts neutrals; amber and blue stay.
5. **Typography:** Geist Sans for headings + body, JetBrains Mono for code, Fraunces for the hero "v1.0" numerals only (single expressive serif moment).
6. **JS budget:** Zero dependencies. Constellation animation = SVG + ~80 lines of `requestAnimationFrame`.
7. **File structure:** Single `index.html`. Single `styles.css` but sectioned with clear `/* ===== REGION ===== */` comment fences. New `script.js` — keep current util functions, add `constellation.js` *concatenated into* the single bundle (or a second `<script>`).
8. **Default theme:** Dark default (amber-on-ink is the headline look). Light theme via the existing toggle.
9. **Motion language:** Restrained. Constellation hero draws once on load (~600ms). Section reveals: 200ms opacity + 8px translate. Hover states: 120ms. No parallax, no scroll-jacking. `prefers-reduced-motion` respected (constellation appears statically drawn, all reveals become instant).
10. **IA:** 5 sections — Hero / What is this / What's in v1.0 / Try it / Deeper — replacing the current 9. Smart Retrieval, Security, Advanced Features, Developer Experience all collapse into a single "Built for production" stat strip. Dev workflow content (`make install`) moves out of the landing page entirely (lives on the wiki).

---

## Visual identity

### Logo — Constellation mark

**Concept:** Five points connected by thin lines, arranged in an asymmetric asterism (deliberately *not* a recognizable real constellation — avoids cultural specificity, lets the mark feel found rather than referenced). The mark sits inside a soft-cornered square (4px radius at 32px size) so it has weight at favicon scale.

**Construction rules:**

- 5 dots positioned roughly: top-center, upper-left, upper-right, lower-left, lower-right (loose pentagon, intentionally tilted ~8° clockwise so it doesn't read as symmetric)
- Connecting lines: top → upper-left, top → upper-right, upper-left → lower-left, upper-right → lower-right, lower-left → lower-right (a "kite + base" shape)
- Dots stroked, not filled, at 32px+ sizes (1.5px stroke weight). Filled at favicon size (≤16px).
- Single color (paper on ink, ink on paper). Amber accent is reserved for the brightest dot — top-center — at hero scale only.

**Size variants:**

- 16px favicon: 3 filled dots only, no lines (lines too thin to read)
- 32px nav: full 5 dots stroked + lines, monochrome
- 48px hero badge: full mark + amber top dot
- Hero illustration: full constellation drawn at 480×480, animated draw-on-load, top dot pulses subtly (1 cycle / 4s, ±15% opacity)

**Files to produce:**

- `assets/logo.svg` — 32px nav variant (replace existing)
- `assets/favicon.svg` — 16px favicon (replace existing)
- `assets/favicon.ico` — fallback (replace existing 1-byte stub)
- `assets/og-image.svg` — new 1200×630 OG image with the hero illustration + "OpenZIM MCP 1.0" wordmark
- `assets/brain-icon.svg` — **delete** (no longer used after redesign)

### Palette tokens

```css
:root {
  /* Brand */
  --ink: #0B0F1A;
  --ink-elev: #131826;        /* card / nav surface on dark */
  --paper: #F5F1E8;
  --paper-elev: #FFFFFF;      /* card / nav surface on light */
  --signal: #FFD24A;          /* amber accent */
  --signal-dim: #B8923A;      /* amber for hover/active on light bg */
  --secondary: #5B8DEF;       /* cold blue */
  --muted: #7A8499;           /* dark mode body-secondary */
  --muted-light: #5B6478;     /* light mode body-secondary */
  --border: #1F2533;          /* dark mode borders */
  --border-light: #D8D2C2;    /* light mode borders */
  --success: #22D3A8;
  --danger: #E85D3C;
}

[data-theme="light"] {
  --bg: var(--paper);
  --surface: var(--paper-elev);
  --text: var(--ink);
  --text-secondary: var(--muted-light);
  --border-color: var(--border-light);
}

[data-theme="dark"], :root {  /* dark default */
  --bg: var(--ink);
  --surface: var(--ink-elev);
  --text: var(--paper);
  --text-secondary: var(--muted);
  --border-color: var(--border);
}
```

The signal amber and secondary blue stay the same in both themes — only neutrals invert.

### Typography

```css
--font-display: 'Fraunces', Georgia, serif;          /* hero "1.0" numerals only */
--font-sans: 'Geist', 'Inter', system-ui, sans-serif;  /* Google Fonts ships the family as "Geist", not "Geist Sans" */
--font-mono: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;

/* Type scale — slightly tightened from current */
--text-xs: 0.75rem;
--text-sm: 0.875rem;
--text-base: 1rem;
--text-lg: 1.125rem;
--text-xl: 1.375rem;
--text-2xl: 1.75rem;
--text-3xl: 2.25rem;
--text-4xl: 3rem;
--text-5xl: 4rem;
--text-6xl: 5.5rem;          /* hero title */
--text-display: 8rem;        /* hero "1.0" Fraunces moment */

/* Weights */
--weight-regular: 400;
--weight-medium: 500;
--weight-semibold: 600;
```

Geist Sans loaded via Vercel's CDN or Google Fonts (use Google Fonts: `family=Geist:wght@400;500;600`); JetBrains Mono and Fraunces from Google Fonts. Three font families total — one network round-trip via `family=Geist:wght@400;500;600&family=JetBrains+Mono:wght@400;500&family=Fraunces:wght@600` combined query.

### Motion language

| Element | Duration | Easing | Notes |
|---|---|---|---|
| Constellation draw-on-load | 600ms total, 80ms stagger per line | `cubic-bezier(0.2, 0.8, 0.3, 1)` | Lines stroke-dasharray animation, dots fade in 200ms after their lines complete |
| Top-dot pulse | 4s loop, ±15% opacity | `ease-in-out` | Only at hero scale; off in nav |
| Section reveal on scroll | 200ms opacity + 8px translate-y | `cubic-bezier(0.2, 0.8, 0.3, 1)` | Triggered by IntersectionObserver at 0.15 threshold |
| Hover (link, button, card) | 120ms | `ease-out` | Color, background, border |
| Theme toggle | 200ms | `ease` | Background + text crossfade |
| Tab switch | 150ms | `ease-out` | Cross-fade only, no slide |
| Copy-button feedback | 1500ms toast, 200ms slide-up | `ease-out` | Reuse existing copy-toast pattern |

`@media (prefers-reduced-motion: reduce)`: constellation drawn statically (no stagger), section reveals become instant (opacity 1 immediately, no translate), hover transitions stay (they're not "motion" in the disability sense), top-dot pulse disabled.

---

## Information architecture

### 1. Nav

Sticky top nav, 64px tall, surface-colored with 1px bottom border. Contains: logo + wordmark on the left, anchor links on the right (`What is this · v1.0 · Try it · Deeper · GitHub`), theme toggle as the rightmost element. Mobile: hamburger collapse at <768px (reuse existing pattern). No scroll-progress bar (current site has one — cut as visual noise).

### 2. Hero

**Layout:** Two-column at ≥1024px, stacked at <1024px. Left column 50% width.

**Left column (content):**

- Tiny eyebrow: `MCP SERVER · v1.0.0` in mono, `--signal` amber color, all caps, letter-spaced
- H1 in Geist Sans: **"Knowledge that works offline."** (big claim, period included, 5xl→6xl scale)
- Sub-headline (text-lg, secondary text color): "OpenZIM MCP gives any AI model structured, secure access to ZIM archives — Wikipedia, MedlinePlus, the Stack Exchange dumps — without an internet connection."
- Two buttons: primary `Get started →` (filled amber on ink, jumps to #try-it), secondary `View on GitHub ↗` (outline style)
- Below buttons: install one-liner in a mono pill with copy button — `uv tool install openzim-mcp` — showing immediately what the first step is
- Below that, a 4-stat strip (Latest release · Test coverage · Tools available · License). Replace current "Known vulnerabilities = 0" stat (negative framing) with "Tools available: 21" (positive, informative).

**Right column (visual):**

- Constellation hero illustration, 480×480 SVG container
- Animated: lines stroke in over 600ms with 80ms stagger, dots fade in trailing
- Top dot is amber and pulses
- Background: subtle radial gradient from the top-center dot outward, 30% opacity, only on dark theme

**Removed from current hero:**

- The MCP-config code window (replaced by the constellation; install one-liner covers the "what does it look like" need more concretely)
- The "Built for LLM Intelligence" badge (eyebrow replaces it more elegantly)
- The "NEW Feature Banner" strip above the hero (the v1.0 framing is already throughout — no need for a banner-on-banner)

### 3. What is this

One-screen explainer. Centered max-width 960px container. Single paragraph + a diagram.

**Diagram (SVG, ~600px wide):** Three labeled boxes left-to-right with arrows between them.

- Box 1 (left): "ZIM archive" with a small archive-icon and a stack of file glyphs
- Box 2 (center, larger, highlighted with `--signal` border): "openzim-mcp" with the constellation mark inside
- Box 3 (right): "Your LLM" with an abstract chat-bubble glyph
- Below each box, a one-word descriptor: `Static · Intelligent · Conversational`
- Arrows are dashed amber (`--signal`)

**Three-card row beneath the diagram:** `Offline · Secure · Structured` — each card has a one-line claim and a 2-line elaboration. This is the only place the "Built for production" stats appear: `Zero known CVEs · 80%+ test coverage · 100% type-annotated` slot in as a quiet sub-strip below the cards.

### 4. What's in v1.0 (the milestone moment)

This is the celebration section. **Visual treatment:** section background subtly lifts (`--surface` instead of `--bg`), with the Fraunces "1.0" numeral as a giant background watermark (8rem, 8% opacity, anchored bottom-right of the section).

**Layout:**

- Section eyebrow: `THE 1.0 RELEASE` (mono, amber)
- Section title: "Four headlines, dozens of fixes."
- Four marquee cards in a 2×2 grid (≥768px) / single column (<768px):
  1. **Streamable HTTP & SSE transports** — bearer-token auth, multi-arch Docker, `/healthz`. Mini code: a one-line `docker run` invocation.
  2. **Batch entry retrieval** — `get_zim_entries`, up to 50 per call. Mini code: a JSON request fetching 3 entries.
  3. **Per-entry MCP resources** — `zim://{name}/entry/{path}` with native MIME. Mini code: a resource URI example.
  4. **Resource subscriptions** — `notifications/resources/updated` when archives change. Mini code: a subscribe-then-notify sequence.
- Each card: title, 2-line description, mini code-snippet (3–5 lines, mono, syntax-highlighted via simple CSS classes — no Prism dependency), corner amber dot indicating "v1.0".
- Below the 2×2: a `<details>` collapsible — **"Also in 1.0 — polish, fixes, and scope cuts"** — containing the existing v1.0 details blocks (Smarter archive handling / Cleaner content extraction / Server hygiene / Streamlined scope / Review pass) verbatim from the current site.
- v0.9.0 release block stays below the v1.0 block (preserves current pattern of showing the prior release as context). Visually de-emphasized (smaller heading, `--text-secondary`).

### 5. Try it

3-step install with copy buttons.

**Step row** (3 cards horizontal at ≥768px):

1. **Install** — install code block with three tabs (`uv` / `Docker` / `From source`). Default = `uv`.
2. **Get a ZIM** — link to `browse.library.kiwix.org` with a one-liner `mkdir ~/zim-files && cd ~/zim-files`.
3. **Run it** — `uv run openzim-mcp ~/zim-files` with a callout: "or HTTP mode: `--transport streamable-http`".

**Below the steps:** "See it in action" — the existing usage tabs trimmed from 4 to 3:

- Search content
- Browse namespaces
- Subscribe (NEW — replaces "MCP Config" tab; the config snippet moves into Step 1 above)

Each tab shows a request + response pair, mono, no syntax highlighting beyond CSS color classes.

### 6. Deeper

Compact 6-cell links grid (3×2 at ≥768px). Each cell is title + one-line description + arrow link. No icons (a deliberate departure from the current icon-heavy doc cards — cleaner).

- API Reference → README#api-reference
- Deployment Guide → wiki Deployment-Guide
- Architecture Overview → wiki Architecture-Overview
- Configuration Guide → wiki Configuration-Guide
- Troubleshooting → wiki Troubleshooting-Guide
- Contributing → CONTRIBUTING.md

### 7. Footer

Refreshed but structurally similar to current. Three columns at ≥768px:

- Brand column: logo + wordmark, one-line tagline, MIT license + Python 3.12+ badges
- Resources column: GitHub · Releases · Issues · Wiki
- Community column: Model Context Protocol · OpenZIM · Kiwix · ZIM Library

Bottom strip (centered): "Made with care by Cameron Rye." Drop the beating-heart emoji icon — too SaaS-cute for the new brand. Add a small constellation mark (3 dots, no lines) inline in place of decorative flourish.

---

## Component inventory (CSS regions)

The single `styles.css` will be sectioned with these region fences (in order):

```
/* ============= TOKENS ============= */
/* ============= RESET ============= */
/* ============= BASE TYPOGRAPHY ============= */
/* ============= LAYOUT PRIMITIVES ============= */     /* container, grid utils, stack */
/* ============= NAV ============= */
/* ============= HERO ============= */
/* ============= CONSTELLATION ============= */         /* SVG illustration styles */
/* ============= WHAT-IS-THIS ============= */
/* ============= WHATS-IN-V1 ============= */
/* ============= TRY-IT ============= */
/* ============= DEEPER ============= */
/* ============= FOOTER ============= */
/* ============= UTILITIES ============= */              /* code-block, copy-btn, toast, etc */
/* ============= MOTION ============= */                 /* keyframes, reveal classes */
/* ============= RESPONSIVE ============= */             /* media queries — bottom of file, last word wins */
/* ============= REDUCED MOTION ============= */
```

Estimated final size: ~28KB minified (down from current 44KB) — the cuts come from removing Smart Retrieval / Security / Advanced Features / Developer Experience section styles.

---

## JavaScript components

Single `assets/script.js`, no dependencies. Modules (in load order):

1. **theme.js logic** — read `localStorage`, fall back to `prefers-color-scheme`, attach toggle handler. Default: dark. (Keep current pattern.)
2. **nav.js logic** — mobile hamburger, scroll-shadow on nav (border appears when scrolled >0px). **Drop:** scroll-progress bar.
3. **constellation.js logic** — given an inline `<svg id="hero-constellation">`, animate lines via `stroke-dasharray` + `stroke-dashoffset` interpolation in `requestAnimationFrame`, then fade dots in. Pulse the top dot via CSS `@keyframes`. Skip animation if `prefers-reduced-motion`. ~80 lines.
4. **reveal.js logic** — `IntersectionObserver` adds `.revealed` class to `[data-reveal]` elements at 0.15 threshold. ~25 lines.
5. **tabs.js logic** — generic tab handler for both Install (`uv`/`Docker`/`From source`) and Try-it (`Search`/`Browse`/`Subscribe`). Reuse current tab pattern.
6. **copy.js logic** — copy-to-clipboard with toast, reuse current pattern.
7. **version.js logic** — fetch `/manifest.json` or hard-code `1.0.0`; populate `#version-display` and the install one-liner version pin if present. (Keep current `version-display` ID for compatibility with `release-please-config.json` extra-files annotation if applicable.)

---

## Content changes

### Copy rewrites

- Hero H1 changes from **"Transform Static ZIM Archives into Dynamic Knowledge Engines"** to **"Knowledge that works offline."** (shorter, more direct, period included for finality)
- Hero description tightened from 3 sentences to 1, drops the "Simple/Advanced mode" line (covered later in Try-it)
- "Why LLMs Love OpenZIM MCP" section title → cut entirely (the new "What is this" replaces it)
- All emoji icons in section headings (🧠, 🔒, ⚡, 🛠) → cut. The constellation/star motif is the only iconography.

### Cuts (content removed from landing page entirely)

- Smart Retrieval System section — moved to README; not landing-page material
- Security feature grid (4 cards + stat strip) — collapsed to one stat sub-strip on "What is this"
- Advanced Features section (Health/Caching/Architecture cards) — cut entirely; covered by README
- Developer Experience section (Release/Makefile/Testing/Quality cards + workflow code) — cut entirely; covered by CONTRIBUTING.md
- Documentation grid → simplified to "Deeper" (6 cells, no icons, 1-line descriptions)
- Beating-heart emoji in footer
- "NEW Feature Banner" strip above hero
- The hero MCP-config code window
- Scroll progress bar

### SEO / metadata fixes (alongside redesign)

- `<script type="application/ld+json">` `softwareVersion` field: `0.8.2` → `1.0.0`
- `<meta property="article:modified_time">` updates to current redesign date
- New OG image at `assets/og-image.svg` rendering the constellation + "OpenZIM MCP 1.0" wordmark
- `<title>` updated: "OpenZIM MCP — Knowledge that works offline" (mirrors new hero)
- `<meta name="description">` mirrors the new hero sub-headline
- Twitter card image updates to new OG
- `humans.txt` updated: bump release line to 1.0.0
- `sitemap.xml`: bump `lastmod`
- `llm.txt`: hero H1 line + tagline updated to match new copy

---

## Accessibility

- Skip-to-main-content link preserved (current pattern)
- Color contrast: amber `#FFD24A` on ink `#0B0F1A` = 11.6:1 (AAA). Paper on ink = 14.7:1 (AAA). Secondary text `#7A8499` on ink = 4.9:1 (AA for body). Verified targets, no contrast regressions vs current site.
- All interactive elements (buttons, links, theme toggle, copy buttons, tab buttons, hamburger) keyboard-reachable with visible focus rings using `--signal` outline at 2px offset 2px
- Constellation SVG has `role="img"` and `aria-label="Decorative constellation illustration"`; static fallback if `prefers-reduced-motion`
- Section headings remain `<h2>` (not styled-up `<div>`s); single `<h1>` (hero only)
- Tab pattern uses `role="tablist"` / `role="tab"` / `role="tabpanel"` with `aria-selected` and arrow-key navigation

---

## Out of scope

The following are explicitly **not** part of this redesign:

- Build pipeline / SSG migration (no Astro, 11ty, Vite, etc.)
- Search functionality on the site itself
- Interactive in-browser MCP playground (tempting but adds significant scope; defer to v1.1 if useful)
- Blog / changelog page (the "What's in v1.0" section + linked CHANGELOG.md is sufficient)
- Newsletter / subscription form
- Analytics integration (current site has none; this redesign keeps it that way)
- A separate documentation site (docs continue to live in README + wiki)
- Internationalization
- Animated background patterns or scroll-jacking effects

---

## Files touched

| File | Change |
|---|---|
| [website/index.html](../../../website/index.html) | Restructure to 5 sections; new hero markup with constellation SVG; rewrite copy per spec; update `<head>` metadata |
| [website/assets/styles.css](../../../website/assets/styles.css) | Full rewrite to new tokens / regions / scale; ~28KB target |
| [website/assets/script.js](../../../website/assets/script.js) | Add constellation animator + reveal observer; remove scroll-progress; otherwise preserve existing handlers |
| [website/assets/logo.svg](../../../website/assets/logo.svg) | Replace with constellation mark (32px nav variant) |
| [website/assets/favicon.svg](../../../website/assets/favicon.svg) | Replace with 16px favicon variant (3 dots) |
| [website/assets/favicon.ico](../../../website/assets/favicon.ico) | Optional — current file is a 1-byte stub. Either generate a proper multi-size .ico (16/32/48px) from the constellation mark, or leave the stub in place since `favicon.svg` is the primary reference. Not asserted by `validate.py`. |
| [website/assets/og-image.svg](../../../website/assets/og-image.svg) | New constellation + wordmark composition |
| [website/assets/brain-icon.svg](../../../website/assets/brain-icon.svg) | Delete (no longer referenced) |
| [website/assets/shield-icon.svg](../../../website/assets/shield-icon.svg) | Delete (Security section gone) |
| [website/assets/search-icon.svg](../../../website/assets/search-icon.svg) | Delete (no longer used) |
| [website/humans.txt](../../../website/humans.txt) | Bump release to 1.0.0 |
| [website/sitemap.xml](../../../website/sitemap.xml) | Bump lastmod |
| [website/llm.txt](../../../website/llm.txt) | Update hero H1 + tagline lines to match new copy |
| [website/validate.py](../../../website/validate.py) | No changes needed — its `required_files` list (`styles.css`, `script.js`, `favicon.svg`, `og-image.svg`, `robots.txt`, `sitemap.xml`, `humans.txt`, `.well-known/*.txt`) all remain. Verified during spec review. |

---

## Acceptance criteria

The redesign is complete when:

1. The site renders identically across Chrome, Firefox, Safari (desktop) at 1440px / 1024px / 768px / 375px breakpoints
2. Lighthouse scores: Performance ≥95, Accessibility ≥95, Best Practices ≥95, SEO ≥95 on the redesigned page
3. Constellation hero animates on first load and is statically drawn under `prefers-reduced-motion`
4. Theme toggle persists across reloads via `localStorage` and respects `prefers-color-scheme` on first visit (default: dark)
5. All copy buttons, tabs, hamburger nav, smooth-scroll anchor links work correctly
6. Schema.org `softwareVersion` reads `1.0.0`; OG image renders correctly when shared on Twitter/Mastodon previews
7. Existing site URL fragments still resolve to a sensible section after the IA collapse. Concrete redirect map: `#features` and `#smart-retrieval` and `#advanced-features` and `#developer-experience` → all point to `#what-is-this` (the new explainer); `#security` → `#what-is-this` (the production-stat strip lives there); `#whats-new` → `#v1` (the milestone section); `#installation` and `#usage` → `#try-it`; `#documentation` → `#deeper`. Implement as either empty `<span id="old-anchor">` placeholder elements at the top of each new section, or via a small JS handler that rewrites legacy hashes on load. Either is acceptable.
8. `validate.py` (if it asserts asset presence) passes against the new asset list
9. CSS file size ≤ 32KB, JS file size ≤ 12KB (both unminified, no build step)
10. No JS dependencies introduced; no build step required to view the site locally
