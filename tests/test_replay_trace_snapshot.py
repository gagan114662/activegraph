"""Snapshot test for the replay trace format. CONTRACT v0.5 #22 — replay
trace lines are part of the public contract. Don't drift without updating
both the snapshot and the README's `Replay and resume` section.
"""

from __future__ import annotations

import os

from activegraph import (
    FrozenClock,
    Graph,
    IDGen,
    Runtime,
    behavior,
)


SNAPSHOT_PATH = os.path.join(
    os.path.dirname(__file__), "snapshots", "replay_trace.txt"
)


def _run(tmp_path) -> str:
    @behavior(name="planner", on=["goal.created"])
    def planner(event, graph, ctx):
        graph.add_object("task", {"title": "x", "status": "open"})
        graph.add_object("task", {"title": "y", "status": "open"})

    db = str(tmp_path / "snap.db")
    g = Graph(ids=IDGen(), clock=FrozenClock("2026-05-15T10:32:01Z"))
    rt = Runtime(g, persist_to=db, seed=0)
    rt.run_goal("Pin the trace")
    run_id = rt.run_id

    loaded = Runtime.load(db, run_id=run_id)
    return "\n".join(loaded.trace.lines()) + "\n"


def test_replay_trace_matches_snapshot(tmp_path):
    actual = _run(tmp_path)
    if os.environ.get("UPDATE_SNAPSHOTS"):
        os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
        with open(SNAPSHOT_PATH, "w") as f:
            f.write(actual)
    with open(SNAPSHOT_PATH) as f:
        expected = f.read()
    assert actual == expected, (
        "Replay trace drifted. If intentional, run with UPDATE_SNAPSHOTS=1 "
        "and update README's `Replay and resume` section in the same commit."
    )
