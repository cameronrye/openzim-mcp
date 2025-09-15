# OpenZIM MCP Testing Guide

This guide covers the comprehensive testing infrastructure for OpenZIM MCP, including integration with the official zim-testing-suite.

## Overview

OpenZIM MCP uses a hybrid testing approach that combines:

1. **Fast unit tests** with mocked components for development
2. **Comprehensive integration tests** with real ZIM files for validation
3. **Automated test data management** for consistent testing environments

## Test Categories

### Unit Tests
- **Location**: `tests/test_*.py` (excluding `test_zim_testing_suite.py`)
- **Purpose**: Fast feedback during development
- **Dependencies**: Mock objects, temporary files
- **Runtime**: < 1 second

### Integration Tests
- **Location**: `tests/test_zim_testing_suite.py`
- **Purpose**: Validate functionality with real ZIM files
- **Dependencies**: zim-testing-suite files
- **Runtime**: 1-10 seconds

### Performance Tests
- **Markers**: `@pytest.mark.slow`
- **Purpose**: Validate caching and performance characteristics
- **Dependencies**: Real ZIM files
- **Runtime**: 10+ seconds

## ZIM Test Data Integration

### Official Test Files

OpenZIM MCP integrates with the [zim-testing-suite](https://github.com/openzim/zim-testing-suite) repository, which provides:

- **Valid ZIM files**: Various formats and content types
- **Invalid ZIM files**: For error handling testing
- **Edge cases**: Split files, embedded content, etc.

### Test File Categories

#### Basic Files (Priority 1)
Essential files for core functionality testing:
- `withns/small.zim` - Small ZIM with namespaces
- `nons/small.zim` - Small ZIM without namespaces

#### Real Content (Priority 2-3)
Actual content for integration testing:
- `withns/wikibooks_be_all_nopic_2017-02.zim` - Real Wikibooks content
- `withns/wikipedia_en_climate_change_mini_2024-06.zim` - Wikipedia content

#### Invalid Files (Priority 2)
For error handling validation:
- `invalid.smaller_than_header.zim` - Truncated file
- `invalid.bad_mimetype_in_dirent.zim` - Corrupted MIME types
- `invalid.outofbounds_clusterptrpos.zim` - Invalid pointers

#### Special Cases (Priority 3)
Advanced testing scenarios:
- `small.zim.embedded` - Embedded content
- `*.zimaa`, `*.zimab`, `*.zimac` - Split files

## Running Tests

### Basic Testing

```bash
# Run all tests (unit + integration if data available)
make test

# Run with coverage
make test-cov

# Run specific test file
uv run pytest tests/test_security.py -v
```

### ZIM Data Testing

```bash
# Download essential test files
make download-test-data

# Run tests with ZIM data
make test-with-zim-data

# Run only tests requiring ZIM data
make test-requires-zim-data

# Run integration tests only
make test-integration
```

### Advanced Testing

```bash
# Download all test files (14+ MB)
make download-test-data-all

# Run slow tests
uv run pytest -m "slow"

# Run with specific test data directory
ZIM_TEST_DATA_DIR=/custom/path make test
```

## Test Data Management

### Automatic Download

The `scripts/download_test_data.py` script manages test data:

```bash
# List available files
python scripts/download_test_data.py --list

# Download by priority (1=essential, 2=important, 3=advanced)
python scripts/download_test_data.py --priority 2

# Download specific categories
python scripts/download_test_data.py --category basic invalid_files

# Force re-download
python scripts/download_test_data.py --force
```

### Manual Management

```bash
# Clean test data
make clean-test-data

# Set custom test data location
export ZIM_TEST_DATA_DIR=/path/to/test/data
```

### Test Data Structure

```
test_data/zim-testing-suite/
├── manifest.json              # File metadata and checksums
├── withns/                     # Files with namespaces
│   ├── small.zim
│   ├── wikibooks_be_all_nopic_2017-02.zim
│   ├── invalid.*.zim
│   └── ...
└── nons/                       # Files without namespaces
    ├── small.zim
    └── ...
```

## Test Configuration

### Environment Variables

- `ZIM_TEST_DATA_DIR`: Custom test data directory
- `PYTEST_CURRENT_TEST`: Current test name (set by pytest)

### Pytest Markers

```python
@pytest.mark.requires_zim_data  # Requires ZIM test files
@pytest.mark.integration       # Integration test
@pytest.mark.slow             # Long-running test
```

### Test Fixtures

Key fixtures available in tests:

```python
# ZIM test data fixtures
zim_test_data_dir              # Path to test data directory
zim_test_manifest              # Manifest with file metadata
available_test_zim_files       # List of all available ZIM files
basic_test_zim_files           # Essential test files
invalid_test_zim_files         # Invalid files for error testing
real_content_zim_files         # Real content files

# Configuration fixtures
test_config_with_zim_data      # Config including ZIM data paths
```

## Writing Tests

### Unit Test Example

```python
def test_zim_operations_basic(self, zim_operations: ZimOperations, temp_dir: Path):
    """Test basic functionality with mocked data."""
    # Create mock ZIM file
    zim_file = temp_dir / "test.zim"
    zim_file.write_text("test content")
    
    # Test with mocks
    with patch("openzim-mcp.zim_operations.Archive") as mock_archive:
        # Setup mock behavior
        mock_archive_instance = MagicMock()
        mock_archive.return_value = mock_archive_instance
        
        # Test functionality
        result = zim_operations.list_zim_files()
        assert "test.zim" in result
```

### Integration Test Example

```python
@pytest.mark.requires_zim_data
def test_real_zim_file(self, basic_test_zim_files: Dict[str, Optional[Path]]):
    """Test with real ZIM files."""
    withns_file = basic_test_zim_files["withns"]
    if withns_file:
        # Test with real file
        result = zim_ops.get_zim_metadata(str(withns_file))
        assert "entry_count" in result
```

## Continuous Integration

### GitHub Actions Integration

```yaml
- name: Download test data
  run: make download-test-data

- name: Run comprehensive tests
  run: make test-with-zim-data
```

### Test Skipping

Tests requiring ZIM data are automatically skipped if data is not available:

```python
def pytest_collection_modifyitems(config, items):
    """Skip tests requiring ZIM data if not available."""
    if not zim_data_available:
        skip_zim_data = pytest.mark.skip(reason="ZIM test data not available")
        for item in items:
            if "requires_zim_data" in item.keywords:
                item.add_marker(skip_zim_data)
```

## Troubleshooting

### Common Issues

1. **Tests skipped**: ZIM test data not available
   - Solution: Run `make download-test-data`

2. **Download failures**: Network connectivity issues
   - Solution: Check internet connection, retry download

3. **Invalid file tests failing**: libzim handles files gracefully
   - Solution: Update test expectations for graceful handling

4. **Performance tests flaky**: Timing-dependent tests
   - Solution: Use relative performance comparisons

### Debug Commands

```bash
# Check test data status
ls -la test_data/zim-testing-suite/

# Verify manifest
cat test_data/zim-testing-suite/manifest.json

# Run single test with verbose output
uv run pytest tests/test_zim_testing_suite.py::TestZimTestingSuiteIntegration::test_basic_zim_files_available -v

# Run with debug logging
uv run pytest --log-cli-level=DEBUG
```

## Best Practices

1. **Use appropriate test types**: Unit tests for logic, integration tests for file operations
2. **Mock external dependencies**: Use mocks for fast unit tests
3. **Test error conditions**: Include tests for invalid inputs and edge cases
4. **Maintain test data**: Keep test files up to date with zim-testing-suite
5. **Document test requirements**: Use clear markers and docstrings
6. **Optimize test performance**: Use caching and selective test execution
