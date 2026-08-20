Look up links from one article — outbound/inbound link buckets or
related-article suggestions.

EXTRACT the direction before calling: `"outbound"` = the article's
own links (internal / external / media buckets); `"inbound"` = pages
that link TO it; `"related"` = "see also" by outbound-link overlap.

ALIASES: "links in <article>" / "what does <article> link to"
(outbound); "what links here" / "pages linking to <article>"
(inbound); "related to <article>" / "articles like <article>"
(related). Route through THIS tool with the matching direction.

DIRECTIONS:
  `"outbound"` (default) — paginated.
  `"inbound"`  — ranked by linker importance; paginated. Requires a
                 built link-graph sidecar (`openzim-mcp build
                 link-graph`); absent/stale → structured error.
  `"related"`  — one ranked set (no pagination).

PARAMETERS:
  zim_file_path   REQUIRED. The archive containing the article.
  entry_path      REQUIRED. The article whose links to inspect.
  direction       See DIRECTIONS above.
  kind            Outbound only — which bucket to return: "internal"
                  (default) / "external" / "media". One per call;
                  `category_totals` reports all three counts.
  cursor          Cursor handle (outbound/inbound).
  limit           Page size. Outbound 1-500 (default 100);
                  inbound and related 1-100 (default 10).
  offset          Pagination offset (outbound/inbound).

RESPONSE:
  LinksResponse (outbound) or RelatedArticlesResponse (inbound /
  related). Outbound is occurrence-level (document order, duplicates
  kept; `total` counts occurrences). `url` is the raw href; internal
  rows add `path`, the resolved entry path for `zim_get`. Related
  dedupes targets and reports `mention_count`.
  `category_totals.internal` excludes `#anchor` links (counted as
  `category_totals.anchor`) and anchor-wrapped assets, which move to
  the media bucket as `type: "asset"`.

ERRORS:
  Invalid `direction` → `invalid_direction`. Missing/stale inbound
  sidecar → `inbound_sidecar_unavailable`. Unknown `entry_path` →
  not-found envelope. Cursor from another archive/entry/tool →
  `cursor_context_mismatch` / `cursor_mismatch`.
