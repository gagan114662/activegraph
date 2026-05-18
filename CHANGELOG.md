# Changelog

All notable changes to **activegraph** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Per-version migration notes reference the
[Migration from v0.7](https://docs.activegraph.dev/cookbook/migration-from-v0-7/)
cookbook, the canonical runbook for upgrading runs and code across
milestones.

The doc site mirrors this file at
[Changelog](https://docs.activegraph.dev/about/changelog/) via the
mkdocs snippet plugin — edit `CHANGELOG.md` at the repo root.

## [Unreleased]

Nothing yet. v1.1 scope is tracked in
[CONTRACT.md § v1.1](https://github.com/yoheinakajima/activegraph/blob/main/CONTRACT.md).

## [v1.0] — TBD

Placeholder. v1.0 final ships after a lighter-weight verification
pass against v1.0-rc2 (steps 1, 2, and 7 of the tutorial — the
beats the rc1 user-test gate hit blockers on) confirms the rc2
fixes resolved the gate findings.

Scope = v1.0-rc2 + any lighter-pass findings.

## [v1.0-rc2] — 2026-05-18

The user-test-findings milestone. Five findings from the
[CONTRACT v1.0 #C4](https://github.com/yoheinakajima/activegraph/blob/main/CONTRACT.md)
gate addressed; one was a latent runtime state-machine bug since
v0.5. No new runtime capability; no public-API renames.

### Added

- **PyPI publish workflow** (`.github/workflows/publish.yml`).
  Tag-push trigger matching `v*` triggers `python -m build` then
  upload via PyPI trusted publishing (OIDC-based). Documented in
  [Publishing a release](https://docs.activegraph.dev/about/publishing/).
  Externally owned per
  [CONTRACT v1.0 #C8](https://github.com/yoheinakajima/activegraph/blob/main/CONTRACT.md)
  — the agent ships the workflow, the maintainer runs the publish.
- **Tutorial-snippet CI test** (`tests/test_tutorial_snippets.py`).
  Subprocess-runs the tutorial's step 7 fork snippet end-to-end
  against the bundled fixtures; asserts exit 0 and idempotency on
  re-run. Tactical down-payment on
  [CONTRACT v1.1 #2 expansion](https://github.com/yoheinakajima/activegraph/blob/main/CONTRACT.md)
  (spec-vs-impl drift gate for Python doc snippets).
- **`_requeue_unfired` regression test** (`tests/test_requeue_unfired.py`).
  Locks the C3 regression vector: `Runtime.load` on a cleanly-drained
  saved run produces `queue_depth == 0`.

### Changed

- **`_requeue_unfired` uses `runtime.idle` as the high-water mark.**
  Latent bug since CONTRACT v0.5 #8: the function relied on the false
  reverse-implication "no `behavior.started` references this event id
  ⟹ event was still in the queue." Events with **zero** subscribed
  behaviors are popped-and-discarded with no `behavior.started`
  emitted, so they were falsely requeued on every `Runtime.load`.
  The fix uses the last `runtime.idle` event as the high-water mark
  (the runtime emits `runtime.idle` only after the queue empties);
  only events after the last idle are candidates for requeue.
  `runtime.budget_exhausted` is explicitly NOT a drain marker —
  using it would break budget-bounded pause-and-resume.
- **Tutorial step 3 and quickstart prose** distinguish the provider
  layer (where the fixture provider produces responses) from the
  runtime's replay cache layer (where `cache_hit=true` legitimately
  appears under strict-replay loads or `Runtime.fork()` in-process).
  Pre-rc2 prose conflated the two. The conflation was originally in
  the v1.0 spec at `examples/quickstart_session.txt`; the spec is
  updated with a header drift-note documenting the two-layer reality.
- **Tutorial step 7 fork snippet** uses
  `RecordedDiligenceProvider(companies=THREE_COMPANIES)` as the fork's
  `llm_provider=`. Matches the parent run's provider; preserves the
  "no API key required" tutorial pitch. The snippet also includes a
  tutorial-only cleanup-on-collision branch so it's re-runnable
  without manual DB surgery.
- **`_prepare_interactive_subdir` collision prompt** re-prompts on
  unrecognized input. Pre-rc2 behavior fell through to the suffix
  branch on any input that wasn't `o` or `q`, which swallowed
  typeahead from the next prompt. Mirrors the existing iteration-loop
  pattern at `run_interactive_mode`.

### Deprecated

Nothing. Backward compatibility holds — all v0–v1.0-rc1 tests pass.

### Removed

Nothing user-facing.

### Fixed

- **`Runtime.load(...).status().queue_depth` reads 0 on a freshly
  loaded cleanly-drained run.** Was a non-zero false count of events
  that had been popped-and-discarded during the original run. See
  the Changed entry for `_requeue_unfired` above.
- **`activegraph --version` reports the correct version.** Was stuck
  at `0.9.1` through v1.0-rc1's release (the version-sync gate
  validated internal consistency but not correspondence with the git
  tag). The v1.1 #6 version-tag-correspondence gate closes this gap
  in v1.1.
- **Tutorial step 7 fork snippet runs end-to-end against bundled
  fixtures** with no API key, matching the rest of the quickstart's
  "no API key required" pitch.
- **`cache_hit=true` claim** in the tutorial and quickstart "what
  just happened" prose: the claim was wrong for initial fixture-mode
  runs (the runtime's replay cache only fires on strict-replay or
  in-process fork). Prose corrected; two-layer vocabulary lands
  cleanly for first-time readers.

### Migration from v1.0-rc1

Additive. No code changes required. Existing v1.0-rc1 installs
should:

```bash
pip install --upgrade activegraph==1.0.0rc2
```

Existing saved runs (`*.db` files) load with `queue_depth == 0`
correctly post-upgrade — the C3 fix is in the load path, not the
storage format.

### Known follow-ons (v1.1 scope)

In addition to the v1.0-rc1 v1.1 backlog (carried forward):

- **CONTRACT v1.1 #2 expansion** — spec-vs-impl drift gate covers
  executable Python snippets in docs, not just CLI flags. v1.0-rc2
  ships the tactical step 7 test; v1.1 generalizes.
- **CONTRACT v1.1 #5** — `Runtime.load` auto-provider ergonomics.
  The rc2 fix for B2 passes `RecordedDiligenceProvider` explicitly;
  the v1.1 design question is whether `Runtime.load` should infer a
  provider from the run's recorded events or from a pack-manifest
  declaration. New runtime capability, banned in v1.0.
- **CONTRACT v1.1 #6** — version-tag-correspondence CI gate.
  Existing version-sync gate validates `__version__` matches
  `pyproject.toml`; the v1.1 gate adds correspondence with the
  current annotated tag in tagged-release CI runs.
- **CONTRACT v1.1 #7 backlog item: fork cache pre-population
  symmetry.** `Runtime.fork(at_event=...)` in-process pre-populates
  the LLM cache from the parent's events; the persistent shape
  (`SQLiteEventStore.fork_run` then `Runtime.load`) does not. The
  two paths should be symmetric. New runtime behavior, banned in v1.0.

## [v1.0-rc1] — 2026-05-18

The adoption-surface milestone. No new runtime capability; the
contract is "a new user can install, run, understand, debug, and
extend the framework without reading source code."

### Added

- **Error hierarchy rewrite.** Every exception now inherits from
  `ActiveGraphError` and carries structured `what_failed`,
  `how_to_fix`, and `context` fields. Seven category bases
  (`ConfigurationError`, `RegistrationError`, `ExecutionError`,
  `ReplayError`, `StorageError`, `PatternError`, `PackError`) with
  33 leaves. Built-in lineage preserved via multi-inheritance —
  `except ValueError`/`except KeyError` clauses still work.
- **Per-error reference catalog.** Every error message ends with a
  `More:` link to a dedicated page documenting when it fires, why,
  how to diagnose, and how to fix. Catalog at
  [docs.activegraph.dev/reference/errors](https://docs.activegraph.dev/reference/errors/replay-divergence-error/).
- **Documentation site at [docs.activegraph.dev](https://docs.activegraph.dev/)**:
  concepts pages for every primitive (graph, events, behaviors,
  relations, patches, views, frames, policies, patterns, replay,
  forking, failure model); guides; cookbook (common patterns,
  debugging, migration); CLI reference; API reference via
  mkdocstrings.
- **`activegraph quickstart` CLI command.** Bundled Diligence demo
  in fixture mode (byte-deterministic, no API key, ~20 seconds);
  `--interactive` mode walks the user through writing their first
  behavior.
- **10-minute tutorial at
  [docs.activegraph.dev/quickstart](https://docs.activegraph.dev/quickstart/).**
  Install → run → write a behavior → save and inspect → fork and
  diff. Seven steps; every example runs.
- **CI gates on the public surface.** Version-sync gate
  (`pyproject.toml` ↔ `activegraph.__version__`), broken-link gate
  for the doc site, mypy `--strict` gate on the
  [`__all__` allowlist](https://github.com/yoheinakajima/activegraph/blob/main/docs/reference/api/TYPE_REPORT.md)
  (22/38 modules clean at baseline), docstring coverage gate
  ([Ring 0 92/100 not-missing, Ring 1 at 84.7%](https://github.com/yoheinakajima/activegraph/blob/main/docs/reference/api/COVERAGE_REPORT.md);
  exemption list in
  [`docstring_gaps.toml`](https://github.com/yoheinakajima/activegraph/blob/main/docstring_gaps.toml)).
- **CLI follow-on flags** (referenced from error messages' recovery
  prose): `inspect --event <id>`, `inspect --behaviors`,
  `inspect --pack-version`, `migrate --skip-corrupted`,
  `fork --record`.

### Changed

- **README trimmed** from 1275 lines to ~190. The doc site is now
  the canonical reference; the README is the conversion funnel
  (30-second pitch → install → `activegraph quickstart` →
  tutorial).
- **Error messages structured.** Every framework-raised exception
  exposes `what_failed` (one line), `how_to_fix` (actionable
  prose), and `context` (structured detail) on the exception
  instance. Plain `str(exc)` renders all three.
- **Trace printer formats `pack.loaded`** (was previously falling
  through to the generic event renderer).

### Deprecated

Nothing. Backward compatibility holds — all v0–v0.9 tests pass.

### Removed

Nothing user-facing. Internal: a handful of dead code paths
surfaced during the error-rewrite audits were removed.

### Fixed

- `pack.loaded` trace formatting (was missing despite being spec'd
  in CONTRACT v0.9 #25).
- Several inconsistent error categories — see CONTRACT v1.0 PR-F
  audit findings for the cross-category reclassifications.

### Migration from v0.9.1

Additive. See
[Migration from v0.7 § 5–6](https://docs.activegraph.dev/cookbook/migration-from-v0-7/#5-adopt-the-v10-error-hierarchy-v09--v10):

```python
# v1.0 — broader catches with structured context:
try:
    rt = Runtime.load(url, run_id=rid)
except activegraph.StorageError as e:
    log(e.what_failed, e.how_to_fix, e.context)
except activegraph.ActiveGraphError as e:
    log(e.what_failed, e.how_to_fix)
```

Existing `except ValueError`/`except KeyError`/`except TypeError`
clauses keep working — multi-inheritance preserves builtin
lineage.

### Known follow-ons (v1.1 scope)

- `fork --set <pack>.<key>=<value>` for cheap fork-with-override
  experiments (CONTRACT v1.1 #1; canonical Python-API recipe at
  [Cookbook § Fork with a pack-setting override](https://docs.activegraph.dev/cookbook/common-patterns/#fork-with-a-pack-setting-override-v10-python-api)).
- `inspect --memo` and `inspect --search` (CONTRACT v1.1 #1).
- Type-completeness burndown — close the 16 dirty allowlist
  modules (CONTRACT v1.1 #3,
  [`TYPE_REPORT.md`](https://github.com/yoheinakajima/activegraph/blob/main/docs/reference/api/TYPE_REPORT.md)).
- Docstring-completeness burndown — close the 8 missing Ring 0
  exemptions and upgrade one-liners to full
  (CONTRACT v1.1 #4,
  [`COVERAGE_REPORT.md`](https://github.com/yoheinakajima/activegraph/blob/main/docs/reference/api/COVERAGE_REPORT.md)).
- Spec-vs-impl drift gate for CLI flags (CONTRACT v1.1 #2).

## [v0.9.1] — 2026-05-17

Operator-visible quality-of-life fixes between v0.9 and v1.0.

### Added

- `[trace.flags]` rollup header at the top of every trace block
  with `prompt_normalized=true|false` so operators can see at a
  glance whether a run used the v0.7+ normalized-prompt format.

### Changed

- Approval-demo output is now granular (per-object) rather than
  batched, so operators can see which approval the runtime is
  waiting on.

### Migration from v0.9

None — additive trace and demo improvements; no API changes.

## [v0.9] — 2026-05-16

The **pack format** milestone. A pack bundles object types,
behaviors, tools, prompts, and policies for a specific domain.

### Added

- `Pack` dataclass: frozen, equality by `(name, version)`.
- Pack-aware decorators (`activegraph.packs.behavior`,
  `llm_behavior`, `relation_behavior`, `tool`) with no global
  registry side effects.
- `runtime.load_pack(pack, settings=...)` — idempotent;
  conflicts (object type, relation type, behavior name, tool
  name, policy name) raise `PackConflictError` before any state
  mutation; version mismatch raises `PackVersionConflictError`.
- Object type schemas enforced via Pydantic at
  `graph.add_object`; relation type validation at
  `graph.add_relation`.
- Namespace prefixing: canonical strict
  (`diligence.claim_extractor`); short-name lookups lenient.
- Three settings access forms: typed parameter injection
  (primary), `ctx.settings`, `ctx.pack_settings(name)`.
- Prompt loader: TOML frontmatter; content-hashed via SHA-256
  truncated to 16 hex chars; hash (not version) is the replay
  contract.
- Discovery via Python entry points
  (`activegraph.packs`); `discover()`, `load_by_name()`,
  `clear_discovery_cache()`.
- `activegraph pack new <name>` scaffolding command.
- `activegraph pack list` to enumerate installed packs.
- `activegraph.packs.diligence` — production-quality reference
  pack: 8 object types, 6 relation types, 7 behaviors, 3 tools,
  2 policies, 4 prompts, recorded fixtures for 3 companies,
  end-to-end demo at
  [`examples/diligence_real_run.py`](https://github.com/yoheinakajima/activegraph/blob/main/examples/diligence_real_run.py).
- Pack authoring guide at
  [Authoring packs](https://docs.activegraph.dev/guides/authoring-packs/).

### Changed

- **Python floor raised to 3.11** (uses stdlib `tomllib`).
- **`pydantic>=2` is now a hard dependency** (was opt-in via
  `[llm]`). The pack format's object-type schemas and settings
  models require it.
- `click>=8,<9` becomes a hard dependency (CLI is always
  available).

### Migration from v0.8

Additive. See
[Migration from v0.7 § 4](https://docs.activegraph.dev/cookbook/migration-from-v0-7/#4-adopt-the-pack-format-v08--v09).
Global decorators (`@behavior`, `@tool`) keep working alongside
loaded packs; the pack format is opt-in for new code.

Python 3.10 users must upgrade to 3.11+ before installing v0.9.

## [v0.8] — 2026-05-16

The **operator surface** milestone. Hardens the boundary between
the framework and the world it runs in.

### Added

- `PostgresEventStore` behind the same `EventStore` protocol as
  SQLite (Postgres 16+; `pip install activegraph[postgres]`).
- Connection-URL addressing everywhere (`sqlite:///relative`,
  `sqlite:////absolute`, `postgres://...`).
- `activegraph migrate --from <url> --to <url>` —
  transaction-per-run, idempotent, one-directional.
- Structured JSON logging via `configure_logging(json_output=True)`
  with a documented schema (the operator contract).
- `Metrics` protocol (three methods: counter, histogram, gauge)
  with `NoOpMetrics` default and reference `PrometheusMetrics`
  backend.
- `runtime.status(recent=N)` — frozen `RuntimeStatus` dataclass
  for introspection.
- `activegraph` CLI: `inspect`, `replay`, `fork`, `diff`,
  `export-trace`, `migrate`. CLI exit codes documented as
  contract.
- Operator guide at
  [Operating in production](https://docs.activegraph.dev/guides/operating-in-production/).

### Migration from v0.7

Additive. See
[Migration from v0.7 § 3, 7, 8](https://docs.activegraph.dev/cookbook/migration-from-v0-7/#3-adopt-connection-urls-v07--v08).
Old SQLite path arguments (`persist_to="/path/to.db"`) keep
working; URLs are required for CLI and cross-store operations.

## [v0.7] — 2026-05-16

The **tools and advanced matching** milestone.

### Added

- `@tool` decorator: tools as first-class primitives with input
  schema, output schema, determinism flag, cost, timeout.
- LLM ↔ tool turn loop owned by the runtime; multi-turn until
  the model returns a non-tool response or `max_tool_turns` hits.
- `tool.requested` / `tool.responded` event pair; replay cache
  separate from the LLM cache.
- `RecordedToolProvider` + `RecordingToolProvider` for tests.
- Two reference tools: `web_fetch`, `graph_query` (factory-based
  for graph read access).
- Cypher-subset pattern subscriptions via `pattern=` on
  `@behavior` / `@llm_behavior`. Compile-time strict; the
  unsupported tokens raise `UnsupportedPatternError` naming the
  offending token.
- Negation via `NOT EXISTS { ... }`.
- Temporal predicates: `activate_after=N` events (event-count,
  not wall-clock — keeps replay deterministic).
- Tool budgets (`max_tool_calls`) + cost-sharing with LLM
  (`max_cost_usd` covers both).
- Causal-chain walk crosses tool boundaries via
  `tool_request_event_id` provenance.

### Changed

- Prompt assembly normalized — every prompt is content-hashed
  via the canonical form; the `prompt_normalized=true` flag
  appears in the v0.9.1 trace rollup for runs using this format.

### Migration from v0.6

Additive. v0.6 LLM behaviors continue to work without `tools=`
declarations.

## [v0.6] — 2026-05-16

The **LLM integration** milestone.

### Added

- `@llm_behavior` decorator with structured output parsing
  (Pydantic schema).
- Frame-aware prompt construction: system prompt assembled from
  frame goal + constraints + behavior description + output-schema
  reminder, in a fixed order.
- `llm.requested` / `llm.responded` event pair with model, full
  prompt+params, prompt hash, estimated cost, deterministic flag,
  cache-hit flag.
- `AnthropicProvider` reference implementation (reads
  `ANTHROPIC_API_KEY`; never from code).
- `RecordedLLMProvider` + `RecordingLLMProvider` for tests
  (fixtures keyed by SHA-256 of prompt+params canonical form).
- Cost accounting: Decimal-precise `max_cost_usd` budget; pre-call
  estimate via `count_tokens`; post-call actual cost from
  provider's `usage`.
- Structured failure reasons (`llm.network_error`,
  `llm.rate_limited`, `llm.parse_error`, `llm.schema_violation`,
  `llm.fixture_missing`, `budget.cost_exhausted`).

### Migration from v0.5

Additive. LLM behaviors are opt-in; non-LLM runs unaffected. New
optional dependency `activegraph[llm]` (anthropic SDK).

## [v0.5] — 2026-05-16

The **resumability** milestone. The event log becomes the source
of truth.

### Added

- Full event log persistence via the `EventStore` protocol;
  SQLite reference backend with schema version pinned from day
  one in a `meta` table.
- `Runtime.load(url, run_id=...)` — open, pick a run, replay,
  return runtime ready to continue.
- Strict-replay mode (`replay_strict=True`) — re-executes
  behaviors and fires `ReplayDivergenceError` on mismatch.
- Fork (`runtime.fork(at_event=...)`) — new run, copies parent's
  event log up to the cutoff (inclusive), independent log
  thereafter.
- Structural diff (`parent.diff(other)`) — shared / parent-only
  / fork-only event partitions; divergent objects and relations.
- Multiple runs per file; ULID `run_id`s; provenance carries
  `run_id`.
- Unfired-event re-queue on load (events emitted but never popped
  return to the queue on resume).

### Migration from v0

Additive. v0 in-memory runs continue to work without
`persist_to=`. New optional dependency
`activegraph[sqlite]` (stdlib — no extra packages needed).

## [v0] — 2026-05-16

The **core runtime**.

### Added

- In-memory `Graph` with typed objects, typed relations, and an
  append-only event log.
- Function-based (`@behavior`) and class-based
  (subclass `Behavior`) behaviors.
- Relation behaviors (`@relation_behavior`) — coordination logic
  on edges.
- Event-type subscriptions with predicate filters (`where=`).
- Patch system with optimistic concurrency (version-keyed apply;
  rejected patches surface as `patch.rejected` events).
- Views with type/depth/recent-events scoping.
- Frames (mission context per run) and policies (per-behavior
  capability declarations).
- Trace printer (`runtime.print_trace()`); causal-chain query
  (`runtime.trace.causal_chain(object_id=...)`).
- Budgets (`max_events`, `max_behavior_calls`, `max_seconds`,
  `max_depth`, etc.) — runtime stops cleanly when hit; resumable.

### Migration from before v0

There is no before-v0.

---

The graph is the world. Behaviors are physics. The trace is the proof.
