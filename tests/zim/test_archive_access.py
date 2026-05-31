"""Tests for _ArchiveAccessMixin._validate_zim_path and _json."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openzim_mcp.zim._ops_base import _ArchiveAccessMixin, _json


class TestJsonHelper:
    """Tests for the module-level _json serialization helper."""

    def test_matches_reference_dumps(self) -> None:
        """_json must produce bit-identical output to json.dumps with indent=2, ensure_ascii=False."""
        payload = {"a": "é", "n": 1}
        expected = json.dumps(payload, indent=2, ensure_ascii=False)
        assert _json(payload) == expected

    def test_non_ascii_preserved_literally(self) -> None:
        """The non-ASCII character é must appear literally, not as \\uXXXX."""
        result = _json({"a": "é"})
        assert "é" in result
        assert "\\u" not in result

    def test_indent_is_two_spaces(self) -> None:
        """Output must use 2-space indentation."""
        result = _json({"k": 1})
        assert '  "k": 1' in result


class _Stub(_ArchiveAccessMixin):
    """Minimal host that provides a fake path_validator."""

    def __init__(self, path_validator: MagicMock) -> None:
        self.path_validator = path_validator


class TestArchiveAccessMixin:
    """Tests for _ArchiveAccessMixin._validate_zim_path."""

    @pytest.fixture
    def fake_validator(self) -> MagicMock:
        validator = MagicMock()
        intermediate = Path("/allowed/archive.zim")
        final = Path("/allowed/archive.zim")
        validator.validate_path.return_value = intermediate
        validator.validate_zim_file.return_value = final
        return validator

    @pytest.fixture
    def stub(self, fake_validator: MagicMock) -> _Stub:
        return _Stub(fake_validator)

    def test_calls_validate_path_then_validate_zim_file(
        self, stub: _Stub, fake_validator: MagicMock
    ) -> None:
        """validate_path is called with the raw arg; its result is forwarded to validate_zim_file."""
        arg = "/some/path/archive.zim"
        intermediate = fake_validator.validate_path.return_value

        result = stub._validate_zim_path(arg)

        fake_validator.validate_path.assert_called_once_with(arg)
        fake_validator.validate_zim_file.assert_called_once_with(intermediate)
        assert result == fake_validator.validate_zim_file.return_value

    def test_returns_final_path(self, stub: _Stub, fake_validator: MagicMock) -> None:
        """The return value is whatever validate_zim_file returns."""
        expected = Path("/resolved/archive.zim")
        fake_validator.validate_zim_file.return_value = expected

        result = stub._validate_zim_path("/any/path.zim")

        assert result is expected

    def test_validate_path_exception_propagates_unwrapped(
        self, stub: _Stub, fake_validator: MagicMock
    ) -> None:
        """An exception from validate_path is not caught or wrapped."""
        fake_validator.validate_path.side_effect = ValueError("bad path")

        with pytest.raises(ValueError, match="bad path"):
            stub._validate_zim_path("/bad/path.zim")

        # validate_zim_file must not be called if the first step fails.
        fake_validator.validate_zim_file.assert_not_called()

    def test_validate_zim_file_exception_propagates_unwrapped(
        self, stub: _Stub, fake_validator: MagicMock
    ) -> None:
        """An exception from validate_zim_file is not caught or wrapped."""
        fake_validator.validate_zim_file.side_effect = RuntimeError("not a zim")

        with pytest.raises(RuntimeError, match="not a zim"):
            stub._validate_zim_path("/ok/path.zim")
