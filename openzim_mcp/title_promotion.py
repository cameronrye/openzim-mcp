"""Shared title-promotion helpers.

Several operations need the same logic: "given a topic and a list of
search hits, is the top hit actually the canonical article for the
topic, and if not, can we find one?" Extracted here so
``tell me about``, ``synthesize``, and ``search`` all share the same
decision rather than re-deriving it.

The match decision (:func:`is_strong_title_match`) was originally the
``_is_strong_title_match`` static on the simple-tools handler; the
title-index promotion (:func:`find_title_match`) was
``_find_title_match_for_topic``. Both moved here unchanged in v2.0.0a9
so the synthesize and search-result paths can reuse them without
importing the simple-tools handler.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Iterator, Optional

logger = logging.getLogger(__name__)


_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Unicode equivalent of _TOKEN_RE (word chars except underscore). The ASCII
# _TOKEN_RE silently DELETES non-ASCII letters, so a diacritic-bearing topic
# whose ASCII residue collapses to a short token (``Łódź`` → ``d``, ``café`` →
# ``caf``) could exact-match an unrelated short-titled article (M24), and a
# non-ASCII possessor (``Ampère``) shredded into ``amp``/``re`` could never
# intersect its own canonical path (M25). Used where those comparisons must be
# Unicode-correct. _TOKEN_RE itself is kept for the external importers that
# still rely on the ASCII tokenisation.
_UNICODE_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def is_strong_title_match(topic: str, path: str, title: str) -> bool:
    """Return True iff ``path`` or ``title`` looks like the article for ``topic``.

    Tokenizes both sides on alphanumerics (so ``"Martin_Luther_King_Jr."``
    and ``"Martin Luther King Jr."`` both yield
    ``("martin", "luther", "king", "jr")``), then accepts the match when
    the token lists are equal OR when one prefixes the other within
    reason. Two directions are valid:

    * **Candidate extends topic** (``Berlin`` → ``Berlin (city)``):
      unconditional. The candidate is the canonical article with a
      disambiguator; the topic is the bare term the model asked about.
    * **Topic extends candidate** (``Apollo 11 (mission)`` → ``Apollo_11``):
      bounded — the topic must carry at most one extra token beyond the
      candidate. This covers parenthetical disambiguation on the topic
      side (the model asked about ``Berlin (city)`` and we found
      ``Berlin``). Wider drops (``Martin Luther King`` → ``Martin``)
      are NOT accepted — a bare-first-name stub shouldn't outrank the
      canonical full-name article (H20 regression).

    The 3-char-minimum guard on each side prevents trivially-short
    tokens (``Pi``) from driving prefix matches.
    """
    # M24: Unicode-aware tokeniser so non-Latin topics aren't mutilated into
    # short ASCII residues that spuriously exact-match short article titles.
    topic_tokens = tuple(_UNICODE_TOKEN_RE.findall(topic.lower()))
    if not topic_tokens:
        return False

    for candidate in (path, title):
        if not candidate:
            continue
        cand_tokens = tuple(_UNICODE_TOKEN_RE.findall(candidate.lower()))
        if not cand_tokens:
            continue
        if topic_tokens == cand_tokens:
            return True
        if sum(len(t) for t in topic_tokens) < 3:
            continue
        if sum(len(t) for t in cand_tokens) < 3:
            continue
        # Candidate-extends-topic — unconditional (canonical promotion).
        if cand_tokens[: len(topic_tokens)] == topic_tokens:
            return True
        # Topic-extends-candidate — bounded to a 1-token diff so
        # ``Apollo 11 (mission)`` → ``Apollo_11`` works but
        # ``Martin Luther King`` → ``Martin`` doesn't.
        diff = len(topic_tokens) - len(cand_tokens)
        if 0 < diff <= 1 and topic_tokens[: len(cand_tokens)] == cand_tokens:
            return True
    return False


# A11 post-a11 H1: punctuation characters whose presence in the topic
# encodes load-bearing meaning the title resolver may smear away.
# ``C++`` (the language) was getting silently mapped to ``C/C++`` (a
# compatibility-of-C-and-C++ shorthand) because libzim's title index
# normalises ``+`` away, so the resolver couldn't tell ``C`` from
# ``C++``. The token-equality guard below requires that the resolved
# path preserve the count of each load-bearing punctuation character —
# if the topic has two ``+`` and the candidate has zero, it's a smear,
# not a match.
_LOAD_BEARING_PUNCTUATION = ("+", "#", "*", "&", "?", "!")


def _punctuation_smear_detected(topic: str, candidate_path: str) -> bool:
    """Return True iff resolving ``topic`` to ``candidate_path`` collapsed
    a load-bearing punctuation character (``+``, ``#``, etc.).

    Cheap byte-level count comparison. Designed to catch the false-
    positive class observed live (``C++`` → ``C/C++``,
    ``F#`` → ``F``-the-letter), without rejecting legitimate
    punctuation-preserving redirects (``Newton's_laws`` →
    ``Newton's_laws_of_motion`` keeps the apostrophe count steady).
    """
    for ch in _LOAD_BEARING_PUNCTUATION:
        if topic.count(ch) > candidate_path.count(ch):
            return True
    return False


def find_title_match(
    zim_operations: Any,
    zim_file_path: str,
    topic: str,
    *,
    cross_file: bool = False,
    min_score: float = 1.0,
) -> Optional[Dict[str, Any]]:
    """Ask the title index whether ``topic`` resolves to a score-1.0 entry.

    Returns ``{"path": ..., "title": ..., "zim_file": ...}`` when an
    exact-title match exists; ``None`` otherwise. Used by callers that
    want to promote the canonical article past a noisy BM25 ranking
    (``List of songs about Berlin`` outranks ``Berlin`` for the query
    ``Berlin`` on Wikipedia because title-match boost isn't strong
    enough). Score 1.0 is the safe promotion threshold — lower-confidence
    matches (0.95, fuzzy 0.85) can introduce false positives like
    ``Java`` → ``Java (programming language)``.

    ``cross_file=True`` searches across all configured archives.
    ``min_score`` lets typo-tolerant callers (D3 fix:
    ``tell me about Photosythesis``) accept the fuzzy-fallback 0.85
    score the title index produces for single-edit typos. Errors in
    the backend are logged and swallowed so a transient failure blanks
    the promotion path rather than the whole response.

    A11 post-a11 H1: rejects matches that drop load-bearing
    punctuation from the topic (``C++`` → ``C/C++`` was silently
    smearing the language name onto the cross-language compatibility
    article). Falls through to ``None`` so the calling search /
    tell-me-about path uses its Xapian fallback instead, where the
    actual ``C++_programming_language`` article resolves correctly via
    canonical-title-match.
    """
    try:
        data = zim_operations.find_entry_by_title_data(
            zim_file_path, topic, cross_file=cross_file, limit=3
        )
    except Exception as e:
        logger.debug("find_title_match: find_entry_by_title_data failed: %s", e)
        return None
    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        return None
    top = results[0]
    if not isinstance(top, dict):
        return None
    if float(top.get("score", 0.0)) < min_score:
        return None
    candidate_path = str(top.get("path", ""))
    if _punctuation_smear_detected(topic, candidate_path):
        logger.debug(
            "find_title_match: punctuation smear rejected (%r -> %r)",
            topic,
            candidate_path,
        )
        return None
    result: Dict[str, Any] = {
        "path": candidate_path,
        "title": str(top.get("title", "")),
        "zim_file": str(top.get("zim_file", zim_file_path)),
    }
    # Post-b4 D1: propagate ``match_type`` so callers using the 0.95
    # gate (the b4 pass-0 probe; the synthesize-path pass-0 probe)
    # can reject ``fuzzy_suggest`` rows — the suggestion-rank top score
    # of 0.95 covers both meaningful redirects AND incidental fuzzy
    # title-prefix matches, and only the former is safe to auto-fetch.
    # Field is optional — older mocks / non-annotated callers pass
    # through transparently.
    match_type = top.get("match_type")
    if match_type:
        result["match_type"] = str(match_type)
    # Post-b6 Z1: propagate ``pre_redirect_path`` so callers can
    # detect "associative" redirects — libzim's suggestion-search
    # sometimes returns a row whose pre-redirect path is unrelated to
    # the user's possessor entity (the path libzim found via fuzzy
    # token-prefix matching just happens to walk through a redirect
    # to a canonical that shares one user-typed token). The D1 filter
    # on possessive topics uses this to distinguish semantic redirects
    # (``Plato's_cave`` → ``Allegory_of_the_cave`` — pre-path
    # contains the possessor ``plato``) from associative ones
    # (some unrelated-redirect → ``Evolution`` for a
    # ``darwin's evolution`` query). Field is optional; older callers
    # that don't set it pass through transparently.
    pre_redirect_path = top.get("pre_redirect_path")
    if pre_redirect_path:
        result["pre_redirect_path"] = str(pre_redirect_path)
    return result


# Tokenizer for tail / window probe yielders. Unicode-aware so non-Latin
# topics like ``München`` / ``Zürich`` / ``Köln`` tokenize to one token
# (``["münchen"]``) instead of being split on the diacritic into
# ``["m", "nchen"]`` etc. Post-a17 P1-D2: the ASCII-only ``[a-z0-9]+``
# previously used here yielded ``"m"`` for ``München`` via
# ``iter_query_windows``, which ``find_title_match`` then cleanly
# resolved to the ``M`` letter article at score 1.0 — a confidently-
# wrong answer at cert=0.85 for any place name with a diacritic. The
# backend ``find_entry_by_title_data`` natively handles Unicode (probed
# directly with ``find article titled München`` → resolves to Munich
# at score 1.00), so the fix is to stop destroying the topic before it
# reaches the backend. Underscores, punctuation, and whitespace remain
# token boundaries — ``[^\W_]+`` keeps ``\w`` minus underscore so
# path-form input like ``"Big_Rapids,_Michigan"`` still tokenizes to
# ``["big", "rapids", "michigan"]``. ``re.UNICODE`` is the default in
# Python 3 — naming it here keeps the intent explicit.
#
# Post-b4 D2/D3/D5: apostrophes (``'`` straight, ``’`` curly) are now
# kept INSIDE otherwise-alphanumeric runs so ``einstein's`` stays one
# token instead of fragmenting to ``["einstein", "s"]``. Pre-fix, the
# stub ``s`` token polluted every tail/window yielded for an
# apostrophe-bearing topic; the trailing 1-token tail (``"theory"`` /
# ``"philosophy"`` / ``"history"``) then strict-1.0-matched whatever
# generic Wikipedia article shared that title and silently won.
# ``['’]`` covers both Unicode codepoints Wikipedia uses
# (U+0027 APOSTROPHE for ASCII titles, U+2019 RIGHT SINGLE QUOTATION
# MARK for typographically-styled titles like ``Achilles’ heel``).
_TAIL_TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


# Post-b4: detect topics carrying an apostrophe-possessive shape so
# callers (pass-1 / pass-3 of ``_promote_topic_via_title_index`` and
# pass-1 of ``_promote_title_match``) can tighten ``iter_query_tails``'s
# ``min_len`` floor to 2. The b4 pass-0 probe handles the legitimate
# "X's Y is canonical" case; without the floor, pass-1 will silently
# promote a generic 1-token tail (``"philosophy"`` → ``Philosophy``,
# ``"history"`` → ``History``, ``"tourism"`` → ``Tourism``) for
# prose-with-possessive queries where the full topic isn't canonical.
# Matches ``X's``, ``X’s``, ``Achilles'`` (bare trailing apostrophe).
#
# Post-b6 Z1: the regex now captures the possessor token (before the
# apostrophe) as group 1, so ``extract_possessor_tokens`` can pull it
# out to check against a redirect's pre-resolution path. The
# ``has_apostrophe_possessive`` predicate continues to use ``search``
# on the same pattern — group 1 is harmless for existence checks.
#
# Inner character class is ``[^\W_]`` rather than ``[^\W_'’]`` because
# apostrophes (both ASCII ``'`` and curly ``’``) are already excluded
# by ``\W`` — listing them inside ``^\W`` is a redundant character
# class member (SonarCloud S5869). The leading-letter + repeat is
# expressed as a single ``[^\W_]+`` (S6353).
#
# The quantifier is bounded ``{1,64}`` rather than unbounded ``+`` so
# the static analyzer can prove linear-time worst case (SonarCloud
# S5852 ReDoS): the engine can backtrack at most 64 positions per
# apostrophe character — well above any natural-language possessor
# token length (longest English name in common use is well under
# 30 chars). Same mitigation pattern as the post-a22 sweep's
# ``[\s\S]+?for ...`` rewrite (commit 63dac8a).
_POSSESSIVE_TOKEN_RE = re.compile(r"([^\W_]{1,64})['’](?:s\b|\B)", re.UNICODE)


def has_apostrophe_possessive(topic: str) -> bool:
    """Return True iff ``topic`` carries an apostrophe-possessive token.

    Used by promotion callers to decide whether to tighten the tail-
    iteration ``min_len`` floor (see ``_POSSESSIVE_TOKEN_RE`` docstring
    above).
    """
    if not topic:
        return False
    return bool(_POSSESSIVE_TOKEN_RE.search(topic))


def extract_possessor_tokens(topic: str) -> list[str]:
    """Return the lowercased possessor tokens in ``topic``.

    For each ``X's`` / ``X'`` / ``X’s`` shape in the topic, the
    possessor is the bare token before the apostrophe. ``Plato's
    cave`` yields ``["plato"]``; ``John's and Mary's books`` yields
    ``["john", "mary"]``; ``Berlin Germany`` yields ``[]``.

    Post-b6 Z1 helper: the D1 filter in
    ``_promote_topic_via_title_index`` and ``_promote_title_match``
    uses these tokens to detect "associative" redirects — libzim's
    suggestion-search occasionally returns a result via a redirect
    chain whose pre-resolution path is unrelated to the user's
    possessor entity (e.g., ``"darwin's evolution"`` → some unrelated
    redirect → ``Evolution``). When NONE of the possessor tokens
    appear in the pre-redirect path's tokens, the redirect is
    classified as associative-not-semantic and rejected.

    Returns an empty list when the topic has no possessive shape.
    Order follows left-to-right occurrence in the topic; duplicates
    are preserved so callers that want a set can ``set(...)``-wrap.
    """
    if not topic:
        return []
    return [m.group(1).lower() for m in _POSSESSIVE_TOKEN_RE.finditer(topic)]


def accept_possessive_promotion(promoted: Dict[str, Any], topic: str) -> bool:
    """Return True iff ``promoted`` is safe to auto-fetch for ``topic``.

    Shared filter used by both ``simple_tools._promote_topic_via_title_index``
    (pass-0 + pass-3) and ``synthesize._promote_title_match`` pass-0 so
    the two-mode tell-me-about/synthesize paths apply the SAME D1+Z1
    safety logic. Lives here in ``title_promotion`` (not on either
    handler) to keep ``simple_tools`` and ``synthesize`` decoupled from
    each other — both already import from this module.

    The libzim suggestion-search produces three relevant ``match_type``
    shapes at the 0.95+ score band:

      * ``"direct"`` — exact-title hit (post-redirect title equals
        user input case-insensitively). Always safe.
      * ``"redirect"`` — libzim found a redirect entry and
        ``_follow_redirect_chain`` walked it to a canonical. SAFE iff
        the pre-redirect path is semantically related to the user's
        query. Post-b7 Z1.1: this check is the SUBSET RULE — the
        pre-redirect path's tokens must be a subset of the topic's
        tokens. Catches two distinct attack surfaces:

          - **Associative redirect** (b6 Z1): pre-path is an
            unrelated entry that happens to walk to a canonical
            sharing one user token. ``Plato's republic philosophy``
            → some redirect → ``Czech_philosophy``: pre-path tokens
            don't include ``plato`` → fails subset (and fails
            containment too) → REJECT.
          - **Truncation redirect** (b7 Z1.1): pre-path is a LONGER
            phrase the user truncated. ``Darwin's evolution`` →
            ``Darwin's_Theory_of_Evolution`` → ``Evolution``:
            pre-path contains ``darwin`` (passes the b6 containment
            check) BUT has extras ``theory``, ``of`` not in the
            topic → fails subset → REJECT. The post-b6 containment
            check accepted this and produced a cert=0.85 silent-
            wrong-answer.

        The subset rule subsumes the b6 containment check: any
        pre-path that is a subset of the topic necessarily contains
        the possessor (which is one of the topic tokens) — so cases
        accepted by b6 with pre ⊆ topic continue to be accepted;
        cases accepted by b6 with pre having extras are now
        rejected.

      * ``"fuzzy_suggest"`` — libzim returned the canonical directly
        via token-prefix matching, no redirect walked. SAFE for
        non-possessive prose (``"Berlin Germany"`` → ``"Berlin"`` is
        the user's intent), UNSAFE for possessives (``"Darwin's
        evolution"`` → ``"Evolution"`` drops the possessor entirely
        — silent-wrong-answer at cert=0.85).

    For non-possessive topics, all three shapes are accepted — the b4
    pass-0 improvements for ``<entity> <disambiguator>`` queries
    depend on this.

    Missing/unknown ``match_type`` is accepted for backwards-compat
    with older callers and test mocks that don't annotate the row.
    """
    match_type = promoted.get("match_type")
    if not has_apostrophe_possessive(topic):
        return _accept_non_possessive(promoted, topic, match_type)
    if match_type == "direct":
        return True
    if match_type == "fuzzy_suggest":
        return _accept_possessive_fuzzy_suggest(promoted, topic)
    if match_type == "redirect":
        return _accept_possessive_redirect(promoted, topic)
    return True


def _accept_non_possessive(
    promoted: Dict[str, Any], topic: str, match_type: Any
) -> bool:
    """Accept gate for non-possessive topics.

    Post-b8 Z3: non-possessive multi-token topics can still leak a
    hijack via Pass 0's full-topic probe at min_score=0.95 — libzim's
    title-suggest fuzzy-matches a single strong token in the topic
    and returns that token's canonical alone. The b4 D2 raised-
    min_len protection covered only possessives. Live silent-wrong-
    answers at v2.0.0b8 (cert=0.85): Stalin USSR Russia → Russia,
    Hitler Germany Berlin → Berlin, Marie Curie polonium discovery →
    Discovery (a disambig page!), Big Rapids Michigan tourism →
    Tourism (contradicts iter_query_windows docstring), O'Brien
    character 1984 → 1984 (the year), Marie Curie radioactivity →
    Radioactive_(Redniss_book) (an obscure 2010 graphic novel
    surfaced via stemming).

    Two narrow rejections for non-possessive + fuzzy_suggest when the
    topic has 3+ tokens:

      (a) **Tail-token hijack** — canonical is a single token equal
          to the topic's LAST token. The user typed
          ``<subject> ... <generic>``; libzim returned the generic
          article. ``Hamlet Denmark prince`` → ``Hamlet`` stays
          accepted because the canonical sits at the HEAD position,
          not the tail.
      (b) **Zero-overlap stemming hit** — canonical's tokens have
          zero exact-overlap with topic's tokens (the match was via
          stemming only). The 2010 graphic novel
          ``Radioactive_(Redniss_book)`` surfaced for ``Marie Curie
          radioactivity`` because libzim's title index stems
          ``radioactivity`` to ``radioactive``; no other topic token
          matches the canonical, so the hit is one-stem-token-deep —
          too thin a signal to auto-fetch.

    Topics with <3 tokens are unaffected — ``Berlin Germany`` →
    ``Berlin`` resolves via ``is_strong_title_match`` at the BM25
    stage anyway, and 2-token possessive carve-outs are handled by
    the possessive branch.

    Post-b9 Z3 extension: the b9 rule gated the tail-hijack check on
    ``match_type == "fuzzy_suggest"``. Live post-b9 sweep against
    v2.0.0b9 revealed every Z3 silent-wrong-answer actually routes
    through ``_promote_topic_via_title_index`` Pass 1's
    ``iter_query_tails`` 1-token tail probe, where the tail string
    (``"russia"``, ``"berlin"``, ``"discovery"``, etc.) is passed to
    ``find_title_match``. libzim sees the tail string as a
    case-insensitive title equal → returns ``match_type="direct"``
    at score 1.0. The b9 short-circuit ``if match_type !=
    "fuzzy_suggest": return True`` bypassed the Z3 check entirely.

    The tail-hijack premise is purely about the topic↔canonical
    token relationship; it doesn't depend on how libzim resolved
    the match. Apply it regardless of match_type. The zero-overlap
    stemming sub-rule stays gated on ``fuzzy_suggest`` (a direct or
    redirect match by definition shares at least the matched token,
    so the rule is moot for those branches).

    Post-b10 invariant: the b10 case-based discriminator (counting
    capitalized + digit tokens in the original-case topic) was
    fundamentally broken because ``IntentParser._normalize_topic_case``
    (Tier 1 Rule 1) lowercases the query BEFORE topic extraction. By
    the time this gate runs, the topic is uniformly lowercase — the
    discriminator counted zero capitalized tokens and never fired on
    live data. The multi-entity discriminator now lives at the call
    site in ``_promote_topic_via_title_index`` as a probe-based check
    (see ``count_non_tail_strong_entities``); this gate just emits
    the unconditional tail-hijack rejection and lets the caller
    override when its probe confirms the topic is single-entity.
    """
    topic_tokens_seq = _TAIL_TOKEN_RE.findall(topic.lower())
    if len(topic_tokens_seq) < 3:
        return True
    cand_path = str(promoted.get("path", ""))
    cand_tokens_seq = _TAIL_TOKEN_RE.findall(cand_path.lower())
    if len(cand_tokens_seq) == 1 and cand_tokens_seq == topic_tokens_seq[-1:]:
        return False
    if match_type == "fuzzy_suggest" and not (
        set(cand_tokens_seq) & set(topic_tokens_seq)
    ):
        return False
    return True


def is_tail_hijack_shape(promoted: Dict[str, Any], topic: str) -> bool:
    """Pure-logic check: ``promoted`` is a single-token canonical
    equal to the topic's LAST token, AND the topic has 3+ tokens.

    The tail-hijack shape distinguishes the silent-wrong-answer
    pattern from legitimate multi-token matches:

      * ``Stalin USSR Russia`` → ``Russia``: single-token canonical
        equal to topic[-1:] → tail-hijack shape.
      * ``Hamlet Denmark prince`` → ``Hamlet``: single-token
        canonical at HEAD position → NOT a tail-hijack shape.
      * ``Apollo 11 moon landing`` → ``Moon_landing``: multi-token
        canonical → NOT a tail-hijack shape.
      * ``Berlin Germany`` → ``Berlin``: 2-token topic → NOT a
        tail-hijack shape (the b4 carve-out invariant).

    Callers that want the rejection to fire conditionally
    (e.g., only when the topic ALSO probes as multi-entity) check
    this shape predicate first and then layer on the probe.
    """
    topic_tokens_seq = _TAIL_TOKEN_RE.findall(topic.lower())
    if len(topic_tokens_seq) < 3:
        return False
    cand_path = str(promoted.get("path", ""))
    cand_tokens_seq = _TAIL_TOKEN_RE.findall(cand_path.lower())
    return len(cand_tokens_seq) == 1 and cand_tokens_seq == topic_tokens_seq[-1:]


def is_single_token_tail_match(promoted: Dict[str, Any], topic: str) -> bool:
    """Floor-free sibling of :func:`is_tail_hijack_shape`: the promoted
    canonical is a single token equal to the topic's LAST token,
    regardless of topic length.

    ``is_tail_hijack_shape`` carries a ``< 3 token`` floor (the b4
    ``Berlin Germany`` carve-out) because, on the tell_me_about SOURCE
    gate, a 2-token tail can be legitimate. The cross-archive LEAK gate
    has an extra signal — provenance — so it can safely act on the
    2-token shape too (``connection refused`` -> ``Refused`` from a
    NON-PRIMARY archive). Used only by
    ``synthesize._drop_cross_archive_leakage`` (Fix 1, #253) and the Fix 2
    tail-rescue probe; the source gate keeps the floored predicate.
    """
    topic_tokens_seq = _TAIL_TOKEN_RE.findall(topic.lower())
    if not topic_tokens_seq:
        return False
    cand_tokens_seq = _TAIL_TOKEN_RE.findall(str(promoted.get("path", "")).lower())
    return len(cand_tokens_seq) == 1 and cand_tokens_seq == topic_tokens_seq[-1:]


# English stop-word inventory used by the multi-entity discriminator
# to skip tokens that are not entities even when libzim's title index
# happens to resolve them (``What``, ``Is``, ``The``, ``Of`` all exist
# as articles or disambiguation pages on Wikipedia). The list is
# conservative — only words that are clearly non-content in a
# tell-me-about query. Domain-specific common words (``population``,
# ``character``, ``radioactivity``) deliberately stay OUT so the
# discriminator still catches multi-entity queries that happen to
# include those words.
_DISCRIMINATOR_STOP_WORDS: frozenset[str] = frozenset(
    {
        # Question words
        "what",
        "when",
        "where",
        "who",
        "whom",
        "whose",
        "which",
        "why",
        "how",
        # Articles
        "a",
        "an",
        "the",
        # Conjunctions
        "and",
        "or",
        "but",
        "nor",
        "yet",
        # Prepositions
        "of",
        "in",
        "on",
        "at",
        "to",
        "from",
        "by",
        "with",
        "as",
        "into",
        "onto",
        "over",
        "under",
        "about",
        # Auxiliary verbs
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "can",
        "could",
        # Pronouns / determiners
        "i",
        "me",
        "my",
        "we",
        "us",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "it",
        "its",
        "they",
        "them",
        "their",
        "this",
        "that",
        "these",
        "those",
        # Politeness
        "please",
        "kindly",
        # Filler adverbs
        "also",
        "too",
        "very",
        "just",
        "really",
        # Generic verbs that appear in pure-filler prose contexts
        # ("people who live in michigan"). Kept narrow to verbs that
        # are pure structural connectors; nouns stay OUT.
        "live",
        "lived",
        "lives",
        "make",
        "makes",
        "made",
    }
)


def count_non_tail_strong_entities(
    topic: str,
    title_probe: Callable[[str], Optional[Dict[str, Any]]],
    *,
    limit: int = 2,
) -> int:
    """Probe each non-tail topic token; count how many resolve to a
    strong title match where the probed token actually appears in
    the resolved canonical or pre-redirect path tokens.

    Case-independent multi-entity discriminator — used by
    ``_promote_topic_via_title_index`` to distinguish the
    silent-wrong-answer pattern (multiple stacked proper-noun-
    shaped tokens like ``Stalin USSR Russia``, ``Hitler Germany
    Berlin``, ``O'Brien character 1984``) from filler-prose +
    tail-entity (``what is the population of detroit``, ``musicians
    from tokyo``, ``people who live in michigan``).

    Two refinements over a raw probe-counting check:

      1. **Stop-word filter** — non-entity tokens (``what``, ``is``,
         ``the``, ``of``, common pronouns/auxiliaries) are skipped
         even though they often resolve to a real Wikipedia
         disambiguation page. Without the filter, ``what is the
         population of detroit`` would probe to four+ false-positive
         matches and over-reject the documented Pass 1 1-token-tail
         feature.
      2. **Probed-token-in-canonical check** — the probe result is
         only counted when the probed token (lowercased) appears in
         the canonical path tokens OR the pre-redirect-path tokens.
         This filters out fuzzy/stemming hits where libzim's
         suggestion-search lands on an unrelated article AND defends
         against overly-permissive test mocks that return the same
         row regardless of input.

    The b10 discriminator counted capitalized tokens in the original-
    case topic but ``IntentParser._normalize_topic_case`` (Tier 1
    Rule 1, ``intent_parser.py``) lowercases the query upstream, so
    the gate never saw any capitalized tokens on live data. Probing
    sidesteps the case-sensitivity assumption entirely.

    Stops counting at ``limit`` (default 2) to avoid wasted probes
    when the discriminator's decision is already made.

    Topics with fewer than 3 tokens return 0 immediately — the
    tail-hijack rule those topics interact with doesn't fire for
    them either, so probing is wasted work.

    Exceptions from individual probe calls are swallowed (treated
    as "no match") so a transient libzim error on one token doesn't
    blow up the gate.
    """
    tokens = _TAIL_TOKEN_RE.findall(topic.lower())
    if len(tokens) < 3:
        return 0
    non_tail = tokens[:-1]
    count = 0
    for tok in non_tail:
        if tok in _DISCRIMINATOR_STOP_WORDS:
            continue
        try:
            result = title_probe(tok)
        except Exception:
            continue
        if result is None:
            continue
        cand_path = str(result.get("path", "")).lower()
        pre_path = str(result.get("pre_redirect_path", "")).lower()
        haystack_tokens = set(_TAIL_TOKEN_RE.findall(cand_path)) | set(
            _TAIL_TOKEN_RE.findall(pre_path)
        )
        if tok not in haystack_tokens:
            continue
        count += 1
        if count >= limit:
            break
    return count


def is_tangential_multi_token_shape(promoted: Dict[str, Any], topic: str) -> bool:
    """Post-b11 Z4: shape predicate for multi-token canonical tangential
    promotions.

    Returns True iff ``promoted``'s canonical path is multi-token AND
    its tokens are NOT a subset of the topic's tokens. The subset rule
    preserves the b8 ``Apollo 11 moon landing`` → ``Moon_landing`` and
    ``Lincoln Gettysburg Address`` → ``Gettysburg_Address`` invariants
    (canonical ⊆ topic = generalization of topic, NOT tangential), while
    flagging the silent-wrong-answer pattern at v2.0.0b11 where the
    canonical contains the topic head as a subordinate (possessive,
    parenthetical, stem prefix) AND adds modifier tokens that the user
    never supplied:

      * ``Tesla electricity`` → ``Tesla's_Wireless_Electricity`` (extras:
        ``wireless``)
      * ``Mozart Vienna`` → ``Mozarthaus_Vienna`` (extras: ``mozarthaus``)
      * ``Lenin Russia`` → ``Leninist_Komsomol_of_the_Russian_Federation``
        (extras: ``leninist``, ``komsomol``, ``of``, ``the``, ``russian``,
        ``federation``)
      * ``Beethoven symphony`` → ``Symphony_No._1_(Beethoven)`` (extras:
        ``no``, ``1``)

    Topic-size guards:

      * Topics with <2 tokens: no head/modifier distinction, no Z4. The
        bare-head case (``Picasso``) already routes through
        ``is_strong_title_match`` at the BM25 stage.
      * Single-token canonicals: ``is_tail_hijack_shape`` territory
        (b9/b10 single-token-tail rule).

    Sibling shape predicate to ``is_tail_hijack_shape``: the b11 b10 rule
    catches 1-token-tail hijacks; this catches the symmetric multi-token
    case. The discriminator at the call site layers exemptions on top
    (biographical canonical via head probe, numbered-instance via digit
    specificity) — this predicate is pure logic.
    """
    topic_tokens_seq = _TAIL_TOKEN_RE.findall(topic.lower())
    if len(topic_tokens_seq) < 2:
        return False
    cand_path = str(promoted.get("path", ""))
    cand_tokens_seq = _TAIL_TOKEN_RE.findall(cand_path.lower())
    if len(cand_tokens_seq) < 2:
        return False
    topic_tokens = set(topic_tokens_seq)
    # Filter function-word tokens (articles, conjunctions, prepositions)
    # from the canonical when checking subset. These structural tokens
    # ("of", "the", "a", "and") surface in canonical paths like
    # ``Constitution_of_the_United_States`` or
    # ``Assassination_of_John_F._Kennedy`` without changing the
    # canonical's identity — they shouldn't flag the canonical as
    # tangential just because the topic ``united states constitution``
    # or ``john f kennedy assassination`` omits them. Verbs and pronouns
    # stay OUT of this filter: ``Made_in_USA`` (canonical extra ``made``)
    # for topic ``USA products`` SHOULD reject (user didn't ask for the
    # ``Made in USA`` label specifically).
    cand_meaningful = set(cand_tokens_seq) - _CANONICAL_FUNCTION_WORDS
    return not cand_meaningful.issubset(topic_tokens)


# Narrow function-word filter for the Z4 canonical-subset check —
# articles, conjunctions, and prepositions that surface in canonical
# paths without changing the canonical's meaning. Distinct from
# ``_DISCRIMINATOR_STOP_WORDS`` (which is broader, used for head-
# selection and entity-probe filtering) because we don't want to
# filter verbs or pronouns from the canonical (``Made_in_USA`` should
# NOT be treated as ``USA`` for the subset comparison).
_CANONICAL_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "nor",
        "of",
        "in",
        "on",
        "at",
        "to",
        "from",
        "by",
        "with",
        "for",
        "as",
        "into",
        "onto",
        "over",
        "under",
    }
)


def probed_head_matches_promoted(
    topic: str,
    promoted: Dict[str, Any],
    title_probe: Callable[[str], Optional[Dict[str, Any]]],
) -> bool:
    """Post-b11 Z4 biographical-canonical exemption: probe each non-
    stop-word topic token; True iff ANY probe's canonical path (or
    pre-redirect path) equals the promoted candidate's path AND the
    probed token literally appears in the promoted canonical's tokens.

    The "subject" position in a topic varies — sometimes head
    (``Picasso Paris cubism`` → subject ``Picasso`` at position 0,
    promoted ``Pablo_Picasso``), sometimes tail (``quantum mechanics
    Einstein`` → subject ``Einstein`` at position 2, promoted
    ``Albert_Einstein``). Probing only the head misses the tail-subject
    case; probing all positions catches it.

    The TOKEN-IN-CANONICAL guard prevents accidental over-acceptance:
    ``Darwin evolution Galapagos`` → ``Galápagos_Islands`` would also
    match if we accepted on path-only — ``galapagos`` probes to
    ``Galápagos_Islands`` which equals promoted. But raw token
    comparison shows ``galapagos`` ∉ canonical tokens ``{galápagos,
    islands}`` (accent difference), so the guard correctly rejects.
    The same guard rejects ``Lenin Russia`` →
    ``Leninist_Komsomol_of_the_Russian_Federation`` (probes don't
    match promoted path) and ``Tesla electricity`` →
    ``Tesla's_Wireless_Electricity`` (probes return ``Nikola_Tesla`` /
    ``Electricity``, neither matches promoted).

    Stop-word topic tokens are skipped (``the picasso paintings``
    skips ``the``, lands on ``picasso``). Probe exceptions are
    swallowed for transient-error tolerance.
    """
    tokens = _TAIL_TOKEN_RE.findall(topic.lower())
    promoted_path = str(promoted.get("path", "")).lower()
    if not promoted_path:
        return False
    cand_tokens = set(_TAIL_TOKEN_RE.findall(promoted_path))
    for tok in tokens:
        if tok in _DISCRIMINATOR_STOP_WORDS:
            continue
        # Token-in-canonical guard runs FIRST — cheap pre-filter. A
        # probe that wouldn't satisfy this guard is wasted work.
        if tok not in cand_tokens:
            continue
        try:
            result = title_probe(tok)
        except Exception:
            continue
        if result is None:
            continue
        probe_path = str(result.get("path", "")).lower()
        probe_pre = str(result.get("pre_redirect_path", "") or "").lower()
        if probe_path == promoted_path or probe_pre == promoted_path:
            return True
    return False


def has_digit_specificity_match(promoted: Dict[str, Any], topic: str) -> bool:
    """Post-b11 Z4 digit-specificity exemption: True iff the canonical's
    extras (tokens NOT in topic) include a digit-bearing token AND the
    topic also has a digit-bearing token.

    Without this exemption, Z4 over-rejects legitimate numbered sub-
    article promotions — ``Beethoven 9th symphony`` →
    ``Symphony_No._9_(Beethoven)`` has canonical extras ``{no, 9}`` and
    the topic explicitly carries the ordinal ``9th``. The user signaled
    they want a numbered instance; the canonical's digit matches.
    Allow.

    The asymmetric "extras digit AND topic digit" shape distinguishes
    legitimate numbered queries from defect cases like ``Beethoven
    symphony`` → ``Symphony_No._1_(Beethoven)`` (canonical has digit
    extra ``1``, topic has NO digit — user never asked for symphony #1
    specifically; this is the system silently picking one instance).
    Subset cases (``Apollo 11`` for ``apollo 11 mission`` where the
    canonical digit ``11`` is already in topic, so no digit extras) are
    handled by the subset rule in ``is_tangential_multi_token_shape``
    before reaching this check — no extras means no exemption claim.
    """
    cand_path = str(promoted.get("path", ""))
    cand_tokens = set(_TAIL_TOKEN_RE.findall(cand_path.lower()))
    topic_tokens = set(_TAIL_TOKEN_RE.findall(topic.lower()))
    extras = cand_tokens - topic_tokens
    return _any_token_has_digit(extras) and _any_token_has_digit(topic_tokens)


def _any_token_has_digit(tokens: set[str]) -> bool:
    """True iff any token in ``tokens`` contains an ASCII digit
    character. Used by ``has_digit_specificity_match`` to detect
    ordinal/numbered tokens like ``9th``, ``11``, ``1949``."""
    return any(any(c.isdigit() for c in t) for t in tokens)


def has_topic_prefix_canonical_extension(promoted: Dict[str, Any], topic: str) -> bool:
    """Post-b11 Z4 type-extension exemption: canonical's LEADING tokens
    form a contiguous slice of the topic's tokens (length ≥ 2), AND the
    remaining canonical tail tokens are all extras (not in topic).

    Catches the type-name extension pattern: ``Big Rapids Michigan
    Ferris State`` (topic) → ``Ferris_State_University`` (canonical
    starts with topic-slice ``ferris state``, adds type word
    ``university``).  This is symmetric to the biographical-prefix
    pattern handled by ``probed_head_matches_promoted`` (matched
    tokens at SUFFIX of canonical, extras at prefix); the
    type-extension case has matched tokens at PREFIX, extras at
    suffix.

    Requires the matched slice to be at least 2 tokens long. A
    1-token slice would over-match — single-token coincidences are
    common in tangential promotions (``Lenin Russia`` →
    ``Leninist_Komsomol_of_the_Russian_Federation`` shares 0 raw
    tokens; ``Mao China revolution`` shares only ``china`` at
    canonical position 6 of 9). The 2-token floor pins the rule to
    the "type extension" shape where the matched slice is a coherent
    entity name.

    Defect cases stay rejected — none of them have a canonical
    starting with a contiguous 2+-token topic slice:

      * ``Tesla electricity`` → ``Tesla's_Wireless_Electricity``:
        canonical prefix ``tesla's`` ≠ topic ``tesla`` (raw token
        comparison), so the prefix-match search fails.
      * ``Mozart Vienna`` → ``Mozarthaus_Vienna``: canonical prefix
        ``mozarthaus`` ≠ topic ``mozart``.
      * ``Lenin Russia`` → ``Leninist_Komsomol_...``: canonical
        prefix ``leninist`` ≠ topic ``lenin``.
      * ``Beethoven symphony`` → ``Symphony_No._1_(Beethoven)``:
        canonical prefix [``symphony``, ``no``] not contiguous in
        topic.
    """
    cand_path = str(promoted.get("path", ""))
    cand_tokens = _TAIL_TOKEN_RE.findall(cand_path.lower())
    if len(cand_tokens) < 2:
        return False
    topic_tokens = _TAIL_TOKEN_RE.findall(topic.lower())
    if len(topic_tokens) < 2:
        return False
    topic_set = set(topic_tokens)
    # Try the longest canonical prefix first; the first match wins.
    # Longest-first ensures multi-token entity names ("Ferris State")
    # are detected before any shorter coincidental prefix.
    for prefix_len in range(min(len(cand_tokens), len(topic_tokens)), 1, -1):
        prefix = cand_tokens[:prefix_len]
        suffix = cand_tokens[prefix_len:]
        # The suffix must be all extras — if any suffix token also
        # appears in topic, this isn't a clean type-extension shape.
        if any(t in topic_set for t in suffix):
            continue
        # Look for ``prefix`` as a contiguous slice anywhere in
        # topic_tokens.
        for start_idx in range(len(topic_tokens) - prefix_len + 1):
            if topic_tokens[start_idx : start_idx + prefix_len] == prefix:
                return True
    return False


def _accept_possessive_fuzzy_suggest(promoted: Dict[str, Any], topic: str) -> bool:
    """Accept gate for possessive topic + ``match_type="fuzzy_suggest"``.

    Post-b8 OPP-1: the b6 D1 blanket-reject for possessive +
    fuzzy_suggest is too strict when the canonical preserves the
    user's possessor token literally. Live: ``Newton's gravity``
    falls to BM25 even though ``Newton's_law_of_universal_gravitation``
    is the obvious rank-1 BM25 canonical AND contains ``newton`` in
    the path. Carve-out: ACCEPT iff the canonical path tokens include
    any of the topic's possessor tokens. Original b6 attack surfaces
    continue to reject — ``Darwin's evolution`` → ``Evolution`` has
    no ``darwin`` in path, ``Plato's republic philosophy`` →
    ``Czech_philosophy`` has no ``plato`` in path. Uses ``_TOKEN_RE``
    (apostrophe-splitting) so ``newton's`` in the canonical surfaces
    as the bare token ``newton`` for comparison with the possessor
    list — the same tokenizer the redirect-branch subset rule uses,
    keeping both branches symmetric.
    """
    cand_path = str(promoted.get("path", ""))
    cand_tokens = set(_UNICODE_TOKEN_RE.findall(cand_path.lower()))
    possessors = set(extract_possessor_tokens(topic))
    return bool(possessors & cand_tokens)


def _accept_possessive_redirect(promoted: Dict[str, Any], topic: str) -> bool:
    """Accept gate for possessive topic + ``match_type="redirect"``.

    b8 Z1.1 subset rule: pre-redirect path's tokens must be a subset
    of the topic's tokens. Catches both b6 Z1 associative redirects
    (pre-path unrelated to user's possessor) and b8 Z1.1 truncation
    redirects (pre-path is a longer phrase the user truncated).

    Post-b9 OPP-1 redirect extension: when the subset rule rejects
    (pre-path has tokens not in the topic), STILL accept if the
    post-redirect canonical path preserves the user's possessor
    token literally. Live: ``Newton's gravity`` resolves through
    libzim's redirect chain ``Newton_Laws_of_Gravity`` →
    ``Newton's_law_of_universal_gravitation``; pre-path
    ``{newton, laws, of, gravity} ⊄ {newton, s, gravity}`` would
    reject under b8 Z1.1, but the post-redirect canonical literally
    contains ``newton`` — the redirect IS semantic, just one that
    libzim happened to route via a non-subset stem path.

    The b6 Z1 ``Plato's republic philosophy`` → ``Czech_philosophy``
    attack surface continues to reject because ``plato`` is not in
    ``Czech_philosophy``. The b7 Z1.1 ``Darwin's evolution`` →
    ``Evolution`` attack surface continues to reject because
    ``darwin`` is not in ``Evolution``.
    """
    pre_path = promoted.get("pre_redirect_path", "") or promoted.get("path", "")
    # ``_UNICODE_TOKEN_RE`` is the same Unicode-aware tokenizer
    # ``is_strong_title_match`` uses (M25), so pre-path-vs-topic comparison
    # stays symmetric with the rest of the title-promotion pipeline AND a
    # non-ASCII possessor (``Ampère``, ``Gödel``) is not shredded into
    # ASCII fragments that can never intersect its own canonical path.
    pre_tokens = set(_UNICODE_TOKEN_RE.findall(pre_path.lower()))
    if not pre_tokens:
        # Empty pre-path (shouldn't happen in practice but the data
        # layer doesn't strictly require non-empty) — fall back to
        # accept so we don't silently reject a row a sibling code
        # path depends on.
        return True
    topic_tokens = set(_UNICODE_TOKEN_RE.findall(topic.lower()))
    if pre_tokens.issubset(topic_tokens):
        return True
    cand_path = str(promoted.get("path", ""))
    cand_tokens = set(_UNICODE_TOKEN_RE.findall(cand_path.lower()))
    possessors = set(extract_possessor_tokens(topic))
    return bool(possessors & cand_tokens)


def passes_z4(
    promoted: Dict[str, Any],
    topic: str,
    title_probe: Callable[[str], Optional[Dict[str, Any]]],
) -> bool:
    """Post-b11 Z4 layer, shared by the tell_me_about
    (``topic_preprocessing.promote_topic_via_title_index``) and
    synthesize (``synthesize._promote_title_match``) promotion paths so
    the two cannot drift.

    Accept the promotion UNLESS it is a multi-token tangential canonical
    (``is_tangential_multi_token_shape``) with none of the three
    exemptions: biographical-canonical (a topic token probes to the same
    canonical), digit-specificity (numbered instance), or type-extension
    (canonical's leading tokens are a 2+-token contiguous topic slice).
    Possessive topics bypass Z4 — their own accept gate
    (``accept_possessive_promotion``) handles them.
    """
    if has_apostrophe_possessive(topic):
        return True
    if not is_tangential_multi_token_shape(promoted, topic):
        return True
    if probed_head_matches_promoted(topic, promoted, title_probe):
        return True
    if has_digit_specificity_match(promoted, topic):
        return True
    if has_topic_prefix_canonical_extension(promoted, topic):
        return True
    return False


def accept_tail_promotion(
    promoted: Dict[str, Any],
    topic: str,
    title_probe: Callable[[str], Optional[Dict[str, Any]]],
) -> bool:
    """Acceptance gate for a tail-iteration title promotion.

    Shared by the tell_me_about tail loop (Pass 1 / Pass 2 of
    ``promote_topic_via_title_index``) and the synthesize tail loop
    (``_promote_title_match``) so a tail-hijack cannot slip through one
    path while the other guards it — the post-b4 D3 / "synthesize never
    got the treatment" drift class. ``title_probe`` resolves a single
    topic token to a title-index hit (or ``None``); it is used by the
    multi-entity discriminator and the Z4 biographical exemption.

    Possessive topics defer entirely to ``accept_possessive_promotion``
    (the b6/b7/b8 possessor-token rules). Non-possessive topics apply
    the base accept gate; if it rejects as a single-token tail-hijack
    (``Stalin USSR Russia`` -> ``Russia``, ``ssh connection refused`` ->
    ``Refused``), the b10 single-entity escape re-accepts ONLY when the
    topic is genuine filler-prose around one entity (fewer than two
    OTHER strong entities probe successfully — ``what is the population
    of detroit`` -> ``Detroit`` stays accepted). Otherwise the Z4
    multi-token tangential layer applies.
    """
    if has_apostrophe_possessive(topic):
        return accept_possessive_promotion(promoted, topic)
    if not accept_possessive_promotion(promoted, topic):
        if not is_tail_hijack_shape(promoted, topic):
            return False
        return count_non_tail_strong_entities(topic, title_probe, limit=2) < 2
    return passes_z4(promoted, topic, title_probe)


def iter_query_tails(
    query: str,
    *,
    max_len: int = 4,
    min_len: int = 1,
) -> Iterator[str]:
    """Yield greedy length-down trailing token windows of ``query``.

    Used by both ``_promote_title_match`` (synthesize path) and
    ``_promote_topic_via_title_index`` (tell_me_about path) to probe
    a multi-word natural-language query for an entity that resolves
    against a ZIM archive's title index.

    Example:
        ``"who are some famous people from big rapids michigan"``
        with default bounds yields:
            ``"from big rapids michigan"``
            ``"big rapids michigan"``
            ``"rapids michigan"``
            ``"michigan"``

    The caller probes each yielded tail in order; the first to resolve
    wins. Greedy length-down picks the most specific entity that
    actually exists (``"big rapids michigan"`` beats ``"michigan"``
    when both resolve).

    Args:
        query: Natural-language query. Tokenized on alphanumeric runs,
            so punctuation between words is treated as a boundary
            (``"big rapids, michigan"`` → 3 tokens).
        max_len: Longest tail to yield. Default 4 — empirically, ZIM
            article titles rarely exceed 4 tokens, and the cost of a
            failed probe is microseconds, so a tight cap is safe.
        min_len: Shortest tail to yield. Default 1. Callers that want
            to skip single-token false positives can raise this.

    Yields:
        Tail strings reconstructed by joining tokens with single
        spaces, in the order they were found in ``query``, lowercased.
        The title-index lookups consumed by callers are case-insensitive,
        so the lowercase form is what reaches the probe regardless of
        the caller's input casing.
    """
    if not query or not query.strip():
        return
    tokens = _TAIL_TOKEN_RE.findall(query.lower())
    if not tokens:
        return
    upper = min(max_len, len(tokens))
    lower = max(1, min_len)
    for tail_len in range(upper, lower - 1, -1):
        yield " ".join(tokens[-tail_len:])


def iter_query_windows(
    query: str,
    *,
    max_len: int = 4,
    min_len: int = 1,
) -> Iterator[str]:
    """Yield non-trailing consecutive token windows of ``query``,
    longest first.

    Post-a14 sweep (A2): the trailing-tail probe in
    ``iter_query_tails`` misses queries whose entity sits at the head
    or middle (``"Big Rapids, Michigan tourism"`` — the entity is
    tokens 0..2 of 4). This helper yields the windows
    ``iter_query_tails`` does *not* yield, so the caller can probe
    head/middle entities as a fallback after trailing-tail probes have
    failed.

    The iteration is length-decreasing (4-windows before 3-windows
    before…); within a length, left-to-right. The trailing window at
    each length is skipped — callers are expected to have already
    probed those via ``iter_query_tails``.

    Example:
        ``"a b c d e"`` yields:
            ``"a b c d"``     (non-trailing 4-window)
            ``"a b c"``, ``"b c d"``  (non-trailing 3-windows)
            ``"a b"``, ``"b c"``, ``"c d"``
            ``"a"``, ``"b"``, ``"c"``, ``"d"``

    Returns nothing when the query has fewer than 2 tokens (no
    non-trailing windows exist).

    Args:
        query: Natural-language query. Tokenized the same way as
            ``iter_query_tails`` (lowercased alphanumeric runs).
        max_len: Longest window to yield. Default 4.
        min_len: Shortest window to yield. Default 1.

    Yields:
        Window strings (single-space-joined, lowercased), in the order
        described above. Trailing windows (those whose last token is
        ``tokens[-1]``) are filtered out.
    """
    if not query or not query.strip():
        return
    tokens = _TAIL_TOKEN_RE.findall(query.lower())
    n = len(tokens)
    if n < 2:
        return
    upper = min(max_len, n)
    lower = max(1, min_len)
    for window_len in range(upper, lower - 1, -1):
        # ``start + window_len == n`` means the window is the trailing
        # tail at this length; iter_query_tails already yielded it,
        # so we skip it here.
        for start in range(n - window_len):
            yield " ".join(tokens[start : start + window_len])
