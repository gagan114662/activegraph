import pytest

from activegraph.core.graph import Object
from activegraph.core.view import View


pytestmark = getattr(pytest.mark, "activegraph.core.view.View.objects")


def _object(
    object_id: str,
    type_: str,
    data: dict,
    *,
    version: int = 1,
) -> Object:
    return Object(
        id=object_id,
        type=type_,
        data=data,
        version=version,
        provenance={"source": "test"},
    )


def test_activegraph_core_view_view_objects_filters_by_type() -> None:
    note = _object("obj_note", "note", {"title": "ship"})
    task = _object("obj_task", "task", {"title": "review"})
    view = View(objects=[note, task], relations=[], events=[])

    result = view.objects(type="task")

    assert result == [task]


def test_activegraph_core_view_view_objects_filters_by_nested_where() -> None:
    active = _object("obj_active", "task", {"status": {"state": "active"}})
    archived = _object("obj_archived", "task", {"status": {"state": "archived"}})
    view = View(objects=[active, archived], relations=[], events=[])

    result = view.objects(where={"data.status.state": "active"})

    assert result == [active]
