import pytest

from activegraph.core.event import Event
from activegraph.core.view import View


pytestmark = getattr(pytest.mark, "activegraph.core.view.View.events")


def _event(event_id: str, type_: str, payload: dict) -> Event:
    return Event(
        id=event_id,
        type=type_,
        payload=payload,
        actor="test",
        timestamp="2026-05-26T00:00:00Z",
    )


def test_activegraph_core_view_view_events_filters_by_type() -> None:
    created = _event("evt_created", "object.created", {"object_id": "obj_1"})
    patched = _event("evt_patched", "patch.applied", {"patch_id": "patch_1"})
    view = View(objects=[], relations=[], events=[created, patched])

    result = view.events(type="patch.applied")

    assert result == [patched]


def test_activegraph_core_view_view_events_returns_copy_for_unfiltered_results() -> None:
    emitted = _event("evt_emitted", "event.emitted", {"kind": "audit"})
    view = View(objects=[], relations=[], events=[emitted])

    result = view.events()
    result.clear()

    assert view.events() == [emitted]
