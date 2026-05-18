# Policies

A policy is a runtime-attached rule that gates changes to the graph
before they land. A behavior proposing a graph mutation under a
policy doesn't get a direct apply — the change becomes an
**approval** in `proposed` state. An operator (or an auto-approve
setting) then approves the proposal, and the change lands.

Policies are how the framework lets an operator sit in the loop
without rewriting the behavior. The behavior says "I want to add
this memo"; the policy says "memos require explicit approval"; the
operator says "yes, approve it." The same behavior runs in dev
(auto-approve) and prod (explicit-approve) without code changes.

## What gets gated

Two operations can be policy-gated:

- **Object proposals via `ctx.propose_object(type, data, reason)`.**
  Instead of an immediate `add_object`, the framework creates a
  pending approval and emits `approval.proposed`. The object
  lands only when the approval is granted.
- **Patches.** A patch declared as policy-gated takes the same
  proposed-and-approved path, except the patch lifecycle lives in
  the patch event types (`patch.proposed` / `patch.applied`)
  rather than approval event types. See [`patches`](patches.md)
  for the patch state machine.

Object proposals are the more common shape. The diligence pack's
`memo_approval` and `risk_approval` policies are the canonical
examples: the pack declares which object types require approval,
the operator decides per-instance.

Not every change is policy-gated. Direct `graph.add_object`,
`graph.patch_object`, and `graph.emit` calls land immediately;
they're for changes the behavior author decided don't need
operator review. The behavior chooses by calling the proposal
method instead of the direct method.

## The approval lifecycle

```
            proposed ──approve──> granted
                |
                └──deny────────> denied
```

Both transitions are one-shot. A proposed approval becomes granted
exactly once (via `runtime.approve(id, approved_by=...)`) or
denied exactly once (via `runtime.deny(id, denied_by=..., reason=...)`).
Calling either on an already-terminal approval raises
[`approval-not-found-error`](../reference/errors/approval-not-found-error.md)
— the approval id is consumed by the transition.

Each transition emits an event:

- `approval.proposed` — carries the proposal kind (`object` /
  `patch`), the type, the data, the reason from the proposing
  behavior, and the pack that owns the gating policy.
- `approval.granted` — carries the approval id, the approver
  identity, and the resulting object id (or applied patch id).
- `approval.denied` — carries the approval id, the denier
  identity, and the denial reason.

The events sit in the log alongside everything else. Downstream
behaviors can subscribe to them; replay reconstructs the full
proposal-and-decision sequence; the trace renders them.

## Declaring policies

Packs declare policies as part of their `Pack(...)` declaration:

```python
from activegraph.packs import Pack, PackPolicy

pack = Pack(
    name="diligence",
    version="0.1.0",
    policies=[
        PackPolicy(
            name="memo_approval",
            requires_approval=["memo"],
            settings_key="auto_approve_memos",
        ),
        ...
    ],
    ...
)
```

`requires_approval` lists the object types the policy gates.
`settings_key` names the pack-settings boolean that controls
auto-approve behavior; when `True`, the framework approves every
proposal automatically and the behavior runs as if the policy
weren't there. When `False`, every proposal pauses until an
operator decides.

The pack ships with the policies; the runtime instance decides
auto-approve via its `DiligenceSettings(auto_approve_memos=...)`.
That separation lets one pack run in different approval modes
across environments.

## How a behavior proposes

A behavior that wants its change to flow through a policy calls
`ctx.propose_object` instead of `graph.add_object`:

```python
@behavior(name="memo_synthesizer", on=["claim.completed"])
def memo_synthesizer(event, graph, ctx):
    ...
    ctx.propose_object(
        "memo",
        data={"title": "Diligence memo", "body": "..."},
        reason="diligence run complete",
    )
```

The propose call returns an approval id. The runtime decides
whether to apply immediately (auto-approve setting is `True`) or
queue the proposal (setting is `False`). Either way, the behavior
body completes; the approval lifecycle continues independently.

If the behavior tries `ctx.propose_object` outside a
runtime-bound context — typically a test fixture or a refactored
helper — it raises
[`runtime-context-required-error`](../reference/errors/runtime-context-required-error.md).

## The operator-facing recovery

When auto-approve is off, the operator drives the lifecycle:

```python
for pa in rt.pending_approvals():
    print(pa.id, pa.kind, pa.object_type, pa.reason)

# Approve one:
rt.approve(approval_id, approved_by="operator-jane")

# Or deny:
rt.deny(approval_id, denied_by="operator-jane", reason="not yet")
```

The CLI surface for production approval workflows is in the
[operating guide](../guides/operating-in-production.md).

## The events-not-exceptions principle applied

A denied approval is an event (`approval.denied`), not an
exception. A behavior whose proposal gets denied doesn't see a
raised exception — it sees the denial in the event log if it
subscribes to `approval.denied`. The runtime continues; the
behavior author writes a retry-or-escalate behavior if denial
needs a response.

The exception case is misuse of the primitive — passing a
nonexistent approval id to `approve` / `deny` — which fires
`ApprovalNotFoundError`. See
[`failure-model`](failure-model.md) for the broader principle.

## What's related

- [`patches`](patches.md) — the durable-change primitive that
  policies gate. Approvals and patches share the proposed-and-
  decided shape; patches are the lower-level primitive.
- [`behaviors`](behaviors.md) — where `ctx.propose_object` is
  called from.
- [`failure-model`](failure-model.md) — why denials are events.
- [`approval-not-found-error`](../reference/errors/approval-not-found-error.md)
  — the exception for misuse of the approval API.
- [Operating in production](../guides/operating-in-production.md)
  — production workflows for the operator side.
