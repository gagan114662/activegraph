# AmbiguousToolError

A short tool name resolves to tools in more than one loaded pack.
The runtime can't pick one without an explicit choice — picking
silently would let an `@llm_behavior` call the wrong pack's tool,
with a potentially-different input/output schema.

Symmetric with
[`ambiguous-behavior-error`](ambiguous-behavior-error.md) — same
canonical-strict / lookup-lenient resolution rule (the rule is
defined in detail on that page; this page applies it to tools).

## Quick fix

Use the canonical form `<pack_name>.<tool_name>`:

```python
# Instead of:
t = rt.get_tool("fetch_docs")        # ambiguous if two packs declare it

# Use the canonical form:
t = rt.get_tool("diligence.fetch_docs")
```

If you want an `@llm_behavior` to use a specific pack's version,
list the canonical name in the `tools=[...]` argument:

```python
@llm_behavior(
    name="researcher",
    tools=[
        "diligence.fetch_docs",   # canonical — unambiguous
        "diligence.fetch_filings",
    ],
    ...
)
```

The error message names which packs collided and shows the
canonical form using one of them as a copy-paste example.

## How to diagnose

The error names the conflicting packs:

```
AmbiguousToolError: tool name 'fetch_docs' is ambiguous across
loaded packs

What failed:
  The short tool name 'fetch_docs' resolves to tools in more than
  one loaded pack: 'diligence', 'research'.
```

From code:

```python
try:
    t = rt.get_tool("fetch_docs")
except AmbiguousToolError as e:
    print(e.name)    # 'fetch_docs'
    print(e.packs)   # ('diligence', 'research')
```

`activegraph inspect <store> --behaviors` also lists registered
tools alongside the behaviors that declare them.

## When does this fire

At `rt.get_tool(name)` lookups, and at `@llm_behavior` registration
when the behavior's `tools=[...]` lists a short name that resolves
ambiguously. The check is the same as the behavior-name check —
short names are lenient unless they're ambiguous.

It does NOT fire during an LLM tool-call. The LLM-call path uses the
canonical name the behavior declared, which was already resolved at
registration time. If the LLM tries to call a tool the behavior
didn't declare, you get
[`unknown-tool-error`](unknown-tool-error.md) instead.

## Why the framework refuses to continue

Tool canonical names are unique across loaded packs for the same
reason behavior names are: silent dispatch routing would let an
`@llm_behavior` call the wrong pack's tool, with a potentially-
different input/output schema. Refusing the lookup surfaces the
conflict at registration time rather than producing wrong-shape
data at runtime.

See [`ambiguous-behavior-error`](ambiguous-behavior-error.md) for
the canonical statement of the resolution rule. See
[`failure-model`](../../concepts/failure-model.md) for the broader
principle.

## What's related

- [`ambiguous-behavior-error`](ambiguous-behavior-error.md) — the
  sibling for behavior names. Canonical statement of the
  canonical-strict / lookup-lenient resolution rule lives there.
- [`tool-not-found-error`](tool-not-found-error.md) — the sibling
  for "no tool under any name." Uses the same resolution rule.
- [`unknown-tool-error`](unknown-tool-error.md) — fires at LLM-call
  time when the LLM asks for a tool the behavior didn't declare;
  distinct from this page's lookup-time ambiguity.
