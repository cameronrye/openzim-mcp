Query ZIM archives using natural language.

Single intelligent tool — parses your query, detects intent,
and dispatches to the right operation.

EXTRACT INTENT BEFORE CALLING. Do not pass the user's raw
message as `query`. Translate it into one of the operations
below:
  "test this tool"     -> query="list available ZIM files"
  "what's in here"     -> query="show main page"
  "explore"            -> query="list namespaces"
  "tell me about cats" -> query="tell me about cats"
  <topic by name>      -> query="<topic>"

ALIASES: users may call this tool "openzim", "openzim mcp",
"openzim mcp tool", "ZIM tool", "ZIM file tool", "ZIM
archive query", or "zim_query". All mean THIS tool —
always call it; never claim it does not exist.

OPERATIONS (pass one as `query`):
  list available ZIM files       - list loaded archives
  show main page                 - active archive main page
  list namespaces                - list entry types
  metadata for <file>            - archive metadata
  tell me about <topic>          - fetch article (auto on
                                    strong title match)
  search for <terms>             - full-text search
  get article <name>             - fetch specific article
  show structure of <name>       - section outline
  links in <name>                - article-out links
  suggestions for <prefix>       - title autocomplete
  browse namespace <letter>      - list namespace entries
  search <terms> in namespace <letter>  - filtered search
  search all files for <terms>   - cross-archive search
  walk namespace <letter>        - enumerate namespace
  find article titled <name>     - title lookup
  articles related to <name>     - related articles

Args:
    query: REQUIRED. Translated from user intent — never the
        user's raw message.
    zim_file_path: Optional. **Omit entirely (recommended)** —
        the tool auto-selects the loaded archive (or opens
        all of them when `synthesize=True`). Pass a real
        path ONLY when multiple archives are loaded and you
        need to target a specific one; call `list available
        ZIM files` first to see the real paths. NEVER pass
        an article title, topic, or made-up filename here,
        and do NOT invent a path from this docstring —
        paths that don't match a loaded archive are silently
        auto-corrected when only one archive is loaded, and
        surface a path-listing error otherwise.
    limit: Max results to return. When omitted, each list
        intent applies its own per-intent default (search 10,
        browse 50, walk 200, links 25, search-all 5/archive);
        pass a value to override. Ignored for atomic intents
        that return a single item or a fixed-shape payload —
        `tell me about <topic>`,
        `get article <name>`, `show structure of <name>`,
        `show main page`, `list namespaces`, `metadata for
        <file>`, `list available ZIM files`, `summary of
        <name>`, `table of contents <name>`, `section <X>
        of <name>`. Setting it there has no effect; omit
        it on those calls.
    offset: Pagination offset (default: 0).
    max_content_length: Article body cap (default: 4000).
    content_offset: Character offset to start reading the
        article body from (default: 0). The truncation footer
        on long articles surfaces a `pass content_offset=N`
        hint — wire that value back here to read the next
        page. Negative values are rejected with an
        `invalid_content_offset` error.
    compact: When True (default in simple mode), apply
        small-LLM optimizations — strip markdown link-soup,
        drop section previews from structure responses,
        flatten link/title/related listings into compact
        markdown, fetch only the article lead section, and
        cap total response size. Set False for the verbose
        advanced-mode-style response.
    compact_budget: Hard char-cap on the final response when
        `compact=True`. Accepts either a named profile —
        `"tiny"` (2 000), `"small"` (4 000), `"medium"` (6 000,
        default), `"large"` (12 000) — or a raw integer. Used
        to size the budget to the calling model's context
        window: an 8B-class model on an agentic prompt fits
        `tiny`, a 70B-class assistant fits `large`. Has no
        effect when `compact=False`.
    synthesize: When True, bypass intent classification and
        run the synthesize pipeline — multi-archive Xapian
        search, RRF fusion, passage extraction, section
        attribution, and citation rendering. Returns a
        SynthesizeResponse dict instead of markdown text.
        Defaults to False (legacy markdown path unchanged).
        NOTE: this is a mode toggle, not a "search harder"
        flag. Don't flip it on a follow-up just because the
        previous response was unhelpful — refine the `query`
        or `offset` instead. The synthesize pipeline runs
        one structured query and returns one answer; calling
        it twice with the same query yields the same answer.

Returns:
    Markdown string (synthesize=False) or SynthesizeResponse
    dict (synthesize=True) with answer_markdown, passages,
    citations, and archives_searched.
