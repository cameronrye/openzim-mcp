Fetch entries from a ZIM archive — single, batch, binary, or main page.

EXTRACT the right path-shape before calling — the parameters form four
mutually-exclusive branches:

- Single entry, body view (default): pass `entry_path` + optional
    `view`. Returns the article body for view="full", a short summary
    for view="summary", a TOC tree for view="toc", a flat section
    list for view="structure".
- Single entry, binary: pass `entry_path` + `binary=True`. Returns
    raw bytes (image, video, PDF, etc.). `view` is locked to "full"
    in this branch.
- Batch: pass `entry_paths` (list of strings). Returns full bodies
    per entry; `view` is locked to "full" (a non-full `view` returns
    `invalid_path_combination`).
- Main page: pass `main_page=True` (no entry_path). Returns the
    archive's main page. `view`, `entry_path`, `entry_paths`,
    `binary` are all forbidden in this branch.

ALIASES: callers may say "get article", "fetch", "show me <article>",
"summary of <article>", "structure of <article>", "main page". Route
through THIS tool with the matching branch.

PARAMETERS:
  zim_file_path        REQUIRED. The archive containing the entry.
  entry_path           Single-entry path (string). Mutually exclusive
                       with entry_paths and main_page.
  entry_paths          Batch-mode path list. Mutually exclusive with
                       entry_path, binary, main_page.
  view                 Body slice when not binary/main_page:
                       "full" (default, full markdown body),
                       "summary" (short snippet),
                       "toc" (heading tree),
                       "structure" (flat section list).
  binary               Default False. Set True to fetch raw bytes
                       (single entry only).
  main_page            Default False. Set True for the archive's
                       main page (zero-path fetch).
  max_content_length   Body cap in chars for view="full".
  content_offset       Char offset into the body for view="full"
                       (default 0). Used with the truncation footer's
                       `pass content_offset=N` hint.
  compact              Default **False** (v2.0). Set True for
                       small-LLM compaction. v2.5 revisits the default.
  compact_budget       Inert in zim_get at v2.x (honored by `zim_query`,
                       not here) — does not cap the response.

RESPONSE:
  Branch-dependent dict — EntryResponse / BatchEntryResponse /
  EntrySummaryResponse / TableOfContentsResponse /
  ArticleStructureResponse / BinaryEntryResponse — or
  ToolErrorPayload on invalid combinations
  (`invalid_path_combination`).

ERRORS:
  Invalid branch combinations return structured
  `invalid_path_combination` with a hint naming the conflict.
  Defense-in-depth: even if a small model flattens the wire-schema
  oneOf and sends an impossible payload, the handler rejects it
  cleanly.
