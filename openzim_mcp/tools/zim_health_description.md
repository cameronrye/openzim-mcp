Inspect the openzim-mcp server's state — or validate one archive — in one call.

With NO argument: returns health checks (cache stats, directory probes,
recommendations), configuration (allowed directories, cache config,
server PID), and loaded_archives (the ZIM files the server can read).
Collapses the legacy `get_server_health` + `get_server_configuration` +
`list_zim_files` triple into one answer to "what is this server, what
does it have, and is it OK".

With a `zim_file_path`: validates/diagnoses that one archive — runs
`Archive.check()` (integrity), reports checksum, index, and identity.

ALIASES: "is the server ok", "list archives", "what's loaded", "server
health" (no arg); "validate this zim", "is this archive corrupt" (with path).

PARAMETERS:
  zim_file_path   OPTIONAL. Omit for server state; pass to validate one archive.

RESPONSE:
  No arg → ServerHealthResponse `{health, configuration, loaded_archives, _meta}`.
  With path → ArchiveValidationResponse `{is_valid (check() result), has_checksum, checksum, has_fulltext_index, has_title_index, uuid, is_multipart, path, name, _meta}`.
