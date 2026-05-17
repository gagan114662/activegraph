# CorruptedEventPayloadError

A stored event's payload bytes don't parse as JSON. The framework
refuses to silently skip the row — that would make the replay
contract unverifiable, and the next fork or diff would lie about
what happened. The fix is recovery (partial migration that skips the
corrupt rows) or repair (manual edit of the offending row, if you
have the original payload elsewhere).

This is distinct from
[`NonSerializableEventError`](non-serializable-event-error.md), which
fires at *encode time* when a Python value can't be made into JSON.
Corrupted payload fires at *decode time* when the bytes on disk
can't be made into a Python value.

## Quick fix

```bash
# Recover the readable subset of the run. The destination run is
# partial — corrupted events are skipped, the rest are migrated.
# The skipped event ids appear in the per-run report.
activegraph migrate --from <src> --to <new-dst> --skip-corrupted

# To see surrounding events before deciding:
activegraph inspect <store> --tail 50
```

The `--skip-corrupted` flag walks the run row-by-row, decoding each
event individually. Rows that fail JSON decode are recorded in
`skipped_events` on the per-run report. Rows around the corruption
that decode cleanly migrate to the destination.

If you have the original payload elsewhere (a previous run, a
backup, a log), open the source store directly with `sqlite3` or
`psql` and repair the row in place — preferable to skip-and-lose
when the data is recoverable.

If the corruption is intrinsic and the run isn't worth recovering,
re-run from the original goal in a fresh store. The store is
append-only; partial corruption does not propagate backward in time.

## How to diagnose

The error message body shows the parser's error location and a
preview of the corrupted payload:

```
What failed:
  While reading a stored event payload, the JSON parser failed at
  line 1, column 24:
    Expecting value
    payload preview: '{"goal": "x", "broken":'
```

`column` is the position in the corrupted JSON where the parser
gave up. `preview` is the first 64 bytes of the row's payload column.

From Python:

```python
try:
    rt = Runtime.load(url, run_id=run_id)
except CorruptedEventPayloadError as e:
    print(e.context["line"], e.context["column"])
    print(e.context["preview"])
    print(e.context["underlying_msg"])
```

To see which event id failed, look at the events near the failure
point with `activegraph inspect <store> --tail 50` — the corrupted
row will be the one immediately after the last readable event.

## When does this fire

At load time, whenever the store reads a row whose payload column
doesn't parse as JSON. `Runtime.load`, `iter_events`,
`activegraph inspect`, and `activegraph migrate` all trigger this if
they hit a bad row. `activegraph migrate --skip-corrupted` is the
only operation that catches the error per-row and continues; every
other operation propagates it.

## Why the framework refuses to continue

The store persists every event payload as JSON so the audit trail
is human-inspectable and round-trips through any JSON-aware tool. A
row that doesn't parse means either the bytes on disk are corrupted,
the store schema is mismatched (someone wrote a non-JSON format
here), or an out-of-band edit damaged the file. Silently skipping
the row would make the replay contract unverifiable — the next fork
or diff would behave as if the event never happened, and the
audit trail wouldn't record that anything went wrong.

See [`failure-model`](../../concepts/failure-model.md) for the
broader principle.

## What's related

- [`NonSerializableEventError`](non-serializable-event-error.md) —
  the encode-time sibling. Fires when a Python value can't be
  written to JSON in the first place.
- [`SchemaVersionMismatch`](schema-version-mismatch.md) — fires when
  the store opens cleanly but the schema_version meta row doesn't
  match this build. Distinct from corruption.
- `activegraph migrate --skip-corrupted` in the [CLI reference](../cli/).
