Inspect the openzim-mcp server's state in one combined response.

Returns three things: health checks (cache stats, directory probes,
recommendations), configuration (allowed directories, cache config,
server PID), and loaded_archives (the list of ZIM files the server
can read from). Collapses the legacy `get_server_health` +
`get_server_configuration` + `list_zim_files` triple into one
single-call answer to "what is this server, what does it have, and
is it OK".

ALIASES: callers may say "is the server ok", "list archives",
"what's loaded", "server health". Route through THIS tool — it
answers all three from one round trip.

PARAMETERS:
  (none — zim_health takes no arguments.)

RESPONSE:
  ServerHealthResponse (combined Phase F shape):
    - health: HealthStatus (legacy get_server_health output).
    - configuration: ServerConfig (legacy get_server_configuration).
    - loaded_archives: list[ArchiveInfo] (legacy list_zim_files).
    - _meta: standard envelope.
