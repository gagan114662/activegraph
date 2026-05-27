import pytest

from activegraph.core.graph import Graph, Object


pytestmark = getattr(pytest.mark, "activegraph.core.graph.Object.to_dict")


def test_activegraph_core_graph_object_to_dict_serializes_basic_fields() -> None:
    graph = Graph(run_id="run_t7m_025_basic")
    obj = graph.add_object("task", {"title": "ship release", "priority": 1})

    result = obj.to_dict()

    assert isinstance(result, dict)
    assert result["id"] == obj.id
    assert result["type"] == "task"
    assert result["version"] == 1
    assert result["data"]["title"] == "ship release"
    assert result["data"]["priority"] == 1
    # Provenance is stamped by the graph projector (CONTRACT #5).
    assert result["provenance"]["created_by"] == "system"
    assert result["provenance"]["run_id"] == "run_t7m_025_basic"
    # Keys must be the exact public surface.
    assert set(result.keys()) == {"id", "type", "data", "version", "provenance"}


def test_activegraph_core_graph_object_to_dict_deep_copies_data_and_provenance() -> None:
    graph = Graph(run_id="run_t7m_025_isolation")
    obj = graph.add_object("note", {"body": "draft", "tags": ["alpha", "beta"]})

    snapshot = obj.to_dict()
    # Mutating the snapshot must not bleed back into the live object.
    snapshot["data"]["body"] = "tampered"
    snapshot["data"]["tags"].append("gamma")
    snapshot["provenance"]["created_by"] = "attacker"

    assert obj.data["body"] == "draft"
    assert obj.data["tags"] == ["alpha", "beta"]
    assert obj.provenance["created_by"] == "system"

    # Re-serializing should still reflect the original state.
    fresh = obj.to_dict()
    assert fresh["data"]["body"] == "draft"
    assert fresh["data"]["tags"] == ["alpha", "beta"]
    assert fresh["provenance"]["created_by"] == "system"


def test_activegraph_core_graph_object_to_dict_preserves_nested_structures_and_version_bumps() -> None:
    graph = Graph(run_id="run_t7m_025_nested")
    obj = graph.add_object(
        "company",
        {
            "name": "Acme",
            "metrics": {"arr": 1000, "team": {"size": 5, "roles": ["eng", "ops"]}},
        },
    )

    initial = obj.to_dict()
    assert initial["version"] == 1
    assert initial["data"]["metrics"]["team"]["roles"] == ["eng", "ops"]

    graph.patch_object(obj.id, {"name": "Acme Corp"})
    bumped = obj.to_dict()

    assert bumped["version"] == 2
    assert bumped["data"]["name"] == "Acme Corp"
    # Untouched nested fields survive the patch.
    assert bumped["data"]["metrics"]["team"]["size"] == 5
    # Direct construction (no graph) is also a valid call path.
    standalone = Object(
        id="obj_manual",
        type="manual",
        data={"k": "v"},
        version=7,
        provenance={"created_by": "test", "evidence": []},
    )
    assert standalone.to_dict() == {
        "id": "obj_manual",
        "type": "manual",
        "data": {"k": "v"},
        "version": 7,
        "provenance": {"created_by": "test", "evidence": []},
    }
