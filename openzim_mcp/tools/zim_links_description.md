Look up links from one article — outbound link buckets or
related-article suggestions.

EXTRACT the direction before calling. `direction="outbound"` returns
the article's own outgoing links (internal / external / media
buckets, paginated). `direction="related"` returns articles
connected to this one by outbound-link overlap — the canonical
"see also" experience.

ALIASES: callers may say "links in <article>", "what does <article>
link to", "related to <article>", "articles like <article>". Route
through THIS tool with the matching direction.

PARAMETERS:
  zim_file_path     REQUIRED. The archive containing the article.
  entry_path        REQUIRED. The article whose links to inspect.
  direction         "outbound" (default) — outgoing links by bucket.
                    "related" — related articles via outbound-link
                    overlap.
  cursor            Phase B cursor pagination handle.
  limit             Page size.
  offset            Pagination offset (outbound mode only).

RESPONSE:
  LinksResponse (direction="outbound") or
  RelatedArticlesResponse (direction="related"). Both carry
  pagination metadata.

NOTE (v2.0 scope): `"inbound"` is NOT in the direction enum. Inbound
link discovery requires a link-graph sidecar that lands in v2.5 —
reserving an unusable enum value at v2.0 would create a small-model
failure mode where the model attempts it, eats an error, and gives
up. The schema-additive promotion to add `"inbound"` in v2.5 is
non-breaking.

ERRORS:
  Invalid `direction` returns `invalid_direction`. Missing or
  unknown `entry_path` returns the underlying data-layer error
  envelope.
