"""T7 repeat-hard 002 — docstring↔code drift regression.

`example_instance_from_schema`'s docstring states it "Walks the schema's
``type``, ``properties``, ``items``, ``enum``, ``required``, and ``$defs``
keys" (activegraph/llm/prompt.py docstring). The example it renders is a
*minimal* concrete instance the model is told to mirror — so honoring
``required`` means the example object carries exactly the schema's required
properties, not every declared property.

The bug: the object branch ignored ``required`` entirely (the key was named
in the docstring but never read in the code), emitting a value for every
property. A schema with optional properties produced an example that
over-specifies the shape — directly contradicting the documented walk of
``required``.
"""

from activegraph.llm.prompt import example_instance_from_schema


def test_example_instance_object_emits_only_required_properties() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["name"],
    }

    example = example_instance_from_schema(schema)

    # The docstring promises ``required`` is walked: a minimal example
    # carries only the required properties, not the optional ones.
    assert example == {"name": "<string>"}


def test_example_instance_object_without_required_emits_all_properties() -> None:
    # No ``required`` key => no minimization signal => every property is shown.
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "boolean"},
        },
    }

    example = example_instance_from_schema(schema)

    assert example == {"a": 0, "b": True}


def test_example_instance_object_all_required_emits_all_properties() -> None:
    schema = {
        "type": "object",
        "properties": {
            "x": {"type": "string"},
            "y": {"type": "number"},
        },
        "required": ["x", "y"],
    }

    example = example_instance_from_schema(schema)

    assert example == {"x": "<string>", "y": 0.0}
