# T6 Extra-Hard: Activegraph Events Tail

## Scope

Add a CLI subcommand that prints the last events from the active event store as
newline-delimited JSON. This is a read-only operator view over the current
event log, except for the required audit event emitted by the command itself.

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
- `--since <iso-timestamp>` includes only events whose timestamp is greater
  than or equal to the supplied ISO timestamp.
- `--filter <substring>` includes only events whose event kind contains the
  literal substring.
- `--json` selects the machine-readable output mode. For this subcommand,
  output is always newline-delimited JSON; `--json` is accepted for consistency
  with existing CLI selectors and must not change the row schema.

Selection order:

1. Resolve the active event store.
2. Emit the `events_tail_invoked` audit event to that store.
3. Read events from the store in append order.
4. Apply `--since` if present.
5. Apply `--filter` if present.
6. Select the last `--n` matching events.
7. Print one JSON object per selected event, one object per line, with no
   wrapping array.

The audit event is part of the event stream. If it matches the supplied filters
and falls within the selected tail window, it may appear in the output like any
other event. Implementations must not special-case it out of the tail result.

## Output Schema

Each output row is one UTF-8 JSON object followed by `\n`.

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
- `parent_id`: string or null. The causal parent id for the event. For the
  existing `Event` dataclass this maps to `caused_by`.

No other top-level fields are part of the T6 contract. Future additions require
a spec amendment.

## Error Modes

### No Store

If there is no active event store, the command must fail before printing rows.
It must write a clear stderr message containing `no active event store` and exit
with the CLI's generic error code `1`.

Because there is no store, no `events_tail_invoked` event can be emitted in this
mode.

### Empty Store

If the active event store contains no events before invocation, the command
still emits `events_tail_invoked`. The output then contains that audit event
when it passes the active filters and tail window. If caller-supplied filters
exclude the audit event, the command exits `0` and prints nothing.

An empty result set is not an error.

### Malformed Flags

Malformed CLI inputs are usage errors and must exit with code `2`.

Malformed inputs include:

- `--n` missing a value.
- `--n` not parseable as an integer.
- `--n` less than `0`.
- `--since` missing a value.
- `--since` not parseable as an ISO timestamp.
- Unknown options or unexpected positional arguments.

Malformed flags must be rejected before `events_tail_invoked` is emitted.

### Unknown Filter

`--filter` is a literal substring filter over event kind. It does not name a
registry, event namespace, or query language. A substring that matches no events
is therefore an empty result, not an error.

For an unknown/non-matching filter, the command exits `0` and prints no rows
unless the `events_tail_invoked` audit event itself contains the substring and
falls within the selected tail window.

## Auditability

Every successful invocation must append one audit event before reading and
printing the tail:

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

The emitted event must use the repository's normal event id, timestamp, actor,
frame, and causal-link machinery. It must be appended through the active store's
normal event append path, not written through a side channel.

## Non-Goals

- No tests are specified in this document.
- No implementation is included in this document.
- No new event store indexing or query API is required.
- No pretty/table output is required.
