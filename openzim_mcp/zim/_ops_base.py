"""Shared path-validation helper for the ZIM domain mixins."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openzim_mcp.security import PathValidator


class _ArchiveAccessMixin:
    """Composed into ``ZimOperations`` so every domain mixin reuses one
    copy of the previously-duplicated validate-path prologue."""

    if TYPE_CHECKING:
        path_validator: "PathValidator"

    def _validate_zim_path(self, zim_file_path: str) -> Path:
        """Validate a path then confirm it is a readable ZIM file.

        This is the 2-line prologue repeated across the domain mixins.
        Validation/security errors propagate unwrapped, exactly as before.
        """
        validated = self.path_validator.validate_path(zim_file_path)
        return self.path_validator.validate_zim_file(validated)
