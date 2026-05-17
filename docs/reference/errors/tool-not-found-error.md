# ToolNotFoundError

`rt.get_tool(name)` couldn't resolve the name to a registered tool.
The framework refuses to fall back to a fuzzy match because the
tool's input/output schema is part of the contract — invoking the
wrong tool with the right name would silently produce wrong-shape
data.

Multi-inherits `LookupError` for back-compat — code that does
`except LookupError` around tool lookups continues to work.

The name resolution rule (canonical strict, lookup lenient) is
defined on [`ambiguous-behavior-error`](ambiguous-behavior-error.md)
and applies symmetrically to tool names. See also
[`ambiguous-tool-error`](ambiguous-tool-error.md).

## Quick fix

Check the spelling and the pack:

```python
# Tools are exposed alongside behaviors:
status = rt.status(recent=0)
# Inspect the runtime's tool registry directly:
print(list(rt.tool_registry.keys()))
```

Common causes:

- **The tool's pack isn't loaded.** Load it:
  ```python
  rt.load_pack(my_pack, settings=...)
  ```
- **The `@tool` decorator hasn't run.** Tools register at
  module-import time. Import the module before constructing the
  Runtime, or pass the tool explicitly via `Runtime(tools=[...])`.
- **You used a short name when canonical was needed.** If the tool
  comes from a pack, use `pack_name.tool_name`. See
  [`ambiguous-behavior-error`](ambiguous-behavior-error.md) for the
  resolution rule.

## How to diagnose

The error names the offending name and the registered tools:

```
ToolNotFoundError: no tool named 'fetch_pdfs' is loaded

What failed:
  rt.get_tool('fetch_pdfs') could not resolve the name to a
  registered tool.
    registered: 'diligence.fetch_company_docs',
                'diligence.fetch_filings'
```

From code:

```python
try:
    t = rt.get_tool("fetch_pdfs")
except ToolNotFoundError as e:
    print(e.name)         # 'fetch_pdfs'
    print(e.registered)   # registered tool names
```

If `registered` is empty, no tools are registered at all — likely
an import ordering problem.

## When does this fire

At `rt.get_tool(name)` and equivalent lookups. The runtime's
LLM-tool-loop has its own path that uses the canonical name
resolved at `@llm_behavior` registration; if the LLM asks for a
tool the behavior didn't declare, you get
[`unknown-tool-error`](unknown-tool-error.md) instead — different
error, different recovery.

## Why the framework refuses to continue

Tools are addressable by their declared name. The runtime refuses
to fall back to a fuzzy match because the tool's input/output
schema is part of the contract — a fuzzy match could invoke a tool
with a different schema than the caller expected, silently
producing wrong-shape data. The Pydantic validation that runs on
every tool call would fail with a different (less helpful) error,
or worse, would pass on coincidentally-compatible shapes.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`ambiguous-tool-error`](ambiguous-tool-error.md) — fires when a
  short name resolves to two different tools across loaded packs.
- [`behavior-not-found-error`](behavior-not-found-error.md) — the
  symmetric case for behavior lookups.
- [`missing-tool-error`](missing-tool-error.md) — the
  construction-time variant for when an `@llm_behavior` declares a
  tool that isn't registered.
- [`unknown-tool-error`](unknown-tool-error.md) — the runtime
  variant for when an LLM asks for an undeclared tool inside a
  declared behavior.
