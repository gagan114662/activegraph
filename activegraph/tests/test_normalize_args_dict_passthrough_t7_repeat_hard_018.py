"""T7 repeat-hard 018 — docstring↔code drift in tools/recorded._normalize_args.

The docstring of ``_normalize_args(tool, args)`` documents a two-branch,
``tool``-dependent contract:

    "If args is a dict and the tool has an input_schema, return the dict.
     If args is a BaseModel instance, dump to dict via canonicalize_args."

i.e. for the *dict + input_schema* case it promises to **return the dict**
(the caller's own dict, unchanged). The implementation ignored the ``tool``
parameter entirely and routed *every* input through ``canonicalize_args``,
which recursively rewrites a dict into a *new* dict with **sorted keys**.
So a dict was neither "the dict" (a different object) nor key-order-preserving
— the documented behaviour was not honoured, and the ``tool`` argument was
dead.

These tests assert the DOCUMENTED behaviour. They fail against the pre-fix
code (which reorders keys and returns a fresh dict) and pass once the function
honours its docstring.
"""

from __future__ import annotations

from activegraph.tools.base import Tool
from activegraph.tools.recorded import _normalize_args


def _tool(*, input_schema=None) -> Tool:
    return Tool(name="probe", fn=lambda args, ctx: args, input_schema=input_schema)


def test_dict_with_input_schema_returns_the_dict_unchanged() -> None:
    """Doc: 'If args is a dict and the tool has an input_schema, return the dict.'

    'the dict' means the caller's dict, with its key order intact — not a
    freshly-sorted copy.
    """

    class _Schema:  # stand-in for a Pydantic input_schema (only presence matters)
        pass

    tool = _tool(input_schema=_Schema)
    args = {"b": 1, "a": 2, "m": 3}  # deliberately not in sorted order

    out = _normalize_args(tool, args)

    # Documented contract: return the dict — so key order is preserved.
    assert list(out.keys()) == ["b", "a", "m"], (
        "docstring says 'return the dict' for the dict+input_schema case, "
        f"but keys were reordered to {list(out.keys())}"
    )
    assert out == args


def test_tool_parameter_is_actually_consulted() -> None:
    """The docstring makes behaviour conditional on the tool's input_schema,
    so the ``tool`` argument must matter. A tool WITHOUT an input_schema is
    outside the documented dict-passthrough branch; one WITH an input_schema
    is inside it and must preserve the caller's dict order.
    """

    class _Schema:
        pass

    unsorted = {"z": 1, "a": 2}

    with_schema = _normalize_args(_tool(input_schema=_Schema), dict(unsorted))

    # With an input_schema, the dict-passthrough branch applies: order kept.
    assert list(with_schema.keys()) == ["z", "a"], (
        "a tool WITH an input_schema must hit the documented dict-passthrough "
        f"branch and keep key order, got {list(with_schema.keys())}"
    )
