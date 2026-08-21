"""The promotion guards must behave the same on both ZIM namespace schemes.

libzim returns entry paths WITH the namespace segment (``A/Aerosol``) for
archives built under the old scheme — every mwoffliner Wikipedia build,
including the bundled ``test_data/zim-testing-suite/withns`` fixtures — and
bare (``Aerosol``) for new-scheme archives. Every tail-hijack predicate
tokenizes the promoted path, so the leading ``a`` silently turned the
single-token tests off and re-enabled the fabricated single-article answer
the b9/b10 rules exist to block (``antarctica coal aerosol`` -> ``A/Aerosol``
at score 1.0 with zero raw hits), while inverting the b8 Z1.1 subset rule
into a false reject for possessive redirects.

Every assertion below runs twice — once per scheme — so the two cannot
diverge again.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from openzim_mcp.title_promotion import (
    accept_possessive_promotion,
    accept_tail_promotion,
    has_topic_prefix_canonical_extension,
    is_single_token_tail_match,
    is_tail_hijack_shape,
    is_tangential_multi_token_shape,
)
from openzim_mcp.topic_preprocessing import promote_topic_via_title_index

# "" = new-scheme archive (bare paths), "A/" = old-scheme (namespaced).
SCHEMES = ("", "A/")


def _no_probe(_token: str) -> Optional[Dict[str, Any]]:
    return None


@pytest.mark.parametrize("ns", SCHEMES)
def test_tail_hijack_shape_sees_through_the_namespace(ns: str) -> None:
    assert is_tail_hijack_shape({"path": f"{ns}Russia"}, "stalin ussr russia") is True


@pytest.mark.parametrize("ns", SCHEMES)
def test_non_possessive_gate_rejects_the_tail_hijack(ns: str) -> None:
    promoted = {"path": f"{ns}Russia", "match_type": "direct"}
    assert accept_possessive_promotion(promoted, "stalin ussr russia") is False


@pytest.mark.parametrize("ns", SCHEMES)
def test_single_token_tail_match_sees_through_the_namespace(ns: str) -> None:
    assert is_single_token_tail_match({"path": f"{ns}Refused"}, "connection refused")


@pytest.mark.parametrize("ns", SCHEMES)
def test_multi_entity_tail_promotion_is_rejected(ns: str) -> None:
    """``Hitler Germany Berlin`` -> ``Berlin``: two other topic tokens probe
    to their own canonicals, so the b10 single-entity escape must not fire."""

    def probe(token: str) -> Optional[Dict[str, Any]]:
        return {"path": f"{ns}{token.capitalize()}"}

    promoted = {"path": f"{ns}Berlin", "match_type": "direct"}
    assert accept_tail_promotion(promoted, "hitler germany berlin", probe) is False


@pytest.mark.parametrize("ns", SCHEMES)
def test_filler_prose_tail_promotion_still_accepted(ns: str) -> None:
    """The b10 escape invariant: one entity wrapped in filler prose stays."""
    promoted = {"path": f"{ns}Detroit", "match_type": "direct"}
    topic = "what is the population of detroit"
    assert accept_tail_promotion(promoted, topic, _no_probe) is True


@pytest.mark.parametrize("ns", SCHEMES)
def test_single_token_canonical_is_not_z4_territory(ns: str) -> None:
    """Z4 is the multi-token rule; a 1-token canonical belongs to the
    tail-hijack rule and must not be judged under the tangential shape."""
    promoted = {"path": f"{ns}Discovery"}
    assert is_tangential_multi_token_shape(promoted, "marie curie polonium") is False


@pytest.mark.parametrize("ns", SCHEMES)
def test_type_extension_exemption_survives_the_namespace(ns: str) -> None:
    promoted = {"path": f"{ns}Ferris_State_University"}
    topic = "big rapids michigan ferris state"
    assert has_topic_prefix_canonical_extension(promoted, topic) is True


@pytest.mark.parametrize("ns", SCHEMES)
def test_semantic_possessive_redirect_is_accepted(ns: str) -> None:
    """b8 Z1.1 subset rule: ``Plato's_cave`` -> ``Allegory_of_the_cave`` is a
    semantic redirect — the namespace token must not break the subset test."""
    promoted = {
        "path": f"{ns}Allegory_of_the_cave",
        "match_type": "redirect",
        "pre_redirect_path": f"{ns}Plato's_cave",
    }
    assert accept_possessive_promotion(promoted, "plato's cave") is True


@pytest.mark.parametrize("ns", SCHEMES)
def test_namespace_letter_is_not_a_possessor_match(ns: str) -> None:
    """b6 D1: possessive + ``fuzzy_suggest`` is accepted only when the
    canonical preserves the possessor. ``Oakland A's history`` -> generic
    ``History`` must not qualify by matching the ``A`` namespace letter."""
    promoted = {"path": f"{ns}History", "match_type": "fuzzy_suggest"}
    assert accept_possessive_promotion(promoted, "oakland a's history") is False


@pytest.mark.parametrize("ns", SCHEMES)
def test_end_to_end_tail_hijack_is_refused(ns: str) -> None:
    """The reported live shape: ``zim_search(mode="title")`` for
    ``antarctica coal aerosol`` returned a single ``A/Aerosol`` row on top of
    a 0-hit page. Pass 1's 1-token tail resolves, but two other topic tokens
    probe to their own canonicals, so that tail must be refused — under both
    schemes alike."""
    titles = {"antarctica": "Antarctica", "coal": "Coal", "aerosol": "Aerosol"}

    class _Ops:
        def find_entry_by_title_data(
            self, _zim_file_path: str, probe: str, **_kwargs: Any
        ) -> Dict[str, Any]:
            title = titles.get(probe.strip().lower())
            if title is None:
                return {"results": []}
            return {
                "results": [
                    {
                        "path": f"{ns}{title}",
                        "title": title,
                        "score": 1.0,
                        "match_type": "direct",
                    }
                ]
            }

    promoted = promote_topic_via_title_index(
        _Ops(), "/data/wiki.zim", "antarctica coal aerosol"
    )
    assert promoted is not None
    # Pass 1's tail is rejected, so Pass 2's head window resolves instead.
    assert promoted["path"] == f"{ns}Antarctica"
