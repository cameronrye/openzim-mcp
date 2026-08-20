Look up links from one article — outbound/inbound link buckets or
related-article suggestions.

EXTRACT the direction before calling. `direction="outbound"` returns
the article's own outgoing links (internal / external / media
buckets). `direction="inbound"` returns pages that link TO this
entry. `direction="related"` returns articles connected by
outbound-link overlap — the canonical "see also" experience.

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
  limit           Page size.
  offset          Pagination offset (outbound/inbound).

RESPONSE:
  LinksResponse (outbound) or RelatedArticlesResponse (inbound /
  related). Outbound/inbound paginate; related is one ranked set.
  Outbound is occurrence-level: every link in document order,
  duplicates included, and `total` counts occurrences. Rows keep the
  raw href as `url`; internal rows add `path`, the resolved entry
  path to pass to `zim_get`. Related dedupes targets and reports
  `mention_count`. Outbound `category_totals.internal` excludes
  in-page `#anchor` links (counted as `category_totals.anchor`) and
  anchor-wrapped assets (images, fonts, scripts), which land in the
  media bucket as `type: "asset"`.

ERRORS:
  Invalid `direction` → `invalid_direction`. Missing/stale inbound
  sidecar → `inbound_sidecar_unavailable`. Missing/unknown
  `entry_path` → the underlying data-layer error envelope.
