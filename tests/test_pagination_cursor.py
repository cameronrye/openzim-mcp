"""Tests for openzim_mcp.pagination.Cursor — encode/decode, tool binding, versioning."""

from __future__ import annotations

import base64
import json

import pytest

from openzim_mcp.pagination import Cursor, CursorMismatchError


class TestCursorRoundTrip:
    def test_encode_decode_roundtrip_minimal(self) -> None:
        token = Cursor.encode(
            tool="browse_namespace", state={"o": 50, "l": 50, "ns": "C"}
        )
        assert isinstance(token, str)
        decoded = Cursor.decode(token, expected_tool="browse_namespace")
        assert decoded["v"] == 2  # cursor v1->v2 clean break (v2 alpha line)
        assert decoded["t"] == "browse_namespace"
        assert decoded["s"] == {"o": 50, "l": 50, "ns": "C"}

    def test_encode_produces_urlsafe_base64(self) -> None:
        token = Cursor.encode(
            tool="search_zim_file", state={"o": 0, "l": 20, "q": "berlin"}
        )
        assert "+" not in token
        assert "/" not in token

    def test_encode_unicode_state(self) -> None:
        token = Cursor.encode(
            tool="search_zim_file", state={"o": 0, "l": 20, "q": "café"}
        )
        decoded = Cursor.decode(token, expected_tool="search_zim_file")
        assert decoded["s"]["q"] == "café"


class TestCursorVersioning:
    def test_default_version_is_two(self) -> None:
        token = Cursor.encode(
            tool="browse_namespace", state={"o": 0, "l": 50, "ns": "C"}
        )
        decoded = Cursor.decode(token, expected_tool="browse_namespace")
        assert decoded["v"] == 2

    def test_v1_cursor_rejected_after_clean_break(self) -> None:
        """Cursors from v2.0.0a2 (cursor v=1) are no longer honoured —
        they lacked archive identity and per-tool integrity fields,
        which led to several silent wrong-result bugs.
        """
        raw = json.dumps(
            {"v": 1, "t": "browse_namespace", "s": {"o": 0, "l": 50, "ns": "C"}}
        )
        token = base64.urlsafe_b64encode(raw.encode()).decode()
        with pytest.raises(ValueError, match="Unsupported cursor version"):
            Cursor.decode(token, expected_tool="browse_namespace")

    def test_unknown_future_version_rejected(self) -> None:
        raw = json.dumps(
            {"v": 99, "t": "browse_namespace", "s": {"o": 0, "l": 50, "ns": "C"}}
        )
        token = base64.urlsafe_b64encode(raw.encode()).decode()
        with pytest.raises(ValueError, match="Unsupported cursor version"):
            Cursor.decode(token, expected_tool="browse_namespace")


class TestCursorToolBinding:
    def test_decode_with_matching_tool_succeeds(self) -> None:
        token = Cursor.encode(tool="search_zim_file", state={"o": 0, "l": 20, "q": "x"})
        decoded = Cursor.decode(token, expected_tool="search_zim_file")
        assert decoded["t"] == "search_zim_file"

    def test_decode_with_mismatched_tool_raises(self) -> None:
        token = Cursor.encode(tool="search_zim_file", state={"o": 0, "l": 20, "q": "x"})
        with pytest.raises(CursorMismatchError) as exc_info:
            Cursor.decode(token, expected_tool="browse_namespace")
        assert "search_zim_file" in str(exc_info.value)
        assert "browse_namespace" in str(exc_info.value)

    def test_mismatch_error_is_value_error_subclass(self) -> None:
        assert issubclass(CursorMismatchError, ValueError)


class TestCursorMalformed:
    def test_decode_garbage_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            Cursor.decode("not-base64!@#$", expected_tool="browse_namespace")

    def test_decode_valid_base64_invalid_json_raises(self) -> None:
        token = base64.urlsafe_b64encode(b"this is not json").decode()
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            Cursor.decode(token, expected_tool="browse_namespace")

    def test_decode_missing_required_fields_raises(self) -> None:
        raw = json.dumps({"v": 2, "s": {"o": 0, "l": 20}})
        token = base64.urlsafe_b64encode(raw.encode()).decode()
        with pytest.raises(ValueError, match="missing"):
            Cursor.decode(token, expected_tool="browse_namespace")

    def test_decode_tolerates_missing_padding(self) -> None:
        token = Cursor.encode(
            tool="browse_namespace", state={"o": 0, "l": 50, "ns": "C"}
        )
        stripped = token.rstrip("=")
        decoded = Cursor.decode(stripped, expected_tool="browse_namespace")
        assert decoded["s"]["ns"] == "C"


class TestCursorWalkNamespaceState:
    def test_walk_namespace_state_roundtrip(self) -> None:
        token = Cursor.encode(tool="walk_namespace", state={"scan_at": 0, "l": 200})
        decoded = Cursor.decode(token, expected_tool="walk_namespace")
        assert decoded["s"]["scan_at"] == 0


class TestArchiveIdentity:
    def test_archive_identity_is_stable_for_same_path(self) -> None:
        from openzim_mcp.pagination import archive_identity

        assert archive_identity("/zim/wiki.zim") == archive_identity("/zim/wiki.zim")

    def test_archive_identity_differs_per_path(self) -> None:
        from openzim_mcp.pagination import archive_identity

        a = archive_identity("/zim/wiki.zim")
        b = archive_identity("/zim/dictionary.zim")
        assert a != b

    def test_verify_archive_identity_passes_on_match(self) -> None:
        from openzim_mcp.pagination import archive_identity

        ai = archive_identity("/zim/wiki.zim")
        # No exception raised
        Cursor.verify_archive_identity(
            {"ai": ai}, expected=ai, tool="extract_article_links"
        )

    def test_verify_archive_identity_rejects_mismatch(self) -> None:
        from openzim_mcp.pagination import archive_identity

        a = archive_identity("/zim/wiki.zim")
        b = archive_identity("/zim/dictionary.zim")
        with pytest.raises(CursorMismatchError):
            Cursor.verify_archive_identity(
                {"ai": a}, expected=b, tool="extract_article_links"
            )

    def test_verify_archive_identity_rejects_missing(self) -> None:
        with pytest.raises(CursorMismatchError, match="missing archive-identity"):
            Cursor.verify_archive_identity({}, expected="abc", tool="walk_namespace")
