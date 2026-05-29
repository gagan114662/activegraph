"""T7 medium 013 coverage for activegraph.runtime.scheduler.DelayedQueue.push.

DelayedQueue.push appends a ScheduledEntry to the pending FIFO of
`activate_after` invocations. It is the input side of the scheduler;
pop_due is the (already-covered) output side. These tests exercise push
directly against real ScheduledEntry fixtures (no mocks of the API under
test) and assert both the happy-path append behavior and the boundary
interaction with pop_due that push must satisfy.
"""

from __future__ import annotations

from activegraph.runtime.scheduler import DelayedQueue, ScheduledEntry


def _entry(name: str, fire_at: int, index: int = 0) -> ScheduledEntry:
    """Build a real ScheduledEntry fixture for the queue under test."""
    return ScheduledEntry(
        behavior_name=name,
        behavior_index=index,
        triggering_event_id=f"evt-{name}",
        fire_at_event_count=fire_at,
        where_recheck_path=None,
        scheduled_event_id=f"sched-{name}",
    )


def test_delayed_queue_push_appends_and_preserves_fifo_order():
    """Happy path: push appends entries and preserves insertion order."""
    q = DelayedQueue()
    assert len(q) == 0

    first = _entry("first", fire_at=5, index=0)
    second = _entry("second", fire_at=5, index=1)
    third = _entry("third", fire_at=5, index=2)

    q.push(first)
    q.push(second)
    q.push(third)

    # push grows the queue by exactly one per call.
    assert len(q) == 3
    # FIFO order is preserved in the backing list.
    assert q.entries == [first, second, third]
    # All three share fire_at_event_count=5, so popping at 5 yields them
    # in the same order push recorded.
    due = q.pop_due(current_event_count=5)
    assert [e.behavior_name for e in due] == ["first", "second", "third"]


def test_delayed_queue_push_boundary_retains_not_yet_due_entries():
    """Boundary: a pushed entry whose fire count is in the future is
    retained by pop_due, not dropped, and remains poppable later."""
    q = DelayedQueue()

    due_now = _entry("due_now", fire_at=2)
    not_yet = _entry("not_yet", fire_at=10)
    q.push(due_now)
    q.push(not_yet)
    assert len(q) == 2

    # At count=2 only the due entry fires; the future one stays queued.
    fired = q.pop_due(current_event_count=2)
    assert [e.behavior_name for e in fired] == ["due_now"]
    assert len(q) == 1
    assert q.entries[0] is not_yet

    # Pushing onto the partially-drained queue still appends correctly.
    later = _entry("later", fire_at=10)
    q.push(later)
    assert [e.behavior_name for e in q.entries] == ["not_yet", "later"]

    # Once the event count reaches the fire-at boundary, both come due.
    fired_later = q.pop_due(current_event_count=10)
    assert [e.behavior_name for e in fired_later] == ["not_yet", "later"]
    assert len(q) == 0


def test_delayed_queue_push_allows_duplicate_entries():
    """Push does not deduplicate: the same logical schedule pushed twice
    is held twice (the runtime relies on this for repeated scheduling)."""
    q = DelayedQueue()
    e = _entry("dup", fire_at=3)
    q.push(e)
    q.push(e)
    assert len(q) == 2
    assert q.entries == [e, e]
