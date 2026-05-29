"""T7 repeat-hard 022 — docstring↔code drift bug.

`memo_synthesizer` (activegraph/packs/diligence/behaviors.py) documents:

    "Idempotent: only one memo per company. ... we only synthesize on
    the first one."

The behavior fires `on=["object.created"] where {object.type: risk}`, so
it runs once per risk object. `risk_identifier` may emit MORE than one risk
for the same company, so `memo_synthesizer` fires multiple times for one
company and relies on its idempotency guard to produce a single memo.

The guard only inspects MATERIALIZED memos (`ctx.view.objects(type="memo")`).
Under the `memo_approval` policy (`auto_approve_memos=False`) memos are NOT
materialized — they go through `ctx.propose_object`, which records a PENDING
approval not visible in the view. So a second risk for the same company
proposes a SECOND memo, violating the documented "only one memo per company".

This is the exact failure mode `risk_identifier` already guards against: it
checks both materialized risks AND `ctx._runtime.pending_approvals()`.
`memo_synthesizer`'s docstring promises the same idempotency but its code
omits the pending-approval check.

This test asserts the DOCUMENTED behavior (one memo per company) on the
propose path. It FAILS against the buggy code (two proposals) and PASSES
once the pending-approval check is added.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from activegraph.packs import PendingApproval
from activegraph.packs.diligence.behaviors import memo_synthesizer
from activegraph.packs.diligence.settings import DiligenceSettings


# The decorated object is an LLMBehavior; `.handler` is the original
# (event, graph, ctx, out, *, settings) callable.
_memo_fn = memo_synthesizer.handler


class _FakeView:
    """`ctx.view` stand-in. Returns only MATERIALIZED objects — pending
    approvals are deliberately invisible here, exactly as the real view
    behaves under a gating policy.
    """

    def __init__(self, store: dict[str, list[Any]]) -> None:
        self._store = store

    def objects(self, *, type: str) -> list[Any]:
        return list(self._store.get(type, []))


class _FakeRuntime:
    """`ctx._runtime` stand-in. Holds the pending-approval list that
    `propose_object` appends to.
    """

    def __init__(self) -> None:
        self._pending: list[PendingApproval] = []
        self._n = 0

    def pending_approvals(self) -> list[PendingApproval]:
        return list(self._pending)

    def add_pending(self, *, object_type: str, data: dict) -> str:
        self._n += 1
        pa = PendingApproval(
            id=f"approval_{self._n:03d}",
            kind="object",
            object_type=object_type,
            data=dict(data),
            reason="",
            pack="diligence",
        )
        self._pending.append(pa)
        return pa.id


class _FakeCtx:
    def __init__(self, runtime: _FakeRuntime, view: _FakeView) -> None:
        self._runtime = runtime
        self.view = view

    def propose_object(self, object_type: str, data: dict, *, reason: str = "") -> str:
        # Mirrors Runtime.propose_object -> _add_pending_approval: the
        # object is NOT materialized, only queued as a pending approval.
        return self._runtime.add_pending(object_type=object_type, data=data)


class _FakeGraph:
    """`graph` stand-in. Resolves risk objects by id; records auto-applied
    add_object calls so the control case can be asserted too.
    """

    def __init__(self) -> None:
        self._objects: dict[str, Any] = {}
        self.added: list[tuple[str, dict]] = []

    def register_risk(self, risk_id: str, company_id: str) -> None:
        self._objects[risk_id] = SimpleNamespace(
            id=risk_id, data={"company_id": company_id}
        )

    def get_object(self, id_: str) -> Any:
        return self._objects.get(id_)

    def add_object(self, type: str, data: dict) -> None:
        self.added.append((type, data))


def _risk_created_event(risk_id: str) -> SimpleNamespace:
    return SimpleNamespace(payload={"object": {"id": risk_id, "type": "risk"}})


def _memo_out() -> SimpleNamespace:
    # MemoBody-shaped duck for the synthesizer body.
    return SimpleNamespace(
        summary="s",
        thesis_questions_addressed=[],
        key_claims=[],
        open_contradictions=[],
        contradictions_note="",
        risks=[],
    )


def test_memo_synthesizer_proposes_only_one_memo_per_company_under_gating() -> None:
    """DOCUMENTED behavior: one memo per company, even when two risks fire
    for that company and memos are gated (auto_approve_memos=False).
    """
    runtime = _FakeRuntime()
    graph = _FakeGraph()
    company_id = "company_acme"
    # Two distinct risks for the SAME company — as risk_identifier can emit.
    graph.register_risk("risk_001", company_id)
    graph.register_risk("risk_002", company_id)

    # No materialized memos: gating defers them to pending approvals.
    view = _FakeView({"memo": []})
    ctx = _FakeCtx(runtime, view)
    settings = DiligenceSettings(auto_approve_memos=False)

    _memo_fn(_risk_created_event("risk_001"), graph, ctx, _memo_out(), settings=settings)
    _memo_fn(_risk_created_event("risk_002"), graph, ctx, _memo_out(), settings=settings)

    memo_proposals = [
        pa for pa in runtime.pending_approvals() if pa.object_type == "memo"
    ]
    assert len(memo_proposals) == 1, (
        "memo_synthesizer must propose exactly one memo per company "
        f"(documented idempotency), got {len(memo_proposals)} proposals"
    )
    memo_companies = [pa.data.get("company_id") for pa in memo_proposals]
    assert memo_companies == [company_id]


def test_memo_synthesizer_auto_approve_path_still_one_memo_per_company() -> None:
    """Control: the already-correct auto-approve path stays idempotent.

    Second risk sees the first memo materialized in the view and skips.
    """
    runtime = _FakeRuntime()
    graph = _FakeGraph()
    company_id = "company_beta"
    graph.register_risk("risk_010", company_id)
    graph.register_risk("risk_011", company_id)

    materialized: list[Any] = []
    view = _FakeView({"memo": materialized})
    ctx = _FakeCtx(runtime, view)
    settings = DiligenceSettings(auto_approve_memos=True)

    _memo_fn(_risk_created_event("risk_010"), graph, ctx, _memo_out(), settings=settings)
    # Reflect the first auto-applied memo into the view before the 2nd fire.
    for type_, data in graph.added:
        if type_ == "memo":
            materialized.append(SimpleNamespace(id="memo_x", data=data))

    _memo_fn(_risk_created_event("risk_011"), graph, ctx, _memo_out(), settings=settings)

    memos_added = [d for (t, d) in graph.added if t == "memo"]
    assert len(memos_added) == 1
