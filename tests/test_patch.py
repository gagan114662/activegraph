"""Patch lifecycle. CONTRACT #4 (versioning) and #12 (single-target atomic)."""

from activegraph import FrozenClock, Graph, IDGen


def _g():
    return Graph(ids=IDGen(), clock=FrozenClock())


def test_patch_object_emits_patch_applied_with_diff():
    g = _g()
    o = g.add_object("task", {"status": "blocked"})
    p = g.patch_object(o.id, {"status": "open"})
    assert p.status == "applied"
    assert g.get_object(o.id).version == 2  # bumped
    assert g.get_object(o.id).data["status"] == "open"
    last = g.events[-1]
    assert last.type == "patch.applied"
    assert last.payload["target"] == o.id
    assert last.payload["diff"]["status"] == {"old": "blocked", "new": "open"}


def test_propose_patch_emits_proposed_and_can_apply():
    g = _g()
    o = g.add_object("memory", {"summary": "old"})
    p = g.propose_patch(
        target=o.id,
        op="update",
        value={"summary": "new"},
        proposed_by="memory_behavior",
        rationale="user said so",
    )
    assert p.status == "proposed"
    types = [e.type for e in g.events]
    assert "patch.proposed" in types

    g.apply_patch(p.id, approved_by="reviewer")
    assert g.get_object(o.id).data["summary"] == "new"
    assert g.get_object(o.id).version == 2
    assert g.get_patch(p.id).status == "applied"


def test_apply_patch_with_stale_version_is_rejected():
    g = _g()
    o = g.add_object("memory", {"summary": "v1"})
    p = g.propose_patch(
        target=o.id,
        op="update",
        value={"summary": "v3-from-stale-branch"},
        proposed_by="A",
    )
    # Meanwhile, someone else patches the object — bumps version.
    g.patch_object(o.id, {"summary": "v2"})
    assert g.get_object(o.id).version == 2

    g.apply_patch(p.id, approved_by="reviewer")
    types_after = [e.type for e in g.events]
    assert types_after[-1] == "patch.rejected"
    # Object data unchanged by the rejected patch.
    assert g.get_object(o.id).data["summary"] == "v2"
    assert g.get_patch(p.id).status == "rejected"
