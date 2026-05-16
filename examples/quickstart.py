"""The killer demo. Written before the runtime — defines the v0 public API.

Runs the exact quickstart from README.md and prints the trace.
"""

from activegraph import Graph, Runtime, behavior, relation_behavior


graph = Graph()
runtime = Runtime(graph, budget={"max_events": 200, "max_seconds": 60})


@behavior(name="planner", on=["goal.created"])
def planner(event, graph, ctx):
    goal_text = event.payload["goal"]
    research = graph.add_object("task", {"title": f"Research: {goal_text}", "status": "open"})
    memo = graph.add_object("task", {"title": "Draft memo", "status": "blocked"})
    graph.add_relation(research.id, memo.id, "depends_on")


@behavior(name="researcher", on=["object.created"], where={"object.type": "task"})
def researcher(event, graph, ctx):
    task = event.payload["object"]
    if task["data"]["status"] != "open" or "Research" not in task["data"]["title"]:
        return
    graph.add_object("claim", {
        "text": "Market appears early but growing.",
        "confidence": 0.7,
        "evidence": [],
    })
    graph.emit("task.completed", {"task_id": task["id"]})


@relation_behavior(name="unblock", relation_type="depends_on", on=["task.completed"])
def unblock(relation, event, graph, ctx):
    if event.payload["task_id"] == relation.source:
        graph.patch_object(relation.target, {"status": "open"})


if __name__ == "__main__":
    runtime.run_goal("Evaluate this startup idea")
    runtime.print_trace()
    print()
    runtime.print_graph()
