Fetch one named section of an article — by `section_id` (from the
TOC), with optional subsection inclusion.

EXTRACT a specific section before calling — use `zim_get(view="toc")`
first to discover available section ids if the caller didn't supply
one.

ALIASES: callers may say "section <X> of <article>", "show me the
<X> section", "<article> section <X>". Route through THIS tool.

PARAMETERS:
  zim_file_path        REQUIRED. The archive containing the article.
  entry_path           REQUIRED. The article whose section to fetch.
  section_id           REQUIRED. The TOC id (e.g. "History",
                       "Early_life") of the section.
  max_chars            Optional char cap on the section body.
  compact              Default True. Present for surface uniformity
                       with `zim_query` / `zim_get`. At v2.0 the
                       parameter is a no-op: section bodies always
                       ship in the bundle's compact rendering so the
                       slice shape matches `zim_get(view="full")`
                       output on the same article. v2.5 #18 wires a
                       true raw-text path.
  compact_budget       Named profile ("tiny"/"small"/"medium"/"large")
                       or raw integer char cap. Same v2.0 no-op
                       caveat as `compact`.

RESPONSE:
  GetSectionResponse — section body markdown (always compact-rendered
  at v2.0), metadata, and any nested subsections.

ERRORS:
  Returns a ToolErrorPayload on missing/unknown section_id with a
  hint listing the available section ids from the article's TOC.
