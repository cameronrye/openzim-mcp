r"""Direct unit tests for ``openzim_mcp.topic_preprocessing``.

Stage A Task A6 of v2 Phase F rc0. Documents the module-level
function's contract INDEPENDENTLY of its current call sites
(``SimpleToolsHandler._promote_topic_via_title_index`` /
``_auto_select_zim_file``). These tests stay in the project's main
suite so they run in normal CI without the ``--dispatch-eval`` opt-in.

Coverage targets (from
``docs/superpowers/plans/2026-05-24-v2-phase-f-tool-surface.md`` Task A6):

  * **Z3 probe-based discriminator** (b11) — multi-entity discriminator
    rejects tail-hijack canonicals when 2+ non-tail tokens probe as
    strong title matches (``Stalin USSR Russia`` → must NOT resolve to
    ``Russia``; Pass 2 head-window probes find ``Stalin`` instead).
  * **Z4 multi-token tangential rejection** (b12) — ``Tesla
    electricity`` must NOT promote to ``Tesla's_Wireless_Electricity``.
  * **Z4 biographical exemption** — ``Picasso Paris cubism`` →
    ``Pablo_Picasso`` (head probe matches promoted).
  * **Z4 digit-specificity exemption** — ``Beethoven 9th symphony`` →
    ``Symphony_No._9_(Beethoven)`` (canonical extras digit + topic
    has digit).
  * **Z4 type-extension exemption** — ``Big Rapids Michigan Ferris
    State`` → ``Ferris_State_University`` (canonical's leading 2+
    tokens form a contiguous topic slice + suffix is the type-word).
  * **OPP-1 possessive promotion** (b9) — ``Newton's gravity`` →
    ``Newton's_law_of_universal_gravitation`` (possessor token in
    canonical, OPP-1 path).
  * **auto_select_zim_file** — 0/1/N archives + exception handling.

Pattern note: re-uses the ``fake_find_title_match`` builder from
``tests/_promote_fixtures.py`` (proven scripting helper from the
b-series sweep tests). The fake is patched at
``openzim_mcp.topic_preprocessing.find_title_match`` — the live
binding the orchestrator imports at module scope. Tests target
``promote_topic_via_title_index`` directly (NOT the SimpleToolsHandler
wrapper) so the contract is documented against the extracted
module-level surface specifically.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from tests._promote_fixtures import fake_find_title_match as _fake_find_title_match

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_promote_direct(
    topic: str, mapping: Dict[str, Optional[Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    """Drive ``promote_topic_via_title_index`` (the extracted module-
    level function, NOT the SimpleToolsHandler wrapper) with
    ``mapping`` scripted as the ``find_title_match`` stand-in.

    The orchestrator only consumes ``find_title_match(zim_ops, path,
    topic, min_score=...)`` — the ``zim_operations`` object itself
    is never dereferenced inside the function, so a bare
    ``MagicMock()`` is sufficient.
    """
    from openzim_mcp.topic_preprocessing import promote_topic_via_title_index

    fake = _fake_find_title_match(mapping)
    with patch("openzim_mcp.topic_preprocessing.find_title_match", side_effect=fake):
        return promote_topic_via_title_index(MagicMock(), "test.zim", topic)


# ---------------------------------------------------------------------------
# Z3 probe-based discriminator (b11).
# ---------------------------------------------------------------------------


class TestZ3ProbeBasedDiscriminator:
    """b11: when the topic probes as multi-entity (2+ non-tail tokens
    individually resolve to strong title matches), the tail-hijack
    candidate must be rejected. Verifies the extracted orchestrator
    still routes through ``count_non_tail_strong_entities`` /
    ``is_tail_hijack_shape``."""

    def test_stalin_ussr_russia_rejects_tail_russia(self) -> None:
        """Pass 1 tail ``russia`` returns Russia direct (tail-hijack).
        Probing ``stalin`` and ``ussr`` resolves strong matches →
        multi-entity → reject Russia. Pass 2 head-window probe finds
        ``stalin`` → Stalin."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "russia": {
                "path": "Russia",
                "title": "Russia",
                "zim_file": "test.zim",
                "match_type": "direct",
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
        result = _run_promote_direct("stalin ussr russia", mapping)
        assert result is None or result["path"] != "Russia", (
            "Z3 must reject tail-hijack `Russia` when non-tail tokens "
            f"probe as multi-entity. Got: {result!r}"
        )


# ---------------------------------------------------------------------------
# Z4 multi-token tangential rejection (b12).
# ---------------------------------------------------------------------------


class TestZ4MultiTokenTangentialRejection:
    """b12: Z4 layer rejects multi-token canonical tangential matches
    that ``is_tail_hijack_shape`` doesn't cover (canonical multi-token
    AND/OR topic 2-tokens)."""

    def test_tesla_electricity_rejects_wireless_electricity(self) -> None:
        """2-token topic, canonical contains head as possessive +
        adds modifier ``wireless``. Head probe ``tesla`` resolves to
        ``Nikola_Tesla`` (distinct from promoted) → tangential → reject.
        """
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "tesla electricity": {
                "path": "Tesla's_Wireless_Electricity",
                "title": "Tesla's Wireless Electricity",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "electricity": {
                "path": "Electricity",
                "title": "Electricity",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "tesla": {
                "path": "Nikola_Tesla",
                "title": "Nikola Tesla",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Tesla",
            },
        }
        result = _run_promote_direct("tesla electricity", mapping)
        assert result is None or result["path"] != "Tesla's_Wireless_Electricity", (
            "Z4 must reject tangential multi-token canonical "
            f"`Tesla's_Wireless_Electricity`. Got: {result!r}"
        )


# ---------------------------------------------------------------------------
# Z4 exemptions (biographical / digit-specificity / type-extension).
# ---------------------------------------------------------------------------


class TestZ4BiographicalExemption:
    """Z4 must NOT reject when the head probe resolves to the same
    canonical the orchestrator is about to promote — that's the
    biographical-canonical case (the promotion IS the head's article).
    """

    def test_picasso_paris_cubism_promotes_pablo_picasso(self) -> None:
        """Head probe ``picasso`` resolves to ``Pablo_Picasso`` = the
        promoted candidate → biographical exemption → accept."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "picasso paris cubism": {
                "path": "Pablo_Picasso",
                "title": "Pablo Picasso",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Picasso",
            },
            "picasso": {
                "path": "Pablo_Picasso",
                "title": "Pablo Picasso",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Picasso",
            },
            "paris": {
                "path": "Paris",
                "title": "Paris",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "cubism": {
                "path": "Cubism",
                "title": "Cubism",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote_direct("picasso paris cubism", mapping)
        assert result is not None and result["path"] == "Pablo_Picasso"


class TestZ4DigitSpecificityExemption:
    """Z4 must NOT reject when the user explicitly signals a numbered-
    instance request via a digit/ordinal token AND the canonical's
    extras include a digit."""

    def test_beethoven_9th_symphony_promotes_specific_symphony(self) -> None:
        """Canonical extras ``{no, 9}`` include digit AND topic
        ``{beethoven, 9th, symphony}`` includes digit token →
        digit-specificity exemption → accept the specific symphony."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "beethoven 9th symphony": {
                "path": "Symphony_No._9_(Beethoven)",
                "title": "Symphony No. 9 (Beethoven)",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "9th symphony": {
                "path": "Symphony_No._9_(Beethoven)",
                "title": "Symphony No. 9 (Beethoven)",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "symphony": {
                "path": "Symphony",
                "title": "Symphony",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "beethoven": {
                "path": "Ludwig_van_Beethoven",
                "title": "Ludwig van Beethoven",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Beethoven",
            },
        }
        result = _run_promote_direct("beethoven 9th symphony", mapping)
        assert result is not None and result["path"] == "Symphony_No._9_(Beethoven)"


class TestZ4TypeExtensionExemption:
    """Z4 must NOT reject when the canonical's leading 2+ tokens form
    a contiguous topic slice AND the canonical's suffix tokens are all
    extras (the type-word case — e.g., ``Ferris State`` →
    ``Ferris_State_University``)."""

    def test_big_rapids_michigan_ferris_state_promotes_university(self) -> None:
        """Type-extension exemption: canonical's leading 2 tokens
        ``{ferris, state}`` form a contiguous slice of the topic; the
        suffix ``university`` is the type-word extra → accept."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "big rapids michigan ferris state": None,
            "rapids michigan ferris state": None,
            "michigan ferris state": None,
            "ferris state": {
                "path": "Ferris_State_University",
                "title": "Ferris State University",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "big": None,
            "rapids": None,
            "michigan": {
                "path": "Michigan",
                "title": "Michigan",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "ferris": None,
            "state": None,
        }
        result = _run_promote_direct("Big Rapids Michigan Ferris State", mapping)
        assert result is not None and result["path"] == "Ferris_State_University"


# ---------------------------------------------------------------------------
# OPP-1 possessive promotion (b9).
# ---------------------------------------------------------------------------


class TestOPP1PossessivePromotion:
    """b9 OPP-1: apostrophe-possessive topics route through
    ``accept_possessive_promotion``. When the canonical contains the
    possessor token (``newton``), the redirect-shape promotion is
    accepted at Pass 0 (full-topic probe with min_score=0.95)."""

    def test_newtons_gravity_promotes_universal_gravitation(self) -> None:
        """``Newton's gravity`` → ``Newton's_law_of_universal_gravitation``:
        possessive topic, canonical contains possessor token ``newton``
        → accept via OPP-1 redirect rule. Z4 doesn't apply to
        possessive topics (``has_apostrophe_possessive(topic)`` returns
        True at the top of ``_passes_z4`` → exempted)."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "newton's gravity": {
                "path": "Newton's_law_of_universal_gravitation",
                "title": "Newton's law of universal gravitation",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Newton's_law_of_gravity",
            },
        }
        result = _run_promote_direct("newton's gravity", mapping)
        assert result is not None and (
            result["path"] == "Newton's_law_of_universal_gravitation"
        ), (
            "OPP-1 must accept the possessive promotion when canonical "
            f"contains the possessor token. Got: {result!r}"
        )


# ---------------------------------------------------------------------------
# auto_select_zim_file — direct unit tests (no live ZIM needed).
# ---------------------------------------------------------------------------


class TestAutoSelectZimFile:
    """Pure unit tests for ``auto_select_zim_file``. The orchestrator
    only consumes ``zim_operations.list_zim_files_data()``, so a bare
    MagicMock is sufficient — no real archive needed.

    Behavior contract (from ``topic_preprocessing.py`` docstring):

      * 0 files → log INFO + return None
      * 1 file → return ``str(files[0]['path'])``
      * N files → log INFO + return None
      * raises → log WARNING + return None
    """

    def test_zero_files_returns_none(self) -> None:
        from openzim_mcp.topic_preprocessing import auto_select_zim_file

        ops = MagicMock()
        ops.list_zim_files_data = MagicMock(return_value=[])
        assert auto_select_zim_file(ops) is None

    def test_one_file_returns_path_string(self) -> None:
        from openzim_mcp.topic_preprocessing import auto_select_zim_file

        ops = MagicMock()
        ops.list_zim_files_data = MagicMock(
            return_value=[{"path": "/archives/wikipedia.zim"}]
        )
        result = auto_select_zim_file(ops)
        assert result == "/archives/wikipedia.zim"
        assert isinstance(result, str)

    def test_multiple_files_returns_none(self) -> None:
        from openzim_mcp.topic_preprocessing import auto_select_zim_file

        ops = MagicMock()
        ops.list_zim_files_data = MagicMock(
            return_value=[
                {"path": "/archives/a.zim"},
                {"path": "/archives/b.zim"},
            ]
        )
        assert auto_select_zim_file(ops) is None

    def test_exception_returns_none(self) -> None:
        """Defensive catch-all: any exception from
        ``list_zim_files_data`` (filesystem error, libzim error, etc.)
        falls through to a warning log and ``None`` return — never
        propagates."""
        from openzim_mcp.topic_preprocessing import auto_select_zim_file

        ops = MagicMock()
        ops.list_zim_files_data = MagicMock(side_effect=RuntimeError("boom"))
        assert auto_select_zim_file(ops) is None

    def test_one_file_logs_to_simple_tools_logger(self, caplog: Any) -> None:
        """Log-name preservation invariant: the extracted function
        emits via ``logging.getLogger("openzim_mcp.simple_tools")``
        (NOT this module's natural ``__name__``) so operator-visible
        log records carry the pre-extraction ``LogRecord.name``. The
        A3a parity diff-test's caplog assertion (which scopes to
        ``logger="openzim_mcp.simple_tools"``) depends on this."""
        import logging

        from openzim_mcp.topic_preprocessing import auto_select_zim_file

        ops = MagicMock()
        ops.list_zim_files_data = MagicMock(return_value=[{"path": "/x.zim"}])
        with caplog.at_level(logging.DEBUG, logger="openzim_mcp.simple_tools"):
            auto_select_zim_file(ops)
        assert any(r.name == "openzim_mcp.simple_tools" for r in caplog.records), (
            "auto_select_zim_file must emit under the "
            "`openzim_mcp.simple_tools` logger to preserve the A3a "
            "diff-test contract."
        )
