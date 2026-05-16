"""Snapshot test for the quickstart trace. CONTRACT #18 — trace format is
contract; this test is the canary for any drift.

If you change the trace format on purpose, update the snapshot in the same
commit and update the README's expected trace block.
"""

import os

from activegraph import (
    FrozenClock,
    Graph,
    IDGen,
    Runtime,
    behavior,
    relation_behavior,
)


SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "snapshots", "quickstart_trace.txt")


def _run_quickstart() -> str:
    @behavior(name="planner", on=["goal.created"])
    def planner(event, graph, ctx):
        goal_text = event.payload["goal"]
        research = graph.add_object(
            "task", {"title": f"Research: {goal_text}", "status": "open"}
        )
        memo = graph.add_object("task", {"title": "Draft memo", "status": "blocked"})
        graph.add_relation(research.id, memo.id, "depends_on")

    @behavior(name="researcher", on=["object.created"], where={"object.type": "task"})
    def researcher(event, graph, ctx):
        task = event.payload["object"]
        if task["data"]["status"] != "open" or "Research" not in task["data"]["title"]:
            return
        graph.add_object(
            "claim",
            {
                "text": "Market appears early but growing.",
                "confidence": 0.7,
                "evidence": [],
            },
        )
        graph.emit("task.completed", {"task_id": task["id"]})

    @relation_behavior(
        name="unblock", relation_type="depends_on", on=["task.completed"]
    )
    def unblock(relation, event, graph, ctx):
        if event.payload["task_id"] == relation.source:
            graph.patch_object(relation.target, {"status": "open"})

    g = Graph(ids=IDGen(), clock=FrozenClock("2026-05-15T10:32:01Z"))
    runtime = Runtime(g, budget={"max_events": 200, "max_seconds": 60}, seed=0)
    runtime.run_goal("Evaluate this startup idea")
    return "\n".join(runtime.trace.lines()) + "\n"


def test_quickstart_trace_matches_snapshot():
    actual = _run_quickstart()
    if os.environ.get("UPDATE_SNAPSHOTS"):
        os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
        with open(SNAPSHOT_PATH, "w") as f:
            f.write(actual)
    with open(SNAPSHOT_PATH) as f:
        expected = f.read()
    assert actual == expected, (
        "Trace drifted. If intentional, run with UPDATE_SNAPSHOTS=1 "
        "and update README's expected trace block in the same commit."
    )
