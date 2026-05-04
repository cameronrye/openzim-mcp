"""Tests for timeout_utils module."""

import time

import pytest

from openzim_mcp.exceptions import (
    ArchiveOpenTimeoutError,
    OpenZimMcpTimeoutError,
    RegexTimeoutError,
)
from openzim_mcp.timeout_utils import run_with_timeout


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


class TestSafeRegexSearch:
    """Tests for thread-based regex timeout via safe_regex_search."""

    def test_runs_off_main_thread_without_signal_error(self) -> None:
        """safe_regex_search must work from worker threads.

        The previous SIGALRM-based implementation raised
        ``ValueError: signal only works in main thread`` when called from
        anywhere but the main thread. The thread-based replacement must
        complete cleanly.
        """
        import threading

        from openzim_mcp.intent_parser import safe_regex_search

        outcome: list[object] = []

        def worker() -> None:
            try:
                match = safe_regex_search(r"hello", "hello world")
                outcome.append(("ok", match.group() if match else None))
            except (KeyboardInterrupt, SystemExit, Exception) as e:
                outcome.append(("err", e))

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5.0)

        assert outcome == [("ok", "hello")]


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
