r"""Regression tests for the post-b9 beta-test sweep.

The post-b9 live-MCP sweep against v2.0.0b9 confirmed the b9 Z3 +
OPP-1 fixes land at the unit-test level but BOTH bypass the actual
live silent-wrong-answer code paths because b9 gated on the wrong
``match_type``.

## Z3-bypass (HIGH) — tail-hijack lives on the direct/redirect branches

The b9 Z3 rule only fires inside ``_accept_non_possessive`` when
``match_type == "fuzzy_suggest"``. The live ``Stalin USSR Russia`` →
``Russia`` silent-wrong-answer routes through Pass 1
``iter_query_tails`` (full topic returns ``None`` from
``find_title_match``, so the next pass kicks in), where the
1-token tail ``"russia"`` is passed to ``find_title_match``.
libzim sees ``"russia" == "Russia"`` case-insensitively → returns
``match_type="direct"`` at score 1.0. The accept gate routes to
``_accept_non_possessive`` with ``match_type="direct"`` →
``if match_type != "fuzzy_suggest": return True`` → immediate
ACCEPT → silently returns Russia.

The same shape applies to every Z3 repro at the live deployment:

  * ``Stalin USSR Russia`` → Pass 1 ``"russia"`` direct
  * ``Hitler Germany Berlin`` → Pass 1 ``"berlin"`` direct
  * ``Marie Curie polonium discovery`` → Pass 1 ``"discovery"`` direct
  * ``Big Rapids Michigan tourism`` → Pass 1 ``"tourism"`` direct
  * ``O'Brien character 1984`` → Pass 1 ``"1984"`` direct
  * ``Marie Curie radioactivity`` → Pass 1 ``"radioactivity"`` direct
    (libzim's title-suggest happens to fuzzy-match
    ``Radioactive_(Redniss_book)`` via stemming, but for the
    direct-match path against the ZIM corpus the canonical token
    equals the topic tail — same shape)

The fix is to generalise the b9 tail-token-hijack rule to apply to
ALL match_types (direct, redirect, fuzzy_suggest, missing), not just
fuzzy_suggest. The rule's premise — "for a non-possessive multi-
token topic, a single-token canonical equal to the topic's LAST
token is the trailing-tail-hijack pattern" — is purely about the
topic↔canonical token relationship; it doesn't depend on how libzim
resolved the match.

The zero-overlap stemming sub-rule stays gated on fuzzy_suggest
(direct matches by definition share at least the matched token, so
the rule is moot for direct/redirect).

## OPP-1-bypass (MEDIUM) — Newton's gravity redirect canonical preserves possessor

The b9 OPP-1 carve-out only fires inside
``_accept_possessive_fuzzy_suggest``. The live ``Newton's gravity``
case routes through ``_accept_possessive_redirect``: libzim returns
``Newton's_law_of_universal_gravitation`` with
``match_type="redirect"`` and
``pre_redirect_path="Newton_Laws_of_Gravity"``. The b7 Z1.1 subset
rule then rejects because ``{newton, laws, of, gravity} ⊄ {newton,
s, gravity}`` — pre-path has extras ``laws`` / ``of`` not in the
topic. OPP-1's possessor-in-canonical check never runs.

The fix is to extend OPP-1's possessor-in-canonical carve-out to
``_accept_possessive_redirect`` as a fallback after the subset rule
rejects: when ``pre_tokens ⊄ topic_tokens``, STILL accept if the
post-redirect canonical path contains any of the topic's possessor
tokens. The b6 Z1 ``Plato's republic philosophy`` →
``Czech_philosophy`` attack surface continues to reject because
``plato`` is not in ``Czech_philosophy``. The b7 Z1.1
``Darwin's evolution`` → ``Evolution`` attack surface continues to
reject because ``darwin`` is not in ``Evolution``.

Decision matrix for possessive + redirect:

  +----------------------+-------------------------------+--------+
  | Topic                | Resolved canonical            | Decide |
  +----------------------+-------------------------------+--------+
  | ``Plato's cave``     | ``Allegory_of_the_cave`` via  | ACCEPT |
  |                      | pre=``Plato's_cave``          | (b8)   |
  | ``Einstein's theory``| ``Theory_of_relativity`` via  | ACCEPT |
  |                      | pre=``Einstein's_theory``     | (b8)   |
  | ``Newton's gravity`` | ``Newton's_law_of_…`` via     | ACCEPT |
  |                      | pre=``Newton_Laws_of_Gravity``| (OPP-1)|
  | ``Darwin's evolution``| ``Evolution`` via            | REJECT |
  |                      | pre=``Darwin's_Theory_of_…``  | (b7)   |
  | ``Plato's republic … ``| ``Czech_philosophy``        | REJECT |
  |                      |                               | (b6)   |
  +----------------------+-------------------------------+--------+
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from tests._promote_fixtures import fake_find_title_match as _fake_find_title_match
from tests._promote_fixtures import run_promote_simple as _run_promote_simple

# ---------------------------------------------------------------------------
# Z3-bypass: tail-token hijack must fire on direct + redirect match_types
# ---------------------------------------------------------------------------


class TestZ3TailHijackAllMatchTypes:
    """The b9 Z3 rule only fired on ``match_type="fuzzy_suggest"``.
    The live silent-wrong-answers route through ``direct`` (the Pass
    1 tail-probe path). The rule must fire regardless of match_type."""

    @pytest.mark.parametrize(
        "match_type",
        ["direct", "redirect", "fuzzy_suggest"],
        ids=["direct", "redirect", "fuzzy_suggest"],
    )
    @pytest.mark.parametrize(
        "topic, canonical_path",
        [
            ("Stalin USSR Russia", "Russia"),
            ("Hitler Germany Berlin", "Berlin"),
            ("Marie Curie polonium discovery", "Discovery"),
            ("Big Rapids Michigan tourism", "Tourism"),
            ("O'Brien character 1984", "1984"),
        ],
        ids=[
            "stalin_ussr_russia",
            "hitler_germany_berlin",
            "marie_curie_polonium_discovery",
            "big_rapids_michigan_tourism",
            "obrien_character_1984",
        ],
    )
    def test_tail_hijack_rejected_regardless_of_match_type(
        self, topic: str, canonical_path: str, match_type: str
    ) -> None:
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": canonical_path,
            "title": canonical_path.replace("_", " "),
            "match_type": match_type,
            "pre_redirect_path": canonical_path,
        }
        assert accept_possessive_promotion(promoted, topic) is False, (
            f"Z3 must reject {canonical_path!r} for topic {topic!r} when "
            f"match_type={match_type!r}: canonical is a single token equal "
            f"to topic's last token — the tail-hijack pattern, regardless "
            f"of how libzim resolved the match."
        )


class TestZ3TailHijackRegressionGuards:
    """Counter-cases that MUST keep working under the extended Z3 rule."""

    @pytest.mark.parametrize(
        "match_type",
        ["direct", "redirect", "fuzzy_suggest"],
        ids=["direct", "redirect", "fuzzy_suggest"],
    )
    @pytest.mark.parametrize(
        "topic, canonical_path",
        [
            # HEAD position: canonical's single token matches topic's
            # FIRST token, not last. Must ACCEPT — the user's primary
            # subject is at the head.
            ("Hamlet Denmark prince", "Hamlet"),
            ("Napoleon France emperor", "Napoleon"),
            ("Stalin USSR Russia", "Stalin"),
            ("Hitler Germany Berlin", "Hitler"),
        ],
        ids=[
            "hamlet_at_head",
            "napoleon_at_head",
            "stalin_at_head",
            "hitler_at_head",
        ],
    )
    def test_head_position_canonical_accepted(
        self, topic: str, canonical_path: str, match_type: str
    ) -> None:
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": canonical_path,
            "title": canonical_path.replace("_", " "),
            "match_type": match_type,
            "pre_redirect_path": canonical_path,
        }
        assert accept_possessive_promotion(promoted, topic) is True, (
            f"Z3 must NOT reject {canonical_path!r} for topic {topic!r}: "
            f"canonical at HEAD position is the user's subject, not "
            f"a noisy tail hijack."
        )

    def test_multi_token_canonical_accepted(self) -> None:
        """Multi-token canonical = real phrase match, never a tail
        hijack. Apollo 11 moon landing → Moon_landing is the
        canonical Pass-0 example."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Moon_landing",
            "title": "Moon landing",
            "match_type": "fuzzy_suggest",
            "pre_redirect_path": "Moon_landing",
        }
        assert accept_possessive_promotion(promoted, "Apollo 11 moon landing") is True

    def test_two_token_topic_unaffected(self) -> None:
        """The Z3 rule requires the topic to have 3+ tokens. 2-token
        topics like ``Berlin Germany`` continue to ACCEPT under the
        b4 carve-out (handled here AND at ``is_strong_title_match``
        BM25-stage)."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Berlin",
            "title": "Berlin",
            "match_type": "direct",
            "pre_redirect_path": "Berlin",
        }
        assert accept_possessive_promotion(promoted, "Berlin Germany") is True

    def test_single_token_topic_unaffected(self) -> None:
        """A literal user query of ``Russia`` (1 token) must still
        auto-fetch Russia — the Z3 rule is gated to multi-token
        topics specifically."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Russia",
            "title": "Russia",
            "match_type": "direct",
            "pre_redirect_path": "Russia",
        }
        assert accept_possessive_promotion(promoted, "Russia") is True


# ---------------------------------------------------------------------------
# OPP-1-bypass: possessive redirect carve-out
# ---------------------------------------------------------------------------


class TestOPP1RedirectExtension:
    """The b9 OPP-1 carve-out only fired on
    ``_accept_possessive_fuzzy_suggest``. The live ``Newton's gravity``
    case routes through ``_accept_possessive_redirect``: pre-path
    fails the b7 Z1.1 subset rule but the post-redirect canonical
    path preserves the user's possessor token. Extend OPP-1 to the
    redirect branch."""

    def test_newtons_gravity_redirect_accepted_via_canonical_possessor(
        self,
    ) -> None:
        """Live OPP-1 repro on the redirect branch.

        libzim returns ``Newton's_law_of_universal_gravitation`` with
        ``match_type="redirect"`` and
        ``pre_redirect_path="Newton_Laws_of_Gravity"``.

        - Subset rule: ``{newton, laws, of, gravity} ⊄ {newton, s,
          gravity}`` → would reject.
        - Extended OPP-1: ``newton`` IS in canonical tokens
          ``{newton, s, law, of, universal, gravitation}`` → ACCEPT.
        """
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Newton's_law_of_universal_gravitation",
            "title": "Newton's law of universal gravitation",
            "match_type": "redirect",
            "pre_redirect_path": "Newton_Laws_of_Gravity",
        }
        assert accept_possessive_promotion(promoted, "Newton's gravity") is True

    def test_b7_z11_darwin_evolution_still_rejected(self) -> None:
        """b7 Z1.1 attack surface preserved: the post-redirect
        canonical ``Evolution`` drops the possessor entirely, so
        even the extended OPP-1 (possessor-in-canonical) finds no
        ``darwin`` → REJECT."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Evolution",
            "title": "Evolution",
            "match_type": "redirect",
            "pre_redirect_path": "Darwin's_Theory_of_Evolution",
        }
        assert accept_possessive_promotion(promoted, "Darwin's evolution") is False

    def test_b6_z1_platos_philosophy_still_rejected(self) -> None:
        """b6 Z1 attack surface preserved: ``Plato's republic
        philosophy`` → ``Czech_philosophy`` has neither pre-subset
        nor ``plato`` in canonical → REJECT."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Czech_philosophy",
            "title": "Czech philosophy",
            "match_type": "redirect",
            "pre_redirect_path": "Republic_of_Plato_philosophy",
        }
        assert (
            accept_possessive_promotion(promoted, "Plato's republic philosophy")
            is False
        )

    def test_b8_subset_rule_still_accepts_pre_equals_topic(self) -> None:
        """``Plato's cave`` → ``Allegory_of_the_cave`` via
        pre=``Plato's_cave``: the pre⊆topic subset rule fires FIRST
        and accepts. The extended OPP-1 check is a fallback after
        the subset rule fails, so this case is unaffected."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Allegory_of_the_cave",
            "title": "Allegory of the cave",
            "match_type": "redirect",
            "pre_redirect_path": "Plato's_cave",
        }
        assert accept_possessive_promotion(promoted, "Plato's cave") is True


# ---------------------------------------------------------------------------
# Integration through _promote_topic_via_title_index
# ---------------------------------------------------------------------------


class TestPromoteIntegration:
    """End-to-end shape: the post-b9 fix must reject the live
    silent-wrong-answer path through ``_promote_topic_via_title_index``."""

    def test_stalin_ussr_russia_pass_1_tail_probe_rejected(self) -> None:
        """Live repro: Pass 0 (full topic at 0.95) returns None;
        Pass 1's 1-token tail probe ``"russia"`` returns
        ``Russia`` at ``match_type="direct"`` score 1.0. The
        post-b10 multi-entity discriminator probes non-tail tokens
        ``stalin`` + ``ussr``; both resolve strong → 2 → reject
        Russia → falls through to Pass 2 / Pass 3 / BM25.

        Post-b10 update: the mock now includes the multi-entity
        probe entries reflecting what the live Wikipedia ZIM returns
        for those token probes.
        """
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "russia": {
                "path": "Russia",
                "title": "Russia",
                "zim_file": "test.zim",
                "match_type": "direct",
                "pre_redirect_path": "Russia",
            },
            "stalin": {
                "path": "Stalin",
                "title": "Stalin",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "ussr": {
                "path": "Soviet_Union",
                "title": "Soviet Union",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "USSR",
            },
        }
        result = _run_promote_simple(
            "Stalin USSR Russia", _fake_find_title_match(mapping)
        )
        assert result is None or result["path"] != "Russia", (
            f"post-b10 Z3 multi-entity discriminator must reject "
            f"the 1-token tail hijack `Russia` for `Stalin USSR Russia` "
            f"when non-tail tokens probe as multi-entity; got {result!r}"
        )

    def test_newtons_gravity_redirect_accepted_via_opp1_extension(self) -> None:
        """Live repro: Pass 0 returns
        ``Newton's_law_of_universal_gravitation`` at 0.95 via a
        redirect from ``Newton_Laws_of_Gravity``. b7 Z1.1 subset
        rule would reject; OPP-1 extension accepts because the
        post-redirect canonical contains ``newton``."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "newton's gravity": {
                "path": "Newton's_law_of_universal_gravitation",
                "title": "Newton's law of universal gravitation",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Newton_Laws_of_Gravity",
            },
        }
        result = _run_promote_simple(
            "Newton's gravity",
            _fake_find_title_match(mapping, min_score_floor=0.95),
        )
        assert (
            result is not None
            and result["path"] == "Newton's_law_of_universal_gravitation"
        )


# ---------------------------------------------------------------------------
# Structural pins
# ---------------------------------------------------------------------------


class TestStructuralGuards:
    """Lightweight pins that catch accidental revert of the post-b9
    extensions at the source level."""

    def test_non_possessive_helper_does_not_short_circuit_on_match_type(
        self,
    ) -> None:
        """Structural pin: ``_accept_non_possessive`` must NOT
        short-circuit non-fuzzy_suggest match_types with an early
        ``return True`` BEFORE the tail-hijack check. The b9
        implementation had::

            if match_type != "fuzzy_suggest":
                return True

        which bypassed the Z3 rule for direct/redirect — exactly
        the silent-wrong-answer code path in the live deployment.
        """
        import ast
        import inspect

        from openzim_mcp import title_promotion

        source = inspect.getsource(title_promotion._accept_non_possessive)
        tree = ast.parse(source).body[0]
        # Walk the function body (NOT the docstring) and assert no
        # ``if match_type != "fuzzy_suggest": return True`` early-
        # return exists at the top level.
        for node in tree.body:
            if not isinstance(node, ast.If):
                continue
            try:
                cond = ast.unparse(node.test)
            except AttributeError:  # pragma: no cover (py<3.9)
                continue
            if (
                "match_type" in cond
                and "fuzzy_suggest" in cond
                and "!=" in cond
                and isinstance(node.body[0], ast.Return)
                and isinstance(node.body[0].value, ast.Constant)
                and node.body[0].value.value is True
            ):
                raise AssertionError(
                    "_accept_non_possessive must not short-circuit "
                    "non-fuzzy_suggest match_types — the tail-hijack "
                    "rule must run for direct/redirect too "
                    "(post-b9 Z3 extension)"
                )

    def test_pass_1_and_pass_2_consult_accept_gate(self) -> None:
        """Structural pin: ``_promote_topic_via_title_index`` must
        consult ``accept_possessive_promotion`` on EVERY pass that
        returns a promoted row, not just pass-0 and pass-3. The b9
        implementation had Pass 1 (tail-iter) and Pass 2 (window-
        iter) returning ``promoted`` unconditionally; that's the
        live Z3 silent-wrong-answer code path (1-token tail
        ``"russia"`` → direct match → returned without gating).

        Post-b10 update: Pass 1 / Pass 2 now go through the
        ``_accept_with_multi_entity_check`` wrapper (defined inside
        ``_promote_topic_via_title_index``) which calls
        ``accept_possessive_promotion`` once. So the dispatcher
        source has three direct ``accept_possessive_promotion(`` call
        sites — Pass 0, the wrapper, and Pass 3 — plus the helper
        invocation. The pin asserts the wrapper is wired by name AND
        every gate path is present.
        """
        # Phase F: orchestrator body lives in
        # ``openzim_mcp.topic_preprocessing.promote_topic_via_title_index``.
        import inspect

        from openzim_mcp.topic_preprocessing import promote_topic_via_title_index

        source = inspect.getsource(promote_topic_via_title_index)
        # Pass 0, the multi-entity wrapper (which calls
        # accept_possessive_promotion once), and Pass 3 → 3 direct
        # ``accept_possessive_promotion(`` callsites.
        count = source.count("accept_possessive_promotion(")
        assert count >= 3, (
            f"promote_topic_via_title_index must call "
            f"accept_possessive_promotion on every pass; found "
            f"{count} call(s), expected >= 3 (pass-0, multi-entity "
            f"wrapper covering pass-1 + pass-2, pass-3)."
        )
        # The multi-entity wrapper must be wired by name into both
        # Pass 1 (iter_query_tails) and Pass 2 (iter_query_windows).
        assert "_accept_with_multi_entity_check" in source, (
            "promote_topic_via_title_index must define + use the "
            "_accept_with_multi_entity_check wrapper to gate Pass 1 "
            "and Pass 2 with the post-b10 multi-entity discriminator"
        )

    def test_possessive_redirect_has_canonical_possessor_fallback(self) -> None:
        """Structural pin: ``_accept_possessive_redirect`` must
        reference ``extract_possessor_tokens`` so the OPP-1 redirect
        extension stays wired in (live ``Newton's gravity`` repro)."""
        import inspect

        from openzim_mcp import title_promotion

        source = inspect.getsource(title_promotion._accept_possessive_redirect)
        assert "extract_possessor_tokens" in source, (
            "_accept_possessive_redirect must consult "
            "extract_possessor_tokens for the post-b9 OPP-1 "
            "canonical-possessor fallback after the b7 Z1.1 subset "
            "rule fails"
        )
