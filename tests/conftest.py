"""Pytest configuration and fixtures for OpenZIM MCP tests."""

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Generator, List, Optional

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def test_config(temp_dir: Path) -> OpenZimMcpConfig:
    """Create a test configuration with the full advanced tool surface.

    Most tests exercise individual advanced-mode tools (``get_zim_entries``,
    ``search_zim_file``, the per-entry resource handler, etc.). Pinning the
    fixture to ``tool_mode='advanced'`` keeps those tests independent of the
    default mode. The few tests that specifically validate simple-mode
    behavior construct their own ``OpenZimMcpConfig`` instead.
    """
    return OpenZimMcpConfig(
        allowed_directories=[str(temp_dir)],
        tool_mode="advanced",
        cache=CacheConfig(enabled=True, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="DEBUG"),
    )


@pytest.fixture
def path_validator(test_config: OpenZimMcpConfig) -> PathValidator:
    """Create a path validator for testing."""
    return PathValidator(test_config.allowed_directories)


@pytest.fixture
def cache_config() -> CacheConfig:
    """Create cache configuration for testing."""
    return CacheConfig(enabled=True, max_size=5, ttl_seconds=60)


@pytest.fixture
def openzim_mcp_cache(cache_config: CacheConfig) -> OpenZimMcpCache:
    """Create a cache instance for testing."""
    return OpenZimMcpCache(cache_config)


@pytest.fixture
def content_processor() -> ContentProcessor:
    """Create a content processor for testing."""
    return ContentProcessor(snippet_length=100)


@pytest.fixture
def sample_html() -> str:
    """Sample HTML content for testing."""
    return """
    <html>
        <head>
            <title>Test Page</title>
            <script>alert('test');</script>
        </head>
        <body>
            <h1>Main Title</h1>
            <p>This is the first paragraph with <strong>bold text</strong>.</p>
            <p>This is the second paragraph.</p>
            <div class="mw-editsection">Edit section</div>
            <footer>Footer content</footer>
        </body>
    </html>
    """


# ZIM Testing Suite Integration Fixtures


@pytest.fixture(scope="session")
def zim_test_data_dir() -> Optional[Path]:
    """Get the ZIM test data directory from env var or default location.

    Returns:
        Path to ZIM test data directory if it exists, None otherwise
    """
    # Check environment variable first
    env_dir = os.environ.get("ZIM_TEST_DATA_DIR")
    if env_dir:
        path = Path(env_dir)
        if path.exists():
            return path

    # Check default location
    default_path = Path(__file__).parent.parent / "test_data" / "zim-testing-suite"
    if default_path.exists():
        return default_path

    return None


@pytest.fixture(scope="session")
def zim_test_manifest(zim_test_data_dir: Optional[Path]) -> Optional[Dict]:
    """Load the ZIM test data manifest if available.

    Returns:
        Manifest dictionary or None if not available
    """
    if not zim_test_data_dir:
        return None

    manifest_path = zim_test_data_dir / "manifest.json"
    if not manifest_path.exists():
        return None

    try:
        with open(manifest_path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


@pytest.fixture
def available_test_zim_files(zim_test_data_dir: Optional[Path]) -> List[Path]:
    """Get list of available ZIM test files.

    Returns:
        List of available ZIM file paths
    """
    if not zim_test_data_dir:
        return []

    zim_files = []
    for pattern in ["**/*.zim", "**/*.zim.*"]:
        zim_files.extend(zim_test_data_dir.glob(pattern))

    return sorted(zim_files)


@pytest.fixture
def basic_test_zim_files(
    zim_test_data_dir: Optional[Path],
) -> Dict[str, Optional[Path]]:
    """Get basic test ZIM files for essential testing.

    Returns:
        Dictionary with 'withns' and 'nons' keys pointing to small.zim files
    """
    files = {"withns": None, "nons": None}

    if not zim_test_data_dir:
        return files

    withns_file = zim_test_data_dir / "withns" / "small.zim"
    if withns_file.exists():
        files["withns"] = withns_file

    nons_file = zim_test_data_dir / "nons" / "small.zim"
    if nons_file.exists():
        files["nons"] = nons_file

    return files


@pytest.fixture
def invalid_test_zim_files(zim_test_data_dir: Optional[Path]) -> List[Path]:
    """Get invalid ZIM test files for error handling testing.

    Returns:
        List of invalid ZIM file paths
    """
    if not zim_test_data_dir:
        return []

    invalid_files = []
    for pattern in ["**/invalid.*.zim"]:
        invalid_files.extend(zim_test_data_dir.glob(pattern))

    return sorted(invalid_files)


@pytest.fixture
def real_content_zim_files(
    zim_test_data_dir: Optional[Path],
) -> Dict[str, Optional[Path]]:
    """Get real content ZIM files for integration testing.

    Returns:
        Dictionary with available real content ZIM files
    """
    files = {"wikibooks": None, "wikipedia_climate": None}

    if not zim_test_data_dir:
        return files

    wikibooks_file = zim_test_data_dir / "withns" / "wikibooks_be_all_nopic_2017-02.zim"
    if wikibooks_file.exists():
        files["wikibooks"] = wikibooks_file

    wikipedia_file = (
        zim_test_data_dir / "withns" / "wikipedia_en_climate_change_mini_2024-06.zim"
    )
    if wikipedia_file.exists():
        files["wikipedia_climate"] = wikipedia_file

    return files


@pytest.fixture
def test_config_with_zim_data(
    temp_dir: Path, zim_test_data_dir: Optional[Path]
) -> OpenZimMcpConfig:
    """Create a test config including ZIM test data directory if available."""
    allowed_dirs = [str(temp_dir)]

    # Add ZIM test data directory to allowed directories if available
    if zim_test_data_dir:
        allowed_dirs.append(str(zim_test_data_dir))

    return OpenZimMcpConfig(
        allowed_directories=allowed_dirs,
        tool_mode="advanced",
        cache=CacheConfig(enabled=True, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="DEBUG"),
    )


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line(
        "markers",
        "live: mark test as spawning a real openzim-mcp subprocess "
        "(binds loopback ports; deselected unless explicitly requested via "
        "`-m live` or `make test-live`)",
    )
    config.addinivalue_line(
        "markers",
        "docker: mark test as additionally requiring the docker CLI and a "
        "reachable daemon (auto-skipped otherwise)",
    )
