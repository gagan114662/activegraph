"""v0.8 killer demo: operate a run end-to-end.

This file IS the v0.8 contract — the API shape is locked here first, the
runtime is built backward to make it run. Pairs with `docs/operating.md`.

Story:
  1. Start a run with persistent backing (SQLite by default; Postgres if
     ACTIVEGRAPH_POSTGRES_URL is set).
  2. Configure structured (JSON) logging and Prometheus metrics.
  3. Run partway through with a tight budget; call ``runtime.status()``
     and print the frozen snapshot.
  4. Stop the runtime. Use ``activegraph inspect <url>`` from the shell
     to confirm the snapshot matches.
  5. Use ``activegraph fork <url> --at-event <id> --label ...`` to branch.
  6. Use ``activegraph diff <url> --run-a <id> --run-b <id>`` to compare.
  7. Use ``activegraph export-trace --format jsonl`` to dump the parent
     run as JSON Lines (one event per line) for ingestion by Loki,
     Splunk, BigQuery, etc.
  8. If Postgres is configured, demonstrate
     ``activegraph migrate --from sqlite:///... --to postgres://...``.

Run it:
    python examples/operate_a_run.py

It uses only a few of the framework's smaller surfaces (a planner +
researcher pair, no LLM). The point is the operator loop, not the
behaviors.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from activegraph import (
    Graph,
    Runtime,
    behavior,
    clear_registry,
    relation_behavior,
)
from activegraph.observability import (
    NoOpMetrics,
    PrometheusMetrics,
    configure_logging,
)


# ---------- shared behaviors ----------------------------------------------


def register_behaviors() -> None:
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

    @relation_behavior(name="unblock", relation_type="depends_on", on=["task.completed"])
    def unblock(relation, event, graph, ctx):
        if event.payload["task_id"] == relation.source:
            graph.patch_object(relation.target, {"status": "open"})


# ---------- helpers --------------------------------------------------------


def _sqlite_url(path: str) -> str:
    """sqlite:///absolute/path  — three slashes is the SQLAlchemy convention."""
    return f"sqlite:///{path}"


def _cli(*args: str) -> str:
    """Invoke the activegraph CLI in a subprocess; return stdout."""
    cmd = [sys.executable, "-m", "activegraph", *args]
    print(f"$ {' '.join(cmd[2:])}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    if result.stderr.strip():
        # Surface stderr (warnings, info) but don't fail on it.
        for line in result.stderr.splitlines():
            print(f"  ! {line}")
    return result.stdout


# ---------- the operator loop ---------------------------------------------


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="activegraph-operate-"))
    sqlite_path = work / "diligence.db"
    sqlite_url = _sqlite_url(str(sqlite_path))
    pg_url = os.environ.get("ACTIVEGRAPH_POSTGRES_URL")

    # ---- (2) configure observability ---------------------------------
    # Single call sets up the recommended JSON line format. Operators
    # who already have logging configured can skip this and the framework
    # will attach to whatever they've set up.
    configure_logging(level="INFO", json_output=True)
    metrics = (
        PrometheusMetrics() if PrometheusMetrics.available() else NoOpMetrics()
    )
    print(
        f"\n[setup] logging=json metrics={type(metrics).__name__} "
        f"store={sqlite_url}\n"
    )

    # ---- (1, 3) start, run partway, call status ----------------------
    register_behaviors()
    graph = Graph()
    rt = Runtime(
        graph,
        persist_to=sqlite_url,
        metrics=metrics,
        budget={"max_behavior_calls": 1},  # stops after planner fires
    )
    rt.run_goal("Evaluate this startup idea")
    parent_run_id = rt.run_id
    rt.save_state()

    status = rt.status(recent=10)
    print(f"\n[runtime.status snapshot]")
    print(f"  run_id          = {status.run_id}")
    print(f"  state           = {status.state}")
    print(f"  queue_depth     = {status.queue_depth}")
    print(f"  events_processed= {status.events_processed}")
    print(f"  behaviors       = {[b.name for b in status.registered_behaviors]}")
    print(f"  recent (last 3) = "
          f"{[(e.type, e.id) for e in status.recent_events[-3:]]}")

    # ---- (4) inspect from the shell shows the same thing -------------
    print("\n[cli] inspect from the shell:")
    cli_out = _cli("inspect", sqlite_url, "--run-id", parent_run_id, "--json")
    cli_status = json.loads(cli_out)
    assert cli_status["run_id"] == status.run_id
    assert cli_status["state"] == status.state
    assert cli_status["events_processed"] == status.events_processed
    print(f"  ok — CLI snapshot matches runtime.status() "
          f"({cli_status['events_processed']} events)")

    # ---- (5) fork from the command line ------------------------------
    # Pick the first object.created event as the fork point.
    fork_at = next(
        e.id for e in rt.graph.events if e.type == "object.created"
    )
    print(f"\n[cli] forking at {fork_at}:")
    fork_out = _cli(
        "fork", sqlite_url,
        "--run-id", parent_run_id,
        "--at-event", fork_at,
        "--label", "ops-demo-fork",
        "--json",
    )
    fork_info = json.loads(fork_out)
    fork_run_id = fork_info["new_run_id"]
    print(f"  forked -> {fork_run_id} "
          f"({fork_info['events_copied']} events copied)")

    # Run the fork to completion via the library (CLI doesn't run loops).
    register_behaviors()
    fork_rt = Runtime.load(sqlite_url, run_id=fork_run_id, metrics=metrics)
    fork_rt.run_until_idle()
    fork_rt.save_state()

    # Run the parent to completion too, so the diff is meaningful.
    register_behaviors()
    parent_rt = Runtime.load(sqlite_url, run_id=parent_run_id, metrics=metrics)
    parent_rt.run_until_idle()
    parent_rt.save_state()

    # ---- (6) diff from the shell -------------------------------------
    print(f"\n[cli] diff parent vs fork:")
    diff_out = _cli(
        "diff", sqlite_url,
        "--run-a", parent_run_id,
        "--run-b", fork_run_id,
        "--json",
    )
    diff_info = json.loads(diff_out)
    print(f"  shared events:       {diff_info['shared_events']}")
    print(f"  parent-only events:  {diff_info['parent_only_events']}")
    print(f"  fork-only events:    {diff_info['fork_only_events']}")
    print(f"  divergent objects:   {diff_info['divergent_objects']}")

    # ---- (7) export the trace as JSONL for log aggregation -----------
    export_path = work / "parent.jsonl"
    print(f"\n[cli] export trace as JSONL to {export_path}:")
    _cli(
        "export-trace", sqlite_url,
        "--run-id", parent_run_id,
        "--format", "jsonl",
        "-o", str(export_path),
    )
    n_lines = sum(1 for _ in open(export_path))
    print(f"  wrote {n_lines} JSONL lines "
          f"(pipe this into Loki / BigQuery / Splunk)")

    # ---- (8) migrate sqlite -> postgres (if configured) --------------
    if pg_url:
        print(f"\n[cli] migrate {sqlite_url} -> {pg_url}:")
        mig_out = _cli(
            "migrate",
            "--from", sqlite_url,
            "--to", pg_url,
            "--json",
        )
        report = json.loads(mig_out)
        for r in report["runs"]:
            print(
                f"  {r['status']:7s} run={r['run_id']} "
                f"events={r['events_migrated']}"
                + (f" error={r['error']}" if r.get("error") else "")
            )
    else:
        print("\n[migrate] skipped — set ACTIVEGRAPH_POSTGRES_URL to demo")

    print(f"\n[done] artifacts in {work}")
    return 0


if __name__ == "__main__":
    # Quiet the JSON log stream from polluting stdout during the demo.
    logging.getLogger("activegraph").setLevel(logging.WARNING)
    raise SystemExit(main())
