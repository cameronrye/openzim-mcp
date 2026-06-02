"""Post-v2.1.3 live-beta-sweep regression suite.

The v2.1.3 live beta sweep (remote dual-archive library: Wikipedia
2026-02 + superuser.com 2026-02) surfaced a HIGH-severity synthesize
defect:

  D1 — synthesize promotes an off-topic single-token exact-title match
  to the PRIMARY citation. ``synthesize("ssh connection refused")``
  returned the Wikipedia article ``Refused`` (a Swedish hardcore punk
  band) at rank 1 / score 1.0, demoting the two genuinely relevant
  superuser.com SSH troubleshooting Q&As to ranks 2-3. The answer led
  with band metadata cited as the authoritative source.

Root cause: ``synthesize._promote_title_match``'s tail-iteration loop
(the ``iter_query_tails`` probe) promoted the single-token tail
``"refused"`` -> exact-title article with NO tangential/tail-hijack
guard, then tagged it ``promoted`` so ``_drop_cross_archive_leakage``
exempted it from the cross-archive relevance floor. The sibling
``simple_tools`` / ``topic_preprocessing`` tail loop already guards this
case via the b9/b10 tail-hijack + multi-entity discriminator
(``_accept_with_multi_entity_check``); the synthesize tail loop was the
narrow-scope sibling that never got the treatment (cf. post-b4 D3,
which flagged the same "synthesize never got the pass-0 treatment"
shape).

The fix mirrors that guard in the synthesize tail loop via the shared
``accept_tail_promotion`` gate, so the two promotion paths can no longer
drift. Critically, the guard must NOT over-reject legitimate
single-entity-in-filler-prose tails (``population of detroit`` ->
``Detroit``) or multi-token entity tails (``big rapids michigan`` ->
``Big_Rapids,_Michigan``) — those regression cases are pinned below.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch


class _Archive:
    """Minimal stand-in for a libzim ``Archive`` handle."""

    def __init__(self, label: str) -> None:
        self.label = label


class TestD1SynthesizeTailHijackGuard:
    """D1: the synthesize tail loop must not promote an off-topic
    single-token tail-hijack when the multi-token query carries 2+ other
    strong entities."""

    def test_ssh_connection_refused_does_not_promote_band(self) -> None:
        from openzim_mcp.synthesize import _promote_title_match

        wiki = _Archive("wiki")
        su = _Archive("su")

        def fake_title_match_hit(archive: Any, title: str) -> Optional[Dict[str, Any]]:
            # Only the bare 1-token tail "refused" resolves as an exact
            # title — to the off-topic Swedish punk band, on Wikipedia.
            if archive is wiki and title == "refused":
                return {
                    "path": "Refused",
                    "snippet": "Refused are a Swedish hardcore punk band ...",
                    "score": 1.0,
                }
            return None

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            t = topic.lower()
            # Pass-0 full-query probe: no canonical for the full query.
            if t == "ssh connection refused":
                return None
            # Per-token probes consumed by the multi-entity discriminator.
            # The probed token must appear in the resolved path/pre-path
            # tokens to be counted as a strong entity.
            if t == "ssh":
                return {
                    "path": "Secure_Shell",
                    "title": "Secure Shell",
                    "match_type": "redirect",
                    "pre_redirect_path": "SSH",
                }
            if t == "connection":
                return {
                    "path": "Connection",
                    "title": "Connection",
                    "match_type": "direct",
                }
            return None

        handler = MagicMock()
        handler.title_match_hit = fake_title_match_hit

        # A weak BM25 top hit (no query-token overlap) so the
        # is_strong_title_match short-circuit does not fire and the
        # promotion path actually runs.
        top_hits = [
            (
                "su",
                {
                    "path": "questions/977104/ssh-connect-issue",
                    "title": "SSH connect issue",
                    "snippet": "connect to host localhost port 22 ...",
                    "score": 0.3,
                },
            )
        ]

        with patch(
            "openzim_mcp.synthesize.find_title_match",
            side_effect=fake_find_title_match,
        ):
            result = _promote_title_match(
                top_hits,
                query="ssh connection refused",
                archives=[(wiki, "/wiki.zim"), (su, "/su.zim")],
                archives_searched=["wiki", "su"],
                search_handler=handler,
            )

        promoted_paths = [hit.get("path") for _name, hit in result]
        assert "Refused" not in promoted_paths, (
            "off-topic single-token tail-hijack 'Refused' must not be "
            f"promoted for a multi-entity query; got {promoted_paths!r}"
        )
        assert result[0][1]["path"] == "questions/977104/ssh-connect-issue", (
            "the relevant BM25 hit must stay at rank 0; got "
            f"{result[0][1]['path']!r}"
        )


class TestD1GuardDoesNotOverReject:
    """The tail-hijack guard must preserve LEGITIMATE tail promotions:
    single-entity-in-filler-prose and multi-token entity tails."""

    def _run(
        self,
        query: str,
        title_hits: Dict[str, Dict[str, Any]],
        token_probes: Dict[str, Dict[str, Any]],
    ) -> list:
        from openzim_mcp.synthesize import _promote_title_match

        wiki = _Archive("wiki")

        def fake_title_match_hit(archive: Any, title: str) -> Optional[Dict[str, Any]]:
            return title_hits.get(title)

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            # Pass-0 full-query probe always misses here so the tail loop runs.
            if topic.lower() == query.lower():
                return None
            return token_probes.get(topic.lower())

        handler = MagicMock()
        handler.title_match_hit = fake_title_match_hit
        weak_top = [("wiki", {"path": "Some_BM25_Noise", "title": "x", "score": 0.1})]
        with patch(
            "openzim_mcp.synthesize.find_title_match",
            side_effect=fake_find_title_match,
        ):
            return _promote_title_match(
                weak_top,
                query=query,
                archives=[(wiki, "/wiki.zim")],
                archives_searched=["wiki"],
                search_handler=handler,
            )

    def test_population_of_detroit_still_promotes_detroit(self) -> None:
        # Filler prose around ONE entity: only "population" is a
        # non-stop-word non-tail token, so the b10 single-entity escape
        # re-accepts the tail-hijack-shaped "Detroit".
        result = self._run(
            "what is the population of detroit",
            title_hits={"detroit": {"path": "Detroit", "snippet": "", "score": 1.0}},
            token_probes={
                "population": {"path": "Population", "match_type": "direct"},
            },
        )
        assert result[0][1]["path"] == "Detroit", (
            f"legitimate filler-prose tail promotion was wrongly rejected; "
            f"got {[h.get('path') for _n, h in result]!r}"
        )

    def test_big_rapids_michigan_multi_token_tail_still_promotes(self) -> None:
        # Multi-token entity tail whose tokens are a subset of the topic:
        # not a tail-hijack, not Z4-tangential -> still promoted.
        result = self._run(
            "famous people from big rapids michigan",
            title_hits={
                "big rapids michigan": {
                    "path": "Big_Rapids,_Michigan",
                    "snippet": "",
                    "score": 1.0,
                }
            },
            token_probes={},
        )
        assert result[0][1]["path"] == "Big_Rapids,_Michigan", (
            f"legitimate multi-token entity tail promotion was wrongly "
            f"rejected; got {[h.get('path') for _n, h in result]!r}"
        )
