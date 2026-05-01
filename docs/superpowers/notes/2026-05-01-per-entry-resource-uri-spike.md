# Per-entry resource URI-template spike — 2026-05-01

**Question:** Which URI-template form does `mcp[cli]>=1.23.0` (FastMCP) accept
for per-entry ZIM resources, where the captured segment must contain `/`?

**SDK under test:** `mcp` 1.26.0 (the version `uv` resolves from the
`mcp[cli]>=1.23.0` pin in `pyproject.toml`; recorded in `uv.lock`).

## Forms tested

1. `zim://{name}/entry/{+path}` — RFC 6570 reserved expansion
2. `zim://{name}/entry/{path}` — plain capture
3. `zim://{name}/entry?path=...` — query-string fallback (base URI registered
   with no path placeholder; client appends `?path=` to request)

## Findings

| Form | Registers? | Routes URI containing `/` in captured segment? |
|------|------------|------------------------------------------------|
| 1. `{+path}` | **No** | n/a — registration fails |
| 2. `{path}`  | Yes    | **No** for literal `/`; **Yes** if client URL-encodes the slash as `%2F` |
| 3a. `?path=` (handler with `path` param) | **No** | n/a — registration fails (URI template lacks `path` placeholder) |
| 3b. `?path=` (handler without `path` param, client appends `?path=...`) | Yes (base) | **No** — `ResourceManager.get_resource` performs exact-string + template-regex matching, ignoring query strings |

**Conclusion:** None of the three forms route a literal `/` inside a captured
URI segment in `mcp` 1.26.0. Form 2 is usable if the client URL-encodes `/`
as `%2F` before requesting.

## Decision

**Task 17 will use form 2 (`zim://{name}/entry/{path}`) with URL-encoded slashes.**

The handler must URL-decode the captured `path` before looking up the entry in
the ZIM archive, and `list_resource_templates` documentation / examples must
make the encoding requirement explicit so clients know to encode `/` as `%2F`
(and other reserved characters appropriately) before issuing
`resources/read`.

This is not a punt to 1.1, but it is a constraint worth calling out in the
1.0.0 release notes.

## Task 17 must do

A consolidated checklist (the constraints below are derived from the findings;
do not skip any):

1. **Decorator URI:** register the resource with template
   `zim://{name}/entry/{path}` (Form 2).
2. **Handler decoding:** call `urllib.parse.unquote(path)` on the captured
   `path` before looking up the entry. Both `%2F` and `%2f` round-trip
   correctly through FastMCP's regex; treat them as `/` after decoding.
3. **Resource template `description` field:** state explicitly that clients
   must URL-encode `/` (and other reserved characters per RFC 3986) in the
   path segment before issuing `resources/read`. This is the
   client-facing surface.
4. **README:** document the encoding requirement in the per-entry resource
   section, with at least one worked example showing both the encoded request
   URI and the decoded entry path.
5. **CHANGELOG / 1.0.0 release notes:** call out the encoding constraint as a
   known quirk so users don't hit it without warning.
6. **Tests:** at minimum, exercise:
   - A path with no `/` (e.g. `zim://wikipedia_en/entry/Article`).
   - A path with one `/` encoded as `%2F` (e.g. `zim://wikipedia_en/entry/A%2FArticle`).
   - A path with multiple `/` encoded (e.g. `zim://wikipedia_en/entry/A%2FFoo%2FBar`).
   - The lowercase variant (`%2f`) since it also rounds-trips.
   - A literal-`/` request that should fail (`zim://wikipedia_en/entry/A/Article`)
     to lock in the negative case so a future SDK upgrade doesn't silently
     change behavior without a test catching it.

## Evidence

### Registration (Step 2)

`uv run pytest tests/test_per_entry_resource_spike.py -v --no-cov`:

```text
tests/test_per_entry_resource_spike.py::test_template_registers_and_resolves[zim://{name}/entry/{+path}] FAILED
tests/test_per_entry_resource_spike.py::test_template_registers_and_resolves[zim://{name}/entry/{path}]   PASSED
tests/test_per_entry_resource_spike.py::test_template_registers_and_resolves[zim://{name}/entry]          FAILED
```

- Form 1 fails because FastMCP scans the URI template with `re.findall(r"{(\w+)}", uri)`
  (`server.py:602`); `{+path}` does not match (the `+` is not in `\w`), so
  FastMCP sees the URI's placeholder set as `{"name"}` while the handler
  declares `{"name", "path"}` and raises `ValueError: Mismatch between URI parameters
  {'name'} and function parameters {'name', 'path'}`.
- Form 3 fails for the same mismatch reason: the URI declares only `{name}` but
  the handler asks for `path`. Registering a no-path handler (just `name`)
  succeeds, but then the client can't pass `path` via the template (see routing
  below).

### Routing (Step 3)

The matching regex is in `mcp/server/fastmcp/resources/templates.py:88`:

```python
pattern = self.uri_template.replace("{", "(?P<").replace("}", ">[^/]+)")
```

So `{path}` becomes `(?P<path>[^/]+)` — a named capture that explicitly
**excludes `/`**. Probed via the in-process resource manager:

```text
template = zim://{name}/entry/{path}
matches('zim://archive/entry/Article')        = {'name': 'archive', 'path': 'Article'}
matches('zim://archive/entry/A/Article')      = None
matches('zim://archive/entry/A%2FArticle')    = {'name': 'archive', 'path': 'A%2FArticle'}

get_resource('zim://archive/entry/Article')        -> OK
get_resource('zim://archive/entry/A/Article')      -> ValueError: Unknown resource
get_resource('zim://archive/entry/A%2FArticle')    -> OK   (path captured as 'A%2FArticle')
get_resource('zim://archive/entry/A%2fArticle')    -> OK   (lowercase encoding also works)
```

For form 3 (base URI `zim://{name}/entry`, no path placeholder, client appends
`?path=...`):

```text
get_resource('zim://archive/entry')                  -> OK
get_resource('zim://archive/entry?path=A/Article')   -> ValueError: Unknown resource
```

`ResourceManager.get_resource` (`resource_manager.py:84`) has no query-string
parsing — it does an exact-string lookup against concrete resources, then runs
each template's `^pattern$` regex against the full URI string. The `?` and
everything after are part of the string being matched, so a query-suffix URI
never matches a template that doesn't include `?...` literally.

### SDK behavior notes / quirks

- FastMCP 1.26.0 enforces a strict equality check between URI template
  placeholders (matched by `\w+`) and handler parameter names. There is no
  syntax in 1.26.0 for "match across `/` boundaries" — no `{+path}`, no
  `*path`, no `**path`, no escape, no per-segment override.
- The decision in Task 17 to use URL-encoded slashes works because
  `[^/]+` matches `%2F` (encoded slashes are literal `%`, `2`, `F` characters,
  none of which are `/`). The handler must call `urllib.parse.unquote()` on
  the captured `path` before treating it as a ZIM path.
- If a future FastMCP version adds RFC 6570 reserved expansion (`{+path}`) or
  any other escape, Task 17 should be revisited to drop the encoding hack.
- Concrete (non-template) resources are stored by exact URI string, so a
  precomputed concrete resource per entry is technically possible but
  impractical (a typical ZIM has tens of thousands to millions of entries).

## Files

- Spike test (deleted at end of task): `tests/test_per_entry_resource_spike.py`
- This note: `docs/superpowers/notes/2026-05-01-per-entry-resource-uri-spike.md`
