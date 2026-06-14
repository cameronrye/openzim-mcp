"""Real-world-test regressions in intent parsing:

* A pasted URL was tokenised on ``/`` and the scheme token ``https:`` was
  taken as the topic, returning the wrong article. The final path segment
  is the intended topic.
* Verbose phrasing ("show me everything about X") was not normalised, so it
  was searched literally and returned irrelevant results, while
  "tell me about X" / "define X" were stripped to the core topic.
"""

from __future__ import annotations

from openzim_mcp.intent_parser import IntentParser


def test_pasted_url_uses_final_path_segment():
    _intent, params, _cert = IntentParser.parse_intent(
        "https://en.wikipedia.org/wiki/Photosynthesis"
    )
    topic = (params.get("topic") or "").lower()
    assert topic == "photosynthesis", params


def test_pasted_url_underscores_become_spaces():
    _intent, params, _cert = IntentParser.parse_intent(
        "https://en.wikipedia.org/wiki/Climate_change"
    )
    topic = (params.get("topic") or "").lower()
    assert topic == "climate change", params


def test_pasted_url_topic_has_no_scheme_or_slashes():
    _intent, params, _cert = IntentParser.parse_intent(
        "https://en.wikipedia.org/wiki/Quantum_computing"
    )
    topic = params.get("topic") or ""
    assert "/" not in topic
    assert "http" not in topic.lower()


def test_verbose_filler_routes_to_tell_me_about_and_strips_filler():
    intent, params, _cert = IntentParser.parse_intent(
        "show me everything about photosynthesis"
    )
    assert intent == "tell_me_about", (intent, params)
    assert (params.get("topic") or "").lower() == "photosynthesis", params
