"""Regression tests for scripts/download_test_data.py atomic download (M34)."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "download_test_data.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("download_test_data", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def mod():
    """Load the download_test_data script module by file path."""
    return _load_module()


def test_failed_download_leaves_no_truncated_file(mod, tmp_path, monkeypatch):
    """A mid-stream failure must not leave a file at dest_path (M34)."""
    dest = tmp_path / "withns" / "small.zim"

    def fake_urlretrieve(url, filename, reporthook=None):
        # Simulate a transfer that writes a few bytes then dies.
        Path(filename).write_bytes(b"partial")
        raise OSError("connection reset mid-stream")

    monkeypatch.setattr(mod, "urlretrieve", fake_urlretrieve)

    ok = mod.download_file("http://example/small.zim", dest, "small")

    assert ok is False
    assert not dest.exists(), "truncated file must not be promoted to dest_path"
    assert not (dest.parent / "small.zim.part").exists(), ".part must be cleaned up"


def test_successful_download_atomically_replaces(mod, tmp_path, monkeypatch):
    """A successful download lands the full bytes at dest_path (M34)."""
    dest = tmp_path / "withns" / "small.zim"

    def fake_urlretrieve(url, filename, reporthook=None):
        Path(filename).write_bytes(b"complete-zim-bytes")

    monkeypatch.setattr(mod, "urlretrieve", fake_urlretrieve)

    ok = mod.download_file("http://example/small.zim", dest, "small")

    assert ok is True
    assert dest.read_bytes() == b"complete-zim-bytes"
    assert not (dest.parent / "small.zim.part").exists()
