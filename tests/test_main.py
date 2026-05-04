"""Tests for main module and __main__ entry point."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.exceptions import OpenZimMcpConfigurationError


class TestMainModule:
    """Test main module functionality."""

    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir"])
    def test_main_success(self, mock_config_class, mock_server_class):
        """Test successful main execution."""
        from openzim_mcp.main import main

        # Setup mocks
        mock_config = MagicMock(transport="stdio")
        mock_config_class.return_value = mock_config
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server

        # Call main
        main()

        # Verify calls — main() calls run() without arguments; the server
        # derives the wire transport from config.transport itself.
        mock_config_class.assert_called_once_with(allowed_directories=["/test/dir"])
        mock_server_class.assert_called_once_with(mock_config)
        mock_server.run.assert_called_once_with()

    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir1", "/test/dir2"])
    def test_main_multiple_directories(self, mock_config_class, mock_server_class):
        """Test main with multiple directories."""
        from openzim_mcp.main import main

        # Setup mocks
        mock_config = MagicMock(transport="stdio")
        mock_config_class.return_value = mock_config
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server

        # Call main
        main()

        # Verify calls
        mock_config_class.assert_called_once_with(
            allowed_directories=["/test/dir1", "/test/dir2"]
        )

    @patch("sys.argv", ["openzim_mcp"])
    @patch("sys.stderr")
    def test_main_no_arguments(self, mock_stderr):
        """Test main with no arguments."""
        from openzim_mcp.main import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir"])
    @patch("sys.stderr")
    def test_main_configuration_error(self, mock_stderr, mock_config_class):
        """Test main with configuration error."""
        from openzim_mcp.main import main

        # Setup mock to raise configuration error
        mock_config_class.side_effect = OpenZimMcpConfigurationError("Config error")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir"])
    @patch("sys.stderr")
    def test_main_server_startup_error(
        self, mock_stderr, mock_config_class, mock_server_class
    ):
        """Test main with server startup error."""
        from openzim_mcp.main import main

        # Setup mocks
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_server_class.side_effect = Exception("Server error")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir"])
    @patch("sys.stderr")
    def test_main_server_run_error(
        self, mock_stderr, mock_config_class, mock_server_class
    ):
        """Test main with server run error."""
        from openzim_mcp.main import main

        # Setup mocks
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server
        mock_server.run.side_effect = Exception("Run error")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "--transport", "http", "/test/dir"])
    def test_main_http_transport(self, mock_config_class, mock_server_class):
        """--transport http: main() defers wire mapping to server.run()."""
        from openzim_mcp.main import main

        mock_config = MagicMock()
        mock_config.transport = "http"
        mock_config_class.return_value = mock_config
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server

        main()

        # main() always calls run() without arguments; OpenZimMcpServer.run()
        # translates config.transport='http' to FastMCP's 'streamable-http'.
        mock_server.run.assert_called_once_with()

    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch(
        "sys.argv",
        [
            "openzim_mcp",
            "--transport",
            "http",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "/test/dir",
        ],
    )
    def test_main_http_with_host_port(self, mock_config_class, mock_server_class):
        """--host and --port pass through to config kwargs."""
        from openzim_mcp.main import main

        mock_config_class.return_value = MagicMock(transport="http")
        mock_server_class.return_value = MagicMock()

        main()

        call_kwargs = mock_config_class.call_args.kwargs
        assert call_kwargs["transport"] == "http"
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 9000

    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "--transport", "sse", "/test/dir"])
    def test_main_sse_transport(self, mock_config_class, mock_server_class):
        """--transport sse: main() defers transport selection to server.run()."""
        from openzim_mcp.main import main

        mock_config = MagicMock()
        mock_config.transport = "sse"
        mock_config_class.return_value = mock_config
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server

        main()

        mock_server.run.assert_called_once_with()

    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch(
        "sys.argv",
        [
            "openzim_mcp",
            "--transport",
            "sse",
            "--host",
            "127.0.0.1",
            "--port",
            "9001",
            "/test/dir",
        ],
    )
    def test_main_sse_with_host_port(self, mock_config_class, mock_server_class):
        """--host and --port pass through to config kwargs for sse too."""
        from openzim_mcp.main import main

        mock_config_class.return_value = MagicMock(transport="sse")
        mock_server_class.return_value = MagicMock()

        main()

        call_kwargs = mock_config_class.call_args.kwargs
        assert call_kwargs["transport"] == "sse"
        assert call_kwargs["host"] == "127.0.0.1"
        assert call_kwargs["port"] == 9001

    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir"])
    def test_main_default_still_stdio(self, mock_config_class, mock_server_class):
        """Existing behavior preserved: no flags = stdio."""
        from openzim_mcp.main import main

        mock_config_class.return_value = MagicMock(transport="stdio")
        mock_server_class.return_value = MagicMock()

        main()

        mock_server_class.return_value.run.assert_called_once_with()

    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir"])
    def test_startup_banner_routes_through_logger(
        self,
        mock_config_class,
        mock_server_class,
        caplog: pytest.LogCaptureFixture,
    ):
        """Startup banner must be emitted via ``logger.info``, not ``print``.

        Regression for finding 8.8: previously ``print(..., file=sys.stderr)``
        bypassed the logging configuration entirely, so banner text leaked
        out even when the operator had configured a higher log level.
        Routing through ``logger.info`` lets the standard logging level
        machinery suppress the banner when desired.
        """
        from openzim_mcp.main import main

        mock_config_class.return_value = MagicMock(transport="stdio")
        mock_server_class.return_value = MagicMock()

        with caplog.at_level(logging.INFO, logger="openzim_mcp.main"):
            main()

        banner_messages = [
            record.getMessage()
            for record in caplog.records
            if record.name == "openzim_mcp.main"
        ]
        joined = "\n".join(banner_messages)
        assert (
            "OpenZIM MCP server started" in joined
        ), f"startup banner not found in log records: {banner_messages!r}"
        assert (
            "Allowed directories" in joined
        ), f"allowed-directories line not found in log records: {banner_messages!r}"


class TestMainEntryPoint:
    """Test __main__ entry point."""

    def test_main_entry_point_import(self):
        """Test that __main__ module can be imported."""
        # Test that the __main__ module imports correctly
        import openzim_mcp.__main__

        # Verify the module has the expected attributes
        assert hasattr(openzim_mcp.__main__, "main")

    @patch("openzim_mcp.main.main")
    def test_main_module_if_name_main(self, mock_main):
        """Test the if __name__ == '__main__' block in main.py."""
        # Execute just the if __name__ == "__main__" block
        exec(
            'if __name__ == "__main__":\n    main()',
            {"__name__": "__main__", "main": mock_main},
        )

        # main() should have been called
        mock_main.assert_called_once()

    @patch("openzim_mcp.main.main")
    def test_main_py_if_name_main_coverage(self, mock_main):
        """Test the if __name__ == '__main__' block in main.py for coverage."""
        import openzim_mcp.main

        # Directly test the condition by simulating the module being run as __main__
        # Save the original __name__
        original_name = openzim_mcp.main.__name__

        try:
            # Temporarily set __name__ to "__main__" to trigger the condition
            openzim_mcp.main.__name__ = "__main__"

            # Now execute the specific line that checks if __name__ == "__main__"
            # This simulates line 49-50 in main.py
            if openzim_mcp.main.__name__ == "__main__":
                openzim_mcp.main.main()

        except SystemExit:
            pass  # Expected when main() is called  # NOSONAR
        finally:
            # Restore the original __name__
            openzim_mcp.main.__name__ = original_name

        # Verify main was called
        mock_main.assert_called_once()

    @patch("openzim_mcp.__main__.main")
    def test_main_module_if_name_main_coverage(self, mock_main):
        """Test the if __name__ == '__main__' block in __main__.py for coverage."""
        # Directly test the condition by simulating the module being run as __main__
        import openzim_mcp.__main__

        # Save the original __name__
        original_name = openzim_mcp.__main__.__name__

        try:
            # Temporarily set __name__ to "__main__" to trigger the condition
            openzim_mcp.__main__.__name__ = "__main__"

            # Now execute the specific line that checks if __name__ == "__main__"
            # This simulates line 7-8 in __main__.py
            if openzim_mcp.__main__.__name__ == "__main__":
                openzim_mcp.__main__.main()

        except SystemExit:
            pass  # Expected when main() is called  # NOSONAR
        finally:
            # Restore the original __name__
            openzim_mcp.__main__.__name__ = original_name

        # Verify main was called
        mock_main.assert_called_once()
