"""ZIM operations package.

The package layout is an implementation detail; external callers should
import from ``openzim_mcp.zim_operations`` (the backward-compat shim).

This ``__init__`` deliberately defers the public re-exports until late
to avoid circularity during the in-progress refactor: ``zim_operations``
still owns the ``ZimOperations`` class and ``zim_archive`` symbol, and
each mixin module under this package needs to import
``openzim_mcp.zim_operations`` for late-bound access. Re-exporting
``ZimOperations`` from this package's ``__init__`` would force
``zim_operations`` to import this package before ``ZimOperations`` is
defined.
"""
