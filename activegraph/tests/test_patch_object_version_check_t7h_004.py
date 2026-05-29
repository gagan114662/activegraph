"""T7 HARD repetition run 004 — docstring↔code drift regression test.

Target: ``activegraph.core.graph.Graph.patch_object``

The docstring at ``activegraph/core/graph.py`` states:

    "Auto-apply shortcut: build patch, version-check, emit applied/rejected."

That documents THREE behaviors: (1) build a patch, (2) perform a
version-check, (3) emit ``patch.applied`` OR ``patch.rejected`` depending
on the check. The original code only ever did (1) and unconditionally
emitted ``patch.applied`` with ``status="applied"`` — it performed no
version comparison and could NEVER emit ``patch.rejected``. The
"version-check" and "rejected" half of the documented behavior was
unreachable: that gap IS the bug.

This test asserts the DOCUMENTED behavior: when a caller supplies an
``expected_version`` that no longer matches the object's current version
(a stale optimistic-concurrency token), ``patch_object`` must version-check
and emit ``patch.rejected`` rather than blindly applying. It also pins the
backward-compatible happy path (no ``expected_version`` / matching version
→ ``patch.applied``).
"""

from __future__ import annotations

from activegraph.core.graph import Graph


def _fresh_object() -> tuple[Graph, str]:
    g = Graph()
    obj = g.add_object("task", {"title": "draft", "status": "open"})
    return g, obj.id


def test_patch_object_rejects_on_stale_expected_version() -> None:
    """Documented 'version-check, emit ... rejected' path.

    A caller holding a stale ``expected_version`` must get a rejection,
    not a silent apply. Pre-fix this raised TypeError (no such kwarg) or
    silently applied — both violate the docstring.
    """
    g, oid = _fresh_object()

    # Object is at version 1. Bump it once so any expected_version=1 token
    # the caller still holds is now stale.
    g.patch_object(oid, {"status": "in_progress"})
    assert g.get_object(oid).version == 2

    # Caller still believes the object is at version 1 — stale token.
    patch = g.patch_object(oid, {"status": "done"}, expected_version=1)

    # Documented behavior: version-check fails -> rejected, NOT applied.
    assert patch.status == "rejected", (
        "patch_object docstring promises 'version-check, emit applied/rejected' "
        f"but a stale expected_version produced status={patch.status!r}"
    )

    # The rejected patch must NOT have mutated the object.
    assert g.get_object(oid).data["status"] == "in_progress"

    # A patch.rejected event must be in the log (the documented 'rejected' emit).
    kinds = [e.type for e in g.events]
    assert "patch.rejected" in kinds, (
        f"expected a patch.rejected event in the log, got kinds={kinds}"
    )


def test_patch_object_applies_when_version_matches() -> None:
    """Happy path stays intact: matching/absent expected_version -> applied."""
    g, oid = _fresh_object()

    # No expected_version supplied — backward-compatible auto-apply.
    p1 = g.patch_object(oid, {"status": "in_progress"})
    assert p1.status == "applied"
    assert g.get_object(oid).data["status"] == "in_progress"
    assert g.get_object(oid).version == 2

    # Explicit, matching expected_version — version-check passes -> applied.
    p2 = g.patch_object(oid, {"status": "done"}, expected_version=2)
    assert p2.status == "applied"
    assert g.get_object(oid).data["status"] == "done"

    applied = [e.type for e in g.events if e.type == "patch.applied"]
    assert len(applied) == 2
