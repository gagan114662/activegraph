"""v0.5 killer demo: stop, save, reload in a fresh process, resume, fork, diff.

This file is the v0.5 contract. The API shape is locked here first; the
runtime is built backward to make it run. Per CONTRACT #20.

Story:
  1. Start a run with a tiny budget so it stops partway.
  2. Save state (persisted continuously to SQLite).
  3. Re-open in a fresh Runtime (as if a new process), continue to idle.
  4. Pick an interesting midpoint event and fork — get a new run that
     branched off the parent's history.
  5. Inject a counter-hypothesis into the fork; let it run to completion.
  6. Diff parent vs fork. Print divergent objects, relations, and which
     event ranges belong to which side.

Run it: `python examples/resume_and_fork.py`
Output: trace lines for both runs and a diff summary at the end.
"""

from __future__ import annotations

import os

from activegraph import (
    Graph,
    Runtime,
    behavior,
    clear_registry,
    relation_behavior,
)


DB = "/tmp/activegraph_resume_and_fork.db"


# ---------- behaviors (the same ones a fresh process would re-register) ----


def _register_behaviors() -> None:
    clear_registry()

    @behavior(name="planner", on=["goal.created"])
    def planner(event, graph, ctx):
        goal_text = event.payload["goal"]
        research = graph.add_object(
            "task", {"title": f"Research: {goal_text}", "status": "open"}
        )
        memo = graph.add_object(
            "task", {"title": "Draft memo", "status": "blocked"}
        )
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


# ---------- the demo flow ----------


def step_1_start_and_pause() -> str:
    """Run with a tight budget so we stop mid-flow, then save."""
    if os.path.exists(DB):
        os.remove(DB)
    _register_behaviors()

    graph = Graph()
    rt = Runtime(graph, persist_to=DB, budget={"max_behavior_calls": 1})
    rt.run_goal("Evaluate this startup idea")
    # Budget exhausted after planner runs. Persisted continuously, but we
    # call save_state explicitly to make the seam visible.
    rt.save_state()
    print(f"[step 1] paused run {rt.run_id} after {len(graph.events)} events")
    return rt.run_id


def step_2_resume(run_id: str) -> Runtime:
    """Fresh process: re-register behaviors, load, continue to idle."""
    _register_behaviors()  # behaviors are code, not state — re-register them

    rt = Runtime.load(DB, run_id=run_id)
    print(f"[step 2] loaded {rt.run_id} — {len(rt.graph.events)} events replayed")
    rt.run_until_idle()
    rt.save_state()
    print(
        f"[step 2] resumed to idle — {len(rt.graph.all_objects())} objects, "
        f"{len(rt.graph.all_relations())} relations"
    )
    return rt


def step_3_fork(parent: Runtime) -> Runtime:
    """Fork at the first claim and inject a counter-hypothesis."""
    target = None
    for e in parent.graph.events:
        if (
            e.type == "object.created"
            and e.payload.get("object", {}).get("type") == "claim"
        ):
            target = e.id
            break
    assert target is not None, "expected a claim to fork at"

    fork = parent.fork(at_event=target, label="alternative-thesis")
    fork.graph.add_object(
        "claim",
        {
            "text": "Counter-hypothesis: market is saturated.",
            "confidence": 0.6,
            "evidence": [],
        },
    )
    fork.run_until_idle()
    fork.save_state()
    print(
        f"[step 3] forked at {target} -> {fork.run_id} "
        f"({len(fork.graph.all_objects())} objects)"
    )
    return fork


def step_4_diff(parent: Runtime, fork: Runtime) -> None:
    diff = parent.diff(fork)
    print("\n=== diff: parent vs fork ===")
    print(f"  shared events:       {len(diff.shared_events)}")
    print(f"  parent-only events:  {len(diff.parent_only_events)}")
    print(f"  fork-only events:    {len(diff.fork_only_events)}")
    print(f"  divergent objects:   {len(diff.divergent_objects)}")
    for obj in diff.divergent_objects:
        print(f"    - {obj.summary()}")
    print(f"  divergent relations: {len(diff.divergent_relations)}")
    for rel in diff.divergent_relations:
        print(f"    - {rel.summary()}")


if __name__ == "__main__":
    run_id = step_1_start_and_pause()
    parent = step_2_resume(run_id)
    fork = step_3_fork(parent)
    step_4_diff(parent, fork)
