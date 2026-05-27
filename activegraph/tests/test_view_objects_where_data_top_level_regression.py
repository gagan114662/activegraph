"""Regression: View.objects(where=) honors top-level data field keys.

Bug source: activegraph/activegraph/core/graph.py:253
  The Graph.objects docstring promises:
    "v1.0.3 #1: the canonical query API on Graph, mirroring
     View.objects(type=...) so call sites read the same inside
     and outside behaviors."

Correct behavior: the same `where={"status": "open"}` filter must select
the same objects through View.objects as through Graph.objects, so a
behavior reading from ctx.view sees its world the same way the caller
sees it through graph.objects.

Wrong (current) behavior: Graph.objects builds its `where` root with
`**obj.data` spread at top level (graph.py:_eval_where_on_object), but
View.objects routes through view._object_root which only exposes the
nested {"data": {...}} branch. As a result, the unprefixed form
matches in Graph but never matches in View — call sites do NOT read
the same inside and outside behaviors.
"""

from __future__ import annotations

from activegraph.core.graph import Graph
from activegraph.core.view import View


def test_view_objects_where_top_level_data_mirrors_graph_objects() -> None:
    g = Graph()
    g.add_object("task", {"status": "open"})
    g.add_object("task", {"status": "done"})

    graph_matches = g.objects(where={"status": "open"})
    assert len(graph_matches) == 1
    assert graph_matches[0].data["status"] == "open"

    view = View(objects=g.all_objects(), relations=[], events=[])
    view_matches = view.objects(where={"status": "open"})

    assert [o.id for o in view_matches] == [o.id for o in graph_matches], (
        "View.objects(where=) must mirror Graph.objects(where=) per the "
        "Graph.objects docstring promise (graph.py:253)."
    )
