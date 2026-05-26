Browse a ZIM archive's namespace — paginated lookup or full walk.

EXTRACT whether the caller wants a paginated page or a full walk
before calling. Most read-the-table-of-contents-style requests are
`mode="page"`; only full-enumeration tasks (e.g. "list every article
in namespace A") need `mode="walk"`.

ALIASES: callers may say "browse <namespace>", "list <namespace>",
"walk namespace <letter>". Route through THIS tool with the matching
mode.

PARAMETERS:
  zim_file_path     REQUIRED. The archive to browse.
  namespace         REQUIRED. ZIM namespace letter (e.g. "C" for
                    content, "A" for articles in legacy archives,
                    "I" for images).
  mode              "page" (default) — paginated browse via cursor.
                    "walk" — full namespace enumeration via cursor
                    state.
  cursor            Phase B cursor pagination handle.
  limit             Page size (default depends on mode).
  offset            Page-mode pagination offset (ignored in walk).

RESPONSE:
  BrowseNamespaceResponse (mode="page") or WalkNamespaceResponse
  (mode="walk"). Both carry `results`, `next_cursor`, and pagination
  metadata in `page_info`.

ERRORS:
  Invalid `mode` returns `invalid_mode`. Missing or unknown
  namespace returns the underlying data-layer error envelope.
