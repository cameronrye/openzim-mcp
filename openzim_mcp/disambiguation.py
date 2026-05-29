"""Title disambiguation handling for SimpleToolsHandler.

Extracted from ``simple_tools.py`` (post-v2.0.5 review sweep) as a mixin,
following the ``zim`` package's split of ``ZimOperations`` across
``_ContentMixin`` / ``_SearchMixin`` / etc.

Handles the disambiguation surface: detecting ``Foo_(disambiguation)`` twin
paths, auto-picking the canonical article over a disambiguation twin (or a
topic-extending sibling) when the title match is strong enough, and
rendering the disambiguation chooser when it isn't. The concrete
``SimpleToolsHandler`` supplies ``zim_operations`` (declared under
``TYPE_CHECKING``).
"""

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional


class _DisambiguationMixin:
    """Title disambiguation handling for ``SimpleToolsHandler``."""

    if TYPE_CHECKING:
        from .zim_operations import ZimOperations

        zim_operations: "ZimOperations"

        @staticmethod
        def _recase_from_original(token: str, original_query: str) -> str: ...

    @staticmethod
    def _is_disambig_twin_path(path: str) -> bool:
        """Return True iff ``path`` matches the ``Foo_(disambiguation)``
        suffix pattern. Tolerates both URL-encoded and decoded forms.
        """
        lower = path.lower()
        return lower.endswith("_(disambiguation)") or lower.endswith(
            "_%28disambiguation%29"
        )

    def _probe_disambig_twin(
        self, zim_file_path: str, canonical_path: str
    ) -> Optional[str]:
        """A16 post-a16 D4: probe the title index for ``<canonical_path>_
        (disambiguation)``. Returns the matching path if it exists,
        else ``None``.

        Cheap (in-memory title-index hit). Strict match: the returned
        path must equal one of the two expected forms (URL-decoded or
        URL-encoded ``%28...%29``) — case-insensitive on the prefix
        only. This avoids promoting unrelated articles whose titles
        contain ``(disambiguation)`` (e.g. ``Word-sense_disambiguation``
        in the live archive).
        """
        if not canonical_path:
            return None
        expected = {
            (canonical_path + "_(disambiguation)").lower(),
            (canonical_path + "_%28disambiguation%29").lower(),
        }
        title_probe = canonical_path.replace("_", " ") + " (disambiguation)"
        try:
            data = self.zim_operations.find_entry_by_title_data(
                zim_file_path, title_probe, cross_file=False, limit=3
            )
        except Exception:
            return None
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            return None
        for hit in results:
            if not isinstance(hit, dict):
                continue
            hit_path = str(hit.get("path") or "")
            if hit_path and hit_path.lower() in expected:
                return hit_path
        return None

    @classmethod
    def _auto_pick_canonical_over_disambig_twin(
        cls,
        topic: str,
        strong_matches: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """A11 C1 + Opp1: when exactly one strong match is the canonical
        ``Foo`` and another is the ``Foo (disambiguation)`` twin, auto-
        pick the canonical so ``tell me about Berlin`` stops forking
        the caller between ``Berlin`` and ``Berlin (disambiguation)``.

        Returns the canonical match dict to auto-resolve to, or ``None``
        when the strong-match set isn't a clean canonical+twin pair
        (e.g. genuine multi-meaning Apollo/Mercury/Java cases).

        Heuristic: the strong matches must contain (a) at least one
        path whose ``_is_disambig_twin_path`` is True, AND (b) at least
        one non-twin path whose title equals the topic
        (token-list-identity, the strict gate from
        :func:`is_strong_title_match`). No other strong matches.
        """
        if len(strong_matches) < 2:
            return None
        twins: List[Dict[str, Any]] = []
        canonicals: List[Dict[str, Any]] = []
        others: List[Dict[str, Any]] = []
        for m in strong_matches:
            if not isinstance(m, dict):
                others.append(m)
                continue
            path = str(m.get("path") or "")
            if cls._is_disambig_twin_path(path):
                twins.append(m)
                continue
            # Token-equality canonical check — bare topic name with no
            # extra qualifier. Reusing the strict-gate logic locally so
            # the auto-pick decision is independent of Xapian rank.
            topic_tokens = tuple(t.lower() for t in re.findall(r"[A-Za-z0-9]+", topic))
            title_tokens = tuple(
                t.lower()
                for t in re.findall(r"[A-Za-z0-9]+", str(m.get("title") or ""))
            )
            path_tokens = tuple(t.lower() for t in re.findall(r"[A-Za-z0-9]+", path))
            if topic_tokens and (
                title_tokens == topic_tokens or path_tokens == topic_tokens
            ):
                canonicals.append(m)
            else:
                others.append(m)
        if twins and canonicals and not others:
            return canonicals[0]
        return None

    @classmethod
    def _auto_pick_canonical_over_extends_topic(
        cls,
        topic: str,
        strong_matches: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """A11 post-a11 C1: pick the canonical when the strong-match set
        contains exactly one entry whose tokens equal the topic AND every
        other entry is a pure "extends-topic" hit (a longer-titled
        article whose title starts with the topic).

        Returns the canonical match dict to auto-resolve to, or ``None``
        when the shape doesn't match — e.g. zero token-equality
        canonicals (no clear winner), multiple token-equality canonicals
        (Apollo / Mercury / Java — genuine multi-meaning), or any
        disambig twin in the set (handled by
        ``_auto_pick_canonical_over_disambig_twin`` already).

        Concrete failure this fixes: ``tell me about France`` with
        Xapian's #1 = ``France_national_football_team_results_(2000–
        2019)``. The H3 canonical-prepend gate (extended in C1) injects
        ``France`` at the head of the strong-matches list, then this
        helper recognises the [canonical, extends-only] shape and picks
        the canonical France article instead of forking the caller.
        """
        if len(strong_matches) < 2:
            return None
        topic_tokens = tuple(t.lower() for t in re.findall(r"[A-Za-z0-9]+", topic))
        if not topic_tokens:
            return None
        canonicals: List[Dict[str, Any]] = []
        extends: List[Dict[str, Any]] = []
        for m in strong_matches:
            if not isinstance(m, dict):
                return None
            path = str(m.get("path") or "")
            # Any disambig twin in the set means the older
            # canonical-over-twin auto-pick should have handled this
            # case (or chose to fork) — don't second-guess it.
            if cls._is_disambig_twin_path(path):
                return None
            title_tokens = tuple(
                t.lower()
                for t in re.findall(r"[A-Za-z0-9]+", str(m.get("title") or ""))
            )
            path_tokens = tuple(t.lower() for t in re.findall(r"[A-Za-z0-9]+", path))
            if title_tokens == topic_tokens or path_tokens == topic_tokens:
                canonicals.append(m)
            elif (
                len(title_tokens) > len(topic_tokens)
                and title_tokens[: len(topic_tokens)] == topic_tokens
            ) or (
                len(path_tokens) > len(topic_tokens)
                and path_tokens[: len(topic_tokens)] == topic_tokens
            ):
                extends.append(m)
            else:
                # Doesn't fit the [canonical, extends-only] shape; bail
                # out so the existing disambig-render path takes over.
                return None
        if len(canonicals) == 1 and extends:
            return canonicals[0]
        return None

    @classmethod
    def _render_disambiguation(
        cls,
        topic: str,
        candidates: list,
        *,
        original_query: Optional[str] = None,
    ) -> str:
        """Render a "did you mean?" list when 2+ articles strong-match
        the topic (e.g. Mercury → planet/element/mythology).

        Each candidate gets its full title, path, and search score so
        the calling LLM can pick a specific path for follow-up. The
        suggested follow-up phrasings (``tell me about <title>``, ``get
        article <path>``) are concrete enough that a small model can
        copy them verbatim. Capped at 5 candidates — beyond that the
        list itself becomes hard to skim.

        Post-b1 P2-D1: ``original_query`` (the pre-Rule-1-lowercase
        query) lets the heading echo ``topic`` in the caller's
        original casing. Pre-fix, ``tell me about Stalin`` returned
        ``**Multiple articles match "stalin"**`` — same shape as the
        post-b1 P1-D2 footer leak but in a different user-facing
        string. Falls back to ``topic`` unchanged when not provided.
        """
        # Wrap the long subtitle in parens so the implicit-string
        # concatenation is unambiguous to readers (and to CodeQL's
        # py/implicit-string-concatenation-in-list rule, which flags
        # adjacency-concat in list literals as a likely missing-comma
        # bug). The two-line break is for line-length only.
        subtitle = (
            "_Several archive articles strong-match this topic. "
            "Pick one explicitly:_"
        )
        display_topic = (
            cls._recase_from_original(topic, original_query)
            if original_query
            else topic
        )
        lines = [
            f'**Multiple articles match "{display_topic}"** — which one did you mean?',
            "",
            subtitle,
            "",
        ]
        for i, c in enumerate(candidates[:5], 1):
            title = c.get("title") or "(untitled)"
            path = c.get("path") or ""
            score = c.get("score")
            if score is not None:
                lines.append(f"{i}. **{title}** — `{path}` (score: {float(score):.2f})")
            else:
                lines.append(f"{i}. **{title}** — `{path}`")
        lines.append("")
        lines.append(
            "_Follow up with `tell me about <full title>` for the article "
            "body, or `get article <path>` for the raw entry._"
        )
        return "\n".join(lines)
