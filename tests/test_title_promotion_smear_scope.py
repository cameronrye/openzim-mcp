"""The punctuation-smear guard in the shared accept gates must be scoped
to the topic tokens the candidate actually resolved.

P5 put ``_punctuation_smear_detected`` into ``passes_z4`` /
``accept_tail_promotion`` because the tail probes
(``iter_query_tails``) strip load-bearing punctuation before
``find_title_match`` ever sees it, so ``c++`` probed as ``c`` and the
letter-``C`` article was promoted. That is still required.

But the check compared the WHOLE multi-token topic, so a single ``&`` /
``?`` / ``!`` anywhere vetoed every tail and window promotion — including
ones driven by a completely unrelated token. ``carbon capture & storage
technology`` lost ``A/Carbon_capture``, and every natural-language
question ending in ``?`` lost tail promotion outright, since no canonical
path ever contains one.

Both directions are pinned here: the P5 rejections, and the
false-positive vetoes the scoping removes.
"""

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from openzim_mcp.title_promotion import accept_tail_promotion, passes_z4

GATES = ("passes_z4", "accept_tail_promotion")


def _gate(name: str) -> Any:
    return {"passes_z4": passes_z4, "accept_tail_promotion": accept_tail_promotion}[
        name
    ]


def _no_probe(_topic: str) -> Optional[Dict[str, Any]]:
    return None


def _promoted(path: str) -> Dict[str, Any]:
    return {"path": path, "title": path.rsplit("/", 1)[-1], "score": 1.0}


# ---------------------------------------------------------------------------
# The regression: punctuation belonging to an unrelated part of the topic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize(
    "topic,path",
    [
        # The ``&`` sits in a phrase the candidate doesn't cover at all.
        ("carbon capture & storage technology", "A/Carbon_capture"),
        ("what causes deforestation & drought", "A/Drought"),
        ("american clean energy & security act", "A/Energy_security"),
        # Sentence framing: no canonical path ever contains ``?``.
        ("is climate change real?", "A/Climate_change"),
        ("how does the greenhouse effect work?", "A/Greenhouse_effect"),
    ],
)
def test_unrelated_punctuation_does_not_veto_promotion(gate, topic, path):
    assert _gate(gate)(_promoted(path), topic, _no_probe) is True


def test_end_to_end_tail_promotion_survives_an_ampersand(monkeypatch):
    """Through ``promote_topic_via_title_index``, which is the surface the
    regression was observed on (tell_me_about / zim_search mode=title)."""
    from openzim_mcp.topic_preprocessing import promote_topic_via_title_index

    mock = MagicMock()

    def _index(_path: str, probe: str, **_kw: Any) -> Dict[str, Any]:
        # Only the ``carbon capture`` window resolves, exactly as the real
        # title index behaves — the ``&`` token is not part of it.
        if probe.strip().lower() in {"carbon capture", "carbon capture storage"}:
            return {
                "results": [
                    {
                        "path": "A/Carbon_capture",
                        "title": "Carbon capture",
                        "score": 1.0,
                        "match_type": "direct",
                    }
                ]
            }
        return {"results": []}

    mock.find_entry_by_title_data.side_effect = _index

    promoted = promote_topic_via_title_index(
        mock, "/x.zim", "carbon capture & storage technology"
    )
    assert promoted is not None
    assert promoted["path"] == "A/Carbon_capture"


# ---------------------------------------------------------------------------
# ...while P5 itself stays fixed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize(
    "topic,smeared_path",
    [
        ("c++", "C"),
        ("f#", "F"),
        ("a* search", "A"),
        ("c++'s syntax", "C"),
        # The load-bearing char belongs to the very token that resolved.
        ("c++ tutorial", "A/C_(programming_language)"),
    ],
)
def test_smear_on_the_resolving_token_is_still_rejected(gate, topic, smeared_path):
    assert _gate(gate)(_promoted(smeared_path), topic, _no_probe) is False


@pytest.mark.parametrize("gate", GATES)
def test_no_token_overlap_falls_back_to_the_whole_topic(gate):
    """When NOTHING in the topic survives in the candidate path, the title
    index resolved it purely by normalisation — the smear case itself.
    Scoping would make the check vacuous, so the whole topic is compared.

    Observed live against the climate-change fixture: ``c++`` fuzzily
    resolves to ``A/Air_conditioning``.
    """
    assert _gate(gate)(_promoted("A/Air_conditioning"), "c++", _no_probe) is False


def test_punctuation_preserving_candidate_is_accepted():
    """The counts match, so this was never a smear."""
    assert (
        passes_z4(_promoted("A/C++"), "c++", _no_probe) is True
    ), "a candidate that keeps the ``+`` must not be vetoed"
