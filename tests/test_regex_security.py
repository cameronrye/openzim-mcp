#!/usr/bin/env python3
"""Test regex pattern security.

Verify that the regex patterns used in the codebase are secure
and don't suffer from catastrophic backtracking vulnerabilities.
"""

import sys
import time
from pathlib import Path

# Add the scripts directory to the path so we can import the module
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Import after path modification (flake8: noqa: E402)
from generate_help import parse_makefile  # noqa: E402


class TestRegexSecurity:
    """Test regex patterns for security vulnerabilities."""

    def test_makefile_parsing_with_malicious_input(self):
        """Test that Makefile parsing is resistant to ReDoS attacks."""
        # Create a temporary Makefile with potentially problematic content
        test_makefile = Path("test_makefile_temp")

        try:
            # Create content that could trigger catastrophic backtracking
            # with the old vulnerable regex pattern
            malicious_content = (
                "target1: dependency1 dependency2 " + "a" * 100 + " ## Valid comment\n"
                "target2: " + "b" * 100 + "c" * 100 + " ## Another comment\n"
                "target3: " + "#" * 50 + "## Final comment\n"
                "# This is just a comment with lots of text " + "x" * 2000 + "\n"
                "normal-target: deps ## Normal comment\n"
                "very-long-target: "
                + "dependency " * 1000
                + " ## This should be filtered\n"
            )

            with open(test_makefile, "w") as f:
                f.write(malicious_content)

            # Measure parsing time - should complete quickly
            start_time = time.time()
            result = parse_makefile(test_makefile)
            end_time = time.time()

            # Should complete in well under a second
            parsing_time = end_time - start_time
            assert (
                parsing_time < 1.0
            ), f"Parsing took too long: {parsing_time:.2f} seconds"

            # Should still extract valid targets
            all_targets = []
            for category_targets in result.values():
                all_targets.extend([target for target, _ in category_targets])

            assert "target1" in all_targets
            assert "target2" in all_targets
            assert "target3" in all_targets
            assert "normal-target" in all_targets

            # Verify that the very long target was filtered out for safety
            assert "very-long-target" not in all_targets

        finally:
            # Clean up
            if test_makefile.exists():
                test_makefile.unlink()

    def test_makefile_parsing_with_extremely_long_lines(self):
        """Test parsing with extremely long lines that could cause issues."""
        test_makefile = Path("test_makefile_long_lines")

        try:
            # Create content with very long lines
            long_line_content = (
                "short-target: ## Short comment\n"
                "long-target: " + "dependency " * 10000 + " ## Long line comment\n"
                "another-target: deps ## Normal comment\n"
            )

            with open(test_makefile, "w") as f:
                f.write(long_line_content)

            # Should handle long lines gracefully
            start_time = time.time()
            result = parse_makefile(test_makefile)
            end_time = time.time()

            # Should still complete quickly
            parsing_time = end_time - start_time
            assert (
                parsing_time < 2.0
            ), f"Parsing took too long: {parsing_time:.2f} seconds"

            # Should extract valid targets (long line might be skipped)
            all_targets = []
            for category_targets in result.values():
                all_targets.extend([target for target, _ in category_targets])

            assert "short-target" in all_targets
            assert "another-target" in all_targets

        finally:
            # Clean up
            if test_makefile.exists():
                test_makefile.unlink()

    def test_makefile_parsing_with_many_lines(self):
        """Test parsing with many lines for performance."""
        test_makefile = Path("test_makefile_many_lines")

        try:
            # Create content with many lines
            lines = []
            for i in range(5000):
                if i % 100 == 0:
                    lines.append(f"target{i}: deps ## Comment for target {i}")
                else:
                    lines.append(f"# Comment line {i}")

            content = "\n".join(lines)

            with open(test_makefile, "w") as f:
                f.write(content)

            # Should handle many lines efficiently
            start_time = time.time()
            result = parse_makefile(test_makefile)
            end_time = time.time()

            # Should complete reasonably quickly
            parsing_time = end_time - start_time
            assert (
                parsing_time < 3.0
            ), f"Parsing took too long: {parsing_time:.2f} seconds"

            # Should extract the target lines
            all_targets = []
            for category_targets in result.values():
                all_targets.extend([target for target, _ in category_targets])

            # Should have found the targets (every 100th line)
            assert len(all_targets) >= 40  # Should find most of the 50 targets

        finally:
            # Clean up
            if test_makefile.exists():
                test_makefile.unlink()

    def test_empty_and_invalid_makefiles(self):
        """Test parsing with empty and invalid Makefiles."""
        test_makefile = Path("test_makefile_empty")

        try:
            # Test empty file
            with open(test_makefile, "w") as f:
                f.write("")

            result = parse_makefile(test_makefile)
            assert isinstance(result, dict)

            # Test file with no valid targets
            with open(test_makefile, "w") as f:
                f.write("# Just comments\n# No targets here\n")

            result = parse_makefile(test_makefile)
            assert isinstance(result, dict)

        finally:
            # Clean up
            if test_makefile.exists():
                test_makefile.unlink()


if __name__ == "__main__":
    # Run the tests
    test_instance = TestRegexSecurity()
    test_instance.test_makefile_parsing_with_malicious_input()
    test_instance.test_makefile_parsing_with_extremely_long_lines()
    test_instance.test_makefile_parsing_with_many_lines()
    test_instance.test_empty_and_invalid_makefiles()
    print("All regex security tests passed!")
