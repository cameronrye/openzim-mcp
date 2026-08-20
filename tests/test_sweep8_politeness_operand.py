"""The politeness strip must not eat an operand that is itself a courtesy word.

``_TOPIC_LIKE_POLITENESS`` exists because ``Cheers`` and ``tack`` are ordinary
article titles as well as courtesy words, and ``_strip_trailing_politeness``
refuses a pass that would consume the query's last topic-bearing token. That
guard asks ``_carries_topic`` what is left, and the answer was wrong for half
the intents: the set held ``structure`` / ``section`` / ``toc`` but not
``outline`` / ``table`` / ``contents``, so ``outline of tack`` left
``outline of`` behind and that read as topic-bearing. The guard stayed silent,
the operand was peeled, and the extractor anchored on the last keyword and
returned ``entry_path='of'`` — a confident structure dump for an entry named
"of", with no error surfaced.
"""

from __future__ import annotations

import pytest

from openzim_mcp.intent_parser import IntentParser


@pytest.fixture
def parser() -> IntentParser:
    return IntentParser()


@pytest.mark.parametrize(
    ("query", "intent", "entry_path"),
    [
        ("outline of tack", "structure", "tack"),
        ("outline of cheers", "structure", "cheers"),
        ("table of contents for cheers", "toc", "cheers"),
        ("sections of tack", "structure", "tack"),
        ("headings of cheers", "structure", "cheers"),
    ],
)
def test_courtesy_word_operand_survives(
    parser: IntentParser, query: str, intent: str, entry_path: str
) -> None:
    got_intent, params, _confidence = parser.parse_intent(query)
    assert got_intent == intent, (query, got_intent)
    assert params.get("entry_path") == entry_path, (query, params)


@pytest.mark.parametrize(
    ("query", "entry_path"),
    [
        ("outline of Berlin", "berlin"),
        ("sections of Photosynthesis", "photosynthesis"),
        ("structure of Climate_change", "climate_change"),
    ],
)
def test_ordinary_operands_are_unchanged(
    parser: IntentParser, query: str, entry_path: str
) -> None:
    """The words added to the scaffolding set must not disturb these."""
    _intent, params, _confidence = parser.parse_intent(query)
    assert params.get("entry_path") == entry_path, (query, params)


def test_genuine_trailing_politeness_is_still_peeled(parser: IntentParser) -> None:
    """The guard only refuses when peeling would leave nothing to act on."""
    _intent, params, _confidence = parser.parse_intent("outline of Berlin please")
    assert params.get("entry_path") == "berlin", params
