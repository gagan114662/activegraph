# Tail Events

Use `activegraph events tail` to inspect the active run's event log from the
command line. The command prints newline-delimited JSON: one event object per
line, with no wrapping array.

## Synopsis

```bash
activegraph events tail [--n <int>] [--since <iso-timestamp>] [--filter <substring>] [--json]
```

The command reads the active event store selected by environment variables:

- `ACTIVEGRAPH_STORE_URL`: event store URL, such as `sqlite:////tmp/run.db`.
- `ACTIVEGRAPH_RUN_ID`: run id inside that store.

`ACTIVEGRAPH_RUN_ID` may be omitted for stores that can resolve the most recent
run. If no active store can be resolved, the command exits with code `1` and
prints a message containing `no active event store`.

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

Filter by a literal substring in the event kind:

```bash
activegraph events tail --filter object.created
```

Use `--json` for consistency with other CLI commands. For this command, output
is always newline-delimited JSON, so `--json` does not change the row shape:

```bash
activegraph events tail --json
```

Each output row has this shape:

```json
{"id":"evt_001","ts":"2026-05-25T15:00:00Z","kind":"object.created","payload":{},"parent_id":null}
```

## Audit Event

Every successful invocation appends an `events_tail_invoked` audit event before
reading and printing the tail. The audit event records the effective values of
`--n`, `--since`, `--filter`, and `--json`.

The audit event is part of the event stream. If it matches the active filters
and falls inside the selected tail window, it can appear in the command output.

## Usage Notes

Malformed flags are usage errors and exit with code `2`. Examples include a
missing `--n` value, a non-integer or negative `--n`, a missing `--since` value,
a `--since` value that is not an ISO timestamp with timezone, unknown options,
or unexpected positional arguments. Usage errors are rejected before the
`events_tail_invoked` audit event is appended.

`--filter` is a literal substring match over the event kind. A filter that
matches no events exits `0` and prints no rows, unless the audit event itself
matches the filter.
