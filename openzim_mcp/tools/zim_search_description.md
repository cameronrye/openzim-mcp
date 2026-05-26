Search a ZIM archive — three modes, one tool.

EXTRACT the search intent before calling. Pick the `mode` that matches
what the user actually needs; the wrong mode silently returns the
wrong shape of results.

MODES (pass one as `mode`):
  - "fulltext" (default) — Xapian BM25 search with optional
    `namespace` / `content_type` filters. Use for queries with
    multiple keywords ("history of Rome", "Tesla electricity") or
    when the caller wants snippets, not just titles. Cross-archive
    via `cross_file=True`.
  - "title" — Exact / typo-tolerant title lookup. Returns titles
    matching the query (case ladder + suggestion expansion +
    Levenshtein-1). Use when the caller knows the article name and
    wants to confirm it exists or find near matches ("find article
    titled Detroit"). Single-archive applies Z3/Z4/OPP-1 promotion;
    cross-archive (`cross_file=True`) returns raw matches without
    promotion (promotion is per-archive).
  - "suggest" — Prefix autocomplete via libzim SuggestionSearcher.
    Returns title candidates only — no snippets, no body. Use for
    typeahead-style completion ("prefix `Det`"). Does NOT support
    `cross_file=True` (libzim's SuggestionSearcher is per-archive).

ALIASES: callers may say "search", "find", "lookup", or "autocomplete".
All route through THIS tool — pick the matching `mode`.

PARAMETERS:
  query        REQUIRED. The user's search query.
  mode         One of {"fulltext", "title", "suggest"}. Default
               "fulltext".
  zim_file_path Optional. Omit for auto-selection of the single
               loaded archive, or use `cross_file=True` for
               multi-archive fan-out.
  cross_file   Default False. Set True to fan out across every
               loaded archive (modes "fulltext" and "title" only;
               "suggest" rejects this with `invalid_combination`).
  namespace    Only valid in mode="fulltext". Restricts search to
               one ZIM namespace letter (e.g. "C" for content).
               Silently ignored in other modes.
  content_type Only valid in mode="fulltext". Restricts search to
               one MIME bucket (e.g. "text/html").
  limit        Maximum results to return (default depends on mode).
  offset       Pagination offset (default 0).
  cursor       Phase B cursor pagination handle; overrides `offset`
               when set.

RESPONSE:
  Search-shape dict with `results` array. Each result carries
  `entry_path`, `title`, and (mode-dependent) `snippet`. The
  `_meta` envelope on title-mode results sets `promotion_applied`
  to True when the wired Criterion-C path hoisted a Z3/Z4/OPP-1
  candidate; False with a `hint` when cross-archive blocked the
  promotion pass.

ERRORS:
  Returns a ToolErrorPayload on:
    - mode="suggest" with cross_file=True (`invalid_combination`)
    - non-positive limit, negative offset (`invalid_limit`,
      `invalid_offset`)
    - missing archive when zim_file_path is required but cross_file
      is False and auto-selection fails
