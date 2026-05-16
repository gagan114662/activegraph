from activegraph import FrozenClock, Graph, IDGen, Runtime, behavior


def test_view_default_is_full_graph():
    seen = {}

    @behavior(name="capture", on=["goal.created"])
    def capture(event, graph, ctx):
        seen["objects"] = ctx.view.objects()
        seen["events"] = ctx.view.events()

    g = Graph(ids=IDGen(), clock=FrozenClock())
    g.add_object("task", {"title": "pre-existing"})
    runtime = Runtime(g)
    runtime.run_goal("test")

    assert any(o.data.get("title") == "pre-existing" for o in seen["objects"])
    assert len(seen["events"]) >= 1


def test_view_scoped_around_event_with_depth_and_types():
    captured = {}

    @behavior(
        name="critic",
        on=["object.created"],
        where={"object.type": "claim"},
        view={
            "around": "event.payload.object.id",
            "depth": 1,
            "include_types": ["claim", "evidence"],
        },
    )
    def critic(event, graph, ctx):
        captured["objects"] = [o.type for o in ctx.view.objects()]

    g = Graph(ids=IDGen(), clock=FrozenClock())
    runtime = Runtime(g)
    # Pre-load some unrelated state.
    g.add_object("task", {"title": "noise"})
    # Now trigger the critic.
    claim = g.add_object("claim", {"text": "x", "confidence": 0.9})
    runtime.run_until_idle()

    # Only types in include_types appear.
    assert "task" not in captured["objects"]
    assert "claim" in captured["objects"]
