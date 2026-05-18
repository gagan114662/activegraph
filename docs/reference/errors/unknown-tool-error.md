# UnknownToolError

**This is not a tool execution failure.** An LLM response asked to
invoke a tool whose name isn't declared on the calling
`@llm_behavior`'s `tools=[...]` argument. The runtime refuses any
tool call that isn't in the declared set — an undeclared tool could
perform side effects the behavior's audit trail doesn't account for,
which would break replay determinism.

If you're looking for the error that fires when a declared tool fails
to execute, see [`tool-error`](tool-error.md) instead.

The runtime catches `UnknownToolError` inside the tool-loop and
surfaces it as `behavior.failed reason="tool.unknown_tool"`.

## Quick fix

Two paths depending on whether the LLM should be calling the tool:

### The LLM should be calling this tool — declare it

Add the missing tool to the behavior's `tools=[...]`:

```python
@llm_behavior(
    name="diligence.researcher",
    tools=[
        fetch_company_docs,
        fetch_filings,
        web_search,          # ← add this
    ],
    ...
)
```

Confirm the tool itself is registered with `@tool` (or passed via
`Runtime(tools=[...])`). If the tool's name doesn't appear in
`activegraph inspect <run> --behaviors`, the registration didn't
take — usually a missing import.

### The LLM shouldn't be calling this tool — tighten the prompt

If the model is consistently asking for an undeclared tool, the
prompt is implying capabilities the behavior doesn't have. Be
explicit about which tools are available:

```python
description=(
    "Research a company using ONLY the declared tools. "
    "If a question requires capabilities outside this set, return a "
    "structured 'unanswered' response and let downstream behaviors "
    "handle it. Do not invent tool calls."
)
```

## How to diagnose

The error message names three things — the tool requested, the
behavior that triggered the call, and the tools the behavior
declared:

```
What failed:
  An LLM response asked to invoke a tool that the calling behavior
  did not declare.
    tool requested: 'web_search'
    declared on behavior 'diligence.researcher':
      'diligence.fetch_company_docs', 'diligence.fetch_filings'
```

From code:

```python
try:
    rt.run_goal("...")
except UnknownToolError as e:
    print(e.tool_name)       # 'web_search'
    print(e.behavior_name)   # 'diligence.researcher'
    print(e.declared_tools)  # ('diligence.fetch_company_docs', ...)
```

The same fields appear in the `behavior.failed` event's
`payload_extras` for downstream code that subscribes to the event.

## Registration-time vs runtime — the distinction matters

Two related errors gate the tool surface:

- [`MissingToolError`](missing-tool-error.md) fires at **runtime
  startup**. An `@llm_behavior` declares a tool name that the
  Runtime's tool registry doesn't have. The check runs once at
  Runtime construction so the misconfiguration fails before any
  LLM call burns budget.
- **`UnknownToolError` (this page)** fires at **LLM-call time**. The
  declared tools are all registered, but the LLM asked for one
  that's not in the declared set for *this specific behavior*.

Read the error message's `tool requested` field carefully: if it
names a tool you intend the behavior to call, you've hit
`MissingToolError` shape — the tool isn't registered. If it names a
tool you don't expect the LLM to ever call, the prompt is the
problem.

## When does this fire

During an LLM behavior's tool-loop, when the provider returns a
tool call whose `name` isn't in the behavior's declared `tools`. The
runtime emits `behavior.failed reason="tool.unknown_tool"` and the
goal continues — other behaviors keep firing, the LLM behavior
itself doesn't retry automatically (a retry behavior subscribing to
`behavior.failed` is the canonical pattern; see
[`tool-error`](tool-error.md)).

## Why the framework refuses to continue

`@llm_behavior` declares the exact set of tools the wrapped behavior
is allowed to invoke. The runtime refuses any other tool call rather
than silently execute it — an undeclared tool could perform side
effects the behavior's audit trail doesn't account for, and
re-running the behavior in replay would either produce a different
event stream (if the undeclared tool wasn't called) or invoke an
effect the recorded run didn't have.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`tool-error`](tool-error.md) — fires when a declared tool fails
  to execute. The distinction is on this page above; bookmark both
  if you're debugging LLM-driven tool calls.
- [`missing-tool-error`](missing-tool-error.md) — the
  registration-time variant. Fires at Runtime construction when an
  `@llm_behavior` declares a tool that isn't registered.
- [`llm-behavior-error`](llm-behavior-error.md) — the LLM-side
  failure carrier; covers the parse/schema/network reasons.
