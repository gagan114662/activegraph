"""Prompt assembler + view serializer (CONTRACT v0.6 #6, #13, #20).

These tests pin the bytes that go to the model. The view-block format
and the system prompt structure are part of the public contract — if
either drifts, this suite breaks first.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from activegraph import Frame, Graph
from activegraph.core.event import Event
from activegraph.core.view import View
from activegraph.llm.prompt import (
    AssembledPrompt,
    assemble_prompt,
    build_instruction,
    build_system_prompt,
    schema_to_json,
    serialize_view,
)


class _Out(BaseModel):
    n: int


# ---------- view serializer -------------------------------------------------


def _populated_view(graph: Graph) -> View:
    d1 = graph.add_object("document", {"title": "Doc one", "body": "body"})
    d2 = graph.add_object("document", {"title": "Doc two", "body": "body"})
    graph.add_relation(d1.id, d2.id, "refers_to")
    return View(
        objects=graph.all_objects(),
        relations=graph.all_relations(),
        events=graph.events,
    )


def test_view_serializer_empty():
    v = View(objects=[], relations=[], events=[])
    out = serialize_view(v)
    assert out == (
        "## Graph context\n"
        "\n"
        "### Objects\n"
        "- (none)\n"
        "\n"
        "### Relations\n"
        "- (none)\n"
        "\n"
        "### Recent events\n"
        "- (none)"
    )


def test_view_serializer_populated_format_is_locked():
    g = Graph()
    v = _populated_view(g)
    out = serialize_view(v, around="document#1", depth=2)
    # Pin the human-readable shape; this is the documented format.
    assert "## Graph context (depth=2, around=document#1)" in out
    assert "### Objects" in out
    assert "- document#1 (document):" in out
    assert "- document#2 (document):" in out
    assert "### Relations" in out
    assert "- document#1 --refers_to--> document#2" in out
    assert "### Recent events" in out
    assert " object.created document#1" in out


def test_view_serializer_object_data_is_canonical_json():
    g = Graph()
    obj = g.add_object("note", {"z": 1, "a": 2})
    v = View(objects=[obj], relations=[], events=[])
    out = serialize_view(v)
    # Stable key order matters for prompt hash stability.
    assert '"a": 2' in out
    assert out.index('"a"') < out.index('"z"')


# ---------- system prompt ---------------------------------------------------


def test_system_prompt_omits_absent_sections():
    sp = build_system_prompt(
        behavior_name="x",
        description="",
        frame=None,
        output_schema_name=None,
        output_schema_json=None,
    )
    assert "Mission:" not in sp
    assert "Constraints:" not in sp
    assert "Role:" not in sp
    assert "Respond with JSON" not in sp
    assert 'behavior named "x"' in sp


def test_system_prompt_orders_blocks_frame_then_constraints_then_role_then_schema():
    sp = build_system_prompt(
        behavior_name="extractor",
        description="Pull facts.",
        frame=Frame(goal="Audit Q3", constraints=["cite spans", "no hallucinations"]),
        output_schema_name="ClaimList",
        output_schema_json={"type": "object"},
    )
    mission_i = sp.index("Mission:")
    constraints_i = sp.index("Constraints:")
    role_i = sp.index("Role:")
    schema_i = sp.index("Respond with JSON")
    assert mission_i < constraints_i < role_i < schema_i


# ---------- task instruction -----------------------------------------------


def test_instruction_uses_schema_and_creates():
    s = build_instruction(creates=["claim"], output_schema_name="ClaimList")
    assert "ClaimList" in s
    assert "claim" in s


def test_instruction_schema_only():
    assert "ClaimList" in build_instruction(creates=[], output_schema_name="ClaimList")


def test_instruction_creates_only():
    assert "claim" in build_instruction(creates=["claim"], output_schema_name=None)


def test_instruction_fallback():
    assert "what should happen" in build_instruction(
        creates=[], output_schema_name=None
    )


# ---------- top-level assembly + hash stability ----------------------------


def _bare_event(g: Graph) -> Event:
    return g.add_object("document", {"title": "T", "body": "B"}).provenance.get(
        "_unused_just_to_get_an_event"
    ) or next(
        e for e in g.events if e.type == "object.created"
    )


def test_assemble_prompt_returns_sections_and_hash():
    g = Graph()
    ev = _bare_event(g)
    v = View(objects=g.all_objects(), relations=[], events=g.events)
    p = assemble_prompt(
        behavior_name="x",
        description="d",
        model="claude-sonnet-4-5",
        output_schema=_Out,
        creates=["x"],
        view=v,
        event=ev,
        frame=None,
        around="document#1",
        depth=1,
        max_tokens=512,
        temperature=0.7,
        top_p=1.0,
        deterministic=False,
    )
    assert isinstance(p, AssembledPrompt)
    assert set(p.sections.keys()) == {
        "system",
        "view",
        "event",
        "instruction",
        "user",
    }
    assert len(p.hash()) == 64  # sha256 hex


def test_hash_stable_across_identical_inputs():
    g1 = Graph()
    ev1 = _bare_event(g1)
    v1 = View(objects=g1.all_objects(), relations=[], events=g1.events)
    g2 = Graph()
    ev2 = _bare_event(g2)
    v2 = View(objects=g2.all_objects(), relations=[], events=g2.events)
    kwargs = dict(
        behavior_name="x",
        description="d",
        model="claude-sonnet-4-5",
        output_schema=_Out,
        creates=["x"],
        frame=None,
        around="document#1",
        depth=1,
        max_tokens=512,
        temperature=0.0,
        top_p=1.0,
        deterministic=True,
    )
    p1 = assemble_prompt(view=v1, event=ev1, **kwargs)
    p2 = assemble_prompt(view=v2, event=ev2, **kwargs)
    assert p1.hash() == p2.hash()


def test_hash_changes_when_model_changes():
    g = Graph()
    ev = _bare_event(g)
    v = View(objects=g.all_objects(), relations=[], events=g.events)
    base = dict(
        behavior_name="x",
        description="d",
        output_schema=_Out,
        creates=["x"],
        view=v,
        event=ev,
        frame=None,
        around=None,
        depth=None,
        max_tokens=512,
        temperature=0.0,
        top_p=1.0,
        deterministic=True,
    )
    h_sonnet = assemble_prompt(model="claude-sonnet-4-5", **base).hash()
    h_opus = assemble_prompt(model="claude-opus-4-7", **base).hash()
    assert h_sonnet != h_opus


def test_deterministic_overrides_temperature_and_top_p():
    g = Graph()
    ev = _bare_event(g)
    v = View(objects=g.all_objects(), relations=[], events=g.events)
    p = assemble_prompt(
        behavior_name="x",
        description="d",
        model="claude-sonnet-4-5",
        output_schema=None,
        creates=[],
        view=v,
        event=ev,
        frame=None,
        around=None,
        depth=None,
        max_tokens=512,
        temperature=0.9,
        top_p=0.5,
        deterministic=True,
    )
    assert p.temperature == 0.0
    assert p.top_p == 1.0


def test_prompt_template_swap_uses_placeholders():
    g = Graph()
    ev = _bare_event(g)
    v = View(objects=g.all_objects(), relations=[], events=g.events)
    p = assemble_prompt(
        behavior_name="x",
        description="d",
        model="m",
        output_schema=None,
        creates=[],
        view=v,
        event=ev,
        frame=None,
        around=None,
        depth=None,
        max_tokens=64,
        temperature=0.0,
        top_p=1.0,
        deterministic=True,
        prompt_template=">>> {instruction} ||| view={view} ||| event={event}",
    )
    user = p.messages[0].content
    assert user.startswith(">>>")
    assert "||| view=## Graph context" in user
    assert "||| event=" in user


def test_prompt_template_bad_placeholder_raises():
    g = Graph()
    ev = _bare_event(g)
    v = View(objects=g.all_objects(), relations=[], events=g.events)
    with pytest.raises(ValueError, match="unknown placeholder"):
        assemble_prompt(
            behavior_name="x",
            description="",
            model="m",
            output_schema=None,
            creates=[],
            view=v,
            event=ev,
            frame=None,
            around=None,
            depth=None,
            max_tokens=64,
            temperature=0.0,
            top_p=1.0,
            deterministic=True,
            prompt_template="{notarealkey}",
        )


# ---------- volatile-field stripping ---------------------------------------


def test_event_serialization_strips_provenance_and_run_id():
    """The triggering event's payload contains an embedded object with
    provenance that carries `run_id` and `timestamp`. Those vary across
    runs/forks; stripping them is what lets the cache lookup succeed
    after a fork.
    """

    g = Graph()
    g.add_object("doc", {"title": "t"})
    ev = next(e for e in g.events if e.type == "object.created")
    v = View(objects=g.all_objects(), relations=[], events=g.events)
    p = assemble_prompt(
        behavior_name="x",
        description="d",
        model="m",
        output_schema=None,
        creates=[],
        view=v,
        event=ev,
        frame=None,
        around=None,
        depth=None,
        max_tokens=64,
        temperature=0.0,
        top_p=1.0,
        deterministic=True,
    )
    user = p.messages[0].content
    assert "run_id" not in user
    assert "provenance" not in user


# ---------- schema_to_json -------------------------------------------------


def test_schema_to_json_handles_pydantic_v2():
    out = schema_to_json(_Out)
    assert out is not None
    assert "properties" in out
    assert "n" in out["properties"]


def test_schema_to_json_handles_none():
    assert schema_to_json(None) is None
