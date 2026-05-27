# T6 Extra-Hard: Activegraph Events Tail

Spec owner: Sofia. Cohort: opus-4.7-claude-code-2026-05-27.

## Scope

Add a CLI subcommand that prints the most recent events from the active event
store as newline-delimited JSON. It is a read-only operator view over the
current event log, except for one required audit event that the command itself
appends before reading.

The implementation must not change event storage semantics, replay semantics,
or the canonical `Event` shape. It must read from the attached active
`EventStore` and preserve append-only ordering.

## CLI Contract

Command:

```bash
activegraph events tail [--n <int>] [--since <iso-timestamp>] [--filter <substring>] [--json]
```

Arguments and flags:

- `events tail` is a subcommand under the existing `activegraph` CLI.
- `--n <int>` limits output to the last N matching events. Default: `20`.
  `--n` must be a non-negative integer; `--n 0` is legal and produces zero
  output rows.
- `--since <iso-timestamp>` includes only events whose timestamp is greater
  than or equal to the supplied ISO 8601 timestamp.
- `--filter <substring>` includes only events whose event kind contains the
  literal substring. Matching is case-sensitive.
- `--json` selects the machine-readable output mode. For T6 the output is
  always newline-delimited JSON; `--json` is accepted for forward compatibility
  with future non-JSON output modes and must not change the row schema in T6.

Selection order (deterministic):

1. Parse and validate flags. Reject malformed inputs before any I/O.
2. Resolve the active event store. Fail fast if none.
3. Append the `events_tail_invoked` audit event to the active store.
4. Read events from the store in append order.
5. Apply `--since` if present.
6. Apply `--filter` if present.
7. Select the last `--n` matching events (the suffix of the filtered list).
8. Print the selected events in chronological order (oldest to newest within
   the selected window), one JSON object per line.

The audit event is part of the event stream. If it matches the supplied
filters and falls within the selected tail window, it appears in the output
like any other event. Implementations must not special-case it out of the
tail result.

## Output Schema

Each output row is one UTF-8 JSON object followed by a single `\n` (LF) byte.
No wrapping array. No trailing comma. No `\r\n`. Output is written to stdout.

```json
{
  "id": "evt_001",
  "ts": "2026-05-25T15:00:00Z",
  "kind": "object.created",
  "payload": {},
  "parent_id": null
}
```

Required fields:

- `id`: string. The event id exactly as stored.
- `ts`: string. The event timestamp exactly as stored.
- `kind`: string. The event type/kind exactly as stored.
- `payload`: object. The event payload exactly as stored, encoded with the
  repository's normal JSON-safe event serializer rules.
- `parent_id`: string or null. The causal parent id for the event. This maps
  to `Event.caused_by` on the existing dataclass. It is `null` for events
  that have no causal parent (root-of-chain events).

No other top-level fields are part of the T6 contract. Future additions
require a spec amendment.

## Error Modes

### No Store

If there is no active event store, the command must fail before printing
rows. It must write a clear stderr message containing the substring
`no active event store` and exit with the CLI's generic error code `1`.

Because there is no store, no `events_tail_invoked` event can be emitted in
this mode.

### Empty Store

If the active event store contains no events before invocation, the command
still emits `events_tail_invoked`. The output then contains that audit event
when it passes the active filters and falls within the selected tail window.
If caller-supplied filters exclude the audit event, the command exits `0`
and prints nothing.

An empty result set is not an error.

### Malformed Flags

Malformed CLI inputs are usage errors and must exit with code `2`.

Malformed inputs include:

- `--n` missing a value.
- `--n` not parseable as an integer.
- `--n` less than `0`.
- `--since` missing a value.
- `--since` not parseable as an ISO 8601 timestamp.
- `--filter` missing a value.
- Unknown options or unexpected positional arguments.

Malformed flags must be rejected before `events_tail_invoked` is emitted and
before any read from the store.

### Unknown Filter

`--filter` is a literal substring filter over event kind. It does not name a
registry, event namespace, or query language. A substring that matches no
events is therefore an empty result, not an error.

For an unknown/non-matching filter, the command exits `0` and prints no rows
unless the `events_tail_invoked` audit event itself contains the substring
and falls within the selected tail window.

### Exit Code Summary

| Code | Meaning |
|------|---------|
| `0`  | Success. Audit event emitted (when a store exists). Zero or more rows printed. |
| `1`  | Runtime error. No active event store. Stderr explains. |
| `2`  | Usage error. Malformed flags. Stderr explains. |

## Auditability

Every successful invocation must append exactly one audit event before
reading and printing the tail:

```json
{
  "type": "events_tail_invoked",
  "payload": {
    "n": 20,
    "since": null,
    "filter": null,
    "json": false
  }
}
```

The payload must record the effective flag values after defaults are applied:

- `n`: integer.
- `since`: string or null, preserving the caller's accepted ISO timestamp text.
- `filter`: string or null.
- `json`: boolean.

The emitted event must use the repository's normal event id, timestamp,
actor, frame, and causal-link machinery. It must be appended through the
active store's normal event append path, not written through a side channel.
The actor and frame attribution must be the same the CLI uses for any other
CLI-originated event so that downstream consumers can correlate `events tail`
invocations with the operator session that produced them.

## Non-Goals

- No tests are specified in this document.
- No implementation is included in this document.
- No new event store indexing or query API is required.
- No pretty/table output is required.
- No streaming/follow (`-f`) behavior is required in T6.
