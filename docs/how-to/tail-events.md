# Tail Events

Use `activegraph events tail` when you need a compact audit readout from a run.

## Print Recent Events

\`\`\`bash
activegraph events tail sqlite:/tmp/activegraph.db --run-id run_001 --n 5 --json
\`\`\`

The command writes one JSON object per line. Each object includes `id`, `ts`, `kind`, `payload`, and `parent_id`.

## Filter Events

Use `--since` to keep only newer events and `--filter` to keep rows whose JSON contains a substring.

\`\`\`bash
activegraph events tail sqlite:/tmp/activegraph.db --run-id run_001 --since 2026-05-25T00:00:00Z --filter approval --json
\`\`\`

Every invocation emits an `events_tail_invoked` event so the audit log records that it was inspected.
