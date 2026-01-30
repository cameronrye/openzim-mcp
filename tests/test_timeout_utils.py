"""Tests for timeout_utils module."""

import sys
import time

import pytest

from openzim_mcp.exceptions import (
    ArchiveOpenTimeoutError,
    OpenZimMcpTimeoutError,
    RegexTimeoutError,
)
from openzim_mcp.timeout_utils import regex_timeout, run_with_timeout


class TestRunWithTimeout:
    """Tests for run_with_timeout function."""

    def test_successful_execution(self) -> None:
        """Test that function completes successfully within timeout."""

        def quick_func() -> str:
            return "success"

        result = run_with_timeout(quick_func, 5.0, "Should not timeout")
        assert result == "success"

    def test_timeout_raises_exception(self) -> None:
        """Test that timeout raises the specified exception."""

        def slow_func() -> str:
            time.sleep(10)
            return "never reached"

        with pytest.raises(OpenZimMcpTimeoutError) as exc_info:
            run_with_timeout(slow_func, 0.1, "Operation timed out")

        assert "Operation timed out" in str(exc_info.value)

    def test_timeout_with_custom_exception(self) -> None:
        """Test that custom exception class is used for timeout."""

        def slow_func() -> str:
            time.sleep(10)
            return "never reached"

        with pytest.raises(ArchiveOpenTimeoutError) as exc_info:
            run_with_timeout(
                slow_func, 0.1, "Archive operation timed out", ArchiveOpenTimeoutError
            )

        assert "Archive operation timed out" in str(exc_info.value)

    def test_exception_propagation(self) -> None:
        """Test that exceptions from the function are propagated."""

        def failing_func() -> str:
            raise ValueError("Test error")

        with pytest.raises(ValueError) as exc_info:
            run_with_timeout(failing_func, 5.0, "Should not timeout")

        assert "Test error" in str(exc_info.value)

    def test_returns_none_value(self) -> None:
        """Test that None return value is handled correctly."""

        def none_func() -> None:
            return None

        # This should raise timeout exception since result list is empty
        # when the function returns None (which doesn't append to result list)
        result = run_with_timeout(none_func, 5.0, "Should not timeout")
        assert result is None

    def test_returns_falsy_values(self) -> None:
        """Test that falsy return values are handled correctly."""

        def zero_func() -> int:
            return 0

        def empty_string_func() -> str:
            return ""

        def empty_list_func() -> list:
            return []

        assert run_with_timeout(zero_func, 5.0, "msg") == 0
        assert run_with_timeout(empty_string_func, 5.0, "msg") == ""
        assert run_with_timeout(empty_list_func, 5.0, "msg") == []


class TestRegexTimeout:
    """Tests for regex_timeout context manager."""

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Signal-based timeout not available on Windows"
    )
    def test_successful_operation_within_timeout(self) -> None:
        """Test that operations complete successfully within timeout."""
        with regex_timeout(5.0):
            result = 1 + 1
        assert result == 2

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Signal-based timeout not available on Windows"
    )
    def test_timeout_raises_regex_timeout_error(self) -> None:
        """Test that timeout raises RegexTimeoutError on Unix."""
        with pytest.raises(RegexTimeoutError) as exc_info, regex_timeout(0.1):
            time.sleep(10)

        assert "timed out" in str(exc_info.value).lower()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_yields_without_timeout(self) -> None:
        """Test that Windows implementation yields without enforcing timeout."""
        # On Windows, the context manager just yields without timeout enforcement
        with regex_timeout(0.001):
            # This should complete even though timeout is very short
            result = "completed"
        assert result == "completed"

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Signal-based timeout not available on Windows"
    )
    def test_signal_handler_restored(self) -> None:
        """Test that the original signal handler is restored after context."""
        import signal

        original_handler = signal.getsignal(signal.SIGALRM)

        with regex_timeout(5.0):
            pass

        # Handler should be restored
        assert signal.getsignal(signal.SIGALRM) == original_handler

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Signal-based timeout not available on Windows"
    )
    def test_signal_handler_restored_after_exception(self) -> None:
        """Test that signal handler is restored even after exception."""
        import signal

        original_handler = signal.getsignal(signal.SIGALRM)

        def raise_in_timeout_context():
            with regex_timeout(5.0):
                raise ValueError("Test exception")

        with pytest.raises(ValueError):
            raise_in_timeout_context()

        # Handler should be restored even after exception
        assert signal.getsignal(signal.SIGALRM) == original_handler


class TestExceptionHierarchy:
    """Tests for timeout exception class hierarchy."""

    def test_archive_timeout_is_subclass(self) -> None:
        """Test that ArchiveOpenTimeoutError is a subclass of OpenZimMcpTimeoutError."""
        assert issubclass(ArchiveOpenTimeoutError, OpenZimMcpTimeoutError)

    def test_regex_timeout_is_subclass(self) -> None:
        """Test that RegexTimeoutError is a subclass of OpenZimMcpTimeoutError."""
        assert issubclass(RegexTimeoutError, OpenZimMcpTimeoutError)

    def test_can_catch_archive_timeout_with_base_class(self) -> None:
        """Test that ArchiveOpenTimeoutError can be caught with base class."""
        with pytest.raises(OpenZimMcpTimeoutError):
            raise ArchiveOpenTimeoutError("Test")

    def test_can_catch_regex_timeout_with_base_class(self) -> None:
        """Test that RegexTimeoutError can be caught with base class."""
        with pytest.raises(OpenZimMcpTimeoutError):
            raise RegexTimeoutError("Test")
