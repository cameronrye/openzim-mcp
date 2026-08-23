"""``schema_slimming`` — what it removes, and everything it must not.

The transform runs over generated JSON Schema, where the same token can be a
keyword or a name the schema author chose. The interesting tests here are the
ones that pin the difference: a property literally named ``title``, a
definition named ``title``, and a real ``default`` whose *value* is an object
carrying a ``title`` key. None of the eight shipped tools declares any of
those, so nothing on the live surface would notice a walk that confused data
for vocabulary — the fixtures below are the only thing standing between that
bug and a silently mangled schema.
"""

import json
import tempfile
from typing import Any

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.mcp_envelope import _unknown_argument_error
from openzim_mcp.schema_slimming import slim_input_schema
from openzim_mcp.server import OpenZimMcpServer

_ALLOWED_DIR = tempfile.mkdtemp(prefix="openzim_mcp_schema_slimming_")


@pytest.fixture(scope="module")
def advanced_tools():
    cfg = OpenZimMcpConfig(allowed_directories=[_ALLOWED_DIR], tool_mode="advanced")
    return OpenZimMcpServer(cfg).mcp._tool_manager._tools


# Keywords whose value is a map from author-chosen NAMES to subschemas. The
# helper below needs them to say whether a given key is a keyword or a name;
# the transform under test needs the full list, which is its own business.
_NAME_MAPS = ("properties", "$defs", "definitions")


def _schema_positions(node: Any, *, in_name_map: bool = False):
    """Yield ``(is_keyword, key, value)`` for every dict entry below ``node``.

    ``is_keyword`` is False exactly where the key is a property or definition
    name rather than JSON Schema vocabulary — the distinction the transform has
    to get right, restated independently here so the tests are not checking the
    implementation against itself.

    Otherwise deliberately naive: it descends into instance data too, so a
    "nothing survived" assertion over-reports rather than under-reports.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            yield not in_name_map, key, value
            yield from _schema_positions(
                value, in_name_map=not in_name_map and key in _NAME_MAPS
            )
    elif isinstance(node, list):
        for item in node:
            yield from _schema_positions(item)


# ---------------------------------------------------------------------------
# The live surface
# ---------------------------------------------------------------------------


def test_the_detector_sees_an_untrimmed_schema():
    """Guards the guard below: a walk that finds nothing proves nothing.

    Also pins the keyword/name split the detector is built on — the property
    named ``title`` is not counted, the ``title`` inside its schema is.
    """
    untrimmed = {
        "type": "object",
        "title": "Root",
        "properties": {
            "a": {"type": "string", "title": "A", "default": None},
            "title": {"type": "string"},
        },
    }
    found = sorted(
        key
        for is_keyword, key, value in _schema_positions(untrimmed)
        if is_keyword and (key == "title" or (key == "default" and value is None))
    )
    assert found == ["default", "title", "title"]


def test_the_advanced_surface_publishes_no_generated_annotations(advanced_tools):
    """No tool ships a ``title`` keyword or a ``default: null``.

    This is the guard behind ``add_tool``'s deliberately silent tool lookup: a
    seam that stopped firing shows up here, naming the tool, instead of raising
    at server startup.
    """
    offenders = []
    for name, tool in advanced_tools.items():
        for is_keyword, key, value in _schema_positions(tool.parameters):
            if not is_keyword:
                continue
            if key == "title":
                offenders.append(f"{name}: title={value!r}")
            if key == "default" and value is None:
                offenders.append(f"{name}: default=null")
    assert not offenders, (
        "generated annotations reached the wire: "
        + ", ".join(offenders)
        + ". EnvelopeAwareMCPServer.add_tool should have slimmed these."
    )


def test_real_defaults_survive_on_the_live_surface(advanced_tools):
    """The trim must not have taken the defaults that mean something.

    ``zim_query.synthesize`` defaults to ``False`` and ``zim_links.direction``
    to ``"outbound"``: a falsy default and a string one, both of which a
    "drop empty defaults" implementation would eat.
    """
    assert advanced_tools["zim_query"].parameters["properties"]["synthesize"] == {
        "default": False,
        "type": "boolean",
    }
    assert (
        advanced_tools["zim_links"].parameters["properties"]["direction"]["default"]
        == "outbound"
    )
    assert (
        advanced_tools["zim_query"].parameters["properties"]["offset"]["default"] == 0
    )


def test_every_declared_argument_survives_the_trim(advanced_tools):
    """Same properties, same ``required`` — so the same calls are accepted.

    ``mcp_envelope._unknown_argument_error`` builds its allow-list from
    ``parameters["properties"]``, so a trim that dropped a property would turn
    a valid argument into a rejected one.
    """
    for name, tool in advanced_tools.items():
        generated = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)
        assert set(tool.parameters["properties"]) == set(generated["properties"]), name
        assert tool.parameters.get("required", []) == generated.get(
            "required", []
        ), name
        assert tool.parameters["type"] == "object", name


def test_argument_acceptance_and_rejection_are_unchanged(advanced_tools):
    """Every tool still takes the names it declares and still refuses the rest."""
    for name, tool in advanced_tools.items():
        declared = sorted(tool.parameters["properties"])
        accepted = dict.fromkeys(declared, "x")
        assert _unknown_argument_error(tool, name, accepted) is None, name

        rejected = _unknown_argument_error(tool, name, {"not_a_parameter": 1})
        assert rejected is not None, name
        assert rejected["unknown_arguments"] == ["not_a_parameter"]
        assert rejected["accepted_arguments"] == declared


def test_the_trim_reclaims_over_a_kilobyte_of_the_advanced_surface(advanced_tools):
    """Worth doing: the reclaimed bytes are budget, not rounding.

    Asserted as a floor rather than an exact total so ordinary description
    edits do not have to touch this test; the exact figure at the time of the
    change was 1,621B (25,432 → 23,811 against the 25,600B cap in
    ``test_phase_f_schema_budget``).
    """

    def wire(schema) -> int:
        return len(json.dumps(schema, separators=(",", ":")).encode())

    generated = sum(
        wire(tool.fn_metadata.arg_model.model_json_schema(by_alias=True))
        for tool in advanced_tools.values()
    )
    published = sum(wire(tool.parameters) for tool in advanced_tools.values())
    assert generated - published >= 1_000, (
        f"the trim now reclaims only {generated - published}B "
        f"({generated} → {published}); it was worth 1,621B when it landed."
    )


# ---------------------------------------------------------------------------
# Keyword vs. name — the cases the live surface cannot exercise
# ---------------------------------------------------------------------------


def test_a_property_literally_named_title_is_kept():
    """``properties`` keys are names. Only the value's own ``title`` goes."""
    slimmed = slim_input_schema(
        {
            "type": "object",
            "title": "ArgumentsModel",
            "properties": {
                "title": {"type": "string", "title": "Title"},
                "default": {"type": "string", "title": "Default"},
            },
            "required": ["title"],
        }
    )
    assert slimmed == {
        "type": "object",
        "properties": {"title": {"type": "string"}, "default": {"type": "string"}},
        "required": ["title"],
    }


def test_a_definition_named_title_is_kept():
    """``$defs``/``definitions`` keys are names too, and ``$ref`` targets them."""
    slimmed = slim_input_schema(
        {
            "type": "object",
            "$defs": {
                "title": {"type": "string", "title": "Title", "default": None},
                "default": {"type": "integer", "title": "Default"},
            },
            "properties": {"heading": {"$ref": "#/$defs/title", "title": "Heading"}},
        }
    )
    assert slimmed == {
        "type": "object",
        "$defs": {"title": {"type": "string"}, "default": {"type": "integer"}},
        "properties": {"heading": {"$ref": "#/$defs/title"}},
    }


def test_instance_data_carrying_a_title_key_is_untouched():
    """A ``default``/``const``/``enum``/``examples`` value is data, not a schema.

    An object-valued default that happens to contain ``{"title": ...}`` is the
    caller's payload; walking into it would silently change what the tool
    receives when the argument is omitted.
    """
    schema = {
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "title": "Header",
                "default": {"title": "untitled", "level": 1},
                "examples": [{"title": "Chapter 1"}],
            },
            "marker": {"const": {"title": "sentinel"}, "title": "Marker"},
            "choice": {"enum": [{"title": "a"}, {"title": "b"}], "title": "Choice"},
        },
    }
    slimmed = slim_input_schema(schema)
    header = slimmed["properties"]["header"]
    assert "title" not in header
    assert header["default"] == {"title": "untitled", "level": 1}
    assert header["examples"] == [{"title": "Chapter 1"}]
    assert slimmed["properties"]["marker"] == {"const": {"title": "sentinel"}}
    assert slimmed["properties"]["choice"] == {"enum": [{"title": "a"}, {"title": "b"}]}


def test_falsy_defaults_are_not_null_defaults():
    """Only ``None`` goes. ``0``/``""``/``False``/``[]``/``{}`` are real values."""
    schema = {
        "type": "object",
        "properties": {
            "offset": {"type": "integer", "default": 0, "title": "Offset"},
            "prefix": {"type": "string", "default": "", "title": "Prefix"},
            "compact": {"type": "boolean", "default": False, "title": "Compact"},
            "tags": {"type": "array", "default": [], "title": "Tags"},
            "opts": {"type": "object", "default": {}, "title": "Opts"},
            "cursor": {"type": "string", "default": None, "title": "Cursor"},
        },
    }
    props = slim_input_schema(schema)["properties"]
    assert props["offset"] == {"type": "integer", "default": 0}
    assert props["prefix"] == {"type": "string", "default": ""}
    assert props["compact"] == {"type": "boolean", "default": False}
    assert props["tags"] == {"type": "array", "default": []}
    assert props["opts"] == {"type": "object", "default": {}}
    assert props["cursor"] == {"type": "string"}


def test_every_applicator_shape_is_recursed():
    """Map-valued, list-valued and single-valued applicators all get walked."""
    schema = {
        "type": "object",
        "title": "Root",
        "properties": {
            "items_form": {
                "type": "array",
                "title": "Items Form",
                "items": {"type": "string", "title": "Item", "default": None},
                "prefixItems": [{"type": "integer", "title": "First"}],
                "contains": {"type": "string", "title": "Contains"},
            },
            "union_form": {
                "title": "Union Form",
                "anyOf": [{"type": "string", "title": "A"}],
                "oneOf": [{"type": "integer", "title": "B"}],
                "allOf": [{"type": "object", "title": "C"}],
                "not": {"type": "null", "title": "D"},
            },
            "object_form": {
                "type": "object",
                "title": "Object Form",
                "additionalProperties": {"type": "string", "title": "Extra"},
                "patternProperties": {"^x-": {"type": "string", "title": "Ext"}},
                "propertyNames": {"pattern": "^a", "title": "Names"},
                "if": {"required": ["a"], "title": "If"},
                "then": {"required": ["b"], "title": "Then"},
                "else": {"required": ["c"], "title": "Else"},
            },
        },
    }
    slimmed = slim_input_schema(schema)
    remaining = [
        key
        for is_keyword, key, _ in _schema_positions(slimmed)
        if is_keyword and key == "title"
    ]
    assert not remaining, f"titles survived at {len(remaining)} position(s)"
    items_form = slimmed["properties"]["items_form"]
    assert items_form["items"] == {"type": "string"}
    assert items_form["prefixItems"] == [{"type": "integer"}]
    assert slimmed["properties"]["object_form"]["patternProperties"] == {
        "^x-": {"type": "string"}
    }


def test_a_boolean_subschema_is_left_alone():
    """``additionalProperties: false`` is a schema, but not a dict to rebuild."""
    assert slim_input_schema(
        {"type": "object", "additionalProperties": False, "title": "Root"}
    ) == {"type": "object", "additionalProperties": False}


def test_the_input_schema_is_not_mutated():
    """The trim returns a new schema and shares no mutable structure with it."""
    schema = {
        "type": "object",
        "title": "Root",
        "properties": {"a": {"type": "string", "title": "A", "default": None}},
    }
    original = json.loads(json.dumps(schema))
    slimmed = slim_input_schema(schema)
    assert schema == original

    slimmed["properties"]["a"]["type"] = "integer"
    assert schema == original


def test_the_trim_is_idempotent():
    """Applying it to an already-trimmed schema is a no-op."""
    schema = {
        "type": "object",
        "title": "Root",
        "properties": {"a": {"anyOf": [{"type": "string"}], "default": None}},
    }
    once = slim_input_schema(schema)
    assert slim_input_schema(once) == once
