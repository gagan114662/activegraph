import pytest

from activegraph.core.patch import Patch


pytestmark = getattr(pytest.mark, "activegraph.core.patch.Patch.to_dict")


def test_activegraph_core_patch_patch_to_dict_serializes_all_fields() -> None:
    patch = Patch(
        id="patch_001",
        target="obj_note",
        op="update",
        value={"title": "ship it", "status": "active"},
        expected_version=3,
        proposed_by="agent.maya",
        rationale="bump status after review",
        evidence=["evt_001", "evt_002"],
        status="applied",
        rejection_reason=None,
        provenance={"frame_id": "frm_abc", "caused_by": "msg_42"},
    )

    result = patch.to_dict()

    assert result == {
        "id": "patch_001",
        "target": "obj_note",
        "op": "update",
        "value": {"title": "ship it", "status": "active"},
        "expected_version": 3,
        "proposed_by": "agent.maya",
        "rationale": "bump status after review",
        "evidence": ["evt_001", "evt_002"],
        "status": "applied",
        "rejection_reason": None,
        "provenance": {"frame_id": "frm_abc", "caused_by": "msg_42"},
    }


def test_activegraph_core_patch_patch_to_dict_defaults_for_optional_fields() -> None:
    patch = Patch(
        id="patch_002",
        target="obj_task",
        op="create",
        value={"title": "draft"},
        expected_version=0,
        proposed_by="agent.quinn",
    )

    result = patch.to_dict()

    assert result["rationale"] is None
    assert result["evidence"] == []
    assert result["status"] == "proposed"
    assert result["rejection_reason"] is None
    assert result["provenance"] == {}


def test_activegraph_core_patch_patch_to_dict_copies_mutable_containers() -> None:
    evidence = ["evt_a"]
    provenance = {"frame_id": "frm_xyz"}
    patch = Patch(
        id="patch_003",
        target="obj_rel",
        op="remove",
        value={},
        expected_version=7,
        proposed_by="agent.sofia",
        evidence=evidence,
        provenance=provenance,
    )

    result = patch.to_dict()

    result["evidence"].append("evt_b")
    result["provenance"]["frame_id"] = "frm_changed"

    assert patch.evidence == ["evt_a"]
    assert patch.provenance == {"frame_id": "frm_xyz"}
