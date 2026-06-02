"""topic_preprocessing — NL-topic promotion orchestrator + archive auto-select.

Extracted from :class:`openzim_mcp.simple_tools.SimpleToolsHandler` during the
v2 Phase F rc0 refactor. Both functions are pure (no instance state) and take
``zim_operations`` as an explicit argument so they can be re-used from the
forthcoming ``openzim_mcp.tools.zim_search`` (Phase F mode='title') without
holding a reference to a full ``SimpleToolsHandler``.

Used by:
  - :meth:`SimpleToolsHandler._promote_topic_via_title_index` (thin wrapper)
  - :meth:`SimpleToolsHandler._auto_select_zim_file` (thin wrapper)
  - ``openzim_mcp.tools.zim_search`` (Phase F mode='title') — auto-select
    always; promotion orchestrator IFF Gate 0b takes the wired path.

The byte-identical-behavior contract is enforced by the Gate 0a parity
diff-tests in ``tests/dispatch_eval/test_promotion_extraction_parity.py``
(94 b1→b13 probes against a live Wikipedia ZIM) and
``tests/dispatch_eval/test_auto_select_extraction_parity.py`` (4 archive-count
scenarios with caplog comparison).

Log-name preservation: :func:`auto_select_zim_file` emits via the
``openzim_mcp.simple_tools`` logger (not this module's ``__name__``) so the
operator-visible log records carry the same ``LogRecord.name`` they did
pre-extraction, and the A3a diff-test's caplog assertion (which scopes to
``logger="openzim_mcp.simple_tools"``) continues to capture them.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .title_promotion import (
    accept_possessive_promotion,
    accept_tail_promotion,
    find_title_match,
    has_apostrophe_possessive,
    iter_query_tails,
    iter_query_windows,
    passes_z4,
)

# Preserve the pre-extraction log-record ``name`` field so the operator-
# visible diagnostic surface (and the A3a diff-test's caplog assertion)
# don't shift. The A3a parity test scopes ``caplog.at_level`` to
# ``logger="openzim_mcp.simple_tools"`` — emitting under this module's
# natural ``__name__`` would silently drop those records from the
# capture and break the byte-identical contract.
logger = logging.getLogger("openzim_mcp.simple_tools")


def promote_topic_via_title_index(
    zim_operations: Any, zim_file_path: str, topic: str
) -> Optional[Dict[str, Any]]:
    """Resolve ``topic`` to a canonical title-index hit.

    Pass order (first hit wins):

      1. Strict 1.0 gate over the trailing tails
         (``iter_query_tails``) — preserves a14's motivating
         "famous people from big rapids michigan" behavior, where
         the entity sits at the tail of the prose.
      2. Strict 1.0 gate over non-trailing sliding windows
         (``iter_query_windows``) — post-a14 sweep (F4 / A2):
         catches queries whose entity sits at the head/middle
         ("Big Rapids Michigan tourism"). Only fires when no
         trailing tail resolved strictly, so existing behavior is
         unchanged for tail-positioned entities.
      3. Typo-tolerant 0.8 gate over the trailing tails — catches
         single-edit typos like ``Photosythesis`` →
         ``Photosynthesis``.

    D6 fix (v2.0.0a9): Xapian ranks ``List of songs about Berlin``
    above the canonical ``Berlin`` article for ``query=Berlin``
    because the title-match boost isn't strong enough. The 1.0 gate
    promotes the canonical past that ranking.
    """
    # Pass 0: probe the FULL topic (with original punctuation
    # preserved) BEFORE iter_query_tails decomposes it.
    # ``iter_query_tails`` tokenizes on alphanumeric runs, so
    # apostrophe-bearing possessives split: ``einstein's theory``
    # becomes the tokens ``["einstein", "s", "theory"]`` and the
    # yielded tails (``"einstein s theory"`` / ``"s theory"`` /
    # ``"theory"``) all lose the apostrophe. The longer tails
    # then fail to match any canonical title-index entry (which
    # are stored WITH the apostrophe — ``Einstein's_theory``
    # redirects to ``Theory_of_relativity``), and the shortest
    # tail ``"theory"`` wins via the generic ``Theory`` article.
    # Probing the original topic with punctuation at the start
    # catches these. ``min_score=0.95`` mirrors the canonical-or-
    # fuzzy gate Rule 2/3/4's probe uses (intent_parser.py:317),
    # accepting both direct hits (1.0) and high-confidence
    # redirects / spelling variants (0.95). The b3 invariant
    # (regression-guarded by test_post_b3 / test_promote_function_
    # starts_with_full_topic_probe) requires this to be the FIRST
    # ``find_title_match`` call in the function.
    promoted = find_title_match(zim_operations, zim_file_path, topic, min_score=0.95)
    # Post-b4 D2: when the topic carries an apostrophe-possessive
    # (``Plato's republic philosophy`` / ``Einstein's theory
    # history``), tighten the tail-iteration floor to ``min_len=2``
    # so a generic 1-token trailing tail (``"philosophy"`` /
    # ``"history"`` / ``"tourism"``) can't silently win at strict
    # 1.0. Pass-0 already covered the legitimate "full X's Y is
    # canonical" case; further 1-token tail iteration just risks
    # picking a generic Wikipedia title that shares the word.
    pass_tail_min_len = 2 if has_apostrophe_possessive(topic) else 1

    # Token probe shared by the b10 Z3 multi-entity discriminator
    # AND the b11 Z4 head-biographical-canonical check. Wrapped
    # once and reused so the cost stays bounded at one libzim probe
    # per non-tail topic token (and one per head check).
    def _probe(token_str: str) -> Optional[Dict[str, Any]]:
        return find_title_match(zim_operations, zim_file_path, token_str)

    # Post-b11 Z4 layer + b10 Z3 multi-entity discriminator. The actual
    # logic lives in ``title_promotion.passes_z4`` /
    # ``title_promotion.accept_tail_promotion`` so the synthesize tail
    # loop (``_promote_title_match``) shares the SAME gate and the two
    # promotion paths can't drift (the post-b4 D3 /
    # "synthesize never got the treatment" class — re-confirmed by the
    # post-v2.1.3 sweep's HIGH ``ssh connection refused`` -> ``Refused``
    # inversion). These thin closures just bind the per-call ``topic``
    # and ``_probe`` so the four pass call-sites below stay terse.
    #
    # ``_passes_z4`` (Pass 0 / Pass 3): reject multi-token tangential
    # canonicals (``Lenin Russia`` -> ``Leninist_Komsomol_...``,
    # ``Mozart Vienna`` -> ``Mozarthaus_Vienna``) unless one of three
    # exemptions applies (biographical-canonical, digit-specificity,
    # type-extension like ``Big Rapids Michigan Ferris State`` ->
    # ``Ferris_State_University``).
    def _passes_z4(promoted_arg: Dict[str, Any]) -> bool:
        return passes_z4(promoted_arg, topic, _probe)

    # ``_accept_with_multi_entity_check`` (Pass 1 / Pass 2): layers the
    # b10 single-entity escape over the b9 tail-hijack rejection, then
    # Z4. Pass 0 / Pass 3 use the bare ``accept_possessive_promotion`` +
    # ``_passes_z4`` pair (no single-entity escape — that escape exists
    # for Pass 1's 1-token-tail filler-prose pattern only).
    def _accept_with_multi_entity_check(
        promoted_arg: Dict[str, Any],
    ) -> bool:
        return accept_tail_promotion(promoted_arg, topic, _probe)

    # Pass 0 acceptance: base accept gate + Z4 layer. Stalin USSR
    # Russia → Russia (tail-hijack) is rejected here unconditionally
    # because ``accept_possessive_promotion`` already says False —
    # the multi-entity escape only fires at Pass 1/2. Tesla
    # electricity → Tesla's_Wireless_Electricity is accepted by
    # ``accept_possessive_promotion`` (2-token topic, no tail-
    # hijack) but rejected by ``_passes_z4`` (tangential shape,
    # head probe differs from promoted).
    if (
        promoted is not None
        and accept_possessive_promotion(promoted, topic)
        and _passes_z4(promoted)
    ):
        return promoted

    # Pass 1: strict 1.0-score gate across every trailing tail.
    # Prefer an exact title match on any tail (even a short one)
    # over a typo-tolerant fuzzy match on a longer noisier tail.
    for tail in iter_query_tails(topic, min_len=pass_tail_min_len):
        promoted = find_title_match(zim_operations, zim_file_path, tail)
        if promoted is not None and _accept_with_multi_entity_check(promoted):
            return promoted
    # Pass 2: strict 1.0-score gate across non-trailing windows.
    # Catches head/middle-positioned entities like
    # ``Big Rapids Michigan tourism``. Length-decreasing so longer
    # (more specific) windows win.
    for window in iter_query_windows(topic, min_len=pass_tail_min_len):
        promoted = find_title_match(zim_operations, zim_file_path, window)
        if promoted is not None and _accept_with_multi_entity_check(promoted):
            return promoted
    # Pass 3: 0.8 typo-tolerant gate. Only fires when no strict
    # match exists at all — catches single-edit typos. The bare
    # ``accept_possessive_promotion`` + ``_passes_z4`` pair (no
    # multi-entity escape) is the same shape as Pass 0; the
    # escape's filler-prose pattern doesn't apply to typo-corrected
    # tails.
    for tail in iter_query_tails(topic, min_len=pass_tail_min_len):
        promoted = find_title_match(zim_operations, zim_file_path, tail, min_score=0.8)
        if (
            promoted is not None
            and accept_possessive_promotion(promoted, topic)
            and _passes_z4(promoted)
        ):
            return promoted
    return None


def auto_select_zim_file(zim_operations: Any) -> Optional[str]:
    """Auto-select a ZIM file if only one is available.

    Returns:
        Path to ZIM file if exactly one exists, None otherwise.
        Returns None with appropriate logging if multiple files exist
        or on error.
    """
    try:
        # Use structured data method directly (not parsing JSON from string)
        files = zim_operations.list_zim_files_data()

        if len(files) == 0:
            logger.info("Auto-select failed: no ZIM files found in allowed directories")
            return None
        elif len(files) == 1:
            selected = str(files[0]["path"])
            logger.debug(f"Auto-selected ZIM file: {selected}")
            return selected
        else:
            logger.info(
                f"Auto-select skipped: {len(files)} ZIM files found, "
                "please specify which file to use"
            )
            return None

    except Exception as e:
        # Log at warning level with specific error for debugging
        logger.warning(
            f"Auto-select ZIM file failed with error: {type(e).__name__}: {e}"
        )
        return None
