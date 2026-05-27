import pytest

from activegraph.core.event import Event
from activegraph.runtime.queue import EventQueue


pytestmark = getattr(pytest.mark, "activegraph.runtime.queue.EventQueue")


def _event(event_id: str) -> Event:
    return Event(
        id=event_id,
        type="test.synthetic",
        actor="t7m_022",
        payload={"id": event_id},
        frame_id=None,
        caused_by=None,
        timestamp="2026-05-27T00:00:00Z",
    )


def test_activegraph_runtime_queue_EventQueue_push_pop_preserves_fifo_order() -> None:
    queue = EventQueue()
    first = _event("ev-1")
    second = _event("ev-2")
    third = _event("ev-3")

    queue.push(first)
    queue.push(second)
    queue.push(third)

    assert queue.pop() is first
    assert queue.pop() is second
    assert queue.pop() is third


def test_activegraph_runtime_queue_EventQueue_pop_on_empty_returns_none_and_keeps_falsy() -> None:
    queue = EventQueue()

    assert queue.pop() is None
    assert len(queue) == 0
    assert bool(queue) is False


def test_activegraph_runtime_queue_EventQueue_len_and_bool_track_pending_events() -> None:
    queue = EventQueue()
    assert len(queue) == 0
    assert bool(queue) is False

    queue.push(_event("ev-a"))
    queue.push(_event("ev-b"))
    assert len(queue) == 2
    assert bool(queue) is True

    queue.pop()
    assert len(queue) == 1
    assert bool(queue) is True

    queue.pop()
    assert len(queue) == 0
    assert bool(queue) is False
