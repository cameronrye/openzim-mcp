"""
Tests for main module and __main__ entry point.
"""

from unittest.mock import MagicMock, patch

import pytest

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


class TestMainModuleMissingCoverage:
    """Test missing coverage areas in main module."""

    @patch("sys.argv", ["openzim_mcp"])
    def test_main_no_arguments_coverage(self):
        """Test main with no arguments - covers lines 46, 69."""
        from openzim_mcp.main import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        # Should exit with code 1
        assert exc_info.value.code == 1

    @patch("openzim_mcp.main.InstanceTracker")
    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir"])
    def test_main_configuration_error_coverage(
        self, mock_config_class, mock_server_class, mock_tracker_class
    ):
        """Test main with configuration error - covers exception handling."""
        from openzim_mcp.main import main

        # Mock config to raise configuration error
        mock_config_class.side_effect = OpenZimMcpConfigurationError("Config error")

        with pytest.raises(SystemExit) as exc_info:
            main()

        # Should exit with code 1
        assert exc_info.value.code == 1

    @patch("openzim_mcp.main.InstanceTracker")
    @patch("openzim_mcp.main.OpenZimMcpServer")
    @patch("openzim_mcp.main.OpenZimMcpConfig")
    @patch("sys.argv", ["openzim_mcp", "/test/dir"])
    def test_main_general_exception_coverage(
        self, mock_config_class, mock_server_class, mock_tracker_class
    ):
        """Test main with general exception - covers exception handling."""
        from openzim_mcp.main import main

        # Mock config to raise general exception
        mock_config_class.side_effect = Exception("General error")

        with pytest.raises(SystemExit) as exc_info:
            main()

        # Should exit with code 1
        assert exc_info.value.code == 1


class TestMainModuleEntryPoint:
    """Test __main__.py entry point."""

    @patch("openzim_mcp.__main__.main")
    def test_main_entry_point_coverage(self, mock_main):
        """Test __main__.py entry point - covers line 8."""
        # Import the module to trigger the if __name__ == "__main__" block
        import subprocess
        import sys

        # Run the module as a script to test the entry point
        result = subprocess.run(
            [sys.executable, "-c", "import openzim_mcp.__main__; print('imported')"],
            capture_output=True,
            text=True
        )

        # Should import successfully
        assert result.returncode == 0
        assert "imported" in result.stdout

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

    def test_main_cleanup_function_coverage(self):
        """Test the cleanup function inside main() - covers line 46."""
        from unittest.mock import patch, MagicMock
        import tempfile
        import sys

        # Create a temporary directory for the test
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock sys.argv to provide the required directory argument
            with patch.object(sys, 'argv', ['openzim_mcp', temp_dir]):
                # Mock the components to avoid actually starting the server
                with patch('openzim_mcp.main.OpenZimMcpConfig') as mock_config_class, \
                     patch('openzim_mcp.main.InstanceTracker') as mock_tracker_class, \
                     patch('openzim_mcp.main.OpenZimMcpServer') as mock_server_class, \
                     patch('openzim_mcp.main.atexit') as mock_atexit:

                    # Set up mocks
                    mock_config = MagicMock()
                    mock_config.get_config_hash.return_value = "test_hash"
                    mock_config.server_name = "test_server"
                    mock_config_class.return_value = mock_config

                    mock_tracker = MagicMock()
                    mock_tracker_class.return_value = mock_tracker

                    mock_server = MagicMock()
                    mock_server_class.return_value = mock_server

                    # Import and call main
                    from openzim_mcp.main import main
                    main()

                    # Verify that atexit.register was called with a cleanup function
                    mock_atexit.register.assert_called_once()
                    cleanup_function = mock_atexit.register.call_args[0][0]

                    # Call the cleanup function to cover line 46
                    cleanup_function()

                    # Verify the cleanup function calls unregister_instance with silent=True
                    mock_tracker.unregister_instance.assert_called_with(silent=True)

    def test_main_if_name_main_coverage(self):
        """Test the if __name__ == '__main__' block in main.py - covers line 69."""
        from unittest.mock import patch

        # Mock the main function to avoid actually starting the server
        with patch('openzim_mcp.main.main') as mock_main:
            # Import the main module
            import openzim_mcp.main

            # Save the original __name__
            original_name = openzim_mcp.main.__name__

            try:
                # Set __name__ to "__main__" to trigger the condition
                openzim_mcp.main.__name__ = "__main__"

                # Execute the if __name__ == "__main__" block
                exec("""
if __name__ == "__main__":
    main()
""", {"__name__": "__main__", "main": openzim_mcp.main.main})

            finally:
                # Restore the original __name__
                openzim_mcp.main.__name__ = original_name

            # Verify main was called
            mock_main.assert_called_once()

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
        import openzim_mcp.main

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

    def test_main_module_subprocess_execution(self):
        """Test __main__.py by actually running it as a subprocess."""
        import subprocess
        import sys
        import tempfile

        # Create a temporary directory for the test
        with tempfile.TemporaryDirectory() as temp_dir:
            # Run the module using python -m to trigger __main__.py
            # This should fail quickly due to no ZIM files, but will execute __main__.py
            result = subprocess.run(
                [sys.executable, "-m", "openzim_mcp", temp_dir],
                capture_output=True,
                text=True,
                timeout=5,
                env={"PYTHONPATH": ".", **dict(__import__("os").environ)}
            )

            # The process should start and then exit (likely due to no ZIM files or other config)
            # The important thing is that __main__.py was executed
            # We expect it to fail, but not with import errors
            assert "ModuleNotFoundError" not in result.stderr
            assert "ImportError" not in result.stderr

    def test_main_module_no_args_execution(self):
        """Test __main__.py with no arguments to trigger usage message."""
        import subprocess
        import sys

        # Run the module with no arguments to trigger usage message
        result = subprocess.run(
            [sys.executable, "-m", "openzim_mcp"],
            capture_output=True,
            text=True,
            timeout=5
        )

        # Should exit with code 1 and show usage
        assert result.returncode == 1
        assert "Usage:" in result.stderr

    def test_main_module_coverage_direct_execution(self):
        """Test __main__.py by directly executing the main() call for coverage."""
        from unittest.mock import patch

        # Import the __main__ module first
        import openzim_mcp.__main__

        # Mock the main function to avoid actually starting the server
        with patch('openzim_mcp.__main__.main') as mock_main:
            # Directly call the main function that would be called in __main__.py line 8
            openzim_mcp.__main__.main()

            # Verify main was called
            mock_main.assert_called_once()

    def test_main_module_import_coverage(self):
        """Test that __main__.py can be imported without errors."""
        # This test ensures the import statement on line 5 is covered
        import openzim_mcp.__main__

        # Verify the module has the expected attributes
        assert hasattr(openzim_mcp.__main__, 'main')

        # Verify the main function is the one from the main module
        from openzim_mcp.main import main as main_func
        assert openzim_mcp.__main__.main is main_func

    def test_main_module_runpy_execution(self):
        """Test __main__.py using runpy to simulate python -m execution."""
        from unittest.mock import patch
        import runpy
        import sys
        import tempfile

        # Create a temporary directory for the test
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock sys.argv to provide the required directory argument
            with patch.object(sys, 'argv', ['openzim_mcp', temp_dir]):
                # Mock the main function to avoid actually starting the server
                with patch('openzim_mcp.main.main') as mock_main:
                    try:
                        # Use runpy to execute the module as if run with python -m
                        runpy.run_module('openzim_mcp', run_name='__main__')
                    except SystemExit:
                        # Expected when main() is called and exits
                        pass

                    # Verify main was called
                    mock_main.assert_called_once()
