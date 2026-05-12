# ADR-001: Compact-mode plumbing for the advanced tool surface

**Status:** Accepted
**Date:** 2026-05-11
**Phase:** A/B/C cross-cutting; informs Phase F (#9 tool surface collapse).

## Context

`compact=True/False` is currently a first-class parameter on `zim_query`
(simple mode) and a `**kwargs` knob the simple-mode dispatcher forwards
into the data layer for a subset of tools (`get_entry_summary`,
`get_zim_entry`, `find_entry_by_title`). The advanced tool surface
(`tools/*.py`) does not expose `compact` explicitly.

Phase F (#9) collapses the 21-tool advanced surface to ~8. If `compact`
becomes a per-tool parameter on every kept tool, that's 20+ signature
additions today. If it stays simple-mode-only, Phase F's collapsed
tools will need a different mechanism (dispatcher shim, separate
compact tools, etc.).

## Decision

1. **Add `compact: bool = False` to the advanced tool registrations
   where it has well-defined meaning today** — i.e., where the
   underlying data layer already honors `compact` to render shorter
   output for small models. That set is:
   - `search_zim_file`
   - `search_with_filters`
   - `search_all`
   - `find_entry_by_title`
   - `get_search_suggestions`
   - `get_table_of_contents`
   - `get_article_structure`
   - `get_entry_summary`
   - `get_zim_entries`
   - `get_zim_entry`
2. **Skip `compact` on tools whose data layer doesn't honor it today**
   — `browse_namespace`, `walk_namespace`, `extract_article_links`,
   `get_related_articles`, `get_binary_entry`, `list_namespaces`,
   `get_section`, `get_zim_metadata`, `get_main_page`. Adding no-op
   parameters clutters the surface and trains models to pass arguments
   that don't matter. Phase F can decide per kept-tool whether
   `compact` belongs there.
3. **Document this contract on every tool that accepts `compact`**
   so its meaning is unambiguous: "When True, the response is rendered
   in compact form intended for small LLMs (Haiku-class, Llama-3-8B).
   Specifics vary by tool — typically a shorter snippet, less
   metadata, and dropped fields with low information density."
4. **Phase F (#9) decides** which compact strategy survives the
   collapse — per-tool param vs unified `compact` on every collapsed
   tool vs separate compact-mode endpoints. This ADR doesn't lock that
   call in; it just stops the asymmetry where simple-mode has compact
   but advanced-mode pretends it doesn't exist.

## Consequences

- Models calling advanced-mode tools can opt into compact rendering
  for the high-traffic content tools today without going through
  `zim_query`. This is the main reason Op2 mattered: a small-model
  caller may want fine-grained tool calls (advanced mode) AND compact
  output (small context).
- Phase F's spec must explicitly state whether the collapsed surface
  keeps `compact` as a per-tool param or moves it to a shared
  rendering layer. The Phase F brainstorm uses this ADR as input.
- No wire-format breaks today — every added `compact` parameter
  defaults to `False`, preserving v2.0.0a9 behavior on calls that
  don't pass it.

## Not chosen

- **"Add `compact` to every advanced tool unconditionally"** — too
  much surface area for no-op parameters; trains models to learn
  argument shapes that don't matter for half the tools.
- **"Defer the decision to Phase F brainstorm"** — leaves the
  simple/advanced asymmetry in place until Phase F lands, which
  may be months out.
- **"Build a shared dispatcher shim"** — over-engineered for the
  cost of the asymmetry; revisit during Phase F if compact rendering
  fans out further.
