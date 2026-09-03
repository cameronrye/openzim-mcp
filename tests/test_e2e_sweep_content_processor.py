"""Real-world sweep (v3.2.2): snippet anchoring and the image placeholder.

Both defects surfaced driving the installed server against the live corpus:

* ``what causes migraines`` anchored its featured passage on the *lead* of
  an off-topic article because the interrogative ``what`` is >= 3 chars and
  therefore counted as an anchorable query term. The article's actual
  migraine paragraph sat 11k chars further down.
* A non-binary fetch of an image dead-ends on a placeholder that never
  names the route which does return the bytes — ``binary=True`` on the
  advanced surface, ``get binary content of <path>`` in simple mode, where
  ``zim_get`` is not registered at all.
"""

import pytest

from openzim_mcp.content_processor import ContentProcessor


def _processor(tool_mode: str = "advanced") -> ContentProcessor:
    return ContentProcessor(snippet_length=3000, tool_mode=tool_mode)


class TestSnippetAnchoringIgnoresStopWords:
    """A question word must not anchor the snippet on an irrelevant lead."""

    CONTENT = (
        "Nietzsche spoke of the death of God and of becoming what one is, "
        "a phrase that has occupied commentators ever since.\n\n"
        "His early philology gave way to the aphoristic style.\n\n"
        "Nietzsche suffered debilitating migraines throughout his adult "
        "life, and the attacks shaped his working habits."
    )

    def test_question_word_does_not_anchor_the_lead(self):
        snippet = _processor().create_snippet(
            self.CONTENT, query="what causes migraines"
        )
        assert "migraines" in snippet
        assert not snippet.startswith("Nietzsche spoke of the death of God")

    def test_content_term_still_anchors_when_present(self):
        snippet = _processor().create_snippet(self.CONTENT, query="migraines")
        assert "migraines" in snippet

    def test_all_stop_word_query_falls_back_to_full_term_set(self):
        # Nothing anchorable remains after filtering, so the old behavior
        # (match on whatever the query gave us) must survive rather than
        # silently degrading to the lead for every function-word query.
        snippet = _processor().create_snippet(self.CONTENT, query="what is it")
        assert snippet


class TestImagePlaceholderNamesBinaryArgument:
    def test_placeholder_points_at_binary_true(self):
        result = _processor("advanced").process_mime_content(
            b"fake image data", "image/png"
        )
        assert "Image content" in result
        assert "binary=True" in result

    def test_simple_mode_placeholder_names_a_route_that_exists(self):
        """Simple mode registers ``zim_query`` alone.

        The advanced placeholder named ``zim_get(entry_path=..., binary=True)``
        in both modes, so the one client that cannot call ``zim_get`` was the
        one being told to. The replacement is the ``binary`` intent, which
        ``zim_query`` does resolve.
        """
        result = _processor("simple").process_mime_content(
            b"fake image data", "image/png"
        )
        assert "Image content" in result
        assert "get binary content of" in result
        assert "zim_get" not in result

    @pytest.mark.parametrize("tool_mode", ["simple", "advanced"])
    def test_placeholder_always_offers_a_next_step(self, tool_mode):
        """Neither mode may "fix" the hint by dropping the route."""
        result = _processor(tool_mode).process_mime_content(
            b"fake image data", "image/png"
        )
        assert "Cannot display directly" in result
        assert result.rstrip().endswith(")")
