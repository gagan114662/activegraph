# UnsupportedPatternError

The pattern you passed to `@behavior(pattern=...)` uses syntax outside
the v0.7 Cypher subset. The parser refused it at behavior-registration
time — long before any match runs — so the misconfiguration surfaces
before the runtime starts firing behaviors.

The error message names which feature the parser refused (in the
summary line) and the per-feature workaround (in the body). The two
shapes are **refused features** (a recognized Cypher feature the
subset deliberately excludes) and **syntax errors** (the pattern
didn't parse at all).

## Quick fix by kind

### Refused feature

The error message's `What failed:` section names the feature
(`OR`, `OPTIONAL MATCH`, `variable-length path syntax (-[*]-)`, etc.),
and the `How to fix:` section gives the specific workaround for that
feature.

The general pattern: **when the subset refuses a feature, the
workaround is usually to register multiple behaviors instead of one
clever pattern.**

- `OR` in WHERE → register two behaviors, one per branch.
- `OPTIONAL MATCH` → register a second behavior whose pattern is the
  optional sub-pattern.
- Variable-length paths → register N behaviors, one per length.
- `CREATE` / `MERGE` / `SET` / `DELETE` / `DETACH` → patterns don't
  mutate; do the mutation in the behavior body.
- `RETURN` / `WITH` / extra `MATCH` → patterns observe; compose
  pipelines as chained behaviors via emitted events.

The error message itself has the specific recipe for the feature you
hit. The full set is in
[`concepts/patterns.md`](../../concepts/patterns.md#what-the-subset-deliberately-refuses).

### Syntax error

The parser couldn't tokenize or parse the pattern. The error
message's `What failed:` includes the offending token and its
position, and `How to fix:` points at the documented grammar.

```
UnsupportedPatternError: pattern does not parse: unexpected character at position 17

What failed:
  While parsing the pattern: unexpected character at position 17.
    at: '@'
```

Common causes:

- **Missing relationship type.** Use `-[:type]->`, not `-[]->`.
  Relationships always require an explicit type in the v0.7 subset.
- **Missing arrow direction.** Use `-[:type]->` or `<-[:type]-`;
  undirected relationships are refused.
- **Unbalanced brackets.** `(a:type {prop: value` without a closing
  brace produces a parse error at the next token.
- **Reserved keyword as an identifier.** The forbidden-keywords list
  is enforced at tokenization; using one as a variable name fires
  this error.

## How to diagnose

If the error message's `at:` field doesn't make the cause obvious,
print the pattern around the position:

```python
import activegraph
pattern = "your pattern here"
try:
    from activegraph.runtime.patterns import parse
    parse(pattern)
except activegraph.UnsupportedPatternError as e:
    print(f"pattern: {pattern}")
    print(f"position: {e.at!r}")
    print(f"context: {e.context}")
```

`e.at` is the offending token; `e.context` carries the same
information the error message body includes.

## When does this fire

At behavior registration. The parser validates the pattern when
`@behavior(pattern=...)` (or `@llm_behavior(pattern=...)`) runs at
import time. Once a behavior is registered, its pattern is locked —
the runtime never re-parses, so the error fires before the runtime
loop ever starts.

This is a deliberate v0.7 choice (CONTRACT v0.7 #9): patterns are
compiled once, at registration. A pattern that takes too long to
parse, or that uses unsupported syntax, fails the developer's import
rather than the production run.

## Why the framework refuses

The subset is small on purpose. A fuzzy superset of Cypher would let
patterns *appear* to match input they did not actually match. Two
patterns differing only in a refused feature would silently produce
different match sets at runtime, and the audit trail would not
record which pattern actually matched what. The subset is the
contract that makes pattern subscriptions trustworthy.

For the broader principle, see
[`concepts/failure-model`](../../concepts/failure-model.md). For the
locked subset and the rationale per feature, see
[`concepts/patterns`](../../concepts/patterns.md).

## What's related

- [`concepts/patterns`](../../concepts/patterns.md) — the canonical
  reference for what the subset supports and what it refuses, with
  workaround patterns per refusal.
- [`concepts/failure-model`](../../concepts/failure-model.md) — why
  the framework prefers "refuse loudly at registration" to "match
  fuzzily at runtime."
