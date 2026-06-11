"""Regression tests for scripts/download_test_data.py atomic download (M34)."""

import importlib.util
import io
import sys
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


def test_import_does_not_hijack_stdio_on_windows(monkeypatch):
    """Importing the script must never replace sys.stdout/sys.stderr.

    Regression for a Windows-only failure: a module-level
    ``sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)`` ran at import time
    on win32. When a test imports this script under pytest's output capture, that
    wrapper takes over the capture file and closes it on garbage collection,
    erroring every subsequent test and crashing capture teardown
    (``ValueError: I/O operation on closed file``). Simulate win32 with harmless
    fake streams so the invariant is checked on any platform without touching the
    real capture buffers.
    """
    fake_out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    fake_err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stderr", fake_err)

    _load_module()

    assert sys.stdout is fake_out, "import must not replace sys.stdout"
    assert sys.stderr is fake_err, "import must not replace sys.stderr"


def test_ensure_utf8_stdio_reconfigures_in_place(monkeypatch):
    """On win32 the helper reconfigures existing streams (no object replacement)."""
    mod = _load_module()
    calls = []

    class _FakeStream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    fake_out, fake_err = _FakeStream(), _FakeStream()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stderr", fake_err)

    mod._ensure_utf8_stdio()

    assert sys.stdout is fake_out and sys.stderr is fake_err
    assert calls == [{"encoding": "utf-8"}, {"encoding": "utf-8"}]


def test_ensure_utf8_stdio_is_noop_off_windows(monkeypatch):
    """Off win32 the helper leaves the streams untouched."""
    mod = _load_module()
    monkeypatch.setattr(sys, "platform", "linux")
    before_out, before_err = sys.stdout, sys.stderr

    mod._ensure_utf8_stdio()

    assert sys.stdout is before_out and sys.stderr is before_err


def test_failed_download_leaves_no_truncated_file(mod, tmp_path, monkeypatch):
    """A mid-stream failure must not leave a file at dest_path (M34)."""
    dest = tmp_path / "withns" / "small.zim"

    def fake_urlretrieve(url, filename, reporthook=None):
        # Simulate a transfer that writes a few bytes then dies.
        Path(filename).write_bytes(b"partial")
        raise OSError("connection reset mid-stream")

    monkeypatch.setattr(mod, "urlretrieve", fake_urlretrieve)

    ok = mod.download_file("https://example/small.zim", dest, "small")

    assert ok is False
    assert not dest.exists(), "truncated file must not be promoted to dest_path"
    assert not (dest.parent / "small.zim.part").exists(), ".part must be cleaned up"


def test_successful_download_atomically_replaces(mod, tmp_path, monkeypatch):
    """A successful download lands the full bytes at dest_path (M34)."""
    dest = tmp_path / "withns" / "small.zim"

    def fake_urlretrieve(url, filename, reporthook=None):
        Path(filename).write_bytes(b"complete-zim-bytes")

    monkeypatch.setattr(mod, "urlretrieve", fake_urlretrieve)

    ok = mod.download_file("https://example/small.zim", dest, "small")

    assert ok is True
    assert dest.read_bytes() == b"complete-zim-bytes"
    assert not (dest.parent / "small.zim.part").exists()
