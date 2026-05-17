# MissingProviderError

You constructed a `Runtime` with `@llm_behavior`-decorated behaviors
in the registry, but didn't pass an `llm_provider=` argument. The
framework refuses to dispatch LLM behaviors without a provider —
silently no-op'ing them would produce events that claim to depend on
an LLM call that never happened.

Fires at Runtime **construction time**, not at first LLM call.
The validation runs once when the runtime initializes.

## Quick fix

Pass an `llm_provider=` to the Runtime constructor:

```python
from activegraph import Runtime, Graph
from activegraph.llm.anthropic import AnthropicProvider

rt = Runtime(
    Graph(),
    llm_provider=AnthropicProvider(),
)
```

For offline replay or tests, use a recorded or scripted provider
instead of a live one:

```python
from activegraph.llm.recorded import RecordedLLMProvider

rt = Runtime(
    Graph(),
    llm_provider=RecordedLLMProvider(fixture_dir="path/to/fixtures"),
)
```

## How to diagnose

The error names which `@llm_behavior` triggered the check:

```
MissingProviderError: no LLM provider configured for @llm_behavior

What failed:
  An LLM-backed behavior ('diligence.researcher') was registered,
  but Runtime(...) was constructed without an `llm_provider=`
  argument.
```

From code:

```python
try:
    rt = Runtime(Graph(), behaviors=[...])
except MissingProviderError as e:
    print(e.behavior_name)   # 'diligence.researcher'
```

If `behavior_name` is unset, no specific behavior was named — the
runtime found at least one `@llm_behavior` in its registry but
didn't track which one in the check.

## When does this fire

At `Runtime(...)` construction, after the behavior registry is
populated and before any goal runs. The check walks the registry
once and fails fast if any `@llm_behavior` is present without a
provider.

This is deliberate (CONTRACT v0.6 #21): silently no-op'ing the
behavior at first LLM call would produce events that claim to
depend on an LLM call that never happened. Failing at construction
makes the misconfiguration immediately visible.

## Why the framework refuses to continue

`@llm_behavior` dispatches LLM calls through the provider attached
to the runtime at construction. Failing loud at registration rather
than at first invocation is the v0.6 contract — silently no-op'ing
the behavior would corrupt the audit trail (behaviors fire and
produce events; a missing provider would produce events that claim
to depend on an LLM call that never happened).

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`missing-tool-error`](missing-tool-error.md) — the symmetric
  registration-time error for tools. Fires when an `@llm_behavior`
  declares a tool name that isn't registered.
- [`missing-optional-dependency`](missing-optional-dependency.md) —
  fires when `AnthropicProvider()` itself can't construct because
  the `anthropic` SDK isn't installed.
- [`llm-behavior-error`](llm-behavior-error.md) — the runtime-time
  carrier for when a configured provider's call fails.
