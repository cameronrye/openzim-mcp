"""Subject-attribute section resolution for :class:`SimpleToolsHandler`.

Extracted from ``simple_tools.py`` (post-v2.0.5 review sweep) as a mixin,
following the same pattern the ``zim`` package uses to split
``ZimOperations`` across ``_ContentMixin`` / ``_SearchMixin`` / etc. The
concrete ``SimpleToolsHandler`` mixes this in and supplies the attributes
and helper methods declared under ``TYPE_CHECKING`` below.

The "subject-attribute" path handles queries like
``famous musicians from Big Rapids, Michigan``: once the entity resolves to
``Big Rapids, Michigan``, the leftover tokens (``famous``, ``musicians``)
name a subject category that maps to a section of the resolved article, so
the handler returns that section instead of the article lead.
"""

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .text_utils import _TOKEN_RE

# Subject-attribute resolution: when the resolved entity's title
# doesn't cover all of the topic's tokens, the residual tokens often
# name a subject category ("musician", "actor", "athlete", etc.).
# Map each subject hint token to a tuple of section-name candidates
# (case-insensitive substring match against H2 text). The first
# section whose name contains any candidate substring wins. Section
# names are taken from Wikipedia's place-article convention; tune as
# new gaps surface in live-MCP probes.
#
# Tuple ordering matters: more-specific candidates first ("Musicians"
# beats "Music" beats "Notable people"), so a music-specific section
# wins over the generic notable-people fallback when both exist.
#
# NOTE on candidate strings: matching uses whole-word regex
# (\bcand\b), so a candidate like "Music" matches "Music and
# dance" but NOT "Microfilm". Still, keep candidates >=4 chars
# and avoid English-common substrings (e.g. "art") that may
# appear as standalone words in unrelated section names.
_SUBJECT_HINT_TO_SECTION: Dict[str, "tuple[str, ...]"] = {
    "musician": ("Musicians", "Music", "Notable people"),
    "musicians": ("Musicians", "Music", "Notable people"),
    "music": ("Music", "Musicians", "Notable people"),
    "actor": ("Actors", "Film", "Notable people"),
    "actors": ("Actors", "Film", "Notable people"),
    "actress": ("Actors", "Film", "Notable people"),
    "athlete": ("Athletes", "Sports", "Notable people"),
    "athletes": ("Athletes", "Sports", "Notable people"),
    "sports": ("Sports", "Athletes", "Notable people"),
    "scientist": ("Scientists", "Science", "Notable people"),
    "scientists": ("Scientists", "Science", "Notable people"),
    "writer": ("Writers", "Literature", "Notable people"),
    "writers": ("Writers", "Literature", "Notable people"),
    "author": ("Authors", "Writers", "Literature", "Notable people"),
    "authors": ("Authors", "Writers", "Literature", "Notable people"),
    "politician": ("Politicians", "Politics", "Government", "Notable people"),
    "politicians": ("Politicians", "Politics", "Government", "Notable people"),
    "people": ("Notable people",),
    "person": ("Notable people",),
    "persons": ("Notable people",),
    "notable": ("Notable people",),
    "famous": ("Notable people",),
}

# Tokens that ALONE (without a co-occurring entity-name token) don't
# trigger subject-attribute resolution. ``famous`` and ``notable`` are
# weak signals by themselves — they amplify a real subject hint
# elsewhere in the residual ("famous musicians from X" → trigger on
# ``musicians``) but shouldn't fire on their own.
_WEAK_SUBJECT_HINTS: "frozenset[str]" = frozenset({"famous", "notable"})


class _SubjectSectionMixin:
    """Subject-attribute section resolution for ``SimpleToolsHandler``.

    Attributes and helper methods declared under ``TYPE_CHECKING`` are
    supplied by the concrete ``SimpleToolsHandler`` that mixes this in.
    """

    # Compact mode rewrites oversized tables to a placeholder; a section
    # whose body is only placeholders has no substantive content to
    # surface (the same zero-content shape that triggers small-model
    # hallucination), so we point the caller at the compact=False recovery.
    _TABLE_PLACEHOLDER_RE = re.compile(
        r"\[Table\s+\d+:\s+\d+\s+rows\s+x\s+\d+\s+cols\s+-\s+"
        r"pass compact=False to expand\]"
    )

    if TYPE_CHECKING:
        from .zim_operations import ZimOperations

        zim_operations: "ZimOperations"

        def _track(self, event: str) -> None: ...

        def _coerce_content_offset(self, raw: Any) -> int: ...

        def _soft_connector_footer(
            self,
            topic: str,
            top_title: str,
            *,
            zim_file_path: Optional[str] = None,
            top_path: Optional[str] = None,
            original_query: Optional[str] = None,
        ) -> Optional[str]: ...

    @classmethod
    def _extract_subject_hint(cls, topic: str, resolved_title: str) -> Optional[str]:
        """Detect a subject-category hint in the residual of ``topic``
        after the resolved entity's title tokens are removed.

        Used by the subject-attribute decomposition path: when a query
        like ``famous musician from big rapids michigan`` resolves
        (via tail-probing in ``_promote_topic_via_title_index``) to
        the entity ``Big Rapids, Michigan``, the leftover tokens
        (``famous``, ``musician``, ``from``) often name a subject
        category that maps to a section in the resolved article.

        Returns the residual subject token (lowercased) on a strong
        match, or ``None`` when the residual is empty, contains only
        weak hints (``famous`` / ``notable`` alone), or contains no
        known subject vocabulary.

        Token matching is whole-word, case-insensitive, alphanumeric-
        only.
        """
        topic_tokens: tuple[str, ...] = tuple(_TOKEN_RE.findall(topic.lower()))
        title_tokens: set[str] = set(_TOKEN_RE.findall(resolved_title.lower()))
        if not topic_tokens or not title_tokens:
            return None
        residual: List[str] = [t for t in topic_tokens if t not in title_tokens]
        if not residual:
            return None
        for tok in residual:
            if tok in _SUBJECT_HINT_TO_SECTION and tok not in _WEAK_SUBJECT_HINTS:
                return tok
        return None

    @classmethod
    def _resolve_section_for_subject(
        cls, structure: Any, subject: str
    ) -> Optional[Dict[str, Any]]:
        """Find the best-matching H2 heading for a subject hint.

        ``structure`` is the dict returned by
        ``zim_operations.get_article_structure_data``. ``subject`` is
        one of the keys in ``_SUBJECT_HINT_TO_SECTION``. Returns the
        heading dict (with ``text`` / ``id`` / ``level`` keys) of the
        first matching section, or ``None`` when none of the
        candidate section names appear as substrings of any H2 in the
        article.

        Matching is case-insensitive whole-word regex (``\\bcand\\b``)
        against the heading text so a candidate like ``Music`` matches
        ``Music and dance`` but NOT ``Microfilm``. Candidate priority
        is the tuple order from ``_SUBJECT_HINT_TO_SECTION``: a
        more-specific candidate (``Music``) wins over a generic
        fallback (``Notable people``) when both exist.
        """
        if subject not in _SUBJECT_HINT_TO_SECTION:
            return None
        candidates = _SUBJECT_HINT_TO_SECTION[subject]
        if not isinstance(structure, dict):
            return None
        h2s: List[Dict[str, Any]] = []
        for h in structure.get("headings") or []:
            if not isinstance(h, dict):
                continue
            if h.get("level") != 2:
                continue
            text = (h.get("text") or "").strip()
            if not text or text == "Content":
                continue
            h2s.append(h)
        for cand in candidates:
            cand_pattern = re.compile(r"\b" + re.escape(cand.lower()) + r"\b")
            for h in h2s:
                text = (h.get("text") or "").lower()
                if cand_pattern.search(text):
                    return h
        return None

    def _maybe_render_subject_section(
        self,
        *,
        zim_file_path: str,
        topic: str,
        top_path: str,
        top_title: str,
        options: Dict[str, Any],
        original_query: Optional[str] = None,
    ) -> Optional[str]:
        """Try the subject-attribute decomposition path. Returns the
        rendered response string on a successful subject-section match,
        or ``None`` to signal "fall through to the normal lead-fetch
        path."

        Gates:
          (a) ``compact=True`` and ``content_offset == 0`` — both
              required for the section-replacement behavior to make
              sense.
          (b) The topic carries a subject hint residual that doesn't
              appear in the resolved entity's title. This is the sole
              gate that filters out unambiguous entity requests like
              ``tell me about Berlin``: ``_extract_subject_hint`` returns
              ``None`` for empty residuals.
          (c) The resolved article's structure has a section matching
              the subject hint.
          (d) The matched section's content fetches successfully and
              is non-empty.
        """
        if not options.get("compact", False):
            return None
        if self._coerce_content_offset(options.get("content_offset")) != 0:
            return None
        subject = self._extract_subject_hint(topic, top_title or top_path)
        if subject is None:
            return None
        try:
            structure = self.zim_operations.get_article_structure_data(
                zim_file_path, top_path
            )
        except Exception:
            return None
        target = self._resolve_section_for_subject(structure, subject)
        if target is None:
            return None
        section_id = target.get("id") or ""
        if not section_id:
            return None
        try:
            section_payload = self.zim_operations.get_section_data(
                zim_file_path, top_path, section_id, include_subsections=True
            )
        except Exception:
            return None
        if not isinstance(section_payload, dict):
            return None
        if section_payload.get("error"):
            return None
        body_text = section_payload.get("content_markdown") or ""
        if not isinstance(body_text, str):
            return None
        body_text = body_text.strip()
        if not body_text:
            return None
        # Post-a18 P3-D1: detect table-dominated sections (compact mode
        # strips oversized tables to ``[Table N: M rows x P cols - pass
        # compact=False to expand]`` placeholders, leaving the LLM with
        # zero substantive content). Munich's ``Notable people`` section
        # is two H3 sub-tables — pre-fix, ``musicians from München``
        # returned just the two placeholders, exactly the content-less-
        # response shape that triggers small-model hallucination. The
        # bundle is always built with ``compact=True`` (see bundle.py),
        # so ``get_section_data`` can't re-emit the expanded tables;
        # instead, surface a direct pointer to the ``compact=False``
        # recovery call so the caller knows what to do.
        section_text = target.get("text") or section_id
        placeholder_count = len(self._TABLE_PLACEHOLDER_RE.findall(body_text))
        stripped_for_density = self._TABLE_PLACEHOLDER_RE.sub("", body_text)
        substantive_chars = len("".join(stripped_for_density.split()))
        if placeholder_count >= 1 and substantive_chars < 100:
            self._track("subject_attribute_table_dominated")
            tables_word = "table" if placeholder_count == 1 else "tables"
            return (
                f"# {top_title or topic}\n\n"
                f"_Source: `{top_path}` (section: {section_text})_\n\n"
                f"_The **{section_text}** section of `{top_path}` "
                f"is rendered as {placeholder_count} {tables_word} "
                f"that compact mode strips. "
                f"Re-issue `tell me about {top_path}` with "
                f"`compact=False` to see the full article including "
                f"table bodies, or `get section {section_id} of "
                f"{top_path}` with `compact=False` for just this "
                f"section._\n"
                f"<!-- intent=subject_attribute_section cert=1.00 -->"
            )
        max_len = options.get("max_content_length")
        truncated = False
        full_len = len(body_text)
        if isinstance(max_len, int) and max_len > 0 and full_len > max_len:
            body_text = body_text[:max_len]
            truncated = True
        self._track("subject_attribute_section_returned")
        result = (
            f"# {top_title or topic}\n\n"
            f"_Source: `{top_path}` (section: {section_text})_\n\n"
            f"_Showing **{section_text}** section because your query "
            f"asked about `{subject}`. Use `tell me about "
            f"{top_path}` for the full article._\n\n"
            f"{body_text}"
        )
        if truncated:
            result = result + (
                f"\n\n_Section truncated at {len(body_text):,} chars "
                f"(was {full_len:,}). Re-run with a larger "
                "`max_content_length` for more._"
            )
        # Honor the soft-connector ambiguity footer so multi-entity
        # subject queries ("musicians from Berlin and Paris" resolving
        # to Paris with a Notable people section) still surface a hint
        # that the OTHER entity was dropped. Without this, the subject-
        # attribute early-return at the call site (_handle_tell_me_about
        # before _soft_connector_footer fires) would silently swallow
        # the drop.
        soft_footer = self._soft_connector_footer(
            topic,
            top_title or top_path,
            zim_file_path=zim_file_path,
            top_path=top_path,
            original_query=original_query,
        )
        if soft_footer:
            result = result + soft_footer
        # Double-marker is intentional: the outer handle_zim_query will
        # append a second <!-- intent=tell_me_about cert=0.70 --> comment
        # based on the bare-topic-fallback classification. The inner
        # subject-attribute marker is required for a calling LLM to
        # distinguish "subject section route" from "low-confidence
        # entity match, lead returned" — both end with the same outer
        # marker. Same convention as namespace_path_redirect.
        result = result + "\n<!-- intent=subject_attribute_section cert=1.00 -->"
        return result
