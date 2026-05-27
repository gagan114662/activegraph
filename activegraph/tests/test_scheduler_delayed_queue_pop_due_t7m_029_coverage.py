import pytest

from activegraph.runtime.scheduler import DelayedQueue, ScheduledEntry


pytestmark = getattr(pytest.mark, "activegraph.runtime.scheduler.DelayedQueue.pop_due")


def _entry(name: str, fire_at: int, idx: int = 0) -> ScheduledEntry:
    return ScheduledEntry(
        behavior_name=name,
        behavior_index=idx,
        triggering_event_id=f"evt_trig_{idx:03d}",
        fire_at_event_count=fire_at,
        where_recheck_path=None,
        scheduled_event_id=f"evt_sched_{idx:03d}",
    )


def test_activegraph_runtime_scheduler_delayedqueue_pop_due_returns_empty_when_queue_is_empty() -> None:
    q = DelayedQueue()

    due = q.pop_due(current_event_count=42)

    assert due == []
    assert len(q) == 0


def test_activegraph_runtime_scheduler_delayedqueue_pop_due_returns_only_due_entries_and_keeps_pending() -> None:
    q = DelayedQueue()
    early = _entry("early_behavior", fire_at=3, idx=1)
    on_time = _entry("on_time_behavior", fire_at=5, idx=2)
    future = _entry("future_behavior", fire_at=10, idx=3)
    q.push(early)
    q.push(on_time)
    q.push(future)

    due = q.pop_due(current_event_count=5)

    assert [e.behavior_name for e in due] == ["early_behavior", "on_time_behavior"]
    assert len(q) == 1
    assert q.entries[0] is future


def test_activegraph_runtime_scheduler_delayedqueue_pop_due_at_boundary_fires_entry_with_exact_match() -> None:
    q = DelayedQueue()
    q.push(_entry("boundary_behavior", fire_at=7, idx=1))

    due_just_before = q.pop_due(current_event_count=6)
    assert due_just_before == []
    assert len(q) == 1

    due_at_boundary = q.pop_due(current_event_count=7)
    assert len(due_at_boundary) == 1
    assert due_at_boundary[0].behavior_name == "boundary_behavior"
    assert len(q) == 0


def test_activegraph_runtime_scheduler_delayedqueue_pop_due_drains_all_when_counter_exceeds_every_fire_at() -> None:
    q = DelayedQueue()
    for i in range(4):
        q.push(_entry(f"behavior_{i}", fire_at=i + 1, idx=i))
    assert len(q) == 4

    due = q.pop_due(current_event_count=100)

    assert [e.behavior_name for e in due] == [
        "behavior_0",
        "behavior_1",
        "behavior_2",
        "behavior_3",
    ]
    assert len(q) == 0
    assert q.entries == []
