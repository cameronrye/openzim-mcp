Fetch one named section of an article — by `section_id` (from the
TOC), with optional subsection inclusion.

EXTRACT the section id before calling — `zim_get(view="toc")` lists
them if the caller didn't supply one.

ALIASES: callers may say "section <X> of <article>", "show me the
<X> section", "<article> section <X>". Route through THIS tool.

PARAMETERS:
  zim_file_path        REQUIRED. The archive containing the article.
  entry_path           REQUIRED. The article whose section to fetch.
  section_id           REQUIRED. The TOC id (e.g. "History").
  max_chars            Optional char cap on the section body.
  include_subsections  Default True: include nested subsections.
                       False: stop at the next heading of any level.
  compact              Default True: oversized tables become
                       placeholders and link markup is stripped (the
                       zim_get compact=True shape). False: raw body
                       with full tables and links.
  compact_budget       Named profile or integer char cap. Inert.

RESPONSE:
  GetSectionResponse — section body markdown, metadata, and any
  nested subsections.

ERRORS:
  Unknown section_id → ToolErrorPayload with `available_section_ids`
  (not a `hint`) and `closest_match`. Missing entry → `entry_not_found`.
