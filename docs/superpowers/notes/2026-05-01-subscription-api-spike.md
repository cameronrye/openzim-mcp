# FastMCP subscription API spike — 2026-05-01

**Question:** Does FastMCP (in `mcp[cli]>=1.23.0`) cleanly expose
resource-subscription handlers, or does adding subscription support require
reaching into private internals? If only fragile monkey-patching works, this
is slip trigger #1 for v1.0.0 and Tasks 19/20/21 defer to 1.1.

**SDK under test:** `mcp` 1.26.0 (the version `uv` resolves from the
`mcp[cli]>=1.23.0` pin in `pyproject.toml`; recorded in `uv.lock`).

## Surfaces probed

| Layer | Symbol | Public? | Status in 1.26.0 |
|-------|--------|---------|------------------|
| `FastMCP` | `subscribe_resource(s)`, `on_subscribe*`, `handle_subscribe`, `add_subscribe_handler`, `notify_resource_updated`, `send_resource_updated` | yes (would be) | **None exist.** No public method exposes subscriptions. |
| `FastMCP` | `_mcp_server` attribute | private (single underscore) | Exists; type is `mcp.server.lowlevel.server.Server`. |
| `Server` (lowlevel) | `subscribe_resource()` decorator | "public" on a class FastMCP doesn't expose | Works; installs handler in `request_handlers[SubscribeRequest]`. |
| `Server` (lowlevel) | `unsubscribe_resource()` decorator | same | Works; installs handler in `request_handlers[UnsubscribeRequest]`. |
| `ServerSession` | `send_resource_updated(uri)` | public on the session | Works; emits `notifications/resources/updated`. |
| `Server.get_capabilities()` | `ResourcesCapability.subscribe` | n/a | **Hardcoded `False`** regardless of registered handlers (`server.py:212`). |
| `FastMCP.run_*_async()` | `InitializationOptions` injection | not parameterised | All three transports build `InitializationOptions` inline via `self._mcp_server.create_initialization_options()`; no override hook. |
| `FastMCP` Context / session-from-background-task | n/a | yes inside a request (`Context.session`) | **No public way to reach a `ServerSession` outside an active request handler.** A filesystem-watch task that wants to broadcast must capture sessions itself in the `subscribe` handler. |

## Findings

1. **No public FastMCP surface for subscriptions.** Probing every plausible
   name yields exactly one positive: `_mcp_server` (a single-underscore
   "private but stable" attribute already used by FastMCP-extension code in
   the wild). See evidence block.

2. **The lowlevel `Server` cleanly supports subscribe/unsubscribe handler
   registration.** The decorators `subscribe_resource()` and
   `unsubscribe_resource()` install entries in `Server.request_handlers`
   keyed by `SubscribeRequest` / `UnsubscribeRequest` request types
   (`server.py:408-432`). The dispatch loop (`server.py:722`,
   `request_handlers.get(type(req))`) routes incoming subscribe requests
   normally — registration is real wiring, not cosmetic.

3. **`send_resource_updated()` is well-defined and public on
   `ServerSession`** (`session.py:226-234`). It builds a proper
   `ResourceUpdatedNotification` and forwards it through the standard
   notification path. No private internals required to *emit*.

4. **There is one durable rough edge:**
   `Server.get_capabilities()` hardcodes `subscribe=False` on
   `ResourcesCapability` even when subscribe handlers are registered
   (`server.py:209-213`). The advertised capabilities are what the client
   uses to decide whether to send `resources/subscribe`, so leaving this at
   `False` likely means well-behaved clients won't subscribe at all.
   Workaround: mutate `init.capabilities.resources.subscribe = True` after
   `create_initialization_options()` returns and before `Server.run()`
   reads it. Confirmed working in the spike test.

5. **FastMCP gives no hook for `InitializationOptions`.** All three
   `FastMCP.run_*_async()` methods inline
   `self._mcp_server.create_initialization_options()`
   (`server.py:759`, `848`, and similar in streamable HTTP). To inject the
   patched capabilities Task 21 must either:
     - **(a)** monkey-patch `mcp._mcp_server.create_initialization_options`
       to return a value with `resources.subscribe = True`, or
     - **(b)** subclass `FastMCP` and override the `run_*_async` methods
       (more code, same private dependency on `_mcp_server`), or
     - **(c)** replace `mcp.run()` with a direct call to
       `mcp._mcp_server.run(...)` and manage transports ourselves.
   **(a)** has the smallest blast radius and is the recommended path.

6. **No way to send `resources/updated` outside a request context.** The
   notification has to be emitted on a `ServerSession`, and FastMCP only
   exposes a session inside an active tool/resource handler via
   `Context.session` (`server.py:1298-1300`). A filesystem-watch task
   running in the background therefore must:
     - capture the active `ServerSession` at the moment the
       `subscribe_resource` handler fires (the handler is itself dispatched
       inside a request context — `Server.request_context` works there);
     - hold the session in our own subscriber registry, keyed by the URI
       being watched;
     - drop sessions on `unsubscribe_resource` and on session shutdown.
   This is application code we'd write anyway; the SDK does not provide a
   "broadcast to all subscribers of URI X" helper.

## Decision

**Subscriptions stay in 1.0.0.** The escape hatch is workable:

- **Handler registration:** stable lowlevel decorators on `_mcp_server`.
- **Notification emission:** public `ServerSession.send_resource_updated()`.
- **Capability advertisement:** one-line post-construction mutation of
  `InitializationOptions.capabilities.resources.subscribe = True`, applied
  via a monkey-patch of `_mcp_server.create_initialization_options`.

The blast radius is bounded (one private attribute + one wrapped method) and
all four surfaces (decorators, session method, capabilities model,
`InitializationOptions`) are stable parts of the lowlevel `mcp` package; the
only cross-version risk is that the lowlevel package itself is renamed or
restructured.

Task 21 will use the FastMCP private-internals approach described in the
checklist below.

## Risk note (private-API stability)

| Concern | Assessment |
|---------|-----------|
| `FastMCP._mcp_server` rename | Low. Single underscore, widely used in third-party FastMCP extensions; rename would be a breaking change called out in the SDK changelog. |
| `Server.subscribe_resource` removal | Very low. It's the only handler-registration path for the spec-defined `resources/subscribe` request and is documented in the lowlevel `Server` class. |
| `Server.get_capabilities` `subscribe=False` hardcode flips to `True` (or to "auto-detect from handlers") | Plausible, even desirable. If it does, our patch becomes a no-op (we'd be setting `True` -> `True`). The spike test we leave behind in Task 21's regression suite should pin this assumption with a "once this flips, simplify" hint. |
| `ServerSession.send_resource_updated` signature change | Low. Pinned by the public MCP spec: takes one URI, sends `notifications/resources/updated`. Pydantic types may evolve; signature won't. |
| `create_initialization_options` becomes parameterised by FastMCP | Plausible. If FastMCP starts accepting an `init_options=` argument on `run_*_async`, our monkey-patch becomes unnecessary; either path keeps working. |
| Hard breakage on 1.26 -> 1.27 | None observed in current 1.27 prereleases (not pinned; would need re-spike on bump). The SDK respects semver; a major restructure of `mcp.server.lowlevel` would be a 2.x event. |
| Typing/protocol guarantees | None — `_mcp_server` is `Server[LifespanResultT, RequestT]` (generic, not typed.Protocol). We pin via `mcp>=1.23.0,<2`. |
| Public migration path | None advertised by upstream. Nothing in the SDK suggests FastMCP plans to expose subscriptions. We'd be ahead of upstream. |

Mitigation: Task 21 adds a ceiling pin `mcp<2` (already implicit), wraps the
private-internals access in a single helper module so a future SDK change
touches one file, and ships a unit test that pins:

1. `FastMCP("x")._mcp_server` is an instance of
   `mcp.server.lowlevel.server.Server`.
2. `Server.subscribe_resource()` and `Server.unsubscribe_resource()` exist
   and produce entries in `request_handlers`.
3. `ResourcesCapability.subscribe` is still `False` after
   `get_capabilities()` (so we know whether our patch is still needed).
4. `ServerSession.send_resource_updated` is callable.

If any of those break on an `mcp` version bump, CI catches it.

## Task 21 must do

A consolidated checklist (the constraints below are derived from the
findings; do not skip any):

1. **Wrap the private-internals access in one helper module.** Suggested
   path: `openzim_mcp/subscriptions.py`. The helper exports:
     - `register_subscription_handlers(mcp: FastMCP, registry: SubscriberRegistry) -> None`
       which calls `mcp._mcp_server.subscribe_resource()` and
       `mcp._mcp_server.unsubscribe_resource()` to install handlers that
       insert/remove `(uri, ServerSession)` pairs into `registry`. Capture
       the session via `mcp._mcp_server.request_context.session` inside
       the handler (it's set during the subscribe request).
     - `patch_capabilities_to_advertise_subscribe(mcp: FastMCP) -> None`
       which monkey-patches `mcp._mcp_server.create_initialization_options`
       to return an `InitializationOptions` with
       `capabilities.resources.subscribe = True`.
     - `broadcast_resource_updated(registry, uri: AnyUrl) -> Awaitable[None]`
       which iterates the registry's sessions for `uri` and calls
       `session.send_resource_updated(uri)` on each. Sessions that error
       (already closed) are silently dropped from the registry.

2. **Apply the capability patch at startup**, in the same place we
   instantiate `FastMCP`. Order matters: install subscribe/unsubscribe
   handlers *before* the patch (so `ListResourcesRequest` is still in
   `request_handlers` when `get_capabilities` runs and the resources
   capability block exists to mutate).

3. **Subscriber registry semantics:**
     - keyed by URI string (post-`urllib.parse.unquote`, to match Task 17).
     - support both static URIs (`zim://files`) and per-archive URIs
       (`zim://{name}` after substitution).
     - drop entries on session close — wire this via a shutdown callback or
       try/except around `send_resource_updated` (the SDK raises when the
       session is closed).
     - thread-safety: handlers run on the asyncio loop; registry mutations
       must use `asyncio.Lock` if broadcast can race with subscribe/
       unsubscribe.

4. **Notification triggers:**
     - `zim://files`: emit when allowed-directory contents change (file
       added/removed). Hook into the existing instance tracker / file
       discovery code.
     - `zim://{name}`: emit when a specific ZIM file is replaced (mtime or
       inode change). The watcher is per-allowed-dir; map filesystem events
       back to the URI.
     - `zim://{name}/entry/...`: out of scope for 1.0; per-entry
       subscriptions are not in the plan.

5. **Capability assertion regression test** (replaces the deleted spike
   probe): assert that after server bootstrap,
   `mcp._mcp_server.create_initialization_options().capabilities.resources.subscribe is True`,
   AND that `subscribe_resource` is in `request_handlers`. Both keep us
   honest if a future SDK upgrade changes either side.

6. **Pin assumptions in tests:** mirror the spike's
   `test_lowlevel_subscription_handlers_register_without_error` so a 1.27+
   bump that breaks the decorator surface fails CI loudly.

7. **Document the private-internals dependency** in
   `openzim_mcp/subscriptions.py`'s module docstring with a pointer back to
   this spike note. Future maintainers should know exactly which SDK lines
   they're betting on (`server.py:212`, `server.py:408-432`,
   `session.py:226`).

8. **Release notes / CHANGELOG:** call out resource subscriptions as a new
   1.0.0 capability AND note the implementation depends on a private
   FastMCP attribute (`_mcp_server`); a future SDK release that exposes a
   public API will let us simplify.

9. **Tests at minimum:**
     - Subscribe handler captures session into registry.
     - Unsubscribe handler removes session from registry.
     - Broadcast helper emits exactly one `notifications/resources/updated`
       per subscribed session.
     - Closed-session entries are evicted on next broadcast.
     - Capability assertion regression test (item 5).
     - Lowlevel-API pin tests (item 6).

## Evidence

### Spike test output (Step 2 + Step 3)

`uv run pytest tests/test_subscription_api_spike.py -v -s --no-cov`:

```text
tests/test_subscription_api_spike.py::test_public_api_for_subscriptions PASSED
tests/test_subscription_api_spike.py::test_lowlevel_server_exposes_subscription_decorators PASSED
tests/test_subscription_api_spike.py::test_lowlevel_subscription_handlers_register_without_error PASSED
tests/test_subscription_api_spike.py::test_send_resource_updated_lives_on_server_session PASSED
tests/test_subscription_api_spike.py::test_capabilities_subscribe_is_hardcoded_false PASSED
tests/test_subscription_api_spike.py::test_capabilities_patch_via_create_initialization_options PASSED
tests/test_subscription_api_spike.py::test_fastmcp_run_methods_call_create_initialization_options_inline PASSED
============================== 7 passed in 0.02s ===============================
```

Key probe results:

```text
FastMCP attribute availability:
  subscribe_resource               -> False
  subscribe_resources              -> False
  on_subscribe                     -> False
  on_subscribe_resource            -> False
  handle_subscribe                 -> False
  resource_subscribe               -> False
  add_subscribe_handler            -> False
  send_resource_updated            -> False
  notify_resource_updated          -> False
  notify_resources_updated         -> False
  _mcp_server                      -> True
  low_level                        -> False
  lowlevel                         -> False
  server                           -> False
  mcp_server                       -> False

_mcp_server type: mcp.server.lowlevel.server.Server

request_handlers keys after registration:
  PingRequest, ListToolsRequest, CallToolRequest, ListResourcesRequest,
  ReadResourceRequest, ListPromptsRequest, GetPromptRequest,
  ListResourceTemplatesRequest, SubscribeRequest, UnsubscribeRequest

Advertised capabilities.resources: subscribe=False listChanged=True
After manual patch:                subscribe=True  listChanged=True
```

### Source citations

All paths under
`/Users/cameron/Developer/openzim-mcp-v1.0/.venv/lib/python3.12/site-packages/`.

- `mcp/server/lowlevel/server.py:209-213` — hardcoded `subscribe=False`:

  ```python
  if types.ListResourcesRequest in self.request_handlers:
      resources_capability = types.ResourcesCapability(
          subscribe=False, listChanged=notification_options.resources_changed
      )
  ```

- `mcp/server/lowlevel/server.py:408-432` — subscribe/unsubscribe decorators
  install handlers in `self.request_handlers[types.SubscribeRequest]` /
  `[types.UnsubscribeRequest]`. Marked `# pragma: no cover` upstream
  (i.e. SDK has no internal tests for them) — Task 21 fills that gap on
  our side.

- `mcp/server/lowlevel/server.py:722` —
  `if handler := self.request_handlers.get(type(req)):` is the dispatch
  edge that calls our subscribe handler when a client sends
  `resources/subscribe`.

- `mcp/server/lowlevel/server.py:240-244` —
  `Server.request_context` reads from a contextvar, set during request
  dispatch. This is how the subscribe handler reaches the active
  `ServerSession` to register it in our registry.

- `mcp/server/session.py:226-234` —
  `ServerSession.send_resource_updated(uri)` builds a
  `ResourceUpdatedNotification` and calls `send_notification`.

- `mcp/server/fastmcp/server.py:205-213` — FastMCP constructs
  `self._mcp_server = MCPServer(...)`. This is the only attribute that
  exposes the lowlevel server.

- `mcp/server/fastmcp/server.py:753-760` — `FastMCP.run_stdio_async`
  inlines `self._mcp_server.create_initialization_options()`. Same pattern
  at lines 845-849 (SSE) and inside `run_streamable_http_async`. There is
  no `init_options=` kwarg — hence the monkey-patch path.

- `mcp/server/fastmcp/server.py:1098-1300` —
  `Context` exposes `session` only inside a request via
  `self.request_context.session`. There is no FastMCP-level "list of all
  active sessions"; the subscriber registry is application state.

- `mcp/types.py:445-452` — `ResourcesCapability` has
  `model_config = ConfigDict(extra="allow")`, so post-construction
  mutation of `subscribe` is supported and will round-trip through
  pydantic JSON serialisation. Important: this means the patch is
  schema-stable, not a hack against pydantic.

- `mcp/types.py:917-965` — `SubscribeRequest`, `UnsubscribeRequest`,
  `ResourceUpdatedNotification`, `ResourceUpdatedNotificationParams` are
  all spec-defined, public types. Wire format is stable.

### Quirks

- `mcp.server.lowlevel.Server.subscribe_resource()` (singular) vs
  `mcp.server.lowlevel.Server.unsubscribe_resource()` — both singular. The
  task brief mentioned "subscribe_resources" (plural); that name does not
  exist in 1.26.0. Use the singular forms.
- The `# pragma: no cover` markers on the subscribe/unsubscribe decorators
  mean upstream's coverage suite doesn't exercise them. They work, but
  Task 21 is on its own for verifying behaviour.
- Capability mutation works because `ResourcesCapability` allows extra
  attributes (`extra="allow"`); writing `subscribe = True` post-construction
  is well-defined pydantic, not a hack.
- The lowlevel Server's `Server.request_context` is only valid inside a
  request handler. A subscribe handler runs in that context, which is why
  capturing the session there is safe; broadcasting from a background
  watcher is not — we capture sessions on subscribe and broadcast through
  them.

## Files

- Spike test (deleted at end of task): `tests/test_subscription_api_spike.py`
- This note: `docs/superpowers/notes/2026-05-01-subscription-api-spike.md`
