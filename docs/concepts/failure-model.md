# Failure model

The framework distinguishes two kinds of failure, and the distinction
governs how you write behaviors, how you read errors, and how you build
on top of the runtime.

## The principle

> **Exceptions are for caller-facing failures the caller can reasonably
> catch and act on. Non-fatal stops — budget exhaustion, behavior
> failures, tool failures, approval denials — are events in the log.
> The distinction: exceptions interrupt control flow; events extend the
> audit trail. When in doubt, an event.**

Behaviors that fail during a run don't raise out to your code. The
runtime catches the exception, emits a `behavior.failed` event with
the original exception's type, message, and `reason` code in the
payload, and the loop continues. Other behaviors keep firing. The
operator sees the failure in the trace; downstream code that subscribes
to `behavior.failed` can react (alert, retry-with-different-args, escalate).

The same shape applies to tools: a `ToolError` raised inside a tool
body becomes a `tool.responded` event with `error.reason` set, and the
calling behavior's loop reads the structured failure and decides what
to do.

The same shape applies to budget exhaustion: when a `max_*` limit is
hit, the runtime emits `runtime.budget_exhausted` with the dimension
in the payload and stops gracefully. No exception escapes to your
code — you read the event from `runtime.status()` or from the trace.

## When exceptions are the right answer

Exceptions are for failures the caller is making **right now, at this
line of code**, and can reasonably catch:

- Constructing a runtime with conflicting arguments
  (`InvalidRuntimeConfiguration`)
- Looking up a behavior or tool that isn't registered
  (`BehaviorNotFoundError`, `ToolNotFoundError`)
- Passing a malformed store URL (`InvalidStoreURL`)
- Replaying a run whose recorded event stream doesn't match the live
  re-run (`ReplayDivergenceError`)
- Calling `runtime.approve(id)` on an id that doesn't exist
  (`ApprovalNotFoundError`)

These all interrupt the call. The caller catches the exception, fixes
the input, and tries again. There's no audit-trail entry to preserve
because the call never produced one.

## The exception hierarchy

Every framework exception inherits from `ActiveGraphError`. Seven
categories live one level down:

```
ActiveGraphError
├── ConfigurationError      construction-time / API-call argument errors
├── RegistrationError       behavior/tool/pack registration problems
├── ExecutionError          runtime execution problems (escaped to the caller)
├── ReplayError             replay/fork divergence
├── StorageError            persistence problems
├── PatternError            pattern subscription syntax errors
└── PackError               pack-specific runtime problems
```

Catch `ActiveGraphError` to catch every framework exception. Catch a
category base to catch every leaf in that category. Catch a specific
leaf when the recovery is leaf-specific.

The category leaves also multi-inherit from Python builtins where it
preserves existing catch sites: `EventNotFoundError` is also a
`KeyError`, `InvalidStoreURL` is also a `ValueError`, etc. Existing
code catching the builtin keeps working; new code can catch the
category for richer context.

## The structured event types

`behavior.failed`, `tool.responded` (with error), `runtime.budget_exhausted`,
`approval.denied` — each carries a `reason` field with a stable
discriminator code so downstream code can branch on the failure mode
without parsing prose. The codes are documented in
[Reference: Events](../reference/events/).

## "When in doubt, an event"

If you're writing a behavior and you're about to raise an exception
because something downstream "should never happen," ask:

- Can the caller reasonably catch and act on this?
- Is the failure attributable to a specific event in the log?

If the answer to the first is "no" and the answer to the second is
"yes," emit an event instead. The audit trail is the durable record;
exceptions are just the runtime's way of refusing the current call.

This rule is what kept `BehaviorFailedError` and `BudgetExhaustedError`
out of the framework's exception hierarchy. Both were considered
during the v1.0 error-rewrite series and rejected because their
information already lives in events. Adding them as exceptions would
have surfaced two parallel failure surfaces — one in the trace, one in
caller code — and the divergence is exactly the kind of subtle
inconsistency that makes a framework feel unreliable six months in.
