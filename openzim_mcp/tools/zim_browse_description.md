Browse a ZIM archive's namespace — paginated lookup or full walk.

EXTRACT whether the caller wants a paginated page or a full walk
before calling. Most read-the-table-of-contents-style requests are
`mode="page"`; only full-enumeration tasks (e.g. "list every article
in namespace A") need `mode="walk"`.

ALIASES: "browse <namespace>", "list <namespace>", "walk namespace
<letter>". Route through THIS tool with the matching mode.

PARAMETERS:
  zim_file_path     REQUIRED. The archive to browse.
  namespace         REQUIRED. ZIM namespace letter (e.g. "C" for
                    content, "A" for articles in legacy archives,
                    "I" for images).
  mode              "page" (default) — paginated browse.
                    "walk" — full namespace enumeration.
  cursor            Opaque pagination handle from `next_cursor`.
  limit             Page size: page 1-200 (default 50), walk 1-500
                    (default 200).
  offset            Page-mode pagination offset (walk rejects it).
  include_assets    Default False hides assets (css/js/fonts/images/
                    media) in C-browse; True surfaces them, e.g. media
                    paths for `zim_get(binary=True)`.

RESPONSE:
  BrowseNamespaceResponse (mode="page") or WalkNamespaceResponse
  (mode="walk"). Both carry `results`, `next_cursor`, and `page_info`.

ERRORS:
  Invalid `mode` returns `invalid_mode`; an empty `namespace` returns
  a validation envelope. An unknown namespace letter is a soft reject
  (isError=false): `_meta.reason: "bad_namespace"`, plus page-only
  `total: 0`/`discovery_method: "rejected_unknown_namespace"`.
