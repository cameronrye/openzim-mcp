"""Chained-intent and multi-entity query detection for SimpleToolsHandler.

Extracted from ``simple_tools.py`` (post-v2.0.5 review sweep) as a mixin,
following the ``zim`` package's split of ``ZimOperations`` across
``_ContentMixin`` / ``_SearchMixin`` / etc.

Detects and guides two query shapes the dispatcher special-cases: chained
operations (``show structure of X then summarize Y``) and multi-entity
topics (``Berlin and Paris``). Holds the connector / operation-prefix regex
tables and the topic-shape predicates those paths rely on. The concrete
``SimpleToolsHandler`` supplies ``zim_operations`` and
``_recase_from_original`` (declared under ``TYPE_CHECKING``).
"""

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .intent_parser import IntentParser


class _ChainMixin:
    """Chained-intent / multi-entity detection for ``SimpleToolsHandler``."""

    if TYPE_CHECKING:
        from .zim_operations import ZimOperations

        zim_operations: "ZimOperations"

        def _recase_from_original(
            self, token: str, original_query: str
        ) -> str: ...

    # A11 B1: connector tokens that split a chained query into two
    # halves. Each connector is a whole-word match (surrounded by
    # whitespace or punctuation). The semicolon is a literal split
    # rather than a connector word.
    _CHAINED_INTENT_CONNECTORS = (
        r"\s+then\s+",
        r"\s+after\s+that\s+",
        r"\s*;\s+",
        r"\s+and\s+then\s+",
        r"\s+,\s+then\s+",
        # A16 post-a16 D1: clear chain markers. The right-promote
        # branch below projects the left's verb onto a bare topic-
        # shaped right half so ``tell me about Berlin also Paris``
        # → fires the chain warning. ``and`` / ``or`` / ``&`` /
        # ``,`` / ``/`` are deliberately NOT here — those connectors
        # appear inside real article titles (``Romeo and Juliet``,
        # ``Tom & Jerry``, ``Vienna, Austria``, ``TCP/IP``) often
        # enough that a hard chain warning false-fires too easily.
        # Those ambiguous cases are handled by
        # ``_soft_connector_footer`` on the resolved article instead,
        # which suppresses the warning when the returned title
        # already contains both halves.
        r"\s+also\s+",
        r"\s+plus\s+",
        r"\s*\.\s+(?=[A-Z])",
        r"\s*->\s*",
    )

    # A11 B1: verb-shaped leads we recognise on the right-hand side of
    # a chain. These are deliberately a subset of the intent vocab —
    # ``and`` and ``then`` already get split out; we want to confirm
    # the post-connector segment is an operation phrase, not free
    # prose.
    _CHAINED_OPERATION_PREFIX_RE = re.compile(
        r"^(?:"
        r"list\s+|"
        r"show\s+|"
        r"get\s+|"
        r"find\s+|"
        r"search\s+|"
        r"browse\s+|"
        r"tell\s+me\s+about\s+|"
        r"who\s+(?:is|was)\s+|"
        r"what\s+(?:is|are)\s+|"
        r"describe\s+|"
        r"explain\s+|"
        r"walk\s+namespace|"
        r"articles?\s+related\s+to\s+|"
        r"links?\s+in\s+|"
        r"suggestions?\s+for\s+|"
        r"summary\s+of\s+|"
        r"metadata\s+(?:for|about)\s+|"
        r"table\s+of\s+contents\b|"
        r"main\s+page"
        r")",
        re.IGNORECASE,
    )

    @classmethod
    def _chained_intent_guidance(cls, query: str) -> Optional[str]:
        """Return a guidance string when ``query`` chains two operation
        phrases with a connector — otherwise ``None``.

        H5: ``"tell me about berlin then list namespaces"`` was silently
        running just ``list namespaces`` (highest-confidence intent
        wins) and dropping the first half on the floor. Rather than
        guess which half the caller really meant, surface the ambiguity
        and ask them to split the work.

        Heuristic: split on a connector (then/and then/;), check that
        the left side starts with a recognised operation phrase AND the
        right side does too. Both halves matching means the caller
        described two operations, not one with a connective phrase in
        the middle ("links in Photosynthesis" doesn't trip this — no
        connector — and "tell me about then and now" doesn't trip
        either — the right side has no operation prefix).
        """
        if not query:
            return None
        # Post-a24 P1-D6: peel leaked ``param=value`` suffixes before the
        # chained-operation detector runs. ``parse_intent``'s strip
        # (intent_parser.py:_strip_param_leaks) runs on the FULL query
        # at parse time, but the dispatcher calls
        # ``_chained_intent_guidance(query)`` upstream of that —
        # ``query`` here is still the raw user input. Without this
        # mirror-strip, live ``tell me about Berlin limit=5 then list
        # namespaces`` surfaced a chained-intent rejection whose
        # ``**First op (left)**: tell me about Berlin limit=5`` carried
        # the leaked param verbatim, confusing the user who'd then copy
        # the suggested left-op and re-dispatch with the same leak.
        # Idempotent with ``parse_intent``'s downstream strip — both
        # produce identical output on a clean query.
        query = IntentParser._strip_param_leaks(query)
        # A15 post-a15 P4-D2 + P6-D3: strip leading politeness
        # (``please``, ``kindly``, ``could you``, ``can you``,
        # ``would you``, ``will you``) before splitting on the
        # connector. The chained-detection
        # `_CHAINED_OPERATION_PREFIX_RE` is anchored at ``^`` and only
        # matches operation verbs at the very start; any politeness
        # prefix pushes the verb past position 0 so ``left_is_op``
        # evaluates False, the gate fails, and the chain falls
        # through to normal intent classification — where
        # ``list_namespaces`` (highest confidence) silently wins over
        # the dropped ``tell me about`` half. Mirror the same
        # scaffold-strip ``_extract_tell_me_about`` uses (including
        # the loop so ``please could you tell me about X then ...``
        # also peels cleanly).
        for _ in range(3):
            before_query = query
            query = re.sub(
                r"^\s*(?:please|kindly)\s+", "", query, flags=re.IGNORECASE
            ).strip()
            query = re.sub(
                r"^\s*(?:could|can|would|will)\s+(?:you|we|i)\s+(?:please\s+)?",
                "",
                query,
                flags=re.IGNORECASE,
            ).strip()
            if query == before_query:
                break
        if not query:
            return None
        for connector_pat in cls._CHAINED_INTENT_CONNECTORS:
            parts = re.split(connector_pat, query, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) != 2:
                continue
            left, right = parts[0].strip(), parts[1].strip()
            if not left or not right:
                continue
            # A11 post-a11 L2: when the connector is ``then`` (not ``and
            # then``), an ``and`` may dangle on the end of the left half
            # — ``tell me about berlin and then list namespaces`` splits
            # to left=``tell me about berlin and`` / right=``list
            # namespaces``. Trim trailing connectors / orphan punctuation
            # so the suggested split-up call is clean for the caller to
            # paste back as a follow-up query.
            #
            # Implementation note: an earlier regex
            # ``\s+(?:and|or|but)\s*$|\s*[;,]\s*$`` tripped SonarCloud's
            # S5852 ReDoS check (multiple ``\s*`` / ``\s+`` quantifiers
            # in alternation). String ops mirror the original "strip one
            # of: trailing connector word OR trailing ;/, " semantics
            # with no backtracking risk — same approach as
            # ``_is_disambig_lead`` below.
            # a13 D6: trim until stable so we strip BOTH an orphan
            # connector word AND a trailing ``;`` / ``,`` when both are
            # present (e.g. ``tell me about DNA, and`` → ``tell me about
            # DNA``). Pre-fix, the ``for/else`` structure only entered
            # the punctuation branch when no connector matched, so
            # ``tell me about DNA, and then …`` left the trailing comma
            # unstripped after the ``and`` was removed.
            left = left.rstrip()
            while left:
                trimmed = False
                lower_left = left.lower()
                for _conn in ("and", "or", "but"):
                    _n = len(_conn)
                    if (
                        lower_left.endswith(_conn)
                        and len(left) > _n
                        and left[-_n - 1].isspace()
                    ):
                        left = left[:-_n].rstrip()
                        trimmed = True
                        break
                if not trimmed and left[-1] in ";,":
                    left = left[:-1].rstrip()
                    trimmed = True
                if not trimmed:
                    break
            if not left:
                continue
            # Post-b2 pass-3 (D1 sibling): peel trailing politeness from
            # EACH chain half before the rejection bullets render. The
            # universal ``_strip_trailing_politeness`` lives in
            # ``parse_intent`` (which runs DOWNSTREAM of this method);
            # without per-half mirroring, modal politeness inside a
            # chain (``tell me about Tokyo if you would then list
            # namespaces``) leaks into ``**First op (left):**
            # tell me about Tokyo if you would`` — the same UX leak
            # the post-a24 P1-D6 param-leak strip above was added to
            # plug. Stripping each half is structurally safe: the
            # ``_CHAINED_OPERATION_PREFIX_RE`` test checks the LEADING
            # verb, which the trailing strip can't touch.
            left = IntentParser._strip_trailing_politeness(left)
            right = IntentParser._strip_trailing_politeness(right)
            if not left or not right:
                continue
            # a13 D3 negative-case guard: append a space before the
            # prefix match so the regex's trailing ``\s+`` is satisfied
            # even when a half is JUST an operation verb prefix with
            # no topic content (``tell me about``). Without this,
            # ``tell me about then and now`` (a topic whose name
            # contains ``then``) split into left=``tell me about`` /
            # right=``and now``; pre-guard, the regex rejected the
            # bare verb (no content after), the D3 bare-topic branch
            # then mis-classified both halves as plain topics and
            # wrapped them with ``tell me about`` — chained guidance
            # fired for a single-topic query.
            left_is_op = bool(cls._CHAINED_OPERATION_PREFIX_RE.match(left + " "))
            right_is_op = bool(cls._CHAINED_OPERATION_PREFIX_RE.match(right + " "))
            # a13 D4: single-imperative-prefix continuation. ``tell me
            # about Photosynthesis and then about DNA`` splits to
            # left=``tell me about Photosynthesis`` (operation) /
            # right=``about DNA`` (continuation phrase that implicitly
            # inherits the left's verb). Pre-fix, the right side failed
            # the prefix regex (``about`` alone isn't an op verb) and
            # the splitter fell through to topic-fetch full-text
            # search on the literal concatenation. Recognise the
            # continuation shape and re-prefix the right so the user
            # sees the implied second call.
            if left_is_op and not right_is_op:
                cont_m = re.match(
                    r"^(?:about|of|for|with|on|in|into|to)\s+(\S.*)$",
                    right,
                    re.IGNORECASE,
                )
                if cont_m:
                    # Project the left's leading verb onto the right's
                    # bare topic. ``tell me about X and then about Y``
                    # becomes ``tell me about Y`` on the right.
                    verb_m = cls._CHAINED_OPERATION_PREFIX_RE.match(left)
                    if verb_m:
                        right = f"{verb_m.group(0).strip()} {cont_m.group(1).strip()}"
                        right_is_op = True
            # A16 post-a16 D1: right-promote for weak connectors. When
            # the left half carries an op verb and the right half is a
            # bare topic that LOOKS like a proper noun, the caller
            # almost certainly meant two queries. Project the left's
            # verb onto the right so both halves render in the chain-
            # rejection warning.
            #
            # Triple guard against over-firing on natural-language
            # phrases that contain a soft connector but mean one
            # topic (``Now and Then``, ``Pride and Prejudice``,
            # ``Romeo and Juliet``):
            #   1) ``_is_topic_shaped`` — caps token count + rejects
            #      mid-phrase strong connectors,
            #   2) right's first content token is uppercase (filters
            #      ``tell me about Berlin and the capital of
            #      Germany``-style prose),
            #   3) right is "substantive" — multi-token OR ≥5 chars OR
            #      contains a digit. The 5-char floor filters the
            #      common single-token English words ``Then`` / ``Now``
            #      / ``Here`` / ``This`` while still admitting real
            #      proper-noun topics (Paris/Berlin/Mercury/Photo
            #      synthesis...). Multi-token / digit-containing rights
            #      (``Apollo 12``, ``Mars rover``) are always
            #      substantive enough to promote.
            if left_is_op and not right_is_op and cls._is_topic_shaped(right):
                # Strip leading adverbials (``then``, ``next``, ``also``,
                # ``and``, ``finally``) so ``... . Then Paris`` (period
                # connector) projects to ``tell me about Paris`` rather
                # than ``tell me about Then Paris``. Adverbials only —
                # no real verbs.
                stripped_right = re.sub(
                    r"^(?:then|next|also|and|finally|after\s+that)\s+",
                    "",
                    right,
                    flags=re.IGNORECASE,
                ).strip()
                verb_m = cls._CHAINED_OPERATION_PREFIX_RE.match(left)
                # Pass-2 self-audit: require the LEFT bare topic to be
                # substantive too. Without this, the period+capital
                # connector mis-fires on common title abbreviations
                # (``Dr. Strange``, ``St. Louis``, ``Mt. Everest``,
                # ``Jr. Bandits``) — left's bare topic is the abbreviation
                # itself (1-2 chars), clearly not a chain situation.
                left_bare = left[verb_m.end() :].strip() if verb_m else ""
                if (
                    verb_m
                    and stripped_right
                    and stripped_right[0].isupper()
                    and cls._is_substantive_topic(stripped_right)
                    and cls._is_substantive_topic(left_bare)
                ):
                    right = f"{verb_m.group(0).strip()} {stripped_right}"
                    right_is_op = True
            # a13 D3: bare-topic chains on a strong connector
            # (``Biology; Chemistry``, ``DNA then Photosynthesis``).
            # Neither half has an operation verb. Pre-fix, this fell
            # through to topic-fetch, where the literal concatenation
            # got fuzzy-resolved to a tangentially-related article
            # (``Biology; Chemistry`` → ``Computational_Biology_&_
            # Chemistry``). When the connector is unambiguous (``;`` or
            # ``then``/``and then``/``after that``/``, then``) AND both
            # halves are topic-shaped (short, no internal connectors),
            # treat as chained and recommend explicit ``tell me about``
            # wrapping.
            if (
                not left_is_op
                and not right_is_op
                and cls._is_strong_chain_connector(connector_pat)
                and cls._is_topic_shaped(left)
                and cls._is_topic_shaped(right)
            ):
                left = f"tell me about {left}"
                right = f"tell me about {right}"
                left_is_op = right_is_op = True
            if left_is_op and right_is_op:
                return (
                    "**Chained Operations Detected**\n\n"
                    "**Issue**: your query looks like two separate "
                    "operations joined by a connector. The intent "
                    "parser handles one operation at a time — chained "
                    "queries would silently drop one half.\n\n"
                    f"**First op (left):** `{left}`\n\n"
                    f"**Second op (right):** `{right}`\n\n"
                    "**Fix**: issue them as two separate `zim_query` "
                    "calls so each gets its own response.\n"
                )
        return None

    # a13 D3: connectors strong enough to imply chaining even when
    # neither half carries an operation verb. ``,`` alone is excluded
    # — comma can legitimately appear inside a topic (``Vienna, Austria``).
    _STRONG_CHAIN_CONNECTOR_PATS = frozenset(
        {
            r"\s+then\s+",
            r"\s+after\s+that\s+",
            r"\s*;\s+",
            r"\s+and\s+then\s+",
            r"\s+,\s+then\s+",
        }
    )

    @classmethod
    def _is_strong_chain_connector(cls, connector_pat: str) -> bool:
        return connector_pat in cls._STRONG_CHAIN_CONNECTOR_PATS

    # a13 D3: tokens that look like the start of an operation verb
    # prefix. ``_is_topic_shaped`` rejects phrases containing these
    # so ``tell me about then and now`` (a single topic with prose
    # connectives) doesn't get mis-wrapped as a chained query when
    # the partial-prefix left ("tell me about") fails the op-verb
    # regex but is clearly not a bare topic phrase. Mirrors the
    # operation verb roots in ``_CHAINED_OPERATION_PREFIX_RE``.
    _OP_VERB_TOKENS = frozenset(
        {
            "list",
            "show",
            "get",
            "find",
            "search",
            "browse",
            "tell",
            "describe",
            "explain",
            "walk",
            "links",
            "suggestions",
            "summary",
            "metadata",
            "table",
            "main",
            "articles",
            "article",
            "who",
            "what",
        }
    )

    # A16 post-a16 D1 (pass-2): ambiguous connectors that can mean
    # either "two queries" (``Berlin and Paris``) or "one article
    # title" (``Romeo and Juliet``). Handled via the soft footer in
    # ``_handle_tell_me_about`` rather than a hard chain warning,
    # because firing chain on every ``X and Y`` mis-flags common
    # title shapes.
    _SOFT_CHAIN_CONNECTOR_PATS = (
        r"\s+and\s+",
        r"\s+or\s+",
        r"\s+vs\.?\s+",
        r"\s*,\s+",
        r"\s+&\s+",
        r"\s*/\s*",
    )

    def _soft_connector_footer(
        self,
        topic: str,
        top_title: str,
        *,
        zim_file_path: Optional[str] = None,
        top_path: Optional[str] = None,
        original_query: Optional[str] = None,
    ) -> Optional[str]:
        """A16 post-a16 D1 (pass-2): when ``topic`` contains an ambiguous
        connector between two substantive proper-noun-shaped halves
        AND the returned ``top_title`` only includes one of them,
        return a footer reminding the caller that the other half was
        dropped.

        Suppressed when:
          * ``top_title`` includes BOTH halves (the article title
            spans the connector — ``Romeo and Juliet`` /
            ``Tom and Jerry`` / ``Vienna, Austria``),
          * ``top_title`` includes NEITHER half (unclear which side
            was picked — surface no guidance rather than guess).

        The footer guides the caller to a clean follow-up query for
        the dropped half without raising a hard chain warning that
        would force the caller to re-run for the obvious-single
        topic cases.

        Post-a18 P3-D2: ``zim_file_path`` / ``top_path`` (optional)
        unlock title-alias resolution as a fallback for the
        "neither half is a substring" branch. The substring check is
        unreliable when the resolved title is an English-aliased form
        of a non-Latin topic half (``München`` resolves to
        ``Munich`` via the title-alias index; substring matching
        can't see through that). When both halves miss the substring
        check, probe the title index for each half; if a half
        resolves to ``top_path``, treat it as "in title"
        semantically. Without these kwargs the function falls back
        to the legacy substring-only behaviour.
        """
        if not topic or not top_title:
            return None
        topic_stripped = topic.strip()
        if not topic_stripped:
            return None
        for pat in self._SOFT_CHAIN_CONNECTOR_PATS:
            m = re.search(pat, topic_stripped, re.IGNORECASE)
            if not m:
                continue
            # Post-a17 P1-D1: when the title itself contains the same
            # connector pattern (``Big Rapids, Michigan`` carries a
            # comma; ``Romeo and Juliet`` carries ``and``), the
            # connector is structural to the title, not a multi-entity
            # separator. The ``left_in == right_in`` branch below
            # catches the simple case where both topic halves are full
            # substrings — but subject-attribute prefixes
            # (``notable people from Big Rapids, Michigan``,
            # ``musicians from Romeo and Juliet``) leave the left half
            # longer than the title, defeating that suppression. The
            # docstring already names ``Vienna, Austria`` as a case
            # this footer should NOT fire for; the earlier guard makes
            # it work in the prefixed-topic shape too.
            if re.search(pat, top_title, re.IGNORECASE):
                return None
            left = topic_stripped[: m.start()].strip()
            right = topic_stripped[m.end() :].strip()
            if not left or not right:
                continue
            # Both halves must look like substantive proper-noun
            # phrases (filters ``He or she`` and other prose where
            # the connector word is a normal English particle).
            if not self._is_substantive_topic(left) or not self._is_substantive_topic(
                right
            ):
                continue
            title_lower = top_title.lower()
            left_in = left.lower() in title_lower
            right_in = right.lower() in title_lower
            if not (left_in and right_in) and zim_file_path and top_path:
                # Post-a18 P3-D2: substring check fails when the
                # resolved title is an English-aliased form of a
                # non-Latin half (München → Munich). Fall back to
                # title-alias resolution: probe the title index for
                # each half and treat any half whose top-scored hit
                # equals ``top_path`` as "in title". Cheap (in-memory
                # title-index hit).
                #
                # Post-a20 P1-D2: previously gated on
                # ``not left_in and not right_in`` (only ran when BOTH
                # halves missed the substring check), which left the
                # asymmetric alias case unsuppressed —
                # ``tell me about Köln or Cologne`` returned the
                # Cologne article with a footer suggesting
                # ``tell me about Köln`` even though Köln's title-index
                # entry redirects right back to Cologne, sending the
                # user on a 2-hop journey. Same shape for
                # ``京都 or Kyoto``, ``上海 or Shanghai``,
                # ``München or Munich`` (and the reverse-order forms).
                # Widen the gate to ``not (left_in and right_in)`` so
                # the alias probe runs whenever EITHER half is missing
                # in substring; the probe still only upgrades a half's
                # ``_in`` to True when its top-scored title-index hit
                # equals ``top_path`` (so unrelated halves like
                # ``Berlin and 東京`` still drop correctly — Berlin
                # resolves to Berlin, not to 東京). The irreducible
                # ``東京 or Tokyo`` case stays unfixed because 東京
                # title-resolves to its own disambig article, not to
                # Tokyo.
                if not left_in:
                    left_in = self._half_resolves_to_top(zim_file_path, left, top_path)
                if not right_in:
                    right_in = self._half_resolves_to_top(
                        zim_file_path, right, top_path
                    )
            if left_in == right_in:
                # Both in title → returned article is the full
                # phrase (``Romeo and Juliet``); neither in title →
                # unclear which half was picked. Either way, no
                # actionable footer.
                return None
            picked = left if left_in else right
            dropped = right if left_in else left
            # Post-b1 P1-D2: recase picked/dropped against the
            # original pre-Rule-1-lowercase query so the footer echoes
            # the caller's casing.
            if original_query:
                picked = self._recase_from_original(picked, original_query)
                dropped = self._recase_from_original(dropped, original_query)
            connector_display = m.group(0).strip() or "(connector)"
            return (
                f"\n\n_Note: your query contained `{connector_display}` "
                f"between two proper-noun phrases. Returned the article "
                f"for `{picked}`. For `{dropped}`, query separately "
                f"with `tell me about {dropped}`._"
            )
        return None

    # Post-a21 P1-D2/D3/D4: when the iterative single-pattern split
    # below applies one connector pattern before the next, a half can
    # end up with a leftover leading conjunction OR a leftover trailing
    # comma. ``Köln, München, and Berlin`` after the ``\s+and\s+`` pass
    # is ``["Köln, München,", "Berlin"]``; the subsequent ``\s*,\s+``
    # pass over ``"Köln, München,"`` yields ``["Köln", "München,"]``
    # because the regex requires whitespace AFTER the comma and there's
    # none at end-of-string. ``Lions, Tigers, and Bears`` — same shape
    # but the leftover is ``"and Bears"`` because the comma-pass split
    # eats the ``", "`` and leaves ``"and"`` as a leading-conjunction
    # prefix. Strip both shapes per-half so the final list is clean.
    #
    # String-based (not regex) so SonarCloud's S5852 polynomial-
    # backtracking flag stays quiet — alternation + ``\s+``/``$`` in
    # one pattern keeps tripping the static analyzer despite the
    # actual runtime being linear in the half length. Longest-first
    # ordering so ``vs.`` matches before ``vs``.
    _CONJUNCTION_SUFFIXES = (" and", " or", " vs.", " vs", " &")
    _CONJUNCTION_PREFIXES = ("and ", "or ", "vs. ", "vs ", "& ")

    @staticmethod
    def _looks_like_slashed_compound(text: str) -> bool:
        """Post-a23 P1-D1: return True iff ``text`` looks like a single-
        entity slashed compound that the chain detector should NOT split.

        Heuristic: exactly one ``/`` between two halves; either
          * both halves are letter-only (Unicode-aware, ``&`` allowed for
            acronyms like ``R&B``) AND ``min(len) ≤ 4`` — covers acronyms
            like ``TCP/IP``, ``AC/DC``, ``Either/Or``, ``A/B`` AND short
            paired-concept compounds like ``Yin/Yang``, ``Hot/Cold``,
            ``Wet/Dry``, ``Light/Dark``, ``Mac/Cheese``, OR
          * both halves are digit-only AND ``min(len) ≤ 2`` — covers
            date / ratio / sports-season shapes like ``9/11``, ``24/7``,
            ``5/4``, ``12/24``, ``2024/25``.

        Mixed alphanumeric halves (``A/4``) split — those are typically
        two separate entities. Longer proper-noun pairs
        (``Berlin/Munich`` min=6, ``Lions/Tigers`` min=5,
        ``2024/2025`` min=4-digit) split too.

        Post-a24 P1-D1 / P1-D2 widen-out: the original ≤2 letter floor
        was tuned for short ALL-CAPS acronyms and silently dropped two
        sibling classes. Live a24 sweep observed:
          * ``9/11 and World War II`` decomposed to ``["9", "11", "World
            War II"]`` chain rejection — but ``9/11`` is a single event.
            Same shape: ``24/7``, ``5/4``.
          * ``Yin/Yang and the Tao`` decomposed to ``["Yin", "Yang", "the
            Tao"]`` — Yin and Yang both failed substantive (3-4 char
            mixed-case ASCII), chain abandoned silently, returned Tao
            with the user's paired concept Yin/Yang silently dropped.
            Same shape: ``Hot/Cold``, ``Wet/Dry``, ``On/Off`` (when
            followed by another half).

        Original ``\\s*/\\s*`` pass in ``_SOFT_CHAIN_CONNECTOR_PATS``
        fragments before the substantive check; this helper is the
        compound-guard called from ``_split_multi_entity`` to skip the
        slash pass for shapes that look like a single entity.
        """
        parts = text.split("/")
        if len(parts) != 2:
            return False
        stripped_parts = [p.strip() for p in parts]
        if not all(stripped_parts):
            return False

        # Shape detection: both halves all-letter (Unicode-aware) or
        # both halves all-digit. Mixed shapes don't get compound
        # treatment. ``isalpha`` is Unicode-aware in Python 3 so
        # accented acronyms / non-Latin halves work.
        all_letter = all(
            all(ch.isalpha() or ch == "&" for ch in p) for p in stripped_parts
        )
        all_digit = all(all(ch.isdigit() for ch in p) for p in stripped_parts)

        if all_digit:
            # Digit halves: ≤2 chars per half is the date/ratio shape
            # (9/11, 24/7, 5/4, 12/24, 2024/25 — the last has min=2 even
            # though max=4). Excludes 2024/2025 (min=4) which is more
            # naturally two distinct years.
            return min(len(p) for p in stripped_parts) <= 2
        if all_letter:
            # Letter halves: ≤4 picks up the post-a24 sibling class of
            # short paired-concept compounds (Yin/Yang min=3, Hot/Cold
            # min=3, Wet/Dry min=3, Mac/Cheese min=3, Salt/Pepper min=4)
            # without affecting longer proper-noun pairs (Berlin/Munich
            # min=6, Tokyo/Kyoto min=5).
            return min(len(p) for p in stripped_parts) <= 4
        return False

    @classmethod
    def _split_multi_entity(cls, topic: str) -> Optional[List[str]]:
        """Split ``topic`` into N substantive halves on any soft
        connector. Returns the list iff N ≥ 3 AND every half passes
        ``_is_substantive_topic``; otherwise None.

        Used by ``_multi_entity_chain_guidance`` to decide whether a
        topic deserves the structured ``Multi-Entity Chain Detected``
        rejection. The 2-entity case stays with the existing
        ``_soft_connector_footer`` post-resolution path (post-a18
        P3-D2 + post-a20 P1-D2).

        Implementation note: applies each entry of
        ``_SOFT_CHAIN_CONNECTOR_PATS`` as a SEPARATE ``re.split``
        pass over the running parts list, rather than joining them
        into one alternation regex. The combined-alternation form
        (``\\s+and\\s+|\\s*,\\s+|...``) trips SonarCloud's S5852
        polynomial-backtracking flag because every alternative
        starts with a ``\\s+`` or ``\\s*`` quantifier and the
        engine could in principle try many overlapping prefixes at
        each position. Iterative single-pattern splits match the
        existing codebase convention (see ``_search_query_tail``'s
        three-token decomposition for the same defensive shape) and
        avoid the static-analysis flag entirely. Cost is O(N · P)
        per topic where P ≤ 6 — a constant — so the runtime cost is
        identical in practice.
        """
        if not topic or not topic.strip():
            return None
        parts: List[str] = [topic.strip()]
        for pat in cls._SOFT_CHAIN_CONNECTOR_PATS:
            next_parts: List[str] = []
            is_slash_pat = pat == r"\s*/\s*"
            for part in parts:
                # Post-a23 P1-D1: don't split slashed compounds whose
                # halves look like a single acronym / 2-letter
                # conjunction (TCP/IP, AC/DC, Either/Or, A/B). See
                # ``_looks_like_slashed_compound`` for the heuristic.
                if is_slash_pat and cls._looks_like_slashed_compound(part):
                    next_parts.append(part)
                    continue
                next_parts.extend(re.split(pat, part, flags=re.IGNORECASE))
            parts = next_parts
        cleaned: List[str] = []
        # Post-a22 P1-D1: the leading-conjunction strip exists to clean
        # leftover ``and ``/``or ``/``& `` prefixes that the iterative
        # split CAN produce when the comma-pass runs before the and-pass
        # (e.g. ``Lions, Tigers, and Bears`` under a reordered pattern
        # list would leave ``and Bears`` as a half). The CURRENT pattern
        # order (``and`` → ``or`` → ``vs`` → ``,`` → ``&`` → ``/``)
        # consumes leading conjunctions in pass 1, so the leftover-
        # prefix shape doesn't arise organically — but the strip is
        # kept as defensive code against future reorderings.
        #
        # The defensive strip MUST NOT apply to the half that occupies
        # the START of the original topic, where a leading ``And`` /
        # ``Or`` / ``&`` is real title content (``tell me about And
        # Then There Were None and Hercule Poirot and Murder on the
        # Orient Express`` produced rejection bullets ``Then There
        # Were None`` / ``Hercule Poirot`` / ``Murder on the Orient
        # Express`` — the leading "And" got mangled away. Worse,
        # ``Or Else and Death and Taxes and Pride and Prejudice``
        # stripped ``Or Else`` to ``Else`` which failed
        # ``_is_substantive_topic`` (4 chars, single token, no digit,
        # no non-ASCII letter), aborting the multi-entity rejection
        # silently and dropping 4 of 5 entities through to
        # ``tell_me_about`` resolution).
        #
        # Skipping the FIRST non-empty half preserves the defensive
        # strip for hypothetical reordered futures while protecting
        # legitimate first-word conjunctions in the original topic.
        # Iterative ``re.split`` preserves order, so the first non-
        # empty entry in ``parts`` corresponds to the leading prefix
        # of the original topic — even after multiple split passes.
        seen_first_half = False
        for raw in parts:
            if not raw:
                continue
            # Strip whitespace + leftover punctuation that the
            # iterative connector splits couldn't trim (trailing
            # commas / semicolons / periods that end a half because
            # the comma-pattern wanted a trailing ``\s+``).
            p = raw.strip(" \t,;.")
            if not p:
                continue
            is_first_half = not seen_first_half
            seen_first_half = True
            # Strip leading conjunction word + whitespace
            # (case-insensitive) on every half EXCEPT the first —
            # see P1-D1 explanation above. String-prefix scan rather
            # than regex so S5852 stays quiet.
            if not is_first_half:
                lower_p = p.lower()
                for prefix in cls._CONJUNCTION_PREFIXES:
                    if lower_p.startswith(prefix):
                        p = p[len(prefix) :].lstrip()
                        break
            # Strip trailing conjunction word preceded by whitespace
            # (case-insensitive); rstrip stray punctuation that
            # follows. Applied to every half (including the first) —
            # a trailing conjunction is always split leftover, never
            # part of a real article title at the END of a topic.
            p = p.rstrip(" \t,;.")
            lower_p = p.lower()
            for suffix in cls._CONJUNCTION_SUFFIXES:
                if lower_p.endswith(suffix):
                    p = p[: -len(suffix)].rstrip(" \t,;.")
                    break
            if p:
                cleaned.append(p)
        if len(cleaned) < 3:
            return None
        if not all(cls._is_substantive_topic(p) for p in cleaned):
            return None
        return cleaned

    @staticmethod
    def _path_matches_topic_loosely(path: str, topic: str) -> bool:
        """True when an article-path (underscored, possibly punctuated)
        normalises to the same word sequence as ``topic``. Used to
        suppress the multi-entity chain warning for real multi-entity
        article titles (``Earth, Wind & Fire`` /
        ``Lions, Tigers, and Bears`` / etc.) — the title-index probe
        returns a path that, once normalised, equals the topic.
        """
        if not path or not topic:
            return False

        def _norm(s: str) -> str:
            s = s.lower().replace("_", " ")
            # \w in Python re is Unicode by default; this keeps
            # letters / digits / underscores → spaces and drops the
            # rest (commas, ampersands, etc.).
            s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
            s = re.sub(r"\s+", " ", s).strip()
            return s

        return _norm(path) == _norm(topic)

    def _multi_entity_chain_guidance(
        self,
        intent: str,
        params: Dict[str, Any],
        zim_file_path: str,
    ) -> Optional[str]:
        """Post-a21 P1-D2/D3/D4: return a structured chain rejection
        when ``intent`` is ``tell_me_about`` and the topic names 3+
        substantive entities joined by soft connectors, UNLESS the
        whole-topic title-index probe resolves to a path that loosely
        matches the topic (real multi-entity titles like
        ``Earth, Wind & Fire``).

        Returns None to fall through to normal resolution; returns a
        structured Markdown body when the chain should be rejected.

        Post-b1 P1-D2: when ``params["_pre_rewrite_query"]`` is set
        (the original, pre-Rule-1-lowercase query), bullets echo each
        entity in the caller's original casing instead of Rule 1's
        lowercased form. Pre-fix, ``tell me about Köln, München, and
        Berlin`` returned bullets reading ``tell me about köln`` /
        ``münchen`` / ``berlin`` — corrupted diacritics + casing that
        broke the user's recovery copy-paste path.
        """
        if intent != "tell_me_about":
            return None
        topic = (params.get("topic") or "").strip() if isinstance(params, dict) else ""
        if not topic:
            return None
        halves = self._split_multi_entity(topic)
        if not halves:
            return None
        # Post-b1 P1-D2: recase each half against the original query.
        original_query = (
            params.get("_pre_rewrite_query") if isinstance(params, dict) else None
        )
        if isinstance(original_query, str) and original_query:
            halves = [self._recase_from_original(h, original_query) for h in halves]
        # Probe the title index for the whole topic — if it resolves
        # cleanly to a single article whose path loosely matches the
        # topic, the user meant a real multi-entity title (band name,
        # movie title, idiom) and the chain warning would false-fire.
        try:
            data = self.zim_operations.find_entry_by_title_data(
                zim_file_path, topic, cross_file=False, limit=1
            )
        except Exception:
            data = None
        if isinstance(data, dict):
            results = data.get("results") or []
            if results and isinstance(results[0], dict):
                hit = results[0]
                hit_path = str(hit.get("path") or "")
                try:
                    score = float(hit.get("score") or 0)
                except (TypeError, ValueError):
                    score = 0.0
                # Score >= 1.0 from the title index means an exact
                # canonical-title hit; loose-path match catches cases
                # where the score is fuzzy but the path obviously
                # spans every entity (``Earth,_Wind_&_Fire`` for
                # ``Earth, Wind & Fire``).
                if score >= 1.0 or self._path_matches_topic_loosely(hit_path, topic):
                    return None
        bullets = "\n".join(f"  - `tell me about {h}`" for h in halves)
        return (
            "**Multi-Entity Chain Detected**\n\n"
            f"**Issue**: your query names {len(halves)} entities joined "
            "by soft connectors (`and` / `or` / `,` / `&` / `vs` / `/`). "
            "The intent parser returns one article at a time — silently "
            f"dropping {len(halves) - 1} of them would be confusing.\n\n"
            f"**Detected entities**:\n{bullets}\n\n"
            "**Fix**: issue each as a separate `zim_query` call so "
            "every entity gets its own response.\n\n"
            "<!-- intent=multi_entity_chain_rejected cert=1.00 -->"
        )

    def _half_resolves_to_top(
        self, zim_file_path: str, half: str, top_path: str
    ) -> bool:
        """Post-a18 P3-D2 helper: probe the title index for ``half`` and
        return True iff its top-scored title-index hit's path equals
        ``top_path``. The fallback substring check in
        ``_soft_connector_footer`` uses this to recognise non-Latin
        topic halves that resolve to English-aliased titles
        (``München`` -> ``Munich``).

        Errors in the backend are swallowed (return False) so a
        transient failure can't widen the footer's behaviour
        accidentally — the substring check stays authoritative when
        title-alias probing can't help.
        """
        try:
            data = self.zim_operations.find_entry_by_title_data(
                zim_file_path, half, cross_file=False, limit=1
            )
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        results = data.get("results") or []
        if not results:
            return False
        first = results[0]
        if not isinstance(first, dict):
            return False
        return str(first.get("path") or "") == top_path

    @classmethod
    def _is_substantive_topic(cls, text: str) -> bool:
        """A16 post-a16 D1 helper: return True iff ``text`` carries
        enough lexical weight to plausibly name an article on its own.

        Used by the right-promote branch of the chain detector to
        filter out single-token English sentence-words (``Then`` /
        ``Now`` / ``Here`` / ``This`` / ``Both``) that happen to
        survive ``_is_topic_shaped`` (1 token, capitalised, no
        connectors) but almost never name a Wikipedia article on
        their own.

        Heuristic: substantive iff any of —
          * ≥2 tokens (multi-word proper nouns / titles),
          * ≥5 characters in the longest token (real proper nouns
            tend to be longer than short adverbials),
          * contains a digit (``Apollo 12``, ``1969`` etc.),
          * contains a non-ASCII letter and length ≥2 (CJK ideograms,
            German umlaut city names like ``Köln``, Greek toponyms
            like ``Αθήνα`` — a single CJK ideogram or accented vowel
            carries roughly a syllable of lexical weight, so the
            5-ASCII-char threshold systematically over-rejects real
            non-Latin proper nouns).
        """
        stripped = text.strip()
        if not stripped:
            return False
        tokens = stripped.split()
        if len(tokens) > 1:
            return True
        if any(ch.isdigit() for ch in stripped):
            return True
        if len(stripped) >= 5:
            return True
        # Post-a19 P1-D3: the ASCII-length-5 threshold was tuned for
        # English particles like ``Now`` / ``Both`` / ``Here``, but it
        # also rejects real non-Latin proper nouns (``東京`` = 2 chars,
        # ``Köln`` = 4 chars, ``北京`` = 2 chars). The post-a17 Unicode
        # tail-tokenisation fix (a18) lets the resolver REACH these
        # topics; this fix lets the chain detector + soft-connector
        # footer recognise them as substantive. Restrict the relaxed
        # threshold to strings carrying a non-ASCII *letter* so we
        # don't accidentally accept ASCII abbreviations like ``Dr.`` or
        # punctuation tokens like ``--``.
        if any(not ch.isascii() and ch.isalpha() for ch in stripped):
            return len(stripped) >= 2
        # Post-a23 P1-D1: short ALL-CAPS tokens are real proper-noun
        # acronyms (``HTTP``, ``TCP``, ``IP``, ``R&B``, ``AC``, ``DC``),
        # not English sentence-words. Live probe sweep:
        # ``tell me about TCP/IP and HTTP and HTTPS`` silently returned
        # ``HTTPS`` because ``TCP`` / ``IP`` / ``HTTP`` all failed the
        # ASCII-length-5 threshold, the substantive check rejected the
        # half list, ``_split_multi_entity`` returned None, and the chain
        # rejection never fired. Same shape for ``AC/DC and Iron Maiden
        # and Metallica`` and ``R&B and Hip Hop``. ``isupper()`` returns
        # True only when ≥1 cased character exists AND every cased
        # character is uppercase — so it accepts ``TCP`` / ``R&B`` /
        # ``M&Ms`` (the ``&`` and ``s`` don't disqualify a topic whose
        # cased letters are all uppercase, but ``M&Ms`` has lowercase
        # ``s`` so it correctly stays in the multi-token branch above).
        # The threshold len ≥ 2 mirrors the non-ASCII branch — single
        # letters (``A``, ``B``) almost never name an article.
        if stripped.isupper() and len(stripped) >= 2:
            return True
        return False

    @classmethod
    def _is_topic_shaped(cls, text: str) -> bool:
        """Return True iff ``text`` looks like a bare topic phrase
        (short, no internal connectors/punctuation that would suggest
        a sentence or a different operation).

        Caps at 6 tokens to avoid mis-classifying free prose as a
        chained topic. Rejects strings that contain stray operation
        verbs or question words mid-phrase, since the splitter would
        have caught those on the operation-prefix path.
        """
        stripped = text.strip()
        if not stripped or len(stripped) > 80:
            return False
        tokens = stripped.split()
        if not tokens or len(tokens) > 6:
            return False
        lower = stripped.lower()
        # Reject if the bare topic contains chain-internal markers
        # (multiple commas, semicolons, "then" mid-phrase) — those
        # indicate a more complex query the splitter shouldn't
        # auto-wrap.
        if any(c in lower for c in (";", " then ", " and then ")):
            return False
        # a13: reject phrases containing operation-verb tokens.
        # ``tell me about`` looks like a bare topic by token count
        # but is actually an incomplete operation prefix that the
        # main regex rejected because the trailing topic is missing.
        # Auto-wrapping it would produce nonsense like
        # ``tell me about tell me about``.
        lower_tokens = [t.lower().strip(".,;:!?") for t in tokens]
        if any(t in cls._OP_VERB_TOKENS for t in lower_tokens):
            return False
        return True
