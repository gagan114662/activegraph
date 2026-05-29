"""T7 HARD repeat 017 — docstring↔code drift regression test.

`Runtime.status()` promises a tail-slice-only cost:

    "Cheap to call. No graph traversal beyond a tail-slice of the
     event log."                                     (runtime.py docstring)

and the `RuntimeStatus` module echoes it:

    "Cheap to call (no graph traversal, no event log scan) ..."
                                                      (observability/status.py:4)

A PRIOR drift run (t7_repeat_hard_015) fixed the *state-derivation* loop so it
no longer walks the whole log via ``reversed(self.graph.events)``; that loop is
now bounded by ``_STATUS_STATE_TAIL`` via ``_tail_events(...)``.

But a SECOND, distinct violation of the same documented contract survives:
``status()`` still builds ``recent_events`` (and the ``events_processed``
count) from ``self.graph.events`` — a property that does ``list(self._events)``,
i.e. a FULL O(len(log)) copy of the entire event log — and only THEN slices the
tail:

    events = self.graph.events        # full-log copy, O(len(log))
    tail = events[-recent:] ...       # tail-slice taken AFTER the full copy

Copying the whole log to extract its last ``recent`` events is exactly the
"event-log scan" / "graph traversal beyond a tail-slice" both docstrings say
``status()`` does not do. The cost is O(len(log)), not O(recent), so a
snapshot of a 1000-event run is ~10x more expensive than a 100-event run —
contradicting the "cheap to call" / "tail-slice only" guarantee.

The run-015 regression test does NOT catch this: it counts elements *iterated*
(via ``__iter__`` / ``__reversed__``), and slicing the full copy never iterates
it. This test measures the size of the COPY the ``events`` property is asked to
materialize, which is what the documented contract actually bounds.

These tests assert the DOCUMENTED behavior: ``status(recent=k)`` must not
materialize a copy of the whole log; the work it does on the event log must be
bounded by ``recent``, independent of total log length.
"""

from __future__ import annotations

from activegraph.core.graph import Graph
from activegraph.runtime.runtime import Runtime


class _CopyCountingGraph(Graph):
    """Graph that records the size of every full ``events`` copy handed out.

    ``Runtime.status()`` reads ``self.graph.events``; the base ``Graph.events``
    property returns ``list(self._events)`` — a full copy. We record the length
    of each such copy so a test can assert ``status()`` does not materialize a
    copy on the order of the whole log.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.events_copy_sizes: list[int] = []

    @property
    def events(self):
        snapshot = list(self._events)
        self.events_copy_sizes.append(len(snapshot))
        return snapshot


def _make_runtime_with_n_plain_events(n: int) -> tuple[Runtime, _CopyCountingGraph]:
    """Build a runtime whose log has ``n`` non-terminal events and return both
    the runtime and its graph (so the test can read the copy-size ledger).

    No ``runtime.idle`` / ``runtime.budget_exhausted`` event is emitted, so the
    run looks "still active / loaded mid-flight" — the common case the
    documented contract must stay cheap for.
    """
    graph = _CopyCountingGraph()
    runtime = Runtime(graph)
    for i in range(n):
        graph.add_object("thing", {"i": i})
    graph.events_copy_sizes.clear()  # measure only what status() does
    return runtime, graph


def test_status_does_not_copy_whole_log() -> None:
    """status(recent=k) must not materialize a copy of the entire log.

    With a 200-event log and recent=5, the documented "no event log scan /
    tail-slice only" contract bounds the work by ``recent``. The buggy
    implementation copies all 200 events (``self.graph.events``) before
    slicing the last 5.
    """
    n = 200
    recent = 5
    runtime, graph = _make_runtime_with_n_plain_events(n)

    status = runtime.status(recent=recent)

    biggest_copy = max(graph.events_copy_sizes, default=0)
    assert biggest_copy <= recent * 4, (
        f"status(recent={recent}) materialized a copy of {biggest_copy} events "
        f"out of {n}; the docstring promises no event-log scan / no traversal "
        f"beyond a tail-slice, so any event-log copy must be bounded by "
        f"`recent`, not by the full log length."
    )
    # Sanity: the snapshot is still correct.
    assert status.events_processed == n
    assert len(status.recent_events) == recent
    # recent_events is the tail of the log, in chronological order.
    assert status.recent_events[-1].type == "object.created"


def test_status_copy_cost_independent_of_log_length() -> None:
    """The 'cheap to call' contract means the event-log work is ~constant in
    log size. A 50-event log and a 400-event log (both terminal-event-free)
    must materialize comparably small copies — bounded by ``recent``, not by
    total length.
    """
    recent = 10
    rt_small, g_small = _make_runtime_with_n_plain_events(50)
    rt_large, g_large = _make_runtime_with_n_plain_events(400)

    rt_small.status(recent=recent)
    rt_large.status(recent=recent)

    small_copy = max(g_small.events_copy_sizes, default=0)
    large_copy = max(g_large.events_copy_sizes, default=0)

    assert large_copy <= small_copy + recent, (
        f"snapshotting a 400-event log copied {large_copy} events while a "
        f"50-event log copied {small_copy}; the documented 'cheap to call "
        f"(no event log scan)' contract requires the cost to be independent "
        f"of log length, not grow with it."
    )
