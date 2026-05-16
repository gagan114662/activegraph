"""End-to-end test of examples/resume_and_fork.py — the v0.5 contract example.

If this drifts from the README's `Replay and resume` story, fix one or the
other in the same commit. CONTRACT v0.5 #20 — the example is the contract.

Two layers:
  1. subprocess: runs the file as a user would. Catches import / CLI
     packaging issues that a pure-Python test can miss.
  2. inline: walks the same flow with two separately constructed Runtime
     instances (simulating two processes). Easier to debug, and lets us
     assert intermediate state — what the budget pause produced, what the
     fork diverged on, what the diff partitions look like.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from activegraph import (
    Graph,
    Runtime,
    behavior,
    clear_registry,
    relation_behavior,
)


def test_resume_and_fork_example_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).parent.parent)
    # The example pins DB to /tmp/...; we tolerate that.
    result = subprocess.run(
        [sys.executable, "examples/resume_and_fork.py"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"example crashed:\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    out = result.stdout
    # Sanity checks on the demo flow.
    assert "[step 1] paused" in out
    assert "[step 2] loaded" in out
    assert "[step 2] resumed to idle" in out
    assert "[step 3] forked" in out
    assert "diff: parent vs fork" in out
    assert "shared events:" in out
    assert "fork-only events:" in out


def _register_quickstart_behaviors() -> None:
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
            {"text": "Market appears early but growing.", "confidence": 0.7, "evidence": []},
        )
        graph.emit("task.completed", {"task_id": task["id"]})

    @relation_behavior(name="unblock", relation_type="depends_on", on=["task.completed"])
    def unblock(rel, event, graph, ctx):
        if event.payload["task_id"] == rel.source:
            graph.patch_object(rel.target, {"status": "open"})


def test_resume_and_fork_flow_inline(tmp_path):
    """Re-implement the demo as the user would, in-test, with intermediate
    assertions at each step boundary. Two separately constructed Runtime
    instances stand in for two processes."""
    db = str(tmp_path / "demo.db")

    # --- step 1: start with a tight budget, save partway through. ---
    _register_quickstart_behaviors()
    paused = Runtime(Graph(), persist_to=db, budget={"max_behavior_calls": 1})
    paused.run_goal("Evaluate this startup idea")
    paused.save_state()
    paused_run_id = paused.run_id
    # The run is paused, not done: no claim yet because the researcher
    # never fired before the budget ran out.
    assert not any(o.type == "claim" for o in paused.graph.all_objects())

    # --- step 2: fresh Runtime, load, finish. ---
    _register_quickstart_behaviors()  # re-register, as a fresh process would
    resumed = Runtime.load(db, run_id=paused_run_id)
    # The full history replayed.
    assert len(resumed.graph.replayed_ids) == len(paused.graph.events)
    resumed.run_until_idle()
    resumed.save_state()
    # Now the researcher has fired; the unblock has patched task#2.
    types_now = {o.type for o in resumed.graph.all_objects()}
    assert "claim" in types_now
    task_2 = resumed.graph.get_object("task#2")
    assert task_2 is not None and task_2.data["status"] == "open"

    # --- step 3: fork at the first claim, inject a counter-hypothesis. ---
    fork_target = next(
        e.id
        for e in resumed.graph.events
        if e.type == "object.created"
        and e.payload["object"]["type"] == "claim"
    )
    fork = resumed.fork(at_event=fork_target, label="alternative-thesis")
    assert fork.run_id != resumed.run_id
    fork.graph.add_object(
        "claim",
        {"text": "Counter-hypothesis: market is saturated.", "confidence": 0.6},
    )
    fork.run_until_idle()
    fork.save_state()

    # The fork's branch point is recorded.
    from activegraph import SQLiteEventStore

    runs = {r.run_id: r for r in SQLiteEventStore.list_runs(db)}
    assert runs[fork.run_id].parent_run_id == resumed.run_id
    assert runs[fork.run_id].forked_at_event_id == fork_target
    assert runs[fork.run_id].label == "alternative-thesis"

    # --- step 4: diff. ---
    diff = resumed.diff(fork)
    # Counter-hypothesis exists only on the fork.
    fork_only_object_ids = {d.id for d in diff.divergent_objects if d.in_parent is None}
    assert any(oid.startswith("claim#") for oid in fork_only_object_ids)
    # task#2 differs: parent patched it; fork didn't.
    differing = {d.id for d in diff.divergent_objects if d.in_parent and d.in_fork}
    assert "task#2" in differing
    # Event partition is non-trivial in both directions.
    assert diff.shared_events, "expected some shared prefix events"
    assert diff.fork_only_events, "expected at least one fork-only event"
