# MissingToolError

An `@llm_behavior` declares a tool name that the runtime's tool
registry doesn't have. The framework refuses to start the runtime
rather than discover the missing tool at first LLM-call time — the
behavior would either produce
[`unknown-tool-error`](unknown-tool-error.md) on every invocation
(cost without progress) or silently drop the call.

Fires at Runtime **construction time**. The check runs once when the
behavior registers; misconfiguration fails before any LLM call burns
budget.

## Quick fix

Register the missing tool with the runtime:

```python
from activegraph import Runtime, Graph
from activegraph.tools import tool

@tool(name="web_search", input_schema=..., output_schema=...)
def web_search(args, ctx):
    ...

rt = Runtime(
    Graph(),
    llm_provider=...,
    tools=[web_search],   # ← register here
)
```

If the tool comes from a pack, load the pack instead:

```python
rt.load_pack(my_pack, settings=...)
```

For pack-scoped tools, the canonical name (`pack_name.tool_name`)
in the `@llm_behavior`'s `tools=[...]` ensures the right tool
resolves even when multiple packs are loaded — see
[`ambiguous-tool`](ambiguous-tool-error.md).

## How to diagnose

The error names the missing tool, the behavior that declared it,
and the tools that *are* registered:

```
MissingToolError: no tool named 'web_search' is registered

What failed:
  @llm_behavior declares the tool 'web_search' on @llm_behavior
  'diligence.researcher', but the Runtime's tool registry has no
  tool by that name.
    registered tools: 'diligence.fetch_company_docs',
                      'diligence.fetch_filings'
```

From code:

```python
try:
    rt = Runtime(Graph(), llm_provider=..., tools=[...])
except MissingToolError as e:
    print(e.tool_name)        # 'web_search'
    print(e.behavior_name)    # 'diligence.researcher'
    print(e.registered)       # what's registered
```

Compare `registered` against the behavior's declared tools — the
gap is your missing registration.

## When does this fire

At `Runtime(...)` construction, after the behavior registry and
tool registry are both populated, before any goal runs. The check
walks every `@llm_behavior`'s `tools=[...]` and verifies each name
resolves in the tool registry.

The runtime-time variant — when the LLM asks for a tool the
behavior didn't declare — is [`unknown-tool-error`](unknown-tool-error.md),
not this. The distinction is the same one called out on the
`unknown-tool-error` page: registration-time mismatch (this page)
vs LLM-call-time mismatch (other page).

## Why the framework refuses to continue

`@llm_behavior` validates its declared tools at startup so a
misconfiguration fails before any LLM call burns budget. A missing
tool at LLM-call time would either produce `UnknownToolError` on
every invocation (cost without progress) or silently drop the call
(which would corrupt the audit trail). Validation at registration
prevents both.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`unknown-tool-error`](unknown-tool-error.md) — the runtime-time
  variant. Fires at LLM-call time when the LLM asks for a tool not
  in the behavior's declared set. Read both if you're debugging
  LLM-tool plumbing.
- [`missing-provider-error`](missing-provider-error.md) — the
  symmetric registration-time error for LLM providers.
- [`tool-not-found-error`](tool-not-found-error.md) — fires at
  explicit `rt.get_tool(name)` lookups (operator-side, not
  registration-side).
