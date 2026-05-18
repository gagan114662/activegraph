# v1.0-rc1 → v1.0 final handoff

This document is the working context for the next session (human or
agent) picking up v1.0 final work. It's a working artifact, not a
user-facing reference — the doc site at
[docs.activegraph.ai](https://docs.activegraph.ai/) is for users;
this is for whoever drives the framework forward from here.

Read it first. Then read CONTRACT.md. Then start.

## Current state (as of v1.0-rc1 merge)

v1.0-rc1 is the current state of the framework, tagged on the
`9f9ea19` merge commit. Five PRs landed across one session: the
`activegraph quickstart` command, the 10-minute tutorial at
`docs/quickstart.md`, the mypy `--strict` CI gate, the docstring
coverage CI gate, and the CHANGELOG covering v0 → v1.0 with the
legacy-guide audit folded in. Four content gates are now live:
version-sync, broken-link, mypy `--strict` (22/38 allowlist modules
clean), docstring coverage (Ring 0 92/100 not-missing, Ring 1 at
84.7%). The doc site carries the long-form reference; the README is
the conversion funnel. v1.0 final is gated only on the
externally-owned user-test (CONTRACT v1.0 #C4); when the test runs
and its findings land, v1.0 final ships as either rc1-promoted-to-
final or rc2-with-fixes-then-final.

## CONTRACT.md is the source of truth

Every milestone (v0, v0.5, v0.6, v0.7, v0.8, v0.9, v0.9.1, v1.0,
v1.1-staged) has its own section in
[`CONTRACT.md`](CONTRACT.md). Every locked decision is numbered
(`#1`, `#2`, …, `#C1`, …). Every revision against an original plan
is documented as a diff with the reasoning. Work that contradicts
CONTRACT without a documented revision is drift.

When a new decision needs locking, amend CONTRACT in the same
commit that lands the code. The v1.0 decisions C1–C7 are the
pattern: seven pushbacks against the original v1.0 plan, all locked
into CONTRACT before the implementation commits. The CHANGELOG
records what shipped; CONTRACT records what was decided and why.

## Discipline patterns

Process decisions that produced this codebase. Carry them forward.

- **Killer demo / spec written first; implementation built
  backward.** `examples/llm_claim_extraction.py` (v0.6),
  `examples/diligence_real_run.py` (v0.9), and
  `examples/quickstart_session.txt` (v1.0) were each a locked spec
  before the code existed.
- **Audit-then-baseline-then-narrow for gates.** mypy and docstring
  both followed this: an audit script produces a report
  (`TYPE_REPORT.md`, `COVERAGE_REPORT.md`); the gate locks at
  current reality with explicit exemptions; future regressions fail
  CI. The broken-link gate is the same shape over doc-site URLs.
- **Single-source-of-truth anchors for cross-referenced content.**
  Each invariant gets exactly one canonical home: resolution-rule
  prose on `ambiguous-behavior-error`, patch lifecycle on
  `patches.md`, pack-conflict semantics on `pack-conflict-error`.
  Other pages reference — they don't duplicate.
- **Sibling-pair cross-references as doc-site idiom.** Locked
  during the per-error series. Each concept page links its sibling
  error page; each error page links its concept and its cookbook
  recipe.
- **Series-of-PRs with audit discipline over single mechanical
  rewrites.** The PR-A through PR-G error series produced findings
  a one-shot rewrite would have shipped wrong (PR-F's
  cross-category reclassification, PR-G's framework-bug voice).
  Audit findings only surface when each batch is treated as an
  independent step with its own pre-commit pass.
- **Events-not-exceptions as both runtime principle and audit
  instrument.** Locked in CONTRACT v1.0 #4b after PR-D surfaced it.
  A behavior failure is a `behavior.failed` event; exceptions live
  at runtime entry points only. "Is this code raising or emitting?"
  is the audit question that surfaces inconsistent handling.
- **"What not to build in this milestone" lists as discipline, not
  afterthought.** Every milestone has one. Out-of-scope items get
  scheduled, not skipped — v1.1 picks up the v1.0 deferrals.
- **Forward-references resolve in subsequent commits; broken-link
  CI gate is the burndown meter.** Pages reference future pages;
  the gate counts unresolved targets and burns down as pages land.
- **No new runtime capability in v1.0.** The milestone was the
  adoption surface (errors, docs, quickstart, gates) over existing
  primitives. v1.1 is where capability returns.

## Known v1.1 scope

The running gap-list. CONTRACT v1.1 expands this into a proper
milestone scope when v1.1 work begins.

- **CONTRACT v1.1 #1** — implement `fork --set <pack>.<key>=<value>`,
  `inspect --memo`, `inspect --search`. All three are spec'd in v1.0
  docs but unimplemented; the quickstart tutorial works around
  `--set` with the Python-API form at
  `docs/cookbook/common-patterns.md#fork-with-a-pack-setting-override-v10-python-api`.
- **CONTRACT v1.1 #2** — spec-vs-impl drift gate for CLI flags.
  Prevents v1.1 #1's shape from recurring.
- **CONTRACT v1.1 #3** — type-completeness. Close the 16 dirty
  modules in `TYPE_REPORT.md`. `converge_clean_set()` in
  `scripts/audit_types.py` is the same tool that ratchets each
  module forward.
- **CONTRACT v1.1 #4** — docstring-completeness. Wave 1: close the
  8 Ring 0 exemptions in `docstring_gaps.toml`. Wave 2: upgrade
  Ring 0 one-liners to full per `COVERAGE_REPORT.md`. Ring 1
  burndown follows the audit.
- **22 partial Pack\* migrations from PR-E** — error-rewrite
  series' deferred work.
- **4 deferred DB-error wrappers from PR-C.**
- **2 internal-evaluator errors needing framework-version context
  from PR-G.**
- **User-test gate findings (TBD).**

## Voice ceiling

Active, declarative, name the invariant being protected.

Four voice modes across the doc site:

- **Reference** (per-error pages, CLI reference) — debugger-first.
  The reader has a problem; cut to the fix.
- **Concepts** — name the primitive, name what it does, name what
  it doesn't.
- **Cookbook** — how-to. Copy-pasteable code with the why
  annotated.
- **Tutorial** (`quickstart.md`) — conversational, beats over
  sections, one fresh-eyed reader's journey.

Process: write each page in one sitting; start with the hardest
page in a batch — it sets the voice floor and the rest fall into
the same key. Read any sequence (across writers, across milestones)
as if from one author; voice consistency is the test. This is the
discipline that produced 12 concepts pages + 33 error pages + 3
cookbook pages + 1 CLI mega-page + 1 tutorial reading as one author
throughout.

## User-test gate procedure

Per CONTRACT v1.0 #C4. Externally owned — the agent loop cannot
run this.

Find one Python-fluent developer who hasn't seen the framework.
Watch them, screen-recorded, through:

1. `pip install activegraph`
2. `activegraph quickstart` — fixture-backed demo
3. `activegraph quickstart --interactive` — write a behavior
4. The tutorial's step 7 Python snippet (fork-and-diff)

Note every hesitation, mis-type, confused moment, abandoned tab.
Don't help mid-stream. Findings are the raw material for v1.0 final
scope.

## What's likely vs unlikely from the user-test

Document this so the next session doesn't over-react to small
findings or under-react to architectural ones.

**Likely:**

- A confusing line in quickstart output ("what does X mean?").
- A tutorial step that lands differently than expected (one beat
  needs an extra sentence).
- An error message recovery that doesn't match a real user's first
  instinct.
- A small CLI ergonomic gap (defaults, help text, output
  formatting).

**Unlikely:**

- Architectural changes — the framework's shape has survived 12
  milestones of scrutiny.
- Public-API renames — `__all__` is locked via the mypy gate.
- The pack format wanting to be a manifest after all — locked
  CONTRACT v0.9 #4.

Heuristic: if a finding has the shape "X is confusing," it's UX —
adjust prose or output. If it has the shape "X doesn't compose
with Y the way I expected," investigate — that might be
architectural.

## rc2 vs v1.0 final — decision tree

Don't speculate before the test runs.

- **Zero findings, or 1–2 typo-level items** — tag v1.0 final
  directly with the small fixes folded in.
- **Three or more items, or one non-trivial item** — v1.0-rc2 with
  the fixes, a lightweight re-gate pass (the user-test re-runs only
  if fixes touched what they hit), then v1.0 final.
- **Architectural finding** — stop the train. The
  CONTRACT-amendment-first discipline applies: name the new
  decision, lock it in CONTRACT, then code.

## Working with the agent loop

Patterns that worked. Carry them forward.

- **Structured PR descriptions over freeform.** "Discipline notes"
  + numbered findings + structured next-step section made every
  commit a working contract.
- **Contract-amendments-before-code.** Locking decisions before
  implementing reduced reverse-engineering work and produced
  cleaner commits.
- **Reverse-audit order for batched work.** Fix the hardest first;
  the rest fall in line.
- **"Discipline notes" sections in every prompt.** Set the voice
  ceiling per-commit, not per-milestone.
- **Agent pushback as a feature.** The seven v1.0 revisions from PR
  pushback became CONTRACT v1.0 C1–C7. Treat resistance to the plan
  as signal, not friction.

Patterns that didn't. Flag them explicitly when they recur.

- **Trying to fix things outside the loop's verification scope.**
  The user-test gate is externally owned for a reason. The loop
  cannot evaluate whether a quickstart line is confusing to a
  first-time reader; only a first-time reader can.
- **Assuming spec equals impl without verification.** The `--set`
  flag was spec'd in docs but never implemented; caught during the
  tutorial work. v1.1 #2 is the gate that prevents recurrence.
- **Letting the burndown counter stay implicit.** The broken-link
  burndown was opaque until the test made the count explicit.
  Every gate should expose its current state as a number, not just
  a pass/fail.

## Closing

Twelve milestones of audit-discipline shipped a framework that
survives scrutiny at every layer the agent loop can scrutinize.
The user-test is the layer the loop can't scrutinize, and it's the
most important one.

If the next session is a fresh agent: start with CONTRACT.md, then
CHANGELOG.md, then this document, then the user-test findings.
Don't try to recompound twelve milestones of context — work from
the artifacts. The framework is built; the work from here is
landing it.

If the next session is a human: same order. The artifacts are the
context.
