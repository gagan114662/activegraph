# Tail Events

Use `activegraph events tail` to inspect the active run's event log from the
command line. The command prints newline-delimited JSON: one event object per
line, with no wrapping array.

## Synopsis

```bash
activegraph events tail [--n <int>] [--since <iso-timestamp>] [--filter <substring>] [--json]
```

Flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--n <int>` | `20` | Print the last N matching events. Must be `>= 0`; `--n 0` is legal and prints zero rows. |
| `--since <iso-timestamp>` | unset | Include only events whose timestamp is `>=` the supplied ISO 8601 timestamp. Must include a timezone offset (e.g. `Z` or `+00:00`). |
| `--filter <substring>` | unset | Include only events whose `kind` contains the literal substring. Match is case-sensitive. |
| `--json` | off | Reserved for forward compatibility with future non-JSON output modes. Output is always NDJSON today; the flag does not change the row schema. |

## Environment

The command reads the active event store from environment variables:

- `ACTIVEGRAPH_STORE_URL` — event store URL, such as `sqlite:////tmp/activegraph.sqlite`.
- `ACTIVEGRAPH_RUN_ID` — run id inside that store.

`ACTIVEGRAPH_RUN_ID` may be omitted if the backing store can resolve the most
recent run id on its own. If neither the URL nor a resolvable run can be
found, the command exits `1` and writes a message containing
`no active event store` to stderr.

## Examples

Print the default tail of the active run:

```bash
ACTIVEGRAPH_STORE_URL=sqlite:////tmp/activegraph.sqlite \
ACTIVEGRAPH_RUN_ID=run_123 \
activegraph events tail
```

Limit output to the last five matching events:

```bash
activegraph events tail --n 5
```

Print events at or after an ISO timestamp:

```bash
activegraph events tail --since 2026-05-25T15:00:00Z
```

Filter by a literal substring on the event kind:

```bash
activegraph events tail --filter object.created
```

Use `--json` for consistency with other CLI commands. For this command the
output is always newline-delimited JSON, so `--json` does not change the row
shape:

```bash
activegraph events tail --json
```

## Output Schema

Each output row is one UTF-8 JSON object followed by a single LF byte. There
is no wrapping array, no trailing comma, and no CRLF. The keys are:

| Key | Type | Description |
|-----|------|-------------|
| `id` | string | Event id, as stored. |
| `ts` | string | Event timestamp, as stored. |
| `kind` | string | Event type/kind, as stored. |
| `payload` | object | Event payload, JSON-safe. |
| `parent_id` | string \| null | Causal parent id (maps to `Event.caused_by`); `null` for root-of-chain events. |

Example row:

```json
{"id":"evt_001","ts":"2026-05-25T15:00:00Z","kind":"object.created","payload":{},"parent_id":null}
```

## Audit Event

Every successful invocation appends exactly one `events_tail_invoked` audit
event to the active store **before** reading and printing the tail. The
audit event records the effective flag values after defaults are applied,
and it preserves the caller's accepted `--since` text verbatim:

```json
{
  "kind": "events_tail_invoked",
  "payload": {"n": 20, "since": null, "filter": null, "json": false}
}
```

The audit event is a normal entry in the event stream. If it matches the
caller-supplied `--since` and `--filter` and falls inside the selected tail
window, it appears in the output like any other event; the command does
not special-case it out of the result.

The audit event is appended through the store's normal event-append path
and uses the CLI's standard actor and frame attribution, so downstream
consumers can correlate `events tail` invocations with the operator
session that produced them.

## Failure and Usage Notes

### No active event store

If no active event store can be resolved (the URL is unset, the run id
cannot be resolved, or the store cannot be opened), the command exits
with code `1` and writes a stderr message containing
`no active event store`. No audit event is appended in this mode.

### Malformed flags

Malformed CLI inputs are usage errors and exit with code `2`. Examples:

- `--n` missing a value, non-integer, or negative.
- `--since` missing a value, or not a timezone-aware ISO 8601 timestamp.
- `--filter` missing a value.
- Unknown options or unexpected positional arguments.

Usage errors are rejected before the `events_tail_invoked` audit event is
appended and before any read from the store, so a malformed invocation
leaves the event log untouched.

### Empty store

If the active store contains no events before invocation, the command
still appends `events_tail_invoked`. The output then contains that audit
event when it passes the active filters and falls within the selected
tail window. An empty result set is not an error.

### Unknown filter

`--filter` is a literal substring match over event kind; it does not name
a registry or query language. A substring that matches no stored events
exits `0` and prints no rows, unless the `events_tail_invoked` audit event
itself contains the substring and falls within the tail window.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success. Audit event appended (when a store exists). Zero or more rows printed. |
| `1` | Runtime error. No active event store; stderr explains. |
| `2` | Usage error. Malformed flags; stderr explains. |
