"""Tests for async_operations module."""

from unittest.mock import MagicMock

import pytest

from openzim_mcp.async_operations import AsyncZimOperations
from openzim_mcp.zim_operations import ZimOperations


class TestAsyncZimOperations:
    """Test AsyncZimOperations class."""

    @pytest.fixture
    def mock_zim_operations(self) -> MagicMock:
        """Create a mock ZimOperations instance."""
        return MagicMock(spec=ZimOperations)

    def test_initialization(self, mock_zim_operations: MagicMock):
        """Test AsyncZimOperations initialization."""
        async_ops = AsyncZimOperations(mock_zim_operations)

        assert async_ops._ops == mock_zim_operations
