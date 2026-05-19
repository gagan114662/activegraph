# RuntimeContextRequiredError

`ctx.propose_object` (or another `ctx` method that requires the
runtime) was called from a behavior whose context isn't bound to a
runtime. This usually means a developer is testing a behavior in
isolation, or has lifted code out of a behavior into a helper that
gets called from somewhere a runtime-bound ctx isn't available.

This is an **exception**, not an event, because the caller can fix
it at the call site — see
[`failure-model`](../../concepts/failure-model.md) for the
events-not-exceptions principle. A behavior calling a runtime-only
method without a runtime is a misuse the framework catches; it's
not a non-fatal stop the audit trail should record and continue
past.

## Quick fix

Drive the behavior through a real Runtime — the `ctx` is built from
the runtime's context factory and bound automatically:

```python
from activegraph import Runtime, Graph

rt = Runtime(Graph(), llm_provider=...)
rt.run_goal("...")   # behaviors fire with ctx bound to rt
```

In a test, the canonical pattern is to construct a real Runtime
rather than mock the `ctx` directly:

```python
def test_my_behavior():
    rt = Runtime(Graph(), llm_provider=RecordedLLMProvider(...))
    rt.run_goal("trigger event")
    # Assert on rt.graph state, behavior.failed events, etc.
```

If the test really needs to bypass the runtime — for instance to
test a behavior's pure logic without firing it through a goal — mock
the policy gate (`ctx.propose_object` returns a fake id, or the
behavior path that calls it is mocked out) so `propose_object` isn't
reached at all. Don't mock the ctx and call a real runtime-bound
method on it.

## How to diagnose

The error names the offending ctx method:

```
RuntimeContextRequiredError: ctx.propose_object requires a
runtime-bound context

What failed:
  A behavior called ctx.propose_object on a BehaviorGraph context
  that was constructed without a Runtime — likely a test fixture
  that stubbed the graph without going through Runtime.
```

From code:

```python
try:
    behavior(event, graph, ctx)
except RuntimeContextRequiredError as e:
    print(e.method)   # 'ctx.propose_object'
```

If the error fires in test code, the most likely cause is a stub
graph or mocked ctx; check the test fixture's setup.

If it fires in production code, the most likely cause is a helper
function refactored out of a behavior body that's now being called
from a place where the ctx isn't a runtime-bound one — for
instance, a setup hook that runs before `run_goal` or a CLI command
that builds objects directly.

## When does this fire

At any `ctx`-method call that requires the runtime (currently
`propose_object`; v1.1 may add others). The check runs at the top
of the method, before any side effect.

The runtime constructs a runtime-bound `ctx` automatically for
every behavior fire. The error fires only when a behavior body
runs through a code path the runtime didn't initiate — test
fixtures, isolated invocations, helper functions called from
non-behavior contexts.

## Why the framework refuses to continue

`ctx.propose_object` writes to the runtime's pending-approvals
queue and emits an `approval.proposed` event. Without a runtime,
neither side effect can happen, and a no-op would silently break
the policy gate the behavior depends on — the audit trail would
show no proposal and the operator would have no record to approve.

See [`failure-model`](../../concepts/failure-model.md) for when the
framework prefers exceptions over silent no-ops. This is the
canonical example: a misuse the caller can fix at the call site,
where silently doing nothing would corrupt the audit trail.

## What's related

- [`invalid-patch-lifecycle-state`](invalid-patch-lifecycle-state.md)
  — the sibling ExecutionError for "the caller misused a runtime
  primitive." Both fire mid-execution, both are caller-correctable.
- [`failure-model`](../../concepts/failure-model.md) — why these
  are exceptions, not events.
- [`concepts/policies`](../../concepts/policies.md) — the approval
  lifecycle that `ctx.propose_object` participates in.


---

See [Observing failures in caller code](../../concepts/failure-model.md#observing-failures-in-caller-code)
for `Runtime.errors` and the `BehaviorFailure` shape.
