"""Drop the keys pydantic adds to a generated tool schema for its own benefit.

``func_metadata`` builds one pydantic model per tool and publishes
``model_json_schema()`` as that tool's ``inputSchema``. The generator emits two
keys that describe the model rather than the call:

``title`` — a title-cased echo of the field name (``limit`` → ``"Limit"``,
``zim_file_path`` → ``"Zim File Path"``) and, at the root, the generated
argument model's class name (``"zim_healthArguments"``). A client already has
the property key and the tool's ``name``; the echo tells it nothing further,
and the root value names an implementation detail no user ever sees.

``default: null`` — how an ``Optional[...] = None`` parameter renders. The
property's own ``anyOf`` already carries a ``{"type": "null"}`` branch, so the
key restates it.

Together they cost 1,621 bytes across the eight advanced tools — 6% of a
surface measured against a hard 25KiB cap in
``tests/test_phase_f_schema_budget.py`` — and buy nothing a tool-calling model
can act on. The trim runs once at registration
(``EnvelopeAwareMCPServer.add_tool``) so the schema the SDK serves, the schema
``mcp_envelope`` reads to reject undeclared arguments, and the schema the
budget test measures stay the same object rather than three drifting copies.

Argument validation is untouched by construction: the SDK validates against
``fn_metadata.arg_model``, never against this dict (see ``Tool.run`` →
``call_fn_with_arg_validation``), and the one in-repo consumer reads property
*names* only (``mcp_envelope._unknown_argument_error``).
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = ["slim_input_schema"]

# JSON Schema 2020-12 applicator keywords, grouped by the shape of their value.
# The grouping is the load-bearing part, not a tidiness choice: under a
# map-valued applicator the KEYS are property or definition names chosen by the
# schema author, so the walk has to enter its values while never testing its
# keys against this vocabulary. That is what keeps ``title`` the keyword
# distinguishable from a property literally named ``title``. (The SDK's own
# schema walk in ``mcp.shared.inbound`` groups the same keywords the same way;
# these are spec vocabulary rather than SDK internals, so they are restated
# here instead of imported from a private name.)
_SUBSCHEMA_MAP = frozenset(
    {"properties", "patternProperties", "dependentSchemas", "$defs", "definitions"}
)
_SUBSCHEMA_LIST = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SUBSCHEMA_SINGLE = frozenset(
    {
        "items",
        "contains",
        "additionalProperties",
        "unevaluatedItems",
        "unevaluatedProperties",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "contentSchema",
    }
)


def slim_input_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return ``schema`` with generated ``title``s and ``default: null`` removed.

    Only those two keys change. Everything else — including a ``default`` that
    is a real value, and ``0`` / ``""`` / ``false`` / ``[]`` are real values —
    survives verbatim, and so does the set of declared properties, so the
    schema still accepts and rejects exactly the arguments it did before.

    The result shares no mutable structure with ``schema``, so a caller may
    keep the original and it is safe to apply twice.
    """
    slimmed: dict[str, Any] = _slim(schema)
    return slimmed


def _slim(node: Any) -> Any:
    """Recurse one schema position, rebuilding it without the two keys."""
    if not isinstance(node, dict):
        # A boolean schema (``"additionalProperties": false``) or a position
        # that is not a schema object at all: nothing to drop, nothing below.
        return copy.deepcopy(node)

    out: dict[str, Any] = {}
    for keyword, value in node.items():
        # Reached only as a keyword of a schema object — a property named
        # ``title`` arrives as a KEY of a ``properties`` map, which the
        # map branch below consumes without ever looking at it here. The
        # ``str`` test is the second line of that defence: were some future
        # map-valued applicator missing from ``_SUBSCHEMA_MAP``, a member
        # named ``title`` would still be a schema object, not a string.
        if keyword == "title" and isinstance(value, str):
            continue
        if keyword == "default" and value is None:
            continue
        if keyword in _SUBSCHEMA_MAP and isinstance(value, dict):
            out[keyword] = {name: _slim(sub) for name, sub in value.items()}
        elif keyword in _SUBSCHEMA_LIST and isinstance(value, list):
            out[keyword] = [_slim(sub) for sub in value]
        elif keyword in _SUBSCHEMA_SINGLE:
            out[keyword] = _slim(value)
        else:
            # Instance data (``default``, ``const``, ``enum``, ``examples``)
            # and plain annotations. Copied verbatim and never walked, so a
            # real default that happens to be ``{"title": "..."}`` keeps its
            # key: the walk must not mistake a caller's data for a keyword.
            out[keyword] = copy.deepcopy(value)
    return out
