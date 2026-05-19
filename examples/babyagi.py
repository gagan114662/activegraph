"""BabyAGI's autonomous agent loop, rebuilt on Active Graph.

The original BabyAGI (Nakajima, 2023) was a while-true loop with three
steps: execute the current task, summarize against the objective,
generate follow-up tasks. State lived in a global list.

Here each step is a reactive behavior over a shared graph. The loop is
event propagation; the state is the graph.

    original step             becomes                     reacts to
    -----------------         -----------------           --------------
    seed the first task       @behavior initializer       goal.created
    execute current task      @llm_behavior executor      object.created
                                                          (type=task)
    generate follow-ups       @llm_behavior task_creator  task.executed

Each step is a subscription, not a function call, so the loop runs as
long as new task objects keep landing on the graph. The trace records
every mutation; the frame carries the objective into every LLM call.

Run it:

    export ANTHROPIC_API_KEY='your-key-here'
    python examples/babyagi.py "Plan a 3-day intro to Rust"
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from activegraph import (
    Frame,
    Graph,
    Runtime,
    behavior,
    clear_registry,
    llm_behavior,
    register,
)
from activegraph.llm import AnthropicProvider


# Edit to taste — these ride along on every LLM call as frame constraints.
DEFAULT_CONSTRAINTS = [
    "Be specific and actionable — avoid vague generalities.",
    "Build incrementally on previous results rather than repeating them.",
]


class TaskResult(BaseModel):
    result: str = Field(description="A detailed answer to the task, 2-5 concrete sentences.")


class NewTasks(BaseModel):
    tasks: list[str] = Field(
        description=(
            "0-4 follow-up tasks, each an imperative sentence. Empty list "
            "only if the objective is fully accomplished."
        )
    )


@behavior(name="initializer", on=["goal.created"])
def initializer(event, graph, ctx):
    # Bootstraps the loop: a single seed task so executor has something to fire on.
    goal = event.payload.get("goal", "")
    graph.add_object("task", {"title": f"Plan the first step toward: {goal}", "status": "pending"})


@llm_behavior(
    name="executor",
    on=["object.created"],
    where={"object.type": "task"},
    description=(
        "You are the EXECUTION agent in a BabyAGI loop. Carry out the task "
        "concretely. Do NOT plan further steps — another behavior handles that."
    ),
    model="claude-haiku-4-5",
    output_schema=TaskResult,
    creates=["result"],
)
def executor(event, graph, ctx, llm_output: TaskResult):
    # Reacts to every newly-created task. No central scheduler picks what
    # runs next — the graph itself is the queue, and the event log is the order.
    task = event.payload["object"]
    if task["data"].get("status") != "pending":
        return
    graph.patch_object(task["id"], {"status": "completed"})
    result = graph.add_object("result", {"task_id": task["id"], "content": llm_output.result})
    graph.add_relation(task["id"], result.id, "produced")
    graph.emit("task.executed", {"task_id": task["id"], "result": llm_output.result})


@llm_behavior(
    name="task_creator",
    on=["task.executed"],
    description=(
        "You are the TASK-CREATION agent in a BabyAGI loop. Given the last "
        "result and the overall objective, propose 0-4 follow-ups. Return "
        "an empty list ONLY when the objective is fully accomplished."
    ),
    model="claude-haiku-4-5",
    output_schema=NewTasks,
    creates=["task"],
)
def task_creator(event, graph, ctx, llm_output: NewTasks):
    # Each new task fires `executor` again — that propagation IS the loop.
    # Returning an empty list is how it terminates without a while-condition.
    for title in llm_output.tasks:
        if title.strip():
            graph.add_object("task", {"title": title.strip(), "status": "pending"})


def run_babyagi(
    objective: str,
    *,
    constraints: list[str] | None = None,
    max_events: int = 100,
    max_seconds: int = 60,
) -> str:
    # Decorators register on import; clear+re-register makes this function
    # safe to call multiple times — see docs/cookbook/multi-run-scripts.md.
    clear_registry()
    for b in (initializer, executor, task_creator):
        register(b)

    os.makedirs("traces", exist_ok=True)
    trace_path = f"traces/babyagi-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.sqlite"
    runtime = Runtime(
        Graph(),
        frame=Frame(goal=objective, constraints=list(constraints or DEFAULT_CONSTRAINTS)),
        llm_provider=AnthropicProvider(),
        budget={"max_events": max_events, "max_seconds": max_seconds},
        persist_to=trace_path,
    )
    runtime.run_goal(objective)
    return trace_path


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY environment variable not set. Set it with:\n"
            "  export ANTHROPIC_API_KEY='your-key-here'",
            file=sys.stderr,
        )
        return 1
    objective = sys.argv[1] if len(sys.argv) > 1 else "Plan a 3-day intro to Rust programming"
    trace_path = run_babyagi(objective)
    print(f"\ntrace: {trace_path}")
    print(f"inspect with: activegraph inspect {trace_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
