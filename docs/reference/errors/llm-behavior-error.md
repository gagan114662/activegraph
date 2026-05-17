# LLMBehaviorError

An `@llm_behavior` failed during a goal run. The provider returned
something the framework can't use (couldn't parse, didn't match the
declared schema, no fixture for the prompt), or the call itself
failed (rate limit, network).

The error you see is a **carrier** — the runtime catches it inside
the behavior dispatch and emits a `behavior.failed` event with the
same `reason` and `payload_extras`. Downstream behaviors subscribed
to `behavior.failed` can react. The exception only surfaces to your
code if you're calling the behavior directly (rare; most code runs
through `runtime.run_goal()` and reads the trace).

See [`failure-model`](../../concepts/failure-model.md) for why
behavior failures are events, not exceptions you have to catch.

## Quick fix by category

Group the reason codes by what you do about them — the framework
distinguishes ~5 reasons but the recovery shapes cluster.

### Failures you can't fix in code: retry

`llm.network_error`, `llm.rate_limited`. The provider is briefly
unavailable. The right pattern is a **retry behavior** that
subscribes to `behavior.failed` and re-fires the work with backoff:

```python
@behavior(
    name="llm_retry",
    on=["behavior.failed"],
    where={
        "behavior": "your.behavior.name",
        "reason": ["llm.network_error", "llm.rate_limited"],
    },
)
def llm_retry(event, graph, ctx):
    attempt = (event.payload.get("attempt") or 0) + 1
    if attempt > 3:
        return
    graph.emit("retry.requested", {
        "for_event": event.payload["triggering_event_id"],
        "attempt": attempt,
    })
```

Retries are first-class graph citizens (CONTRACT v0.6 #13), not
buried in framework middleware. You see every retry in the trace
and can fork from any of them.

### Failures from your prompt: tighten the prompt

`llm.parse_error`, `llm.schema_violation`. The provider returned
something, but it wasn't valid JSON or didn't match the behavior's
`output_schema`. Tighten the prompt so the model produces the right
shape:

- Lower `temperature` if available; reduce sampling variance.
- Add an explicit example of the expected JSON in the prompt.
- Tighten the Pydantic schema to reject ambiguous shapes earlier
  (e.g., `Literal[...]` instead of `str` for enum-shaped fields).

The full provider response is in the `behavior.failed` event's
`payload_extras`:

```bash
activegraph inspect <store> --event <behavior.failed-id>
```

### Failures from fork/replay: re-record

`llm.fixture_missing`. You're running against `RecordedLLMProvider`
and the prompt's hash doesn't match any recorded response. Either
the prompt changed since the fixtures were recorded or this is a
new prompt that was never recorded.

```bash
# Re-record live, then run again against the recorded provider:
ANTHROPIC_API_KEY=... python your_script.py   # records as it runs
```

This is the same fix as [`ReplayDivergenceError`](replay-divergence-error.md)'s
prompt_hash mismatch — the cache contract is the same on both sides.

## How to diagnose

The reason code is in the error's `.reason` attribute and in the
emitted event's payload:

```python
try:
    rt.run_goal("...")
except LLMBehaviorError as e:
    print(e.reason)            # 'llm.parse_error', etc.
    print(e.payload_extras)    # full provider response, raw text, etc.
```

In the trace, look for the `behavior.failed` event the runtime
emitted in your behalf:

```
[behavior.failed]   evt_NNN  your.behavior  reason=llm.parse_error
```

The recovery flow always starts there. The error's `More:` link
points at this page; the trace event points at the behavior that
fired the carrier.

## When does this fire

Inside an `@llm_behavior` wrapper, after the provider returned (or
raised) and before the behavior body's output is merged back into
the graph. The framework catches it, emits `behavior.failed`, and
moves on — the goal run doesn't halt. The exception only escapes
to your code if you're invoking the behavior outside of
`runtime.run_goal()` / `run_until_idle()`.

## Why the framework refuses to continue (the behavior, not the run)

The runtime treats LLM failures as graph-level events because LLM
behavior is inherently flaky and "halt the entire goal on first
provider hiccup" is the wrong default for long-running agentic
work. The failure is captured in the audit trail with full context
(reason, payload_extras, behavior name, triggering event); downstream
code subscribes if it wants to react, ignores if it doesn't.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle and [`tool-error`](tool-error.md) for the sibling
on the tool side.

## What's related

- [`tool-error`](tool-error.md) — if the failure came from the tool
  side rather than the LLM side, see here. The carrier shape is
  symmetric.
- [`unknown-tool-error`](unknown-tool-error.md) — for the
  registration-time variant: an LLM behavior declared a tool that
  isn't registered.
- [`failure-model`](../../concepts/failure-model.md) — why
  `behavior.failed` is an event rather than an escaped exception.
