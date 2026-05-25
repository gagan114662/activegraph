# events tail CLI Contract

\`activegraph events tail\` prints the most recent events from an event store as newline-delimited JSON.

## Command

\`\`\`bash
activegraph events tail <store-url> --run-id <run-id> [--n <int>] [--since <iso-timestamp>] [--filter <substring>] [--json]
\`\`\`

## Output Schema

Each line is a JSON object with at least:

- \`id\`: event id
- \`ts\`: event timestamp
- \`kind\`: event type
- \`payload\`: event payload object
- \`parent_id\`: causal parent id, or \`null\`

## Error Modes

- No store: exit non-zero with a diagnostic naming the missing store.
- Empty store: print no event lines and still emit the invocation audit event.
- Malformed flags: return the CLI usage error.
- Unknown filter: print no matching event lines and still emit the invocation audit event.

## Auditability

Every invocation emits an \`events_tail_invoked\` event into the same event store. The emitted event payload records the requested count, since filter, substring filter, and number of events printed.
