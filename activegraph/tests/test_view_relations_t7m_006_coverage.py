import pytest

from activegraph.core.graph import Relation
from activegraph.core.view import View


pytestmark = getattr(pytest.mark, "activegraph.core.view.View.relations")


def _relation(
    relation_id: str,
    source: str,
    target: str,
    type_: str,
    data: dict,
) -> Relation:
    return Relation(
        id=relation_id,
        source=source,
        target=target,
        type=type_,
        data=data,
        provenance={"source": "test"},
    )


def test_activegraph_core_view_view_relations_filters_by_type() -> None:
    depends_on = _relation("rel_depends", "obj_a", "obj_b", "depends_on", {})
    references = _relation("rel_refs", "obj_a", "obj_c", "references", {})
    view = View(objects=[], relations=[depends_on, references], events=[])

    result = view.relations(type="references")

    assert result == [references]


def test_activegraph_core_view_view_relations_returns_copy_for_unfiltered_results() -> None:
    relation = _relation("rel_depends", "obj_a", "obj_b", "depends_on", {"weight": 2})
    view = View(objects=[], relations=[relation], events=[])

    result = view.relations()
    result.clear()

    assert view.relations() == [relation]
