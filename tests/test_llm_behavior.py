"""@llm_behavior end-to-end (CONTRACT v0.6 #1, #2, #15).

Decorator + runtime path against a scripted provider. Asserts the
handler runs with parsed structured output, llm.requested /
llm.responded events land in the log in the right order, provenance
carries llm_request_event_id, and the behavior.completed counters
reflect the handler's mutations.
"""

from __future__ import annotations

from activegraph import (
    Graph,
    Runtime,
    behavior,
    llm_behavior,
)

from tests._llm_helpers import Claim, ClaimList, ScriptedProvider


def _scripted(claim_text: str = "Sample claim", confidence: float = 0.9):
    return ScriptedProvider(
        respond_fn=lambda messages, schema: ClaimList(
            claims=[Claim(text=claim_text, confidence=confidence)]
        )
    )


def test_llm_behavior_invokes_handler_with_parsed_output():
    provider = _scripted()

    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("document", {"title": "T", "body": "B"})

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        where={"object.type": "document"},
        description="Extract claims.",
        output_schema=ClaimList,
        creates=["claim"],
        view={"around": "event.payload.object.id", "depth": 1},
    )
    def extractor(event, graph, ctx, llm_output):
        assert isinstance(llm_output, ClaimList)
        for c in llm_output.claims:
            graph.add_object("claim", {"text": c.text, "confidence": c.confidence})

    g = Graph()
    rt = Runtime(g, llm_provider=provider)
    rt.run_goal("Run extractor")

    types = [e.type for e in g.events]
    # Lifecycle ordering:
    assert "llm.requested" in types
    assert "llm.responded" in types
    req_i = types.index("llm.requested")
    resp_i = types.index("llm.responded")
    assert req_i < resp_i
    # claim object was created
    claims = [o for o in g.all_objects() if o.type == "claim"]
    assert len(claims) == 1
    assert claims[0].data["text"] == "Sample claim"


def test_llm_events_carry_prompt_hash_and_model():
    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("document", {"title": "T", "body": "B"})

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        where={"object.type": "document"},
        description="x",
        output_schema=ClaimList,
        view={"around": "event.payload.object.id", "depth": 1},
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    provider = _scripted()
    g = Graph()
    Runtime(g, llm_provider=provider).run_goal("g")

    req = next(e for e in g.events if e.type == "llm.requested")
    resp = next(e for e in g.events if e.type == "llm.responded")
    assert req.payload["model"] == "claude-sonnet-4-5"
    assert len(req.payload["prompt_hash"]) == 64
    assert resp.payload["prompt_hash"] == req.payload["prompt_hash"]
    assert resp.caused_by == req.id  # llm.responded.caused_by = llm.requested.id
    assert req.caused_by is not None  # caused by the triggering object.created


def test_objects_in_handler_have_llm_request_event_id_in_provenance():
    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("document", {"title": "T", "body": "B"})

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        where={"object.type": "document"},
        description="x",
        output_schema=ClaimList,
        view={"around": "event.payload.object.id", "depth": 1},
    )
    def extractor(event, graph, ctx, llm_output):
        for c in llm_output.claims:
            graph.add_object("claim", {"text": c.text, "confidence": c.confidence})

    provider = _scripted()
    g = Graph()
    Runtime(g, llm_provider=provider).run_goal("g")

    req = next(e for e in g.events if e.type == "llm.requested")
    claim = next(o for o in g.all_objects() if o.type == "claim")
    assert claim.provenance.get("llm_request_event_id") == req.id


def test_behavior_completed_counts_reflect_handler_mutations():
    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("document", {"title": "T", "body": "B"})

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        where={"object.type": "document"},
        description="x",
        output_schema=ClaimList,
        view={"around": "event.payload.object.id", "depth": 1},
    )
    def extractor(event, graph, ctx, llm_output):
        for c in llm_output.claims:
            cobj = graph.add_object(
                "claim", {"text": c.text, "confidence": c.confidence}
            )
            graph.add_relation(cobj.id, event.payload["object"]["id"], "supports")

    provider = ScriptedProvider(
        respond_fn=lambda m, s: ClaimList(
            claims=[
                Claim(text="A", confidence=0.9),
                Claim(text="B", confidence=0.8),
            ]
        )
    )
    g = Graph()
    Runtime(g, llm_provider=provider).run_goal("g")
    completed = next(
        e
        for e in g.events
        if e.type == "behavior.completed" and e.payload["behavior"] == "extractor"
    )
    assert completed.payload["objects_created"] == 2
    assert completed.payload["relations_created"] == 2


def test_provider_call_log_records_one_call_per_document():
    provider = _scripted()

    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        for i in range(3):
            graph.add_object("document", {"title": f"d{i}", "body": "x"})

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        where={"object.type": "document"},
        description="x",
        output_schema=ClaimList,
        view={"around": "event.payload.object.id", "depth": 1},
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    g = Graph()
    Runtime(g, llm_provider=provider).run_goal("g")
    assert len(provider.call_log) == 3


def test_handler_4th_arg_is_pydantic_instance_not_dict():
    captured: list = []

    @behavior(name="seed", on=["goal.created"])
    def seed(event, graph, ctx):
        graph.add_object("document", {"title": "T", "body": "B"})

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        where={"object.type": "document"},
        description="x",
        output_schema=ClaimList,
        view={"around": "event.payload.object.id", "depth": 1},
    )
    def extractor(event, graph, ctx, llm_output):
        captured.append(type(llm_output).__name__)

    g = Graph()
    Runtime(g, llm_provider=_scripted()).run_goal("g")
    assert captured == ["ClaimList"]


def test_build_prompt_is_callable_without_api_call():
    """CONTRACT v0.6 #20: developers can inspect the exact prompt that
    would be sent without invoking the provider."""

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        description="role",
        output_schema=ClaimList,
        creates=["claim"],
        view={"around": "event.payload.object.id", "depth": 1},
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    g = Graph()
    obj = g.add_object("document", {"title": "T", "body": "B"})
    ev = next(e for e in g.events if e.type == "object.created")
    prompt = extractor.build_prompt(ev, g)
    assert prompt.model == "claude-sonnet-4-5"
    assert "ClaimList" in prompt.system
    assert "## Graph context" in prompt.messages[0].content
    assert prompt.hash() == prompt.hash()  # stable across calls
