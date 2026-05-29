Inspect a ZIM archive's metadata + namespace inventory.

Returns the M-namespace fields (Name, Title, Creator, Date, …) plus
the per-namespace entry counts in one combined response. Replaces
the legacy `get_zim_metadata` + `list_namespaces` pair.

ALIASES: callers may say "metadata for <archive>", "what's in this
zim", "describe the archive". Route through THIS tool.

PARAMETERS:
  zim_file_path     REQUIRED. The archive to inspect.

RESPONSE:
  ArchiveMetadataResponse with:
    - metadata: flat dict[str, str] of M-namespace fields.
    - namespaces: list of NamespaceInfo (letter + total + diagnostics).
    - archive_identity `{uuid, is_multipart}` + index_capabilities
      `{has_fulltext_index, has_title_index}` — identity and whether
      search / suggestions will work.
    - counter_breakdown `{mimetype: count}` parsed from M/Counter;
      omitted when absent.
    - `_meta`: standard envelope.

  **NO `main_page_path` field.** The canonical main-page fetch is
  `zim_get(main_page=True)` — surfacing the path here would create
  two routes a small model would null-check unnecessarily.

ERRORS:
  Missing/invalid `zim_file_path` returns a structured error envelope.
