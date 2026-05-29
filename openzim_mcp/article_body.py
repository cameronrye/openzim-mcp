"""Article lead + table-of-contents rendering for SimpleToolsHandler.

Extracted from ``simple_tools.py`` (post-v2.0.5 review sweep) as a mixin,
following the ``zim`` package's split of ``ZimOperations`` across
``_ContentMixin`` / ``_SearchMixin`` / etc.

Renders the "lead section + section list" view a ``tell me about`` response
falls back to: detecting the article H2 boundaries, recognising and skipping
disambiguation / low-density leads, and assembling the lead-with-TOC body.
The concrete ``SimpleToolsHandler`` supplies ``zim_operations`` (declared
under ``TYPE_CHECKING``).
"""

import re
from typing import TYPE_CHECKING, Optional


class _ArticleBodyMixin:
    """Article lead + table-of-contents rendering for ``SimpleToolsHandler``."""

    if TYPE_CHECKING:
        from .zim_operations import ZimOperations

        zim_operations: "ZimOperations"

    # ``## `` heading marker, used by _lead_with_toc. ``## Content`` is
    # a wrapper section that ``get_zim_entry`` adds at the start of
    # every article; real article H2 sections come after the article
    # H1, which itself follows the wrapper.
    #
    # Wrapper-skip happens in code (``_iter_article_h2`` /
    # ``_first_article_h2`` below) rather than via a regex lookahead —
    # earlier shapes that combined ``[ \t]+`` with ``(?!Content\b)``
    # were flagged by Sonar S5852 because greedy whitespace can
    # backtrack against the lookahead.
    #
    # The capture is anchored with ``\S`` so its first char is
    # mutually exclusive with the leading ``[ \t]+`` — the engine
    # has no ambiguity over where the whitespace ends and the
    # heading text begins. ``[^\n]*`` then runs to end-of-line under
    # MULTILINE in a single greedy pass with no backtracking. An
    # earlier form ``[^\n]+`` overlapped with ``[ \t]+`` on space
    # chars, which Sonar's analyzer treated as polynomial-backtracking
    # risk even though the actual run never backtracks.
    _ARTICLE_H2_RE = re.compile(r"^##[ \t]+(\S[^\n]*)$", re.MULTILINE)

    @classmethod
    def _iter_article_h2(cls, body: str) -> "list[re.Match[str]]":
        """Yield H2 matches in ``body`` excluding the ``## Content``
        wrapper. Filtering happens here instead of in the regex so the
        pattern itself stays trivially backtrack-free.
        """
        return [
            m
            for m in cls._ARTICLE_H2_RE.finditer(body)
            if m.group(1).strip() != "Content"
        ]

    @classmethod
    def _first_article_h2(cls, body: str) -> "Optional[re.Match[str]]":
        """First non-wrapper H2 match in ``body``, or None."""
        for m in cls._ARTICLE_H2_RE.finditer(body):
            if m.group(1).strip() != "Content":
                return m
        return None

    @classmethod
    def _advance_cut_to_second_h2(cls, body: str) -> Optional[str]:
        """Return ``body`` cut at the SECOND non-wrapper H2 instead of the
        first, or ``None`` if the body has fewer than two such H2s.

        Used by ``_lead_with_toc``'s empty-lead fallback: when the
        pre-H2 lead is essentially empty, advancing the cut to the
        second H2 includes the first real section's prose in the
        response, giving the LLM something to ground on instead of
        just a TOC.
        """
        matches = cls._iter_article_h2(body)
        if len(matches) < 2:
            return None
        return body[: matches[1].start()].rstrip()

    # O4 (beta): disambiguation pages on Wikipedia (``Martin``,
    # ``Mercury``) have the form ``# Title\n\n**Title** may refer to:\n``
    # before the first H2. Detect that pattern so the lead-with-TOC cut
    # can be suppressed and the inline disambig list preserved.
    #
    # Implementation note: the original regex
    # ``\bmay\s+(?:also\s+)?refer\s+to\s*:?\s*$`` tripped SonarCloud's
    # S5852 ReDoS check (nested unbounded quantifiers). Equivalent
    # behaviour via normalized ``endswith`` — no regex engine, no
    # backtracking risk, and easier to extend with new phrasings if
    # ZIM exporters ever produce them.
    # Post-b12: ``may refer also to`` added for the Play-style
    # disambig template variant (word order: may-refer-also-to vs the
    # may-also-refer-to of Mercury-style). Live repro at v2.0.0b12:
    # ``Shakespeare England plays`` routed to the ``Play`` disambig at
    # cert=0.85 because the trailing-tail ``endswith`` check missed
    # this phrasing variant.
    _DISAMBIG_LEAD_PHRASES = (
        "may refer to",
        "may also refer to",
        "may refer also to",
    )

    # ``_lead_density`` strips the ZIM-renderer preamble + duplicated H1
    # to measure substantive lead prose. Both patterns are anchored at
    # the start of their respective inputs — ``\A`` always matches the
    # absolute string start regardless of flags, so no MULTILINE here.
    # The duplicated-H1 pattern runs on the output of the preamble strip,
    # which is also a fresh string start for the H1 match.
    #
    # Patterns use a literal single space after ``#`` / ``##`` rather than
    # ``\s+`` or ``[ \t]+``. The ZIM renderer always emits exactly one
    # space after the hash; allowing a repeated whitespace class adjacent
    # to ``[^\n]*`` (which also matches spaces) gives the regex engine
    # ambiguous splits and trips SonarCloud's S5852 polynomial-backtracking
    # detector. A literal single space keeps the boundary unambiguous —
    # ``[^\n]*`` is the sole repetition per field, bounded by an explicit
    # ``\n`` literal at each field separator.
    _LEAD_PREAMBLE_RE = re.compile(
        r"\A# [^\n]*\nPath:[^\n]*\nType:[^\n]*\n## Content[^\n]*\n+"
    )
    # The trailing ``(?:\n+|\Z)`` lets the H1 strip succeed even when the
    # duplicated-H1 line is the last line of ``pre_h2`` (callers
    # ``rstrip()`` ``pre_h2`` before passing it in, which removes the
    # trailing newline that would otherwise terminate the line). Without
    # the ``\Z`` branch, a tightly-cut empty-lead like ``## Content\n\n#
    # Title`` (no inter-H1/H2 content) would leave ``# Title`` unstripped
    # and inflate density to title-length, defeating the empty-lead
    # threshold.
    _DUPLICATED_H1_RE = re.compile(r"\A# \S[^\n]*(?:\n+|\Z)")

    # Empty-lead detection threshold: lead is "effectively empty"
    # when ``_lead_density`` returns ``< 5`` substantive chars after
    # preamble + duplicated-H1 strip. The motivating case
    # (Big_Rapids,_Michigan with infobox-stripped lead) has density
    # 0; any real one-sentence lead like "Foo is a bar." (>=10 chars)
    # stays well above this and is preserved by the standard
    # lead-cut path. Tunable from live-MCP probe data if real
    # articles produce density 1-4 placeholder-only leads.
    _EMPTY_LEAD_DENSITY_THRESHOLD = 5

    @classmethod
    def _is_disambig_lead(cls, pre_h2: str) -> bool:
        """Return True when ``pre_h2`` looks like a disambig-page lead.

        Examines only the trailing 400 characters: pages like Mercury
        carry a ``most commonly refers to:`` preamble with a list of
        top-level entries BEFORE the ``may also refer to:`` line that
        actually marks the end of the disambig lead. The full pre-H2
        body is therefore well over 400 chars on those pages. The
        original implementation bailed out at ``len(pre_h2) >= 400``
        and missed them. The tail window keeps the regex-free
        ``endswith`` bound while letting long preambles still trigger.
        """
        # ``" ".join(s.split())`` collapses all whitespace runs (including
        # newlines and tabs) to single spaces. ``rstrip(":")`` accommodates
        # both ``may refer to:`` and the bare ``may refer to`` variants.
        tail = pre_h2[-400:] if len(pre_h2) > 400 else pre_h2
        normalized = " ".join(tail.lower().split()).rstrip(":").rstrip()
        return normalized.endswith(cls._DISAMBIG_LEAD_PHRASES)

    @classmethod
    def _lead_density(cls, pre_h2: str) -> int:
        """Count substantive characters in the pre-H2 lead body, with a
        preamble-presence gate.

        The "empty-lead" pattern this helper detects is specific to the
        ZIM-rendered body shape: ``# Title\nPath: ...\nType: ...\n##
        Content\n\n# Title\n\n`` followed by an immediate H2. When the
        preamble isn't present (direct-content bodies passed in unit
        tests, or any caller that bypasses the standard ZIM render),
        the stripping logic can't reliably distinguish wrapper noise
        from real lead content. Return the raw non-whitespace count
        in that case so the caller's threshold comparison treats the
        body as substantive and DOES NOT trigger empty-lead detection.

        With the preamble present, strip it plus the duplicated H1
        line and count what remains — that's the substantive lead
        char count the empty-lead path is designed to threshold.
        """
        preamble_match = cls._LEAD_PREAMBLE_RE.match(pre_h2)
        if preamble_match is None:
            # No ZIM preamble — direct-content body. Don't claim it's
            # empty just because we can't see wrappers we expect.
            # Pin the return at-or-above the threshold so the caller's
            # ``< threshold`` check unambiguously declines empty-lead
            # detection; the raw count alone can be below threshold
            # for short one-sentence leads (unit-test fixtures) where
            # we still want to treat the body as substantive.
            raw = len("".join(pre_h2.split()))
            return max(raw, cls._EMPTY_LEAD_DENSITY_THRESHOLD)
        stripped = pre_h2[preamble_match.end() :]
        h1_match = cls._DUPLICATED_H1_RE.match(stripped)
        if h1_match is not None:
            stripped = stripped[h1_match.end() :]
        return len("".join(stripped.split()))

    def _lead_with_toc(self, zim_file_path: str, entry_path: str, body: str) -> str:
        """Truncate ``body`` at the first article H2 (lead-section cut)
        and append a markdown TOC of remaining sections.

        Tries to fetch the full section list via
        ``get_article_structure_data`` (cheap; reuses the structure
        cache) so the TOC includes sections beyond the truncated body.
        Falls back to in-body H2 detection on backend failure.

        Skips the cut when no H2 is found inside ``body`` — common when
        the article's lead is longer than ``max_content_length``, in
        which case we serve the truncated lead unchanged but still
        append the structure TOC (gives the LLM navigation hooks even
        when the body is mid-paragraph-truncated).
        """
        # Try to fetch the full section list FIRST so the in-body H2
        # fallback (used on backend failure) sees the original body —
        # cutting body[:h2.start()] before scanning would drop the H2
        # we need to find.
        sections: list = []
        try:
            structure = self.zim_operations.get_article_structure_data(
                zim_file_path, entry_path
            )
            if isinstance(structure, dict):
                for h in structure.get("headings") or []:
                    if not isinstance(h, dict):
                        continue
                    if h.get("level") != 2:
                        continue
                    text = (h.get("text") or "").strip()
                    if not text or text == "Content":
                        continue
                    sections.append(text)
        except Exception:
            # Backend hiccup. Fall back to whatever H2s we can scan from
            # the body itself — better than nothing. ``_iter_article_h2``
            # already filters out the ``## Content`` wrapper.
            sections = [
                m.group(1).strip()
                for m in self._iter_article_h2(body)
                if m.group(1).strip()
            ]

        # Cut body at first non-wrapper H2 if one's present in the
        # truncated body — saves the LLM from a mid-paragraph cut.
        #
        # O4 (beta): disambiguation pages (Wikipedia "Martin", "Mercury",
        # etc.) have the form ``# Title\n\n**Title** may refer to:\n\n##
        # Category 1\n - link\n - link\n## Category 2\n...``. Cutting
        # at the first H2 produces a ~30-char useless response — just
        # the bare "may refer to:" line with no list. The model has to
        # follow up with ``show structure of Title`` to discover the
        # categories, then more calls to read entries. Detect the
        # pattern (short pre-H2 body ending in "may refer to:") and
        # keep the WHOLE body instead, so the disambig list is right
        # there inline.
        h2_match = self._first_article_h2(body)
        empty_lead_advanced = False
        if h2_match:
            pre_h2 = body[: h2_match.start()].rstrip()
            if self._is_disambig_lead(pre_h2):
                clean_cut = False
            elif self._lead_density(pre_h2) < self._EMPTY_LEAD_DENSITY_THRESHOLD:
                # Empty-lead case: pre-H2 body is essentially just
                # wrappers and the duplicated H1. Advance the cut to
                # the SECOND non-wrapper H2 so the response includes
                # the first real section's prose. Motivating case:
                # ``Big_Rapids,_Michigan`` (2026-05-18 live transcript).
                advanced_body = self._advance_cut_to_second_h2(body)
                if advanced_body is not None:
                    body = advanced_body
                    clean_cut = True
                    empty_lead_advanced = True
                else:
                    # Only one section in the article — no second H2
                    # to advance to. Fall back to whole-body (no cut).
                    clean_cut = False
            else:
                body = pre_h2
                clean_cut = True
        else:
            clean_cut = False

        parts = [body]
        if not clean_cut and not sections:
            # No clean cut and no TOC — the existing truncation message
            # from ``truncate_content`` is the most useful thing we can
            # leave the caller with. Avoid adding noise.
            return body
        if empty_lead_advanced:
            # Always surface the substitution, even if the structure call
            # returned no usable level-2 headings — the LLM still needs
            # to know the "lead" it's reading was actually the first
            # section, not the article's true opening prose.
            parts.append(
                "\n_Lead was empty; showing first section instead. "
                f"Use `show structure of {entry_path}` for the full "
                f"outline, or `get section <name> of {entry_path}` "
                "to fetch a specific section._"
            )
        elif clean_cut and sections:
            parts.append(
                "\n_Lead section shown. Use `show structure of "
                f"{entry_path}` for the full outline, or `summary of "
                f"{entry_path}` for a longer summary._"
            )
        if sections:
            parts.append("\n## Sections in this article\n")
            parts.extend(f"- {s}" for s in sections)
        return "\n".join(parts)
