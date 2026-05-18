# InternalEvaluatorError

**This is a framework bug, not a problem with your code.** A
framework-internal evaluator received input it doesn't recognize —
specifically, a comparison operator or AST node that the parser
produced (or that user code injected via an AST shortcut) but the
evaluator's dispatch table doesn't handle.

In normal use, this never fires. The framework's parsers produce a
closed set of operators and AST nodes; the evaluators handle every
member of that set. An unrecognized one means the parser and the
evaluator are out of sync, or external code constructed an AST that
bypassed the parser. Either way, the runtime would have to silently
mis-evaluate the input to continue — which would corrupt the audit
trail in a way you'd discover much later.

## Quick fix: file an issue

The error message includes the framework version, the internal
location (module:function), and the offending input. Copy the body
into a new GitHub Issue:

```
https://github.com/yoheinakajima/activegraph/issues/new
```

Include the pattern, filter, or AST that triggered the error if
possible. The error's `context` dict carries everything the issue
template needs:

```python
try:
    ...
except InternalEvaluatorError as e:
    print(e.context["framework_version"])
    print(e.context["internal_error_location"])
    # Plus per-site context, e.g.:
    print(e.context.get("operator"))         # patterns.py / graph.py
    print(e.context.get("ast_node_type"))    # patterns.py only
```

## Immediate workaround

Until the bug is fixed, the framework can't proceed past the
offending evaluation. Two paths work for most cases:

- **Simplify the pattern or filter that triggered it.** If the
  error fires on a complex pattern subscription, try a shorter
  version that matches the same intent. The framework supports a
  closed subset; an evaluator failure usually means the AST contains
  a node the supported subset doesn't include.
- **Catch and continue.** If the offending evaluation is non-critical
  (a view filter that can be skipped, an optional pattern subscription),
  catch `InternalEvaluatorError` at the call site and skip the
  evaluation. Code that does `except ValueError` around view
  operations continues to work — `InternalEvaluatorError`
  multi-inherits `ValueError` for back-compat.

## How to diagnose

The error's `internal_error_location` field names which evaluator
fired:

- `activegraph/runtime/patterns.py:_eval_where (unknown comparison operator)` —
  the WHERE evaluator hit an unsupported operator while evaluating
  a pattern subscription's WHERE clause.
- `activegraph/runtime/patterns.py:_eval_where (unrecognized AST node)` —
  the WHERE evaluator hit an AST node type it doesn't handle.
- `activegraph/core/graph.py:evaluate_where` — the view-filter
  evaluator hit an unsupported operator while evaluating a view's
  WHERE filter.

All three sites use the shared `internal_bug_fields` helper so the
message shape and context-dict keys are identical. A GitHub Issue
filed from any of them arrives with the same metadata for triage.

## Why the framework refuses to continue

The operator table (`_OPS`) and the AST node set are closed and
produced by the framework's parsers. An unrecognized operator or
node means either the parser drifted from the evaluator (a
framework-internal inconsistency) or the AST was constructed
externally (bypassing the parser's validation). Both would produce
silent mis-evaluation if the runtime continued — the WHERE filter
would silently match or mismatch input it wasn't supposed to, and
the audit trail wouldn't record that anything went wrong.

The framework refuses to evaluate rather than risk it. This is the
invariant-protection stance applied to the framework's internal
state, not just user input — see
[`failure-model`](../../concepts/failure-model.md) for the broader
principle.

## What's related

- [`failure-model`](../../concepts/failure-model.md) — the
  invariant-protection principle. This page is the framework
  applying that principle to its own internals.
- [GitHub Issues](https://github.com/yoheinakajima/activegraph/issues/new)
  — file framework-bug reports here. The error message carries
  everything the issue needs.
