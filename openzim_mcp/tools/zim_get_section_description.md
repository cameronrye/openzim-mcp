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
  compact              Default True. Small-LLM compaction. Pass
                       False to recover the legacy raw text shape —
                       this is a behavior break vs Phase C's
                       compact-by-default; v2.5 may revisit if
                       telemetry shows callers prefer raw.
  compact_budget       Named profile ("tiny"/"small"/"medium"/"large")
                       or raw integer char cap when compact=True.

RESPONSE:
  GetSectionResponse — section body markdown (compacted by default),
  metadata, and any nested subsections.

ERRORS:
  Returns a ToolErrorPayload on missing/unknown section_id with a
  hint listing the available section ids from the article's TOC.
