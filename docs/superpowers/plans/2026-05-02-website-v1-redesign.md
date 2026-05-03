# Website v1.0.0 Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reskin and restructure the OpenZIM MCP marketing website to celebrate the v1.0.0 milestone — new constellation logo, amber-on-ink palette, 5-section information architecture, animated hero illustration — while staying vanilla HTML/CSS/JS with zero JS dependencies.

**Architecture:** In-place rewrite of `website/`. Three primary files (`index.html`, `assets/styles.css`, `assets/script.js`) get rebuilt; six small asset files (3 SVGs created, 3 SVGs deleted) replace the old logo set; three text files (`humans.txt`, `sitemap.xml`, `llm.txt`) get version bumps. No build pipeline, no JS dependencies, no migration to a static-site generator. Each task lands as one commit.

**Tech Stack:** HTML5, modern CSS (custom properties, `:has()` not used to keep Safari support broad, `IntersectionObserver`, `prefers-reduced-motion`), vanilla JavaScript (`requestAnimationFrame`, no libraries), inline SVG. Verification via `python website/validate.py`, browser inspection at 1440/1024/768/375px breakpoints, and Lighthouse run for the acceptance criteria.

**Spec:** [docs/superpowers/specs/2026-05-02-website-v1-redesign-design.md](../specs/2026-05-02-website-v1-redesign-design.md)

**Prerequisites:** None. The website is a self-contained subtree.

**Worktree note:** This plan rewrites the live website. Recommended to execute in a dedicated git worktree (e.g., `git worktree add ../openzim-mcp-website-redesign HEAD`) so the in-progress redesign can be reviewed in a browser without affecting the deployed `main` branch. The executing-plans / subagent-driven-development skill will handle worktree setup if invoked.

**Verification baseline:** Before starting Task 1, the engineer should run `python website/validate.py` and capture the current "All validations passed" output as the baseline. After every task that touches `index.html`, the same command must still pass.

---

## Task 1: New constellation logo SVG (32px nav variant)

Create the canonical 32px nav-scale logo. The mark is 5 dots in an asymmetric kite-plus-base arrangement, single color, soft-cornered square boundary. This file replaces the existing gradient brain icon.

**Files:**

- Modify: `website/assets/logo.svg`

- [ ] **Step 1: Replace logo.svg with the new constellation mark**

Use the Write tool to overwrite `website/assets/logo.svg` with this content:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img" aria-label="OpenZIM MCP constellation logo">
  <!-- Soft square boundary -->
  <rect x="1" y="1" width="30" height="30" rx="4" fill="none" stroke="currentColor" stroke-width="0" />
  <!-- Constellation: 5-dot kite-plus-base, tilted ~8° clockwise around (16,16) -->
  <g transform="rotate(8 16 16)" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
    <!-- Lines: top->upper-left, top->upper-right, upper-left->lower-left, upper-right->lower-right, lower-left->lower-right -->
    <line x1="16" y1="6"  x2="7"  y2="13" />
    <line x1="16" y1="6"  x2="25" y2="13" />
    <line x1="7"  y1="13" x2="9"  y2="25" />
    <line x1="25" y1="13" x2="23" y2="25" />
    <line x1="9"  y1="25" x2="23" y2="25" />
  </g>
  <g transform="rotate(8 16 16)" fill="none" stroke="currentColor" stroke-width="1.5">
    <!-- Stroked dots at the 5 positions -->
    <circle cx="16" cy="6"  r="2" />
    <circle cx="7"  cy="13" r="2" />
    <circle cx="25" cy="13" r="2" />
    <circle cx="9"  cy="25" r="2" />
    <circle cx="23" cy="25" r="2" />
  </g>
</svg>
```

The SVG uses `currentColor`, so wherever it's embedded the parent element's `color` value drives the stroke. The 8° rotation lives inside `transform`s so the bounding box stays at 0,0,32,32.

- [ ] **Step 2: Verify visually**

Open the file in a browser:

```bash
open website/assets/logo.svg
```

Expected: 5 stroked dots connected by thin lines forming a tilted kite-with-base shape, rendered in the browser's default text color (usually black). The mark fills most of the 32px viewBox without touching its edges.

- [ ] **Step 3: Commit**

```bash
git add website/assets/logo.svg
git commit -m "design(website): replace logo with constellation mark"
```

---

## Task 2: New favicon SVG (16px variant — 3 dots only)

At favicon scale, the lines and 5-dot count don't read clearly. The favicon is a 3-dot reduction.

**Files:**

- Modify: `website/assets/favicon.svg`

- [ ] **Step 1: Replace favicon.svg with the 3-dot favicon**

Use the Write tool to overwrite `website/assets/favicon.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" role="img" aria-label="OpenZIM MCP favicon">
  <rect x="0" y="0" width="16" height="16" rx="3" fill="#0B0F1A" />
  <g fill="#FFD24A">
    <circle cx="8"  cy="3" r="1.5" />
    <circle cx="3"  cy="11" r="1.5" />
    <circle cx="13" cy="11" r="1.5" />
  </g>
</svg>
```

Filled dots (not stroked) since the 16px scale needs visual mass. Background is the brand `--ink` color directly so the favicon has identity even on browser tabs that strip CSS context. Amber dots provide brand recognition.

- [ ] **Step 2: Verify visually**

```bash
open website/assets/favicon.svg
```

Expected: dark navy square with 3 amber filled circles forming a triangle.

- [ ] **Step 3: Commit**

```bash
git add website/assets/favicon.svg
git commit -m "design(website): replace favicon with 3-dot constellation reduction"
```

---

## Task 3: New OG image SVG (1200×630 social card)

The Open Graph / Twitter card image rendered when the site URL is shared. Constellation + wordmark + version.

**Files:**

- Modify: `website/assets/og-image.svg`

- [ ] **Step 1: Replace og-image.svg with the new social card**

Use the Write tool to overwrite `website/assets/og-image.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" role="img" aria-label="OpenZIM MCP — Knowledge that works offline">
  <!-- Background: ink, with a soft radial glow centered on the top-center constellation dot -->
  <defs>
    <radialGradient id="glow" cx="50%" cy="38%" r="50%">
      <stop offset="0%"   stop-color="#FFD24A" stop-opacity="0.18" />
      <stop offset="60%"  stop-color="#FFD24A" stop-opacity="0.04" />
      <stop offset="100%" stop-color="#FFD24A" stop-opacity="0" />
    </radialGradient>
  </defs>
  <rect width="1200" height="630" fill="#0B0F1A" />
  <rect width="1200" height="630" fill="url(#glow)" />

  <!-- Constellation, scaled and centered horizontally, sitting in the upper third -->
  <g transform="translate(600 240) scale(8)" fill="none" stroke="#F5F1E8" stroke-width="1.2" stroke-linecap="round">
    <line x1="0"   y1="-20" x2="-18" y2="-6" />
    <line x1="0"   y1="-20" x2="18"  y2="-6" />
    <line x1="-18" y1="-6"  x2="-14" y2="18" />
    <line x1="18"  y1="-6"  x2="14"  y2="18" />
    <line x1="-14" y1="18"  x2="14"  y2="18" />
  </g>
  <g transform="translate(600 240) scale(8)" fill="#F5F1E8" stroke="none">
    <circle cx="-18" cy="-6"  r="2.4" />
    <circle cx="18"  cy="-6"  r="2.4" />
    <circle cx="-14" cy="18"  r="2.4" />
    <circle cx="14"  cy="18"  r="2.4" />
  </g>
  <!-- Top dot is amber -->
  <g transform="translate(600 240) scale(8)" fill="#FFD24A" stroke="none">
    <circle cx="0" cy="-20" r="3" />
  </g>

  <!-- Wordmark and tagline, centered -->
  <text x="600" y="500" font-family="Geist, Inter, system-ui, sans-serif" font-size="68" font-weight="600" fill="#F5F1E8" text-anchor="middle" letter-spacing="-1">OpenZIM MCP</text>
  <text x="600" y="552" font-family="JetBrains Mono, ui-monospace, monospace" font-size="22" fill="#FFD24A" text-anchor="middle" letter-spacing="2">MCP SERVER · v1.0.0</text>
  <text x="600" y="590" font-family="Geist, Inter, system-ui, sans-serif" font-size="20" fill="#7A8499" text-anchor="middle">Knowledge that works offline.</text>
</svg>
```

Note: SVG OG images don't render in Twitter/Slack previews historically — those platforms want PNG/JPG. The spec accepts SVG because the existing site already used SVG OG. If the engineer has access to an SVG-to-PNG renderer (rsvg-convert, Inkscape, librsvg, or `npx svgexport`), generating a 1200×630 PNG fallback at `og-image.png` and updating the meta tag is a worthwhile bonus. Not required for this task.

- [ ] **Step 2: Verify visually**

```bash
open website/assets/og-image.svg
```

Expected: dark navy 1200×630 card with the white-and-amber constellation centered in the upper portion, "OpenZIM MCP" wordmark, "MCP SERVER · v1.0.0" mono caption, and the tagline below.

- [ ] **Step 3: Commit**

```bash
git add website/assets/og-image.svg
git commit -m "design(website): replace OG image with constellation + v1.0 wordmark"
```

---

## Task 4: Bootstrap new styles.css with tokens, reset, and base typography

Replace the entire 44KB `styles.css` with a fresh foundation. After this task the site will look broken in the browser (no section styles yet) — that's expected. Subsequent tasks add section styles incrementally.

**Files:**

- Modify: `website/assets/styles.css`

- [ ] **Step 1: Write the new styles.css foundation**

Use the Write tool to overwrite `website/assets/styles.css`:

```css
/* ============= TOKENS ============= */
:root {
  /* Brand */
  --ink: #0B0F1A;
  --ink-elev: #131826;
  --paper: #F5F1E8;
  --paper-elev: #FFFFFF;
  --signal: #FFD24A;
  --signal-dim: #B8923A;
  --secondary: #5B8DEF;
  --muted: #7A8499;
  --muted-light: #5B6478;
  --border: #1F2533;
  --border-light: #D8D2C2;
  --success: #22D3A8;
  --danger: #E85D3C;

  /* Semantic — dark default */
  --bg: var(--ink);
  --surface: var(--ink-elev);
  --text: var(--paper);
  --text-secondary: var(--muted);
  --border-color: var(--border);

  /* Typography */
  --font-display: 'Fraunces', Georgia, serif;
  --font-sans: 'Geist', 'Inter', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;

  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-lg: 1.125rem;
  --text-xl: 1.375rem;
  --text-2xl: 1.75rem;
  --text-3xl: 2.25rem;
  --text-4xl: 3rem;
  --text-5xl: 4rem;
  --text-6xl: 5.5rem;
  --text-display: 8rem;

  --weight-regular: 400;
  --weight-medium: 500;
  --weight-semibold: 600;

  /* Spacing (4px base) */
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.25rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --space-10: 2.5rem;
  --space-12: 3rem;
  --space-16: 4rem;
  --space-20: 5rem;
  --space-24: 6rem;

  /* Layout */
  --container-max: 1200px;
  --container-narrow: 960px;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;

  /* Motion */
  --ease-out: cubic-bezier(0.2, 0.8, 0.3, 1);
  --dur-fast: 120ms;
  --dur-base: 200ms;
  --dur-slow: 600ms;
}

[data-theme="light"] {
  --bg: var(--paper);
  --surface: var(--paper-elev);
  --text: var(--ink);
  --text-secondary: var(--muted-light);
  --border-color: var(--border-light);
}

/* ============= RESET ============= */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }
body {
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: 1.6;
  color: var(--text);
  background: var(--bg);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  transition: background var(--dur-base) ease, color var(--dur-base) ease;
}
img, svg { display: block; max-width: 100%; }
a { color: var(--secondary); text-decoration: none; transition: color var(--dur-fast) ease; }
a:hover { color: var(--signal); }
button { font: inherit; color: inherit; background: none; border: none; cursor: pointer; }
ul, ol { list-style: none; }
code, pre { font-family: var(--font-mono); }

/* ============= BASE TYPOGRAPHY ============= */
h1, h2, h3, h4 { font-weight: var(--weight-semibold); line-height: 1.15; letter-spacing: -0.01em; }
h1 { font-size: clamp(2.5rem, 5vw + 1rem, var(--text-6xl)); letter-spacing: -0.025em; }
h2 { font-size: clamp(1.75rem, 3vw + 0.75rem, var(--text-4xl)); letter-spacing: -0.02em; }
h3 { font-size: var(--text-2xl); }
h4 { font-size: var(--text-xl); }
p { color: var(--text-secondary); }

.eyebrow {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--signal);
  text-transform: uppercase;
  letter-spacing: 0.15em;
  display: inline-block;
  margin-bottom: var(--space-4);
}

/* ============= LAYOUT PRIMITIVES ============= */
.container { max-width: var(--container-max); margin-inline: auto; padding-inline: var(--space-6); }
.container--narrow { max-width: var(--container-narrow); }
.section { padding-block: var(--space-24); }
.section--surface { background: var(--surface); }
.skip-link {
  position: absolute; top: -40px; left: 0; background: var(--signal); color: var(--ink);
  padding: var(--space-2) var(--space-4); z-index: 100; border-radius: 0 0 var(--radius-md) 0;
}
.skip-link:focus { top: 0; }

/* ============= UTILITIES ============= */
.btn {
  display: inline-flex; align-items: center; gap: var(--space-2);
  padding: var(--space-3) var(--space-6); border-radius: var(--radius-md);
  font-weight: var(--weight-medium); font-size: var(--text-base);
  transition: background var(--dur-fast) ease, transform var(--dur-fast) ease, color var(--dur-fast) ease;
}
.btn--primary { background: var(--signal); color: var(--ink); }
.btn--primary:hover { background: #FFE07A; transform: translateY(-1px); color: var(--ink); }
.btn--secondary {
  background: transparent; color: var(--text);
  border: 1px solid var(--border-color);
}
.btn--secondary:hover { border-color: var(--signal); color: var(--signal); }

:focus-visible {
  outline: 2px solid var(--signal);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}

/* ============= MOTION ============= */
[data-reveal] {
  opacity: 0;
  transform: translateY(8px);
  transition: opacity var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
}
[data-reveal].revealed { opacity: 1; transform: none; }

/* ============= REDUCED MOTION ============= */
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  [data-reveal] { opacity: 1; transform: none; }
}
```

This is the foundation only — section-specific styles get appended in later tasks under their region fences.

- [ ] **Step 2: Verify the file parses**

```bash
node -e "const fs = require('fs'); const css = fs.readFileSync('website/assets/styles.css', 'utf8'); console.log('OK', css.length, 'chars');"
```

Expected: `OK <number> chars`. If `node` isn't installed, skip — any CSS error will surface visually in the next browser-load step.

Open `website/index.html` in a browser. Expected: the page is broken/unstyled — old IDs reference styles that no longer exist. The body should at least have the dark background applied.

- [ ] **Step 3: Commit**

```bash
git add website/assets/styles.css
git commit -m "design(website): replace styles.css with v1.0 token foundation"
```

---

## Task 5: Bootstrap new index.html — head, nav, and main shell

Replace the existing `index.html` with the new shell. Five empty `<section>` placeholders go in this task; sections fill in over Tasks 6–13.

**Files:**

- Modify: `website/index.html`

- [ ] **Step 1: Replace index.html with the new shell**

Use the Write tool to overwrite `website/index.html`:

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OpenZIM MCP — Knowledge that works offline</title>
  <meta name="description" content="OpenZIM MCP gives any AI model structured, secure access to ZIM archives — Wikipedia, MedlinePlus, the Stack Exchange dumps — without an internet connection.">
  <meta name="keywords" content="OpenZIM, MCP, Model Context Protocol, AI, LLM, knowledge base, offline, ZIM files, Wikipedia, Python, open source">
  <meta name="author" content="Cameron Rye">

  <link rel="canonical" href="https://cameronrye.github.io/openzim-mcp/">
  <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1">
  <meta name="googlebot" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1">
  <meta name="bingbot" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1">
  <meta name="theme-color" content="#0B0F1A">
  <meta name="color-scheme" content="dark light">

  <!-- Open Graph -->
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="OpenZIM MCP">
  <meta property="og:url" content="https://cameronrye.github.io/openzim-mcp/">
  <meta property="og:title" content="OpenZIM MCP — Knowledge that works offline">
  <meta property="og:description" content="MCP server for offline ZIM-archive access. Streamable HTTP, batch retrieval, per-entry resources, subscriptions. v1.0.0.">
  <meta property="og:image" content="https://cameronrye.github.io/openzim-mcp/assets/og-image.svg">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="OpenZIM MCP 1.0 — Knowledge that works offline">
  <meta property="og:locale" content="en_US">
  <meta property="article:author" content="Cameron Rye">
  <meta property="article:modified_time" content="2026-05-02T00:00:00Z">

  <!-- Twitter -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:site" content="@cameronrye">
  <meta name="twitter:creator" content="@cameronrye">
  <meta name="twitter:url" content="https://cameronrye.github.io/openzim-mcp/">
  <meta name="twitter:title" content="OpenZIM MCP — Knowledge that works offline">
  <meta name="twitter:description" content="MCP server for offline ZIM-archive access. Streamable HTTP, batch retrieval, per-entry resources, subscriptions. v1.0.0.">
  <meta name="twitter:image" content="https://cameronrye.github.io/openzim-mcp/assets/og-image.svg">
  <meta name="twitter:image:alt" content="OpenZIM MCP 1.0 — Knowledge that works offline">

  <link rel="icon" type="image/svg+xml" href="assets/favicon.svg">
  <link rel="icon" type="image/x-icon" href="assets/favicon.ico">
  <link rel="author" type="text/plain" href="humans.txt">

  <!-- Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=JetBrains+Mono:wght@400;500&family=Fraunces:wght@600&display=swap" rel="stylesheet">

  <link rel="stylesheet" href="assets/styles.css">

  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    "name": "OpenZIM MCP",
    "alternateName": "OpenZIM MCP Server",
    "description": "A modern, secure MCP server that enables AI models to access and search ZIM format knowledge bases offline with intelligent, structured access patterns",
    "url": "https://cameronrye.github.io/openzim-mcp/",
    "softwareVersion": "1.0.0",
    "releaseNotes": "https://github.com/cameronrye/openzim-mcp/blob/main/CHANGELOG.md",
    "applicationCategory": "DeveloperApplication",
    "applicationSubCategory": "AI Tools",
    "operatingSystem": "Linux, macOS, Windows",
    "programmingLanguage": { "@type": "ComputerLanguage", "name": "Python", "version": "3.12+" },
    "license": "https://opensource.org/licenses/MIT",
    "downloadUrl": "https://pypi.org/project/openzim-mcp/",
    "installUrl": "https://pypi.org/project/openzim-mcp/",
    "codeRepository": "https://github.com/cameronrye/openzim-mcp",
    "softwareHelp": "https://github.com/cameronrye/openzim-mcp#readme",
    "author": { "@type": "Person", "name": "Cameron Rye", "url": "https://rye.dev" },
    "creator": { "@type": "Person", "name": "Cameron Rye", "url": "https://rye.dev" },
    "maintainer": { "@type": "Person", "name": "Cameron Rye", "url": "https://rye.dev" },
    "offers": { "@type": "Offer", "price": "0", "priceCurrency": "USD" }
  }
  </script>
  <script type="application/ld+json">
  { "@context": "https://schema.org", "@type": "Organization", "name": "OpenZIM MCP",
    "url": "https://cameronrye.github.io/openzim-mcp/",
    "logo": "https://cameronrye.github.io/openzim-mcp/assets/logo.svg",
    "founder": { "@type": "Person", "name": "Cameron Rye", "url": "https://rye.dev" } }
  </script>
  <script type="application/ld+json">
  { "@context": "https://schema.org", "@type": "WebSite", "name": "OpenZIM MCP",
    "url": "https://cameronrye.github.io/openzim-mcp/",
    "description": "Knowledge that works offline." }
  </script>
</head>
<body>
  <a href="#main" class="skip-link">Skip to main content</a>

  <header class="nav" id="nav">
    <div class="container nav__inner">
      <a href="#hero" class="nav__brand" aria-label="OpenZIM MCP home">
        <svg class="nav__logo" width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
          <use href="assets/logo.svg#root" />
        </svg>
        <span class="nav__wordmark">OpenZIM&nbsp;MCP</span>
      </a>
      <nav class="nav__menu" id="nav-menu" aria-label="Primary">
        <a href="#what" class="nav__link">What is this</a>
        <a href="#v1" class="nav__link">v1.0</a>
        <a href="#try" class="nav__link">Try it</a>
        <a href="#deeper" class="nav__link">Deeper</a>
        <a href="https://github.com/cameronrye/openzim-mcp" class="nav__link" target="_blank" rel="noopener">GitHub ↗</a>
        <button class="nav__theme" id="theme-toggle" aria-label="Toggle theme" type="button">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </button>
      </nav>
      <button class="nav__toggle" id="nav-toggle" aria-label="Open menu" aria-expanded="false" type="button">
        <span></span><span></span><span></span>
      </button>
    </div>
  </header>

  <main id="main">
    <!-- Anchor aliases for legacy URLs (filled out in Task 15) -->

    <section id="hero" class="hero">
      <!-- Filled in Task 6 -->
    </section>

    <section id="what" class="section section--surface what">
      <!-- Filled in Task 9 -->
    </section>

    <section id="v1" class="section v1">
      <!-- Filled in Task 10 -->
    </section>

    <section id="try" class="section section--surface try">
      <!-- Filled in Task 11 -->
    </section>

    <section id="deeper" class="section deeper">
      <!-- Filled in Task 12 -->
    </section>
  </main>

  <footer class="footer" id="footer">
    <!-- Filled in Task 13 -->
  </footer>

  <script src="assets/script.js" defer></script>
</body>
</html>
```

The `<use href="assets/logo.svg#root" />` reference assumes the logo SVG has an `id="root"` on its outer element. Since the logo file uses `<svg>` as the root with no id, this will fall back gracefully. The nav SVG will be replaced with an inline copy in Task 14 to avoid the `<use>` external-reference issue (Safari limitations). For now this empty render is acceptable as a placeholder.

Now add nav styles to the CSS. Use the Edit tool to append a NAV region to `website/assets/styles.css`. Find the end of the `/* ============= UTILITIES ============= */` block (after the `:focus-visible` rule) and insert before `/* ============= MOTION ============= */`:

`old_string`:

```
:focus-visible {
  outline: 2px solid var(--signal);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}

/* ============= MOTION ============= */
```

`new_string`:

```
:focus-visible {
  outline: 2px solid var(--signal);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}

/* ============= NAV ============= */
.nav {
  position: sticky; top: 0; z-index: 50;
  background: color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter: saturate(180%) blur(12px);
  -webkit-backdrop-filter: saturate(180%) blur(12px);
  border-bottom: 1px solid transparent;
  transition: border-color var(--dur-base) ease;
}
.nav.is-scrolled { border-bottom-color: var(--border-color); }
.nav__inner {
  display: flex; align-items: center; justify-content: space-between;
  height: 64px;
}
.nav__brand {
  display: inline-flex; align-items: center; gap: var(--space-3);
  color: var(--text); font-weight: var(--weight-semibold);
  font-size: var(--text-base); letter-spacing: -0.01em;
}
.nav__brand:hover { color: var(--signal); }
.nav__logo { color: var(--text); }
.nav__menu {
  display: flex; align-items: center; gap: var(--space-6);
}
.nav__link {
  color: var(--text-secondary); font-size: var(--text-sm);
  transition: color var(--dur-fast) ease;
}
.nav__link:hover { color: var(--text); }
.nav__theme {
  display: inline-flex; align-items: center; justify-content: center;
  width: 36px; height: 36px; border-radius: var(--radius-md);
  color: var(--text-secondary);
  transition: color var(--dur-fast) ease, background var(--dur-fast) ease;
}
.nav__theme:hover { color: var(--signal); background: var(--surface); }
.nav__toggle {
  display: none;
  flex-direction: column; gap: 4px;
  width: 32px; height: 32px;
  align-items: center; justify-content: center;
}
.nav__toggle span { display: block; width: 20px; height: 2px; background: var(--text); border-radius: 1px; }

@media (max-width: 768px) {
  .nav__menu { display: none; }
  .nav__toggle { display: flex; }
  .nav.is-open .nav__menu {
    display: flex; flex-direction: column; gap: var(--space-4);
    position: absolute; top: 64px; left: 0; right: 0;
    background: var(--surface);
    padding: var(--space-6); border-bottom: 1px solid var(--border-color);
  }
}

```

- [ ] **Step 2: Inline the logo SVG in nav (replace `<use>` with literal SVG)**

The `<use href="assets/logo.svg#root">` pattern doesn't work cleanly without an `id` on the source SVG and has Safari quirks. Replace it with an inline copy.

Use the Edit tool to update `website/index.html`:

`old_string`:

```
      <a href="#hero" class="nav__brand" aria-label="OpenZIM MCP home">
        <svg class="nav__logo" width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
          <use href="assets/logo.svg#root" />
        </svg>
        <span class="nav__wordmark">OpenZIM&nbsp;MCP</span>
      </a>
```

`new_string`:

```
      <a href="#hero" class="nav__brand" aria-label="OpenZIM MCP home">
        <svg class="nav__logo" width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
          <g transform="rotate(8 16 16)" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
            <line x1="16" y1="6" x2="7" y2="13"/>
            <line x1="16" y1="6" x2="25" y2="13"/>
            <line x1="7" y1="13" x2="9" y2="25"/>
            <line x1="25" y1="13" x2="23" y2="25"/>
            <line x1="9" y1="25" x2="23" y2="25"/>
          </g>
          <g transform="rotate(8 16 16)" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="16" cy="6" r="2"/>
            <circle cx="7" cy="13" r="2"/>
            <circle cx="25" cy="13" r="2"/>
            <circle cx="9" cy="25" r="2"/>
            <circle cx="23" cy="25" r="2"/>
          </g>
        </svg>
        <span class="nav__wordmark">OpenZIM&nbsp;MCP</span>
      </a>
```

- [ ] **Step 3: Verify the page loads with nav visible**

```bash
open website/index.html
```

Expected: dark page, top nav visible with constellation logo, "OpenZIM MCP" wordmark, four nav links + GitHub + theme toggle. Body is empty below the nav. Theme toggle and hamburger may not respond yet (handlers come in Task 14).

Run the validator:

```bash
python website/validate.py
```

Expected: All meta-tag checks pass. The script may flag "Missing meta tag" if any required tag was lost in the rewrite. Address any failures by adding missing tags before committing.

- [ ] **Step 4: Commit**

```bash
git add website/index.html website/assets/styles.css
git commit -m "design(website): bootstrap new shell with v1.0 nav and section scaffolding"
```

---

## Task 6: Hero section — markup and styles (without constellation animation)

Build the hero copy, CTAs, install one-liner, and stat strip. The constellation illustration goes in as a static SVG in this task; animation comes in Task 8.

**Files:**

- Modify: `website/index.html`
- Modify: `website/assets/styles.css`

- [ ] **Step 1: Fill in the hero section markup**

Use the Edit tool on `website/index.html`:

`old_string`:

```
    <section id="hero" class="hero">
      <!-- Filled in Task 6 -->
    </section>
```

`new_string`:

```
    <section id="hero" class="hero">
      <div class="container hero__inner">
        <div class="hero__content">
          <span class="eyebrow">MCP&nbsp;SERVER · v1.0.0</span>
          <h1 class="hero__title">Knowledge that works offline.</h1>
          <p class="hero__lead">
            OpenZIM MCP gives any AI model structured, secure access to ZIM archives —
            Wikipedia, MedlinePlus, the Stack Exchange dumps — without an internet connection.
          </p>
          <div class="hero__ctas">
            <a href="#try" class="btn btn--primary">Get started <span aria-hidden="true">→</span></a>
            <a href="https://github.com/cameronrye/openzim-mcp" class="btn btn--secondary" target="_blank" rel="noopener">
              View on GitHub <span aria-hidden="true">↗</span>
            </a>
          </div>
          <div class="hero__install">
            <code class="hero__install-cmd" id="hero-install">uv tool install openzim-mcp</code>
            <button class="hero__install-copy copy-btn" data-copy-target="#hero-install" aria-label="Copy install command">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <rect x="8" y="2" width="8" height="4" rx="1"/>
                <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>
              </svg>
            </button>
          </div>
          <ul class="hero__stats">
            <li><span class="hero__stat-num" id="version-display">v1.0.0</span><span class="hero__stat-label">Latest release</span></li>
            <li><span class="hero__stat-num">21</span><span class="hero__stat-label">Tools available</span></li>
            <li><span class="hero__stat-num">80%+</span><span class="hero__stat-label">Test coverage</span></li>
            <li><span class="hero__stat-num">MIT</span><span class="hero__stat-label">License</span></li>
          </ul>
        </div>
        <div class="hero__visual" aria-hidden="true">
          <svg id="hero-constellation" class="constellation" viewBox="0 0 480 480" role="img" aria-label="Decorative constellation illustration">
            <defs>
              <radialGradient id="hero-glow" cx="50%" cy="22%" r="55%">
                <stop offset="0%" stop-color="#FFD24A" stop-opacity="0.25"/>
                <stop offset="100%" stop-color="#FFD24A" stop-opacity="0"/>
              </radialGradient>
            </defs>
            <rect width="480" height="480" fill="url(#hero-glow)"/>
            <g transform="translate(240 240) rotate(8)" fill="none" stroke="var(--text)" stroke-width="1.4" stroke-linecap="round">
              <line class="constellation__line" data-i="0" x1="0"    y1="-160" x2="-130" y2="-40"/>
              <line class="constellation__line" data-i="1" x1="0"    y1="-160" x2="130"  y2="-40"/>
              <line class="constellation__line" data-i="2" x1="-130" y1="-40"  x2="-90"  y2="140"/>
              <line class="constellation__line" data-i="3" x1="130"  y1="-40"  x2="90"   y2="140"/>
              <line class="constellation__line" data-i="4" x1="-90"  y1="140"  x2="90"   y2="140"/>
            </g>
            <g transform="translate(240 240) rotate(8)" stroke="none">
              <circle class="constellation__dot" data-i="0" cx="-130" cy="-40" r="6" fill="var(--text)"/>
              <circle class="constellation__dot" data-i="1" cx="130"  cy="-40" r="6" fill="var(--text)"/>
              <circle class="constellation__dot" data-i="2" cx="-90"  cy="140" r="6" fill="var(--text)"/>
              <circle class="constellation__dot" data-i="3" cx="90"   cy="140" r="6" fill="var(--text)"/>
              <circle class="constellation__dot constellation__dot--bright" data-i="4" cx="0" cy="-160" r="8" fill="#FFD24A"/>
            </g>
          </svg>
        </div>
      </div>
    </section>
```

- [ ] **Step 2: Append HERO and CONSTELLATION region styles to styles.css**

Use the Edit tool to add hero styles. Find the end of the NAV region (after the `@media (max-width: 768px) { .nav.is-open ... }` block) and insert before `/* ============= MOTION ============= */`:

`old_string`:

```
@media (max-width: 768px) {
  .nav__menu { display: none; }
  .nav__toggle { display: flex; }
  .nav.is-open .nav__menu {
    display: flex; flex-direction: column; gap: var(--space-4);
    position: absolute; top: 64px; left: 0; right: 0;
    background: var(--surface);
    padding: var(--space-6); border-bottom: 1px solid var(--border-color);
  }
}

/* ============= MOTION ============= */
```

`new_string`:

```
@media (max-width: 768px) {
  .nav__menu { display: none; }
  .nav__toggle { display: flex; }
  .nav.is-open .nav__menu {
    display: flex; flex-direction: column; gap: var(--space-4);
    position: absolute; top: 64px; left: 0; right: 0;
    background: var(--surface);
    padding: var(--space-6); border-bottom: 1px solid var(--border-color);
  }
}

/* ============= HERO ============= */
.hero { padding-block: var(--space-20) var(--space-24); overflow: hidden; }
.hero__inner {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-16);
  align-items: center;
}
@media (min-width: 1024px) {
  .hero__inner { grid-template-columns: 1fr 1fr; gap: var(--space-12); }
}
.hero__title {
  font-size: clamp(2.75rem, 5.5vw + 1rem, var(--text-6xl));
  margin-block: var(--space-4) var(--space-6);
  letter-spacing: -0.03em;
  line-height: 1.05;
}
.hero__lead {
  font-size: var(--text-lg);
  max-width: 50ch;
  margin-bottom: var(--space-8);
}
.hero__ctas {
  display: flex; flex-wrap: wrap; gap: var(--space-3);
  margin-bottom: var(--space-8);
}
.hero__install {
  display: inline-flex; align-items: center; gap: var(--space-3);
  background: var(--surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3) var(--space-2) var(--space-4);
  font-family: var(--font-mono); font-size: var(--text-sm);
  margin-bottom: var(--space-12);
  max-width: 100%; overflow-x: auto;
}
.hero__install-cmd { white-space: nowrap; }
.hero__install-copy {
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px;
  color: var(--text-secondary); border-radius: var(--radius-sm);
  transition: color var(--dur-fast) ease, background var(--dur-fast) ease;
}
.hero__install-copy:hover { color: var(--signal); background: var(--bg); }
.hero__stats {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-6);
}
@media (min-width: 768px) { .hero__stats { grid-template-columns: repeat(4, 1fr); } }
.hero__stats li { display: flex; flex-direction: column; gap: var(--space-1); }
.hero__stat-num {
  font-family: var(--font-mono); font-size: var(--text-2xl);
  color: var(--text); font-weight: var(--weight-medium);
}
.hero__stat-label { font-size: var(--text-sm); color: var(--text-secondary); }
.hero__visual {
  display: flex; align-items: center; justify-content: center;
  position: relative;
}

/* ============= CONSTELLATION ============= */
.constellation { width: 100%; max-width: 480px; height: auto; }
.constellation__dot--bright {
  filter: drop-shadow(0 0 16px rgba(255, 210, 74, 0.45));
}
@keyframes constellation-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.85; }
}
.constellation__dot--bright { animation: constellation-pulse 4s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .constellation__dot--bright { animation: none; }
}

```

- [ ] **Step 3: Verify the hero renders correctly**

```bash
open website/index.html
```

Expected at desktop width: two-column hero. Left column has eyebrow ("MCP SERVER · v1.0.0" in amber mono), large title "Knowledge that works offline.", lead paragraph, two buttons (amber "Get started", outline "View on GitHub"), install one-liner pill with copy icon, four-stat row. Right column shows the static constellation in a soft amber glow with the top dot pulsing.

At <1024px: single column, constellation appears below the content.

- [ ] **Step 4: Commit**

```bash
git add website/index.html website/assets/styles.css
git commit -m "design(website): build hero section with constellation visual and stat strip"
```

---

## Task 7: Constellation animator JavaScript module

Replace the existing `script.js` with a new file. This task adds only the constellation animator (theme/nav/reveal/copy/tabs come in subsequent tasks). The animator hides the lines and dots on load, then strokes lines in with stagger and fades dots in trailing.

**Files:**

- Modify: `website/assets/script.js`

- [ ] **Step 1: Write the constellation animator + initial scaffold**

Use the Write tool to overwrite `website/assets/script.js` with:

```javascript
// OpenZIM MCP — website interactions. No dependencies.
(function () {
  'use strict';

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ============= CONSTELLATION ANIMATOR =============
  function animateConstellation() {
    const svg = document.getElementById('hero-constellation');
    if (!svg) return;

    const lines = svg.querySelectorAll('.constellation__line');
    const dots = svg.querySelectorAll('.constellation__dot');

    if (reduceMotion) {
      // Static draw — set fully visible
      lines.forEach(l => { l.style.strokeDasharray = 'none'; l.style.opacity = '1'; });
      dots.forEach(d => { d.style.opacity = '1'; });
      return;
    }

    // Initial state: lines hidden via dasharray, dots transparent
    lines.forEach(l => {
      const len = l.getTotalLength();
      l.style.strokeDasharray = String(len);
      l.style.strokeDashoffset = String(len);
      l.style.transition = `stroke-dashoffset 280ms cubic-bezier(0.2, 0.8, 0.3, 1)`;
    });
    dots.forEach(d => {
      d.style.opacity = '0';
      d.style.transition = `opacity 200ms cubic-bezier(0.2, 0.8, 0.3, 1)`;
    });

    // Animate after one frame so initial state is committed
    requestAnimationFrame(() => {
      lines.forEach((l, i) => {
        setTimeout(() => { l.style.strokeDashoffset = '0'; }, i * 80);
      });
      // Dots fade in 200ms after their corresponding line completes (line-stroke takes 280ms)
      dots.forEach((d, i) => {
        const idx = parseInt(d.dataset.i || String(i), 10);
        setTimeout(() => { d.style.opacity = '1'; }, idx * 80 + 280);
      });
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    animateConstellation();
  });
})();
```

- [ ] **Step 2: Verify the animation runs in the browser**

Reload `website/index.html` in a browser (force-refresh with Cmd-Shift-R / Ctrl-Shift-F5 to bypass JS cache).

Expected: on page load, the constellation lines stroke into view from start to end of each line over ~280ms each, with an 80ms stagger between lines. Dots fade in trailing each line. Total animation completes around 600ms after page render. The amber top-dot continues to pulse subtly afterward.

To verify the reduced-motion branch: In Chrome DevTools, open the Rendering tab (⋮ → More tools → Rendering), set "Emulate CSS media feature prefers-reduced-motion" to "reduce", reload. Constellation should appear fully drawn instantly.

- [ ] **Step 3: Commit**

```bash
git add website/assets/script.js
git commit -m "feat(website): animate constellation hero with stroke draw-on-load"
```

---

## Task 8: "What is this" section — explainer + diagram + production stats

Build the section that replaces the "Why LLMs love it" feature grid. It contains a one-paragraph explainer, a 3-box flow diagram (ZIM archive → openzim-mcp → Your LLM), three card row (Offline · Secure · Structured), and a production-stat sub-strip.

**Files:**

- Modify: `website/index.html`
- Modify: `website/assets/styles.css`

- [ ] **Step 1: Fill in the "What is this" section markup**

Use the Edit tool on `website/index.html`:

`old_string`:

```
    <section id="what" class="section section--surface what">
      <!-- Filled in Task 9 -->
    </section>
```

`new_string`:

```
    <section id="what" class="section section--surface what" data-reveal>
      <div class="container container--narrow">
        <header class="section__header">
          <span class="eyebrow">What is this</span>
          <h2>An MCP server for offline knowledge.</h2>
          <p>
            ZIM archives package Wikipedia, Project Gutenberg, MedlinePlus, the Stack Exchange
            network, and more into self-contained files you can carry on a USB stick. OpenZIM MCP
            is the Model Context Protocol server that turns those static files into intelligent,
            structured access for any LLM client — Claude Desktop, Cursor, Cline, or your own.
          </p>
        </header>

        <figure class="what__diagram" aria-label="Architecture diagram: ZIM archive flows through openzim-mcp to your LLM">
          <svg viewBox="0 0 720 220" role="img" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill="var(--signal)"/>
              </marker>
            </defs>
            <!-- Box 1 -->
            <g>
              <rect x="20"  y="60" width="180" height="100" rx="10" fill="var(--bg)" stroke="var(--border-color)" stroke-width="1.5"/>
              <text x="110" y="105" text-anchor="middle" fill="var(--text)" font-family="var(--font-sans)" font-size="18" font-weight="600">ZIM archive</text>
              <text x="110" y="130" text-anchor="middle" fill="var(--text-secondary)" font-family="var(--font-mono)" font-size="13">Static</text>
            </g>
            <!-- Box 2 (highlighted) -->
            <g>
              <rect x="270" y="40" width="180" height="140" rx="10" fill="var(--bg)" stroke="var(--signal)" stroke-width="2"/>
              <g transform="translate(360 95) scale(1.4)" fill="none" stroke="var(--text)" stroke-width="1.4" stroke-linecap="round">
                <line x1="0" y1="-22" x2="-18" y2="-6"/>
                <line x1="0" y1="-22" x2="18" y2="-6"/>
                <line x1="-18" y1="-6" x2="-14" y2="18"/>
                <line x1="18" y1="-6" x2="14" y2="18"/>
                <line x1="-14" y1="18" x2="14" y2="18"/>
              </g>
              <g transform="translate(360 95) scale(1.4)" stroke="none">
                <circle cx="-18" cy="-6" r="2.2" fill="var(--text)"/>
                <circle cx="18" cy="-6" r="2.2" fill="var(--text)"/>
                <circle cx="-14" cy="18" r="2.2" fill="var(--text)"/>
                <circle cx="14" cy="18" r="2.2" fill="var(--text)"/>
                <circle cx="0" cy="-22" r="2.6" fill="#FFD24A"/>
              </g>
              <text x="360" y="148" text-anchor="middle" fill="var(--text)" font-family="var(--font-sans)" font-size="16" font-weight="600">openzim-mcp</text>
              <text x="360" y="168" text-anchor="middle" fill="var(--signal)" font-family="var(--font-mono)" font-size="13">Intelligent</text>
            </g>
            <!-- Box 3 -->
            <g>
              <rect x="520" y="60" width="180" height="100" rx="10" fill="var(--bg)" stroke="var(--border-color)" stroke-width="1.5"/>
              <text x="610" y="105" text-anchor="middle" fill="var(--text)" font-family="var(--font-sans)" font-size="18" font-weight="600">Your LLM</text>
              <text x="610" y="130" text-anchor="middle" fill="var(--text-secondary)" font-family="var(--font-mono)" font-size="13">Conversational</text>
            </g>
            <!-- Arrows -->
            <line x1="200" y1="110" x2="265" y2="110" stroke="var(--signal)" stroke-width="2" stroke-dasharray="6 4" marker-end="url(#arrow)"/>
            <line x1="450" y1="110" x2="515" y2="110" stroke="var(--signal)" stroke-width="2" stroke-dasharray="6 4" marker-end="url(#arrow)"/>
          </svg>
        </figure>

        <ul class="what__triad">
          <li>
            <h3>Offline</h3>
            <p>No network round-trips. The whole archive — every article, every link — sits on disk and stays accessible whether the network is up or down.</p>
          </li>
          <li>
            <h3>Secure</h3>
            <p>Path-traversal protection, sanitized error messages, bearer-token auth on HTTP, multi-arch container running as non-root.</p>
          </li>
          <li>
            <h3>Structured</h3>
            <p>Search, browse, summarize, traverse — 21 tools designed for how LLMs actually consume knowledge, not just raw file access.</p>
          </li>
        </ul>

        <ul class="what__production">
          <li><span class="what__production-num">0</span><span class="what__production-label">Known CVEs</span></li>
          <li><span class="what__production-num">80%+</span><span class="what__production-label">Test coverage</span></li>
          <li><span class="what__production-num">100%</span><span class="what__production-label">Type-annotated</span></li>
        </ul>
      </div>
    </section>
```

- [ ] **Step 2: Append WHAT-IS-THIS region styles**

Use the Edit tool on `website/assets/styles.css`. Find the end of the CONSTELLATION region and insert before `/* ============= MOTION ============= */`:

`old_string`:

```
.constellation__dot--bright { animation: constellation-pulse 4s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .constellation__dot--bright { animation: none; }
}

/* ============= MOTION ============= */
```

`new_string`:

```
.constellation__dot--bright { animation: constellation-pulse 4s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .constellation__dot--bright { animation: none; }
}

/* ============= WHAT-IS-THIS ============= */
.section__header { text-align: center; margin-bottom: var(--space-16); }
.section__header h2 { margin-block: var(--space-3) var(--space-6); }
.section__header p { max-width: 60ch; margin-inline: auto; font-size: var(--text-lg); }

.what__diagram {
  margin-block: var(--space-12) var(--space-16);
}
.what__diagram svg { width: 100%; height: auto; max-width: 720px; margin-inline: auto; }

.what__triad {
  display: grid; grid-template-columns: 1fr; gap: var(--space-6);
  margin-bottom: var(--space-16);
}
@media (min-width: 768px) { .what__triad { grid-template-columns: repeat(3, 1fr); } }
.what__triad li {
  background: var(--bg); border: 1px solid var(--border-color);
  border-radius: var(--radius-lg); padding: var(--space-6);
}
.what__triad h3 { font-size: var(--text-xl); margin-bottom: var(--space-3); }
.what__triad p { font-size: var(--text-base); }

.what__production {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-6);
  padding-block: var(--space-8); border-top: 1px solid var(--border-color);
  text-align: center;
}
.what__production li { display: flex; flex-direction: column; gap: var(--space-1); }
.what__production-num {
  font-family: var(--font-mono); font-size: var(--text-3xl);
  color: var(--signal); font-weight: var(--weight-medium);
}
.what__production-label { font-size: var(--text-sm); color: var(--text-secondary); }

```

- [ ] **Step 3: Verify the section renders**

Reload the page in browser. Expected: below the hero, a surface-colored section with center-aligned eyebrow + heading + paragraph; a 3-box diagram with arrows pointing left to right; three cards in a row (Offline / Secure / Structured) at desktop, stacked on mobile; production-stat row at the bottom (0 / 80%+ / 100% in amber mono).

- [ ] **Step 4: Commit**

```bash
git add website/index.html website/assets/styles.css
git commit -m "design(website): build What-is-this section with diagram and production stats"
```

---

## Task 9: "What's in v1.0" milestone section

The celebration section. Watermark "1.0" Fraunces numerals as background, four marquee cards in a 2×2 grid each with a mini code snippet, then a `<details>` with the polish-and-fixes content from the existing site, then v0.9.0 below.

**Files:**

- Modify: `website/index.html`
- Modify: `website/assets/styles.css`

- [ ] **Step 1: Fill in the "What's in v1.0" section markup**

Use the Edit tool on `website/index.html`:

`old_string`:

```
    <section id="v1" class="section v1">
      <!-- Filled in Task 10 -->
    </section>
```

`new_string`:

```
    <section id="v1" class="section v1" data-reveal>
      <div class="container">
        <span class="v1__watermark" aria-hidden="true">1.0</span>
        <header class="section__header">
          <span class="eyebrow">The 1.0 release</span>
          <h2>Four headlines, dozens of fixes.</h2>
          <p>v1.0.0 ships streamable HTTP, batch retrieval, per-entry resources, and resource subscriptions — plus an end-to-end review pass before tagging.</p>
        </header>

        <ul class="v1__cards">
          <li class="v1__card">
            <span class="v1__card-dot" aria-hidden="true"></span>
            <h3>Streamable HTTP &amp; SSE transports</h3>
            <p>Run as a long-running service. Bearer-token auth, CORS allow-list, <code>/healthz</code> &amp; <code>/readyz</code>, multi-arch Docker.</p>
            <pre><code>docker run -p 8080:8080 \
  ghcr.io/cameronrye/openzim-mcp:1.0.0 \
  --transport streamable-http \
  --auth-token "$TOKEN" /data</code></pre>
          </li>

          <li class="v1__card">
            <span class="v1__card-dot" aria-hidden="true"></span>
            <h3>Batch entry retrieval</h3>
            <p><code>get_zim_entries</code> fetches up to 50 entries per call. Multi-archive batches, partial-success reporting, rate-limit-aware.</p>
            <pre><code>{
  "name": "get_zim_entries",
  "arguments": {
    "zim_file_path": "wiki.zim",
    "entries": ["A/Evolution",
                "A/Genetics",
                "A/Mendel"]
  }
}</code></pre>
          </li>

          <li class="v1__card">
            <span class="v1__card-dot" aria-hidden="true"></span>
            <h3>Per-entry MCP resources</h3>
            <p>Each entry exposed as <code>zim://{name}/entry/{path}</code> with libzim's native MIME type — HTML, PDFs, images render in MCP-aware clients.</p>
            <pre><code>zim://wikipedia_en/entry/A%2FEvolution
# returns text/html

zim://gutenberg/entry/I%2Fbook_cover.jpg
# returns image/jpeg</code></pre>
          </li>

          <li class="v1__card">
            <span class="v1__card-dot" aria-hidden="true"></span>
            <h3>Resource subscriptions</h3>
            <p>Subscribe to <code>zim://files</code> or <code>zim://{name}</code>. mtime-polling watcher emits <code>notifications/resources/updated</code> when archives change.</p>
            <pre><code>// client subscribes
{ "method": "resources/subscribe",
  "params": { "uri": "zim://files" } }

// server notifies on change
{ "method": "notifications/resources/updated",
  "params": { "uri": "zim://files" } }</code></pre>
          </li>
        </ul>

        <details class="v1__also">
          <summary><strong>Also in 1.0</strong> — polish, fixes, and scope cuts</summary>
          <div class="v1__also-grid">
            <div>
              <h4>Smarter archive handling</h4>
              <ul>
                <li><code>get_related_articles</code> resolves relative hrefs against the source entry's directory and detects the content namespace correctly on domain-scheme archives.</li>
                <li>Suggestion fallback uses <code>SuggestionSearcher(archive).suggest(text)</code> (the prior <code>archive.suggest()</code> call didn't exist).</li>
                <li><code>list_zim_files</code> gains a case-insensitive <code>name_filter</code> substring argument.</li>
                <li><code>search_zim_file</code> accepts an opaque <code>cursor</code> parameter; passing the cursor alone resumes pagination.</li>
              </ul>
            </div>
            <div>
              <h4>Cleaner content extraction</h4>
              <ul>
                <li>Heading-id resolution falls through <code>id</code> → mw-headline anchor → <code>&lt;a name=""&gt;</code> → slug.</li>
                <li>Summary extraction skips USWDS banners and skip-nav blocks above the first <code>&lt;h1&gt;</code>.</li>
                <li>Link extraction drops non-navigable schemes (<code>javascript:</code>, <code>mailto:</code>, <code>tel:</code>, <code>data:</code>, <code>blob:</code>, <code>vbscript:</code>).</li>
                <li>Per-entry paths sanitized in <code>get_zim_entries</code>.</li>
              </ul>
            </div>
            <div>
              <h4>Server hygiene</h4>
              <ul>
                <li><code>__version__</code> reads from <code>importlib.metadata</code>; <code>serverInfo.version</code> reports openzim-mcp's actual version.</li>
                <li>HTTP transport's subscription watcher starts via wrapped lifespan.</li>
                <li>Per-entry <code>zim://</code> returns libzim's native MIME type.</li>
              </ul>
            </div>
            <div>
              <h4>Streamlined scope</h4>
              <p>Advanced-mode tool surface drops 27 → 21. Removed: <code>warm_cache</code>, <code>cache_stats</code>, <code>cache_clear</code>, <code>get_random_entry</code>, <code>diagnose_server_state</code>, <code>resolve_server_conflicts</code>. The cache itself remains. Multi-instance conflict tracking removed entirely.</p>
            </div>
          </div>
        </details>

        <article class="v1__prior">
          <h3>v0.9.0 <span class="v1__prior-label">— previously</span></h3>
          <ul>
            <li><strong>Multi-archive search</strong> — <code>search_all</code> queries every ZIM file in your allowed directories at once.</li>
            <li><strong>MCP Prompts</strong> — <code>/research</code>, <code>/summarize</code>, <code>/explore</code> as ready-made workflows.</li>
            <li><strong>Find entries by title</strong> — <code>find_entry_by_title</code> resolves a title to entry paths, optionally cross-file.</li>
            <li><strong>MCP Resources</strong> — <code>zim://files</code> and <code>zim://{name}</code> show up in your client's resource browser.</li>
            <li><strong>Power-user tools</strong> — <code>walk_namespace</code> for cursor-paginated iteration; <code>get_related_articles</code> for outbound link-graph neighbours.</li>
          </ul>
        </article>
      </div>
    </section>
```

- [ ] **Step 2: Append WHATS-IN-V1 region styles**

Use the Edit tool on `website/assets/styles.css`. Find the end of the WHAT-IS-THIS region and insert before `/* ============= MOTION ============= */`:

`old_string`:

```
.what__production-num {
  font-family: var(--font-mono); font-size: var(--text-3xl);
  color: var(--signal); font-weight: var(--weight-medium);
}
.what__production-label { font-size: var(--text-sm); color: var(--text-secondary); }

/* ============= MOTION ============= */
```

`new_string`:

```
.what__production-num {
  font-family: var(--font-mono); font-size: var(--text-3xl);
  color: var(--signal); font-weight: var(--weight-medium);
}
.what__production-label { font-size: var(--text-sm); color: var(--text-secondary); }

/* ============= WHATS-IN-V1 ============= */
.v1 { position: relative; overflow: hidden; }
.v1__watermark {
  position: absolute; bottom: -3rem; right: -1rem;
  font-family: var(--font-display);
  font-size: clamp(8rem, 25vw, 18rem);
  font-weight: 600;
  color: var(--text);
  opacity: 0.04;
  pointer-events: none;
  user-select: none;
  line-height: 1;
}

.v1__cards {
  display: grid; grid-template-columns: 1fr; gap: var(--space-6);
  margin-block: var(--space-12);
}
@media (min-width: 768px) {
  .v1__cards { grid-template-columns: repeat(2, 1fr); gap: var(--space-8); }
}
.v1__card {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: var(--space-8);
  transition: border-color var(--dur-base) ease, transform var(--dur-base) ease;
}
.v1__card:hover { border-color: var(--signal); transform: translateY(-2px); }
.v1__card-dot {
  position: absolute; top: var(--space-5); right: var(--space-5);
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--signal);
  box-shadow: 0 0 12px rgba(255, 210, 74, 0.5);
}
.v1__card h3 {
  font-size: var(--text-xl); margin-bottom: var(--space-3);
  padding-right: var(--space-6);
}
.v1__card p { margin-bottom: var(--space-5); }
.v1__card pre {
  background: var(--bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  overflow-x: auto;
  font-size: var(--text-sm);
  line-height: 1.5;
}
.v1__card code:not(pre code) {
  background: var(--bg); padding: 1px 6px; border-radius: 3px;
  font-size: 0.92em; color: var(--signal);
}

.v1__also {
  background: var(--surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  margin-bottom: var(--space-12);
}
.v1__also summary {
  cursor: pointer; font-size: var(--text-lg);
  list-style: none; padding-block: var(--space-2);
  display: flex; align-items: center; gap: var(--space-2);
}
.v1__also summary::before {
  content: '▸'; color: var(--signal); transition: transform var(--dur-fast) ease;
  display: inline-block;
}
.v1__also[open] summary::before { transform: rotate(90deg); }
.v1__also-grid {
  display: grid; grid-template-columns: 1fr; gap: var(--space-6);
  margin-top: var(--space-6);
}
@media (min-width: 768px) { .v1__also-grid { grid-template-columns: repeat(2, 1fr); } }
.v1__also-grid h4 { font-size: var(--text-base); margin-bottom: var(--space-3); color: var(--text); }
.v1__also-grid ul { display: flex; flex-direction: column; gap: var(--space-2); }
.v1__also-grid li, .v1__also-grid p {
  font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.6;
}
.v1__also-grid code {
  background: var(--bg); padding: 1px 5px; border-radius: 3px;
  font-size: 0.9em; color: var(--signal);
}

.v1__prior { padding-top: var(--space-6); border-top: 1px solid var(--border-color); }
.v1__prior h3 { font-size: var(--text-lg); color: var(--text-secondary); margin-bottom: var(--space-4); }
.v1__prior-label { font-weight: var(--weight-regular); }
.v1__prior ul { display: flex; flex-direction: column; gap: var(--space-2); }
.v1__prior li { font-size: var(--text-sm); color: var(--text-secondary); }
.v1__prior code {
  background: var(--surface); padding: 1px 5px; border-radius: 3px;
  font-size: 0.9em; color: var(--signal);
}

```

- [ ] **Step 3: Verify the section renders**

Reload the page. Expected: large faded "1.0" Fraunces watermark in the lower-right, eyebrow "THE 1.0 RELEASE", section title, four cards in a 2×2 grid (single column on mobile), each card with a small amber dot in its top-right corner, hover lifts the card. Below the cards: a collapsible "Also in 1.0" details, then v0.9.0 in muted styling.

- [ ] **Step 4: Commit**

```bash
git add website/index.html website/assets/styles.css
git commit -m "design(website): build What's-in-v1.0 milestone section with marquee cards"
```

---

## Task 10: "Try it" section — install steps + usage example tabs

3-step install row (`uv` / `Docker` / `From source` tabs in step 1), then trimmed usage tabs (Search / Browse / Subscribe) below.

**Files:**

- Modify: `website/index.html`
- Modify: `website/assets/styles.css`

- [ ] **Step 1: Fill in the "Try it" section markup**

Use the Edit tool on `website/index.html`:

`old_string`:

```
    <section id="try" class="section section--surface try">
      <!-- Filled in Task 11 -->
    </section>
```

`new_string`:

```
    <section id="try" class="section section--surface try" data-reveal>
      <div class="container">
        <header class="section__header">
          <span class="eyebrow">Try it</span>
          <h2>Three steps to a knowledge engine.</h2>
        </header>

        <ol class="try__steps">
          <li class="try__step">
            <span class="try__step-num">1</span>
            <h3>Install</h3>
            <div class="tabs" data-tabs="install">
              <div class="tabs__buttons" role="tablist">
                <button class="tabs__btn is-active" role="tab" data-tab="install-uv" aria-selected="true">uv</button>
                <button class="tabs__btn" role="tab" data-tab="install-docker" aria-selected="false">Docker</button>
                <button class="tabs__btn" role="tab" data-tab="install-source" aria-selected="false">From source</button>
              </div>
              <div class="tabs__panel is-active" id="install-uv" role="tabpanel">
                <pre><code>uv tool install openzim-mcp</code></pre>
              </div>
              <div class="tabs__panel" id="install-docker" role="tabpanel" hidden>
                <pre><code>docker pull ghcr.io/cameronrye/openzim-mcp:1.0.0</code></pre>
              </div>
              <div class="tabs__panel" id="install-source" role="tabpanel" hidden>
                <pre><code>git clone https://github.com/cameronrye/openzim-mcp.git
cd openzim-mcp
uv sync</code></pre>
              </div>
            </div>
          </li>

          <li class="try__step">
            <span class="try__step-num">2</span>
            <h3>Get a ZIM</h3>
            <p>Download an archive from <a href="https://browse.library.kiwix.org/" target="_blank" rel="noopener">the Kiwix library ↗</a>.</p>
            <pre><code>mkdir ~/zim-files &amp;&amp; cd ~/zim-files
# place .zim files here</code></pre>
          </li>

          <li class="try__step">
            <span class="try__step-num">3</span>
            <h3>Run it</h3>
            <pre><code>uv run openzim-mcp ~/zim-files</code></pre>
            <p class="try__callout">
              Or as an HTTP service: <code>--transport streamable-http --auth-token $TOKEN</code>
            </p>
          </li>
        </ol>

        <div class="try__usage">
          <h3 class="try__usage-title">See it in action</h3>
          <div class="tabs" data-tabs="usage">
            <div class="tabs__buttons" role="tablist">
              <button class="tabs__btn is-active" role="tab" data-tab="use-search" aria-selected="true">Search</button>
              <button class="tabs__btn" role="tab" data-tab="use-browse" aria-selected="false">Browse</button>
              <button class="tabs__btn" role="tab" data-tab="use-subscribe" aria-selected="false">Subscribe</button>
            </div>
            <div class="tabs__panel is-active" id="use-search" role="tabpanel">
              <div class="try__exchange">
                <div>
                  <h4>Request</h4>
                  <pre><code>{
  "name": "search_zim_file",
  "arguments": {
    "zim_file_path": "wikipedia_en.zim",
    "query": "artificial intelligence",
    "limit": 5
  }
}</code></pre>
                </div>
                <div>
                  <h4>Response</h4>
                  <pre><code>Found 42 matches, showing 1-5:

## 1. Artificial Intelligence
Path: A/Artificial_intelligence
Snippet: Artificial intelligence (AI) is
intelligence demonstrated by machines...

## 2. Machine Learning
Path: A/Machine_learning
Snippet: Machine learning is a subset of
artificial intelligence...</code></pre>
                </div>
              </div>
            </div>
            <div class="tabs__panel" id="use-browse" role="tabpanel" hidden>
              <div class="try__exchange">
                <div>
                  <h4>Request</h4>
                  <pre><code>{
  "name": "browse_namespace",
  "arguments": {
    "zim_file_path": "wikipedia_en.zim",
    "namespace": "C",
    "limit": 10
  }
}</code></pre>
                </div>
                <div>
                  <h4>Response</h4>
                  <pre><code>{
  "namespace": "C",
  "total_in_namespace": 80000,
  "returned_count": 10,
  "has_more": true,
  "entries": [
    { "path": "C/Biology",
      "title": "Biology",
      "preview": "Biology is the scientific
                  study of life..." }
  ]
}</code></pre>
                </div>
              </div>
            </div>
            <div class="tabs__panel" id="use-subscribe" role="tabpanel" hidden>
              <div class="try__exchange">
                <div>
                  <h4>Subscribe</h4>
                  <pre><code>{
  "method": "resources/subscribe",
  "params": { "uri": "zim://files" }
}</code></pre>
                </div>
                <div>
                  <h4>Notification (when archive changes)</h4>
                  <pre><code>{
  "method": "notifications/resources/updated",
  "params": { "uri": "zim://files" }
}</code></pre>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
```

- [ ] **Step 2: Append TRY-IT region styles**

Use the Edit tool on `website/assets/styles.css`. Find the end of the WHATS-IN-V1 region and insert before `/* ============= MOTION ============= */`:

`old_string`:

```
.v1__prior code {
  background: var(--surface); padding: 1px 5px; border-radius: 3px;
  font-size: 0.9em; color: var(--signal);
}

/* ============= MOTION ============= */
```

`new_string`:

```
.v1__prior code {
  background: var(--surface); padding: 1px 5px; border-radius: 3px;
  font-size: 0.9em; color: var(--signal);
}

/* ============= TRY-IT ============= */
.try__steps {
  display: grid; grid-template-columns: 1fr; gap: var(--space-6);
  margin-bottom: var(--space-16); counter-reset: none;
}
@media (min-width: 768px) {
  .try__steps { grid-template-columns: repeat(3, 1fr); gap: var(--space-6); }
}
.try__step {
  background: var(--bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  display: flex; flex-direction: column; gap: var(--space-3);
}
.try__step-num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border-radius: 50%;
  background: var(--signal); color: var(--ink);
  font-family: var(--font-mono); font-weight: var(--weight-semibold);
  font-size: var(--text-sm);
}
.try__step h3 { font-size: var(--text-lg); }
.try__step p { font-size: var(--text-sm); }
.try__step pre {
  background: var(--surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  font-size: var(--text-sm);
  overflow-x: auto;
}
.try__callout {
  font-size: var(--text-xs); color: var(--text-secondary);
  border-top: 1px dashed var(--border-color); padding-top: var(--space-3);
  margin-top: auto;
}
.try__callout code {
  background: var(--surface); padding: 1px 4px; border-radius: 3px;
  font-size: 0.95em; color: var(--signal);
}

.try__usage { padding-top: var(--space-12); border-top: 1px solid var(--border-color); }
.try__usage-title { text-align: center; margin-bottom: var(--space-8); font-size: var(--text-2xl); }

.try__exchange {
  display: grid; grid-template-columns: 1fr; gap: var(--space-4);
}
@media (min-width: 1024px) {
  .try__exchange { grid-template-columns: 1fr 1fr; }
}
.try__exchange h4 {
  font-size: var(--text-sm); font-family: var(--font-mono);
  text-transform: uppercase; letter-spacing: 0.1em;
  color: var(--text-secondary); margin-bottom: var(--space-2);
}
.try__exchange pre {
  background: var(--bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  font-size: var(--text-sm);
  overflow-x: auto;
  min-height: 100%;
}

/* Generic tabs */
.tabs__buttons {
  display: flex; gap: var(--space-1);
  border-bottom: 1px solid var(--border-color);
  margin-bottom: var(--space-4);
}
.tabs__btn {
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: color var(--dur-fast) ease, border-color var(--dur-fast) ease;
}
.tabs__btn:hover { color: var(--text); }
.tabs__btn.is-active {
  color: var(--text);
  border-bottom-color: var(--signal);
}
.tabs__panel { display: none; }
.tabs__panel.is-active { display: block; }

```

- [ ] **Step 3: Verify the section renders**

Reload. Expected: surface-colored section with three install-step cards (single column on mobile, 3-up on tablet+); each step has a small amber-circle number badge; step 1 has a tab strip (uv selected by default); step 3 has a dashed-border callout. Below the steps, a "See it in action" subsection with three tabs (Search / Browse / Subscribe). Tab content shows side-by-side request/response panels at desktop, stacked on mobile. Tabs may not switch yet — handler comes in Task 14.

- [ ] **Step 4: Commit**

```bash
git add website/index.html website/assets/styles.css
git commit -m "design(website): build Try-it section with install steps and usage tabs"
```

---

## Task 11: "Deeper" section — links grid

Six-cell links grid (3×2 at desktop, 2×3 on tablet, 1-col on mobile). No icons — title + one-line description + arrow link.

**Files:**

- Modify: `website/index.html`
- Modify: `website/assets/styles.css`

- [ ] **Step 1: Fill in the "Deeper" section markup**

Use the Edit tool on `website/index.html`:

`old_string`:

```
    <section id="deeper" class="section deeper">
      <!-- Filled in Task 12 -->
    </section>
```

`new_string`:

```
    <section id="deeper" class="section deeper" data-reveal>
      <div class="container">
        <header class="section__header">
          <span class="eyebrow">Deeper</span>
          <h2>Documentation &amp; resources.</h2>
        </header>
        <ul class="deeper__grid">
          <li>
            <a href="https://github.com/cameronrye/openzim-mcp#api-reference" target="_blank" rel="noopener">
              <h3>API Reference <span aria-hidden="true">↗</span></h3>
              <p>Every MCP tool with parameters, response schema, and intent examples.</p>
            </a>
          </li>
          <li>
            <a href="https://github.com/cameronrye/openzim-mcp/wiki/Deployment-Guide" target="_blank" rel="noopener">
              <h3>Deployment Guide <span aria-hidden="true">↗</span></h3>
              <p>Streamable HTTP, Docker, reverse proxies, auth tokens, multi-arch images.</p>
            </a>
          </li>
          <li>
            <a href="https://github.com/cameronrye/openzim-mcp/wiki/Architecture-Overview" target="_blank" rel="noopener">
              <h3>Architecture <span aria-hidden="true">↗</span></h3>
              <p>Modules, mixins, the <code>zim/</code> package split, dependency injection.</p>
            </a>
          </li>
          <li>
            <a href="https://github.com/cameronrye/openzim-mcp/wiki/Configuration-Guide" target="_blank" rel="noopener">
              <h3>Configuration <span aria-hidden="true">↗</span></h3>
              <p>Environment variables, cache tuning, content limits, logging levels.</p>
            </a>
          </li>
          <li>
            <a href="https://github.com/cameronrye/openzim-mcp/wiki/Troubleshooting-Guide" target="_blank" rel="noopener">
              <h3>Troubleshooting <span aria-hidden="true">↗</span></h3>
              <p>Common failures, error-message decoder, performance hints.</p>
            </a>
          </li>
          <li>
            <a href="https://github.com/cameronrye/openzim-mcp/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener">
              <h3>Contributing <span aria-hidden="true">↗</span></h3>
              <p>Local setup, Makefile workflow, test structure, PR conventions.</p>
            </a>
          </li>
        </ul>
      </div>
    </section>
```

- [ ] **Step 2: Append DEEPER region styles**

Use the Edit tool on `website/assets/styles.css`. Find the end of the TRY-IT region and insert before `/* ============= MOTION ============= */`:

`old_string`:

```
.tabs__panel { display: none; }
.tabs__panel.is-active { display: block; }

/* ============= MOTION ============= */
```

`new_string`:

```
.tabs__panel { display: none; }
.tabs__panel.is-active { display: block; }

/* ============= DEEPER ============= */
.deeper__grid {
  display: grid; grid-template-columns: 1fr; gap: var(--space-4);
}
@media (min-width: 640px) { .deeper__grid { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 1024px) { .deeper__grid { grid-template-columns: repeat(3, 1fr); } }
.deeper__grid li {
  background: var(--surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  transition: border-color var(--dur-base) ease, transform var(--dur-base) ease;
}
.deeper__grid li:hover { border-color: var(--signal); transform: translateY(-2px); }
.deeper__grid a {
  display: block; padding: var(--space-6);
  color: var(--text);
}
.deeper__grid h3 {
  font-size: var(--text-lg); margin-bottom: var(--space-2);
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-2);
}
.deeper__grid h3 span { color: var(--text-secondary); transition: color var(--dur-fast) ease; }
.deeper__grid a:hover h3 span { color: var(--signal); }
.deeper__grid p { font-size: var(--text-sm); }
.deeper__grid code {
  background: var(--bg); padding: 1px 5px; border-radius: 3px;
  font-size: 0.92em; color: var(--signal);
}

```

- [ ] **Step 3: Verify the section renders**

Reload. Expected: section with eyebrow + title, six cards in a 3×2 grid at desktop. Each card is a link with title + arrow + one-line description. Hover lifts card and turns the arrow amber.

- [ ] **Step 4: Commit**

```bash
git add website/index.html website/assets/styles.css
git commit -m "design(website): build Deeper section with iconless docs links grid"
```

---

## Task 12: Footer

Three-column footer (Brand · Resources · Community), bottom strip with credit and a 3-dot constellation flourish.

**Files:**

- Modify: `website/index.html`
- Modify: `website/assets/styles.css`

- [ ] **Step 1: Fill in the footer markup**

Use the Edit tool on `website/index.html`:

`old_string`:

```
  <footer class="footer" id="footer">
    <!-- Filled in Task 13 -->
  </footer>
```

`new_string`:

```
  <footer class="footer" id="footer">
    <div class="container">
      <div class="footer__cols">
        <div class="footer__brand">
          <a href="#hero" class="nav__brand" aria-label="OpenZIM MCP home">
            <svg class="nav__logo" width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
              <g transform="rotate(8 16 16)" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
                <line x1="16" y1="6" x2="7" y2="13"/>
                <line x1="16" y1="6" x2="25" y2="13"/>
                <line x1="7" y1="13" x2="9" y2="25"/>
                <line x1="25" y1="13" x2="23" y2="25"/>
                <line x1="9" y1="25" x2="23" y2="25"/>
              </g>
              <g transform="rotate(8 16 16)" fill="none" stroke="currentColor" stroke-width="1.5">
                <circle cx="16" cy="6" r="2"/>
                <circle cx="7" cy="13" r="2"/>
                <circle cx="25" cy="13" r="2"/>
                <circle cx="9" cy="25" r="2"/>
                <circle cx="23" cy="25" r="2"/>
              </g>
            </svg>
            <span class="nav__wordmark">OpenZIM&nbsp;MCP</span>
          </a>
          <p>Knowledge that works offline. Released under the <a href="https://opensource.org/licenses/MIT">MIT License</a>.</p>
          <div class="footer__badges">
            <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+" loading="lazy">
            <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License" loading="lazy">
          </div>
        </div>
        <div>
          <h4 class="footer__title">Resources</h4>
          <ul class="footer__links">
            <li><a href="https://github.com/cameronrye/openzim-mcp">GitHub</a></li>
            <li><a href="https://github.com/cameronrye/openzim-mcp/releases">Releases</a></li>
            <li><a href="https://github.com/cameronrye/openzim-mcp/issues">Issues</a></li>
            <li><a href="https://github.com/cameronrye/openzim-mcp/wiki">Wiki</a></li>
          </ul>
        </div>
        <div>
          <h4 class="footer__title">Community</h4>
          <ul class="footer__links">
            <li><a href="https://modelcontextprotocol.io/">Model Context Protocol</a></li>
            <li><a href="https://openzim.org/">OpenZIM</a></li>
            <li><a href="https://www.kiwix.org/">Kiwix</a></li>
            <li><a href="https://browse.library.kiwix.org/">ZIM Library</a></li>
          </ul>
        </div>
      </div>
      <div class="footer__bottom">
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
          <g fill="currentColor">
            <circle cx="8" cy="3" r="1.4"/>
            <circle cx="3" cy="11" r="1.4"/>
            <circle cx="13" cy="11" r="1.4"/>
          </g>
        </svg>
        <span>Made with care by <a href="https://rye.dev" target="_blank" rel="noopener">Cameron Rye</a>.</span>
      </div>
    </div>
  </footer>
```

- [ ] **Step 2: Append FOOTER region styles**

Use the Edit tool on `website/assets/styles.css`. Find the end of the DEEPER region and insert before `/* ============= MOTION ============= */`:

`old_string`:

```
.deeper__grid code {
  background: var(--bg); padding: 1px 5px; border-radius: 3px;
  font-size: 0.92em; color: var(--signal);
}

/* ============= MOTION ============= */
```

`new_string`:

```
.deeper__grid code {
  background: var(--bg); padding: 1px 5px; border-radius: 3px;
  font-size: 0.92em; color: var(--signal);
}

/* ============= FOOTER ============= */
.footer {
  border-top: 1px solid var(--border-color);
  padding-block: var(--space-16) var(--space-8);
  margin-top: var(--space-16);
}
.footer__cols {
  display: grid; grid-template-columns: 1fr; gap: var(--space-10);
  margin-bottom: var(--space-12);
}
@media (min-width: 768px) {
  .footer__cols { grid-template-columns: 2fr 1fr 1fr; gap: var(--space-12); }
}
.footer__brand p { margin-block: var(--space-4); font-size: var(--text-sm); max-width: 40ch; }
.footer__badges { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.footer__badges img { height: 20px; }
.footer__title {
  font-size: var(--text-sm); font-family: var(--font-mono);
  text-transform: uppercase; letter-spacing: 0.12em;
  color: var(--text-secondary); margin-bottom: var(--space-4);
}
.footer__links { display: flex; flex-direction: column; gap: var(--space-2); }
.footer__links a { color: var(--text); font-size: var(--text-sm); }
.footer__links a:hover { color: var(--signal); }
.footer__bottom {
  display: flex; align-items: center; gap: var(--space-2);
  justify-content: center;
  padding-top: var(--space-8);
  border-top: 1px solid var(--border-color);
  font-size: var(--text-sm); color: var(--text-secondary);
}
.footer__bottom svg { color: var(--signal); }

```

- [ ] **Step 3: Verify the footer renders**

Reload. Expected: footer at the bottom with brand column on the left (logo + wordmark, tagline, two badge images), Resources column, Community column. Bottom strip centered: 3-dot amber constellation flourish + "Made with care by Cameron Rye."

- [ ] **Step 4: Commit**

```bash
git add website/index.html website/assets/styles.css
git commit -m "design(website): build new footer with brand, resources, community columns"
```

---

## Task 13: Wire up theme toggle, scroll-shadow, hamburger nav, reveal observer, copy buttons, tabs

All remaining JavaScript handlers. Builds on the existing `script.js` from Task 7.

**Files:**

- Modify: `website/assets/script.js`

- [ ] **Step 1: Replace script.js with the full handlers module**

Use the Write tool to overwrite `website/assets/script.js`:

```javascript
// OpenZIM MCP — website interactions. No dependencies.
(function () {
  'use strict';

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ============= THEME =============
  function initTheme() {
    const stored = localStorage.getItem('theme');
    const initial = stored || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    document.documentElement.setAttribute('data-theme', initial);

    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;
    toggle.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
    });
  }

  // ============= NAV (scroll shadow + mobile menu) =============
  function initNav() {
    const nav = document.getElementById('nav');
    const toggle = document.getElementById('nav-toggle');
    if (nav) {
      const onScroll = () => {
        if (window.scrollY > 0) nav.classList.add('is-scrolled');
        else nav.classList.remove('is-scrolled');
      };
      window.addEventListener('scroll', onScroll, { passive: true });
      onScroll();
    }
    if (toggle && nav) {
      toggle.addEventListener('click', () => {
        const open = nav.classList.toggle('is-open');
        toggle.setAttribute('aria-expanded', String(open));
        toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      });
      // Close mobile menu when an anchor is clicked
      nav.querySelectorAll('.nav__link').forEach(link => {
        link.addEventListener('click', () => {
          nav.classList.remove('is-open');
          toggle.setAttribute('aria-expanded', 'false');
        });
      });
    }
  }

  // ============= CONSTELLATION ANIMATOR =============
  function animateConstellation() {
    const svg = document.getElementById('hero-constellation');
    if (!svg) return;

    const lines = svg.querySelectorAll('.constellation__line');
    const dots = svg.querySelectorAll('.constellation__dot');

    if (reduceMotion) {
      lines.forEach(l => { l.style.strokeDasharray = 'none'; l.style.opacity = '1'; });
      dots.forEach(d => { d.style.opacity = '1'; });
      return;
    }

    lines.forEach(l => {
      const len = l.getTotalLength();
      l.style.strokeDasharray = String(len);
      l.style.strokeDashoffset = String(len);
      l.style.transition = 'stroke-dashoffset 280ms cubic-bezier(0.2, 0.8, 0.3, 1)';
    });
    dots.forEach(d => {
      d.style.opacity = '0';
      d.style.transition = 'opacity 200ms cubic-bezier(0.2, 0.8, 0.3, 1)';
    });

    requestAnimationFrame(() => {
      lines.forEach((l, i) => setTimeout(() => { l.style.strokeDashoffset = '0'; }, i * 80));
      dots.forEach((d, i) => {
        const idx = parseInt(d.dataset.i || String(i), 10);
        setTimeout(() => { d.style.opacity = '1'; }, idx * 80 + 280);
      });
    });
  }

  // ============= REVEAL ON SCROLL =============
  function initReveal() {
    const items = document.querySelectorAll('[data-reveal]');
    if (!items.length) return;
    if (reduceMotion || !('IntersectionObserver' in window)) {
      items.forEach(el => el.classList.add('revealed'));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('revealed');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15 });
    items.forEach(el => io.observe(el));
  }

  // ============= COPY BUTTONS =============
  function initCopyButtons() {
    const buttons = document.querySelectorAll('.copy-btn[data-copy-target]');
    buttons.forEach(btn => {
      btn.addEventListener('click', async () => {
        const sel = btn.getAttribute('data-copy-target');
        const target = sel ? document.querySelector(sel) : null;
        if (!target) return;
        const text = target.innerText.trim();
        try {
          await navigator.clipboard.writeText(text);
          showToast('Copied to clipboard');
        } catch (e) {
          // Fallback: prompt-based selection
          const range = document.createRange();
          range.selectNodeContents(target);
          const sel2 = window.getSelection();
          if (sel2) { sel2.removeAllRanges(); sel2.addRange(range); }
        }
      });
    });
  }

  function showToast(msg) {
    let toast = document.getElementById('copy-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'copy-toast';
      toast.className = 'toast';
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.classList.add('is-visible');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.remove('is-visible'), 1500);
  }

  // ============= TABS =============
  function initTabs() {
    document.querySelectorAll('[data-tabs]').forEach(group => {
      const buttons = group.querySelectorAll('.tabs__btn');
      const panels = group.querySelectorAll('.tabs__panel');
      buttons.forEach(btn => {
        btn.addEventListener('click', () => {
          const target = btn.getAttribute('data-tab');
          buttons.forEach(b => {
            const active = b === btn;
            b.classList.toggle('is-active', active);
            b.setAttribute('aria-selected', String(active));
          });
          panels.forEach(p => {
            const active = p.id === target;
            p.classList.toggle('is-active', active);
            if (active) p.removeAttribute('hidden'); else p.setAttribute('hidden', '');
          });
        });
        // Arrow-key nav
        btn.addEventListener('keydown', (e) => {
          const arr = Array.from(buttons);
          const i = arr.indexOf(btn);
          if (e.key === 'ArrowRight') { arr[(i + 1) % arr.length].focus(); e.preventDefault(); }
          if (e.key === 'ArrowLeft')  { arr[(i - 1 + arr.length) % arr.length].focus(); e.preventDefault(); }
        });
      });
    });
  }

  // ============= LEGACY ANCHOR REDIRECT =============
  function redirectLegacyAnchors() {
    const aliases = {
      '#features': '#what',
      '#smart-retrieval': '#what',
      '#advanced-features': '#what',
      '#developer-experience': '#what',
      '#security': '#what',
      '#whats-new': '#v1',
      '#installation': '#try',
      '#usage': '#try',
      '#documentation': '#deeper',
      '#home': '#hero'
    };
    if (aliases[location.hash]) {
      const target = aliases[location.hash];
      history.replaceState(null, '', target);
      const el = document.querySelector(target);
      if (el) el.scrollIntoView({ behavior: 'auto', block: 'start' });
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initNav();
    animateConstellation();
    initReveal();
    initCopyButtons();
    initTabs();
    redirectLegacyAnchors();
  });
})();
```

- [ ] **Step 2: Add toast styles**

Use the Edit tool on `website/assets/styles.css`. Find the end of the FOOTER region and insert before `/* ============= MOTION ============= */`:

`old_string`:

```
.footer__bottom svg { color: var(--signal); }

/* ============= MOTION ============= */
```

`new_string`:

```
.footer__bottom svg { color: var(--signal); }

/* ============= TOAST ============= */
.toast {
  position: fixed; bottom: var(--space-6); left: 50%;
  transform: translateX(-50%) translateY(8px);
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border-color);
  padding: var(--space-3) var(--space-5);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--dur-base) ease, transform var(--dur-base) ease;
  z-index: 100;
}
.toast.is-visible { opacity: 1; transform: translateX(-50%) translateY(0); }

/* ============= MOTION ============= */
```

- [ ] **Step 3: Verify all interactions**

Reload (Cmd-Shift-R / Ctrl-Shift-F5). Test each interaction:

- Theme toggle: click sun icon — page background and text invert. Reload — theme persists.
- Mobile menu: resize browser to <768px — hamburger appears. Click — menu drops down. Click a link — menu closes.
- Scroll: nav border appears/strengthens after scrolling >0px.
- Reveal: scroll past the "What is this" section — opacity should fade in (subtle since reduce-motion handling exists).
- Copy button: click the copy icon in the hero install bar — see "Copied to clipboard" toast at bottom.
- Tabs (install): click `Docker` tab — content switches to docker pull command.
- Tabs (usage): click `Browse` then `Subscribe` — exchange panels switch.
- Tabs (keyboard): focus a tab button, press → / ← — focus moves between tabs.
- Legacy anchors: navigate to `<file://...>/website/index.html#installation` — page should jump to `#try` and the URL should rewrite to `#try`.

- [ ] **Step 4: Commit**

```bash
git add website/assets/script.js website/assets/styles.css
git commit -m "feat(website): wire theme, nav, reveals, copy buttons, tabs, and legacy anchor redirects"
```

---

## Task 14: Update peripheral text files (humans.txt, sitemap.xml, llm.txt)

Bump version references and timestamps in the supporting text files.

**Files:**

- Modify: `website/humans.txt`
- Modify: `website/sitemap.xml`
- Modify: `website/llm.txt`

- [ ] **Step 1: Update humans.txt — bump version, last update, and font list**

Use the Edit tool on `website/humans.txt` (three Edit calls):

Edit 1 — bump the Last update:

`old_string`: `Last update: 2025-01-15`
`new_string`: `Last update: 2026-05-02`

Edit 2 — bump the Version:

`old_string`: `Version: 0.6.0`
`new_string`: `Version: 1.0.0`

Edit 3 — refresh the Fonts colophon to reflect the new type system:

`old_string`:

```
    ## Fonts
    Inter (Google Fonts)
    JetBrains Mono (Google Fonts)
```

`new_string`:

```
    ## Fonts
    Geist (Google Fonts)
    JetBrains Mono (Google Fonts)
    Fraunces (Google Fonts)
```

- [ ] **Step 2: Update sitemap.xml — bump every lastmod and refresh fragment URLs**

The current sitemap has 8 `<lastmod>2025-01-15</lastmod>` entries and 4 fragment URLs from the old IA (`#features`, `#installation`, `#usage`, `#documentation`).

Edit 1 — bump every `lastmod` in one call:

`old_string`: `<lastmod>2025-01-15</lastmod>`
`new_string`: `<lastmod>2026-05-02</lastmod>`

Use `replace_all: true` since every `<lastmod>` line is identical.

Edit 2 — replace the four legacy fragment URLs with new fragments matching the redesigned IA:

`old_string`:

```
    <url>
        <loc>https://cameronrye.github.io/openzim-mcp/#features</loc>
        <lastmod>2026-05-02</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>https://cameronrye.github.io/openzim-mcp/#installation</loc>
        <lastmod>2026-05-02</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>https://cameronrye.github.io/openzim-mcp/#usage</loc>
        <lastmod>2026-05-02</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>https://cameronrye.github.io/openzim-mcp/#documentation</loc>
        <lastmod>2026-05-02</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.7</priority>
    </url>
```

`new_string`:

```
    <url>
        <loc>https://cameronrye.github.io/openzim-mcp/#what</loc>
        <lastmod>2026-05-02</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>https://cameronrye.github.io/openzim-mcp/#v1</loc>
        <lastmod>2026-05-02</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>https://cameronrye.github.io/openzim-mcp/#try</loc>
        <lastmod>2026-05-02</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>https://cameronrye.github.io/openzim-mcp/#deeper</loc>
        <lastmod>2026-05-02</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.7</priority>
    </url>
```

- [ ] **Step 3: Update llm.txt — replace the tagline**

The version line in llm.txt is already `1.0.0` (release-please's `x-release-please-version` annotation keeps it current). Only the hero tagline needs updating.

Use the Edit tool on `website/llm.txt`:

`old_string`: `> Transform static ZIM archives into dynamic knowledge engines for Large Language Models`
`new_string`: `> Knowledge that works offline. OpenZIM MCP gives any AI model structured, secure access to ZIM archives — Wikipedia, MedlinePlus, the Stack Exchange dumps — without an internet connection.`

- [ ] **Step 4: Verify**

```bash
grep "1.0.0" website/humans.txt
grep "2026-05-02" website/sitemap.xml | wc -l
grep -c "Knowledge that works offline" website/llm.txt
```

Expected:

- humans.txt: line `Version: 1.0.0`
- sitemap.xml: count = 8 (every lastmod updated)
- llm.txt: count ≥ 1

- [ ] **Step 5: Commit**

```bash
git add website/humans.txt website/sitemap.xml website/llm.txt
git commit -m "docs(website): bump peripheral text files for v1.0 redesign launch"
```

---

## Task 15: Delete unused asset files

Three icon SVGs are no longer referenced in the new design.

**Files:**

- Delete: `website/assets/brain-icon.svg`
- Delete: `website/assets/shield-icon.svg`
- Delete: `website/assets/search-icon.svg`

- [ ] **Step 1: Verify the files are not referenced anywhere**

```bash
grep -r "brain-icon\|shield-icon\|search-icon" website/ --include="*.html" --include="*.css" --include="*.js" --include="*.txt" --include="*.xml"
```

Expected: no matches. If matches exist, address them (likely a missed update from earlier tasks) before proceeding.

- [ ] **Step 2: Delete the files**

```bash
rm website/assets/brain-icon.svg website/assets/shield-icon.svg website/assets/search-icon.svg
```

- [ ] **Step 3: Verify the validator still passes**

```bash
python website/validate.py
```

Expected: "All validations passed". The deleted files are not in the validator's `required_files` list (verified during spec self-review).

- [ ] **Step 4: Commit**

```bash
git add -A website/assets/
git commit -m "chore(website): remove icon SVGs no longer used after redesign"
```

---

## Task 16: Final verification — validate.py + Lighthouse + cross-browser smoke

Last task. Confirms the redesign meets the acceptance criteria from the spec.

**Files:** none modified

- [ ] **Step 1: Run validate.py one more time**

```bash
python website/validate.py
```

Expected: "All validations passed" plus all required files present.

- [ ] **Step 2: Check styles.css and script.js sizes against the spec ceilings**

```bash
wc -c website/assets/styles.css website/assets/script.js
```

Expected: `styles.css` ≤ 32KB unminified, `script.js` ≤ 12KB unminified (per spec acceptance criterion 9). If over, consider trimming unused selectors.

- [ ] **Step 3: Visual smoke at the four breakpoints**

Open `website/index.html` in Chrome. Open DevTools, use the device toolbar to test each breakpoint:

- 1440px (desktop wide): two-column hero, 2×2 v1 cards, 3-up Try-it steps, 3×2 Deeper grid
- 1024px (laptop): same as 1440 (this is the breakpoint for two-column hero)
- 768px (tablet): hero stacks (constellation below content), Try-it steps still 3-up, Deeper grid 2×3, footer 2fr-1fr-1fr
- 375px (mobile): everything single-column, hamburger nav appears

For each breakpoint, scroll the full page top to bottom. No horizontal scroll bars should appear. Text should never overflow its container. The constellation hero should scale proportionally without distortion.

- [ ] **Step 4: Cross-browser smoke**

Open the same file in Firefox and Safari (or Edge if Safari unavailable). Verify the constellation animation runs in each. Verify the theme toggle works. Verify the install copy button works (Safari has historical clipboard quirks — the fallback selection branch should kick in).

- [ ] **Step 5: Lighthouse run**

In Chrome DevTools, open the Lighthouse panel. Run a Mobile + Desktop audit on the redesigned page. Capture the four scores.

Expected (per spec acceptance criterion 2): Performance ≥ 95, Accessibility ≥ 95, Best Practices ≥ 95, SEO ≥ 95 on at least the Desktop audit.

If any score is below 95, common fixes:

- Performance: defer non-critical fonts, audit unused CSS, check for layout shift from font swap
- Accessibility: missing alt text, low contrast, missing form labels (none expected here, but verify)
- Best Practices: HTTPS-only links, no console errors, no deprecated APIs
- SEO: missing meta description, missing canonical, robots.txt blocking

Address any below-95 score before declaring done. Score evidence belongs in the PR description.

- [ ] **Step 6: Reduced-motion verification**

Re-test with `prefers-reduced-motion: reduce` enabled (in Chrome DevTools: ⋮ → More tools → Rendering → "Emulate CSS media feature prefers-reduced-motion: reduce"). Reload. Constellation should appear fully drawn instantly. Section reveals should be instant. Top-dot pulse should not animate.

- [ ] **Step 7: Legacy-anchor smoke**

Test each legacy anchor redirect from Task 13 by manually navigating to:

```
website/index.html#features
website/index.html#smart-retrieval
website/index.html#advanced-features
website/index.html#developer-experience
website/index.html#security
website/index.html#whats-new
website/index.html#installation
website/index.html#usage
website/index.html#documentation
website/index.html#home
```

Each should jump to a sensible new section per the redirect map and rewrite the URL hash.

- [ ] **Step 8: Final commit (if any acceptance-criterion fixes were needed)**

If steps 5-7 surfaced issues that required code changes, commit the fixes:

```bash
git add -A website/
git commit -m "polish(website): post-Lighthouse fixes for redesign"
```

If no fixes needed, no commit — Task 16 is verification only.

---

## Done

The redesign is complete when:

1. `python website/validate.py` passes
2. Lighthouse Desktop scores: Performance ≥95 / Accessibility ≥95 / Best Practices ≥95 / SEO ≥95
3. All 4 breakpoints render without horizontal scroll
4. Constellation animates on first load and stays static under reduced-motion
5. Theme toggle persists across reloads
6. Tabs, copy buttons, hamburger, smooth scroll all functional
7. Schema.org `softwareVersion` reads `1.0.0`
8. CSS ≤ 32KB and JS ≤ 12KB (unminified)
9. No JS dependencies introduced
10. Legacy URL fragments redirect to sensible new sections

The commit log should show ~16 commits, one per task. Open a PR linking back to the spec at [docs/superpowers/specs/2026-05-02-website-v1-redesign-design.md](../specs/2026-05-02-website-v1-redesign-design.md).
