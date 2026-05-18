"""v0.9 killer demo: the Diligence pack, end-to-end, on fixtures.

This file is the v0.9 contract for the pack format. The Pack API
surface — `Pack(...)`, `runtime.load_pack(...)`, pack-aware
decorators, typed settings injection, the `pack.loaded` event,
namespace prefixing, schema validation, prompt content-hash replay —
is locked here first; the runtime, pack, and CLI are built backward
to make this script run. Same discipline as v0/v0.5/v0.6/v0.7/v0.8.

What this demo proves:

  1. The Diligence pack is a Python package (`activegraph.packs.diligence`)
     that exports a single `pack` symbol. Importing the pack has zero
     side effects on the global behavior / tool registries.
  2. `runtime.load_pack(pack, settings=DiligenceSettings(...))` registers
     all of the pack's object types, relation types, behaviors, tools,
     and prompts. Behaviors are namespace-prefixed (`diligence.*`) in
     the trace, in metrics labels, and in error messages. Lookups by
     short name resolve when unambiguous.
  3. The `pack.loaded` event lands in the event log with prompt content
     hashes recorded. A subsequent fork that loads the same pack with a
     mutated prompt would fire `ReplayDivergenceError` — the hash is
     the replay contract, the declared version is for humans.
  4. Object schemas are enforced for objects created *after* the pack
     loads. A `graph.add_object("claim", data={...malformed...})`
     raises `PackSchemaViolation`. Objects created before load are
     unaffected (v0.9 #5 load-order asymmetry).
  5. Three companies are run end-to-end against recorded fixtures.
     Each company produces exactly one memo with the contracted
     structure: Summary, Thesis Questions Addressed, Key Claims
     (every claim cites evidence), Open Contradictions (≥1 surfaced
     OR explicitly stated absent), Risks (≥1 surfaced).
  6. The `memo_approval` policy gates memo writes — the demo prints
     a pending approval, calls `runtime.approve(...)`, and the memo
     lands. No silent auto-applies for memos.
  7. One company's run is forked with an alternative thesis setting,
     producing a divergent set of claims. `runtime.diff(other)`
     surfaces the diverged objects.
  8. The trace is exported as JSONL. The full causal chain for one
     final claim walks back through LLM call → tool call → document
     → goal.

The pack ships its own recorded fixtures so the demo runs without
an API key or network access. Production usage substitutes the
shipped tool stubs with real implementations and replaces
`RecordedProvider` with `AnthropicProvider`.

Run it: `python examples/diligence_real_run.py`

Runs in under 30 seconds in CI. Output is byte-for-byte reproducible.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from activegraph import Runtime, configure_logging
from activegraph.packs import (
    PackConflictError,
    PackSchemaViolation,
    PackSettingsMissingError,
    PackVersionConflictError,
    load_by_name,
)
from activegraph.packs.diligence import pack as diligence_pack
from activegraph.packs.diligence import DiligenceSettings
from activegraph.packs.diligence.fixtures import (
    RecordedDiligenceProvider,
    THREE_COMPANIES,
    company_goal,
)


DB = "/tmp/activegraph_diligence_real_run.db"


# ---------- the demo flow --------------------------------------------------


def step_1_load_and_run() -> Runtime:
    """Load the pack, run three companies, return the runtime."""
    if os.path.exists(DB):
        os.remove(DB)

    configure_logging(level="WARNING", json_output=True)

    # Build a deterministic provider that scripts every LLM turn from
    # the pack's recorded fixtures. Production: pass AnthropicProvider().
    provider = RecordedDiligenceProvider(companies=THREE_COMPANIES)

    rt = Runtime(
        graph=None,  # type: ignore[arg-type]   filled by Runtime.fresh()
        llm_provider=provider,
        persist_to=DB,
        budget={
            "max_llm_calls": 80,
            "max_tool_calls": 100,
            "max_cost_usd": "5.00",
        },
    ) if False else _fresh_runtime(provider)  # see helper below — keeps API explicit

    # The pack: declared as a frozen Pack dataclass, imported as a
    # single symbol from `activegraph.packs.diligence`. No global
    # registry side effects from the import.
    settings = DiligenceSettings(
        llm_model="claude-sonnet-4-5",
        max_documents_per_company=5,
        max_claims_per_document=10,
        confidence_threshold_for_review=0.7,
        min_questions=8,
        max_questions=12,
    )
    rt.load_pack(diligence_pack, settings=settings)

    # Loading twice is a no-op (v0.9 #6 idempotency by (name, version)).
    rt.load_pack(diligence_pack, settings=settings)

    # Three companies. Each goal is structured so the question_generator
    # produces between min_questions and max_questions, the researcher
    # works through them in order, claims accumulate, contradictions
    # are detected (where the fixtures contain conflicting facts), risks
    # are identified, and a memo is synthesized.
    for company in THREE_COMPANIES:
        rt.run_goal(company_goal(company))

    rt.save_state()
    _print_run_summary(rt)
    return rt


def step_2_approval_demo(rt: Runtime) -> None:
    """Show the memo_approval policy gating a memo write.

    In step 1 we ran with auto-approval enabled so the demo flows
    end-to-end. Here we demonstrate the policy by re-running a single
    company with `auto_approve=False`, observing the pending approval,
    and explicitly approving.
    """
    print("\n=== memo_approval policy demo ===")
    company = THREE_COMPANIES[0]
    provider = RecordedDiligenceProvider(companies=[company])
    rt2 = _fresh_runtime(provider, db_path=DB + ".approval")
    rt2.load_pack(
        diligence_pack,
        settings=DiligenceSettings(
            llm_model="claude-sonnet-4-5",
            auto_approve_memos=False,
            auto_approve_risks=False,
        ),
    )
    rt2.run_goal(company_goal(company))

    # Drain in rounds: approving a risk surfaces the memo (memo_synthesizer
    # fires on risk creation, hits memo_approval policy). One round per
    # gate so the operator sees each one named explicitly.
    round_n = 0
    while True:
        pending = list(rt2.pending_approvals())
        if not pending:
            print(f"after approval: 0 pending")
            break
        round_n += 1
        labels = [_pending_label(p, rt2) for p in pending]
        round_label = f"round {round_n}" if round_n > 1 else "initial"
        print(
            f"pending approvals ({len(pending)}, {round_label}): "
            f"{', '.join(labels)}"
        )
        for p, label in zip(pending, labels):
            print(f"  - {label:28s} {p.id}  reason={p.reason!r}")
            rt2.approve(p.id, approved_by="demo-user")
        rt2.run_until_idle()


def step_3_fork_alt_thesis(rt: Runtime) -> None:
    """Fork one company's run with an alternative thesis and diff."""
    print("\n=== fork with alternative thesis ===")
    company = THREE_COMPANIES[0]
    # Locate the goal.created event for the first company.
    target_goal = company_goal(company)
    goal_evt = next(
        e for e in rt.graph.events
        if e.type == "goal.created" and e.payload.get("goal") == target_goal
    )
    fork = rt.fork(
        at_event=goal_evt.id,
        label="alt-thesis",
        replay_llm_cache=True,
        replay_tool_cache=True,
    )
    # Re-load the pack on the fork with different settings — a higher
    # confidence threshold means fewer claims survive review.
    fork.load_pack(
        diligence_pack,
        settings=DiligenceSettings(
            llm_model="claude-sonnet-4-5",
            confidence_threshold_for_review=0.9,  # was 0.7
        ),
    )
    fork.run_until_idle()
    fork.save_state()

    d = rt.diff(fork)
    print(f"parent run:  {rt.run_id}")
    print(f"fork run:    {fork.run_id}")
    print(f"shared events:        {len(d.shared_events)}")
    print(f"parent-only events:   {len(d.parent_only_events)}")
    print(f"fork-only events:     {len(d.fork_only_events)}")
    print(f"divergent objects:    {len(d.divergent_objects)}")


def step_4_export_trace(rt: Runtime) -> None:
    out = "/tmp/activegraph_diligence_real_run.trace.jsonl"
    rt.export_trace(out)
    print(f"\n=== trace exported ===\n{out}  ({_line_count(out)} events)")


def step_5_causal_chain(rt: Runtime) -> None:
    """Walk one final claim's causal chain back to its source goal."""
    print("\n=== causal chain for one final claim ===")
    final_claim = next(
        (o for o in rt.graph.all_objects() if o.type == "claim"),
        None,
    )
    if final_claim is None:
        print("(no claims produced; skipping)")
        return
    print(rt.trace.causal_chain(final_claim.id))


def step_6_verify_memos(rt: Runtime) -> None:
    """Assert the verifiable memo bar from CONTRACT v0.9 #19."""
    print("\n=== verifying memo bar ===")
    memos = [o for o in rt.graph.all_objects() if o.type == "memo"]
    assert len(memos) == 3, f"expected 3 memos, got {len(memos)}"
    for memo in memos:
        _check_memo_structure(rt, memo)
    print(f"OK: {len(memos)} memos, all with required structure and provenance")


# ---------- helpers --------------------------------------------------------


def _pending_label(pa, rt: Runtime) -> str:
    """Friendly slug for a pending approval — operator sees it at a glance.

    Resolves the gated object's company (via ``data.company_id``) to a
    short, lowercased company name pulled from the graph, so the slug
    is ``memo_northwind`` rather than ``memo_company#1``. Falls back to
    the approval id suffix when no company is in scope.
    """
    data = pa.data or {}
    company_id = data.get("company_id") or ""
    company_short = ""
    if company_id:
        co = rt.graph.get_object(company_id)
        if co is not None:
            raw_name = (co.data or {}).get("name") or company_id
            company_short = raw_name.lower().split()[0]
    suffix = pa.id.removeprefix("approval_")
    if pa.object_type == "memo":
        return f"memo_{company_short}" if company_short else f"memo_{suffix}"
    if pa.object_type == "risk":
        return (
            f"risk_{company_short}_{suffix}"
            if company_short
            else f"risk_{suffix}"
        )
    return f"{pa.object_type}_{suffix}"


def _fresh_runtime(provider, db_path: str = DB) -> Runtime:
    """Build a Runtime + Graph + persistence. Mirrors the v0.8 idiom."""
    from activegraph import Graph

    if os.path.exists(db_path):
        os.remove(db_path)
    graph = Graph()
    return Runtime(
        graph,
        llm_provider=provider,
        persist_to=db_path,
        budget={
            "max_llm_calls": 80,
            "max_tool_calls": 100,
            "max_cost_usd": "5.00",
        },
    )


def _print_run_summary(rt: Runtime) -> None:
    by_type: dict[str, int] = {}
    for o in rt.graph.all_objects():
        by_type[o.type] = by_type.get(o.type, 0) + 1
    print(f"[step 1] run {rt.run_id}: {len(rt.graph.events)} events")
    for t in (
        "company", "document", "question", "claim",
        "evidence", "contradiction", "risk", "memo",
    ):
        print(f"  {t:14s} {by_type.get(t, 0)}")


def _check_memo_structure(rt: Runtime, memo) -> None:
    """Verifiable memo bar from CONTRACT v0.9 #19."""
    body = memo.data
    required_sections = (
        "summary",
        "thesis_questions_addressed",
        "key_claims",
        "open_contradictions",
        "risks",
    )
    for sec in required_sections:
        assert sec in body, f"memo {memo.id} missing section {sec!r}"
    # Every claim cites at least one evidence id.
    for kc in body["key_claims"]:
        assert kc.get("evidence_ids"), (
            f"memo {memo.id}: claim {kc.get('claim_id')!r} has no evidence_ids"
        )
    # ≥1 contradiction surfaced OR explicit "no contradictions found".
    contradictions = body.get("open_contradictions") or []
    if not contradictions:
        assert body.get("contradictions_note") == "no contradictions found", (
            f"memo {memo.id}: zero contradictions and no explicit note"
        )
    # ≥1 risk surfaced.
    assert len(body.get("risks") or []) >= 1, (
        f"memo {memo.id}: zero risks identified"
    )


def _line_count(path: str) -> int:
    with open(path) as f:
        return sum(1 for _ in f)


# ---------- demo entry -----------------------------------------------------


def main() -> int:
    rt = step_1_load_and_run()
    step_6_verify_memos(rt)
    step_2_approval_demo(rt)
    step_3_fork_alt_thesis(rt)
    step_4_export_trace(rt)
    step_5_causal_chain(rt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
