"""Failing tests for frame ``v0-promote-runtime-diff``.

Test-first: this module defines the verifiable contract for promoting
``activegraph/runtime/diff.py`` to the mypy --strict allowlist. It mirrors
the spec in ``examples/v0_promote_runtime_diff.py`` (the killer demo) and
adds the four coverage points the example deliberately under-tests.

Two top-level gates (will fail until Code Owner closes the frame):

1. ``python examples/v0_promote_runtime_diff.py`` exits 0.
2. ``mypy --strict examples/v0_promote_runtime_diff.py`` exits 0.

Plus unit-level reinforcement of the public surface of
``activegraph.runtime.diff``:

* lifecycle event filtering (``compute_diff`` ignores ``behavior.*`` /
  ``relation_behavior.*`` / ``runtime.*`` events — ``diff.py:81-82``);
* provenance-stripping in ``_normalize_object`` / ``_normalize_relation``
  (``diff.py:135-145``) — objects/relations that differ ONLY in
  provenance must NOT show up as divergent;
* every branch of ``DivergentObject.summary`` and
  ``DivergentRelation.summary`` (``diff.py:36-41`` / ``diff.py:50-57``);
* ``Diff`` constructed with all-empty defaults reports ``is_identical=True``.

Determinism gate (CONTRACT v0.7 #13-style): no ``time.sleep``, no live
network, no real wall-clock — every graph uses ``FrozenClock()`` and a
fresh ``IDGen()`` with an explicit ``run_id``. Subprocess calls are
local-only (``python`` / ``python -m mypy``).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from activegraph.core.clock import FrozenClock
from activegraph.core.event import Event
from activegraph.core.graph import Graph
from activegraph.core.ids import IDGen
from activegraph.runtime.diff import (
    Diff,
    DivergentObject,
    DivergentRelation,
    compute_diff,
)


# ---------- locate the project root & the example file ----------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_REL = Path("examples") / "v0_promote_runtime_diff.py"
EXAMPLE_PATH = PROJECT_ROOT / EXAMPLE_REL


# ---------- helpers ----------


def _fresh_graph(run_id: str) -> Graph:
    return Graph(ids=IDGen(), clock=FrozenClock(), run_id=run_id)


def _lifecycle_event(graph: Graph, event_type: str) -> Event:
    return Event(
        id=graph.ids.event(),
        type=event_type,
        payload={"name": "test"},
        actor="system",
        timestamp=graph.clock.now(),
    )


# ===========================================================================
# Gate 1 + 2: the verification recipe from the spec.
# ===========================================================================


def test_example_file_exists() -> None:
    """Spec artifact must be on disk where the recipe expects it."""
    assert EXAMPLE_PATH.is_file(), (
        f"spec example missing: {EXAMPLE_PATH}. "
        f"Frame v0-promote-runtime-diff requires {EXAMPLE_REL} to exist."
    )


def test_example_runs_cleanly() -> None:
    """``python examples/v0_promote_runtime_diff.py`` must exit 0.

    Verification recipe #1 from the spec.
    """
    result = subprocess.run(
        [sys.executable, str(EXAMPLE_REL)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"example exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_example_passes_mypy_strict() -> None:
    """``mypy --strict examples/v0_promote_runtime_diff.py`` must exit 0.

    Verification recipe #2 from the spec. THIS IS THE FAILING TEST that
    drives the promotion: today mypy --strict on the example reports
    Any-leak errors against ``assert_type`` because the project mypy
    config sets ``follow_imports = "skip"``. Code Owner closes this.
    """
    # The subprocess below runs `sys.executable -m mypy`, so the relevant
    # availability question is whether the VENV python (sys.executable) can
    # import mypy — not whether a system mypy exists on PATH. Skip when the
    # venv can't import it; otherwise the test fails for an environment
    # reason rather than a real type regression.
    if not _mypy_module_importable():
        pytest.skip("mypy not importable by sys.executable; skipping in this environment")
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(EXAMPLE_REL)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"mypy --strict {EXAMPLE_REL} exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_runtime_diff_passes_mypy_strict_standalone() -> None:
    """``mypy --strict activegraph/runtime/diff.py`` must exit 0.

    Belt-and-braces: even if pyproject's allowlist drifts, the module
    itself must remain --strict-clean. Frame success criterion
    ``mypy_strict_passes_runtime_diff_zero_errors``.
    """
    # The subprocess below runs `sys.executable -m mypy`, so the relevant
    # availability question is whether the VENV python (sys.executable) can
    # import mypy — not whether a system mypy exists on PATH. Skip when the
    # venv can't import it; otherwise the test fails for an environment
    # reason rather than a real type regression.
    if not _mypy_module_importable():
        pytest.skip("mypy not importable by sys.executable; skipping in this environment")
    target = Path("activegraph") / "runtime" / "diff.py"
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(target)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"mypy --strict {target} exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_pyproject_keeps_diff_in_strict_allowlist() -> None:
    """``pyproject.toml`` must list ``runtime/diff.py`` in both the
    ``files`` block and the per-module ``strict = true`` overrides.

    Frame success criteria ``diff_listed_in_pyproject_mypy_files`` /
    ``diff_listed_in_pyproject_mypy_strict_overrides``.
    """
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "activegraph/runtime/diff.py" in text, (
        "runtime/diff.py missing from [tool.mypy] files allowlist"
    )
    assert "activegraph.runtime.diff" in text, (
        "activegraph.runtime.diff missing from strict override module list"
    )


def _mypy_module_importable() -> bool:
    try:
        import mypy  # noqa: F401
        return True
    except ImportError:
        return False


# ===========================================================================
# Unit-level coverage the spec example deliberately under-tests.
# ===========================================================================


# --- (1) lifecycle event filtering (diff.py:23-27, 81-82) ----------------


@pytest.mark.parametrize(
    "lifecycle_type",
    ["behavior.fired", "relation_behavior.fired", "runtime.tick"],
)
def test_compute_diff_filters_lifecycle_events(lifecycle_type: str) -> None:
    """``compute_diff`` must drop ``behavior.*`` / ``relation_behavior.*`` /
    ``runtime.*`` events before partitioning. The example never emits one,
    so this is the only direct coverage of ``_is_lifecycle``.
    """
    parent = _fresh_graph("p")
    parent.add_object("task", {"title": "a"})
    parent.emit(_lifecycle_event(parent, lifecycle_type))
    parent.add_object("task", {"title": "b"})

    fork = _fresh_graph("f")
    fork.add_object("task", {"title": "a"})

    diff = compute_diff(parent, fork, "p", "f")

    all_partition_events = (
        diff.shared_events + diff.parent_only_events + diff.fork_only_events
    )
    leaked = [e for e in all_partition_events if e.type == lifecycle_type]
    assert leaked == [], (
        f"lifecycle event {lifecycle_type!r} leaked into diff partition: {leaked}"
    )
    for e in all_partition_events:
        assert not e.type.startswith("behavior."), e
        assert not e.type.startswith("relation_behavior."), e
        assert not e.type.startswith("runtime."), e


# --- (2) provenance-stripping in _normalize_object / _normalize_relation -


def test_objects_differing_only_in_provenance_are_not_divergent() -> None:
    """Two objects with the same id + type + data but different
    ``provenance`` (timestamp / run_id) must NOT appear in
    ``divergent_objects``. ``_normalize_object`` strips provenance
    before equality — that branch is otherwise uncovered.
    """
    parent = Graph(
        ids=IDGen(), clock=FrozenClock("2026-05-15T10:00:00Z"), run_id="PARENT"
    )
    fork = Graph(
        ids=IDGen(), clock=FrozenClock("2026-05-16T22:00:00Z"), run_id="FORK"
    )
    parent.add_object("task", {"title": "same", "status": "open"})
    fork.add_object("task", {"title": "same", "status": "open"})

    # Sanity: the underlying provenance really does differ, so the test
    # actually exercises the stripping branch.
    p_obj = parent.all_objects()[0]
    f_obj = fork.all_objects()[0]
    assert p_obj.id == f_obj.id == "task#1"
    assert p_obj.provenance != f_obj.provenance, (
        "test precondition broken: provenance was already equal"
    )

    diff = compute_diff(parent, fork, "PARENT", "FORK")
    assert diff.divergent_objects == [], (
        f"objects identical-modulo-provenance should not diverge; got "
        f"{[d.summary() for d in diff.divergent_objects]}"
    )


def test_relations_differing_only_in_provenance_are_not_divergent() -> None:
    """Same as above for relations; covers ``_normalize_relation``."""
    parent = Graph(
        ids=IDGen(), clock=FrozenClock("2026-05-15T10:00:00Z"), run_id="PARENT"
    )
    fork = Graph(
        ids=IDGen(), clock=FrozenClock("2026-05-16T22:00:00Z"), run_id="FORK"
    )
    a_p = parent.add_object("task", {"title": "a"})
    b_p = parent.add_object("task", {"title": "b"})
    parent.add_relation(a_p.id, b_p.id, "depends_on")

    a_f = fork.add_object("task", {"title": "a"})
    b_f = fork.add_object("task", {"title": "b"})
    fork.add_relation(a_f.id, b_f.id, "depends_on")

    p_rel = parent.all_relations()[0]
    f_rel = fork.all_relations()[0]
    assert p_rel.id == f_rel.id == "rel_001"
    assert p_rel.provenance != f_rel.provenance, (
        "test precondition broken: provenance was already equal"
    )

    diff = compute_diff(parent, fork, "PARENT", "FORK")
    assert diff.divergent_relations == [], (
        f"relations identical-modulo-provenance should not diverge; got "
        f"{[d.summary() for d in diff.divergent_relations]}"
    )


# --- (3) every branch of DivergentObject.summary / DivergentRelation.summary


def test_divergent_object_summary_only_in_parent() -> None:
    do = DivergentObject(id="task#1", in_parent={"version": 1}, in_fork=None)
    assert do.summary() == "task#1 only in parent"


def test_divergent_object_summary_only_in_fork() -> None:
    do = DivergentObject(id="task#9", in_parent=None, in_fork={"version": 1})
    assert do.summary() == "task#9 only in fork"


def test_divergent_object_summary_differs() -> None:
    do = DivergentObject(
        id="task#1", in_parent={"version": 2}, in_fork={"version": 5}
    )
    msg = do.summary()
    assert "differs" in msg and "v2" in msg and "v5" in msg, msg


def test_divergent_relation_summary_only_in_parent() -> None:
    dr = DivergentRelation(
        id="rel_001",
        in_parent={"source": "task#1", "target": "task#2", "type": "depends_on"},
        in_fork=None,
    )
    msg = dr.summary()
    assert "rel_001 only in parent" in msg
    assert "task#1 --depends_on--> task#2" in msg


def test_divergent_relation_summary_only_in_fork() -> None:
    """Spec called this out — example only exercises 'only in parent'."""
    dr = DivergentRelation(
        id="rel_007",
        in_parent=None,
        in_fork={"source": "task#9", "target": "task#10", "type": "blocks"},
    )
    msg = dr.summary()
    assert "rel_007 only in fork" in msg
    assert "task#9 --blocks--> task#10" in msg


def test_divergent_relation_summary_differs() -> None:
    """Spec called this out — example only exercises 'only in parent'."""
    dr = DivergentRelation(
        id="rel_001",
        in_parent={"source": "a", "target": "b", "type": "depends_on"},
        in_fork={"source": "a", "target": "b", "type": "blocks"},
    )
    assert dr.summary() == "rel_001 differs"


# --- (4) Diff dataclass with all-empty defaults -------------------------


def test_diff_empty_defaults_is_identical_true() -> None:
    """A ``Diff`` constructed with just the two run ids — no events, no
    divergence — must report ``is_identical=True``. This is the
    short-circuit shape downstream tools (UI, replay, fork inspector)
    rely on.
    """
    d = Diff(parent_run_id="p", fork_run_id="f")
    assert d.shared_events == []
    assert d.parent_only_events == []
    assert d.fork_only_events == []
    assert d.divergent_objects == []
    assert d.divergent_relations == []
    assert d.is_identical is True
