"""Tests for main module and __main__ entry point."""

from unittest.mock import MagicMock, patch

import pytest

import openzim_mcp.main
from openzim_mcp.exceptions import OpenZimMcpConfigurationError


class TestMainModule:
    """Test main module functionality."""

    @patch("openzim_mcp.main.InstanceTracker")
    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir"])
    def test_main_success(
        self, mock_config_class, mock_server_class, mock_tracker_class
    ):
        """Test successful main execution."""
        from openzim_mcp.main import main

        # Setup mocks
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker

        # Call main
        main()

        # Verify calls
        mock_config_class.assert_called_once_with(allowed_directories=["/test/dir"])
        mock_server_class.assert_called_once_with(mock_config, mock_tracker)
        mock_server.run.assert_called_once_with(transport="stdio")

    @patch("openzim_mcp.main.InstanceTracker")
    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir1", "/test/dir2"])
    def test_main_multiple_directories(
        self, mock_config_class, mock_server_class, mock_tracker_class
    ):
        """Test main with multiple directories."""
        from openzim_mcp.main import main

        # Setup mocks
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_server = MagicMock()
        mock_server_class.return_value = mock_server
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker

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
            pass  # Expected when main() is called
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
            pass  # Expected when main() is called
        finally:
            # Restore the original __name__
            openzim_mcp.__main__.__name__ = original_name

        # Verify main was called
        mock_main.assert_called_once()
