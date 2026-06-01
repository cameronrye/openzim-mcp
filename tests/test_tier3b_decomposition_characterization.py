"""Characterization tests pinning the behavior of the methods decomposed in
the Tier 3b refactor sweep, for branches the existing suite only covered via
their building blocks (helpers / source-text greps) rather than end-to-end.

These exist to give the behavior-preserving decomposition of
``handle_zim_query`` (param-strip seam) and ``_handle_tell_me_about``
(topic-resolution seam) a real net: they assert the *current* observable
behavior so a seam extraction that silently drops a field or reorders a
branch turns a test red.
"""

from typing import Any, Dict, Tuple
from unittest.mock import MagicMock

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler

# ---------------------------------------------------------------------------
# handle_zim_query: the defence-in-depth politeness-strip loop (params)
# ---------------------------------------------------------------------------


class TestParamStripLoopCharacterization:
    """The post-a21/a22 dispatcher-edge politeness strip cleans a fixed set
    of user-content fields in ``params``. Only the ``query`` field had a
    real behavioral test (a21); ``topic`` / ``title`` / ``entry_path`` /
    ``partial_query`` / ``section_name`` and the ``entries`` list were pinned
    only by source-text grep tests, which a refactor could satisfy while
    silently changing runtime behavior. Pin the runtime transform here.
    """

    # Each scalar field carries a base + trailing politeness that the strip
    # must peel. Values are chosen so the strip is non-trivial (changes them).
    SCALAR_FIELDS = (
        ("query", "biology please"),
        ("topic", "Berlin please"),
        ("title", "Tiger please"),
        ("entry_path", "C/Tiger please"),
        ("partial_query", "evol please"),
        ("section_name", "History please"),
    )

    def _strip(self, raw: str) -> str:
        return IntentParser._strip_trailing_politeness(raw).strip()

    def _run_with_params(
        self, monkeypatch: pytest.MonkeyPatch, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Drive ``handle_zim_query`` with a monkeypatched ``parse_intent``
        that returns ``params`` verbatim under the ``list_files`` intent
        (which returns before any content dispatch). The strip loop mutates
        ``params`` in place, so the same dict object reflects the result.
        """

        def fake_parse(
            query: str, *, title_probe: Any = None, query_rewrite_enabled: bool = True
        ) -> Tuple[str, Dict[str, Any], float]:
            return "list_files", params, 0.99

        monkeypatch.setattr(IntentParser, "parse_intent", staticmethod(fake_parse))
        handler = SimpleToolsHandler(MagicMock())
        handler.handle_zim_query(query="list files", zim_file_path="/x.zim")
        return params

    def test_all_scalar_fields_are_stripped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params: Dict[str, Any] = {k: v for k, v in self.SCALAR_FIELDS}
        result = self._run_with_params(monkeypatch, params)
        for field, raw in self.SCALAR_FIELDS:
            expected = self._strip(raw)
            assert result[field] == expected, (
                f"field {field!r} not stripped at dispatcher edge: "
                f"{result[field]!r} != {expected!r}"
            )
            # Guard against a vacuous test: each value must actually change.
            assert expected != raw

    def test_entries_list_is_stripped_per_element(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw_entries = ["C/Apple please", "C/Banana please"]
        params: Dict[str, Any] = {"entries": list(raw_entries)}
        result = self._run_with_params(monkeypatch, params)
        assert result["entries"] == [self._strip(e) for e in raw_entries]
        assert result["entries"] != raw_entries

    def test_pre_rewrite_query_is_stashed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The setdefault at the top of the seam stashes the original-case
        # query for downstream original-case echo-back.
        params: Dict[str, Any] = {"query": "berlin"}
        result = self._run_with_params(monkeypatch, params)
        assert result.get("_pre_rewrite_query") == "list files"


# ---------------------------------------------------------------------------
# _handle_tell_me_about: the topic-resolution seam (decomposition_hint +
# possessive retry)
# ---------------------------------------------------------------------------


class TestTellMeAboutTopicResolutionCharacterization:
    """The Phase-1 topic resolver in ``_handle_tell_me_about`` prefers a
    parse-time ``decomposition_hint`` entity over the extracted topic, and
    (when no hint was attached) retries the possessive ``X's Y`` shape and
    surfaces the recovered hint. Both branches were only tested via their
    building blocks; pin the end-to-end handler behavior so the seam
    extraction can't silently drop or reorder them.
    """

    def _handler_empty_search(self) -> Tuple[SimpleToolsHandler, MagicMock]:
        mock = MagicMock()
        # Empty structured results -> the handler takes the early recovery
        # path after computing the topic, so we can assert the topic that
        # reached the search backend.
        mock.search_zim_file_data.return_value = {"results": []}
        return SimpleToolsHandler(mock), mock

    def _searched_topic(self, mock: MagicMock) -> str:
        # search_zim_file_data(zim_file_path, topic, search_limit, 0)
        assert mock.search_zim_file_data.call_args is not None
        return mock.search_zim_file_data.call_args.args[1]

    def test_decomposition_hint_entity_overrides_extracted_topic(self) -> None:
        handler, mock = self._handler_empty_search()
        params: Dict[str, Any] = {
            "topic": "population of berlin",
            "decomposition_hint": {"entity": "berlin", "attribute": "population"},
        }
        handler._handle_tell_me_about("population of berlin", "/x.zim", params, {})
        assert self._searched_topic(mock) == "berlin"

    def test_possessive_topic_rewrites_to_entity_and_stashes_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler, mock = self._handler_empty_search()
        # Degraded probe mode (no archive title-index in scope) so the
        # decomposition is deterministic — matches the documented
        # "_build_title_probe returns None when no archive is in scope".
        monkeypatch.setattr(handler, "_build_title_probe", lambda *_a, **_k: None)
        params: Dict[str, Any] = {"topic": "photosynthesis's reproduction"}
        handler._handle_tell_me_about(
            "tell me about photosynthesis's reproduction", "/x.zim", params, {}
        )
        # The possessive entity becomes the lookup topic ...
        assert self._searched_topic(mock) == "photosynthesis"
        # ... and the recovered hint is surfaced for downstream consumers.
        assert params.get("decomposition_hint") == {
            "entity": "photosynthesis",
            "attribute": "reproduction",
        }

    def test_non_possessive_topic_skips_retry(self) -> None:
        # A topic without "'s " must not be rewritten — it reaches the
        # backend unchanged (no decomposition_hint stashed).
        handler, mock = self._handler_empty_search()
        params: Dict[str, Any] = {"topic": "death of stalin"}
        handler._handle_tell_me_about(
            "tell me about death of stalin", "/x.zim", params, {}
        )
        assert self._searched_topic(mock) == "death of stalin"
        assert "decomposition_hint" not in params
