"""v1.0.1 patches from the first external user-test.

Three small findings:

1. Multi-run scripts had to reach into the private `_REGISTRY` after
   `clear_registry()` to re-populate. Fix: public `register()` plus
   `clear_registry()` returns the cleared list.

2. `@llm_behavior(output_schema=SomeModel)` showed the schema only;
   some models returned the schema back as their response (triggering
   `llm.schema_violation`). Fix: prompt also includes an example
   instance and explicit "instance, not the schema" language.

3. `SQLiteEventStore()` constructor raised a bare TypeError that
   didn't point at the higher-level `persist_to=` path. Fix: structured
   message naming `Runtime(graph, persist_to=...)`.

Tests live in one file so the v1.0.1 surface is auditable as a group.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

import activegraph
from activegraph import (
    Behavior,
    Graph,
    Runtime,
    behavior,
    clear_registry,
    get_registry,
    register,
)
from activegraph.llm.prompt import (
    build_instruction,
    build_system_prompt,
    example_instance_from_schema,
)
from activegraph.store.sqlite import SQLiteEventStore


# ---------- finding 1: registry round-trip ---------------------------------


def test_register_appends_to_global_registry():
    @behavior(name="a", on=["x.created"])
    def _a(event, graph, ctx):
        pass

    cleared = clear_registry()
    assert cleared == [_a]
    assert get_registry() == []

    register(_a)
    assert get_registry() == [_a]


def test_clear_registry_returns_in_registration_order():
    @behavior(name="first", on=["x.created"])
    def _first(event, graph, ctx):
        pass

    @behavior(name="second", on=["x.created"])
    def _second(event, graph, ctx):
        pass

    cleared = clear_registry()
    assert [b.name for b in cleared] == ["first", "second"]
    assert get_registry() == []


def test_register_rejects_non_behavior_objects():
    with pytest.raises(TypeError, match="expected a Behavior"):
        register("not a behavior")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="expected a Behavior"):
        register(lambda event, graph, ctx: None)  # type: ignore[arg-type]


def test_multi_run_pattern_round_trips_through_runtime():
    """End-to-end shape from the cookbook recipe: capture once,
    re-register per run, run each Runtime fresh."""

    fire_log: list[str] = []

    @behavior(name="record_object_creation", on=["object.created"])
    def _record(event, graph, ctx):
        fire_log.append(event.id)

    cleared = clear_registry()
    assert _record in cleared

    for run_n in range(2):
        assert get_registry() == []
        for b in cleared:
            register(b)
        graph = Graph()
        rt = Runtime(graph)
        graph.add_object("doc", {"n": run_n})
        rt.run_until_idle()
        assert len(fire_log) == run_n + 1
        clear_registry()


def test_register_is_exported_on_top_level_package():
    assert "register" in activegraph.__all__
    assert callable(activegraph.register)


# ---------- finding 2: schema example in the system prompt -----------------


class _Claim(BaseModel):
    speaker: str
    statement: str
    confidence: float


class _ClaimList(BaseModel):
    claims: list[_Claim]


def test_system_prompt_includes_an_example_instance_alongside_schema():
    schema_json = _ClaimList.model_json_schema()
    sp = build_system_prompt(
        behavior_name="extract",
        description="Pull claims.",
        frame=None,
        output_schema_name="ClaimList",
        output_schema_json=schema_json,
    )
    assert "Schema:" in sp
    assert "Example instance" in sp
    # The example instance should be a JSON object, not the schema:
    # a schema has a "properties" key at the top level; an instance
    # has the actual field names ("claims") at the top level.
    example_section = sp.split("Example instance")[1]
    assert '"claims"' in example_section
    # And the placeholder values are present, proving it's an example
    # not the schema:
    assert "<string>" in example_section


def test_system_prompt_says_instance_not_schema():
    schema_json = _ClaimList.model_json_schema()
    sp = build_system_prompt(
        behavior_name="extract",
        description="",
        frame=None,
        output_schema_name="ClaimList",
        output_schema_json=schema_json,
    )
    # The explicit framing the user-test surfaced as the missing piece:
    assert "INSTANCE" in sp
    assert "NOT the schema" in sp


def test_instruction_names_instance_not_schema():
    s_with_creates = build_instruction(
        creates=["claim"], output_schema_name="ClaimList"
    )
    assert "instance" in s_with_creates.lower()
    assert "NOT the schema" in s_with_creates

    s_schema_only = build_instruction(creates=[], output_schema_name="ClaimList")
    assert "instance" in s_schema_only.lower()
    assert "NOT the schema" in s_schema_only


def test_example_instance_walks_nested_pydantic_schema():
    schema = _ClaimList.model_json_schema()
    ex = example_instance_from_schema(schema)
    # Top-level shape is an object with the field name, not the schema:
    assert isinstance(ex, dict)
    assert "claims" in ex
    assert isinstance(ex["claims"], list)
    assert len(ex["claims"]) == 1
    inner = ex["claims"][0]
    assert isinstance(inner, dict)
    # Inner fields all present with type-correct placeholders:
    assert inner["speaker"] == "<string>"
    assert inner["statement"] == "<string>"
    assert isinstance(inner["confidence"], float)


def test_example_instance_handles_enum_and_optional():
    # Enum: pick the first variant.
    enum_schema = {"type": "string", "enum": ["low", "medium", "high"]}
    assert example_instance_from_schema(enum_schema) == "low"

    # anyOf with null: pick the non-null variant.
    optional_schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert example_instance_from_schema(optional_schema) == "<string>"


# ---------- finding 3: SQLiteEventStore constructor message ----------------


def test_sqlite_event_store_bare_call_hints_at_persist_to():
    with pytest.raises(TypeError) as exc_info:
        SQLiteEventStore()  # type: ignore[call-arg]
    msg = str(exc_info.value)
    assert "persist_to=" in msg
    assert "Runtime(" in msg
    # T3 (v1.1): path-only construction is now allowed (file-level
    # forensic mode), so the message no longer requires both args.
    assert "path" in msg


def test_sqlite_event_store_path_only_constructs_in_file_level_mode(tmp_path):
    # T3 (v1.1): SQLiteEventStore(path) without a run_id is the
    # file-level forensic-handle constructor used by `fork --set` and
    # the override-projector tests. Per-run protocol methods require
    # a subsequent _bind_run_id() (or use the kwargs-form append).
    store = SQLiteEventStore(str(tmp_path / "trace.sqlite"))
    try:
        assert store.run_id is None
        # File-level helpers work without a run_id binding.
        assert store.runs() == []
    finally:
        store.close()


def test_sqlite_event_store_explicit_args_still_construct(tmp_path):
    # The fix is back-compatible: callers passing both args still work.
    store = SQLiteEventStore(str(tmp_path / "trace.sqlite"), run_id="run_test")
    try:
        assert store.run_id == "run_test"
        assert store.count() == 0
    finally:
        store.close()
