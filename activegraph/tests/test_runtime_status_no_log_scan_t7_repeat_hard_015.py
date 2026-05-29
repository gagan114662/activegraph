"""T7 HARD repeat 015 — docstring↔code drift regression test.

The `RuntimeStatus` module docstring (activegraph/observability/status.py)
promises that taking a status snapshot does NOT scan the event log:

    "Cheap to call (no graph traversal, no event log scan), safe
     from anywhere, returns immutable data."        (status.py:4)

`Runtime.status()` echoes the same promise:

    "Cheap to call. No graph traversal beyond a tail-slice of the
     event log."                                     (runtime.py:1688)

But `Runtime.status()` derives `state` by walking the WHOLE event log
in reverse until it hits a terminal lifecycle event
(`runtime.idle` / `runtime.budget_exhausted`):

    for ev in reversed(self.graph.events):
        if t == "runtime.budget_exhausted": ...; break
        if t == "runtime.idle": ...; break

When no terminal lifecycle event is present — the common case for a
run that is still active or was loaded mid-flight — that loop visits
EVERY event in the log. That is exactly the "event log scan" /
"graph traversal beyond a tail-slice" both docstrings say does not
happen. The cost of `status()` is therefore O(len(log)), not
O(recent), contradicting the documented "cheap to call" contract.

This is a DIFFERENT drift from the run-003 target (the *immutability*
claim at status.py:5 / runtime.py:1689): this one is the
*no-log-scan / tail-slice-only* claim at status.py:4 / runtime.py:1688.

These tests assert the DOCUMENTED behavior: `status(recent=k)` must
touch at most a tail-slice of the log (bounded by `recent`), not the
whole log, even when no terminal lifecycle event exists.
"""

from __future__ import annotations

from activegraph.core.graph import Graph
from activegraph.runtime.runtime import Runtime


class _CountingEventList(list):
    """A list that counts how many elements are visited via iteration.

    `Runtime.status()` reads `self.graph.events` (a fresh list copy) and
    walks it with `reversed(...)`. We make the *copy* an instance of this
    class so every element touched during the state-derivation walk is
    counted, then assert the count is bounded by the tail-slice size.
    """

    def __init__(self, *args, counter):
        super().__init__(*args)
        self._counter = counter

    def __reversed__(self):
        for item in super().__reversed__():
            self._counter[0] += 1
            yield item

    def __iter__(self):
        for item in super().__iter__():
            self._counter[0] += 1
            yield item


class _CountingGraph(Graph):
    """Graph whose `events` property hands back a counting list copy."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.events_visited = [0]

    @property
    def events(self):
        return _CountingEventList(self._events, counter=self.events_visited)


def _make_runtime_with_n_plain_events(n: int) -> Runtime:
    """Build a runtime whose log has `n` non-terminal events.

    Crucially there is NO `runtime.idle` / `runtime.budget_exhausted`
    event, so the state-derivation loop has no early-exit and would
    scan the entire log under the buggy implementation.
    """
    graph = _CountingGraph()
    rt = Runtime(graph)
    for i in range(n):
        # Use the public mutation API so the emitted events are well-formed
        # and project cleanly. Each call appends one `object.created` event;
        # none of them is a terminal lifecycle event, so the state loop has
        # no early-exit.
        graph.add_object("thing", {"i": i})
    # reset the visit counter so we only measure what status() touches
    graph.events_visited[0] = 0
    return rt


def test_status_does_not_scan_whole_log_for_state() -> None:
    """status(recent=k) must touch only a tail-slice, per status.py:4.

    With a 200-event log and recent=5, the documented contract is "no
    event log scan" / "no traversal beyond a tail-slice". A correct
    implementation visits O(recent) events. The buggy one visits all
    200 deriving `state`.
    """
    n = 200
    recent = 5
    rt = _make_runtime_with_n_plain_events(n)

    status = rt.status(recent=recent)

    visited = rt.graph.events_visited[0]
    # Allow generous slack for a tail-slice plus a couple of bookkeeping
    # reads, but it must NOT be on the order of the full log.
    assert visited <= recent * 4, (
        f"status(recent={recent}) visited {visited} events out of {n}; "
        f"the docstring (status.py:4) promises no event-log scan / no "
        f"traversal beyond a tail-slice, so the visit count must be "
        f"bounded by `recent`, not by the full log length."
    )
    # Sanity: the snapshot still reports the correct totals/state.
    assert status.events_processed == n
    assert status.state in ("idle", "running", "stopped", "exhausted")


def test_status_cost_is_independent_of_log_length() -> None:
    """The 'cheap to call' contract means cost is ~constant in log size.

    A 50-event log and a 400-event log (both terminal-event-free) must
    cost roughly the same to snapshot. Under the buggy full-log scan the
    larger log visits ~8x more events; the documented contract makes the
    two visit-counts comparable (bounded by `recent`).
    """
    recent = 10
    rt_small = _make_runtime_with_n_plain_events(50)
    rt_large = _make_runtime_with_n_plain_events(400)

    rt_small.status(recent=recent)
    rt_large.status(recent=recent)

    small_visits = rt_small.graph.events_visited[0]
    large_visits = rt_large.graph.events_visited[0]

    assert large_visits <= small_visits + recent, (
        f"snapshotting a 400-event log visited {large_visits} events while a "
        f"50-event log visited {small_visits}; the documented 'cheap to call "
        f"(no event log scan)' contract (status.py:4) requires the cost to be "
        f"independent of log length, not grow with it."
    )
