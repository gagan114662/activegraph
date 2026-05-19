# CONTRACT review findings — post-v1.0.3

Review date: 2026-05-19. Branch: `claude/review-contract-docs-CoaO6`.
Work item: documentation-heavy contract review after v1.0, v1.0.1,
v1.0.2, v1.0.2.post1, v1.0.3 shipped across ~2 weeks. The discipline
that produced those amendments was sound; the cumulative document
needed a coherence pass.

This is the findings record. The companion deliverables are:

- `CONTRACT.md` — revised with status markers and a revision banner.
  Prose preserved; structural archeology kept.
- `v1.1-plan.md` — consolidated v1.1 backlog. CONTRACT now points
  here instead of scattering "filed for v1.1" markers.

No source code changed. Code-shaped findings are filed as v1.0.4
candidates (Section 5) or v1.1 candidates (Section 6) with explicit
cross-references.

---

## Section 1 — Amendments reviewed and outcomes

The table covers every milestone section. Per-item drill-down lives
in the relevant amendment in CONTRACT.md, which now carries status
markers inline. "Spot-check" means the most consequential items
in the milestone were audited; the rest were sampled.

| Milestone | Items | Outcome | Notes |
|-----------|-------|---------|-------|
| v0 | #1–#18 | STILL ACCURATE | #11 (`token_budget` "ignored until v0.6") and #16 (out-of-scope list) read as historical statements; PROSE-CLARIFICATION marker added in CONTRACT. |
| v0.5 | #1–#22 | STILL ACCURATE | #7 known-limitation narrowed by v0.6 #22 (forward-ref added in CONTRACT). #8 "re-queue unfired events" — see Section 4 boundary-mismatch finding. |
| v0.6 | #1–#22 | STILL ACCURATE | #14 trace format superseded incrementally by v0.7 #18 and v0.9.1 #2 — marked SUPERSEDED in CONTRACT. |
| v0.7 | #1–#25 | STILL ACCURATE | #18 partially superseded by v0.9.1 #2 (per-line `prompt_normalized=true` now hidden behind rollup). |
| v0.8 | #1–#19, #C4 | STILL ACCURATE | #11 RuntimeStatus shape extended additively in v1.0.3 #3 (`Runtime.errors` is a property, not a dataclass field; the v0.8 #11 frozen-dataclass invariant is intact). |
| v0.9 | #1–#26 | STILL ACCURATE | Spot-checked #5 (load-order), #10 (prompt hash), #13 (`pack.loaded` event). |
| v0.9.1 | #1–#3 | STILL ACCURATE | Self-marking — #2 explicitly notes "v0.7 #22 backward-compat clause is now superseded for the `llm.requested` line." Good discipline pattern. |
| v1.0 #C1–#C8 | C1–C8 | STILL ACCURATE | #C6 (DNS) carries the rc3 `.dev` → `.ai` amendment inline; archeology preserved. |
| v1.0 #1–#10 | All | STILL ACCURATE | #5 doc-site structure has shipped; the burndown is closed. |
| v1.0 PR-A–PR-G | All | STILL ACCURATE | The "hidden-surface count" tables are historical audit data; final tally of 19 leaves stands. v1.1 forward-refs scattered through PR-E/PR-F/PR-G now point at `v1.1-plan.md`. |
| v1.0 #4b, #4c, #4d | All | STILL ACCURATE | Failure-model principle, voice consistency, broken-link gate — all stable post-shipping. |
| v1.0.1 #1–#5 | All | STILL ACCURATE | #5(c) clauses 1–4 are unambiguous v1.1 candidates → consolidated. |
| v1.0.2 #1 | #1(a)–(d) | STILL ACCURATE post-revision | **Discipline finding: §7 #1.** v1.0.2.post1 corrected the v1.0.2 #1(b) wording in place rather than appending a dated amendment section. The CHANGELOG carries the dated v1.0.2.post1 entry; CONTRACT alone reads as if v1.0.2 always said "both binding moments." A `[revised by v1.0.2.post1]` marker is now in CONTRACT. |
| v1.0.3 #1–#4 | All | STILL ACCURATE | All four findings carry contract-anchored tests (Section 4). v1.1 candidates explicitly named per amendment → consolidated. |
| v1.1 #1–#9, #7-and-beyond | All | RELOCATED | The v1.1 section in CONTRACT is now a thin pointer to `v1.1-plan.md` with a one-line carryover note; the consolidated backlog lives in the plan. |

No amendment was retired. No amendment was marked POTENTIAL
CONTRACT-IMPL GAP after the review: every gap surfaced (Section 4)
already has either a shipped fix (`_requeue_unfired`,
v1.0.2.post1 boundary correction) or a v1.0.4 / v1.1 candidate
filed below.

### Per-amendment classification summary

- **STILL ACCURATE**: ~205 items (every numbered item across every
  milestone except the few flagged below).
- **PROSE NEEDS CLARIFICATION**: 2 items — v0 #11 archaic
  "ignored until v0.6" wording; v0 #16 / v0.8 #19 "out of scope"
  lists that are now historical. Marked inline in CONTRACT with a
  one-line note rather than rewriting the prose; the archeology
  reads through.
- **SUPERSEDED**: 2 items — v0.6 #14 trace format → v0.9.1 #2;
  v0.7 #18 `prompt_normalized=true` per-line → v0.9.1 #2 rollup.
  Both already self-document in their successor amendments; the
  review adds the forward pointer at the original site.
- **REVISED IN PLACE**: 1 item — v1.0.2 #1(b). Discipline finding
  (§7 #1) records the cycle gap.

---

## Section 2 — API coherence findings

The Graph / View / Runtime / behavior surface has accumulated
overlapping verbs across milestones. Audit below covers every
finding surfaced by the v1.0.3 review work and the wider
cross-surface scan.

### Finding A — `graph.relations()` referenced in docs, does not exist in code

`docs/concepts/graph.md:43` shows:

```python
graph.relations(source=claim_id)    # outgoing edges
```

`Graph.relations()` does not exist on the `Graph` class
(`activegraph/core/graph.py`). The closest live method is
`Graph.get_relations(object_id=..., type=..., direction=...)`,
which has a different name and a different first kwarg
(`object_id` vs `source`).

This is the same shape as v1.0.3 Finding A: documentation surfaces
a natural form that does not exist; users hit `AttributeError` on
first try.

**Note**: the original review work item described this as "filed
as v1.0.3 adjacent gap." Verified: it was **not** filed. v1.0.3 #1
fixed the `graph.objects` analog but did not extend to
`graph.relations`. The gap remains undocumented in CONTRACT.

**Classification: v1.0.4 candidate.** Smallest fix is the
docs edit (change `graph.relations(source=claim_id)` to
`graph.get_relations(object_id=claim_id, direction="outgoing")`).
The shape-symmetric fix follows v1.0.3 #1: add
`Graph.relations(type=None)` as the View-mirror form, keep
`get_relations` working. The choice between "doc-fix only" vs
"add the alias" is a v1.0.4 design decision; either closes the
finding.

### Finding B — View / Graph surface asymmetry

| Surface       | type-filter callable   | no-filter shape         | endpoint filter            |
|---------------|------------------------|-------------------------|----------------------------|
| `View`        | `objects(type, where)` | `objects()` returns all | (none)                     |
| `View`        | `relations(type)`      | `relations()` returns all | (none)                  |
| `View`        | `events(type)`         | `events()` returns all  | (none)                     |
| `Graph`       | `objects(type, where)` | `all_objects()`         | (none for objects)         |
| `Graph`       | (missing — Finding A)  | `all_relations()`       | `get_relations(object_id, type, direction)` |
| `Graph`       | `events` (property)    | `events` (property)     | (none)                     |

The asymmetries:
1. `graph.relations(type=...)` is absent (Finding A).
2. `graph.events` is a property; `view.events(type=...)` is a
   method.
3. `Graph` retains `all_objects()` / `all_relations()` (no-arg
   form) where `View` uses the same callable with no args. v1.0.3 #1
   acknowledged this: "graph.objects() is a strict superset of
   graph.all_objects()."

**Classification: v1.1 candidate.** Full surface harmonization is
a design decision that must consider mutation methods (which `View`
does not have). Filed in `v1.1-plan.md`. Finding A is the smallest
piece and can ship in v1.0.4 standalone.

### Finding C — Parallel methods `graph.objects` vs `graph.query`

v1.0.3 #1 added `graph.objects(type=, where=)` as canonical and
kept `graph.query(object_type=, where=)` as a backward-compatible
alias with explicit "no deprecation in v1.0.3" carve-out. The kwarg
names diverge (`type` vs `object_type`) — calling one canonical and
the other an alias when their parameter names differ is internally
inconsistent. The v1.0.3 amendment is honest about the choice.

**Classification: v1.1 candidate.** Deprecate `graph.query` and
the `object_type=` kwarg. Filed in `v1.1-plan.md`.

### Finding D — `Tool.to_definition()` emits Anthropic shape only

Documented in CONTRACT v1.0.1 #5(c) clause 2: OpenAI tool calls
raise `LLMBehaviorError(reason="llm.network_error")` with a v1.1
pointer when `tools=` is non-empty. v1.0.3 #4 restated this as a
v1.1 candidate. v1.1 #7-and-beyond also names it.

**Classification: v1.1 candidate.** Already filed in three places;
consolidated in `v1.1-plan.md`.

### Finding E — `runtime.errors` field name vs WARNING log field name

`BehaviorFailure` NamedTuple (v1.0.3 #3) carries `exception_type`
and `message`. The WARNING log line emits `error_type` and
`error_message` per the CONTRACT v0.8 #6 structured-logging schema.
A user grepping logs for `error_type` finds the JSON log; the
NamedTuple field name does not match.

**Classification: no action / documentation clarification.** This
is intentional divergence — the log uses the v0.8 #6 operator
schema; the NamedTuple uses Python-conventional names. The
divergence should be documented (one sentence in
`docs/concepts/failure-model.md`'s "Observing failures in caller
code" section). Filed as a v1.0.4 doc-only candidate (Section 5).

### Finding F — Method-vs-property `Graph.events`

`Graph.events` is a property returning `list[Event]`.
`View.events(type=...)` is a callable with a type filter. A reader
who writes `graph.events()` gets `TypeError: 'list' is not
callable`; a reader who writes `view.events` gets the bound method
without invocation.

**Classification: v1.1 candidate.** Part of the broader
Graph/View harmonization (Finding B).

---

## Section 3 — Failure model consistency findings

CONTRACT v0.6 #11 established failures-as-events. CONTRACT v1.0 #4b
locked the principle framework-wide. CONTRACT v1.0.3 #3 added two
user-facing surfaces: the WARNING log and `Runtime.errors`.

Documentation audit covers `CONTRACT.md`, `docs/concepts/failure-model.md`,
`docs/reference/errors/`, and the `behavior.failed` event schema
docs.

### Finding G — `docs/concepts/failure-model.md` is the canonical surface

The page carries the v1.0.3 #3 "Observing failures in caller code"
section, names the WARNING log line shape, names `Runtime.errors`,
names `BehaviorFailure`. Consistent with CONTRACT v1.0.3 #3. ✓

### Finding H — Per-error pages do not mention `Runtime.errors`

The 31 per-error pages under `docs/reference/errors/` (e.g.,
`llm-behavior-error.md`, `replay-divergence-error.md`,
`pack-conflict-error.md`) document each error in isolation. None
mention `Runtime.errors` or `BehaviorFailure` as the programmatic
inspection surface. A user landing on
`docs/reference/errors/llm-behavior-error.md` from a `More:` link
in a WARNING log message does not learn that they can iterate
`rt.errors` to inspect failures structurally — they have to
discover `failure-model.md` separately.

**Classification: v1.0.4 candidate (doc-only).** Add a one-line
footer to each per-error page in the `behavior.failed`-emitting
categories (LLM, Tool, Pattern, Pack, Execution leaves that surface
as `behavior.failed`) pointing at `failure-model.md#observing-
failures-in-caller-code`. The error-message hierarchy itself does
not change.

### Finding I — No documentation pages still imply failures crash the run

Verified by grepping for "raise", "crash", "abort", "halt" prose in
`docs/concepts/*.md` and `docs/reference/errors/*.md`. The
canonical phrasing across the doc site is "the runtime emits a
`behavior.failed` event and continues." Consistent with CONTRACT
v0.6 #11 / v1.0 #4b. ✓

### Finding J — WARNING log fields vs `BehaviorFailure` field name divergence

Per Finding E above. The WARNING log line uses `error_type` /
`error_message` (CONTRACT v0.8 #6 schema); the NamedTuple uses
`exception_type` / `message`. Intentional but undocumented.

**Classification: v1.0.4 candidate (doc-only).** Add one sentence
to `failure-model.md` naming the divergence: "The WARNING log line
uses the v0.8 #6 structured-logging field names
(`error_type` / `error_message`); the `BehaviorFailure` NamedTuple
uses Python-conventional names (`exception_type` / `message`). The
fields carry the same values."

---

## Section 4 — Tests-verify-contracts findings

The v1.0.2 boundary-mismatch lesson institutionalized. For each
v1.0.1 / v1.0.2 / v1.0.3 amendment that makes a user-visible
promise, the audit identifies whether tests anchor on the
contract's claim or on the implementation's path.

### v1.0.1 amendments

- **v1.0.1 #1 (register / clear_registry)**: Tests in
  `tests/test_v1_0_1_register.py` (and conftest changes) verify the
  contract's claims — `clear_registry()` returns the list,
  `register()` accepts behaviors. ✓ Contract-anchored.
- **v1.0.1 #2 (example_instance_from_schema)**: Tests in
  `tests/test_llm_prompt.py` verify the schema block contains all
  three parts (schema, example, "INSTANCE not schema" language).
  ✓ Contract-anchored.
- **v1.0.1 #3 (SQLiteEventStore hint)**: Tests in
  `tests/test_store_sqlite.py` (spot-checked) verify the
  hand-raised TypeError message contains the `persist_to=` pointer.
  ✓ Contract-anchored.

### v1.0.2 / v1.0.2.post1 amendments

**v1.0.2 #1 (cross-provider validation)**: This is the
boundary-mismatch class. v1.0.2 shipped with the validation firing
at first `run_goal()` via `_ensure_registry()`; the contract said
"registration time." Tests passed because they exercised first-run.

v1.0.2.post1's tests in `tests/test_llm_default_model.py` Section (g)
fix this correctly:

- `test_decorator_after_runtime_construction_raises_at_decoration_time`
  — verifies the contract claim that the @llm_behavior line itself
  raises when a live Runtime has an incompatible provider.
- `test_register_after_runtime_construction_raises_at_register_time`
  — verifies the contract claim that public `register()` is also a
  binding moment.
- `test_claude_model_on_openai_runtime_raises_at_runtime_construction`
  — verifies the bulk-at-construction path.

✓ Contract-anchored. The post1 tests are the model for how to
recover from a boundary mismatch: don't add tests against the new
implementation path; add tests against the contract's claim at every
boundary it names.

**Positive finding**: the v1.0.2.post1 tests would have caught the
v1.0.2 original implementation as broken if they had been written
first. Treat them as the regression-test canon for boundary
contracts.

### v1.0.3 amendments

- **v1.0.3 #1 (graph.objects)**: Tests in `tests/test_graph.py`:
  `test_objects_filters_by_type`, `test_objects_filters_by_where`,
  `test_objects_with_no_kwargs_returns_every_object`,
  `test_objects_and_query_return_the_same_results`,
  `test_query_alias_still_works_with_positional_arg`. The contract
  claims about superset of all_objects, View parity, and alias
  preservation are all tested directly. ✓ Contract-anchored.
- **v1.0.3 #2 (output_schema decoration-time validation)**: Tests
  in `tests/test_llm_behavior.py`:
  `test_output_schema_dict_raises_at_decoration_time`,
  `test_output_schema_string_raises_at_decoration_time`, plus
  variant tests. The contract said "at decoration time, not at
  first LLM call"; the tests verify the raise happens at the
  decorator line (not when the behavior runs). ✓ Contract-anchored.
- **v1.0.3 #3 (WARNING log + Runtime.errors)**: Tests in
  `tests/test_v1_0_3_behavior_failed_ux.py`:
  `test_behavior_failure_emits_warning_log`,
  `test_runtime_errors_returns_structured_view`,
  `test_only_one_log_line_per_failure`, etc. The contract claims
  about consolidated logging (no duplicate ERROR) and the
  property's projection shape (read from `graph._events`) are both
  tested. ✓ Contract-anchored.
- **v1.0.3 #4 (multi-turn tool messages)**: Tests in
  `tests/test_tool_replay.py` and `tests/test_llm_anthropic.py`
  (spot-checked) verify the `_message_to_anthropic` output contains
  text + tool_use blocks for the tool-using turn. The contract
  claim about Anthropic spec compliance is tested via the
  serialized wire format. ✓ Contract-anchored.

### Spot-check on older amendments

- **v0.5 #8 (re-queue unfired events)**: The contract said "events
  with NO `behavior.started` referencing them are re-queued."
  The implementation used the false reverse-implication: "no
  `behavior.started` ⟹ event still in queue." Events with zero
  subscribed behaviors are popped-and-discarded with no
  `behavior.started`, so they were falsely requeued on every
  `Runtime.load`. This was a latent bug from v0.5 caught by the
  v1.0-rc2 user test (B-finding, not B3). CHANGELOG v1.0-rc2 fixed
  it; CONTRACT v0.5 #8 prose was correct; the tests verified the
  budget-resume path but not the zero-subscriber case.
  **Boundary-mismatch class.** Filed as a discipline note (§7 #2).
- **v0.6 #11 (reason taxonomy)**: Tests in `tests/test_llm_*` and
  `tests/test_tool_*` directly raise each reason and assert the
  `behavior.failed` payload's `reason` field. Contract-anchored.
- **v0.7 #7 (cache-by-default tool determinism)**: Tests in
  `tests/test_tool_replay.py` (`replay_reinvoke_deterministic` flag
  toggles re-invocation) — contract-anchored.
- **v0.9 #5 (load-order asymmetry)**: Tests in
  `tests/test_packs_validation.py` — directly verify
  pre-load-of-pack object creation passes; post-load fails.
  Contract-anchored.

### Summary

Every v1.0.1 / v1.0.2 / v1.0.3 amendment audit finds tests that
anchor on the contract's claim, not the implementation's path. The
v1.0.2.post1 correction stands out as the model. The older latent
bug in `_requeue_unfired` was the canary that surfaced the
discipline at scale.

No new test-discipline gap was found in this review. Filed as a
v1.0.4 candidate (Section 5): add a contract-anchored test for
`_requeue_unfired` against the zero-subscriber case to lock the
post-rc2 fix.

---

## Section 5 — New v1.0.4 candidates surfaced

Each candidate fits the patch-release framing: small, mechanical,
no CONTRACT amendments, no new runtime capability. Filed with
explicit cross-reference to the review section that surfaced it.

### v1.0.4 #1 — Close the `graph.relations()` doc-vs-impl gap (Finding A)

**Source**: Section 2 Finding A.

Two equivalent fixes:
- Doc-only: change `docs/concepts/graph.md:43` to use
  `graph.get_relations(object_id=..., direction="outgoing")`.
- Code-symmetric: add `Graph.relations(type=None)` mirroring
  `View.relations(type=None)`; leave `get_relations` working;
  update the doc page to use `graph.relations(type=...)` form
  alongside `get_relations(object_id=...)`.

The code-symmetric fix matches the v1.0.3 #1 pattern. Either
ships in v1.0.4 without a CONTRACT amendment if the alias is
treated as docs/parity work; if the alias is named as new public
surface, a CONTRACT v1.0.4 #N amendment locks it in the same shape
as v1.0.3 #1.

**Estimated scope**: small.

### v1.0.4 #2 — Per-error pages mention `Runtime.errors` and `BehaviorFailure` (Finding H)

**Source**: Section 3 Finding H.

Add a one-line footer to per-error pages whose errors surface via
`behavior.failed` events: "See [Observing failures in caller
code](../concepts/failure-model.md#observing-failures-in-caller-code)
for `Runtime.errors` and the `BehaviorFailure` shape."

Affected pages (rough enumeration; verify against
`docs/reference/errors/`):
- `llm-behavior-error.md`
- `tool-error.md`
- `unknown-tool-error.md`
- `pack-schema-violation.md` (fires from `add_object` /
  `add_relation`, surfaces as behavior failure when inside a
  behavior call)
- `unsupported-pattern-error.md` (registration-time, not
  behavior-failed — skip)
- Plus any other `behavior.failed`-routing leaves.

Doc-only. No code change. No CONTRACT amendment.

**Estimated scope**: small.

### v1.0.4 #3 — Document WARNING log vs `BehaviorFailure` field-name divergence (Finding J)

**Source**: Section 3 Finding J.

Add one sentence to `failure-model.md`'s "Observing failures in
caller code" section: "The WARNING log line uses the v0.8 #6
structured-logging field names (`error_type` / `error_message`);
`BehaviorFailure` uses Python-conventional names (`exception_type`
/ `message`). Same values, different keys."

Doc-only.

**Estimated scope**: small.

### v1.0.4 #4 — Contract-anchored test for `_requeue_unfired` zero-subscriber case

**Source**: Section 4 spot-check on v0.5 #8.

The v1.0-rc2 fix uses `runtime.idle` as the high-water mark. The
existing regression test (`tests/test_requeue_unfired.py`) verifies
`queue_depth == 0` on a cleanly-drained run. Add a
contract-anchored test: emit an event with zero subscribers, save,
reload, assert `queue_depth == 0` (not re-queued). Locks the v0.5 #8
contract claim ("events with NO `behavior.started` referencing them
are re-queued") against the specific subclass that the original
implementation got wrong.

**Estimated scope**: small.

### v1.0.4 #5 — Stale-prose pruning in CONTRACT preamble notes

**Source**: Section 1.

Two amendments carry archaic forward-pointer prose:

- v0 #11: "`token_budget` is parsed but ignored until v0.6." Add
  trailing clause: "(Honored from v0.6 onward via view assembly.)"
- v0 #16 and v0.8 #19 "Out of scope" lists: prepend "(Historical
  scope statement; every listed item has shipped in subsequent
  milestones; preserved for archeology.)"

Pure documentation pass; CONTRACT prose preserved underneath.

**Estimated scope**: small.

---

## Section 6 — New v1.1 candidates surfaced

These are design-pass items, distinguished from v1.0.4 by needing
explicit decisions before code lands. All flow into
`v1.1-plan.md`'s consolidated backlog; this section enumerates
them with their CONTRACT-review source.

| Tag | Title | Section | Notes |
|-----|-------|---------|-------|
| API-1 | Deprecate `graph.query` / `object_type=` kwarg | §2 Finding C | Already a v1.0.3 #1 carve-out; pickup in v1.1. |
| API-2 | Full Graph/View surface harmonization | §2 Findings A, B, F | Method-vs-property `events`, missing `graph.relations`, deprecation of `graph.all_objects()`. |
| DISC-1 | Boundary-anchored test discipline | §4, §7 #2 | Not a code change; a process amendment to the next CONTRACT cycle. |
| DOC-1 | CONTRACT modularization | §7 #5 | Split into per-milestone files with master index, OR add executive-summary preambles. |

The other v1.1 candidates surfaced during v1.0.1 / v1.0.2 / v1.0.3
(dict-form `output_schema=`, `on_failure=` callback, OpenAI tool
translation, fire-once aggregation, pack-load-time validation,
auto-provider ergonomics, version-tag-correspondence gate,
fork-cache-symmetry, native structured-output, package-data and
deploy-verification gates, partial Pack* migrations, deferred
DB-error wrappers) are already consolidated in `v1.1-plan.md` and
not re-itemized here.

---

## Section 7 — Discipline observations

These are notes on the contract process itself, not item-level
findings. The amendment cycle has been working; the observations
are about how to keep it working as the document grows.

### §7 #1 — In-place revisions vs dated amendment sections

**What happened**: v1.0.2.post1 corrected the v1.0.2 #1(b)
implementation boundary (lazy → both binding moments). The
CHANGELOG carries a dated `[v1.0.2.post1]` entry. The CONTRACT
edited v1.0.2 #1(b) prose in place; no `### v1.0.2.post1 amendment
to v1.0.2 #1(b)` section was appended.

**Why it matters**: a future reader of CONTRACT alone cannot
reconstruct when the validation boundary moved. They have to
cross-reference CHANGELOG to learn that v1.0.2 originally claimed
"registration time" while the implementation fired lazily, and
post1 corrected both. The boundary-mismatch lesson is lost in the
in-place edit.

**Forward discipline**: when a post-release amendment changes
contract wording, EITHER:
- Append a `### v1.0.X.postN: <what was revised and why>` block
  under the original amendment, with the corrected wording inside;
  leave the original prose intact, OR
- Edit in place AND add an inline marker `[revised by v1.0.X.postN;
  see CHANGELOG]` at the revision site.

This review chose option (b) for the v1.0.2 #1(b) site (marker
added). Option (a) is preferred for future cycles because it
preserves the boundary-mismatch as a teachable record.

### §7 #2 — Boundary-mismatch as a recurring class

**Pattern**: the contract says X. The implementation does a near-X
(some adjacent path that happens to share most observables with X).
Tests pass because they exercise the implementation's path. The
gap surfaces only when an external spot-check or a non-obvious
edge case lands on the divergence.

**Instances surfaced across milestones**:
1. v0.5 #8: contract says "events with no `behavior.started`
   are re-queued." Implementation: relies on the absence of
   `behavior.started`. Events with **zero subscribers** never
   produced `behavior.started`; the implementation falsely
   re-queued them. v1.0-rc2 fix uses `runtime.idle` as the
   high-water mark.
2. v1.0.2 #1: contract says "validation fires at registration
   time." Implementation: validation fired lazily at
   `_ensure_registry()`. v1.0.2.post1 fix moves validation to both
   binding moments (Runtime construction, decorator/register call
   when a Runtime is alive).

**Forward discipline**: when locking a contract claim that names a
boundary ("at registration time," "before any state mutation,"
"on load," "at decoration time"), write the test against the
boundary the contract names, not against the path the
implementation takes. The v1.0.2.post1 tests in
`test_llm_default_model.py` Section (g) are the canonical model:
each test names the binding moment in its name and asserts the
raise happens at that exact moment.

This is the most valuable forward-discipline note in the review.

### §7 #3 — Scattered v1.x forward-references

**What happened**: v1.0.1 #5(c), v1.0.2 #1(b), v1.0.3 #2, #3, #4,
#5, plus v1.0 PR-E/PR-F/PR-G end-of-series tallies, plus the v1.1
section itself, all carry "filed as a v1.1 candidate" markers
pointing at different (and overlapping) items. The accumulated
forward-pointer graph is not consultable as a single list.

**Forward discipline**: when an amendment defers work, the
deferral text reads as a one-liner: "Filed as v1.1 candidate; see
`v1.1-plan.md#anchor`." The plan is the canonical home for the
backlog. The CONTRACT amendment is the canonical home for the
deferral *reason*. The two co-evolve: every plan item names its
CONTRACT amendment as source; every CONTRACT amendment that defers
points at exactly one plan entry.

This review's deliverable enforces the pattern: `v1.1-plan.md` is
the consolidated backlog; CONTRACT carries the deferral reasons
inline but the "what gets done in v1.1" question is answered in
the plan.

### §7 #4 — Voice consistency holds across milestones

Spot-check across milestone sections: v0.6 reads as the same author
as v1.0.3. Active, declarative, names the invariant being
protected, no hedging. The voice ceiling held even under the
v1.0-rc1 / rc2 / rc3 / v1.0.1 / v1.0.2 / v1.0.2.post1 / v1.0.3 time
pressure. This is a positive observation worth noting because the
HANDOFF.md "Voice ceiling" discipline section described it as a
discipline; the review confirms it held.

The single uneven section is the v1.0 PR-A-through-PR-G running
narrative — at moments it reads as audit progress reports
("running total: 19 new leaves") rather than as locked decisions.
Not a problem (the audit progress *is* part of the contract
record), but a future-cycle pattern to watch: when amendments
accumulate audit tallies, the prose risks reading like a status
report rather than a contract. PR-G's series-completion note is the
cleanest example of catching the drift — it ends with a discipline
note that elevates the principle above the tally.

### §7 #5 — CONTRACT length is becoming a usability concern

**State**: CONTRACT.md is 5427 lines, growing by ~800-1200 lines
per patch release. The cumulative document is no longer readable
cover-to-cover by a new reader without a guided path.

**Symptom**: this review's read-time was ~2-3 hours. A future
reader doing a sub-review (e.g., "audit the failure model alone")
needs to know which milestone sections to read; the document does
not surface that.

**Options for v1.1**:
- **Split per-milestone files** (`CONTRACT/v0.5.md`,
  `CONTRACT/v0.6.md`, etc.) with `CONTRACT.md` as a master index
  + cross-cutting principles (failure model, identity, voice
  ceiling). Loss: harder to grep across the whole contract.
- **Add an executive-summary preamble per milestone**: top-of-section
  TL;DR (~5-10 lines) naming the major decisions. Reader can scan
  the preambles and only drill into sections they need. Loss: more
  prose to maintain.
- **Add cross-cutting principle pages** (`failure-model.md` is the
  in-doc-site example): the doc site holds the synthesis; CONTRACT
  carries the per-milestone decisions. Already partially in place.

**Classification: v1.1 candidate (DOC-1).** Decision before v1.1
work starts.

### §7 #6 — Test-file naming inconsistency

Most tests have functional names (`test_graph.py`,
`test_llm_behavior.py`). v1.0.3 #3 tests live in
`test_v1_0_3_behavior_failed_ux.py`. Version-tagged test file
names couple tests to the version that introduced them; the test's
purpose drifts when the next amendment lands.

**Forward discipline**: name tests after the feature, not the
version. v1.1 should rename `test_v1_0_3_behavior_failed_ux.py`
to `test_runtime_errors.py` or `test_behavior_failure_ux.py`. Not
a v1.0.4 candidate — purely cosmetic and breaks nothing.

---

## Closing

The cumulative document survives the review. No amendment was
retired; no architectural gap surfaced. The largest discipline
finding (§7 #1: in-place revision of v1.0.2 #1(b)) is a process
amendment, not a code amendment. The largest doc-quality finding
(§7 #5: CONTRACT length) is a v1.1 decision, not a v1.0.4 fix.

The review confirms what HANDOFF.md described: twelve milestones
of audit-discipline produced a contract that holds up. The patch
cycles since v1.0 final have not undone the discipline; they have
extended it. The findings here are the next iteration's input,
not a verdict on the cycle so far.

Next: v1.0.4 (the five candidates in Section 5), then a fresh
session decides v1.1 scope using `v1.1-plan.md`.
